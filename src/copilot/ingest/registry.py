"""Registro de adapters e relatorio de cobertura de fontes.

O registry existe por causa do RF-36: o Watchdog precisa saber **quais fontes
deveriam existir**, nao apenas quais responderam. Fonte declarada e indisponivel
aparece no relatorio; fonte que ninguem declarou nao aparece em lugar nenhum — e
essa e a lacuna perigosa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable

from copilot.common.enums import AdapterStatus, DatasetKind
from copilot.common.logging import get_logger
from copilot.ingest.adapters import (
    AnaAdapter,
    AneelAdapter,
    B3N5xAdapter,
    BaseAdapter,
    BbceForwardAdapter,
    CceeAdapter,
    ClimateAdapter,
    DemoDataAdapter,
    EnsoOniAdapter,
    EpeAdapter,
    ForwardCurveUploadAdapter,
    LicensedCurveCsvAdapter,
    ManualObservationAdapter,
    OnsAdapter,
    UnavailableAdapter,
)
from copilot.ingest.contracts import AdapterResult

log = get_logger(__name__)

#: Todos os adapters conhecidos, por nome estavel.
ADAPTER_CLASSES: dict[str, type[BaseAdapter]] = {
    ForwardCurveUploadAdapter.name: ForwardCurveUploadAdapter,
    LicensedCurveCsvAdapter.name: LicensedCurveCsvAdapter,
    ManualObservationAdapter.name: ManualObservationAdapter,
    DemoDataAdapter.name: DemoDataAdapter,
    EnsoOniAdapter.name: EnsoOniAdapter,
    OnsAdapter.name: OnsAdapter,
    CceeAdapter.name: CceeAdapter,
    EpeAdapter.name: EpeAdapter,
    AneelAdapter.name: AneelAdapter,
    AnaAdapter.name: AnaAdapter,
    ClimateAdapter.name: ClimateAdapter,
    B3N5xAdapter.name: B3N5xAdapter,
    BbceForwardAdapter.name: BbceForwardAdapter,
}

#: Adapters que rodam sozinhos num ciclo automatico (sem upload humano).
AUTOMATIC_ADAPTERS: tuple[str, ...] = (
    EnsoOniAdapter.name,
    OnsAdapter.name,
    CceeAdapter.name,
    EpeAdapter.name,
    AneelAdapter.name,
    AnaAdapter.name,
    ClimateAdapter.name,
    B3N5xAdapter.name,
    BbceForwardAdapter.name,
)


def get_adapter(name: str, **kwargs: object) -> BaseAdapter:
    """Instancia um adapter pelo nome estavel."""
    if name not in ADAPTER_CLASSES:
        raise KeyError(
            f"Adapter {name!r} desconhecido. Conhecidos: "
            f"{', '.join(sorted(ADAPTER_CLASSES))}."
        )
    return ADAPTER_CLASSES[name](**kwargs)  # type: ignore[arg-type]


def list_adapters() -> list[dict[str, object]]:
    """Catalogo para a UI e para o relatorio de cobertura."""
    saida: list[dict[str, object]] = []
    for nome, classe in sorted(ADAPTER_CLASSES.items()):
        ficha = classe.source
        saida.append(
            {
                "name": nome,
                "source": ficha.name,
                "publisher": ficha.publisher,
                "license_class": ficha.license_class.value,
                "authorized": ficha.authorized,
                "url": ficha.url,
                "update_frequency": ficha.update_frequency,
                "implemented": not issubclass(classe, UnavailableAdapter),
                "automatic": nome in AUTOMATIC_ADAPTERS,
                "notes": ficha.notes,
            }
        )
    return saida


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """O que rodou, o que falhou e o que nem foi tentado."""

    as_of: date
    ok: tuple[str, ...]
    partial: tuple[str, ...]
    unavailable: tuple[str, ...]
    rejected: tuple[str, ...]

    @property
    def has_gap(self) -> bool:
        return bool(self.unavailable or self.rejected)

    @property
    def coverage_ratio(self) -> float:
        total = len(self.ok) + len(self.partial) + len(self.unavailable) + len(self.rejected)
        return (len(self.ok) + len(self.partial)) / total if total else 0.0

    def summary(self) -> str:
        return (
            f"cobertura {self.coverage_ratio:.0%} em {self.as_of.isoformat()} — "
            f"ok={len(self.ok)} parcial={len(self.partial)} "
            f"indisponivel={len(self.unavailable)} rejeitada={len(self.rejected)}"
        )


def build_coverage(results: Iterable[AdapterResult], *, as_of: date) -> CoverageReport:
    ok, parcial, indisponivel, rejeitada = [], [], [], []
    for resultado in results:
        alvo = {
            AdapterStatus.OK: ok,
            AdapterStatus.PARCIAL: parcial,
            AdapterStatus.INDISPONIVEL: indisponivel,
            AdapterStatus.REJEITADO: rejeitada,
        }[resultado.status]
        alvo.append(resultado.adapter)
    return CoverageReport(
        as_of=as_of,
        ok=tuple(ok),
        partial=tuple(parcial),
        unavailable=tuple(indisponivel),
        rejected=tuple(rejeitada),
    )


def run_automatic(
    *,
    as_of: date,
    dataset_kind: DatasetKind = DatasetKind.DEMO,
    only: Iterable[str] | None = None,
    factory: Callable[[str], BaseAdapter] | None = None,
) -> tuple[list[AdapterResult], CoverageReport]:
    """Roda os adapters automaticos. Nenhuma falha interrompe o ciclo."""
    nomes = tuple(only) if only is not None else AUTOMATIC_ADAPTERS
    criar = factory or (lambda n: get_adapter(n, dataset_kind=dataset_kind))
    resultados: list[AdapterResult] = []
    for nome in nomes:
        adapter = criar(nome)
        resultados.append(adapter.run(as_of=as_of, dataset_kind=dataset_kind))
    cobertura = build_coverage(resultados, as_of=as_of)
    log.info("ciclo_de_ingestao", extra={"resumo": cobertura.summary()})
    return resultados, cobertura


__all__ = [
    "ADAPTER_CLASSES",
    "AUTOMATIC_ADAPTERS",
    "CoverageReport",
    "build_coverage",
    "get_adapter",
    "list_adapters",
    "run_automatic",
]
