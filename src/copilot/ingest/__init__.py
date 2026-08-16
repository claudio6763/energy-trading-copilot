"""Ingestao: politica de licenca, leitura de arquivo, adapters e snapshots.

Todo dado externo entra por aqui e sai carimbado com fonte, unidade, data-base,
classificacao de licenca e qualidade. Nao existe caminho alternativo.
"""

from copilot.ingest.contracts import (
    AdapterResult,
    CurvePointRow,
    CurveRow,
    ObservationRow,
    SnapshotRef,
    SourceAdapter,
    SourceSpec,
)
from copilot.ingest.files import Table, read_bytes, read_csv_bytes, read_table, read_xlsx_bytes
from copilot.ingest.policy import assert_ingestable, effective_authorization, is_ingestable
from copilot.ingest.registry import (
    ADAPTER_CLASSES,
    CoverageReport,
    build_coverage,
    get_adapter,
    list_adapters,
    run_automatic,
)
from copilot.ingest.snapshots import SnapshotStore, payload_hash
from copilot.ingest.validation import ColumnSpec, ValidationReport, validate_table

__all__ = [
    "ADAPTER_CLASSES",
    "AdapterResult",
    "ColumnSpec",
    "CoverageReport",
    "CurvePointRow",
    "CurveRow",
    "ObservationRow",
    "SnapshotRef",
    "SnapshotStore",
    "SourceAdapter",
    "SourceSpec",
    "Table",
    "ValidationReport",
    "assert_ingestable",
    "build_coverage",
    "effective_authorization",
    "get_adapter",
    "is_ingestable",
    "list_adapters",
    "payload_hash",
    "read_bytes",
    "read_csv_bytes",
    "read_table",
    "read_xlsx_bytes",
    "run_automatic",
    "validate_table",
]
