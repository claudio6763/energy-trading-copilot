"""Debate adversarial e verificacao de afirmacoes — DATA_CONTRACT 2.11 e 2.12.

Sprint 1 entrega apenas o schema e as invariantes de banco. A conducao do debate
(Sprint 5) e o Claim Verifier (Sprint 4) consomem estas tabelas.

Invariante que ja vale aqui: uma `claim` com status CONTRADICTED ou BLOCKED
vinculada a uma tese impede a transicao para APROVADA (RF-51). A verificacao e
feita pelo ThesisRepository.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from copilot.common.enums import (
    AgentName,
    ClaimStatus,
    ClaimType,
    DatasetKind,
    DebateVerdict,
    TurnRole,
    Unit,
)
from copilot.common.ids import ULID_LENGTH
from copilot.db.base import AsOfDomainBase, DomainBase
from copilot.db.types import EnumText, Money, Observation, Percent, UTCDateTime, enum_check


class DebateSession(AsOfDomainBase):
    """Uma rodada de debate sobre uma versao de tese."""

    __tablename__ = "debate_session"

    thesis_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("thesis.id", ondelete="CASCADE"), nullable=False
    )
    thesis_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    run_id: Mapped[str] = mapped_column(String(ULID_LENGTH), nullable=False, index=True)
    verdict: Mapped[DebateVerdict | None] = mapped_column(
        EnumText(DebateVerdict), nullable=True, index=True
    )
    #: Premissa mais fragil apontada pelo debate (RF-21 / AC-11).
    weakest_assumption_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("assumption.id", ondelete="SET NULL"), nullable=True
    )
    #: Cenario que quebra a posicao (RF-21 / AC-11).
    breaking_scenario_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("scenario.id", ondelete="SET NULL"), nullable=True
    )
    counter_argument: Mapped[str | None] = mapped_column(Text(), nullable=True)
    #: Criterio numerico de vies de confirmacao (RF-22). Calculado em codigo.
    confirmation_bias_score: Mapped[Decimal | None] = mapped_column(Percent(), nullable=True)
    bias_rationale: Mapped[str | None] = mapped_column(Text(), nullable=True)
    trader_response: Mapped[str | None] = mapped_column(Text(), nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    turns: Mapped[list["DebateTurn"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="DebateTurn.seq"
    )

    __table_args__ = (
        enum_check("verdict", DebateVerdict),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_debate_session_scope", "dataset_kind", "as_of"),
        Index("ix_debate_session_thesis", "thesis_id", "thesis_version"),
    )


class DebateTurn(AsOfDomainBase):
    """Uma fala de agente na rodada, com as ferramentas que chamou."""

    __tablename__ = "debate_turn"

    session_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("debate_session.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer(), nullable=False)
    agent: Mapped[AgentName] = mapped_column(EnumText(AgentName), nullable=False)
    role: Mapped[TurnRole] = mapped_column(EnumText(TurnRole), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    tools_called_json: Mapped[list[Any] | None] = mapped_column(JSON(), nullable=True)
    #: Lista de evidence_id. JSON em vez de ARRAY para funcionar nos dois dialetos.
    evidence_ids: Mapped[list[str] | None] = mapped_column(JSON(), nullable=True)
    verifier_status: Mapped[ClaimStatus | None] = mapped_column(
        EnumText(ClaimStatus), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Prova de isolamento do Agente de Risco (AC-13): hash do contexto recebido.
    context_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    session: Mapped[DebateSession] = relationship(back_populates="turns")

    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_debate_turn_seq"),
        enum_check("agent", AgentName),
        enum_check("role", TurnRole),
        enum_check("verifier_status", ClaimStatus),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_debate_turn_scope", "dataset_kind", "as_of"),
    )


class Claim(DomainBase):
    """Afirmacao extraida de uma saida de agente e seu veredito de verificacao.

    Numero ou fato sem `evidence_id` termina como BLOCKED — e isso trava a
    aprovacao da tese (RF-51 / AC-16 / AC-50).
    """

    __tablename__ = "claim"

    turn_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("debate_turn.id", ondelete="CASCADE"), nullable=True
    )
    alert_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("alert.id", ondelete="CASCADE"), nullable=True
    )
    #: Denormalizado de proposito: permite checar bloqueio sem varrer o debate.
    thesis_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("thesis.id", ondelete="CASCADE"), nullable=True, index=True
    )
    claim_text: Mapped[str] = mapped_column(Text(), nullable=False)
    claim_type: Mapped[ClaimType] = mapped_column(EnumText(ClaimType), nullable=False)
    value_numeric: Mapped[Decimal | None] = mapped_column(Observation(), nullable=True)
    unit: Mapped[Unit | None] = mapped_column(EnumText(Unit), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ClaimStatus] = mapped_column(
        EnumText(ClaimStatus), nullable=False, index=True
    )
    tolerance_applied: Mapped[Decimal | None] = mapped_column(Observation(), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)

    __table_args__ = (
        enum_check("claim_type", ClaimType),
        enum_check("status", ClaimStatus),
        enum_check("unit", Unit),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_claim_blocking", "thesis_id", "status"),
    )


__all__ = ["Claim", "DebateSession", "DebateTurn"]
