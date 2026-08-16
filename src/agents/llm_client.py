"""Cliente Anthropic unico, com modo demonstracao explicito.

Sem `ANTHROPIC_API_KEY` (ou sem o SDK instalado) a aplicacao **inicia
normalmente** e cai em `DEMO`. Resposta demonstrativa nunca e apresentada como
IA real: `LLMResult.mode` carrega `DEMO` ate a UI, ate o audit log e ate o
documento gerado.

O LLM so redige e interpreta. Nenhum numero sai daqui — os agentes recebem os
valores ja calculados e apenas os comentam. E o Claim Verifier confere depois.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from src.config import get_settings
from src.database import repositories as R

#: Teto de chamadas ao LLM por debate (Secao 2, regra 15).
MAX_LLM_CALLS_PER_DEBATE = 4


@dataclass
class LLMResult:
    text: str
    mode: str                      # REAL | DEMO
    model: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None  # AUTENTICACAO | TIMEOUT | RATE_LIMIT | INDISPONIVEL | ERRO

    @property
    def is_demo(self) -> bool:
        return self.mode == "DEMO"

    @property
    def label(self) -> str:
        return "IA (Claude)" if self.mode == "REAL" else "ROTEIRO DEMONSTRATIVO (não é IA)"


def _classify_error(exc: Exception) -> tuple[str, str]:
    """Traduz a excecao do SDK Anthropic em (tipo, mensagem) legivel em portugues."""
    try:
        import anthropic
    except ImportError:  # pragma: no cover - SDK ausente
        return "ERRO", str(exc)

    if isinstance(exc, anthropic.AuthenticationError):
        return "AUTENTICACAO", "Falha de autenticacao: verifique ANTHROPIC_API_KEY."
    if isinstance(exc, anthropic.RateLimitError):
        return "RATE_LIMIT", "Limite de requisicoes da API Anthropic atingido. Tente novamente em instantes."
    if isinstance(exc, anthropic.APITimeoutError):
        return "TIMEOUT", f"A chamada ao modelo excedeu o timeout configurado (AI_TIMEOUT_SECONDS)."
    if isinstance(exc, anthropic.APIConnectionError):
        return "INDISPONIVEL", "Nao foi possivel conectar a API da Anthropic (rede ou servico indisponivel)."
    if isinstance(exc, anthropic.APIStatusError):
        return "INDISPONIVEL", f"API da Anthropic retornou erro (status {exc.status_code})."
    return "ERRO", str(exc)


def _extract_json(texto: str) -> dict[str, Any]:
    """Extrai o primeiro objeto JSON da resposta. Falha vira dict vazio."""
    bloco = re.search(r"\{.*\}", texto or "", re.DOTALL)
    if not bloco:
        return {}
    try:
        return json.loads(bloco.group(0))
    except json.JSONDecodeError:
        return {}


class LLMClient:
    """Cliente compartilhado. Instancie uma vez por processo."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self.calls = 0
        self._init_error: str | None = None
        if self.settings.mode == "REAL":
            try:
                import anthropic

                self._client = anthropic.Anthropic(
                    api_key=self.settings.anthropic_api_key,
                    timeout=self.settings.ai_timeout_seconds,
                )
            except Exception as exc:  # pragma: no cover - depende do ambiente
                self._client = None
                self._init_error = str(exc)

    @property
    def mode(self) -> str:
        return "REAL" if self._client is not None else "DEMO"

    @property
    def banner(self) -> str | None:
        if self.mode == "REAL":
            return None
        return self.settings.demo_banner

    def complete(
        self,
        *,
        system: str,
        user: str,
        demo_fallback: dict[str, Any],
        conn: sqlite3.Connection | None = None,
        agent: str = "agente",
        max_tokens: int | None = None,
    ) -> LLMResult:
        """Uma chamada. Em DEMO devolve o roteiro estruturado, sem inventar numero."""
        if self._client is None:
            resultado = LLMResult(
                text=demo_fallback.get("text", ""), mode="DEMO", payload=demo_fallback
            )
        else:
            self.calls += 1
            try:
                resposta = self._client.messages.create(
                    model=self.settings.anthropic_model,
                    max_tokens=max_tokens or self.settings.llm_max_output_tokens,
                    temperature=self.settings.ai_temperature,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                texto = "".join(
                    bloco.text for bloco in resposta.content if getattr(bloco, "type", "") == "text"
                )
                resultado = LLMResult(
                    text=texto, mode="REAL", model=self.settings.anthropic_model,
                    payload=_extract_json(texto),
                )
            except Exception as exc:  # rede, cota, autenticacao, modelo indisponivel
                tipo, mensagem = _classify_error(exc)
                resultado = LLMResult(
                    text=demo_fallback.get("text", ""), mode="DEMO",
                    payload=demo_fallback, error=mensagem, error_type=tipo,
                )

        if conn is not None:
            # Modo real registra prompt, ferramentas e resultado (Secao 7).
            R.audit(
                conn, action="LLM_CALL", entity="agente", entity_id=agent, agent=agent,
                actor_type="AGENTE", tool="anthropic.messages" if resultado.mode == "REAL" else "demo",
                model=resultado.model,
                input_data={"system": system[:2000], "user": user[:4000]},
                output_data={"mode": resultado.mode, "text": resultado.text[:4000],
                             "error": resultado.error, "error_type": resultado.error_type},
            )
        return resultado


_shared: LLMClient | None = None


def get_client() -> LLMClient:
    """Cliente compartilhado do processo."""
    global _shared
    if _shared is None:
        _shared = LLMClient()
    return _shared


def reset_client() -> None:
    global _shared
    _shared = None


__all__ = ["LLMClient", "LLMResult", "MAX_LLM_CALLS_PER_DEBATE", "get_client", "reset_client"]
