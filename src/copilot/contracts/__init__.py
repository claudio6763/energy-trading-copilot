"""Contratos Pydantic entre camadas.

CLAUDE.md secao 5: "Toda entrada e saida de agente e um modelo Pydantic. Nada de
`dict` solto atravessando fronteira."

Sprint 1 entrega **somente os contratos** — sem implementacao. Eles fixam a
fronteira que as sprints 3 a 6 vao respeitar:

* `quant.py`  — motor determinístico (Sprint 3);
* `verifier.py` — Claim Verifier (Sprint 4);
* `rag.py`    — recuperacao documental (Sprint 4);
* `sql.py`    — Agente de Dados e SQL (Sprint 2);
* `agents.py` — debate multi-agente (Sprint 5);
* `watchdog.py` — avaliacao de regras e alertas (Sprint 6).
"""

from copilot.contracts.agents import (
    AgentRequest,
    AgentResponse,
    DebateOutcome,
    ToolCall,
)
from copilot.contracts.evidence import EvidenceRef, NumericFact
from copilot.contracts.quant import (
    LimitCheck,
    PnLResult,
    QuantRequest,
    QuantResult,
    ScenarioSpec,
    VaRResult,
)
from copilot.contracts.rag import RagAnswer, RagQuery, RetrievedChunk
from copilot.contracts.sql import SqlRequest, SqlResult
from copilot.contracts.verifier import ExtractedClaim, VerificationReport
from copilot.contracts.watchdog import AlertDraft, RuleEvaluation, WatchdogReport

__all__ = [
    "AgentRequest",
    "AgentResponse",
    "AlertDraft",
    "DebateOutcome",
    "EvidenceRef",
    "ExtractedClaim",
    "LimitCheck",
    "NumericFact",
    "PnLResult",
    "QuantRequest",
    "QuantResult",
    "RagAnswer",
    "RagQuery",
    "RetrievedChunk",
    "RuleEvaluation",
    "ScenarioSpec",
    "SqlRequest",
    "SqlResult",
    "ToolCall",
    "VaRResult",
    "VerificationReport",
    "WatchdogReport",
]
