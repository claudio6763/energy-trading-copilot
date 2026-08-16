"""Todos os models. Importar este pacote popula `Base.metadata` por completo.

A ordem de import segue a ordem de dependencia de chave estrangeira, que e a
mesma ordem de criacao das tabelas na migration inicial.
"""

from copilot.db.base import Base, metadata_obj
from copilot.db.models.audit import AuditLog
from copilot.db.models.catalog import (
    ForwardCurve,
    ForwardCurvePoint,
    MarketObservation,
    MarketSeries,
    Source,
)
from copilot.db.models.debate import Claim, DebateSession, DebateTurn
from copilot.db.models.evidence import Evidence, QuantRun, SqlExecution
from copilot.db.models.ingest import IngestSnapshot
from copilot.db.models.rag import Document, DocumentChunk
from copilot.db.models.scenario import Scenario, ScenarioResult
from copilot.db.models.thesis import Assumption, Position, RiskItem, Thesis, TriggerRule
from copilot.db.models.watchdog import Alert, WatchdogRun

#: Ordem de criacao respeitando FKs (usada pela migration e pelo reset de testes).
TABLE_CREATE_ORDER: tuple[str, ...] = (
    "source",
    "sql_execution",
    "quant_run",
    "evidence",
    "ingest_snapshot",
    "market_series",
    "market_observation",
    "forward_curve",
    "forward_curve_point",
    "document",
    "document_chunk",
    "thesis",
    "assumption",
    "position",
    "trigger_rule",
    "risk_item",
    "scenario",
    "scenario_result",
    "debate_session",
    "debate_turn",
    "watchdog_run",
    "alert",
    "claim",
    "audit_log",
)

#: Tabelas que carregam `dataset_kind` — usadas pelo seed e pelos testes de escopo.
DATASET_SCOPED_TABLES: tuple[str, ...] = tuple(
    name for name in TABLE_CREATE_ORDER if name != "audit_log"
)

__all__ = [
    "Alert",
    "Assumption",
    "AuditLog",
    "Base",
    "Claim",
    "DATASET_SCOPED_TABLES",
    "DebateSession",
    "DebateTurn",
    "Document",
    "DocumentChunk",
    "Evidence",
    "ForwardCurve",
    "ForwardCurvePoint",
    "IngestSnapshot",
    "MarketObservation",
    "MarketSeries",
    "Position",
    "QuantRun",
    "RiskItem",
    "Scenario",
    "ScenarioResult",
    "Source",
    "SqlExecution",
    "TABLE_CREATE_ORDER",
    "Thesis",
    "TriggerRule",
    "WatchdogRun",
    "metadata_obj",
]
