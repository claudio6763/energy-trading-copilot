"""Contratos do Agente de Dados e SQL (Sprint 2).

`SqlRequest` nao carrega SQL cru por acidente: o caminho preferencial e
`template` + `params`. SQL livre existe para exploracao e passa pelo validador
de AST antes de executar (ARCHITECTURE secao 3.5).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from copilot.common.enums import DatasetKind


class SqlRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: date
    dataset_kind: DatasetKind
    template: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    raw_sql: str | None = None
    limit: int = 1000

    @model_validator(mode="after")
    def _one_of(self) -> "SqlRequest":
        if bool(self.template) == bool(self.raw_sql):
            raise ValueError("Informe `template` ou `raw_sql`, nunca os dois.")
        return self


class SqlResult(BaseModel):
    """Resultado com proveniencia. `evidence_ids` acompanha cada valor exposto."""

    model_config = ConfigDict(frozen=True)

    rows: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    row_count: int = 0
    sql_hash: str
    execution_id: str
    as_of_applied: bool = True
    dataset_kind_applied: bool = True
    evidence_ids: list[str] = Field(default_factory=list)
    duration_ms: int | None = None


__all__ = ["SqlRequest", "SqlResult"]
