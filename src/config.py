"""Configuracao do MVP. Stdlib pura — le `.env` sem dependencia externa.

Sem `ANTHROPIC_API_KEY` a aplicacao **inicia normalmente** em modo demonstracao.
Resposta demonstrativa nunca e apresentada como IA real: `LLMResult.mode` carrega
`DEMO` ate a UI e ate o audit log.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

#: Corte oficial do case. A tese oficial nao pode usar dado posterior.
DATA_CUT_OFF = date(2026, 8, 14)
VAR_LIMIT_BRL = Decimal("50000000.00")


def load_dotenv(path: Path = ENV_PATH) -> None:
    """Le `.env` para o ambiente. Variavel ja exportada tem precedencia."""
    if not path.exists():
        return
    for linha in path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave, valor = chave.strip(), valor.strip().strip('"').strip("'")
        os.environ.setdefault(chave, valor)


def _bool(name: str, default: bool) -> bool:
    valor = os.environ.get(name)
    if valor is None:
        return default
    return valor.strip().lower() in {"1", "true", "sim", "yes", "y"}


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    anthropic_model: str
    llm_effort: str
    llm_max_output_tokens: int
    demo_mode: bool
    data_cut_off: date
    var_limit_brl: Decimal
    db_path: Path
    ai_mode: str | None = None            # AI_MODE: "live" | "demo" (sobrescreve DEMO_MODE)
    ai_temperature: float = 0.2
    ai_timeout_seconds: float = 60.0
    ai_auto_review_on_alert: bool = False

    @property
    def llm_available(self) -> bool:
        """Modo real exige chave E o SDK instalado."""
        if not self.anthropic_api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def mode(self) -> str:
        """AI_MODE, quando definido, tem precedencia sobre DEMO_MODE."""
        if self.ai_mode == "live":
            return "REAL" if self.llm_available else "DEMO"
        if self.ai_mode == "demo":
            return "DEMO"
        return "REAL" if (self.llm_available and not self.demo_mode) else "DEMO"

    @property
    def demo_banner(self) -> str | None:
        if self.mode == "REAL":
            return None
        if not self.anthropic_api_key:
            return ("MODO DEMONSTRACAO — ANTHROPIC_API_KEY nao configurada. "
                    "Os textos dos agentes sao roteiros deterministicos, nao saida de IA. "
                    "Todos os numeros continuam vindo do banco e do motor quantitativo.")
        if self.ai_mode == "live" and not self.llm_available:
            return ("MODO DEMONSTRACAO — AI_MODE=live foi pedido, mas o SDK `anthropic` nao "
                    "esta disponivel no ambiente. Instale a dependencia para ativar a IA real.")
        return ("MODO DEMONSTRACAO ativado por configuracao (DEMO_MODE=true / AI_MODE=demo). "
                "Os textos dos agentes nao sao saida de IA.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    corte = os.environ.get("DATA_CUT_OFF", "").strip()
    ai_mode = os.environ.get("AI_MODE", "").strip().lower() or None
    if ai_mode not in (None, "live", "demo"):
        ai_mode = None
    max_tokens = os.environ.get("AI_MAX_TOKENS") or os.environ.get("LLM_MAX_OUTPUT_TOKENS", "4000")
    return Settings(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
        llm_effort=os.environ.get("LLM_EFFORT", "medium"),
        llm_max_output_tokens=int(max_tokens),
        demo_mode=_bool("DEMO_MODE", True),
        data_cut_off=date.fromisoformat(corte) if corte else DATA_CUT_OFF,
        var_limit_brl=Decimal(os.environ.get("VAR_LIMIT_BRL", str(VAR_LIMIT_BRL))),
        db_path=Path(os.environ.get("COPILOT_DB", str(PROJECT_ROOT / "data" / "copilot.db"))),
        ai_mode=ai_mode,
        ai_temperature=float(os.environ.get("AI_TEMPERATURE", "0.2")),
        ai_timeout_seconds=float(os.environ.get("AI_TIMEOUT_SECONDS", "60")),
        ai_auto_review_on_alert=_bool("AI_AUTO_REVIEW_ON_ALERT", False),
    )


def reset_settings() -> None:
    get_settings.cache_clear()


__all__ = [
    "DATA_CUT_OFF", "ENV_PATH", "PROJECT_ROOT", "Settings", "VAR_LIMIT_BRL",
    "get_settings", "load_dotenv", "reset_settings",
]
