"""Repositorio base: escopo obrigatorio e auditoria automatica.

Duas garantias que nao dependem de quem escreve a consulta:

* **C5 / RF-57** — todo `select` recebe `dataset_kind = <contexto>`;
* **C6 / RF-58** — todo `select` sobre entidade com data-base recebe
  `as_of <= <contexto>`, impedindo look-ahead.

Quem precisar escapar do escopo deve usar `unscoped()` explicitamente. Isso
existe para migrations e diagnostico, e o uso fica visivel em revisao.
"""

from __future__ import annotations

from typing import Any, Generic, Iterable, Sequence, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from copilot.audit import trail
from copilot.common.context import RunContext, require_context
from copilot.common.enums import AuditAction, DatasetKind
from copilot.common.errors import DatasetKindViolation
from copilot.db.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Acesso escopado a uma entidade."""

    model: type[T]
    entity_name: str

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ ctx
    @property
    def ctx(self) -> RunContext:
        return require_context()

    @property
    def _has_dataset_kind(self) -> bool:
        return "dataset_kind" in self.model.__table__.columns

    @property
    def _has_as_of(self) -> bool:
        return "as_of" in self.model.__table__.columns

    # ---------------------------------------------------------------- query
    def scoped(self, stmt: Select[Any] | None = None) -> Select[Any]:
        """Aplica os predicados obrigatorios de escopo."""
        ctx = self.ctx
        stmt = select(self.model) if stmt is None else stmt
        if self._has_dataset_kind:
            stmt = stmt.where(self.model.dataset_kind == ctx.dataset_kind)
        if self._has_as_of:
            stmt = stmt.where(self.model.as_of <= ctx.as_of)
        return stmt

    def unscoped(self) -> Select[Any]:
        """Consulta sem escopo. Use apenas em diagnostico e manutencao."""
        return select(self.model)

    def get(self, entity_id: str) -> T | None:
        stmt = self.scoped().where(self.model.id == entity_id)
        return self.session.execute(stmt).scalars().first()

    def get_or_raise(self, entity_id: str) -> T:
        obj = self.get(entity_id)
        if obj is None:
            raise LookupError(
                f"{self.entity_name} {entity_id!r} nao encontrado no escopo "
                f"{self.ctx.dataset_kind.value} / as_of<={self.ctx.as_of.isoformat()}"
            )
        return obj

    def list(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        order_by: Any | None = None,
        **filters: Any,
    ) -> list[T]:
        stmt = self.scoped()
        for field, value in filters.items():
            column = getattr(self.model, field)
            if isinstance(value, (list, tuple, set)):
                stmt = stmt.where(column.in_(list(value)))
            else:
                stmt = stmt.where(column == value)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.execute(stmt).scalars())

    def count(self, **filters: Any) -> int:
        stmt = self.scoped(select(func.count()).select_from(self.model))
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        return int(self.session.execute(stmt).scalar_one())

    # ----------------------------------------------------------------- write
    def _stamp(self, obj: T) -> T:
        """Preenche `dataset_kind` e `as_of` a partir do contexto, se ausentes."""
        ctx = self.ctx
        if self._has_dataset_kind:
            current = getattr(obj, "dataset_kind", None)
            if current is None:
                obj.dataset_kind = ctx.dataset_kind
            elif DatasetKind(current) is not ctx.dataset_kind:
                raise DatasetKindViolation(
                    f"{self.entity_name} declarado como {DatasetKind(current).value} "
                    f"dentro de um contexto {ctx.dataset_kind.value} (P9 / RF-57)."
                )
        if self._has_as_of and getattr(obj, "as_of", None) is None:
            obj.as_of = ctx.as_of
        return obj

    def add(
        self,
        obj: T,
        *,
        action: AuditAction = AuditAction.CREATE,
        note: str | None = None,
        evidence_ids: Sequence[str] | None = None,
        audit: bool = True,
    ) -> T:
        """Persiste e audita. `flush` garante o id antes do registro na trilha."""
        self._stamp(obj)
        self.session.add(obj)
        self.session.flush()
        if audit:
            trail.append(
                self.session,
                action=action,
                entity=self.entity_name,
                entity_id=getattr(obj, "id", None),
                after=trail.snapshot(obj),
                evidence_ids=evidence_ids,
                note=note,
            )
        return obj

    def add_all(self, objs: Iterable[T], **kwargs: Any) -> list[T]:
        return [self.add(obj, **kwargs) for obj in objs]

    def update(
        self,
        obj: T,
        *,
        action: AuditAction = AuditAction.UPDATE,
        note: str | None = None,
        **changes: Any,
    ) -> T:
        """Aplica mudancas registrando antes/depois na trilha."""
        before = trail.snapshot(obj)
        for field, value in changes.items():
            setattr(obj, field, value)
        self.session.flush()
        trail.append(
            self.session,
            action=action,
            entity=self.entity_name,
            entity_id=getattr(obj, "id", None),
            before=before,
            after=trail.snapshot(obj),
            note=note,
        )
        return obj


__all__ = ["BaseRepository"]
