"""Snapshot de ingestao — Sprint 2.

Cada execucao de adapter deixa uma linha aqui, com hash do payload bruto e
caminho do arquivo arquivado. E o que permite responder, meses depois: *"o
numero mudou, ou a fonte mudou por baixo?"*.

Execucao que falhou tambem grava linha, com `status=INDISPONÍVEL` e motivo.
Fonte que some do relatorio e a lacuna que o RF-36 existe para impedir.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from copilot.common.enums import AdapterStatus, DatasetKind, LicenseClass
from copilot.common.ids import ULID_LENGTH
from copilot.db.base import AsOfDomainBase
from copilot.db.types import EnumText, UTCDateTime, enum_check


class IngestSnapshot(AsOfDomainBase):
    """Payload bruto arquivado e o resultado da execucao do adapter."""

    __tablename__ = "ingest_snapshot"

    adapter_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("source.id", ondelete="SET NULL"), nullable=True
    )
    source_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[AdapterStatus] = mapped_column(
        EnumText(AdapterStatus), nullable=False, index=True
    )
    license_class: Mapped[LicenseClass] = mapped_column(EnumText(LicenseClass), nullable=False)

    origin_uri: Mapped[str | None] = mapped_column(Text(), nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(Text(), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: SHA-256 do payload bruto. Detecta mudanca silenciosa da fonte.
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    byte_size: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    observations_written: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    curve_points_written: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    #: Motivo declarado quando o status nao e OK. Nunca fica vazio numa falha.
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    issues: Mapped[str | None] = mapped_column(Text(), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        enum_check("status", AdapterStatus),
        enum_check("license_class", LicenseClass),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_ingest_snapshot_scope", "dataset_kind", "as_of"),
        Index("ix_ingest_snapshot_freshness", "adapter_name", "as_of"),
    )

    @property
    def succeeded(self) -> bool:
        return self.status in {AdapterStatus.OK, AdapterStatus.PARCIAL}


__all__ = ["IngestSnapshot"]
