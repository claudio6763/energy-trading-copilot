"""Escrita e leitura da trilha de auditoria (RF-55).

Toda gravacao de dominio passa por aqui. O ator, o `run_id` e o `as_of` vem do
contexto ativo — nunca sao passados a mao, para nao existir caminho em que a
auditoria fique com dados inconsistentes com a operacao.
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from copilot.common.context import require_context
from copilot.common.enums import AuditAction
from copilot.common.logging import get_logger
from copilot.db.base import Base
from copilot.db.models.audit import AuditLog

log = get_logger(__name__)


def snapshot(obj: Base | None, *, exclude: set[str] | None = None) -> dict[str, Any] | None:
    """Estado serializavel de uma entidade, para `before_json`/`after_json`."""
    if obj is None:
        return None
    return obj.to_dict(exclude=exclude)


def append(
    session: Session,
    *,
    action: AuditAction,
    entity: str,
    entity_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    evidence_ids: Sequence[str] | None = None,
    note: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> AuditLog:
    """Acrescenta um evento a trilha. Nunca atualiza nem apaga (C7)."""
    ctx = require_context()
    entry = AuditLog(
        actor_type=ctx.actor_type,
        actor=ctx.actor,
        agent_version=ctx.agent_version,
        action=action,
        entity=entity,
        entity_id=entity_id,
        before_json=before,
        after_json=after,
        run_id=ctx.run_id,
        model=model,
        prompt_version=prompt_version,
        evidence_ids=list(evidence_ids) if evidence_ids else None,
        as_of=ctx.as_of,
        note=note,
    )
    session.add(entry)
    log.debug(
        "audit_append",
        extra={"action": action.value, "entity": entity, "entity_id": entity_id},
    )
    return entry


def history(
    session: Session,
    *,
    entity: str | None = None,
    entity_id: str | None = None,
    run_id: str | None = None,
    limit: int = 200,
) -> list[AuditLog]:
    """Historico em ordem cronologica. Base do navegador de auditoria (AC-60)."""
    stmt = select(AuditLog)
    if entity is not None:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if run_id is not None:
        stmt = stmt.where(AuditLog.run_id == run_id)
    stmt = stmt.order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).limit(limit)
    return list(session.execute(stmt).scalars())


def thesis_timeline(session: Session, thesis_id: str, limit: int = 500) -> list[AuditLog]:
    """Linha do tempo de uma tese, incluindo seus filhos diretos (AC-60)."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_id == thesis_id)
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


__all__ = ["append", "history", "snapshot", "thesis_timeline"]
