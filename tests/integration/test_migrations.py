"""Migrations: ida, volta e ausencia de divergencia com os models.

O teste de divergencia existe porque a migration inicial e escrita a mao. Sem
ele, models e schema poderiam separar-se em silencio ao longo das sprints.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from copilot.config.settings import get_settings
from copilot.db.base import Base
from copilot.db.models import TABLE_CREATE_ORDER
from copilot.db.session import build_engine


def test_upgrade_cria_todas_as_tabelas(migrated_engine, db_url: str) -> None:
    encontradas = set(inspect(migrated_engine).get_table_names())
    esperadas = set(TABLE_CREATE_ORDER)
    assert esperadas <= encontradas, f"faltando: {esperadas - encontradas}"
    assert "alembic_version" in encontradas


def test_migration_matches_models(migrated_engine) -> None:
    """Nenhuma coluna dos models fora do schema migrado, e vice-versa."""
    inspector = inspect(migrated_engine)
    divergencias: list[str] = []

    for nome, tabela in Base.metadata.tables.items():
        colunas_banco = {c["name"] for c in inspector.get_columns(nome)}
        colunas_model = {c.name for c in tabela.columns}
        if faltando := colunas_model - colunas_banco:
            divergencias.append(f"{nome}: no model mas nao no banco -> {sorted(faltando)}")
        if sobrando := colunas_banco - colunas_model:
            divergencias.append(f"{nome}: no banco mas nao no model -> {sorted(sobrando)}")

    assert not divergencias, "\n".join(divergencias)


def test_nulabilidade_bate_com_os_models(migrated_engine) -> None:
    """`assumption.evidence_id` NOT NULL e o coracao do AC-02."""
    inspector = inspect(migrated_engine)
    for nome, tabela in Base.metadata.tables.items():
        banco = {c["name"]: c["nullable"] for c in inspector.get_columns(nome)}
        for coluna in tabela.columns:
            if coluna.primary_key:
                continue
            assert banco[coluna.name] == coluna.nullable, (
                f"{nome}.{coluna.name}: nullable divergente "
                f"(model={coluna.nullable}, banco={banco[coluna.name]})"
            )


def test_colunas_de_evidencia_obrigatoria(migrated_engine) -> None:
    """C3: onde o dado e factual, o lastro e NOT NULL."""
    inspector = inspect(migrated_engine)
    obrigatorias = {
        "assumption": "evidence_id",
        "position": "evidence_id",
        "market_observation": "evidence_id",
        "forward_curve_point": "evidence_id",
        "alert": "evidence_id",
    }
    for tabela, coluna in obrigatorias.items():
        info = {c["name"]: c for c in inspector.get_columns(tabela)}
        assert info[coluna]["nullable"] is False, f"{tabela}.{coluna} deveria ser NOT NULL"


def test_chaves_estrangeiras_existem(migrated_engine) -> None:
    inspector = inspect(migrated_engine)
    fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("assumption")}
    assert {"thesis", "evidence"} <= fks


def test_downgrade_limpa_tudo(alembic_config: Config, db_url: str, migrated_engine) -> None:
    migrated_engine.dispose()
    command.downgrade(alembic_config, "base")

    engine = build_engine(get_settings(), url=db_url)
    try:
        restantes = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert restantes == set()
    finally:
        engine.dispose()


def test_ciclo_upgrade_downgrade_upgrade(
    alembic_config: Config, db_url: str, migrated_engine
) -> None:
    migrated_engine.dispose()
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    engine = build_engine(get_settings(), url=db_url)
    try:
        assert set(TABLE_CREATE_ORDER) <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_foreign_keys_ativas_no_sqlite(migrated_engine) -> None:
    """Sem o PRAGMA, o SQLite ignora FK em silencio."""
    from sqlalchemy import text

    with migrated_engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
