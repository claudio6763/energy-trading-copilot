"""Escopo obrigatorio: DEMO x REAL (RF-57 / AC-57) e data-base (RF-58 / AC-55)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from copilot.common.context import run_context
from copilot.common.enums import (
    ActorType,
    DatasetKind,
    Submarket,
    ThesisDirection,
    ThesisStatus,
    Unit,
)
from copilot.common.errors import DatasetKindViolation
from copilot.db.models import Thesis
from copilot.db.repositories import Repositories
from tests.conftest import AS_OF
from tests.fixtures.builders import make_evidence, make_source, make_thesis


def _ctx(kind: DatasetKind, as_of: date = AS_OF):
    return run_context(
        as_of=as_of, dataset_kind=kind, actor="pytest", actor_type=ActorType.SISTEMA
    )


def test_demo_e_real_nao_se_enxergam(session) -> None:
    """AC-57: nenhuma agregacao mistura os dois datasets."""
    with _ctx(DatasetKind.DEMO):
        make_thesis(Repositories(session), as_of=AS_OF, title="Tese DEMO")
    with _ctx(DatasetKind.REAL):
        make_thesis(Repositories(session), as_of=AS_OF, title="Tese REAL")
    session.flush()

    with _ctx(DatasetKind.DEMO):
        repos = Repositories(session)
        titulos = {t.title for t in repos.theses.list()}
        assert titulos == {"Tese DEMO"}
        assert repos.theses.count() == 1

    with _ctx(DatasetKind.REAL):
        repos = Repositories(session)
        assert {t.title for t in repos.theses.list()} == {"Tese REAL"}

    # A tabela tem as duas: a separacao e de consulta, nao de armazenamento.
    assert session.query(Thesis).count() == 2


def test_get_nao_atravessa_dataset(session) -> None:
    with _ctx(DatasetKind.REAL):
        real = make_thesis(Repositories(session), as_of=AS_OF, title="Somente REAL")
        session.flush()
        real_id = real.id

    with _ctx(DatasetKind.DEMO):
        assert Repositories(session).theses.get(real_id) is None
        with pytest.raises(LookupError, match="DEMO"):
            Repositories(session).theses.get_or_raise(real_id)


def test_gravar_com_dataset_divergente_e_bloqueado(session) -> None:
    """P9: declarar REAL dentro de um contexto DEMO e erro, nao correcao silenciosa."""
    with _ctx(DatasetKind.DEMO):
        repos = Repositories(session)
        objeto = Thesis(
            dataset_kind=DatasetKind.REAL,
            title="Contrabando",
            summary="uma linha",
            direction=ThesisDirection.COMPRA,
            product="Forward",
            submarket=Submarket.SE_CO,
            author="pytest",
            status=ThesisStatus.RASCUNHO,
            version=1,
            var_limit=Decimal("50000000.00"),
            as_of=AS_OF,
        )
        with pytest.raises(DatasetKindViolation):
            repos.theses.add(objeto)


def test_look_ahead_e_impossivel(session) -> None:
    """AC-55: com as_of = 14/08, dado de 15/08 nao aparece."""
    with _ctx(DatasetKind.DEMO, as_of=AS_OF + timedelta(days=10)):
        repos = Repositories(session)
        source = make_source(repos)
        series = repos.series.register(
            metric_key="pld_se_semanal",
            description="Serie de teste.",
            unit=Unit.BRL_PER_MWH,
            frequency="semanal",
            source=source,
        )
        for offset in (-1, 0, 1, 2):
            ref = AS_OF + timedelta(days=offset)
            evidence = make_evidence(
                repos, value=Decimal("100.00"), unit=Unit.BRL_PER_MWH, as_of=ref, source=source
            )
            repos.observations.record(
                series=series,
                ref_date=ref,
                value=Decimal("100.00"),
                evidence_id=evidence.id,
                as_of=ref,
            )
        session.flush()

    with _ctx(DatasetKind.DEMO, as_of=AS_OF):
        repos = Repositories(session)
        visiveis = repos.observations.series_history("pld_se_semanal")
        assert [o.as_of for o in visiveis] == [AS_OF - timedelta(days=1), AS_OF]
        assert all(o.as_of <= AS_OF for o in visiveis)

        ultima = repos.observations.latest("pld_se_semanal")
        assert ultima is not None and ultima.as_of == AS_OF


def test_evidencia_futura_tambem_fica_invisivel(session) -> None:
    with _ctx(DatasetKind.DEMO, as_of=AS_OF + timedelta(days=5)):
        repos = Repositories(session)
        futura = make_evidence(repos, as_of=AS_OF + timedelta(days=3))
        session.flush()
        futura_id = futura.id

    with _ctx(DatasetKind.DEMO, as_of=AS_OF):
        assert Repositories(session).evidence.get(futura_id) is None
