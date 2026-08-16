"""Contratos do Watchdog (Sprint 6).

`WatchdogReport.sources_failed` existe para impedir o pior modo de falha do
sistema: fonte indisponivel interpretada como premissa valida (RF-36 / AC-23).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from copilot.common.enums import (
    AlertKind,
    AssumptionStatus,
    Severity,
    Unit,
    WatchdogStatus,
)


class RuleEvaluation(BaseModel):
    """Avaliacao 100% deterministica de uma regra. Sem LLM no caminho."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    metric_key: str
    observed_value: Decimal | None
    threshold: Decimal
    unit: Unit
    triggered: bool
    #: None quando a fonte falhou — distinto de "nao disparou".
    evaluated: bool = True
    evidence_id: str | None = None
    reason: str | None = None


class AssumptionEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    assumption_id: str
    metric_key: str | None
    status: AssumptionStatus
    observed_value: Decimal | None = None
    expected_value: Decimal | None = None
    delta: Decimal | None = None
    evidence_id: str | None = None


class AlertDraft(BaseModel):
    """Alerta antes de persistir. `evidence_id` e obrigatorio (RF-33)."""

    model_config = ConfigDict(frozen=True)

    thesis_id: str
    severity: Severity
    alert_kind: AlertKind
    message: str
    evidence_id: str
    assumption_id: str | None = None
    trigger_rule_id: str | None = None
    observed_value: Decimal | None = None
    expected_value: Decimal | None = None
    delta: Decimal | None = None
    unit: Unit | None = None
    dedup_key: str | None = None


class WatchdogReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    as_of: date
    status: WatchdogStatus
    theses_checked: int = 0
    assumption_evaluations: list[AssumptionEvaluation] = Field(default_factory=list)
    rule_evaluations: list[RuleEvaluation] = Field(default_factory=list)
    alerts: list[AlertDraft] = Field(default_factory=list)
    sources_ok: list[str] = Field(default_factory=list)
    sources_failed: list[str] = Field(default_factory=list)

    @property
    def has_coverage_gap(self) -> bool:
        return bool(self.sources_failed)


__all__ = [
    "AlertDraft",
    "AssumptionEvaluation",
    "RuleEvaluation",
    "WatchdogReport",
]
