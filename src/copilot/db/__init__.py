"""Camada de persistencia: base declarativa, models, sessao e repositorios."""

from copilot.db.base import Base, metadata_obj
from copilot.db.session import (
    build_engine,
    get_engine,
    get_session_factory,
    healthcheck,
    reset_engine,
    session_scope,
)

__all__ = [
    "Base",
    "build_engine",
    "get_engine",
    "get_session_factory",
    "healthcheck",
    "metadata_obj",
    "reset_engine",
    "session_scope",
]
