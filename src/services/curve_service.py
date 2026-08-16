"""Curva pública de cenário estatístico — P10/P50/P90 sobre histórico de PLD.

Cobre a seção 13 do prompt de integrações: quando não há curva forward de
mercado acessível (BBCE exige assinatura, B3/N5X sem endpoint público
verificado — ver `docs/CONEXOES_DADOS_SETOR.md`), o MVP continua funcional com
uma curva de cenário derivada de dado público real (PLD histórico da CCEE/
observações manuais), sempre identificada como estimativa e nunca como preço
negociado.

Regra dura, testada: sem no mínimo `MIN_ANNUAL_OBSERVATIONS` (3) anos de
histórico para o mesmo mês-calendário, o ponto correspondente do horizonte
fica `INSUFFICIENT_DATA` — nunca interpolado, nunca preenchido a partir de
outro mês.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from src.database import repositories as R

MIN_ANNUAL_OBSERVATIONS = 3
CURVE_NAME = "cenario_estatistico_pld_mensal"
CURVE_CATEGORY = "STATISTICAL_SCENARIO_PUBLIC"
QUOTE_TYPES = ("P10", "P50", "P90")

DISCLAIMER = (
    "Cenário estatístico baseado no histórico público de PLD. Não representa "
    "cotação negociada, recomendação de compra ou venda, nem curva forward de "
    "mercado."
)


@dataclass(frozen=True, slots=True)
class ScenarioPoint:
    horizon_label: str
    target_month: date
    p10: Decimal | None
    p50: Decimal | None
    p90: Decimal | None
    n_observations: int
    status: str  # "OK" | "INSUFFICIENT_DATA"


def _add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + offset
    return total // 12, (total % 12) + 1


def _percentile(sorted_values: list[Decimal], pct: float) -> Decimal:
    """Percentil por interpolação linear. Amostra deve vir ordenada."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    posicao = (len(sorted_values) - 1) * pct
    piso = int(posicao)
    teto = min(piso + 1, len(sorted_values) - 1)
    if piso == teto:
        return sorted_values[piso]
    peso = Decimal(str(posicao - piso))
    return sorted_values[piso] + (sorted_values[teto] - sorted_values[piso]) * peso


def _monthly_average(rows: list[sqlite3.Row]) -> dict[tuple[int, int], Decimal]:
    """(ano, mês) -> média das observações do mês. Junta granularidades diferentes
    (horária/diária/semanal/mensal) num único ponto mensal, sem gerar viés de
    contagem: cada linha de PLD entra com peso igual antes da média."""
    baldes: dict[tuple[int, int], list[Decimal]] = {}
    for linha in rows:
        referencia = date.fromisoformat(str(linha["ref_date"]))
        chave = (referencia.year, referencia.month)
        baldes.setdefault(chave, []).append(Decimal(str(linha["value"])))
    return {chave: sum(valores) / len(valores) for chave, valores in baldes.items()}


def compute_statistical_scenario(
    conn: sqlite3.Connection,
    *,
    as_of: str,
    submarket: str,
    metric_like: str = "pld_%",
    min_years: int = MIN_ANNUAL_OBSERVATIONS,
) -> dict[str, Any]:
    """Calcula P10/P50/P90 de M+1 a M+12 a partir do histórico de PLD.

    Nunca olha além de `as_of` (RF-58): tanto o histórico usado na estimativa
    quanto o mês mais recente de referência respeitam o corte.
    """
    referencia = date.fromisoformat(as_of)
    linhas = conn.execute(
        "SELECT ref_date, value FROM market_observations "
        "WHERE metric LIKE ? AND submarket = ? AND as_of <= ? AND ref_date <= ? "
        "ORDER BY ref_date",
        (metric_like, submarket, as_of, as_of),
    ).fetchall()

    resultado_base: dict[str, Any] = {
        "submarket": submarket,
        "as_of": as_of,
        "methodology": (
            f"Percentis (P10/P50/P90) do PLD mensal histórico por mês-calendário, "
            f"mínimo {min_years} anos de observação por ponto, interpolação linear."
        ),
        "disclaimer": DISCLAIMER,
        "points": [],
    }

    mensal = _monthly_average(linhas)
    if not mensal:
        return {
            **resultado_base,
            "status": "INSUFFICIENT_DATA",
            "historical_period": None,
            "last_observation": None,
            "message": "Sem histórico de PLD para este submercado até a data-base.",
        }

    pontos: list[ScenarioPoint] = []
    for horizonte in range(1, 13):
        ano_alvo, mes_alvo = _add_months(referencia.year, referencia.month, horizonte)
        amostras = sorted(
            valor
            for (ano, mes), valor in mensal.items()
            if mes == mes_alvo and (ano, mes) < (referencia.year, referencia.month)
        )
        rotulo = f"M+{horizonte}"
        alvo = date(ano_alvo, mes_alvo, 1)
        if len(amostras) < min_years:
            pontos.append(ScenarioPoint(rotulo, alvo, None, None, None, len(amostras), "INSUFFICIENT_DATA"))
            continue
        pontos.append(
            ScenarioPoint(
                rotulo, alvo,
                _percentile(amostras, 0.10), _percentile(amostras, 0.50), _percentile(amostras, 0.90),
                len(amostras), "OK",
            )
        )

    anos = sorted({ano for ano, _ in mensal})
    return {
        **resultado_base,
        "status": "OK" if any(p.status == "OK" for p in pontos) else "INSUFFICIENT_DATA",
        "historical_period": f"{anos[0]}-{anos[-1]}" if anos else None,
        "last_observation": max((str(l["ref_date"]) for l in linhas), default=None),
        "points": pontos,
    }


