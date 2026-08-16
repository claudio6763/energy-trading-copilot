"""Repositorios: unico caminho de leitura e escrita do dominio.

Nenhuma camada acima (agentes, UI, Watchdog) monta `select` na mao. Isso e o que
mantem `dataset_kind` e `as_of` aplicados em 100% das consultas.
"""

from copilot.db.repositories.base import BaseRepository
from copilot.db.repositories.catalog import (
    DocumentChunkRepository,
    DocumentRepository,
    EvidenceRepository,
    ForwardCurvePointRepository,
    ForwardCurveRepository,
    MarketObservationRepository,
    MarketSeriesRepository,
    QuantRunRepository,
    SourceRepository,
    SqlExecutionRepository,
    content_hash,
)
from copilot.db.repositories.oversight import (
    AlertRepository,
    ClaimRepository,
    DebateRepository,
    DebateTurnRepository,
    ScenarioRepository,
    ScenarioResultRepository,
    WatchdogRepository,
)
from copilot.db.repositories.thesis import (
    AssumptionRepository,
    PositionRepository,
    RiskItemRepository,
    ThesisRepository,
    TriggerRuleRepository,
)


class Repositories:
    """Agregador conveniente: um ponto de acesso por sessao."""

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self.sources = SourceRepository(session)
        self.evidence = EvidenceRepository(session)
        self.series = MarketSeriesRepository(session)
        self.observations = MarketObservationRepository(session)
        self.curves = ForwardCurveRepository(session)
        self.curve_points = ForwardCurvePointRepository(session)
        self.documents = DocumentRepository(session)
        self.chunks = DocumentChunkRepository(session)
        self.sql_executions = SqlExecutionRepository(session)
        self.quant_runs = QuantRunRepository(session)
        self.theses = ThesisRepository(session)
        self.assumptions = AssumptionRepository(session)
        self.positions = PositionRepository(session)
        self.triggers = TriggerRuleRepository(session)
        self.risks = RiskItemRepository(session)
        self.scenarios = ScenarioRepository(session)
        self.scenario_results = ScenarioResultRepository(session)
        self.debates = DebateRepository(session)
        self.debate_turns = DebateTurnRepository(session)
        self.claims = ClaimRepository(session)
        self.watchdog = WatchdogRepository(session)
        self.alerts = AlertRepository(session)


__all__ = [
    "AlertRepository",
    "AssumptionRepository",
    "BaseRepository",
    "ClaimRepository",
    "DebateRepository",
    "DebateTurnRepository",
    "DocumentChunkRepository",
    "DocumentRepository",
    "EvidenceRepository",
    "ForwardCurvePointRepository",
    "ForwardCurveRepository",
    "MarketObservationRepository",
    "MarketSeriesRepository",
    "PositionRepository",
    "QuantRunRepository",
    "Repositories",
    "RiskItemRepository",
    "ScenarioRepository",
    "ScenarioResultRepository",
    "SourceRepository",
    "SqlExecutionRepository",
    "ThesisRepository",
    "TriggerRuleRepository",
    "WatchdogRepository",
    "content_hash",
]
