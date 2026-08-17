"""Motor de risco: ponte entre `copilot.quant` (deterministico) e o banco.

Nenhum LLM neste caminho. Todo resultado vira linha em `risk_results` ou
`scenario_results` com `inputs_json`, `outputs_json`, metodologia e `evidence_id`.

Regra de proxy: se a curva de marcacao nao for `NEGOCIADA`, o add-on de proxy e
aplicado e aparece no consumo do limite. PLD/CMO usados como referencia sao o
caso mais caro, de proposito.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from copilot.common.enums import CurveOrigin, DataQuality, HydroScenario, Side, Submarket
from copilot.common.errors import InsufficientSampleError, MissingDataError
from copilot.quant.addons import AddOnBundle, build_addons
from copilot.quant.limits import check_var_limit
from copilot.quant.periods import DeliveryPeriod
from copilot.quant.pnl import PositionSpec, portfolio_pnl, position_pnl
from copilot.quant.scenarios import STANDARD_SCENARIOS, run_scenarios
from copilot.quant.var import (
    DEFAULT_CONFIDENCE,
    DEFAULT_HORIZON_DAYS,
    ewma_var,
    ewma_volatility,
    historical_var,
    log_returns,
    parametric_var,
    portfolio_parametric_var,
    sample_volatility,
)
from src.database import repositories as R

INSUFFICIENT_MSG = "Dados insuficientes para cálculo confiável."

_ORIGIN_MAP = {
    "NEGOCIADA": CurveOrigin.NEGOCIADA,
    "PROXY_SPOT": CurveOrigin.PROXY_SPOT,
    "PROXY_MODELO": CurveOrigin.PROXY_MODELO,
    "INTERNA": CurveOrigin.INTERNA,
}
_QUALITY_MAP = {
    "observado": DataQuality.OK, "negociado": DataQuality.OK,
    "projetado": DataQuality.ESTIMADO, "indicativo": DataQuality.ESTIMADO,
    "proxy": DataQuality.PROXY, "manual": DataQuality.ESTIMADO,
    "demonstracao": DataQuality.PROXY,
}


def var_limit(conn: sqlite3.Connection) -> Decimal:
    linha = conn.execute(
        "SELECT limit_value FROM risk_limits WHERE name='VAR_MESA'"
    ).fetchone()
    return Decimal(linha["limit_value"]) if linha else Decimal("50000000.00")


def _position_specs(conn: sqlite3.Connection, thesis_id: str) -> list[PositionSpec]:
    especificacoes = []
    for linha in conn.execute(
        "SELECT * FROM positions WHERE thesis_id = ?", (thesis_id,)
    ).fetchall():
        especificacoes.append(PositionSpec(
            position_id=linha["id"],
            side=Side.LONG if linha["side"] == "COMPRADO" else Side.SHORT,
            volume_mwmed=Decimal(linha["volume_mwm"]),
            price_contract=Decimal(linha["price_entry"]),
            period=DeliveryPeriod(date.fromisoformat(linha["delivery_start"]),
                                  date.fromisoformat(linha["delivery_end"])),
            submarket=Submarket(linha["submarket"]) if linha["submarket"] in
                      [s.value for s in Submarket] else Submarket.SE_CO,
            metric_key=linha["metric_key"],
            instrument=linha["instrument"],
        ))
    return especificacoes


def price_series(conn: sqlite3.Connection, metric: str, *, as_of: str
                 ) -> list[tuple[date, Decimal]]:
    """Serie de precos ate a data-base, para estimar volatilidade."""
    return [
        (date.fromisoformat(r["ref_date"]), Decimal(r["value"]))
        for r in R.metric_history(conn, metric, as_of=as_of)
    ]


def compute_pnl(conn: sqlite3.Connection, thesis_id: str, *,
                prices: dict[str, Decimal], as_of: str) -> dict[str, Any]:
    """P&L comprado e vendido. Preco ausente interrompe — nunca vira zero."""
    posicoes = _position_specs(conn, thesis_id)
    if not posicoes:
        raise MissingDataError("Tese sem posicao cadastrada: nao ha P&L a calcular.")
    resultado = portfolio_pnl(posicoes, prices)
    return {
        "total_pnl": resultado.total_pnl_brl,
        "gross_notional": resultado.gross_notional_brl,
        "net_exposure": resultado.net_exposure_brl,
        "gross_exposure": resultado.gross_exposure_brl,
        "positions": [
            {"position_id": d.position_id, "side": d.side.value, "hours": d.hours,
             "volume_mwh": str(d.volume_mwh), "price_contract": str(d.price_contract),
             "price_market": str(d.price_market), "pnl": str(d.pnl_brl),
             "signed_exposure": str(d.signed_exposure_brl)}
            for d in resultado.positions
        ],
    }


def compute_risk(
    conn: sqlite3.Connection,
    thesis_id: str,
    *,
    as_of: str,
    prices: dict[str, Decimal],
    curve_origin: str = "NEGOCIADA",
    curve_classification: str = "negociado",
    vol_metric: str | None = None,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    market_adv_mwmed: Decimal | None = None,
    basis_vol_daily: float | None = None,
    basis_correlation: float | None = None,
    actor: str = "sistema",
) -> dict[str, Any]:
    """VaR paramétrico + EWMA + histórico + add-ons + consumo do limite.

    `vol_metric` e a serie usada para estimar volatilidade. Se for uma serie de
    PLD/CMO servindo de proxy para a curva, isso e declarado no resultado e
    penalizado pelo add-on — nunca silencioso.
    """
    posicoes = _position_specs(conn, thesis_id)
    if not posicoes:
        raise MissingDataError("Tese sem posicao cadastrada.")

    pnl = compute_pnl(conn, thesis_id, prices=prices, as_of=as_of)
    exposicao_bruta = pnl["gross_exposure"]
    exposicoes = {
        p["position_id"]: Decimal(p["signed_exposure"]) for p in pnl["positions"]
    }

    metrica = vol_metric or posicoes[0].metric_key
    serie = price_series(conn, metrica, as_of=as_of)
    avisos: list[str] = []
    proxy_de_volatilidade = metrica != posicoes[0].metric_key or curve_origin != "NEGOCIADA"

    try:
        retornos = log_returns(serie, metric_key=metrica)
    except (InsufficientSampleError, MissingDataError) as exc:
        return {"ok": False, "message": INSUFFICIENT_MSG, "detail": str(exc),
                "metric": metrica, "sample": len(serie)}

    try:
        sigma = sample_volatility(retornos.returns)
    except InsufficientSampleError as exc:
        return {"ok": False, "message": INSUFFICIENT_MSG, "detail": str(exc),
                "metric": metrica, "sample": len(retornos)}

    if proxy_de_volatilidade:
        avisos.append(
            f"Volatilidade estimada de `{metrica}` usada como PROXY da curva "
            f"(origem {curve_origin}). Add-on de risco de modelo aplicado."
        )

    parametrico = parametric_var(exposicao_bruta, sigma, confidence=confidence,
                                 horizon_days=horizon_days, sample_size=len(retornos))
    try:
        ewma = ewma_var(exposicao_bruta, retornos.returns, confidence=confidence,
                        horizon_days=horizon_days)
        sigma_ewma = ewma.sigma_daily
    except InsufficientSampleError:
        ewma, sigma_ewma = None, None
        avisos.append("EWMA nao calculado: amostra insuficiente.")

    try:
        historico = historical_var(exposicao_bruta, retornos.returns,
                                   confidence=confidence, horizon_days=horizon_days)
    except InsufficientSampleError as exc:
        historico = None
        avisos.append(f"VaR historico nao calculado: {exc}")

    if len(exposicoes) > 1:
        sigmas = {k: sigma for k in exposicoes}
        portfolio = portfolio_parametric_var(exposicoes, sigmas, confidence=confidence,
                                             horizon_days=horizon_days)
    else:
        portfolio = None

    # O VaR de mercado adotado e o mais conservador entre os disponiveis.
    candidatos = [parametrico.var_brl]
    if ewma:
        candidatos.append(ewma.var_brl)
    if historico:
        candidatos.append(historico.var_brl)
    var_mercado = max(candidatos)

    volume_total = sum((Decimal(p.volume_mwmed) for p in posicoes), Decimal("0"))
    addons = build_addons(
        var_market_brl=var_mercado,
        gross_exposure_brl=exposicao_bruta,
        position_mwmed=volume_total if market_adv_mwmed else None,
        market_adv_mwmed=market_adv_mwmed,
        basis_vol_daily=basis_vol_daily,
        basis_correlation=basis_correlation,
        curve_origin=_ORIGIN_MAP.get(curve_origin, CurveOrigin.PROXY_MODELO),
        quality=_QUALITY_MAP.get(curve_classification, DataQuality.PROXY),
        confidence=confidence,
        horizon_days=horizon_days,
    )
    limite = check_var_limit(var_mercado, addons=addons, limit_brl=var_limit(conn))

    metodologia = (
        f"VaR {float(confidence):.0%} / {horizon_days}d uteis. Volatilidade amostral "
        f"de log-retornos de `{metrica}` (n={len(retornos)}); raiz do tempo. "
        f"VaR de mercado = maximo entre parametrico, EWMA e historico. "
        f"Add-ons: liquidez, basis, proxy e risco de modelo. "
        f"Origem da curva: {curve_origin}."
    )
    entradas = {
        "thesis_id": thesis_id, "as_of": as_of, "metric": metrica,
        "confidence": str(confidence), "horizon_days": horizon_days,
        "gross_exposure": str(exposicao_bruta), "sample": len(retornos),
        "curve_origin": curve_origin, "prices": {k: str(v) for k, v in prices.items()},
    }
    saidas = {
        "var_parametric": str(parametrico.var_brl),
        "var_ewma": str(ewma.var_brl) if ewma else None,
        "var_historical": str(historico.var_brl) if historico else None,
        "var_portfolio": str(portfolio.var_brl) if portfolio else None,
        "var_market": str(var_mercado),
        "addons_total": str(addons.total_brl),
        "addons": addons.explain(),
        "var_total": str(limite.var_total_brl),
        "utilization": str(limite.utilization),
        "within_limit": limite.within_limit,
        "headroom": str(limite.headroom_brl),
        "expected_shortfall": str(parametrico.expected_shortfall_brl),
        "sigma_daily": sigma, "sigma_ewma": sigma_ewma,
        "pnl": pnl, "warnings": avisos,
    }

    eid = R.create_evidence(
        conn, kind="CALCULO", source_name="Motor quantitativo (Python)",
        locator=f"risk:{thesis_id}@{as_of}",
        excerpt=(f"VaR total R$ {limite.var_total_brl} ({limite.utilization:.2%} do limite "
                 f"de R$ {limite.limit_brl}). {metodologia}"),
        value=limite.var_total_brl, unit="R$", as_of=as_of, classification="projetado",
    )
    rid = R.new_id()
    conn.execute(
        "INSERT INTO risk_results (id, thesis_id, method, var_market, addons_total, var_total, "
        "limit_value, utilization, within_limit, expected_shortfall, confidence, horizon_days, "
        "sample_size, sigma_daily, inputs_json, outputs_json, methodology, as_of, evidence_id, "
        "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, thesis_id, "var_parametric", str(var_mercado), str(addons.total_brl),
         str(limite.var_total_brl), str(limite.limit_brl), str(limite.utilization),
         1 if limite.within_limit else 0, str(parametrico.expected_shortfall_brl),
         str(confidence), horizon_days, len(retornos), repr(sigma),
         json.dumps(entradas, ensure_ascii=False), json.dumps(saidas, ensure_ascii=False, default=str),
         metodologia, as_of, eid, R.now_iso()),
    )
    R.audit(conn, action="QUANT_RUN", entity="risco", entity_id=rid, actor=actor,
            tool="quant.var", input_data=entradas, output_data={"var_total": str(limite.var_total_brl)},
            evidence_ids=[eid], as_of=as_of)

    return {"ok": True, "risk_result_id": rid, "evidence_id": eid,
            "methodology": metodologia, **saidas, "limit_message": limite.message}


def compute_scenarios(
    conn: sqlite3.Connection, thesis_id: str, *, as_of: str,
    base_prices: dict[str, Decimal], sigma_daily: float, actor: str = "sistema",
) -> list[dict[str, Any]]:
    """Cenarios seco, base, umido e extremo. Minimo de dois hidrologicos (RF-53)."""
    posicoes = _position_specs(conn, thesis_id)
    if not posicoes:
        raise MissingDataError("Tese sem posicao cadastrada.")
    sigmas = {p.metric_key: sigma_daily for p in posicoes}
    matriz = run_scenarios(posicoes, base_prices, sigma_daily=sigmas)

    saida = []
    for resultado in matriz.outcomes:
        eid = R.create_evidence(
            conn, kind="CALCULO", source_name="Motor quantitativo (Python)",
            locator=f"scenario:{thesis_id}:{resultado.scenario.value}@{as_of}",
            excerpt=(f"Cenario {resultado.scenario.value}: P&L R$ {resultado.pnl_brl}, "
                     f"VaR R$ {resultado.var_brl}. {resultado.description}"),
            value=resultado.pnl_brl, unit="R$", as_of=as_of, classification="projetado",
        )
        R.upsert_row(
            conn, table="scenario_results",
            columns=("id", "thesis_id", "scenario", "is_stress", "probability", "shocked_price",
                     "pnl", "var_impact", "thesis_delta", "as_of", "evidence_id", "created_at"),
            values=(R.new_id(), thesis_id, resultado.scenario.value, 1 if resultado.is_stress else 0,
                    str(resultado.probability),
                    str(list(resultado.shocked_prices.values())[0]) if resultado.shocked_prices else None,
                    str(resultado.pnl_brl), str(resultado.var_delta_brl), resultado.thesis_delta,
                    as_of, eid, R.now_iso()),
            conflict_cols=("thesis_id", "scenario", "as_of"),
        )
        saida.append({
            "scenario": resultado.scenario.value, "is_stress": resultado.is_stress,
            "probability": str(resultado.probability), "pnl": str(resultado.pnl_brl),
            "var": str(resultado.var_brl), "var_delta": str(resultado.var_delta_brl),
            "thesis_delta": resultado.thesis_delta, "description": resultado.description,
            "shocked_prices": {k: str(v) for k, v in resultado.shocked_prices.items()},
            "evidence_id": eid,
        })
    R.audit(conn, action="QUANT_RUN", entity="cenarios", entity_id=thesis_id, actor=actor,
            tool="quant.scenarios", output_data={"n": len(saida),
            "expected_pnl": str(matriz.expected_pnl_brl)}, as_of=as_of)
    return saida


def latest_risk(conn: sqlite3.Connection, thesis_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM risk_results WHERE thesis_id=? ORDER BY created_at DESC LIMIT 1",
        (thesis_id,),
    ).fetchone()


def npv_to_year_end(
    pnl: Decimal, *, as_of: str, annual_rate: Decimal = Decimal("0.10"),
    year_end: str | None = None,
) -> dict[str, str]:
    """Valor presente do resultado ate 31/12 — meta de margem/VPL do case.

    Desconto simples pro rata dias. Taxa e premissa declarada, configuravel.
    """
    inicio = date.fromisoformat(as_of)
    fim = date.fromisoformat(year_end) if year_end else date(inicio.year, 12, 31)
    dias = max(0, (fim - inicio).days)
    fator = Decimal(1) + Decimal(annual_rate) * Decimal(dias) / Decimal(365)
    vp = (Decimal(pnl) / fator).quantize(Decimal("0.01"))
    return {"pnl_nominal": str(Decimal(pnl).quantize(Decimal("0.01"))),
            "days_to_year_end": str(dias), "annual_rate": str(annual_rate),
            "discount_factor": str(fator.quantize(Decimal("0.000001"))), "npv": str(vp)}


__all__ = [
    "INSUFFICIENT_MSG", "compute_pnl", "compute_risk", "compute_scenarios",
    "latest_risk", "npv_to_year_end", "price_series", "var_limit",
]
