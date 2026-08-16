"""Evidencia e proveniencia — DATA_CONTRACT secoes 2.1, 2.9.

`evidence` e a peca central do sistema: nenhum fato existe sem uma linha aqui
(P6). `sql_execution` e `quant_run` sao as duas origens automaticas de evidencia;
a terceira e a entrada humana (RF-11).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from copilot.common.enums import (
    Confidence,
    DatasetKind,
    EvidenceSourceType,
    LicenseClass,
    QuantFunction,
    Unit,
)
from copilot.db.base import AsOfDomainBase
from copilot.db.types import EnumText, Observation, UTCDateTime, enum_check, utcnow


class Evidence(AsOfDomainBase):
    """Lastro de uma afirmacao factual. Sem isto, nada e exibido como dado."""

    __tablename__ = "evidence"

    source_type: Mapped[EvidenceSourceType] = mapped_column(
        EnumText(EvidenceSourceType), nullable=False, index=True
    )
    #: FK logica (nao fisica): aponta para `source`, `sql_execution` ou `quant_run`
    #: conforme `source_type`. Deliberadamente polimorfica.
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: Onde exatamente: `doc_id#chunk#pagina`, `sql_hash`, `run_id`, `arquivo#celula`.
    locator: Mapped[str | None] = mapped_column(Text(), nullable=True)
    #: Trecho literal citado ou representacao do valor. Obrigatorio.
    excerpt: Mapped[str] = mapped_column(Text(), nullable=False)
    value_numeric: Mapped[Decimal | None] = mapped_column(Observation(), nullable=True)
    unit: Mapped[Unit | None] = mapped_column(EnumText(Unit), nullable=True)
    #: SHA-256 do conteudo citado — detecta mudanca silenciosa da fonte.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    license_class: Mapped[LicenseClass] = mapped_column(
        EnumText(LicenseClass), nullable=False
    )
    #: Qualidade declarada da fonte. Nunca inferida por LLM.
    confidence: Mapped[Confidence] = mapped_column(
        EnumText(Confidence), nullable=False, default=Confidence.MEDIUM
    )
    note: Mapped[str | None] = mapped_column(Text(), nullable=True)

    __table_args__ = (
        enum_check("source_type", EvidenceSourceType),
        enum_check("license_class", LicenseClass),
        enum_check("confidence", Confidence),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_evidence_scope", "dataset_kind", "as_of"),
    )

    @property
    def is_numeric(self) -> bool:
        return self.value_numeric is not None


class SqlExecution(AsOfDomainBase):
    """Execucao registrada do Agente de Dados e SQL (ARCHITECTURE 3.5)."""

    __tablename__ = "sql_execution"

    #: Nome do template parametrizado, quando a consulta nao foi gerada livremente.
    template_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    sql_text: Mapped[str] = mapped_column(Text(), nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    params_json: Mapped[dict[str, Any] | None] = mapped_column(JSON(), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    #: Guardado explicitamente: prova de que o predicado de data-base foi injetado.
    as_of_applied: Mapped[bool] = mapped_column(nullable=False, default=True)

    __table_args__ = (
        enum_check("dataset_kind", DatasetKind),
        Index("ix_sql_execution_scope", "dataset_kind", "as_of"),
    )


class QuantRun(AsOfDomainBase):
    """Execucao do motor quantitativo. O `id` e o `run_id` e tambem a evidencia.

    Reexecutar com o mesmo `inputs_hash`, `seed` e `code_version` deve produzir
    `outputs_json` identico (RF-56 / AC-40).
    """

    __tablename__ = "quant_run"

    function: Mapped[QuantFunction] = mapped_column(
        EnumText(QuantFunction), nullable=False, index=True
    )
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outputs_json: Mapped[dict[str, Any] | None] = mapped_column(JSON(), nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    code_version: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    __table_args__ = (
        enum_check("function", QuantFunction),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_quant_run_repro", "inputs_hash", "code_version", "seed"),
        Index("ix_quant_run_scope", "dataset_kind", "as_of"),
    )


__all__ = ["Evidence", "QuantRun", "SqlExecution"]
