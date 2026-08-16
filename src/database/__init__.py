"""Persistencia SQLite (stdlib) do MVP."""

from src.database.connection import (
    DEFAULT_DB_PATH,
    PROJECT_ROOT,
    connect,
    db_path,
    healthcheck,
    init_db,
    session,
    table_names,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "PROJECT_ROOT",
    "connect",
    "db_path",
    "healthcheck",
    "init_db",
    "session",
    "table_names",
]
