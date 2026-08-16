"""Conexao e criacao do schema — SQLite local, Postgres em producao.

Decisao original (ADR-011): o nucleo do MVP usa `sqlite3` da stdlib em vez de
SQLAlchemy. Continua valendo para uso local. Mas o Streamlit Cloud nao tem
disco persistente (container efemero: reboot, redeploy ou o app dormindo e
acordando zeram o filesystem) — sqlite em arquivo local perde a tese entre uma
sessao e outra, e o case exige que o registro continue la na defesa.

`DATABASE_URL` (em `st.secrets` ou variavel de ambiente) decide o backend:
  - ausente ou `sqlite:///...`  -> sqlite3 da stdlib, como sempre foi.
  - `postgres://...` / `postgresql://...` -> psycopg, atras de um adaptador
    (`pg_shim.PgConnectionShim`) que faz a conexao Postgres se comportar como
    `sqlite3.Connection` o bastante para `repositories.py`/`thesis_service.py`/
    `risk_service.py`/`watchdog_service.py` funcionarem sem alteracao. Ver
    `pg_shim.py` e `DECISOES.md` para o raciocinio completo.

A URL nunca fica no repositorio: `st.secrets["DATABASE_URL"]` em producao,
`.env`/`DATABASE_URL` local para testar contra Postgres antes do deploy.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Iterator, Union

from src.database.pg_shim import PgConnectionShim, connect_postgres, ensure_theses_extra_columns

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_SQLITE_ONLY_PATH = Path(__file__).resolve().parent / "schema_sqlite_only.sql"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "copilot.db"

AnyConnection = Union[sqlite3.Connection, PgConnectionShim]


def get_database_url() -> str | None:
    """`DATABASE_URL` de `st.secrets` (se rodando sob Streamlit) ou do ambiente.

    Ausente -> sqlite local (comportamento de sempre). Nunca lanca excecao so
    por nao estar num contexto Streamlit — so nesse caso ela nao existe.
    """
    try:
        import streamlit as st

        if "DATABASE_URL" in st.secrets:
            return str(st.secrets["DATABASE_URL"])
    except Exception:
        pass
    return os.environ.get("DATABASE_URL") or None


def _is_postgres_url(url: str) -> bool:
    return url.startswith("postgres://") or url.startswith("postgresql://")


def db_path() -> Path:
    """Caminho do sqlite local. `COPILOT_DB` sobrescreve (usado nos testes)."""
    raw = os.environ.get("COPILOT_DB")
    return Path(raw) if raw else DEFAULT_DB_PATH


def _adapt_decimal(value: Decimal) -> str:
    """Decimal vai para o banco como TEXTO. Nunca via float (perda de centavo)."""
    return str(value)


sqlite3.register_adapter(Decimal, _adapt_decimal)


def _connect_sqlite(path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path else db_path()
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), isolation_level=None, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    # WAL melhora leitura concorrente, mas exige lock de arquivo real. Em pasta de
    # rede, montagem FUSE ou compartilhamento Windows ele falha com "disk I/O error".
    # Nesses casos o modo DELETE funciona e o produto continua de pe.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except sqlite3.Error:
        conn.execute("PRAGMA journal_mode=DELETE")
    return conn


def connect(path: str | Path | None = None) -> AnyConnection:
    """Abre a conexao do backend ativo. `path` so tem efeito no modo sqlite."""
    url = get_database_url()
    if url and _is_postgres_url(url):
        return connect_postgres(url)
    return _connect_sqlite(path)


def dialect_of(conn: AnyConnection) -> str:
    return "postgres" if isinstance(conn, PgConnectionShim) else "sqlite"


def init_db(conn: AnyConnection | None = None, *, path: str | Path | None = None) -> AnyConnection:
    """Cria o schema. Idempotente — pode rodar em banco ja existente, sem
    shell no ambiente publicado (DDL idempotente no boot)."""
    own = conn is None
    conn = conn or connect(path)
    dialeto = dialect_of(conn)

    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    if dialeto == "sqlite":
        conn.executescript(SCHEMA_SQLITE_ONLY_PATH.read_text(encoding="utf-8"))
    ensure_theses_extra_columns(conn, dialect=dialeto)

    _seed_risk_limit(conn)
    return conn


def _seed_risk_limit(conn: AnyConnection) -> None:
    """Limite de VaR de R$ 50 milhoes: cadastrado no banco, nao no codigo."""
    from src.database.repositories import now_iso, new_id

    existente = conn.execute(
        "SELECT id FROM risk_limits WHERE name = ?", ("VAR_MESA",)
    ).fetchone()
    if existente:
        return
    conn.execute(
        "INSERT INTO risk_limits (id, name, limit_value, unit, confidence, "
        "horizon_days, notes, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            new_id(),
            "VAR_MESA",
            "50000000.00",
            "R$",
            "0.95",
            21,
            "Limite do case. Premissa PR-03 enquanto a duvida D-01 nao e "
            "respondida: 95% de confianca, 21 dias uteis, portfolio consolidado.",
            now_iso(),
        ),
    )
    if hasattr(conn, "commit"):
        conn.commit()


@contextmanager
def session(path: str | Path | None = None) -> Iterator[AnyConnection]:
    """Unidade de trabalho: commit no sucesso, rollback no erro."""
    conn = connect(path)
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:  # pragma: no cover - conexao ja fechada
            pass
        raise
    finally:
        conn.close()


def table_names(conn: AnyConnection) -> list[str]:
    if dialect_of(conn) == "postgres":
        rows = conn.execute(
            "SELECT tablename AS name FROM pg_catalog.pg_tables WHERE schemaname = 'public' "
            "ORDER BY tablename"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    return [r["name"] for r in rows]


def healthcheck(path: str | Path | None = None) -> dict[str, object]:
    """Diagnostico usado por `verify_agent.py` e pelo Dashboard."""
    resultado: dict[str, object] = {
        "backend": "postgres" if (get_database_url() and _is_postgres_url(get_database_url())) else "sqlite",
        "path": str(path or db_path()),
        "ok": False,
        "tables": 0,
    }
    try:
        conn = connect(path)
        try:
            resultado["tables"] = len(table_names(conn))
            resultado["ok"] = resultado["tables"] > 0
            if dialect_of(conn) == "sqlite":
                resultado["fts5"] = bool(
                    conn.execute(
                        "SELECT name FROM sqlite_master WHERE name='chunk_fts'"
                    ).fetchone()
                )
            else:
                resultado["fts5"] = False
        finally:
            conn.close()
    except Exception as exc:  # pragma: no cover - depende do ambiente
        resultado["error"] = str(exc)
    return resultado


__all__ = [
    "AnyConnection",
    "DEFAULT_DB_PATH",
    "PROJECT_ROOT",
    "connect",
    "db_path",
    "dialect_of",
    "get_database_url",
    "healthcheck",
    "init_db",
    "session",
    "table_names",
]
