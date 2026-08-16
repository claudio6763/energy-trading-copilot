"""Repositorio da tese — o nucleo da funcao *Registrar*.

Aqui vivem as invariantes que o case exige e que nao podem depender de prompt:

* premissa sem `evidence_id` nao entra (AC-02);
* gatilho precisa ser avaliavel por maquina (AC-03);
* resultado esperado e intervalo P5/P50/P95 (AC-04);
* tese aprovada e imutavel; editar cria nova versao (AC-05);
* transicao de estado segue a maquina declarada em `THESIS_TRANSITIONS` (RF-10);
* aprovacao bloqueada por VaR acima do limite (AC-14) ou por `claim` bloqueante (RF-51).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from copilot.audit import trail
from copilot.common.enums import (
    BLOCKING_CLAIM_STATUSES,
    AssumptionKind,
    AssumptionStatus,
    AuditAction,
    Criticality,
    Instrument,
    Likelihood,
    RiskCategory,
    RuleOperator,
    RuleType,
    Severity,
    Side,
    Submarket,
    THESIS_TRANSITIONS,
    ThesisDirection,
    ThesisStatus,
    Unit,
    IMMUTABLE_THESIS_STATUSES,
)
from copilot.common.errors import (
    ImmutableThesisError,
    InvalidStatusTransition,
    MissingEvidenceError,
    VarLimitExceeded,
)
from copilot.common.logging import get_logger
from copilot.config.settings import get_settings
from copilot.db.models import Assumption, Claim, Position, RiskItem, Thesis, TriggerRule
from copilot.db.repositories.base import BaseRepository
from copilot.db.repositories.catalog import EvidenceRepository

log = get_logger(__name__)

MAX_SUMMARY_LINES = 5


class ThesisRepository(BaseRepository[Thesis]):
    model = Thesis
    entity_name = "thesis"

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self.evidence = EvidenceRepository(session)

    # ------------------------------------------------------------- criacao
    def create_draft(
        self,
        *,
        title: str,
        summary: str,
        direction: ThesisDirection,
        product: str,
        submarket: Submarket,
        author: str,
        delivery_start: date | None = None,
        delivery_end: date | None = None,
        horizon_days: int | None = None,
        review_date: date | None = None,
        expected_pnl_p5: Decimal | None = None,
        expected_pnl_p50: Decimal | None = None,
        expected_pnl_p95: Decimal | None = None,
        var_consumed: Decimal | None = None,
        var_limit: Decimal | None = None,
        as_of: date | None = None,
    ) -> Thesis:
        """Cria um rascunho de tese."""
        self._validate_summary(summary)
        self._validate_expected_range(expected_pnl_p5, expected_pnl_p50, expected_pnl_p95)
        limit = var_limit if var_limit is not None else get_settings().var_limit_brl
        thesis = Thesis(
            title=title,
            summary=summary,
            direction=direction,
            product=product,
            submarket=submarket,
            author=author,
            delivery_start=delivery_start,
            delivery_end=delivery_end,
            horizon_days=horizon_days,
            review_date=review_date,
            expected_pnl_p5=expected_pnl_p5,
            expected_pnl_p50=expected_pnl_p50,
            expected_pnl_p95=expected_pnl_p95,
            var_consumed=var_consumed,
            var_limit=limit,
            status=ThesisStatus.RASCUNHO,
            version=1,
            as_of=as_of,
        )
        return self.add(thesis)

    @staticmethod
    def _validate_summary(summary: str) -> None:
        if not summary or not summary.strip():
            raise ValueError("A tese precisa de um resumo.")
        lines = [line for line in summary.strip().splitlines() if line.strip()]
        if len(lines) > MAX_SUMMARY_LINES:
            raise ValueError(
                f"Resumo com {len(lines)} linhas; o case limita a {MAX_SUMMARY_LINES}."
            )

    @staticmethod
    def _validate_expected_range(
        p5: Decimal | None, p50: Decimal | None, p95: Decimal | None
    ) -> None:
        """RF-08 / AC-04: intervalo, nunca numero unico."""
        provided = [value for value in (p5, p50, p95) if value is not None]
        if not provided:
            return
        if len(provided) != 3:
            raise ValueError(
                "Resultado esperado deve ser um intervalo completo P5/P50/P95, "
                "nao um numero unico (RF-08 / AC-04)."
            )
        if not (p5 <= p50 <= p95):  # type: ignore[operator]
            raise ValueError("Intervalo invalido: exige P5 <= P50 <= P95.")

    # ---------------------------------------------------------- componentes
    def add_assumption(
        self,
        thesis: Thesis,
        *,
        kind: AssumptionKind,
        statement: str,
        evidence_id: str,
        metric_key: str | None = None,
        expected_value: Decimal | None = None,
        tolerance_low: Decimal | None = None,
        tolerance_high: Decimal | None = None,
        unit: Unit | None = None,
        criticality: Criticality = Criticality.MEDIA,
    ) -> Assumption:
        """Registra premissa. Sem `evidence_id` valido, nada e gravado (AC-02)."""
        self._assert_mutable(thesis)
        self.evidence.require(evidence_id, field="assumption")
        monitorable = bool(metric_key) and (
            tolerance_low is not None or tolerance_high is not None
        )
        assumption = Assumption(
            thesis_id=thesis.id,
            kind=kind,
            statement=statement,
            metric_key=metric_key,
            expected_value=expected_value,
            tolerance_low=tolerance_low,
            tolerance_high=tolerance_high,
            unit=unit,
            evidence_id=evidence_id,
            criticality=criticality,
            status=AssumptionStatus.VALIDA if monitorable else AssumptionStatus.NAO_MONITORAVEL,
            as_of=thesis.as_of,
        )
        return AssumptionRepository(self.session).add(
            assumption, evidence_ids=[evidence_id]
        )

    def add_position(
        self,
        thesis: Thesis,
        *,
        instrument: Instrument,
        submarket: Submarket,
        side: Side,
        volume_mwh: Decimal,
        price_ref: Decimal,
        delivery_start: date,
        delivery_end: date,
        evidence_id: str,
        notional: Decimal | None = None,
        counterparty: str | None = None,
        var_contribution: Decimal | None = None,
    ) -> Position:
        self._assert_mutable(thesis)
        self.evidence.require(evidence_id, field="position")
        if notional is None:
            notional = (volume_mwh * price_ref).quantize(Decimal("0.01"))
        position = Position(
            thesis_id=thesis.id,
            instrument=instrument,
            submarket=submarket,
            side=side,
            volume_mwh=volume_mwh,
            price_ref=price_ref,
            delivery_start=delivery_start,
            delivery_end=delivery_end,
            notional=notional,
            counterparty=counterparty,
            var_contribution=var_contribution,
            evidence_id=evidence_id,
            as_of=thesis.as_of,
        )
        return PositionRepository(self.session).add(position, evidence_ids=[evidence_id])

    def add_trigger_rule(
        self,
        thesis: Thesis,
        *,
        rule_type: RuleType,
        metric_key: str,
        operator: RuleOperator,
        threshold: Decimal,
        unit: Unit,
        eval_window: str = "spot",
        severity: Severity = Severity.ATENCAO,
        description: str | None = None,
    ) -> TriggerRule:
        """Gatilho avaliavel por maquina. Texto livre nao e aceito (AC-03)."""
        self._assert_mutable(thesis)
        if not metric_key or not metric_key.strip():
            raise ValueError(
                "Gatilho exige `metric_key`: sem serie mensuravel o Watchdog nao "
                "consegue avaliar a regra (RF-06 / AC-03)."
            )
        rule = TriggerRule(
            thesis_id=thesis.id,
            rule_type=rule_type,
            metric_key=metric_key,
            operator=operator,
            threshold=threshold,
            unit=unit,
            eval_window=eval_window,
            severity=severity,
            description=description,
            active=True,
            as_of=thesis.as_of,
        )
        return TriggerRuleRepository(self.session).add(rule)

    def add_risk(
        self,
        thesis: Thesis,
        *,
        category: RiskCategory,
        description: str,
        severity: Severity,
        likelihood: Likelihood,
        mitigation: str | None = None,
        evidence_id: str | None = None,
    ) -> RiskItem:
        """Risco. `evidence_id` e opcional: risco qualitativo e OPINIAO, nao dado."""
        self._assert_mutable(thesis)
        if evidence_id:
            self.evidence.require(evidence_id, field="risk_item")
        risk = RiskItem(
            thesis_id=thesis.id,
            category=category,
            description=description,
            severity=severity,
            likelihood=likelihood,
            mitigation=mitigation,
            evidence_id=evidence_id,
            as_of=thesis.as_of,
        )
        return RiskItemRepository(self.session).add(
            risk, evidence_ids=[evidence_id] if evidence_id else None
        )

    # ---------------------------------------------------------- imutabilidade
    @staticmethod
    def _assert_mutable(thesis: Thesis) -> None:
        if thesis.status in IMMUTABLE_THESIS_STATUSES:
            raise ImmutableThesisError(
                f"Tese {thesis.id} esta em {thesis.status.value} e e imutavel. "
                "Use `new_version(...)` com motivo declarado (RF-09 / AC-05)."
            )

    def new_version(
        self, thesis: Thesis, *, change_reason: str, author: str | None = None
    ) -> Thesis:
        """Cria a versao n+1 copiando os componentes. A versao n fica intacta."""
        if not change_reason or not change_reason.strip():
            raise ValueError("Nova versao exige motivo declarado (RF-09).")
        full = self.get_full(thesis.id) or thesis
        clone = Thesis(
            version=full.version + 1,
            parent_id=full.id,
            change_reason=change_reason,
            title=full.title,
            summary=full.summary,
            direction=full.direction,
            product=full.product,
            submarket=full.submarket,
            delivery_start=full.delivery_start,
            delivery_end=full.delivery_end,
            horizon_days=full.horizon_days,
            review_date=full.review_date,
            status=ThesisStatus.RASCUNHO,
            expected_pnl_p5=full.expected_pnl_p5,
            expected_pnl_p50=full.expected_pnl_p50,
            expected_pnl_p95=full.expected_pnl_p95,
            var_consumed=full.var_consumed,
            var_limit=full.var_limit,
            author=author or full.author,
            as_of=self.ctx.as_of,
        )
        self.add(clone, action=AuditAction.VERSION, note=change_reason)

        for assumption in full.assumptions:
            AssumptionRepository(self.session).add(
                Assumption(
                    thesis_id=clone.id,
                    kind=assumption.kind,
                    statement=assumption.statement,
                    metric_key=assumption.metric_key,
                    expected_value=assumption.expected_value,
                    tolerance_low=assumption.tolerance_low,
                    tolerance_high=assumption.tolerance_high,
                    unit=assumption.unit,
                    evidence_id=assumption.evidence_id,
                    criticality=assumption.criticality,
                    status=assumption.status,
                    as_of=clone.as_of,
                ),
                audit=False,
            )
        for position in full.positions:
            PositionRepository(self.session).add(
                Position(
                    thesis_id=clone.id,
                    instrument=position.instrument,
                    submarket=position.submarket,
                    side=position.side,
                    volume_mwh=position.volume_mwh,
                    price_ref=position.price_ref,
                    delivery_start=position.delivery_start,
                    delivery_end=position.delivery_end,
                    notional=position.notional,
                    counterparty=position.counterparty,
                    var_contribution=position.var_contribution,
                    evidence_id=position.evidence_id,
                    as_of=clone.as_of,
                ),
                audit=False,
            )
        for rule in full.trigger_rules:
            TriggerRuleRepository(self.session).add(
                TriggerRule(
                    thesis_id=clone.id,
                    rule_type=rule.rule_type,
                    metric_key=rule.metric_key,
                    operator=rule.operator,
                    threshold=rule.threshold,
                    unit=rule.unit,
                    window=rule.window,
                    severity=rule.severity,
                    active=rule.active,
                    description=rule.description,
                    as_of=clone.as_of,
                ),
                audit=False,
            )
        for risk in full.risk_items:
            RiskItemRepository(self.session).add(
                RiskItem(
                    thesis_id=clone.id,
                    category=risk.category,
                    description=risk.description,
                    severity=risk.severity,
                    likelihood=risk.likelihood,
                    mitigation=risk.mitigation,
                    evidence_id=risk.evidence_id,
                    as_of=clone.as_of,
                ),
                audit=False,
            )
        self.session.flush()
        return clone

    # -------------------------------------------------------------- estados
    def blocking_claims(self, thesis_id: str) -> list[Claim]:
        """Claims CONTRADICTED/BLOCKED que impedem a aprovacao (RF-51)."""
        stmt = select(Claim).where(
            Claim.thesis_id == thesis_id,
            Claim.dataset_kind == self.ctx.dataset_kind,
            Claim.status.in_(list(BLOCKING_CLAIM_STATUSES)),
        )
        return list(self.session.execute(stmt).scalars())

    def check_var_limit(self, thesis: Thesis) -> None:
        """P8 / RF-54 / AC-43. Verificacao em codigo, nunca por prompt."""
        if thesis.var_consumed is None:
            return
        if thesis.var_consumed > thesis.var_limit:
            raise VarLimitExceeded(
                f"VaR de R$ {thesis.var_consumed} excede o limite de "
                f"R$ {thesis.var_limit} (tese {thesis.id})."
            )

    def set_status(
        self,
        thesis: Thesis,
        new_status: ThesisStatus,
        *,
        note: str | None = None,
        force: bool = False,
    ) -> Thesis:
        """Transicao de estado auditada, com os bloqueios do case aplicados."""
        allowed = THESIS_TRANSITIONS.get(thesis.status, frozenset())
        if new_status not in allowed and not force:
            raise InvalidStatusTransition(
                f"Transicao {thesis.status.value} -> {new_status.value} nao permitida. "
                f"Permitidas: {sorted(s.value for s in allowed) or 'nenhuma'} (RF-10)."
            )

        if new_status is ThesisStatus.APROVADA:
            self.check_var_limit(thesis)
            blocking = self.blocking_claims(thesis.id)
            if blocking:
                raise MissingEvidenceError(
                    f"Aprovacao bloqueada: {len(blocking)} afirmacao(oes) sem lastro ou "
                    "contraditadas pelo Claim Verifier (RF-51)."
                )

        before = trail.snapshot(thesis)
        previous = thesis.status
        thesis.status = new_status
        if new_status is ThesisStatus.APROVADA:
            from copilot.db.types import utcnow

            thesis.approved_at = utcnow()
        if new_status in {ThesisStatus.ENCERRADA, ThesisStatus.INVALIDADA}:
            from copilot.db.types import utcnow

            thesis.closed_at = utcnow()
        self.session.flush()

        trail.append(
            self.session,
            action=(
                AuditAction.APPROVE
                if new_status is ThesisStatus.APROVADA
                else AuditAction.STATUS_CHANGE
            ),
            entity=self.entity_name,
            entity_id=thesis.id,
            before=before,
            after=trail.snapshot(thesis),
            note=note or f"{previous.value} -> {new_status.value}",
        )
        log.info(
            "tese_status_alterado",
            extra={"thesis_id": thesis.id, "de": previous.value, "para": new_status.value},
        )
        return thesis

    # --------------------------------------------------------------- leitura
    def get_full(self, thesis_id: str) -> Thesis | None:
        """Tese com todos os componentes carregados — base do AC-06."""
        stmt = (
            self.scoped()
            .where(Thesis.id == thesis_id)
            .options(
                selectinload(Thesis.assumptions),
                selectinload(Thesis.positions),
                selectinload(Thesis.trigger_rules),
                selectinload(Thesis.risk_items),
            )
        )
        return self.session.execute(stmt).scalars().first()

    def active(self) -> list[Thesis]:
        return self.list(status=ThesisStatus.ATIVA)

    def lineage(self, thesis_id: str) -> list[Thesis]:
        """Cadeia de versoes, da raiz ate a versao informada (AC-60)."""
        chain: list[Thesis] = []
        current = self.get(thesis_id)
        seen: set[str] = set()
        while current is not None and current.id not in seen:
            chain.append(current)
            seen.add(current.id)
            current = self.get(current.parent_id) if current.parent_id else None
        return list(reversed(chain))

    def monitorable_assumptions(self, thesis_id: str) -> list[Assumption]:
        """Premissas que o Watchdog consegue avaliar (Sprint 6)."""
        stmt = select(Assumption).where(
            Assumption.thesis_id == thesis_id,
            Assumption.dataset_kind == self.ctx.dataset_kind,
            Assumption.metric_key.is_not(None),
        )
        return [a for a in self.session.execute(stmt).scalars() if a.is_monitorable]


class AssumptionRepository(BaseRepository[Assumption]):
    model = Assumption
    entity_name = "assumption"


class PositionRepository(BaseRepository[Position]):
    model = Position
    entity_name = "position"


class TriggerRuleRepository(BaseRepository[TriggerRule]):
    model = TriggerRule
    entity_name = "trigger_rule"

    def active_rules(self) -> list[TriggerRule]:
        return self.list(active=True)


class RiskItemRepository(BaseRepository[RiskItem]):
    model = RiskItem
    entity_name = "risk_item"


__all__ = [
    "AssumptionRepository",
    "MAX_SUMMARY_LINES",
    "PositionRepository",
    "RiskItemRepository",
    "ThesisRepository",
    "TriggerRuleRepository",
]
