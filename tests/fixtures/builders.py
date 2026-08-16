"""Construtores usados pelos testes. Nada aqui simula dado de mercado."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from copilot.common.enums import (
    AssumptionKind,
    Confidence,
    Criticality,
    EvidenceSourceType,
    Instrument,
    LicenseClass,
    Likelihood,
    RiskCategory,
    RuleOperator,
    RuleType,
    Severity,
    Side,
    SourceKind,
    Submarket,
    ThesisDirection,
    Unit,
)
from copilot.db.models import Evidence, Source, Thesis
from copilot.db.repositories import Repositories

TEST_NOTE = "VALOR DE TESTE. Nao e dado de mercado."


def make_source(repos: Repositories, name: str = "Fonte de teste") -> Source:
    return repos.sources.register(
        name=name,
        source_kind=SourceKind.MANUAL,
        license_class=LicenseClass.PUBLIC_OPEN,
        authorized=True,
        notes=TEST_NOTE,
    )


def make_evidence(
    repos: Repositories,
    *,
    value: Decimal | None = None,
    unit: Unit | None = None,
    as_of: date | None = None,
    source: Source | None = None,
) -> Evidence:
    return repos.evidence.create(
        source_type=EvidenceSourceType.HUMAN_INPUT,
        source_id=source.id if source else None,
        locator="test://evidencia",
        excerpt=f"{TEST_NOTE} valor={value}",
        license_class=LicenseClass.PUBLIC_OPEN,
        value_numeric=value,
        unit=unit,
        confidence=Confidence.LOW,
        as_of=as_of,
    )


def make_thesis(
    repos: Repositories,
    *,
    as_of: date,
    title: str = "Tese de teste",
    var_consumed: Decimal | None = Decimal("10000000.00"),
) -> Thesis:
    return repos.theses.create_draft(
        title=title,
        summary="Linha 1.\nLinha 2.",
        direction=ThesisDirection.VENDA,
        product="Forward convencional",
        submarket=Submarket.SE_CO,
        author="pytest",
        horizon_days=90,
        review_date=as_of + timedelta(days=30),
        expected_pnl_p5=Decimal("-1000000.00"),
        expected_pnl_p50=Decimal("500000.00"),
        expected_pnl_p95=Decimal("2000000.00"),
        var_consumed=var_consumed,
        as_of=as_of,
    )


def make_full_thesis(repos: Repositories, *, as_of: date) -> Thesis:
    """Tese com premissa, posicao, gatilho e risco — grafo completo."""
    source = make_source(repos, name=f"Fonte {as_of.isoformat()}")
    thesis = make_thesis(repos, as_of=as_of)

    evidence = make_evidence(
        repos, value=Decimal("0.520000"), unit=Unit.PERCENT, as_of=as_of, source=source
    )
    repos.theses.add_assumption(
        thesis,
        kind=AssumptionKind.HIDROLOGICA,
        statement="Premissa de teste, mensuravel.",
        evidence_id=evidence.id,
        metric_key="ear_sudeste_pct",
        expected_value=Decimal("0.520000"),
        tolerance_low=Decimal("0.450000"),
        tolerance_high=Decimal("0.750000"),
        unit=Unit.PERCENT,
        criticality=Criticality.ALTA,
    )

    price_evidence = make_evidence(
        repos, value=Decimal("195.00"), unit=Unit.BRL_PER_MWH, as_of=as_of, source=source
    )
    repos.theses.add_position(
        thesis,
        instrument=Instrument.FORWARD_CONV,
        submarket=Submarket.SE_CO,
        side=Side.SHORT,
        volume_mwh=Decimal("1000.000"),
        price_ref=Decimal("195.00"),
        delivery_start=as_of,
        delivery_end=as_of + timedelta(days=365),
        evidence_id=price_evidence.id,
    )

    repos.theses.add_trigger_rule(
        thesis,
        rule_type=RuleType.SAIDA,
        metric_key="pld_se_semanal",
        operator=RuleOperator.GTE,
        threshold=Decimal("260.00"),
        unit=Unit.BRL_PER_MWH,
        eval_window="7d",
        severity=Severity.CRITICO,
        description="Gatilho de teste.",
    )

    repos.theses.add_risk(
        thesis,
        category=RiskCategory.MERCADO,
        description="Risco de teste.",
        severity=Severity.ATENCAO,
        likelihood=Likelihood.MEDIA,
    )
    return thesis


__all__ = ["TEST_NOTE", "make_evidence", "make_full_thesis", "make_source", "make_thesis"]
