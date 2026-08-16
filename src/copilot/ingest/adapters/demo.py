"""`DemoDataAdapter` — dado sintetico rotulado, para o dataset DEMO.

Existe para que a ferramenta possa ser demonstrada sem depender de rede e sem
misturar com dado real (P9). Tres regras:

1. Nenhum valor sai de fonte de mercado. Todos vem de uma funcao deterministica
   e sem `random`: mesma data-base, mesma serie, sempre.
2. Toda linha declara `DataQuality.ESTIMADO` e diz no texto que e sintetica.
3. Grava exclusivamente em `dataset_kind=DEMO`. Se alguem pedir `REAL`, recusa.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from decimal import Decimal

from copilot.common.enums import (
    AdapterStatus,
    CurveOrigin,
    CurvePriceType,
    DataQuality,
    DatasetKind,
    LicenseClass,
    ProductClass,
    SourceKind,
    Submarket,
    Unit,
)
from copilot.common.errors import AdapterUnavailable
from copilot.ingest.adapters.base import BaseAdapter
from copilot.ingest.contracts import (
    AdapterResult,
    CurvePointRow,
    CurveRow,
    ObservationRow,
    SourceSpec,
)

SYNTHETIC_MARK = "SINTÉTICO — não é dado de mercado"
DEFAULT_HISTORY_DAYS = 120

#: (metric_key, unidade, submercado, base, amplitude, periodo, fase, rodada)
_SERIES: tuple[tuple[str, Unit, Submarket | None, float, float, float, float, str | None], ...] = (
    ("ear_sudeste_pct", Unit.PERCENT, Submarket.SE_CO, 0.52, 0.10, 90.0, 0.0, None),
    ("ena_sin_mlt_pct", Unit.PERCENT, None, 0.88, 0.22, 60.0, 12.0, None),
    ("pld_se_semanal", Unit.BRL_PER_MWH, Submarket.SE_CO, 180.0, 60.0, 45.0, 5.0, None),
    ("carga_sin_mwmed", Unit.MWMED, None, 71000.0, 2500.0, 30.0, 3.0, None),
    ("precip_prev_7d", Unit.MM, Submarket.SE_CO, 42.0, 18.0, 21.0, 0.0, "RODADA_A"),
    ("precip_prev_7d", Unit.MM, Submarket.SE_CO, 61.0, 25.0, 21.0, 6.0, "RODADA_B"),
)


def _wave(i: int, base: float, amplitude: float, periodo: float, fase: float) -> float:
    return base + amplitude * math.sin((i + fase) * 2 * math.pi / periodo)


class DemoDataAdapter(BaseAdapter):
    """Gerador deterministico de series e de uma curva de referencia."""

    name = "demo_data"
    media_type = "application/json"
    offline = True

    source = SourceSpec(
        name="SINTÉTICO — Gerador de demonstração",
        source_kind=SourceKind.MANUAL,
        license_class=LicenseClass.PUBLIC_OPEN,
        publisher="Energy Trading Copilot (demo)",
        authorized=True,
        update_frequency="sob demanda",
        notes=f"{SYNTHETIC_MARK}. Uso restrito ao dataset DEMO.",
    )

    def run(  # type: ignore[override]
        self,
        *,
        as_of: date,
        dataset_kind: DatasetKind | None = None,
        snapshot: bool = True,
        **kwargs: object,
    ) -> AdapterResult:
        kind = dataset_kind or self.dataset_kind
        if kind is not DatasetKind.DEMO:
            return self.rejected(
                "DemoDataAdapter so grava em dataset_kind=DEMO. Dado sintetico nunca "
                "entra no dataset REAL (P9).",
                as_of=as_of,
            )
        return super().run(as_of=as_of, dataset_kind=kind, snapshot=snapshot, **kwargs)

    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:
        """O 'payload bruto' e a propria parametrizacao — fica no snapshot."""
        dias = int(kwargs.get("history_days") or DEFAULT_HISTORY_DAYS)
        if dias < 2:
            raise AdapterUnavailable("history_days deve ser >= 2.")
        parametros = {
            "aviso": SYNTHETIC_MARK,
            "as_of": as_of.isoformat(),
            "history_days": dias,
            "series": [
                {
                    "metric_key": chave,
                    "unit": unidade.value,
                    "base": base,
                    "amplitude": amplitude,
                    "periodo": periodo,
                    "fase": fase,
                    "model_run": rodada,
                }
                for chave, unidade, _sub, base, amplitude, periodo, fase, rodada in _SERIES
            ],
        }
        return json.dumps(parametros, ensure_ascii=False, indent=2).encode("utf-8")

    def parse(self, raw: bytes, *, as_of: date, **kwargs: object) -> AdapterResult:
        dias = int(kwargs.get("history_days") or DEFAULT_HISTORY_DAYS)
        observacoes: list[ObservationRow] = []

        for chave, unidade, submercado, base, amplitude, periodo, fase, rodada in _SERIES:
            for deslocamento in range(dias, 0, -1):
                referencia = as_of - timedelta(days=deslocamento)
                bruto = _wave(deslocamento, base, amplitude, periodo, fase)
                casas = "0.000001" if unidade is Unit.PERCENT else "0.01"
                valor = Decimal(repr(round(bruto, 8))).quantize(Decimal(casas))
                observacoes.append(
                    ObservationRow(
                        metric_key=chave,
                        ref_date=referencia,
                        value=valor,
                        unit=unidade,
                        as_of=referencia,
                        quality=DataQuality.ESTIMADO,
                        submarket=submercado,
                        model_run=rodada,
                        ensemble_member="membro_01" if rodada else None,
                        description=f"{SYNTHETIC_MARK}: {chave}",
                        note=SYNTHETIC_MARK,
                    )
                )

        curva = self._demo_curve(as_of)
        return AdapterResult(
            adapter=self.name,
            source=self.source,
            status=AdapterStatus.OK,
            as_of=as_of,
            observations=tuple(observacoes),
            curves=(curva,),
        )

    @staticmethod
    def _demo_curve(as_of: date) -> CurveRow:
        """Curva de demonstracao, declarada como proxy de modelo.

        Nao e negociada e nao finge ser: `PROXY_MODELO` faz o motor de risco
        cobrar o add-on correspondente, como cobraria de qualquer proxy.
        """
        pontos = []
        for deslocamento, preco in ((1, "195.00"), (2, "188.50"), (3, "182.00")):
            ano = as_of.year + deslocamento
            pontos.append(
                CurvePointRow(
                    tenor_label=f"A+{deslocamento}",
                    delivery_start=date(ano, 1, 1),
                    delivery_end=date(ano, 12, 31),
                    price=Decimal(preco),
                    quality=DataQuality.PROXY,
                )
            )
        return CurveRow(
            curve_name="SINTÉTICA SE/CO convencional",
            submarket=Submarket.SE_CO,
            product_class=ProductClass.CONVENCIONAL,
            origin=CurveOrigin.PROXY_MODELO,
            as_of=as_of,
            points=tuple(pontos),
            price_type=CurvePriceType.PROXY_PUBLICO,
            quality=DataQuality.PROXY,
            proxy_of="gerador sintetico de demonstracao",
            notes=f"{SYNTHETIC_MARK}. Nao e preco negociado; penalizada no risco.",
        )


__all__ = ["DEFAULT_HISTORY_DAYS", "DemoDataAdapter", "SYNTHETIC_MARK"]
