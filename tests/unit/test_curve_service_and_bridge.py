"""Curva estatistica publica (P10/P50/P90) e ponte de persistencia da ingestao.

Banco SQLite em memoria — rapido, sem tocar disco, sem rede.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest

from copilot.common.enums import AdapterStatus
from copilot.ingest.adapters.public import CceeAdapter, OnsAdapter
from copilot.ingest.contracts import AdapterResult
from src.database import repositories as R
from src.database.connection import init_db
from src.services import curve_service as CS
from src.services.ingestion_bridge import persist_adapter_result

AS_OF = "2026-08-14"


@pytest.fixture()
def conn() -> Iterator[object]:
    c = init_db(path=":memory:")
    yield c
    c.close()


def _seed_pld(conn, *, submarket: str = "SE/CO") -> None:
    for ano, preco in (("2023", "150.00"), ("2024", "420.00"), ("2025", "200.00")):
        R.insert_observation(
            conn, metric="pld_mensal_seco", value=Decimal(preco), unit="R$/MWh",
            ref_date=f"{ano}-09-01", as_of=f"{ano}-09-01", source_name="teste",
            classification="observado", submarket=submarket,
        )


# =============================================================== curve_service
def test_percentis_com_historico_suficiente(conn) -> None:
    _seed_pld(conn)
    resultado = CS.compute_statistical_scenario(conn, as_of=AS_OF, submarket="SE/CO",
                                                 metric_like="pld_mensal%")
    assert resultado["status"] == "OK"
    ponto_setembro = next(p for p in resultado["points"] if p.horizon_label == "M+1")
    assert ponto_setembro.status == "OK"
    assert ponto_setembro.p10 < ponto_setembro.p50 < ponto_setembro.p90
    assert ponto_setembro.n_observations == 3


def test_ponto_sem_tres_anos_fica_insufficient_data(conn) -> None:
    _seed_pld(conn)  # so preenche setembro
    resultado = CS.compute_statistical_scenario(conn, as_of=AS_OF, submarket="SE/CO",
                                                 metric_like="pld_mensal%")
    outro_mes = next(p for p in resultado["points"] if p.horizon_label == "M+2")
    assert outro_mes.status == "INSUFFICIENT_DATA"
    assert outro_mes.p50 is None


def test_sem_historico_algum_e_insufficient_data(conn) -> None:
    resultado = CS.compute_statistical_scenario(conn, as_of=AS_OF, submarket="SE/CO")
    assert resultado["status"] == "INSUFFICIENT_DATA"
    assert resultado["points"] == []


def test_disclaimer_obrigatorio_presente() -> None:
    assert "não representa" in CS.DISCLAIMER.lower()
    assert "cotação negociada" in CS.DISCLAIMER.lower()


def test_persistencia_grava_apenas_pontos_ok(conn) -> None:
    _seed_pld(conn)
    resultado = CS.compute_statistical_scenario(conn, as_of=AS_OF, submarket="SE/CO",
                                                 metric_like="pld_mensal%")
    ids = CS.persist_statistical_scenario(conn, resultado, as_of=AS_OF)
    assert set(ids) == {"P10", "P50", "P90"}
    pontos = R.curve_points(conn, ids["P50"])
    assert len(pontos) == 1  # so M+1 tinha 3 anos de historico
    assert pontos[0]["tenor"] == "M+1"


def test_nunca_persiste_quando_status_nao_e_ok(conn) -> None:
    resultado = CS.compute_statistical_scenario(conn, as_of=AS_OF, submarket="SE/CO")
    ids = CS.persist_statistical_scenario(conn, resultado, as_of=AS_OF)
    assert ids == {}


# =============================================================== ingestion_bridge
def test_bridge_persiste_observacoes_reais_com_evidencia(conn) -> None:
    resultado = OnsAdapter().parse(
        (
            b'{"as_of": "2026-08-09", "errors": [], "datasets": {"carga": '
            b'{"url": "u", "year": "2026", "csv": '
            b'"id_subsistema;nom_subsistema;din_instante;val_cargaenergiamwmed\\n'
            b'SE;Sudeste;2026-08-01;40000.500\\n"}}}'
        ),
        as_of=date(2026, 8, 9),
    )
    saida = persist_adapter_result(conn, resultado, as_of="2026-08-09", access_label="PUBLIC_NO_AUTH")
    assert saida["ok"] is True
    assert saida["observations"] == 1
    linha = R.latest_observation(conn, "carga_verificada_mwmed_seco", as_of="2026-08-09")
    assert linha is not None
    assert linha["evidence_id"]
    fonte = R.list_sources(conn)[0]
    assert fonte["integration_status"] == "LIVE_VALIDATED"
    assert "PUBLIC_NO_AUTH" in fonte["license_note"]


def test_bridge_e_idempotente(conn) -> None:
    resultado = OnsAdapter().parse(
        (
            b'{"as_of": "2026-08-09", "errors": [], "datasets": {"carga": '
            b'{"url": "u", "year": "2026", "csv": '
            b'"id_subsistema;nom_subsistema;din_instante;val_cargaenergiamwmed\\n'
            b'SE;Sudeste;2026-08-01;40000.500\\n"}}}'
        ),
        as_of=date(2026, 8, 9),
    )
    persist_adapter_result(conn, resultado, as_of="2026-08-09")
    persist_adapter_result(conn, resultado, as_of="2026-08-09")
    total = conn.execute("SELECT COUNT(*) c FROM market_observations").fetchone()["c"]
    assert total == 1


def test_bridge_registra_fonte_indisponivel_sem_gravar_dado(conn) -> None:
    payload = b'{"granularity": "mensal", "url": "u", "year": 2026, "csv": "colunas;erradas\\n1;2\\n"}'
    resultado = CceeAdapter().parse(payload, as_of=date(2026, 8, 9))
    assert resultado.status is AdapterStatus.INDISPONIVEL
    saida = persist_adapter_result(conn, resultado, as_of="2026-08-09", access_label="PUBLIC_NO_AUTH")
    assert saida["ok"] is False
    assert saida["observations"] == 0
    total = conn.execute("SELECT COUNT(*) c FROM market_observations").fetchone()["c"]
    assert total == 0
    run = conn.execute("SELECT * FROM ingest_snapshots WHERE adapter='ccee'").fetchone()
    assert run is not None  # a run fica registrada mesmo sem dado (RF-36)


def test_bridge_grava_run_de_ingestao_com_hash(conn) -> None:
    resultado: AdapterResult = OnsAdapter().parse(
        (
            b'{"as_of": "2026-08-09", "errors": [], "datasets": {"carga": '
            b'{"url": "u", "year": "2026", "csv": '
            b'"id_subsistema;nom_subsistema;din_instante;val_cargaenergiamwmed\\n'
            b'SE;Sudeste;2026-08-01;40000.500\\n"}}}'
        ),
        as_of=date(2026, 8, 9),
    )
    persist_adapter_result(conn, resultado, as_of="2026-08-09")
    linha = conn.execute("SELECT * FROM ingest_snapshots WHERE adapter='ons'").fetchone()
    assert linha["status"] == "OK"
    assert linha["rows_written"] == 1
