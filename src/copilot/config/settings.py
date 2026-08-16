"""Configuracao centralizada.

Fonte unica de verdade para banco, contexto padrao, limites de risco e logging.
Nada de segredo em codigo (RNF-07): tudo vem de variavel de ambiente ou de `.env`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from copilot.common.enums import DatasetKind

#: Raiz do repositorio (…/src/copilot/config/settings.py -> tres niveis acima de src).
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Configuracao da aplicacao, carregada de ambiente e `.env`."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Aplicacao ---------------------------------------------------------
    app_name: str = "energy-trading-copilot"
    app_env: Literal["local", "staging", "prod"] = "local"

    # -- Banco -------------------------------------------------------------
    #: Padrao: SQLite em arquivo — persiste entre reinicializacoes (AC-06).
    #: Producao: PostgreSQL/Supabase via DATABASE_URL.
    database_url: str = "sqlite+pysqlite:///./data/copilot.db"
    db_echo: bool = False
    db_pool_size: int = 5

    # -- Contexto padrao (P7, P9) -----------------------------------------
    #: Data-corte da analise do case.
    default_as_of: date = date(2026, 8, 14)
    default_dataset_kind: DatasetKind = DatasetKind.DEMO

    # -- Risco (P8) --------------------------------------------------------
    var_limit_brl: Decimal = Field(default=Decimal("50000000.00"))

    # -- Observabilidade (RNF-10) -----------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    # -- LLM (nao usado no Sprint 1; RNF-06) -------------------------------
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    # ---------------------------------------------------------------- valid
    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Normaliza URLs de provedores para o driver que instalamos.

        Supabase e Heroku publicam `postgres://` / `postgresql://`; o projeto usa
        psycopg 3, cujo dialeto e `postgresql+psycopg`.
        """
        value = value.strip()
        if not value:
            raise ValueError("DATABASE_URL nao pode ser vazio")
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        if value.startswith("sqlite://") and "+" not in value.split("://", 1)[0]:
            return "sqlite+pysqlite://" + value[len("sqlite://") :]
        return value

    @field_validator("var_limit_brl")
    @classmethod
    def _positive_limit(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("VAR_LIMIT_BRL deve ser positivo")
        return value

    # ---------------------------------------------------------------- props
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def has_llm(self) -> bool:
        """RNF-06: sem chave, Registrar e Vigiar continuam operando."""
        return bool(self.anthropic_api_key)

    @property
    def sqlite_path(self) -> Path | None:
        """Caminho absoluto do arquivo SQLite, se for o caso."""
        if not self.is_sqlite:
            return None
        _, _, tail = self.database_url.partition("://")
        # Convencao SQLAlchemy: 3 barras = caminho relativo, 4 = absoluto.
        if tail.startswith("/"):
            stripped = tail.lstrip("/")
            is_absolute = (len(tail) - len(stripped)) >= 2
            raw = ("/" + stripped) if is_absolute else stripped
        else:
            raw = tail
        if raw in {"", ":memory:"}:
            return None
        path = Path(raw)
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    def ensure_sqlite_dir(self) -> None:
        """Cria o diretorio do arquivo SQLite, se necessario."""
        path = self.sqlite_path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def redacted(self) -> dict[str, object]:
        """Visao segura para log e para `make doctor` — sem credencial."""
        url = self.database_url
        if "@" in url:
            scheme, _, rest = url.partition("://")
            url = f"{scheme}://***@{rest.rpartition('@')[2]}"
        return {
            "app_env": self.app_env,
            "database_url": url,
            "backend": "postgresql" if self.is_postgres else "sqlite",
            "default_as_of": self.default_as_of.isoformat(),
            "default_dataset_kind": self.default_dataset_kind.value,
            "var_limit_brl": str(self.var_limit_brl),
            "log_level": self.log_level,
            "log_format": self.log_format,
            "llm_configured": self.has_llm,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Configuracao em cache (uma leitura por processo)."""
    return Settings()


def reset_settings_cache() -> None:
    """Invalida o cache. Usado apenas em testes."""
    get_settings.cache_clear()


__all__ = ["PROJECT_ROOT", "Settings", "get_settings", "reset_settings_cache"]
