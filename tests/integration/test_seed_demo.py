"""Seed de demonstracao: popula DEMO, nao contamina REAL, e e reversivel."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from copilot.common.context import run_context
from copilot.common.enums import (
    ActorType,
    AlertKind,
    AuditAction,
    ClaimStatus,
    DatasetKind,
    ScenarioKind,
    ThesisStatus,
)
from copilot.db.models import (
    Alert,
    AuditLog,
    Claim,
    Evidence,
    MarketObservation,
    Source,
    Thesis,
)
from copilot.db.repositories import Repositories
from copilot.seed.demo import SEED_SOURCE_NAME, SYNTHETIC_NOTE, already_seeded, purge_demo, seed
from tests.conftest import AS_OF


@pytest.fixture()
def seeded(session):
    with run_context(
        as_of=AS_OF,
        dataset_kind=DatasetKind.DEMO,
        actor="pytest",
        actor_type=ActorType.SISTEMA,
    ):
        counts = seed(session, AS_OF)
        session.flush()
        yield counts


def test_seed_popula_o_grafo_completo(session, seeded) -> None:
    assert seeded["thesis"] == 2
    assert seeded["market_series"] == 6
    assert seeded["market_observation"] > 0
    assert seeded["forward_curve_point"] == 3
    assert seeded["scenario"] == 2
    assert seeded["alert"] == 2


def test_tudo_e_gravado_como_demo(session, seeded) -> None:
    """P9: o seed nunca escreve em REAL."""
    for model in (Thesis, Source, Evidence, MarketObservation, Alert, Claim):
        reais = session.execute(
            select(func.count()).select_from(model).where(model.dataset_kind == DatasetKind.REAL)
        ).scalar_one()
        assert reais == 0, f"{model.__tablename__} vazou para REAL"


def test_evidencias_declaram_ser_sinteticas(session, seeded) -> None:
    """Dado de demonstracao rotulado como tal, sempre."""
    evidencias = list(session.execute(select(Evidence)).scalars())
    assert evidencias
    assert all(SYNTHETIC_NOTE.split(".")[0] in e.excerpt for e in evidencias)


def test_toda_observacao_tem_lastro(session, seeded) -> None:
    """C3: nenhuma observacao sem `evidence_id`."""
    observacoes = list(session.execute(select(MarketObservation)).scalars())
    assert observacoes
    assert all(len(o.evidence_id) == 26 for o in observacoes)


def test_divergencia_entre_rodadas_preservada(session, seeded) -> None:
    with run_context(as_of=AS_OF, dataset_kind=DatasetKind.DEMO, actor="pytest"):
        variantes = Repositories(session).series.by_metric_key("precip_prev_7d")
    assert len(variantes) == 2
    assert {s.model_run for s in variantes} == {"RODADA_A", "RODADA_B"}


def test_fonte_licenciada_foi_rejeitada_e_auditada(session, seeded) -> None:
    """AC-56: bloqueio na entrada, com rastro."""
    bloqueadas = session.execute(
        select(func.count()).select_from(Source).where(Source.name.like("Provedor comercial%"))
    ).scalar_one()
    assert bloqueadas == 0

    rejeicoes = session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.INGEST_REJECTED)
    ).scalars().all()
    assert len(rejeicoes) == 1
    assert "rejeitada" in (rejeicoes[0].note or "")


def test_tese_de_demonstracao_fica_ativa_dentro_do_limite(session, seeded) -> None:
    with run_context(as_of=AS_OF, dataset_kind=DatasetKind.DEMO, actor="pytest"):
        repos = Repositories(session)
        ativas = repos.theses.active()
    assert len(ativas) == 1
    tese = ativas[0]
    assert tese.status is ThesisStatus.ATIVA
    assert tese.var_consumed == Decimal("18500000.00")
    assert tese.var_within_limit is True
    assert tese.expected_pnl_p5 < tese.expected_pnl_p50 < tese.expected_pnl_p95


def test_segunda_tese_permanece_bloqueada(session, seeded) -> None:
    """RF-51: claim BLOCKED impede a aprovacao."""
    with run_context(as_of=AS_OF, dataset_kind=DatasetKind.DEMO, actor="pytest"):
        repos = Repositories(session)
        bloqueada = [
            t for t in repos.theses.list() if t.status is ThesisStatus.EM_DEBATE
        ]
        assert len(bloqueada) == 1
        assert len(repos.theses.blocking_claims(bloqueada[0].id)) == 1


def test_dois_cenarios_hidrologicos_distintos(session, seeded) -> None:
    """RF-53 / AC-42."""
    with run_context(as_of=AS_OF, dataset_kind=DatasetKind.DEMO, actor="pytest"):
        repos = Repositories(session)
        ativa = repos.theses.active()[0]
        assert repos.scenarios.hydrological_count(ativa.id) == 2
        nomes = {s.name for s in repos.scenarios.list()}
    assert nomes == {"Base", "Seco"}


def test_alerta_de_cobertura_existe(session, seeded) -> None:
    """RF-36: fonte indisponivel nunca vira silencio."""
    tipos = {
        a.alert_kind
        for a in session.execute(select(Alert)).scalars()
    }
    assert AlertKind.COBERTURA_DADOS in tipos
    assert AlertKind.PREMISSA_VIOLADA in tipos

    run = session.execute(
        select(func.count()).select_from(Alert).where(Alert.evidence_id.is_(None))
    ).scalar_one()
    assert run == 0  # todo alerta tem lastro


def test_idempotencia(session, seeded) -> None:
    with run_context(as_of=AS_OF, dataset_kind=DatasetKind.DEMO, actor="pytest"):
        assert already_seeded(session) is True


def test_purge_remove_demo_mas_preserva_a_trilha(session, seeded) -> None:
    """C7: a auditoria e permanente, inclusive para DEMO."""
    antes = session.execute(select(func.count()).select_from(AuditLog)).scalar_one()
    with run_context(
        as_of=AS_OF, dataset_kind=DatasetKind.DEMO, actor="pytest", actor_type=ActorType.SISTEMA
    ):
        removidas = purge_demo(session)
        session.flush()

    assert removidas > 0
    assert session.execute(select(func.count()).select_from(Thesis)).scalar_one() == 0
    depois = session.execute(select(func.count()).select_from(AuditLog)).scalar_one()
    assert depois > antes  # trilha so cresce
