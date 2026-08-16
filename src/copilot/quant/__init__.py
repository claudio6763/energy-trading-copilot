"""Motor quantitativo deterministico.

Regras do pacote, sem excecao:

* **Nenhum LLM.** Nada aqui chama modelo de linguagem (P3 / P5).
* **Nenhuma dependencia externa.** So stdlib: `math`, `statistics`, `decimal`.
  `statistics.NormalDist` cobre o quantil normal com precisao de maquina. Isso
  mantem o resultado reproduzivel bit a bit e o nucleo com quatro dependencias
  (ADR-010).
* **Nenhum acesso a banco.** Recebe dados ja carregados; quem persiste e
  `quant.runner`, na fronteira.
* **Dinheiro em `Decimal`.** `float` aparece so em estatistica intermediaria
  (retornos, volatilidade), nunca em valor monetario armazenado.
* **Amostra curta ou dado faltante levantam excecao**, nunca devolvem numero.
"""

from copilot.quant.addons import (
    AddOn,
    AddOnBundle,
    basis_addon,
    build_addons,
    liquidity_addon,
    model_risk_addon,
    proxy_addon,
)
from copilot.quant.limits import (
    VAR_LIMIT_BRL,
    LimitCheck,
    assert_within_limit,
    check_var_limit,
    max_exposure_under_limit,
)
from copilot.quant.periods import (
    DeliveryPeriod,
    month_period,
    mwh_to_mwmed,
    mwmed_to_mwh,
    period_hours,
    quarter_period,
    year_period,
)
from copilot.quant.pnl import (
    PortfolioPnL,
    PositionPnL,
    PositionSpec,
    carry_pnl,
    portfolio_pnl,
    position_pnl,
)
from copilot.quant.scenarios import (
    STANDARD_SCENARIOS,
    ScenarioDefinition,
    ScenarioMatrix,
    ScenarioOutcome,
    run_scenario,
    run_scenarios,
)
from copilot.quant.var import (
    DEFAULT_CONFIDENCE,
    DEFAULT_HORIZON_DAYS,
    ReturnSeries,
    VaRResult,
    ewma_var,
    ewma_volatility,
    historical_var,
    log_returns,
    parametric_var,
    portfolio_historical_var,
    portfolio_parametric_var,
    sample_volatility,
    z_score,
)

__all__ = [
    "AddOn",
    "AddOnBundle",
    "DEFAULT_CONFIDENCE",
    "DEFAULT_HORIZON_DAYS",
    "DeliveryPeriod",
    "LimitCheck",
    "PortfolioPnL",
    "PositionPnL",
    "PositionSpec",
    "ReturnSeries",
    "STANDARD_SCENARIOS",
    "ScenarioDefinition",
    "ScenarioMatrix",
    "ScenarioOutcome",
    "VAR_LIMIT_BRL",
    "VaRResult",
    "assert_within_limit",
    "basis_addon",
    "build_addons",
    "carry_pnl",
    "check_var_limit",
    "ewma_var",
    "ewma_volatility",
    "historical_var",
    "liquidity_addon",
    "log_returns",
    "max_exposure_under_limit",
    "model_risk_addon",
    "month_period",
    "mwh_to_mwmed",
    "mwmed_to_mwh",
    "parametric_var",
    "period_hours",
    "portfolio_historical_var",
    "portfolio_parametric_var",
    "portfolio_pnl",
    "position_pnl",
    "proxy_addon",
    "quarter_period",
    "run_scenario",
    "run_scenarios",
    "sample_volatility",
    "year_period",
    "z_score",
]
