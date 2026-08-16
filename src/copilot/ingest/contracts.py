"""Contrato unico para todo adapter de fonte externa.

Qualquer fonte — arquivo do trader, API do ONS, texto do NOAA — entra pelo mesmo
funil: `fetch()` traz o payload bruto, `parse()` transforma em linhas tipadas, e
o `IngestLoader` persiste com evidencia. Isso mantem tres garantias que nao
podem depender de quem escreveu o adapter:

* **Proveniencia.** Toda linha carrega fonte, unidade, data-base e qualidade.
* **Snapshot.** O payload bruto e gravado e hasheado antes de virar dado.
* **Licenca.** A politica de `ingest.policy` roda antes de qualquer gravacao.

Dataclasses em vez de Pydantic de proposito: este modulo precisa rodar sem
banco e sem dependencia externa, para ser testavel isoladamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol, Sequence, runtime_checkable

from copilot.common.enums import (
    AdapterStatus,
    CurveOrigin,
    CurvePriceType,
    DataQuality,
    LicenseClass,
    ProductClass,
    SourceKind,
    Submarket,
    Unit,
)


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Ficha da fonte que o adapter representa. Vira uma linha em `source`."""

    name: str
    source_kind: SourceKind
    license_class: LicenseClass
    publisher: str | None = None
    url: str | None = None
    authorized: bool = True
    authorization_ref: str | None = None
    update_frequency: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class ObservationRow:
    """Uma leitura de metrica, ja tipada e com proveniencia."""

    metric_key: str
    ref_date: date
    value: Decimal
    unit: Unit
    #: Data-base da publicacao. Com `ref_date` forma o par bitemporal.
    as_of: date
    quality: DataQuality = DataQuality.OK
    submarket: Submarket | None = None
    model_run: str | None = None
    ensemble_member: str | None = None
    description: str | None = None
    note: str | None = None

    def evidence_excerpt(self, source_name: str) -> str:
        """Texto literal que vira `evidence.excerpt`. Gerado, nunca escrito a mao."""
        return (
            f"{source_name}: {self.metric_key} = {self.value} {self.unit.value} "
            f"em {self.ref_date.isoformat()} (data-base {self.as_of.isoformat()}, "
            f"qualidade {self.quality.value})."
        )


@dataclass(frozen=True, slots=True)
class CurvePointRow:
    """Um tenor de curva forward."""

    tenor_label: str
    delivery_start: date
    delivery_end: date
    price: Decimal
    quality: DataQuality = DataQuality.OK

    def evidence_excerpt(self, curve_name: str, as_of: date) -> str:
        return (
            f"{curve_name}: tenor {self.tenor_label} "
            f"({self.delivery_start.isoformat()}..{self.delivery_end.isoformat()}) "
            f"= {self.price} R$/MWh, data-base {as_of.isoformat()}, "
            f"qualidade {self.quality.value}."
        )


@dataclass(frozen=True, slots=True)
class CurveRow:
    """Cabecalho de curva com os pontos.

    `origin` e obrigatorio e nunca tem valor padrao acidental: e ele que separa
    preco negociado de PLD/CMO usado como substituto.
    """

    curve_name: str
    submarket: Submarket
    product_class: ProductClass
    origin: CurveOrigin
    as_of: date
    points: tuple[CurvePointRow, ...]
    price_type: CurvePriceType = CurvePriceType.MID
    currency: str = "BRL"
    quality: DataQuality = DataQuality.OK
    proxy_of: str | None = None
    notes: str | None = None

    @property
    def is_traded(self) -> bool:
        return self.origin is CurveOrigin.NEGOCIADA


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    """Ponteiro para o payload bruto arquivado."""

    snapshot_id: str
    payload_hash: str
    byte_size: int
    storage_uri: str
    fetched_at: datetime
    media_type: str = "application/octet-stream"


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """Saida padronizada de um adapter.

    `status` nunca e inferido do tamanho da lista: fonte vazia e fonte quebrada
    sao coisas diferentes, e a segunda vira `INDISPONIVEL` com motivo (RF-36).
    """

    adapter: str
    source: SourceSpec
    status: AdapterStatus
    as_of: date
    observations: tuple[ObservationRow, ...] = ()
    curves: tuple[CurveRow, ...] = ()
    snapshot: SnapshotRef | None = None
    issues: tuple[str, ...] = ()
    reason: str | None = None
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    @property
    def ok(self) -> bool:
        return self.status in {AdapterStatus.OK, AdapterStatus.PARCIAL}

    @property
    def row_count(self) -> int:
        return len(self.observations) + sum(len(c.points) for c in self.curves)

    def summary(self) -> str:
        if not self.ok:
            return f"{self.adapter}: {self.status.value} — {self.reason or 'sem motivo declarado'}"
        return (
            f"{self.adapter}: {self.status.value}, {self.row_count} linha(s), "
            f"data-base {self.as_of.isoformat()}"
        )


@runtime_checkable
class SourceAdapter(Protocol):
    """Interface que todo adapter implementa.

    `name` e estavel e vira chave no registry e em `ingest_snapshot.adapter_name`.
    """

    name: str
    source: SourceSpec

    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:
        """Traz o payload bruto. Levanta `AdapterUnavailable` se a fonte falhar."""
        ...

    def parse(self, payload: bytes, *, as_of: date, **kwargs: object) -> AdapterResult:
        """Transforma o payload bruto em linhas tipadas e validadas."""
        ...

    def run(self, *, as_of: date, **kwargs: object) -> AdapterResult:
        """`fetch` + snapshot + `parse`, na ordem."""
        ...


__all__ = [
    "AdapterResult",
    "CurvePointRow",
    "CurveRow",
    "ObservationRow",
    "SnapshotRef",
    "SourceAdapter",
    "SourceSpec",
]
