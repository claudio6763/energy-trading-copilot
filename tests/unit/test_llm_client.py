"""Cliente Anthropic: modo demonstracao, modo real e tratamento de erro.

Nenhum teste aqui faz chamada paga: o SDK `anthropic` e sempre mockado.
"""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture()
def _fake_anthropic_module(monkeypatch):
    """Instala um modulo `anthropic` falso, controlavel pelo teste."""
    modulo = types.ModuleType("anthropic")

    class AnthropicError(Exception):
        pass

    class AuthenticationError(AnthropicError):
        pass

    class RateLimitError(AnthropicError):
        pass

    class APITimeoutError(AnthropicError):
        pass

    class APIConnectionError(AnthropicError):
        pass

    class APIStatusError(AnthropicError):
        def __init__(self, message="erro", status_code=500):
            super().__init__(message)
            self.status_code = status_code

    class _FakeMessages:
        def __init__(self, behavior):
            self._behavior = behavior

        def create(self, **kwargs):
            self._behavior.last_kwargs = kwargs
            resultado = self._behavior.next_result
            if isinstance(resultado, Exception):
                raise resultado
            return resultado

    class _FakeClient:
        def __init__(self, **kwargs):
            self.init_kwargs = kwargs
            self.messages = _FakeMessages(modulo._behavior)

    class _Behavior:
        next_result = None
        last_kwargs = None

    modulo._behavior = _Behavior()
    modulo.Anthropic = _FakeClient
    modulo.AnthropicError = AnthropicError
    modulo.AuthenticationError = AuthenticationError
    modulo.RateLimitError = RateLimitError
    modulo.APITimeoutError = APITimeoutError
    modulo.APIConnectionError = APIConnectionError
    modulo.APIStatusError = APIStatusError

    monkeypatch.setitem(sys.modules, "anthropic", modulo)
    return modulo


def _block(text: str):
    bloco = types.SimpleNamespace(type="text", text=text)
    return types.SimpleNamespace(content=[bloco])


def _make_client(monkeypatch, tmp_path, *, api_key="sk-teste", ai_mode="live",
                 demo_mode=False):
    monkeypatch.setenv("COPILOT_DB", str(tmp_path / "t.db"))
    if api_key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", api_key)
    else:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    if ai_mode:
        monkeypatch.setenv("AI_MODE", ai_mode)
    else:
        monkeypatch.delenv("AI_MODE", raising=False)
    monkeypatch.setenv("DEMO_MODE", "true" if demo_mode else "false")
    from src.config import reset_settings
    reset_settings()
    from src.agents.llm_client import LLMClient
    return LLMClient()


# --------------------------------------------------------------- ausencia de chave
def test_sem_chave_cai_em_demo_sem_chamar_rede(monkeypatch, tmp_path):
    cliente = _make_client(monkeypatch, tmp_path, api_key=None, ai_mode=None)
    assert cliente.mode == "DEMO"
    assert cliente.banner
    resultado = cliente.complete(system="s", user="u", demo_fallback={"text": "roteiro"})
    assert resultado.mode == "DEMO"
    assert resultado.text == "roteiro"


# ------------------------------------------------------------------- modo demonstracao
def test_ai_mode_demo_forca_roteiro_mesmo_com_chave(monkeypatch, tmp_path,
                                                     _fake_anthropic_module):
    cliente = _make_client(monkeypatch, tmp_path, api_key="sk-teste", ai_mode="demo")
    assert cliente.mode == "DEMO"
    resultado = cliente.complete(system="s", user="u", demo_fallback={"text": "roteiro"})
    assert resultado.mode == "DEMO"


# ------------------------------------------------------------------------- modo live
def test_ai_mode_live_chama_a_api_de_verdade(monkeypatch, tmp_path, _fake_anthropic_module):
    cliente = _make_client(monkeypatch, tmp_path, ai_mode="live")
    assert cliente.mode == "REAL"
    _fake_anthropic_module._behavior.next_result = _block("resposta real")
    resultado = cliente.complete(system="s", user="u", demo_fallback={"text": "roteiro"})
    assert resultado.mode == "REAL"
    assert resultado.text == "resposta real"
    assert resultado.model
    assert cliente.calls == 1


