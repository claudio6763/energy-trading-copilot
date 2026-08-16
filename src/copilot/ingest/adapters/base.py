"""Base comum a todos os adapters.

`run()` fixa a ordem que nao pode variar entre fontes:

1. politica de licenca (P10) — antes de tocar na rede ou no disco;
2. `fetch()` — payload bruto;
3. snapshot com hash — o dado cru fica arquivado antes de ser interpretado;
4. `parse()` — linhas tipadas.

Falha de fonte vira `AdapterStatus.INDISPONIVEL` com motivo declarado, nunca
lista vazia. Lista vazia e "a fonte respondeu e nao tinha nada"; indisponivel e
"nao sabemos". Confundir os dois e o modo de falha que o RF-36 existe para
impedir.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from copilot.common.enums import AdapterStatus, DatasetKind
from copilot.common.errors import AdapterUnavailable, LicenseViolation
from copilot.common.logging import get_logger
from copilot.ingest.contracts import AdapterResult, SourceSpec
from copilot.ingest.policy import assert_ingestable
from copilot.ingest.snapshots import SnapshotStore

log = get_logger(__name__)


class BaseAdapter:
    """Esqueleto de adapter. Subclasses implementam `fetch` e `parse`."""

    name: str = "base"
    source: SourceSpec
    media_type: str = "application/octet-stream"
    #: Adapter que nao acessa rede — util para distinguir falha de conectividade.
    offline: bool = True

    def __init__(
        self,
        *,
        snapshot_store: SnapshotStore | None = None,
        dataset_kind: DatasetKind = DatasetKind.DEMO,
    ) -> None:
        self.snapshots = snapshot_store or SnapshotStore()
        self.dataset_kind = dataset_kind

    # ------------------------------------------------------------ interface
    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:  # pragma: no cover
        raise NotImplementedError(f"{type(self).__name__}.fetch nao implementado.")

    def parse(
        self, raw: bytes, *, as_of: date, **kwargs: object
    ) -> AdapterResult:  # pragma: no cover
        """Nome do parametro e `raw`, nao `payload`: alguns adapters aceitam
        `payload=` como kwarg de `fetch` (reprocessar snapshot sem rede), e a
        colisao de nomes quebraria a chamada."""
        raise NotImplementedError(f"{type(self).__name__}.parse nao implementado.")

    # ----------------------------------------------------------- resultados
    def unavailable(self, reason: str, *, as_of: date) -> AdapterResult:
        log.warning("fonte_indisponivel", extra={"adapter": self.name, "motivo": reason})
        return AdapterResult(
            adapter=self.name,
            source=self.source,
            status=AdapterStatus.INDISPONIVEL,
            as_of=as_of,
            reason=reason,
        )

    def rejected(self, reason: str, *, as_of: date) -> AdapterResult:
        log.warning("ingestao_rejeitada", extra={"adapter": self.name, "motivo": reason})
        return AdapterResult(
            adapter=self.name,
            source=self.source,
            status=AdapterStatus.REJEITADO,
            as_of=as_of,
            reason=reason,
        )

    # ------------------------------------------------------------- execucao
    def run(
        self,
        *,
        as_of: date,
        dataset_kind: DatasetKind | None = None,
        snapshot: bool = True,
        **kwargs: object,
    ) -> AdapterResult:
        """Executa o funil completo. Nunca levanta por falha de fonte."""
        kind = dataset_kind or self.dataset_kind
        try:
            assert_ingestable(
                self.source.license_class,
                self.source.authorized,
                subject=self.source.name,
                authorization_ref=self.source.authorization_ref,
            )
        except LicenseViolation as exc:
            return self.rejected(str(exc), as_of=as_of)

        try:
            raw = self.fetch(as_of=as_of, **kwargs)
        except AdapterUnavailable as exc:
            return self.unavailable(str(exc), as_of=as_of)
        except OSError as exc:  # rede, arquivo, permissao
            return self.unavailable(f"falha de E/S: {exc}", as_of=as_of)

        referencia = None
        if snapshot:
            referencia = self.snapshots.save(
                raw,
                adapter=self.name,
                as_of=as_of,
                dataset_kind=kind,
                media_type=self.media_type,
                source_name=self.source.name,
                origin_uri=self.source.url,
            )

        resultado = self.parse(raw, as_of=as_of, **kwargs)
        return replace(resultado, snapshot=referencia)


class UnavailableAdapter(BaseAdapter):
    """Interface declarada cuja implementacao ainda nao existe.

    Existe para que a fonte apareca no catalogo e no relatorio de cobertura do
    Watchdog **como indisponivel**, em vez de simplesmente nao existir. Fonte que
    ninguem sabe que falta e o pior tipo de lacuna.
    """

    reason: str = "interface declarada; implementacao pendente."

    def run(
        self,
        *,
        as_of: date,
        dataset_kind: DatasetKind | None = None,
        snapshot: bool = True,
        **kwargs: object,
    ) -> AdapterResult:
        return self.unavailable(self.reason, as_of=as_of)


def read_payload(source: bytes | str | Path) -> tuple[bytes, str]:
    """Normaliza entrada de arquivo: bytes, caminho ou texto. Devolve (bytes, nome)."""
    if isinstance(source, bytes):
        return source, "upload"
    caminho = Path(source)
    if caminho.exists():
        return caminho.read_bytes(), caminho.name
    if isinstance(source, str):
        return source.encode("utf-8"), "upload.csv"
    raise AdapterUnavailable(f"Arquivo nao encontrado: {source}")


__all__ = ["BaseAdapter", "UnavailableAdapter", "read_payload"]
