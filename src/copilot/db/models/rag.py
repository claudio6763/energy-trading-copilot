"""Acervo documental — DATA_CONTRACT secao 2.14.

Sprint 1 cria apenas o schema. A ingestao, o chunking e a busca hibrida entram
no Sprint 4. O embedding fica como BLOB inativo no SQLite e vira `vector(1536)`
no PostgreSQL com pgvector, por migration condicional ao dialeto
(DATA_CONTRACT secao 7).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from copilot.common.enums import DatasetKind, DocType, LicenseClass
from copilot.common.ids import ULID_LENGTH
from copilot.db.base import AsOfDomainBase, DomainBase
from copilot.db.types import EnumText, enum_check


class Document(AsOfDomainBase):
    """Documento do acervo, com vigencia e licenca.

    A recuperacao filtra por `effective_from <= as_of` e por licenca autorizada
    (ARCHITECTURE 3.4). Documento bloqueado nunca chega a ser gravado (P10).
    """

    __tablename__ = "document"

    source_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("source.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text(), nullable=False)
    doc_type: Mapped[DocType] = mapped_column(EnumText(DocType), nullable=False, index=True)
    publisher: Mapped[str | None] = mapped_column(String(160), nullable=True)
    published_at: Mapped[date | None] = mapped_column(Date(), nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date(), nullable=True, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date(), nullable=True)
    url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    license_class: Mapped[LicenseClass] = mapped_column(EnumText(LicenseClass), nullable=False)
    authorized: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentChunk.chunk_index"
    )

    __table_args__ = (
        enum_check("doc_type", DocType),
        enum_check("license_class", LicenseClass),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_document_scope", "dataset_kind", "as_of"),
    )


class DocumentChunk(DomainBase):
    """Trecho recuperavel. O `locator` de uma evidencia RAG aponta para aqui."""

    __tablename__ = "document_chunk"

    document_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    text: Mapped[str] = mapped_column(Text(), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    section: Mapped[str | None] = mapped_column(String(200), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    #: Sprint 4. BLOB inativo no SQLite; convertido para vector(1536) no PostgreSQL.
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(80), nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
        enum_check("dataset_kind", DatasetKind),
    )


__all__ = ["Document", "DocumentChunk"]
