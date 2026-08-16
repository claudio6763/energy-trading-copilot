"""Smoke test do Streamlit: reproduz o `TypeError: cannot pickle 'sqlite3.Row'`.

`AppTest.run()` executa o script como o Streamlit executa de verdade,
incluindo a serializacao do estado dos widgets — e o unico jeito confiavel
de pegar essa classe de bug de novo se ela voltar.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

AS_OF = "2026-08-14"
APP_PATH = str(Path(__file__).resolve().parents[2] / "app.py")


@pytest.fixture()
def app_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DB", str(tmp_path / "app_smoke.db"))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_MODE", raising=False)
    from src.config import reset_settings
    reset_settings()


def _seed(tmp_path, monkeypatch, app_env):
    """Semeia o mesmo banco que o app vai abrir, com uma tese cadastrada."""
    from src.database.connection import init_db
    from src.database import repositories as R
    from src.services import thesis_service as TS

    conn = init_db()
    tid = TS.create_thesis(
        conn, title="Tese smoke", summary="Uma linha.", direction="VENDER",
        product="Forward", submarket="SE/CO", owner="pytest", as_of=AS_OF,
        exit_condition="sair em 260", invalidation="EAR<45",
        expected_low=Decimal("-1"), expected_mid=Decimal("0"), expected_high=Decimal("1"))
    conn.close()
    return tid


# -------------------------------------------------------- selectbox com sqlite3.Row
def test_area_teses_nao_quebra_com_selectbox_de_tese(app_env, tmp_path, monkeypatch):
    """Regressao do bug: `st.selectbox("Tese", teses, ...)` com `sqlite3.Row` cru."""
    _seed(tmp_path, monkeypatch, app_env)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception

    at.sidebar.radio[0].set_value("Teses").run()
    assert not at.exception


def test_area_debate_nao_quebra_com_selectbox_de_tese(app_env, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, app_env)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("Debate").run()
    assert not at.exception


# ------------------------------------------------------------------- lista vazia
def test_area_teses_com_lista_vazia_nao_quebra(app_env, tmp_path, monkeypatch):
    """Sem nenhuma tese cadastrada: nem `list(dict.keys())` nem o `format_func` podem quebrar."""
    from src.database.connection import init_db
    init_db().close()

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("Teses").run()
    assert not at.exception
    at.sidebar.radio[0].set_value("Debate").run()
    assert not at.exception


# --------------------------------------------------------------------- outras areas
def test_dashboard_carrega(app_env, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, app_env)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception


def test_monitor_carrega(app_env, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, app_env)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("Monitor").run()
    assert not at.exception


def test_dados_e_fontes_carrega(app_env, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, app_env)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("Dados e fontes").run()
    assert not at.exception


def test_modo_demonstracao_exibido_sem_chave(app_env, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, app_env)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    avisos = " ".join(w.value for w in at.sidebar.warning)
    assert "MODO DEMONSTRA" in avisos
