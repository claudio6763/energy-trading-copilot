"""Contratos do debate multi-agente (Sprint 5).

`AgentRequest` nao tem campo para "historico do outro agente" de proposito: o
Agente de Risco recebe apenas a tese e os dados. O isolamento e estrutural
(ARCHITECTURE secao 3.3 / AC-13), e `context_hash` permite prova-lo depois.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from copilot.common.enums import AgentName, ClaimStatus, DatasetKind, DebateVerdict, TurnRole


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_ref: str | None = None
    duration_ms: int | None = None


class AgentRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: AgentName
    role: TurnRole
    thesis_id: str
    as_of: date
    dataset_kind: DatasetKind
    #: Payload estruturado da tese. Nunca texto livre de outro agente.
    thesis_snapshot: dict[str, Any]
    instructions: str | None = None
    prompt_version: str = "v1"


class AgentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: AgentName
    role: TurnRole
    content: str
    tools_called: list[ToolCall] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    verifier_status: ClaimStatus | None = None
    model: str | None = None
    prompt_version: str = "v1"
    #: SHA-256 do contexto recebido — prova de isolamento (AC-13).
    context_hash: str | None = None
    cost_usd: Decimal | None = None


class DebateOutcome(BaseModel):
    """Veredito consolidado da rodada (RF-21 / AC-11)."""

    model_config = ConfigDict(frozen=True)

    verdict: DebateVerdict
    counter_argument: str | None = None
    weakest_assumption_id: str | None = None
    breaking_scenario_id: str | None = None
    confirmation_bias_score: Decimal | None = None
    bias_rationale: str | None = None
    blocking_reasons: list[str] = Field(default_factory=list)

    @property
    def approvable(self) -> bool:
        """RF-27: sem contra-argumento com evidencia, a rodada nao libera aprovacao."""
        return (
            self.verdict is DebateVerdict.APROVAVEL
            and bool(self.counter_argument)
            and not self.blocking_reasons
        )


__all__ = ["AgentRequest", "AgentResponse", "DebateOutcome", "ToolCall"]
