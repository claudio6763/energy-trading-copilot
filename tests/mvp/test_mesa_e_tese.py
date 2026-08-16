"""Smoke tests das telas Mesa (home) e Tese (detalhe)."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[2] / "app.py")


@pytest.fixture()
def app_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DB", str(tmp_path / "mesa_smoke.db"))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_MODE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from src.config import reset_settings
    reset_settings()
    from src.database.connection import init_db
    init_db().close()


def test_mesa_com_lista_vazia_nao_quebra(app_env):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()  # Mesa e o default
    assert not at.exception
    assert any("Nenhuma tese registrada" in i.value for i in at.info)


def _registrar_tese_via_ui(at):
    at.sidebar.radio[0].set_value("Registrar tese").run()
    [b for b in at.button if b.label == "Gerar book"][0].click().run()
    [b for b in at.button if b.label == "Rodar Desafiar"][0].click().run()
    [ta for ta in at.text_area if ta.key == "registrar_trader_response"][0].set_value(
        "Aceito o risco declarado."
    ).run()
    [b for b in at.button if b.label == "Salvar tese"][0].click().run()
    assert not at.exception
    assert any("Tese registrada" in s.value for s in at.success)


def test_mesa_mostra_book_proposto_apos_registro(app_env):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    _registrar_tese_via_ui(at)

    at.sidebar.radio[0].set_value("Mesa").run()
    assert not at.exception
    assert any("BOOK PROPOSTO" in h.value for h in at.subheader)
    metricas = {m.label: m.value for m in at.metric}
    assert any("Energia" in k for k in metricas)


def test_tese_detalhe_mostra_ladder_e_desafio(app_env):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    _registrar_tese_via_ui(at)

    at.sidebar.radio[0].set_value("Tese").run()
    assert not at.exception
    assert any("Desafiar" in h.value for h in at.subheader)
    texto = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "PREMISSA" in texto or "CALCULADO" in texto


def test_mesa_vigiar_dispara_alerta_de_referencia_alterada(app_env):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    _registrar_tese_via_ui(at)

    at.sidebar.radio[0].set_value("Mesa").run()
    expansores = [e for e in at.expander if "Atualizar leitura" in (e.label or "")]
    assert expansores
    campos = [ni for ni in at.number_input if ni.key and ni.key.startswith("vigiar_2026-12")]
    assert campos, "campo de vigilancia de dez/26 nao encontrado"
    campos[0].set_value(999.0).run()
    [b for b in at.button if b.label == "Verificar vigilância"][0].click().run()
    assert not at.exception

    texto = " ".join(e.label or "" for e in at.expander)
    assert "Referência de vértice mudou" in texto or "limite" in texto.lower()
