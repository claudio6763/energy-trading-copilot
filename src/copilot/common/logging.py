"""Logging estruturado (RNF-10).

Uma linha JSON por evento, com `run_id`, `as_of` e `dataset_kind` extraidos do
contexto ativo. Stdlib apenas — sem dependencia nova.

Uso::

    from copilot.common.logging import get_logger, setup_logging
    setup_logging()
    log = get_logger(__name__)
    log.info("tese_registrada", extra={"thesis_id": tid, "assumptions": 4})
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from copilot.common.context import current_context

#: Atributos padrao de LogRecord, descartados na serializacao.
_RESERVED = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
        "pathname", "process", "processName", "relativeCreated", "stack_info",
        "thread", "threadName", "taskName",
    }
)

_configured = False


def _json_default(value: Any) -> str:
    return str(value)


class JsonFormatter(logging.Formatter):
    """Formata o registro como uma unica linha JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        ctx = current_context()
        if ctx is not None:
            payload["as_of"] = ctx.as_of.isoformat()
            payload["dataset_kind"] = ctx.dataset_kind.value
            payload["actor"] = ctx.actor
            if ctx.run_id:
                payload["run_id"] = ctx.run_id

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=_json_default)


class TextFormatter(logging.Formatter):
    """Formato legivel para desenvolvimento local."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = current_context()
        prefix = ""
        if ctx is not None:
            prefix = f"[{ctx.dataset_kind.value} as_of={ctx.as_of.isoformat()}] "
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_")
        }
        tail = " " + json.dumps(extras, ensure_ascii=False, default=_json_default) if extras else ""
        base = f"{record.levelname:<7} {prefix}{record.name}: {record.getMessage()}{tail}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(level: str | None = None, fmt: str | None = None, *, force: bool = False) -> None:
    """Configura o logging da aplicacao. Idempotente."""
    global _configured
    if _configured and not force:
        return

    from copilot.config.settings import get_settings

    settings = get_settings()
    level = (level or settings.log_level).upper()
    fmt = (fmt or settings.log_format).lower()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # SQLAlchemy e ruidoso em INFO; `DB_ECHO` controla o que interessa.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.db_echo else logging.WARNING
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


__all__ = ["JsonFormatter", "TextFormatter", "get_logger", "setup_logging"]