def persist_statistical_scenario(
    conn: sqlite3.Connection, resultado: dict[str, Any], *, as_of: str
) -> dict[str, str]:
    """Grava os três cabeçalhos de curva (P10/P50/P90) e seus pontos válidos.

    Pontos `INSUFFICIENT_DATA` nunca são gravados — a ausência fica visível na
    UI como lacuna, não como zero disfarçado.
    """
    if resultado["status"] != "OK":
        return {}

    submarket = resultado["submarket"]
    ids: dict[str, str] = {}
    for quote_type in QUOTE_TYPES:
        curve_id, _eid = R.insert_curve(
            conn,
            curve_name=CURVE_NAME,
            submarket=submarket,
            as_of=as_of,
            source_name="Energy Trading Copilot — cenário estatístico (PLD público CCEE)",
            classification="projetado",
            origin="PROXY_MODELO",
            quote_type=quote_type,
            proxy_of="PLD histórico (mediana e percentis por mês-calendário)",
            notes=(
                f"{CURVE_CATEGORY}. {resultado['methodology']} Período histórico: "
                f"{resultado['historical_period']}. Última observação: "
                f"{resultado['last_observation']}. {DISCLAIMER}"
            ),
        )
        ids[quote_type] = curve_id
        for ponto in resultado["points"]:
            if ponto.status != "OK":
                continue
            preco = {"P10": ponto.p10, "P50": ponto.p50, "P90": ponto.p90}[quote_type]
            delivery_end = date(
                ponto.target_month.year + (1 if ponto.target_month.month == 12 else 0),
                1 if ponto.target_month.month == 12 else ponto.target_month.month + 1,
                1,
            )
            R.insert_curve_point(
                conn, curve_id,
                tenor=ponto.horizon_label,
                delivery_start=ponto.target_month.isoformat(),
                delivery_end=delivery_end.isoformat(),
                price=preco,  # type: ignore[arg-type]
                source_name="Energy Trading Copilot — cenário estatístico",
                as_of=as_of,
                classification="projetado",
            )
    return ids


def refresh_all_submarkets(conn: sqlite3.Connection, *, as_of: str) -> dict[str, dict[str, Any]]:
    """Recalcula e persiste a curva estatística para os quatro submercados."""
    saida: dict[str, dict[str, Any]] = {}
    for submarket in ("SE/CO", "S", "NE", "N"):
        resultado = compute_statistical_scenario(conn, as_of=as_of, submarket=submarket)
        if resultado["status"] == "OK":
            persist_statistical_scenario(conn, resultado, as_of=as_of)
        saida[submarket] = resultado
    return saida


__all__ = [
    "CURVE_CATEGORY",
    "CURVE_NAME",
    "DISCLAIMER",
    "MIN_ANNUAL_OBSERVATIONS",
    "QUOTE_TYPES",
    "ScenarioPoint",
    "compute_statistical_scenario",
    "persist_statistical_scenario",
    "refresh_all_submarkets",
]
