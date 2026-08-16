"""Limite de VaR de R$ 50 milhoes — P8 / RF-54 / AC-43.

Funcao pura, sem banco e sem LLM. Limite de risco e regra, nao julgamento.

O consumo do limite e medido sobre o **VaR total**: mercado mais add-ons. Medir
so o VaR de mercado subestimaria o consumo exatamente nos casos em que a
marcacao e por proxy ou a posicao e ilíquida — ou seja, quando mais importa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from copilot.common.enums import AddOnKind
from copilot.common.errors import VarLimitExceeded
from copilot.quant.addons import AddOnBundle

MONEY = Decimal("0.01")
RATIO = Decimal("0.000001")

#: P8. O limite do case. Sobrescrito apenas por configuracao explicita.
VAR_LIMIT_BRL = Decimal("50000000.00")

#: Faixa de atencao: consumo acima disso ja aparece como alerta na mesa.
WARNING_UTILIZATION = Decimal("0.80")


@dataclass(frozen=True, slots=True)
class LimitCheck:
    var_market_brl: Decimal
    addons_brl: Decimal
    var_total_brl: Decimal
    limit_brl: Decimal
    utilization: Decimal
    headroom_brl: Decimal
    within_limit: bool
    warning: bool
    message: str
    addon_breakdown: dict[str, Decimal] = field(default_factory=dict)

    @property
    def utilization_pct(self) -> str:
        return f"{self.utilization:.2%}"


def check_var_limit(
    var_market_brl: Decimal,
    *,
    addons: AddOnBundle | None = None,
    limit_brl: Decimal = VAR_LIMIT_BRL,
) -> LimitCheck:
    """Verifica o consumo do limite. Nao levanta excecao — devolve o veredito."""
    if limit_brl <= 0:
        raise ValueError("Limite de VaR deve ser positivo.")

    var_market = Decimal(var_market_brl).quantize(MONEY)
    total_addons = addons.total_brl if addons else Decimal("0.00")
    var_total = (var_market + total_addons).quantize(MONEY)
    utilizacao = (var_total / limit_brl).quantize(RATIO, rounding=ROUND_HALF_UP)
    folga = (limit_brl - var_total).quantize(MONEY)
    dentro = var_total <= limit_brl
    atencao = dentro and utilizacao >= WARNING_UTILIZATION

    breakdown = {}
    if addons:
        for kind in AddOnKind:
            valor = addons.by_kind(kind)
            if valor != 0:
                breakdown[kind.value] = valor

    if not dentro:
        mensagem = (
            f"VaR total de R$ {var_total} excede o limite de R$ {limit_brl} "
            f"em R$ {-folga}. Aprovacao bloqueada (P8 / RF-54)."
        )
    elif atencao:
        mensagem = (
            f"VaR total de R$ {var_total} consome {utilizacao:.2%} do limite. "
            f"Acima da faixa de atencao de {WARNING_UTILIZATION:.0%}."
        )
    else:
        mensagem = (
            f"VaR total de R$ {var_total} consome {utilizacao:.2%} do limite. "
            f"Folga de R$ {folga}."
        )

    return LimitCheck(
        var_market_brl=var_market,
        addons_brl=total_addons,
        var_total_brl=var_total,
        limit_brl=Decimal(limit_brl).quantize(MONEY),
        utilization=utilizacao,
        headroom_brl=folga,
        within_limit=dentro,
        warning=atencao,
        message=mensagem,
        addon_breakdown=breakdown,
    )


def assert_within_limit(
    var_market_brl: Decimal,
    *,
    addons: AddOnBundle | None = None,
    limit_brl: Decimal = VAR_LIMIT_BRL,
) -> LimitCheck:
    """Versao que bloqueia. Usada no caminho de aprovacao da tese (D-04: *hard*)."""
    resultado = check_var_limit(var_market_brl, addons=addons, limit_brl=limit_brl)
    if not resultado.within_limit:
        raise VarLimitExceeded(resultado.message)
    return resultado


def max_exposure_under_limit(
    var_per_brl_exposure: Decimal,
    *,
    limit_brl: Decimal = VAR_LIMIT_BRL,
    addon_load: Decimal = Decimal("0"),
) -> Decimal:
    """Exposicao maxima que cabe no limite, dado o VaR por real exposto.

    `addon_load` e a carga proporcional de add-ons (fracao da exposicao). Serve
    para dimensionar a posicao **antes** de monta-la, em vez de descobrir o
    estouro depois.
    """
    if var_per_brl_exposure <= 0:
        raise ValueError("VaR por real exposto deve ser positivo.")
    denominador = Decimal(var_per_brl_exposure) + Decimal(addon_load)
    if denominador <= 0:  # pragma: no cover - defensivo
        raise ValueError("Denominador nao positivo no dimensionamento.")
    return (Decimal(limit_brl) / denominador).quantize(MONEY)


__all__ = [
    "LimitCheck",
    "VAR_LIMIT_BRL",
    "WARNING_UTILIZATION",
    "assert_within_limit",
    "check_var_limit",
    "max_exposure_under_limit",
]
