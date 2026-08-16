"""Catalogo de fontes e dados de mercado — DATA_CONTRACT secoes 2.2, 2.8.

Inclui a curva forward (`forward_curve` / `forward_curve_point`), necessaria para
marcacao a mercado e para o dimensionamento da Entrega 2. Enquanto a duvida D-02
nao for respondida, curvas de provedor comercial permanecem bloqueadas na
ingestao e a mesa opera com proxy publico declarado (`CurvePriceType.PROXY_PUBLICO`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from copilot.common.enums import (
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
from copilot.common.ids import ULID_LENGTH
from copilot.db.base import AsOfDomainBase, DomainBase
from copilot.db.types import EnumText, Observation, Price, enum_check


class Source(DomainBase):
    """Ficha de uma fonte de dados, com classificacao de licenca (P10)."""

    __tablename__ = "source"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    publisher: Mapped[str | None] = mapped_column(String(160), nullable=True)
    url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    source_kind: Mapped[SourceKind] = mapped_column(EnumText(SourceKind), nullable=False)
    license_class: Mapped[LicenseClass] = mapped_column(EnumText(LicenseClass), nullable=False)
    #: Sem autorizacao, a ingestao e rejeitada — nao filtrada depois.
    authorized: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    authorization_ref: Mapped[str | None] = mapped_column(Text(), nullable=True)
    update_frequency: Mapped[str | None] = mapped_column(String(60), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)

    series: Mapped[list["MarketSeries"]] = relationship(back_populates="source")

    __table_args__ = (
        UniqueConstraint("name", "dataset_kind", name="uq_source_name_kind"),
        enum_check("source_kind", SourceKind),
        enum_check("license_class", LicenseClass),
        enum_check("dataset_kind", DatasetKind),
    )


class MarketSeries(DomainBase):
    """Serie de mercado identificada por `metric_key` — a chave que o Watchdog vigia."""

    __tablename__ = "market_series"

    metric_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    unit: Mapped[Unit] = mapped_column(EnumText(Unit), nullable=False)
    #: Ex.: `diaria`, `semanal`, `mensal`, `por_rodada`.
    frequency: Mapped[str] = mapped_column(String(40), nullable=False)
    submarket: Mapped[Submarket | None] = mapped_column(EnumText(Submarket), nullable=True)
    source_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("source.id", ondelete="RESTRICT"), nullable=False
    )
    license_class: Mapped[LicenseClass] = mapped_column(EnumText(LicenseClass), nullable=False)
    #: Rodada / membro de ensemble. Divergencia entre modelos e preservada,
    #: nunca reduzida a media na ingestao (DATA_CONTRACT secao 6).
    model_run: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ensemble_member: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: Sprint 2 — qualidade declarada na ingestao, nunca inferida.
    quality: Mapped[DataQuality] = mapped_column(
        EnumText(DataQuality), nullable=False, default=DataQuality.OK
    )
    #: Serie que substitui outra (ex.: PLD usado no lugar de forward negociado).
    proxy_for: Mapped[str | None] = mapped_column(String(80), nullable=True)

    source: Mapped[Source] = relationship(back_populates="series")
    observations: Mapped[list["MarketObservation"]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "metric_key",
            "dataset_kind",
            "model_run",
            "ensemble_member",
            name="uq_market_series_key",
        ),
        enum_check("unit", Unit),
        enum_check("license_class", LicenseClass),
        enum_check("submarket", Submarket),
        enum_check("quality", DataQuality),
        enum_check("dataset_kind", DatasetKind),
    )


class MarketObservation(AsOfDomainBase):
    """Observacao bitemporal: `ref_date` = a que se refere, `as_of` = quando se soube.

    O par e o que permite responder "o que sabiamos em 14/08" e impedir
    look-ahead (RF-58 / AC-55).
    """

    __tablename__ = "market_observation"

    series_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("market_series.id", ondelete="CASCADE"), nullable=False
    )
    ref_date: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    value: Mapped[Decimal] = mapped_column(Observation(), nullable=False)
    revision: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    #: Sprint 2 — qualidade da leitura, declarada pelo adapter.
    quality: Mapped[DataQuality] = mapped_column(
        EnumText(DataQuality), nullable=False, default=DataQuality.OK
    )
    #: C3 — nenhuma observacao existe sem lastro.
    evidence_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("evidence.id", ondelete="RESTRICT"), nullable=False
    )

    series: Mapped[MarketSeries] = relationship(back_populates="observations")

    __table_args__ = (
        UniqueConstraint(
            "series_id", "ref_date", "as_of", "revision", name="uq_market_observation_point"
        ),
        enum_check("quality", DataQuality),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_market_observation_scope", "dataset_kind", "as_of"),
        Index("ix_market_observation_lookup", "series_id", "ref_date", "as_of"),
    )


class ForwardCurve(AsOfDomainBase):
    """Cabecalho de uma curva forward publicada em uma data-base."""

    __tablename__ = "forward_curve"

    curve_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    submarket: Mapped[Submarket] = mapped_column(EnumText(Submarket), nullable=False)
    product_class: Mapped[ProductClass] = mapped_column(EnumText(ProductClass), nullable=False)
    price_type: Mapped[CurvePriceType] = mapped_column(
        EnumText(CurvePriceType), nullable=False, default=CurvePriceType.MID
    )
    #: Sprint 2 — separa preco negociado de PLD/CMO usado como substituto.
    #: `PROXY_SPOT` NUNCA e curva negociada e sempre paga add-on de proxy.
    origin: Mapped[CurveOrigin] = mapped_column(
        EnumText(CurveOrigin), nullable=False, default=CurveOrigin.NEGOCIADA, index=True
    )
    quality: Mapped[DataQuality] = mapped_column(
        EnumText(DataQuality), nullable=False, default=DataQuality.OK
    )
    #: Qual preco esta sendo substituido, quando a origem e proxy.
    proxy_of: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("source.id", ondelete="RESTRICT"), nullable=False
    )
    license_class: Mapped[LicenseClass] = mapped_column(EnumText(LicenseClass), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    evidence_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("evidence.id", ondelete="RESTRICT"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)

    points: Mapped[list["ForwardCurvePoint"]] = relationship(
        back_populates="curve", cascade="all, delete-orphan"
    )
    source: Mapped[Source] = relationship()

    @property
    def is_traded(self) -> bool:
        """Preco negociado, nao substituto. Base do add-on de proxy."""
        return self.origin is CurveOrigin.NEGOCIADA

    __table_args__ = (
        UniqueConstraint(
            "curve_name",
            "submarket",
            "product_class",
            "price_type",
            "as_of",
            "dataset_kind",
            name="uq_forward_curve_key",
        ),
        enum_check("submarket", Submarket),
        enum_check("product_class", ProductClass),
        enum_check("price_type", CurvePriceType),
        enum_check("origin", CurveOrigin),
        enum_check("quality", DataQuality),
        enum_check("license_class", LicenseClass),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_forward_curve_scope", "dataset_kind", "as_of"),
    )


class ForwardCurvePoint(AsOfDomainBase):
    """Ponto (tenor) de uma curva forward, em R$/MWh."""

    __tablename__ = "forward_curve_point"

    curve_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("forward_curve.id", ondelete="CASCADE"), nullable=False
    )
    #: Rotulo comercial do tenor: `M+1`, `Q+1`, `A+1`, `2027`.
    tenor_label: Mapped[str] = mapped_column(String(40), nullable=False)
    delivery_start: Mapped[date] = mapped_column(Date(), nullable=False)
    delivery_end: Mapped[date] = mapped_column(Date(), nullable=False)
    price: Mapped[Decimal] = mapped_column(Price(), nullable=False)
    quality: Mapped[DataQuality] = mapped_column(
        EnumText(DataQuality), nullable=False, default=DataQuality.OK
    )
    evidence_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("evidence.id", ondelete="RESTRICT"), nullable=False
    )

    curve: Mapped[ForwardCurve] = relationship(back_populates="points")

    __table_args__ = (
        UniqueConstraint("curve_id", "tenor_label", name="uq_forward_curve_point_tenor"),
        enum_check("quality", DataQuality),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_forward_curve_point_scope", "dataset_kind", "as_of"),
    )


__all__ = [
    "ForwardCurve",
    "ForwardCurvePoint",
    "MarketObservation",
    "MarketSeries",
    "Source",
]
