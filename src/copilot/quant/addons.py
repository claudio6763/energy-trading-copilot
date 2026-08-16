"""Add-ons de risco somados ao VaR de mercado.

O VaR de mercado mede o que a serie de precos ja mostrou. Ele nao mede quatro
coisas que custam dinheiro de verdade nesta mesa:

* **Liquidez** — o case abre dizendo que o numero de contrapartes ativas vem
  diminuindo. Desmontar posicao custa, e custa mais quanto maior a posicao
  frente ao giro do mercado.
* **Basis** — proteger SE/CO com instrumento de outro submercado deixa risco
  residual proporcional a ``sqrt(1 - rho^2)``.
* **Proxy** — usar PLD/CMO como referencia de preco de longo prazo. PLD e preco
  de curto prazo formado por modelo de despacho, **nao** preco negociado. Se for
  usado, e penalizado aqui, explicitamente, e a penalizacao aparece no numero.
* **Risco de modelo** — a raiz do tempo e a normalidade sao aproximacoes
  declaradas em `quant.var`. O add-on e o preco de admitir isso.

Todos os parametros abaixo sao **premissas declaradas da mesa**, calibraveis.
Nenhum deles e dado de mercado observado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from copilot.common.enums import AddOnKind, CurveOrigin, DataQuality
from copilot.quant.var import DEFAULT_CONFIDENCE, DEFAULT_HORIZON_DAYS, horizon_factor, z_score

MONEY = Decimal("0.01")

# --- Parametros declarados (nao sao dado de mercado) -----------------------

#: Spread de compra e venda tipico assumido, em fracao do preco.
DEFAULT_BID_ASK_PCT = Decimal("0.020")
#: Penalizacao por origem da curva. PROXY_SPOT e a mais cara de proposito.
DEFAULT_PROXY_PENALTY: dict[CurveOrigin, Decimal] = {
    CurveOrigin.NEGOCIADA: Decimal("0.000"),
    CurveOrigin.INTERNA: Decimal("0.050"),
    CurveOrigin.PROXY_MODELO: Decimal("0.150"),
    CurveOrigin.PROXY_SPOT: Decimal("0.250"),
}
#: Penalizacao adicional por qualidade declarada do dado.
DEFAULT_QUALITY_PENALTY: dict[DataQuality, Decimal] = {
    DataQuality.OK: Decimal("0.000"),
    DataQuality.PRELIMINAR: Decimal("0.020"),
    DataQuality.ESTIMADO: Decimal("0.050"),
    DataQuality.INCOMPLETO: Decimal("0.080"),
    DataQuality.SUSPEITO: Decimal("0.150"),
    DataQuality.PROXY: Decimal("0.100"),
}
#: Multiplicador de risco de modelo sobre o VaR de mercado.
DEFAULT_MODEL_RISK_MULTIPLIER = Decimal("0.100")
#: Dias maximos de desmontagem antes de a liquidez virar problema de tese.
MAX_UNWIND_DAYS = 60


def _q(value: Decimal | float) -> Decimal:
    return (value if isinstance(value, Decimal) else Decimal(repr(value))).quantize(MONEY)


@dataclass(frozen=True, slots=True)
class AddOn:
    """Um add-on, com a conta explicita de como foi obtido."""

    kind: AddOnKind
    amount_brl: Decimal
    rationale: str
    driver: Decimal = Decimal("0")
    parameters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AddOnBundle:
    items: tuple[AddOn, ...]

    @property
    def total_brl(self) -> Decimal:
        return sum((a.amount_brl for a in self.items), Decimal("0.00")).quantize(MONEY)

    def by_kind(self, kind: AddOnKind) -> Decimal:
        return sum(
            (a.amount_brl for a in self.items if a.kind is kind), Decimal("0.00")
        ).quantize(MONEY)

    def explain(self) -> list[str]:
        return [f"{a.kind.value}: R$ {a.amount_brl} — {a.rationale}" for a in self.items]


# ---------------------------------------------------------------------------
def liquidity_addon(
    gross_exposure_brl: Decimal,
    *,
    position_mwmed: Decimal,
    market_adv_mwmed: Decimal,
    bid_ask_pct: Decimal = DEFAULT_BID_ASK_PCT,
) -> AddOn:
    """Custo esperado de desmontar a posicao.

    ``custo = (bid_ask/2) * exposicao * sqrt(dias_para_desmontar)``

    `dias_para_desmontar = posicao / giro diario do mercado`. A raiz reflete que
    fatiar a saida reduz impacto, mas nao o elimina.
    """
    if market_adv_mwmed <= 0:
        raise ValueError("Giro diario do mercado deve ser positivo.")
    dias = float(Decimal(position_mwmed).copy_abs() / Decimal(market_adv_mwmed))
    dias_efetivos = min(max(dias, 1.0), float(MAX_UNWIND_DAYS))
    fator = float(bid_ask_pct) / 2.0 * math.sqrt(dias_efetivos)
    valor = _q(abs(float(gross_exposure_brl)) * fator)
    return AddOn(
        kind=AddOnKind.LIQUIDEZ,
        amount_brl=valor,
        driver=Decimal(repr(round(dias, 4))),
        rationale=(
            f"desmontagem estimada em {dias:.1f} dias de giro "
            f"(limitada a {MAX_UNWIND_DAYS}); spread assumido {bid_ask_pct:.2%}"
        ),
        parameters={"dias_desmontagem": f"{dias:.4f}", "bid_ask_pct": str(bid_ask_pct)},
    )


def basis_addon(
    exposure_brl: Decimal,
    *,
    basis_vol_daily: float,
    correlation: float,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> AddOn:
    """Risco residual de proteger em outro submercado ou outro produto.

    ``add-on = z * sqrt(h) * sigma_basis * sqrt(1 - rho^2) * |exposicao|``

    Com `rho = 1` o add-on e zero: hedge perfeito. Com `rho = 0` ele e o VaR
    cheio do basis.
    """
    if not -1.0 <= correlation <= 1.0:
        raise ValueError(f"Correlacao fora de [-1,1]: {correlation}.")
    if basis_vol_daily < 0:
        raise ValueError("Volatilidade de basis nao pode ser negativa.")
    residual = math.sqrt(max(0.0, 1.0 - correlation * correlation))
    fator = z_score(confidence) * horizon_factor(horizon_days) * basis_vol_daily * residual
    valor = _q(abs(float(exposure_brl)) * fator)
    return AddOn(
        kind=AddOnKind.BASIS,
        amount_brl=valor,
        driver=Decimal(repr(round(residual, 6))),
        rationale=(
            f"correlacao {correlation:.2f} deixa {residual:.1%} de risco residual "
            f"com vol de basis {basis_vol_daily:.2%} a.d."
        ),
        parameters={"correlacao": str(correlation), "vol_basis_diaria": str(basis_vol_daily)},
    )


def proxy_addon(
    exposure_brl: Decimal,
    *,
    curve_origin: CurveOrigin,
    quality: DataQuality = DataQuality.OK,
    penalty_by_origin: dict[CurveOrigin, Decimal] | None = None,
    penalty_by_quality: dict[DataQuality, Decimal] | None = None,
) -> AddOn:
    """Penalizacao por marcar posicao com preco que nao e negociado.

    Regra dura do projeto: **PLD e CMO nao sao curva forward.** Quando entram
    como referencia (`CurveOrigin.PROXY_SPOT`), o custo dessa escolha aparece
    aqui, somado ao VaR — nao fica escondido numa nota de rodape.
    """
    origem = penalty_by_origin or DEFAULT_PROXY_PENALTY
    qual = penalty_by_quality or DEFAULT_QUALITY_PENALTY
    penalidade = origem.get(curve_origin, Decimal("0.250")) + qual.get(quality, Decimal("0.000"))
    valor = _q(Decimal(abs(float(exposure_brl))) * penalidade)
    if curve_origin is CurveOrigin.NEGOCIADA and quality is DataQuality.OK:
        motivo = "curva negociada com dado integro: sem penalizacao"
    else:
        motivo = (
            f"marcacao por {curve_origin.value} com qualidade {quality.value}: "
            f"penalizacao total {penalidade:.1%} da exposicao"
        )
    return AddOn(
        kind=AddOnKind.PROXY,
        amount_brl=valor,
        driver=penalidade,
        rationale=motivo,
        parameters={"origem": curve_origin.value, "qualidade": quality.value},
    )


def model_risk_addon(
    var_market_brl: Decimal,
    *,
    multiplier: Decimal = DEFAULT_MODEL_RISK_MULTIPLIER,
    reasons: Sequence[str] = (),
) -> AddOn:
    """Preco de admitir que o modelo e aproximacao.

    Cobre raiz do tempo, normalidade e estabilidade de correlacao — as tres
    aproximacoes declaradas em `quant.var`.
    """
    if multiplier < 0:
        raise ValueError("Multiplicador de risco de modelo nao pode ser negativo.")
    valor = _q(Decimal(var_market_brl) * multiplier)
    base = "raiz do tempo, normalidade e correlacao estavel sao aproximacoes declaradas"
    detalhe = "; ".join(reasons) if reasons else base
    return AddOn(
        kind=AddOnKind.RISCO_MODELO,
        amount_brl=valor,
        driver=multiplier,
        rationale=f"{multiplier:.1%} sobre o VaR de mercado — {detalhe}",
        parameters={"multiplicador": str(multiplier)},
    )


def build_addons(
    *,
    var_market_brl: Decimal,
    gross_exposure_brl: Decimal,
    position_mwmed: Decimal | None = None,
    market_adv_mwmed: Decimal | None = None,
    bid_ask_pct: Decimal = DEFAULT_BID_ASK_PCT,
    basis_vol_daily: float | None = None,
    basis_correlation: float | None = None,
    curve_origin: CurveOrigin = CurveOrigin.NEGOCIADA,
    quality: DataQuality = DataQuality.OK,
    model_risk_multiplier: Decimal = DEFAULT_MODEL_RISK_MULTIPLIER,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> AddOnBundle:
    """Monta o pacote completo. Componente sem parametro declarado e omitido —
    nunca estimado por conta propria."""
    items: list[AddOn] = []

    if position_mwmed is not None and market_adv_mwmed is not None:
        items.append(
            liquidity_addon(
                gross_exposure_brl,
                position_mwmed=position_mwmed,
                market_adv_mwmed=market_adv_mwmed,
                bid_ask_pct=bid_ask_pct,
            )
        )
    if basis_vol_daily is not None and basis_correlation is not None:
        items.append(
            basis_addon(
                gross_exposure_brl,
                basis_vol_daily=basis_vol_daily,
                correlation=basis_correlation,
                confidence=confidence,
                horizon_days=horizon_days,
            )
        )
    items.append(proxy_addon(gross_exposure_brl, curve_origin=curve_origin, quality=quality))
    items.append(model_risk_addon(var_market_brl, multiplier=model_risk_multiplier))
    return AddOnBundle(tuple(items))


__all__ = [
    "AddOn",
    "AddOnBundle",
    "DEFAULT_BID_ASK_PCT",
    "DEFAULT_MODEL_RISK_MULTIPLIER",
    "DEFAULT_PROXY_PENALTY",
    "DEFAULT_QUALITY_PENALTY",
    "basis_addon",
    "build_addons",
    "liquidity_addon",
    "model_risk_addon",
    "proxy_addon",
]
