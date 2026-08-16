"""Trilha de auditoria — DATA_CONTRACT secao 2.15.

Append-only em tres camadas (C7 / AC-61):

1. o repositorio so expoe `append()`;
2. um listener do SQLAlchemy aborta UPDATE e DELETE no mapeador;
3. triggers no banco abortam UPDATE e DELETE mesmo por fora da aplicacao.

A camada 3 e a que vale na defesa: nao depende do codigo da aplicacao.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import JSON, Date, Index, String, Text, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from copilot.common.enums import ActorType, AuditAction
from copilot.common.errors import AppendOnlyViolation
from copilot.common.ids import ULID_LENGTH, new_ulid
from copilot.db.base import Base, TimestampMixin
from copilot.db.types import EnumText, enum_check


class AuditLog(TimestampMixin, Base):
    """Registro imutavel de uma acao.

    Sem `dataset_kind`: a trilha e transversal e cobre DEMO e REAL. O escopo do
    registro auditado fica em `after_json`/`before_json`.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(ULID_LENGTH), primary_key=True, default=new_ulid)

    actor_type: Mapped[ActorType] = mapped_column(EnumText(ActorType), nullable=False)
    actor: Mapped[str] = mapped_column(String(160), nullable=False)
    agent_version: Mapped[str | None] = mapped_column(String(40), nullable=True)

    action: Mapped[AuditAction] = mapped_column(
        EnumText(AuditAction), nullable=False, index=True
    )
    entity: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(ULID_LENGTH), nullable=True, index=True)

    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON(), nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON(), nullable=True)

    run_id: Mapped[str | None] = mapped_column(String(ULID_LENGTH), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    evidence_ids: Mapped[list[str] | None] = mapped_column(JSON(), nullable=True)

    as_of: Mapped[date | None] = mapped_column(Date(), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text(), nullable=True)

    __table_args__ = (
        enum_check("actor_type", ActorType),
        enum_check("action", AuditAction),
        Index("ix_audit_log_entity_pair", "entity", "entity_id"),
    )


def _block_mutation(_mapper: Any, _connection: Any, target: AuditLog) -> None:
    raise AppendOnlyViolation(
        f"audit_log e append-only: alteracao proibida (id={target.id}). "
        "Registre um novo evento em vez de editar o historico (C7)."
    )


event.listen(AuditLog, "before_update", _block_mutation, propagate=True)
event.listen(AuditLog, "before_delete", _block_mutation, propagate=True)


@event.listens_for(Session, "before_flush")
def _guard_audit_log(session: Session, _flush_context: Any, _instances: Any) -> None:
    """Aborta antes do flush, com mensagem clara, se alguem tentar mutar a trilha."""
    for obj in session.dirty:
        if isinstance(obj, AuditLog) and session.is_modified(obj, include_collections=False):
            raise AppendOnlyViolation(
                f"audit_log e append-only: UPDATE bloqueado (id={obj.id})."
            )
    for obj in session.deleted:
        if isinstance(obj, AuditLog):
            raise AppendOnlyViolation(
                f"audit_log e append-only: DELETE bloqueado (id={obj.id})."
            )


__all__ = ["AuditLog"]
