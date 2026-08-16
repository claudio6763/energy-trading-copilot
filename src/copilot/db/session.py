"""Engine, sessao e unidade de trabalho.

Padrao local: SQLite em arquivo — persiste entre reinicializacoes (AC-06).
Producao: PostgreSQL/Supabase via `DATABASE_URL` (RNF-01, RNF-06).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from copilot.common.logging import get_logger
from copilot.config.settings import Settings, get_settings

log = get_logger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    """Sem `foreign_keys=ON` o SQLite ignora FK silenciosamente."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL melhora leitura concorrente (Streamlit abre varias sessoes).
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def build_engine(settings: Settings | None = None, *, url: str | None = None) -> Engine:
    """Cria um engine novo. Use `get_engine()` para o singleton da aplicacao."""
    settings = settings or get_settings()
    target_url = url or settings.database_url

    kwargs: dict[str, Any] = {"echo": settings.db_echo, "future": True}
    if target_url.startswith("sqlite"):
        settings.ensure_sqlite_dir()
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_pool_size
        kwargs["pool_pre_ping"] = True

    engine = create_engine(target_url, **kwargs)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def get_engine() -> Engine:
    """Engine singleton do processo."""
    global _engine
    if _engine is None:
        _engine = build_engine()
        log.info("engine_criado", extra={"backend": _engine.dialect.name})
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), expire_on_commit=False, autoflush=False, future=True
        )
    return _session_factory


def reset_engine() -> None:
    """Descarta engine e factory. Usado em testes e ao trocar de banco."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def session_scope(**kwargs: Any) -> Iterator[Session]:
    """Unidade de trabalho: commit no sucesso, rollback no erro, close sempre."""
    session = get_session_factory()(**kwargs)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def healthcheck() -> dict[str, Any]:
    """Diagnostico usado por `make doctor` e pela UI (Sprint 7)."""
    from sqlalchemy import inspect, text

    settings = get_settings()
    result: dict[str, Any] = {"backend": None, "reachable": False, "tables": 0, "error": None}
    try:
        engine = get_engine()
        result["backend"] = engine.dialect.name
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        result["reachable"] = True
        result["tables"] = len(inspect(engine).get_table_names())
    except Exception as exc:  # pragma: no cover - depende do ambiente
        result["error"] = str(exc)
    result["settings"] = settings.redacted()
    return result


__all__ = [
    "build_engine",
    "get_engine",
    "get_session_factory",
    "healthcheck",
    "reset_engine",
    "session_scope",
]
