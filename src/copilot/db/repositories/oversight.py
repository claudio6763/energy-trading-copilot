"""Repositorios de debate, verificacao, cenarios, Watchdog e alertas.

Sprint 1 entrega persistencia e invariantes. A logica de conducao do debate
(Sprint 5) e a de avaliacao de regras (Sprint 6) consomem estes repositorios.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import select

from copilot.common.enums import (
    BLOCKING_CLAIM_STATUSES,
    AgentName,
    AlertDecision,
    AlertKind,
    AuditAction,
    ClaimStatus,
    ClaimType,
    DebateVerdict,
    ScenarioKind,
    Severity,
    ThesisStatus,
    TurnRole,
    Unit,
    WatchdogStatus,
)
from copilot.common.errors import MissingEvidenceError
from copilot.common.ids import new_ulid
from copilot.common.logging import get_logger
from copilot.db.models import (
    Alert,
    Claim,
    DebateSession,
    DebateTurn,
    Scenario,
    ScenarioResult,
    Thesis,
    WatchdogRun,
)
from copilot.db.repositories.base import BaseRepository
from copilot.db.types import utcnow

log = get_logger(__name__)


class DebateRepository(BaseRepository[DebateSession]):
    model = DebateSession
    entity_name = "debate_session"

    def open_session(self, thesis: Thesis, *, run_id: str | None = None) -> DebateSession:
        session = DebateSession(
            thesis_id=thesis.id,
            thesis_version=thesis.version,
            run_id=run_id or new_ulid(),
            started_at=utcnow(),
            as_of=thesis.as_of,
        )
        return self.add(session)

    def add_turn(
        self,
        session: DebateSession,
        *,
        agent: AgentName,
        role: TurnRole,
        content: str,
        seq: int | None = None,
        tools_called: list[Any] | None = None,
        evidence_ids: Sequence[str] | None = None,
        verifier_status: ClaimStatus | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        context_hash: str | None = None,
    ) -> DebateTurn:
        if seq is None:
            seq = (
                self.session.execute(
                    select(DebateTurn.seq)
                    .where(DebateTurn.session_id == session.id)
                    .order_by(DebateTurn.seq.desc())
                    .limit(1)
                ).scalar()
                or 0
            ) + 1
        turn = DebateTurn(
            session_id=session.id,
            seq=seq,
            agent=agent,
            role=role,
            content=content,
            tools_called_json=tools_called,
            evidence_ids=list(evidence_ids) if evidence_ids else None,
            verifier_status=verifier_status,
            model=model,
            prompt_version=prompt_version,
            context_hash=context_hash,
            as_of=session.as_of,
        )
        return DebateTurnRepository(self.session).add(
            turn, evidence_ids=evidence_ids, audit=False
        )

    def close_session(
        self,
        session: DebateSession,
        *,
        verdict: DebateVerdict,
        counter_argument: str | None = None,
        weakest_assumption_id: str | None = None,
        breaking_scenario_id: str | None = None,
        confirmation_bias_score: Decimal | None = None,
        bias_rationale: str | None = None,
        cost_usd: Decimal | None = None,
    ) -> DebateSession:
        """Fecha a rodada.

        RF-27 / AC-15: sem contra-argumento com evidencia, o veredito e
        INCONCLUSIVA — e a aprovacao continua bloqueada.
        """
        if verdict is DebateVerdict.APROVAVEL and not counter_argument:
            verdict = DebateVerdict.INCONCLUSIVA
            bias_rationale = (
                (bias_rationale or "")
                + " Rodada marcada INCONCLUSIVA: nenhum contra-argumento produzido (RF-27)."
            ).strip()
        return self.update(
            session,
            verdict=verdict,
            counter_argument=counter_argument,
            weakest_assumption_id=weakest_assumption_id,
            breaking_scenario_id=breaking_scenario_id,
            confirmation_bias_score=confirmation_bias_score,
            bias_rationale=bias_rationale,
            cost_usd=cost_usd,
            ended_at=utcnow(),
            note=f"veredito={verdict.value}",
        )

    def for_thesis(self, thesis_id: str) -> list[DebateSession]:
        return self.list(thesis_id=thesis_id, order_by=DebateSession.created_at.asc())


class DebateTurnRepository(BaseRepository[DebateTurn]):
    model = DebateTurn
    entity_name = "debate_turn"


class ClaimRepository(BaseRepository[Claim]):
    model = Claim
    entity_name = "claim"

    def record(
        self,
        *,
        claim_text: str,
        claim_type: ClaimType,
        status: ClaimStatus,
        thesis_id: str | None = None,
        turn_id: str | None = None,
        alert_id: str | None = None,
        value_numeric: Decimal | None = None,
        unit: Unit | None = None,
        evidence_id: str | None = None,
        tolerance_applied: Decimal | None = None,
        reason: str | None = None,
    ) -> Claim:
        """Persiste o veredito do Claim Verifier.

        Invariante local: afirmacao NUMERICA ou FACTUAL marcada VERIFIED sem
        `evidence_id` e incoerente e nunca deve ser gravada (P6).
        """
        if (
            status is ClaimStatus.VERIFIED
            and claim_type in {ClaimType.NUMERICA, ClaimType.FACTUAL}
            and not evidence_id
        ):
            raise MissingEvidenceError(
                "Afirmacao verificada exige `evidence_id`. Sem lastro o status "
                "correto e BLOCKED (P6 / RF-51)."
            )
        claim = Claim(
            claim_text=claim_text,
            claim_type=claim_type,
            status=status,
            thesis_id=thesis_id,
            turn_id=turn_id,
            alert_id=alert_id,
            value_numeric=value_numeric,
            unit=unit,
            evidence_id=evidence_id,
            tolerance_applied=tolerance_applied,
            reason=reason,
        )
        return self.add(claim, audit=False)

    def blocking_for_thesis(self, thesis_id: str) -> list[Claim]:
        return self.list(thesis_id=thesis_id, status=list(BLOCKING_CLAIM_STATUSES))


class ScenarioRepository(BaseRepository[Scenario]):
    model = Scenario
    entity_name = "scenario"

    def create(
        self,
        *,
        name: str,
        kind: ScenarioKind,
        definition: dict[str, Any],
        description: str | None = None,
        probability_weight: Decimal | None = None,
        source_evidence_id: str | None = None,
    ) -> Scenario:
        scenario = Scenario(
            name=name,
            kind=kind,
            definition_json=definition,
            description=description,
            probability_weight=probability_weight,
            source_evidence_id=source_evidence_id,
        )
        return self.add(scenario)

    def by_name(self, name: str) -> Scenario | None:
        return self.session.execute(
            self.scoped().where(Scenario.name == name)
        ).scalars().first()

    def hydrological_count(self, thesis_id: str) -> int:
        """Quantos cenarios hidrologicos distintos a tese tem (RF-53 / AC-42)."""
        stmt = (
            select(ScenarioResult.scenario_id)
            .join(Scenario, Scenario.id == ScenarioResult.scenario_id)
            .where(
                ScenarioResult.thesis_id == thesis_id,
                ScenarioResult.dataset_kind == self.ctx.dataset_kind,
                Scenario.kind == ScenarioKind.HIDROLOGICO,
            )
            .distinct()
        )
        return len(list(self.session.execute(stmt).scalars()))


class ScenarioResultRepository(BaseRepository[ScenarioResult]):
    model = ScenarioResult
    entity_name = "scenario_result"

    def record(
        self,
        *,
        thesis: Thesis,
        scenario: Scenario,
        quant_run_id: str,
        pnl_p5: Decimal | None = None,
        pnl_p50: Decimal | None = None,
        pnl_p95: Decimal | None = None,
        var_impact: Decimal | None = None,
        thesis_delta: str | None = None,
    ) -> ScenarioResult:
        if not quant_run_id:
            raise MissingEvidenceError(
                "scenario_result exige `quant_run_id`: o numero vem do motor quant, "
                "nunca do LLM (P5)."
            )
        result = ScenarioResult(
            thesis_id=thesis.id,
            scenario_id=scenario.id,
            quant_run_id=quant_run_id,
            pnl_p5=pnl_p5,
            pnl_p50=pnl_p50,
            pnl_p95=pnl_p95,
            var_impact=var_impact,
            thesis_delta=thesis_delta,
            as_of=thesis.as_of,
        )
        return self.add(result)


class WatchdogRepository(BaseRepository[WatchdogRun]):
    model = WatchdogRun
    entity_name = "watchdog_run"

    def start(
        self, *, trigger_source: str = "agendado", as_of: date | None = None
    ) -> WatchdogRun:
        run = WatchdogRun(started_at=utcnow(), trigger_source=trigger_source, as_of=as_of)
        return self.add(run, action=AuditAction.WATCHDOG_RUN)

    def finish(
        self,
        run: WatchdogRun,
        *,
        theses_checked: int = 0,
        assumptions_checked: int = 0,
        rules_evaluated: int = 0,
        sources_ok: Sequence[str] | None = None,
        sources_failed: Sequence[str] | None = None,
        notes: str | None = None,
    ) -> WatchdogRun:
        """Fecha a execucao. Fonte que falhou torna o run PARCIAL (RF-36 / AC-23)."""
        failed = list(sources_failed or [])
        status = WatchdogStatus.OK if not failed else WatchdogStatus.PARCIAL
        if failed and not (sources_ok or []):
            status = WatchdogStatus.FALHA
        return self.update(
            run,
            status=status,
            ended_at=utcnow(),
            theses_checked=theses_checked,
            assumptions_checked=assumptions_checked,
            rules_evaluated=rules_evaluated,
            sources_ok=list(sources_ok or []),
            sources_failed=failed,
            notes=notes,
            action=AuditAction.WATCHDOG_RUN,
        )

    def recent(self, limit: int = 20) -> list[WatchdogRun]:
        return self.list(limit=limit, order_by=WatchdogRun.started_at.desc())


class AlertRepository(BaseRepository[Alert]):
    model = Alert
    entity_name = "alert"

    def raise_alert(
        self,
        *,
        thesis_id: str,
        severity: Severity,
        alert_kind: AlertKind,
        message: str,
        evidence_id: str,
        watchdog_run_id: str | None = None,
        assumption_id: str | None = None,
        trigger_rule_id: str | None = None,
        observed_value: Decimal | None = None,
        expected_value: Decimal | None = None,
        delta: Decimal | None = None,
        unit: Unit | None = None,
        dedup_key: str | None = None,
        as_of: date | None = None,
    ) -> Alert:
        """Emite alerta. Sem `evidence_id` nao existe alerta (RF-33).

        Deduplicacao: mesmo `dedup_key` em aberto incrementa o contador em vez
        de criar um alerta novo (RF-37 / AC-24).
        """
        if not evidence_id:
            raise MissingEvidenceError(
                "Alerta exige `evidence_id`: o dado que disparou precisa ser rastreavel "
                "(RF-33 / C3)."
            )
        if dedup_key:
            existing = self.session.execute(
                self.scoped().where(
                    Alert.dedup_key == dedup_key,
                    Alert.acknowledged_at.is_(None),
                )
            ).scalars().first()
            if existing is not None:
                return self.update(
                    existing,
                    occurrence_count=existing.occurrence_count + 1,
                    note="alerta repetido suprimido (RF-37)",
                )

        alert = Alert(
            watchdog_run_id=watchdog_run_id,
            thesis_id=thesis_id,
            assumption_id=assumption_id,
            trigger_rule_id=trigger_rule_id,
            severity=severity,
            alert_kind=alert_kind,
            message=message,
            observed_value=observed_value,
            expected_value=expected_value,
            delta=delta,
            unit=unit,
            evidence_id=evidence_id,
            dedup_key=dedup_key,
            as_of=as_of,
        )
        created = self.add(alert, action=AuditAction.ALERT_RAISED, evidence_ids=[evidence_id])
        log.warning(
            "alerta_emitido",
            extra={
                "thesis_id": thesis_id,
                "severity": severity.value,
                "alert_kind": alert_kind.value,
            },
        )
        return created

    def acknowledge(
        self,
        alert: Alert,
        *,
        decision: AlertDecision,
        rationale: str,
        by: str | None = None,
    ) -> Alert:
        """Reconhecimento com decisao obrigatoria e justificativa (RF-34 / AC-25)."""
        if not rationale or not rationale.strip():
            raise ValueError(
                "Reconhecer alerta exige justificativa registrada (RF-34 / AC-25)."
            )
        return self.update(
            alert,
            acknowledged_by=by or self.ctx.actor,
            acknowledged_at=utcnow(),
            decision=decision,
            decision_rationale=rationale,
            action=AuditAction.DECISION,
            note=f"decisao={decision.value}",
        )

    def open_alerts(self, *, thesis_id: str | None = None) -> list[Alert]:
        stmt = self.scoped().where(Alert.acknowledged_at.is_(None))
        if thesis_id is not None:
            stmt = stmt.where(Alert.thesis_id == thesis_id)
        stmt = stmt.order_by(Alert.created_at.desc())
        return list(self.session.execute(stmt).scalars())

    def critical_open(self) -> list[Alert]:
        return [a for a in self.open_alerts() if a.severity is Severity.CRITICO]


__all__ = [
    "AlertRepository",
    "ClaimRepository",
    "DebateRepository",
    "DebateTurnRepository",
    "ScenarioRepository",
    "ScenarioResultRepository",
    "WatchdogRepository",
]
