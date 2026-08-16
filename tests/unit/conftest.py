"""Testes unitarios rodam com o ambiente limpo.

Sem isso, um `.env` ou uma variavel exportada na maquina do desenvolvedor mudaria
o resultado — e o teste deixaria de significar alguma coisa.
"""

from __future__ import annotations

import pytest

from copilot.config.settings import reset_settings_cache

_ENV_VARS = (
    "DATABASE_URL",
    "DB_ECHO",
    "DB_POOL_SIZE",
    "APP_ENV",
    "DEFAULT_AS_OF",
    "DEFAULT_DATASET_KIND",
    "VAR_LIMIT_BRL",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
)


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in _ENV_VARS:
        monkeypatch.delenv(nome, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()
