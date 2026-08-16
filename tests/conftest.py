"""Fixtures da suite.

Cada teste roda contra um SQLite proprio, criado **pelas migrations** — nunca por
`create_all`. Isso faz a suite validar o mesmo caminho que a producao usa
(CLAUDE.md secao 5 / DATA_CONTRACT secao 7).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from copilot.common.context import run_context
from copilot.common.enums import ActorType, DatasetKind
from copilot.config.settings import PROJECT_ROOT, get_settings, reset_settings_cache
from copilot.db.session import build_engine, reset_engine

AS_OF = date(2026, 8, 14)


def _alembic_config(url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.fixture()
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """URL de um SQLite isolado por teste, ja exportada em DATABASE_URL."""
    db_file = tmp_path / "copilot_test.db"
    url = f"sqlite+pysqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("LOG_FORMAT", "text")
    reset_settings_cache()
    reset_engine()
    yield url
    reset_engine()
    reset_settings_cache()


@pytest.fixture()
def migrated_engine(db_url: str) -> Iterator[Engine]:
    """Banco criado pelas migrations Alembic."""
    command.upgrade(_alembic_config(db_url), "head")
    engine = build_engine(get_settings(), url=db_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def session_factory(migrated_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=migrated_engine, expire_on_commit=False, autoflush=False)


@pytest.fixture()
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    db = session_factory()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture()
def demo_ctx() -> Iterator[None]:
    """Contexto DEMO na data-corte do case."""
    with run_context(
        as_of=AS_OF,
        dataset_kind=DatasetKind.DEMO,
        actor="pytest",
        actor_type=ActorType.SISTEMA,
    ):
        yield


@pytest.fixture()
def real_ctx() -> Iterator[None]:
    with run_context(
        as_of=AS_OF,
        dataset_kind=DatasetKind.REAL,
        actor="pytest",
        actor_type=ActorType.SISTEMA,
    ):
        yield


@pytest.fixture()
def alembic_config(db_url: str) -> Config:
    return _alembic_config(db_url)
