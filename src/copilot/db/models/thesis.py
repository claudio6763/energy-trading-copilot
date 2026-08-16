"""Tese e seus componentes — DATA_CONTRACT secoes 2.3 a 2.7.

Este e o coracao da funcao *Registrar*. Tres decisoes de schema carregam
requisito direto do case:

* `assumption.evidence_id` e NOT NULL — premissa sem lastro nao entra (AC-02).
* `trigger_rule` guarda metrica, operador, limiar e janela — gatilho em texto
  livre nao e gatilho, porque o Watchdog nao consegue avalia-lo (AC-03).
* o resultado esperado e um intervalo P5/P50/P95, nunca um numero unico (AC-04).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from copilot.common.enums import (
    AssumptionKind,
    AssumptionStatus,
    Criticality,
    DatasetKind,
    Instrument,
    Likelihood,
    RiskCategory,
    RuleOperator,
    RuleType,
    Severity,
    Side,
    Submarket,
    ThesisDirection,
    ThesisStatus,
    Unit,
)
from copilot.common.ids import ULID_LENGTH
from copilot.db.base import AsOfDomainBase
from copilot.db.types import EnumText, Energy, Money, Observation, Price, UTCDateTime, enum_check


class Thesis(AsOfDomainBase):
    """Tese registrada. Imutavel apos APROVADA: editar cria nova versao (RF-09)."""

    __tablename__ = "thesis"

    version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    parent_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("thesis.id", ondelete="SET NULL"), nullable=True
    )
    change_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Ate 5 linhas (regra da Entrega 2). Validado no repositorio.
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    direction: Mapped[ThesisDirection] = mapped_column(
        EnumText(ThesisDirection), nullable=False
    )
    product: Mapped[str] = mapped_column(String(120), nullable=False)
    submarket: Mapped[Submarket] = mapped_column(EnumText(Submarket), nullable=False)

    delivery_start: Mapped[date | None] = mapped_column(Date(), nullable=True)
    delivery_end: Mapped[date | None] = mapped_column(Date(), nullable=True)
    horizon_days: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    review_date: Mapped[date | None] = mapped_column(Date(), nullable=True)

    status: Mapped[ThesisStatus] = mapped_column(
        EnumText(ThesisStatus), nullable=False, default=ThesisStatus.RASCUNHO, index=True
    )

    #: Resultado esperado como intervalo (RF-08 / AC-04).
    expected_pnl_p5: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    expected_pnl_p50: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    expected_pnl_p95: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)

    var_consumed: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    #: P8 — limite de R$ 50 milhoes. Verificado por codigo (RF-54).
    var_limit: Mapped[Decimal] = mapped_column(
        Money(), nullable=False, default=Decimal("50000000.00")
    )

    author: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Resposta escrita do trader a premissa mais fragil (RF-26 / AC-17).
    trader_response: Mapped[str | None] = mapped_column(Text(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    assumptions: Mapped[list["Assumption"]] = relationship(
        back_populates="thesis", cascade="all, delete-orphan"
    )
    positions: Mapped[list["Position"]] = relationship(
        back_populates="thesis", cascade="all, delete-orphan"
    )
    trigger_rules: Mapped[list["TriggerRule"]] = relationship(
        back_populates="thesis", cascade="all, delete-orphan"
    )
    risk_items: Mapped[list["RiskItem"]] = relationship(
        back_populates="thesis", cascade="all, delete-orphan"
    )

    __table_args__ = (
        enum_check("direction", ThesisDirection),
        enum_check("submarket", Submarket),
        enum_check("status", ThesisStatus),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_thesis_scope", "dataset_kind", "as_of"),
        Index("ix_thesis_lineage", "parent_id", "version"),
    )

    @property
    def var_within_limit(self) -> bool:
        """P8/RF-54. Verificacao em codigo, nunca em prompt."""
        if self.var_consumed is None:
            return True
        return self.var_consumed <= self.var_limit


class Assumption(AsOfDomainBase):
    """Premissa mensuravel. `metric_key` e o que torna a vigilancia automatica."""

    __tablename__ = "assumption"

    thesis_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("thesis.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[AssumptionKind] = mapped_column(EnumText(AssumptionKind), nullable=False)
    statement: Mapped[str] = mapped_column(Text(), nullable=False)
    #: Sem `metric_key` a premissa e aceita, mas fica NAO_MONITORAVEL (RF-32).
    metric_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    expected_value: Mapped[Decimal | None] = mapped_column(Observation(), nullable=True)
    tolerance_low: Mapped[Decimal | None] = mapped_column(Observation(), nullable=True)
    tolerance_high: Mapped[Decimal | None] = mapped_column(Observation(), nullable=True)
    unit: Mapped[Unit | None] = mapped_column(EnumText(Unit), nullable=True)
    #: C3 / P6 / AC-02 — NOT NULL de proposito.
    evidence_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("evidence.id", ondelete="RESTRICT"), nullable=False
    )
    criticality: Mapped[Criticality] = mapped_column(
        EnumText(Criticality), nullable=False, default=Criticality.MEDIA
    )
    status: Mapped[AssumptionStatus] = mapped_column(
        EnumText(AssumptionStatus), nullable=False, default=AssumptionStatus.VALIDA, index=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    thesis: Mapped[Thesis] = relationship(back_populates="assumptions")

    __table_args__ = (
        enum_check("kind", AssumptionKind),
        enum_check("criticality", Criticality),
        enum_check("status", AssumptionStatus),
        enum_check("unit", Unit),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_assumption_scope", "dataset_kind", "as_of"),
    )

    @property
    def is_monitorable(self) -> bool:
        return bool(self.metric_key) and (
            self.tolerance_low is not None or self.tolerance_high is not None
        )


class Position(AsOfDomainBase):
    """Dimensionamento da tese."""

    __tablename__ = "position"

    thesis_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("thesis.id", ondelete="CASCADE"), nullable=False
    )
    instrument: Mapped[Instrument] = mapped_column(EnumText(Instrument), nullable=False)
    submarket: Mapped[Submarket] = mapped_column(EnumText(Submarket), nullable=False)
    side: Mapped[Side] = mapped_column(EnumText(Side), nullable=False)
    volume_mwh: Mapped[Decimal] = mapped_column(Energy(), nullable=False)
    price_ref: Mapped[Decimal] = mapped_column(Price(), nullable=False)
    delivery_start: Mapped[date] = mapped_column(Date(), nullable=False)
    delivery_end: Mapped[date] = mapped_column(Date(), nullable=False)
    notional: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    #: Sem PII. Apelido de contraparte, quando houver.
    counterparty: Mapped[str | None] = mapped_column(String(120), nullable=True)
    var_contribution: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    evidence_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("evidence.id", ondelete="RESTRICT"), nullable=False
    )

    thesis: Mapped[Thesis] = relationship(back_populates="positions")

    __table_args__ = (
        enum_check("instrument", Instrument),
        enum_check("submarket", Submarket),
        enum_check("side", Side),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_position_scope", "dataset_kind", "as_of"),
    )


class TriggerRule(AsOfDomainBase):
    """Gatilho de saida, condicao de invalidacao ou alerta — avaliavel por maquina."""

    __tablename__ = "trigger_rule"

    thesis_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("thesis.id", ondelete="CASCADE"), nullable=False
    )
    rule_type: Mapped[RuleType] = mapped_column(EnumText(RuleType), nullable=False, index=True)
    metric_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    operator: Mapped[RuleOperator] = mapped_column(EnumText(RuleOperator), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Observation(), nullable=False)
    unit: Mapped[Unit] = mapped_column(EnumText(Unit), nullable=False)
    #: Janela de avaliacao: `spot`, `1d`, `7d`, `30d`.
    #: Nome `eval_window` porque `window` e palavra reservada no PostgreSQL.
    eval_window: Mapped[str] = mapped_column(String(20), nullable=False, default="spot")
    severity: Mapped[Severity] = mapped_column(
        EnumText(Severity), nullable=False, default=Severity.ATENCAO
    )
    active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)

    thesis: Mapped[Thesis] = relationship(back_populates="trigger_rules")

    __table_args__ = (
        enum_check("rule_type", RuleType),
        enum_check("operator", RuleOperator),
        enum_check("severity", Severity),
        enum_check("unit", Unit),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_trigger_rule_scope", "dataset_kind", "as_of"),
        Index("ix_trigger_rule_watch", "active", "metric_key"),
    )


class RiskItem(AsOfDomainBase):
    """Risco identificado. `evidence_id` e opcional: risco qualitativo e OPINIAO."""

    __tablename__ = "risk_item"

    thesis_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("thesis.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[RiskCategory] = mapped_column(EnumText(RiskCategory), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    severity: Mapped[Severity] = mapped_column(EnumText(Severity), nullable=False)
    likelihood: Mapped[Likelihood] = mapped_column(EnumText(Likelihood), nullable=False)
    mitigation: Mapped[str | None] = mapped_column(Text(), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )

    thesis: Mapped[Thesis] = relationship(back_populates="risk_items")

    __table_args__ = (
        enum_check("category", RiskCategory),
        enum_check("severity", Severity),
        enum_check("likelihood", Likelihood),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_risk_item_scope", "dataset_kind", "as_of"),
    )


__all__ = ["Assumption", "Position", "RiskItem", "Thesis", "TriggerRule"]
