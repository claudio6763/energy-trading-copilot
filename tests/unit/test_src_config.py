"""Configuracao de IA em `src/config.py`: AI_MODE tem precedencia sobre DEMO_MODE."""

from __future__ import annotations

import pytest

from src.config import get_settings, reset_settings


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "AI_MODE", "DEMO_MODE", "AI_MAX_TOKENS",
                "AI_TEMPERATURE", "AI_TIMEOUT_SECONDS", "AI_AUTO_REVIEW_ON_ALERT",
                "LLM_MAX_OUTPUT_TOKENS"):
        monkeypatch.delenv(var, raising=False)
    reset_settings()
    yield
    reset_settings()


def test_sem_chave_e_sem_ai_mode_fica_demo(monkeypatch):
    reset_settings()
    assert get_settings().mode == "DEMO"


def test_ai_mode_live_com_chave_fica_real(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-teste")
    monkeypatch.setenv("AI_MODE", "live")
    reset_settings()
    assert get_settings().mode == "REAL"


def test_ai_mode_live_sem_chave_continua_demo(monkeypatch):
    monkeypatch.setenv("AI_MODE", "live")
    reset_settings()
    assert get_settings().mode == "DEMO"


def test_ai_mode_demo_forca_demo_mesmo_com_chave(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-teste")
    monkeypatch.setenv("AI_MODE", "demo")
    reset_settings()
    assert get_settings().mode == "DEMO"


def test_ai_max_tokens_tem_precedencia_sobre_legado(monkeypatch):
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "1000")
    monkeypatch.setenv("AI_MAX_TOKENS", "2500")
    reset_settings()
    assert get_settings().llm_max_output_tokens == 2500


def test_legado_ainda_funciona_sem_ai_max_tokens(monkeypatch):
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "1000")
    reset_settings()
    assert get_settings().llm_max_output_tokens == 1000


def test_ai_auto_review_on_alert_default_desligado(monkeypatch):
    reset_settings()
    assert get_settings().ai_auto_review_on_alert is False


def test_ai_auto_review_on_alert_liga_por_env(monkeypatch):
    monkeypatch.setenv("AI_AUTO_REVIEW_ON_ALERT", "true")
    reset_settings()
    assert get_settings().ai_auto_review_on_alert is True


def test_ai_temperature_e_timeout_tem_default_seguro(monkeypatch):
    reset_settings()
    settings = get_settings()
    assert settings.ai_temperature == 0.2
    assert settings.ai_timeout_seconds == 60.0
