"""Configuracao centralizada, logging estruturado e contexto de execucao."""

from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal

import pytest

from copilot.common.context import current_context, require_context, run_context
from copilot.common.enums import ActorType, DatasetKind
from copilot.common.errors import MissingContextError
from copilot.common.logging import JsonFormatter
from copilot.config.settings import Settings, get_settings, reset_settings_cache


# ------------------------------------------------------------------- settings
def test_padroes_do_case() -> None:
    settings = Settings(_env_file=None)
    assert settings.default_as_of == date(2026, 8, 14)  # data-corte do case
    assert settings.var_limit_brl == Decimal("50000000.00")  # P8
    assert settings.default_dataset_kind is DatasetKind.DEMO
    assert settings.is_sqlite


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgresql://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("sqlite:///./data/x.db", "sqlite+pysqlite:///./data/x.db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ],
)
def test_normalizacao_de_url(entrada: str, esperado: str) -> None:
    assert Settings(_env_file=None, database_url=entrada).database_url == esperado


def test_url_vazia_e_rejeitada() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, database_url="  ")


def test_limite_de_var_precisa_ser_positivo() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, var_limit_brl=Decimal("0"))


def test_redacted_nao_vaza_credencial() -> None:
    settings = Settings(
        _env_file=None, database_url="postgresql://user:supersecreta@host:5432/db"
    )
    exposto = json.dumps(settings.redacted())
    assert "supersecreta" not in exposto
    assert settings.redacted()["backend"] == "postgresql"


def test_sem_chave_de_llm_o_sistema_reconhece_o_modo_degradado() -> None:
    """RNF-06 / AC-71: sem chave, Registrar e Vigiar seguem operando."""
    assert Settings(_env_file=None).has_llm is False
    assert Settings(_env_file=None, anthropic_api_key="sk-teste").has_llm is True


def test_settings_em_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings_cache()
    assert get_settings() is get_settings()
    reset_settings_cache()


# -------------------------------------------------------------------- context
def test_contexto_obrigatorio() -> None:
    assert current_context() is None
    with pytest.raises(MissingContextError):
        require_context()


def test_contexto_aninhado_herda_e_restaura() -> None:
    with run_context(as_of=date(2026, 8, 14), dataset_kind=DatasetKind.REAL, actor="ana"):
        externo = require_context()
        assert externo.dataset_kind is DatasetKind.REAL
        with run_context(as_of=date(2026, 8, 10)):
            interno = require_context()
            assert interno.as_of == date(2026, 8, 10)
            assert interno.dataset_kind is DatasetKind.REAL  # herdado
            assert interno.actor == "ana"
        assert require_context().as_of == date(2026, 8, 14)
    assert current_context() is None


def test_dataset_kind_aceita_string() -> None:
    with run_context(as_of=date(2026, 8, 14), dataset_kind="DEMO"):
        assert require_context().dataset_kind is DatasetKind.DEMO


# -------------------------------------------------------------------- logging
def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("copilot.teste", logging.INFO, __file__, 10, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emite_uma_linha_valida() -> None:
    saida = JsonFormatter().format(_record("tese_registrada", thesis_id="ABC"))
    assert "\n" not in saida
    payload = json.loads(saida)
    assert payload["event"] == "tese_registrada"
    assert payload["level"] == "INFO"
    assert payload["thesis_id"] == "ABC"


def test_json_formatter_carrega_o_contexto() -> None:
    """RNF-10: as_of e dataset_kind aparecem em todo evento."""
    with run_context(
        as_of=date(2026, 8, 14),
        dataset_kind=DatasetKind.DEMO,
        actor="pytest",
        actor_type=ActorType.SISTEMA,
        run_id="01J000000000000000000000AA",
    ):
        payload = json.loads(JsonFormatter().format(_record("evento")))
    assert payload["as_of"] == "2026-08-14"
    assert payload["dataset_kind"] == "DEMO"
    assert payload["actor"] == "pytest"
    assert payload["run_id"] == "01J000000000000000000000AA"


def test_json_formatter_serializa_tipos_nao_json() -> None:
    payload = json.loads(JsonFormatter().format(_record("evento", valor=Decimal("1.5"))))
    assert payload["valor"] == "1.5"