def test_uma_unica_chamada_por_invocacao_de_complete(monkeypatch, tmp_path,
                                                      _fake_anthropic_module):
    cliente = _make_client(monkeypatch, tmp_path, ai_mode="live")
    _fake_anthropic_module._behavior.next_result = _block("ok")
    cliente.complete(system="s", user="u", demo_fallback={"text": "x"})
    cliente.complete(system="s", user="u", demo_fallback={"text": "x"})
    assert cliente.calls == 2


def test_temperatura_e_timeout_sao_repassados(monkeypatch, tmp_path, _fake_anthropic_module):
    monkeypatch.setenv("AI_TEMPERATURE", "0.5")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "12")
    cliente = _make_client(monkeypatch, tmp_path, ai_mode="live")
    assert cliente._client.init_kwargs["timeout"] == 12.0
    _fake_anthropic_module._behavior.next_result = _block("ok")
    cliente.complete(system="s", user="u", demo_fallback={"text": "x"})
    assert _fake_anthropic_module._behavior.last_kwargs["temperature"] == 0.5


# ---------------------------------------------------------------------- erros da API
def test_timeout_nao_derruba_a_aplicacao(monkeypatch, tmp_path, _fake_anthropic_module):
    cliente = _make_client(monkeypatch, tmp_path, ai_mode="live")
    _fake_anthropic_module._behavior.next_result = _fake_anthropic_module.APITimeoutError("timeout")
    resultado = cliente.complete(system="s", user="u", demo_fallback={"text": "roteiro"})
    assert resultado.mode == "DEMO"
    assert resultado.error_type == "TIMEOUT"
    assert resultado.error


def test_erro_de_autenticacao_e_classificado(monkeypatch, tmp_path, _fake_anthropic_module):
    cliente = _make_client(monkeypatch, tmp_path, ai_mode="live")
    _fake_anthropic_module._behavior.next_result = _fake_anthropic_module.AuthenticationError("bad key")
    resultado = cliente.complete(system="s", user="u", demo_fallback={"text": "roteiro"})
    assert resultado.error_type == "AUTENTICACAO"


def test_rate_limit_e_classificado(monkeypatch, tmp_path, _fake_anthropic_module):
    cliente = _make_client(monkeypatch, tmp_path, ai_mode="live")
    _fake_anthropic_module._behavior.next_result = _fake_anthropic_module.RateLimitError("slow down")
    resultado = cliente.complete(system="s", user="u", demo_fallback={"text": "roteiro"})
    assert resultado.error_type == "RATE_LIMIT"


def test_indisponibilidade_e_classificada(monkeypatch, tmp_path, _fake_anthropic_module):
    cliente = _make_client(monkeypatch, tmp_path, ai_mode="live")
    _fake_anthropic_module._behavior.next_result = _fake_anthropic_module.APIConnectionError("down")
    resultado = cliente.complete(system="s", user="u", demo_fallback={"text": "roteiro"})
    assert resultado.error_type == "INDISPONIVEL"


# --------------------------------------------------------------------------- auditoria
def test_chamada_registra_auditoria_com_fontes_e_erro(monkeypatch, tmp_path,
                                                       _fake_anthropic_module):
    from src.database.connection import init_db
    from src.database import repositories as R

    cliente = _make_client(monkeypatch, tmp_path, ai_mode="live")
    conn = init_db()
    try:
        _fake_anthropic_module._behavior.next_result = _block("resposta")
        cliente.complete(system="s", user="u", demo_fallback={"text": "x"}, conn=conn,
                         agent="TESTE")
        trilha = R.audit_trail(conn, limit=5)
        assert trilha[0]["action"] == "LLM_CALL"
        assert trilha[0]["model"]
    finally:
        conn.close()
