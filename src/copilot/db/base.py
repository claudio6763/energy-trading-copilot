"""Base declarativa e mixins comuns a todas as entidades.

Regras C1 e C2 de DATA_CONTRACT.md viram mixins, para que nenhuma tabela de
dominio possa esquecer `id`, `created_at`, `dataset_kind` ou `as_of`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, Index, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from copilot.common.enums import DatasetKind
from copilot.common.ids import ULID_LENGTH, new_ulid
from copilot.db.types import EnumText, UTCDateTime, utcnow

#: Nomes deterministas de constraints — requisito para ALTER em SQLite (batch mode).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}

metadata_obj = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata_obj

    def to_dict(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        """Snapshot serializavel das colunas — usado em `audit_log.before/after`."""
        exclude = exclude or set()
        out: dict[str, Any] = {}
        for column in self.__table__.columns:
            if column.name in exclude:
                continue
            value = getattr(self, column.name, None)
            if isinstance(value, datetime):
                out[column.name] = value.isoformat()
            elif isinstance(value, date):
                out[column.name] = value.isoformat()
            elif hasattr(value, "value"):  # enum de dominio
                out[column.name] = value.value
            elif value is not None and value.__class__.__name__ == "Decimal":
                out[column.name] = str(value)
            else:
                out[column.name] = value
        return out

    def __repr__(self) -> str:  # pragma: no cover - conveniencia
        ident = getattr(self, "id", None)
        return f"<{type(self).__name__} id={ident}>"


def ulid_pk() -> Mapped[str]:
    """Chave primaria ULID (CLAUDE.md secao 5)."""
    return mapped_column(String(ULID_LENGTH), primary_key=True, default=new_ulid)


def ulid_fk_column(length: int = ULID_LENGTH) -> String:
    return String(length)


class TimestampMixin:
    """C1 — `created_at` em UTC."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, index=True
    )


class DatasetScopedMixin:
    """C1/P9 — toda linha de dominio declara DEMO ou REAL."""

    dataset_kind: Mapped[DatasetKind] = mapped_column(
        EnumText(DatasetKind), nullable=False, index=True
    )


class AsOfMixin:
    """C2/P7 — data-base do dado, distinta de `created_at`."""

    as_of: Mapped[date] = mapped_column(Date(), nullable=False, index=True)


class DomainBase(TimestampMixin, DatasetScopedMixin, Base):
    """Entidade de dominio com id ULID, `created_at` e `dataset_kind`."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(ULID_LENGTH), primary_key=True, default=new_ulid)


class AsOfDomainBase(AsOfMixin, DomainBase):
    """Entidade de dominio que tambem carrega data-base."""

    __abstract__ = True


def dataset_asof_index(table_name: str) -> Index:
    """Indice composto usado por toda consulta escopada (C5 + C6)."""
    return Index(f"ix_{table_name}_scope", "dataset_kind", "as_of")


__all__ = [
    "AsOfDomainBase",
    "AsOfMixin",
    "Base",
    "DatasetScopedMixin",
    "DomainBase",
    "NAMING_CONVENTION",
    "TimestampMixin",
    "dataset_asof_index",
    "metadata_obj",
    "ulid_pk",
]
