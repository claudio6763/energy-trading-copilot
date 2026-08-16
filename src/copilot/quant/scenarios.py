"""Cenarios hidrologicos: seco, base, umido e extremo.

O case exige **pelo menos dois cenarios hidrologicos distintos**, com resultado
esperado, impacto no VaR e o que muda na tese em cada um (Entrega 2). Aqui os
quatro sao declarativos: choque de preco, multiplicador de volatilidade e peso
de probabilidade, todos explicitos.

**Os parametros abaixo sao premissas declaradas da mesa, nao dado observado.**
Estao no codigo para serem discutidos e recalibrados, nao para serem aceitos.
`EXTREMO` e cenario de estresse: peso zero na esperanca, existe para dimensionar
cauda, nao para prever.

Nenhum LLM neste caminho.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Sequence

from copilot.common.enums import HydroScenario
from copilot.common.errors import MissingDataError
from copilot.quant.pnl import PositionSpec, portfolio_pnl
from copilot.quant.var import DEFAULT_CONFIDENCE, DEFAULT_HORIZON_DAYS, parametric_var

MONEY = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    """Choque declarado sobre o preco de marcacao."""

    name: HydroScenario
    #: Multiplicador sobre o preco base. 1,0 = sem choque.
    price_multiplier: Decimal
    #: Deslocamento absoluto adicional em R$/MWh, aplicado apos o multiplicador.
    price_shift_brl_mwh: Decimal = Decimal("0.00")
    #: Multiplicador sobre a volatilidade usada no VaR.
    vol_multiplier: Decimal = Decimal("1.0")
    #: Peso na esperanca. Estresse tem peso zero.
    probability: Decimal = Decimal("0.00")
    description: str = ""
    is_stress: bool = False

    def shock_price(self, base_price: Decimal) -> Decimal:
        return (Decimal(base_price) * self.price_multiplier + self.price_shift_brl_mwh).quantize(
            Decimal("0.01")
        )


#: Calibragem inicial. Premissa declarada — revisar com a mesa antes de usar em
#: dimensionamento real. Pesos de BASE/SECO/UMIDO somam 1,0; EXTREMO e estresse.
STANDARD_SCENARIOS: dict[HydroScenario, ScenarioDefinition] = {
    HydroScenario.BASE: ScenarioDefinition(
        name=HydroScenario.BASE,
        price_multiplier=Decimal("1.00"),
        vol_multiplier=Decimal("1.0"),
        probability=Decimal("0.50"),
        description="Hidrologia dentro da faixa recente; curva se realiza como marcada.",
    ),
    HydroScenario.SECO: ScenarioDefinition(
        name=HydroScenario.SECO,
        price_multiplier=Decimal("1.35"),
        vol_multiplier=Decimal("1.4"),
        probability=Decimal("0.30"),
        description="Afluencia abaixo da media prolongada; termica no despacho e preco sobe.",
    ),
    HydroScenario.UMIDO: ScenarioDefinition(
        name=HydroScenario.UMIDO,
        price_multiplier=Decimal("0.75"),
        vol_multiplier=Decimal("0.9"),
        probability=Decimal("0.20"),
        description="Afluencia acima da media; sobra de energia pressiona preco para baixo.",
    ),
    HydroScenario.EXTREMO: ScenarioDefinition(
        name=HydroScenario.EXTREMO,
        price_multiplier=Decimal("1.80"),
        vol_multiplier=Decimal("2.0"),
        probability=Decimal("0.00"),
        description=(
            "Estresse: seca severa com restricao de oferta. Peso zero na esperanca; "
            "existe para dimensionar cauda, nao para prever."
        ),
        is_stress=True,
    ),
}


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    scenario: HydroScenario
    is_stress: bool
    probability: Decimal
    shocked_prices: dict[str, Decimal]
    pnl_brl: Decimal
    var_brl: Decimal
    var_delta_brl: Decimal
    thesis_delta: str
    description: str


@dataclass(frozen=True, slots=True)
class ScenarioMatrix:
    outcomes: tuple[ScenarioOutcome, ...]
    base_pnl_brl: Decimal
    base_var_brl: Decimal

    @property
    def expected_pnl_brl(self) -> Decimal:
        """Esperanca ponderada, excluindo estresse (peso zero)."""
        peso = sum(
            (o.probability for o in self.outcomes if not o.is_stress), Decimal("0")
        )
        if peso == 0:
            return Decimal("0.00")
        soma = sum(
            (o.pnl_brl * o.probability for o in self.outcomes if not o.is_stress),
            Decimal("0"),
        )
        return (soma / peso).quantize(MONEY)

    @property
    def worst_case(self) -> ScenarioOutcome:
        return min(self.outcomes, key=lambda o: o.pnl_brl)

    @property
    def hydrological_count(self) -> int:
        return len(self.outcomes)

    def by_name(self, name: HydroScenario) -> ScenarioOutcome | None:
        return next((o for o in self.outcomes if o.scenario is name), None)


def run_scenario(
    positions: Sequence[PositionSpec],
    base_prices: Mapping[str, Decimal],
    definition: ScenarioDefinition,
    *,
    sigma_daily: Mapping[str, float] | None = None,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> ScenarioOutcome:
    """Aplica um cenario e devolve P&L, VaR e o que muda na tese."""
    if not positions:
        raise MissingDataError("Cenario sem posicoes: nao ha o que estressar.")

    precos = {k: definition.shock_price(v) for k, v in base_prices.items()}
    resultado = portfolio_pnl(positions, precos)

    var_total = Decimal("0.00")
    # `None` = VaR nao pedido. `{}` = pedido e sem dado — sao coisas diferentes,
    # e a segunda tem que falhar alto em vez de devolver zero.
    if sigma_daily is not None:
        for detalhe in resultado.positions:
            sigma = sigma_daily.get(detalhe.metric_key)
            if sigma is None:
                raise MissingDataError(
                    f"Cenario {definition.name.value}: sem volatilidade para "
                    f"{detalhe.metric_key}."
                )
            var = parametric_var(
                detalhe.signed_exposure_brl,
                sigma * float(definition.vol_multiplier),
                confidence=confidence,
                horizon_days=horizon_days,
            )
            var_total += var.var_brl
    var_total = var_total.quantize(MONEY)

    if definition.name is HydroScenario.BASE:
        delta = "Tese mantida; reavaliar na data prevista."
    elif resultado.total_pnl_brl < 0:
        delta = (
            f"Posicao perde R$ {abs(resultado.total_pnl_brl)} neste cenario; "
            "checar gatilho de saida e condicao de invalidacao antes de manter."
        )
    else:
        delta = (
            f"Posicao ganha R$ {resultado.total_pnl_brl}; tese se confirma, "
            "avaliar realizacao parcial."
        )

    return ScenarioOutcome(
        scenario=definition.name,
        is_stress=definition.is_stress,
        probability=definition.probability,
        shocked_prices=precos,
        pnl_brl=resultado.total_pnl_brl,
        var_brl=var_total,
        var_delta_brl=Decimal("0.00"),
        thesis_delta=delta,
        description=definition.description,
    )


def run_scenarios(
    positions: Sequence[PositionSpec],
    base_prices: Mapping[str, Decimal],
    *,
    definitions: Mapping[HydroScenario, ScenarioDefinition] | None = None,
    sigma_daily: Mapping[str, float] | None = None,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> ScenarioMatrix:
    """Roda a matriz completa e mede o impacto no VaR relativo ao cenario base."""
    definitions = definitions or STANDARD_SCENARIOS
    if HydroScenario.BASE not in definitions:
        raise MissingDataError("Matriz de cenarios exige o cenario BASE como referencia.")

    brutos = {
        nome: run_scenario(
            positions,
            base_prices,
            definicao,
            sigma_daily=sigma_daily,
            confidence=confidence,
            horizon_days=horizon_days,
        )
        for nome, definicao in definitions.items()
    }
    base = brutos[HydroScenario.BASE]

    ajustados = tuple(
        ScenarioOutcome(
            scenario=o.scenario,
            is_stress=o.is_stress,
            probability=o.probability,
            shocked_prices=o.shocked_prices,
            pnl_brl=o.pnl_brl,
            var_brl=o.var_brl,
            var_delta_brl=(o.var_brl - base.var_brl).quantize(MONEY),
            thesis_delta=o.thesis_delta,
            description=o.description,
        )
        for o in brutos.values()
    )
    return ScenarioMatrix(
        outcomes=ajustados,
        base_pnl_brl=base.pnl_brl,
        base_var_brl=base.var_brl,
    )


__all__ = [
    "STANDARD_SCENARIOS",
    "ScenarioDefinition",
    "ScenarioMatrix",
    "ScenarioOutcome",
    "run_scenario",
    "run_scenarios",
]
