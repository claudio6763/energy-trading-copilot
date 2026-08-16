"""Contratos da recuperacao documental (Sprint 4).

Regra que o contrato ja carrega: resposta sem `chunks` recuperados e
"nao encontrado no acervo" — nunca conhecimento parametrico do modelo (AC-54).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from copilot.common.enums import DocType


class RagQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    as_of: date
    doc_types: list[DocType] = Field(default_factory=list)
    top_k: int = 8


class RetrievedChunk(BaseModel):
    """Trecho recuperado. Sempre citavel: documento, pagina e vigencia."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    document_title: str
    text: str
    page: int | None = None
    section: str | None = None
    effective_from: date | None = None
    score: float


class RagAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    @property
    def grounded(self) -> bool:
        """Sem trecho recuperado, a resposta nao e fundamentada."""
        return bool(self.chunks)


__all__ = ["RagAnswer", "RagQuery", "RetrievedChunk"]
