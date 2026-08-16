"""Watchdog e alertas — DATA_CONTRACT secao 2.13.

Sprint 1 entrega o schema. Dois campos existem por causa de um requisito
especifico e nao devem ser removidos por parecerem redundantes:

* `watchdog_run.sources_failed` e `status=PARCIAL` — fonte indisponivel gera
  alerta de cobertura, nunca silencio (RF-36 / AC-23);
* `alert.evidence_id` NOT NULL — todo alerta aponta o dado que o disparou (RF-33).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from copilot.common.enums import (
    AlertDecision,
    AlertKind,
    DatasetKind,
    Severity,
    Unit,
    WatchdogStatus,
)
from copilot.common.ids import ULID_LENGTH
from copilot.db.base import AsOfDomainBase
from copilot.db.types import EnumText, Observation, UTCDateTime, enum_check


class WatchdogRun(AsOfDomainBase):
    """Uma execucao do Watchdog. Registra tambem o que NAO conseguiu checar."""

    __tablename__ = "watchdog_run"

    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[WatchdogStatus] = mapped_column(
        EnumText(WatchdogStatus), nullable=False, default=WatchdogStatus.OK, index=True
    )
    theses_checked: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    assumptions_checked: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    rules_evaluated: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    sources_ok: Mapped[list[str] | None] = mapped_column(JSON(), nullable=True)
    sources_failed: Mapped[list[str] | None] = mapped_column(JSON(), nullable=True)
    #: `manual` | `agendado` | `evento_dado`.
    #: Nome `trigger_source` porque `trigger` e palavra reservada no PostgreSQL.
    trigger_source: Mapped[str] = mapped_column(String(30), nullable=False, default="agendado")
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)

    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="watchdog_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        enum_check("status", WatchdogStatus),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_watchdog_run_scope", "dataset_kind", "as_of"),
    )


class Alert(AsOfDomainBase):
    """Alerta emitido pelo Watchdog. Sempre com o dado que o disparou."""

    __tablename__ = "alert"

    watchdog_run_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("watchdog_run.id", ondelete="CASCADE"), nullable=True
    )
    thesis_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("thesis.id", ondelete="CASCADE"), nullable=False
    )
    assumption_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("assumption.id", ondelete="SET NULL"), nullable=True
    )
    trigger_rule_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("trigger_rule.id", ondelete="SET NULL"), nullable=True
    )
    severity: Mapped[Severity] = mapped_column(EnumText(Severity), nullable=False, index=True)
    alert_kind: Mapped[AlertKind] = mapped_column(EnumText(AlertKind), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    observed_value: Mapped[Decimal | None] = mapped_column(Observation(), nullable=True)
    expected_value: Mapped[Decimal | None] = mapped_column(Observation(), nullable=True)
    delta: Mapped[Decimal | None] = mapped_column(Observation(), nullable=True)
    unit: Mapped[Unit | None] = mapped_column(EnumText(Unit), nullable=True)
    #: C3 / RF-33 — NOT NULL de proposito.
    evidence_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("evidence.id", ondelete="RESTRICT"), nullable=False
    )
    #: Deduplicacao por janela (RF-37 / AC-24).
    dedup_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    acknowledged_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    decision: Mapped[AlertDecision | None] = mapped_column(
        EnumText(AlertDecision), nullable=True
    )
    decision_rationale: Mapped[str | None] = mapped_column(Text(), nullable=True)

    watchdog_run: Mapped[WatchdogRun | None] = relationship(back_populates="alerts")

    __table_args__ = (
        enum_check("severity", Severity),
        enum_check("alert_kind", AlertKind),
        enum_check("decision", AlertDecision),
        enum_check("unit", Unit),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_alert_scope", "dataset_kind", "as_of"),
        Index("ix_alert_open", "thesis_id", "severity", "acknowledged_at"),
    )

    @property
    def is_open(self) -> bool:
        return self.acknowledged_at is None


__all__ = ["Alert", "WatchdogRun"]
