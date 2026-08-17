"""Cada consulta usada pelas telas do Streamlit, contra o Postgres real.

So roda com `DATABASE_URL`/`COPILOT_DB` apontando para Postgres (marcador
`postgres`, pulado por padrao):

    DATABASE_URL=postgresql://... pytest -m postgres tests/services/test_screen_queries_postgres.py

Existe porque o deploy provou uma classe de bug inteira sem cobertura: nenhuma
query de tela tinha sido exercitada contra Postgres antes da defesa — so o
caminho novo (motor -> thesis_book) tinha teste real (`test_motor_service_postgres.py`).
`source_freshness` quebrou com `GroupingError` (coluna solta ao lado de
`MAX()` sem `GROUP BY`; SQLite tolera, Postgres nao) em produção, em duas
telas (Dashboard e Dados e fontes) e no Watchdog (`run_once`). Este arquivo:

1. Carrega `app.py` de verdade via `AppTest` contra o Postgres e visita cada
   area do menu lateral — reproduz exatamente o que a defesa vai clicar.
2. Testa isoladamente os quatro `INSERT OR REPLACE` que so existiam em
   sintaxe SQLite (`market_observations`, `forward_curves`,
   `forward_curve_points`, `scenario_results`), agora `upsert_row()`
   dialeto-consciente — prova que gravar duas vezes a mesma chave natural
   atualiza a linha em vez de lançar erro de sintaxe.
3. Testa o RAG (FTS5): SQLite-only por natureza (sem indice equivalente em
   Postgres nesta versao). Correto aqui nao e funcionar, e degradar sem
   quebrar a tela — `search()` devolve lista vazia, `add_document()` recusa
   com mensagem clara em vez de deixar subir um erro de tabela inexistente.

Todo dado escrito por este arquivo é tageado (`pytest_postgres_screen_*`) e
removido no teardown — nunca fica lixo na base de produção.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.config import load_dotenv
from src.database.connection import connect, dialect_of, get_database_url

load_dotenv()  # popula DATABASE_URL/COPILOT_DB do .env antes do skipif de coleta

APP_PATH = str(Path(__file__).resolve().parents[2] / "app.py")
AS_OF = "2026-08-14"
TAG = "pytest_postgres_screen"


def _tem_postgres_configurado() -> bool:
    url = get_database_url()
    return bool(url) and url.startswith(("postgres://", "postgresql://"))


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not _tem_postgres_configurado(),
        reason="DATABASE_URL/COPILOT_DB nao aponta para Postgres nesta execucao.",
    ),
]

_TABELAS_SEM_RESIDUO = ("alerts", "watchdog_runs", "evidence", "audit_log")  # filhas antes das pais


@pytest.fixture(autouse=True)
def _sem_residuo_no_neon():
    """Rede de seguranca: qualquer linha nova nessas tabelas ao final do teste
    e apagada — mesmo quando o efeito colateral vem de dentro do `AppTest`
    (clique real em botao) e nao so das escritas explicitas deste arquivo.
    Este arquivo roda perto da defesa; nao pode acumular rastro a cada rodada.
    """
    conn = connect()
    try:
        antes = {
            t: {r["id"] for r in conn.execute(f"SELECT id FROM {t}").fetchall()}
            for t in _TABELAS_SEM_RESIDUO
        }
    finally:
        conn.close()

    yield

    conn = connect()
    try:
        for t in _TABELAS_SEM_RESIDUO:
            novos = {r["id"] for r in conn.execute(f"SELECT id FROM {t}").fetchall()} - antes[t]
            for nid in novos:
                conn.execute(f"DELETE FROM {t} WHERE id = ?", (nid,))
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# 1. Cada area da barra lateral, carregada de verdade contra Postgres
# =============================================================================
AREAS = [
    "Mesa", "Registrar tese", "Tese", "Dados e procedência", "Dashboard",
    "Teses", "Debate", "Monitor", "Dados e fontes",
]


def test_todas_as_areas_carregam_sem_excecao_contra_postgres():
    """Regressao do `GroupingError`: qualquer excecao aqui e uma tela que quebra na defesa."""
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.run()
    assert not at.exception, f"Falha na carga inicial: {at.exception}"

    for area in AREAS:
        at.sidebar.radio[0].set_value(area).run()
        assert not at.exception, f"Área '{area}' lançou exceção contra Postgres: {at.exception}"


def test_watchdog_run_once_contra_postgres():
    """'Executar Watchdog agora' — mesmo ciclo que `source_freshness` quebrava."""
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.run()
    at.sidebar.radio[0].set_value("Monitor").run()
    assert not at.exception

    botao = next((b for b in at.button if b.label == "Executar Watchdog agora"), None)
    assert botao is not None, "Botão 'Executar Watchdog agora' não encontrado na tela Monitor."
    botao.click().run()
    assert not at.exception, f"Watchdog.run_once() lançou exceção contra Postgres: {at.exception}"


def test_buscar_rag_nao_quebra_a_tela_contra_postgres():
    """FTS5 não existe em Postgres — o botão 'Buscar' precisa degradar, não crashar."""
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.run()
    at.sidebar.radio[0].set_value("Dados e fontes").run()
    assert not at.exception

    botao = next((b for b in at.button if b.label == "Buscar"), None)
    assert botao is not None, "Botão 'Buscar' (RAG) não encontrado em Dados e fontes."
    botao.click().run()
    assert not at.exception, f"Busca RAG lançou exceção contra Postgres: {at.exception}"


# =============================================================================
# 2. Upsert dialeto-consciente — os quatro `INSERT OR REPLACE` reais do projeto
# =============================================================================
@pytest.fixture()
def pg_conn():
    conn = connect()
    assert dialect_of(conn) == "postgres"
    try:
        yield conn
    finally:
        conn.close()


def test_upsert_market_observations_contra_postgres(pg_conn):
    from src.database import repositories as R

    metric = f"{TAG}_metric"
    try:
        oid1, _ = R.insert_observation(
            pg_conn, metric=metric, value=Decimal("100.00"), unit="R$/MWh",
            ref_date=AS_OF, as_of=AS_OF, source_name="pytest", classification="manual",
        )
        oid2, _ = R.insert_observation(
            pg_conn, metric=metric, value=Decimal("200.00"), unit="R$/MWh",
            ref_date=AS_OF, as_of=AS_OF, source_name="pytest", classification="manual",
        )
        pg_conn.commit()

        linhas = pg_conn.execute(
            "SELECT id, value FROM market_observations WHERE metric = ?", (metric,)
        ).fetchall()
        assert len(linhas) == 1, "Chave natural duplicada devia sobrescrever, não somar linha."
        assert linhas[0]["id"] == oid2
        assert Decimal(str(linhas[0]["value"])) == Decimal("200.00")
    finally:
        pg_conn.execute("DELETE FROM market_observations WHERE metric = ?", (metric,))
        pg_conn.execute(
            "DELETE FROM evidence WHERE locator LIKE ?", (f"{metric}@%",)
        )
        pg_conn.commit()


def test_upsert_forward_curve_e_pontos_contra_postgres(pg_conn):
    from src.database import repositories as R

    curve_name = f"{TAG}_curve"
    try:
        cid1, _ = R.insert_curve(
            pg_conn, curve_name=curve_name, submarket="SE/CO", as_of=AS_OF,
            source_name="pytest", classification="manual", notes="v1",
        )
        cid2, _ = R.insert_curve(
            pg_conn, curve_name=curve_name, submarket="SE/CO", as_of=AS_OF,
            source_name="pytest", classification="manual", notes="v2",
        )
        pid1, _ = R.insert_curve_point(
            pg_conn, cid2, tenor="M+1", delivery_start=AS_OF, delivery_end=AS_OF,
            price=Decimal("150.00"), source_name="pytest", as_of=AS_OF, classification="manual",
        )
        pid2, _ = R.insert_curve_point(
            pg_conn, cid2, tenor="M+1", delivery_start=AS_OF, delivery_end=AS_OF,
            price=Decimal("175.00"), source_name="pytest", as_of=AS_OF, classification="manual",
        )
        pg_conn.commit()

        cabecalhos = pg_conn.execute(
            "SELECT id, notes FROM forward_curves WHERE curve_name = ?", (curve_name,)
        ).fetchall()
        assert len(cabecalhos) == 1
        assert cabecalhos[0]["id"] == cid2
        assert cabecalhos[0]["notes"] == "v2"

        pontos = pg_conn.execute(
            "SELECT id, price FROM forward_curve_points WHERE curve_id = ?", (cid2,)
        ).fetchall()
        assert len(pontos) == 1
        assert pontos[0]["id"] == pid2
        assert Decimal(str(pontos[0]["price"])) == Decimal("175.00")
    finally:
        pg_conn.execute("DELETE FROM forward_curves WHERE curve_name = ?", (curve_name,))
        pg_conn.execute("DELETE FROM evidence WHERE locator LIKE ?", (f"curva:{curve_name}%",))
        pg_conn.commit()


def test_upsert_scenario_results_contra_postgres(pg_conn):
    from src.database import repositories as R
    from src.services import thesis_service as TS

    tid = TS.create_thesis(
        pg_conn, title=f"[{TAG}] tese", summary="Uma linha.", direction="VENDER",
        product="Forward", submarket="SE/CO", owner="pytest", as_of=AS_OF,
    )
    try:
        eid = R.create_evidence(
            pg_conn, kind="CALCULO", source_name="pytest", excerpt="cenario de teste",
            as_of=AS_OF, classification="projetado",
        )
        R.upsert_row(
            pg_conn, table="scenario_results",
            columns=("id", "thesis_id", "scenario", "is_stress", "probability", "shocked_price",
                     "pnl", "var_impact", "thesis_delta", "as_of", "evidence_id", "created_at"),
            values=(R.new_id(), tid, "BASE", 0, "0.5", "150.00", "1000.00", "0", None,
                    AS_OF, eid, R.now_iso()),
            conflict_cols=("thesis_id", "scenario", "as_of"),
        )
        segundo_id = R.new_id()
        R.upsert_row(
            pg_conn, table="scenario_results",
            columns=("id", "thesis_id", "scenario", "is_stress", "probability", "shocked_price",
                     "pnl", "var_impact", "thesis_delta", "as_of", "evidence_id", "created_at"),
            values=(segundo_id, tid, "BASE", 0, "0.5", "160.00", "2000.00", "0", None,
                    AS_OF, eid, R.now_iso()),
            conflict_cols=("thesis_id", "scenario", "as_of"),
        )
        pg_conn.commit()

        linhas = pg_conn.execute(
            "SELECT id, pnl FROM scenario_results WHERE thesis_id = ?", (tid,)
        ).fetchall()
        assert len(linhas) == 1
        assert linhas[0]["id"] == segundo_id
        assert Decimal(str(linhas[0]["pnl"])) == Decimal("2000.00")
    finally:
        pg_conn.execute("DELETE FROM theses WHERE id = ?", (tid,))  # cascade cuida do resto
        pg_conn.commit()


def test_source_freshness_contra_postgres_com_dado_real(pg_conn):
    """A query que quebrava: MAX()/COUNT() ao lado de `classification` sem GROUP BY."""
    from src.database import repositories as R

    metric = f"{TAG}_freshness"
    try:
        R.insert_observation(
            pg_conn, metric=metric, value=Decimal("42.00"), unit="R$/MWh",
            ref_date=AS_OF, as_of=AS_OF, source_name="pytest", classification="observado",
        )
        pg_conn.commit()

        linhas = R.source_freshness(pg_conn, as_of=AS_OF)
        alvo = next((l for l in linhas if l["metric"] == metric), None)
        assert alvo is not None
        assert alvo["classification"] == "observado"
        assert alvo["observations"] == 1
        assert alvo["age_days"] == 0
    finally:
        pg_conn.execute("DELETE FROM market_observations WHERE metric = ?", (metric,))
        pg_conn.execute("DELETE FROM evidence WHERE locator LIKE ?", (f"{metric}@%",))
        pg_conn.commit()


# =============================================================================
# 3. RAG (FTS5): SQLite-only por natureza — degrada, não quebra
# =============================================================================
def test_rag_search_degrada_sem_quebrar_contra_postgres(pg_conn):
    from src.rag import store as RAG

    resultados = RAG.search_with_evidence(pg_conn, "penalidade por insuficiência de lastro",
                                          as_of=AS_OF)
    assert resultados == []


def test_rag_add_document_recusa_com_mensagem_clara_contra_postgres(pg_conn):
    from src.rag import store as RAG

    with pytest.raises(RuntimeError, match="SQLite-only"):
        RAG.add_document(
            pg_conn, title="x", institution="CCEE", doc_type="RESOLUCAO", pages=["texto"],
        )
