"""Regressao: sqlite3.Connection nao pode atravessar threads.

O Dashboard (`app.py`) quebrava com

    sqlite3.ProgrammingError: SQLite objects created in a thread can only
    be used in that same thread.

porque a conexao era criada uma vez com `st.cache_resource` e reutilizada
entre reruns do Streamlit, que podem executar em threads diferentes. A
correcao remove qualquer `Connection` cacheada/global e abre uma nova por
execucao via `connection.connect()`. Estes testes fixam esse contrato.
"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from src.database.connection import connect, init_db
from src.database import repositories as R  # noqa: F401  (mantido para simetria com outros testes)
from src.services import thesis_service as TS

AS_OF = "2026-08-14"


def _nova_tese(conn: sqlite3.Connection, titulo: str) -> str:
    return TS.create_thesis(
        conn, title=titulo, summary="Uma linha.", direction="VENDER",
        product="Forward", submarket="SE/CO", owner="pytest", as_of=AS_OF,
        exit_condition="sair em 260", invalidation="EAR<45",
    )


@pytest.fixture()
def db_file(tmp_path: Path) -> Path:
    path = tmp_path / "concorrencia.db"
    conn = init_db(path=path)
    try:
        for i in range(3):
            _nova_tese(conn, f"Tese {i}")
    finally:
        conn.close()
    return path


def test_connect_nao_reutiliza_a_mesma_conexao(db_file: Path) -> None:
    """Requisitos 1/2: cada chamada a `connect()` devolve um objeto novo."""
    a = connect(db_file)
    b = connect(db_file)
    try:
        assert a is not b
    finally:
        a.close()
        b.close()


def test_connect_configura_row_factory_timeout_e_wal(db_file: Path) -> None:
    """Requisitos 3/4: row_factory, busy_timeout e WAL (quando o filesystem permite)."""
    conn = connect(db_file)
    try:
        assert conn.row_factory is sqlite3.Row
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy_timeout >= 15000
        modo = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert modo.lower() in ("wal", "delete")  # DELETE e o fallback documentado
    finally:
        conn.close()


def test_conexao_criada_em_uma_thread_nao_pode_ser_usada_em_outra(db_file: Path) -> None:
    """Caracteriza o bug original: reaproveitar a MESMA Connection entre
    threads continua falhando (comportamento padrao do sqlite3). A correcao
    funciona por nunca compartilhar a conexao — nao por desligar essa protecao.
    """
    conn = connect(db_file)
    erros: list[BaseException] = []

    def usar_em_outra_thread() -> None:
        try:
            conn.execute("SELECT 1")
        except BaseException as exc:  # noqa: BLE001 - captura para asserção no thread principal
            erros.append(exc)

    t = threading.Thread(target=usar_em_outra_thread)
    t.start()
    t.join(timeout=10)
    conn.close()

    assert len(erros) == 1
    assert isinstance(erros[0], sqlite3.ProgrammingError)


def test_list_theses_em_threads_diferentes_com_conexao_propria(db_file: Path) -> None:
    """Reproduz o Dashboard sob concorrencia: cada thread abre sua propria
    conexao (como `app.py` faz agora) e chama `ThesisService.list_theses`.
    Antes da correcao, uma Connection global cacheada disparava
    `sqlite3.ProgrammingError` nesse cenario.
    """
    resultados: list[int] = []
    erros: list[BaseException] = []
    lock = threading.Lock()

    def tarefa() -> None:
        conn = connect(db_file)
        try:
            teses = TS.list_theses(conn)
            with lock:
                resultados.append(len(teses))
        except BaseException as exc:  # noqa: BLE001
            with lock:
                erros.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=tarefa) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not erros, f"erros inesperados nas threads: {erros}"
    assert resultados == [3] * 8


def test_leituras_e_escritas_concorrentes_em_pool_de_threads(db_file: Path) -> None:
    """Simula varias sessoes Streamlit simultaneas: leituras e escritas
    concorrentes, cada operacao com sua propria conexao.
    """

    def escrever(i: int) -> str:
        conn = connect(db_file)
        try:
            return _nova_tese(conn, f"Concorrente {i}")
        finally:
            conn.close()

    def ler() -> int:
        conn = connect(db_file)
        try:
            return len(TS.list_theses(conn))
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        futuros = [pool.submit(escrever, i) for i in range(5)]
        futuros += [pool.submit(ler) for _ in range(5)]
        resultados = [f.result(timeout=15) for f in as_completed(futuros)]

    assert len(resultados) == 10

    conn = connect(db_file)
    try:
        assert len(TS.list_theses(conn)) == 3 + 5
    finally:
        conn.close()
