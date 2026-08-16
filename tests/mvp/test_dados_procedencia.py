"""Smoke test da tela Dados e procedência."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[2] / "app.py")


@pytest.fixture()
def app_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DB", str(tmp_path / "procedencia_smoke.db"))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from src.config import reset_settings
    reset_settings()
    from src.database.connection import init_db
    init_db().close()


def test_dados_procedencia_mostra_manifesto_real(app_env):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value("Dados e procedência").run()
    assert not at.exception

    metricas = {m.label: m.value for m in at.metric}
    assert metricas.get("Status do motor") == "DEFINITIVO"

    caption_text = " ".join(c.value for c in at.caption)
    assert "hash do snapshot" in caption_text
