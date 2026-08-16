"""Persistencia: a tese sobrevive ao reinicio da aplicacao (AC-06 / RNF-01).

Este e o teste que o case cobra literalmente: *"O registro tem que continuar la
quando abrirmos na defesa."* Aqui o processo nao reinicia, mas o engine e a
sessao sao descartados e recriados a partir do arquivo — que e a mesma garantia.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from copilot.common.enums import (
    AssumptionKind,
    AssumptionStatus,
    Criticality,
    DatasetKind,
    ThesisStatus,
    Unit,
)
from copilot.common.errors import MissingEvidenceError, MissingContextError
from copilot.config.settings import get_settings
from copilot.db.repositories import Repositories
from copilot.db.session import build_engine
from tests.conftest import AS_OF
from tests.fixtures.builders import make_evidence, make_full_thesis, make_source, make_thesis

pytestmark = pytest.mark.persistence


def test_tese_sobrevive_ao_reinicio(
    migrated_engine: Engine, db_url: str, demo_ctx: None
) -> None:
    """AC-06: gravar, descartar tudo, reabrir do arquivo, achar intacto."""
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with factory() as session:
        repos = Repositories(session)
        thesis = make_full_thesis(repos, as_of=AS_OF)
        thesis_id = thesis.id
        session.commit()

    # Simula o desligamento: engine e pool descartados.
    migrated_engine.dispose()

    novo_engine = build_engine(get_settings(), url=db_url)
    try:
        with sessionmaker(bind=novo_engine, expire_on_commit=False)() as session:
            recuperada = Repositories(session).theses.get_full(thesis_id)
            assert recuperada is not None
            assert recuperada.title == "Tese de teste"
            assert len(recuperada.assumptions) == 1
            assert len(recuperada.positions) == 1
            assert len(recuperada.trigger_rules) == 1
            assert len(recuperada.risk_items) == 1
            # Decimais voltam exatos, sem passar por float.
            assert recuperada.positions[0].price_ref == Decimal("195.00")
            assert recuperada.expected_pnl_p50 == Decimal("500000.00")
            assert recuperada.var_limit == Decimal("50000000.00")
    finally:
        novo_engine.dispose()


def test_premissa_sem_evidencia_e_recusada(session, demo_ctx: None) -> None:
    """AC-02: sem lastro, nada e gravado."""
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)

    with pytest.raises(MissingEvidenceError, match="evidence_id"):
        repos.theses.add_assumption(
            thesis,
            kind=AssumptionKind.HIDROLOGICA,
            statement="Premissa sem lastro.",
            evidence_id="",
        )
    with pytest.raises(MissingEvidenceError, match="inexistente"):
        repos.theses.add_assumption(
            thesis,
            kind=AssumptionKind.HIDROLOGICA,
            statement="Premissa com lastro inexistente.",
            evidence_id="01J000000000000000000000ZZ",
        )
    assert repos.assumptions.count(thesis_id=thesis.id) == 0


def test_premissa_sem_metrica_fica_nao_monitoravel(session, demo_ctx: None) -> None:
    """RF-32: aceita, porem sinalizada. O silencio e que nao e aceitavel."""
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    evidence = make_evidence(repos, as_of=AS_OF)

    assumption = repos.theses.add_assumption(
        thesis,
        kind=AssumptionKind.REGULATORIA,
        statement="Premissa qualitativa, sem serie associada.",
        evidence_id=evidence.id,
        criticality=Criticality.ALTA,
    )
    assert assumption.status is AssumptionStatus.NAO_MONITORAVEL
    assert assumption.is_monitorable is False
    assert repos.theses.monitorable_assumptions(thesis.id) == []


def test_gatilho_exige_metrica_avaliavel(session, demo_ctx: None) -> None:
    """AC-03: gatilho em texto livre nao e gatilho."""
    from copilot.common.enums import RuleOperator, RuleType

    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    with pytest.raises(ValueError, match="metric_key"):
        repos.theses.add_trigger_rule(
            thesis,
            rule_type=RuleType.SAIDA,
            metric_key="   ",
            operator=RuleOperator.GTE,
            threshold=Decimal("1"),
            unit=Unit.BRL_PER_MWH,
        )


def test_resultado_esperado_precisa_ser_intervalo(session, demo_ctx: None) -> None:
    """AC-04: numero unico e recusado."""
    repos = Repositories(session)
    from copilot.common.enums import Submarket, ThesisDirection

    with pytest.raises(ValueError, match="intervalo"):
        repos.theses.create_draft(
            title="Tese com numero unico",
            summary="Uma linha.",
            direction=ThesisDirection.COMPRA,
            product="Forward",
            submarket=Submarket.SE_CO,
            author="pytest",
            expected_pnl_p50=Decimal("100.00"),
            as_of=AS_OF,
        )

    with pytest.raises(ValueError, match="P5 <= P50 <= P95"):
        repos.theses.create_draft(
            title="Tese com intervalo invertido",
            summary="Uma linha.",
            direction=ThesisDirection.COMPRA,
            product="Forward",
            submarket=Submarket.SE_CO,
            author="pytest",
            expected_pnl_p5=Decimal("900.00"),
            expected_pnl_p50=Decimal("100.00"),
            expected_pnl_p95=Decimal("50.00"),
            as_of=AS_OF,
        )


def test_resumo_limitado_a_cinco_linhas(session, demo_ctx: None) -> None:
    """Regra da Entrega 2: tese em ate 5 linhas."""
    repos = Repositories(session)
    from copilot.common.enums import Submarket, ThesisDirection

    with pytest.raises(ValueError, match="5"):
        repos.theses.create_draft(
            title="Tese prolixa",
            summary="\n".join(f"linha {i}" for i in range(8)),
            direction=ThesisDirection.COMPRA,
            product="Forward",
            submarket=Submarket.SE_CO,
            author="pytest",
            as_of=AS_OF,
        )


def test_operacao_sem_contexto_e_bloqueada(session) -> None:
    """P7/P9: nao existe caminho implicito de escrita."""
    repos = Repositories(session)
    with pytest.raises(MissingContextError):
        repos.theses.list()


def test_observacao_bitemporal_e_recuperada_pela_data_base(
    session, demo_ctx: None
) -> None:
    repos = Repositories(session)
    source = make_source(repos)
    series = repos.series.register(
        metric_key="ear_sudeste_pct",
        description="Serie de teste.",
        unit=Unit.PERCENT,
        frequency="diaria",
        source=source,
    )
    for offset, valor in [(3, "0.500000"), (2, "0.510000"), (1, "0.520000")]:
        ref = AS_OF - timedelta(days=offset)
        evidence = make_evidence(
            repos, value=Decimal(valor), unit=Unit.PERCENT, as_of=ref, source=source
        )
        repos.observations.record(
            series=series,
            ref_date=ref,
            value=Decimal(valor),
            evidence_id=evidence.id,
            as_of=ref,
        )
    session.flush()

    ultima = repos.observations.latest("ear_sudeste_pct")
    assert ultima is not None
    assert ultima.value == Decimal("0.520000")
    assert len(repos.observations.series_history("ear_sudeste_pct")) == 3


def test_divergencia_entre_rodadas_e_preservada(session, demo_ctx: None) -> None:
    """DATA_CONTRACT secao 6: nunca reduzir modelos a uma media na ingestao."""
    repos = Repositories(session)
    source = make_source(repos)
    for run in ("RODADA_A", "RODADA_B"):
        repos.series.register(
            metric_key="precip_prev_7d",
            description=f"Serie de teste {run}.",
            unit=Unit.MM,
            frequency="por_rodada",
            source=source,
            model_run=run,
            ensemble_member="membro_01",
        )
    session.flush()
    variantes = repos.series.by_metric_key("precip_prev_7d")
    assert len(variantes) == 2
    assert {s.model_run for s in variantes} == {"RODADA_A", "RODADA_B"}
