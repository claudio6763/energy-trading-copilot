"""Contratos do motor quantitativo (Sprint 3). Nenhuma implementacao aqui."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from copilot.common.enums import DatasetKind, QuantFunction, ScenarioKind


class QuantRequest(BaseModel):
    """Entrada de qualquer funcao do motor. `as_of` e seed sao obrigatorios
    para reprodutibilidade (RF-56 / AC-40)."""

    model_config = ConfigDict(frozen=True)

    function: QuantFunction
    as_of: date
    dataset_kind: DatasetKind
    inputs: dict[str, Any]
    seed: int | None = None


class QuantResult(BaseModel):
    """Saida do motor. `run_id` e o `evidence_id` do numero produzido."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=26, max_length=26)
    function: QuantFunction
    outputs: dict[str, Any]
    inputs_hash: str
    code_version: str
    seed: int | None = None
    duration_ms: int | None = None


class VaRResult(BaseModel):
    """Resultado de VaR. Metodologia e horizonte explicitos: a definicao do
    limite de R$ 50 mi e a duvida D-01, entao nunca fica implicita."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    method: QuantFunction
    confidence: Decimal
    horizon_days: int
    var_brl: Decimal
    expected_shortfall_brl: Decimal | None = None
    marginal_by_position: dict[str, Decimal] = Field(default_factory=dict)


class PnLResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    realized_brl: Decimal
    mark_to_market_brl: Decimal
    carry_brl: Decimal
    #: Atribuicao tese x carrego x mercado (camada de post-mortem, fora de escopo).
    attribution: dict[str, Decimal] = Field(default_factory=dict)


class ScenarioSpec(BaseModel):
    """Cenario declarativo. Choques explicitos — nada de media escondida."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: ScenarioKind
    shocks: dict[str, Decimal]
    probability_weight: Decimal | None = None
    description: str | None = None


class LimitCheck(BaseModel):
    """Verificacao do limite de VaR (P8 / RF-54 / AC-43). Funcao pura."""

    model_config = ConfigDict(frozen=True)

    var_brl: Decimal
    limit_brl: Decimal
    within_limit: bool
    utilization: Decimal
    message: str


__all__ = [
    "LimitCheck",
    "PnLResult",
    "QuantRequest",
    "QuantResult",
    "ScenarioSpec",
    "VaRResult",
]
