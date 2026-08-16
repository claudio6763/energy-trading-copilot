"""Cenarios e seus resultados — DATA_CONTRACT secao 2.10.

RF-53 / AC-42: toda tese precisa de pelo menos dois cenarios hidrologicos
distintos, com P&L esperado, impacto no VaR e o que muda na tese em cada um.
A verificacao dessa regra e feita no ScenarioRepository e no motor quant
(Sprint 3); aqui existe apenas o schema.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from copilot.common.enums import DatasetKind, ScenarioKind
from copilot.common.ids import ULID_LENGTH
from copilot.db.base import AsOfDomainBase, DomainBase
from copilot.db.types import EnumText, Money, Percent, enum_check


class Scenario(DomainBase):
    """Definicao declarativa de um cenario (choques explicitos, sem media oculta)."""

    __tablename__ = "scenario"

    name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    kind: Mapped[ScenarioKind] = mapped_column(EnumText(ScenarioKind), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    #: Choques declarados, ex.: {"ena_mlt_pct": -0.25, "pld_shift": 80}.
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)
    probability_weight: Mapped[Decimal | None] = mapped_column(Percent(), nullable=True)
    source_evidence_id: Mapped[str | None] = mapped_column(
        String(ULID_LENGTH), ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True
    )

    results: Mapped[list["ScenarioResult"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("name", "dataset_kind", name="uq_scenario_name_kind"),
        enum_check("kind", ScenarioKind),
        enum_check("dataset_kind", DatasetKind),
    )


class ScenarioResult(AsOfDomainBase):
    """Resultado de um cenario aplicado a uma tese, sempre com `quant_run_id`."""

    __tablename__ = "scenario_result"

    thesis_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("thesis.id", ondelete="CASCADE"), nullable=False
    )
    scenario_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("scenario.id", ondelete="RESTRICT"), nullable=False
    )
    #: Prova de que o numero veio do motor quant, nao do LLM (P5).
    quant_run_id: Mapped[str] = mapped_column(
        String(ULID_LENGTH), ForeignKey("quant_run.id", ondelete="RESTRICT"), nullable=False
    )
    pnl_p5: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    pnl_p50: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    pnl_p95: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    var_impact: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    #: O que muda na tese neste cenario (exigencia explicita da Entrega 2).
    thesis_delta: Mapped[str | None] = mapped_column(Text(), nullable=True)

    scenario: Mapped[Scenario] = relationship(back_populates="results")

    __table_args__ = (
        UniqueConstraint(
            "thesis_id", "scenario_id", "as_of", name="uq_scenario_result_thesis"
        ),
        enum_check("dataset_kind", DatasetKind),
        Index("ix_scenario_result_scope", "dataset_kind", "as_of"),
    )


__all__ = ["Scenario", "ScenarioResult"]
