"""Tipos de coluna compartilhados por PostgreSQL e SQLite.

Tres problemas resolvidos aqui:

1. **Decimal.** CLAUDE.md secao 5: "Nunca `float` para dinheiro". O SQLite nao
   tem tipo decimal nativo e o SQLAlchemy converteria via ponto flutuante. Por
   isso `DecimalText` grava a representacao textual do Decimal no SQLite e usa
   NUMERIC nativo no PostgreSQL. O valor volta sempre como `Decimal`, com a
   escala declarada.
   *Limitacao conhecida:* ordenacao e agregacao numerica no SQLite exigem
   `CAST(col AS REAL)` ou processamento em Python. Em PostgreSQL e nativo.

2. **Timestamps.** `UTCDateTime` garante datetime tz-aware em UTC na ida e na
   volta, inclusive no SQLite (que armazena naive).

3. **Enums (C8).** `EnumText` grava o `.value` como texto e valida na escrita.
   A CHECK constraint correspondente e declarada em `__table_args__`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Numeric, String, TypeDecorator
from sqlalchemy.engine import Dialect

from copilot.common.enums import DomainEnum


class DecimalText(TypeDecorator):
    """Decimal exato em qualquer dialeto. NUMERIC no PostgreSQL, TEXT no SQLite."""

    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int, scale: int, **kwargs: Any) -> None:
        self.precision = precision
        self.scale = scale
        self._quantum = Decimal(1).scaleb(-scale)
        super().__init__(precision=precision, scale=scale, asdecimal=True, **kwargs)

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(64))
        return dialect.type_descriptor(Numeric(self.precision, self.scale, asdecimal=True))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if isinstance(value, float):
            # Explicito e proposital: float nao entra em coluna monetaria.
            raise TypeError(
                "float nao e aceito em coluna Decimal. Use Decimal ou str "
                "(CLAUDE.md secao 5)."
            )
        try:
            dec = Decimal(str(value)).quantize(self._quantum, rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError) as exc:  # pragma: no cover - defensivo
            raise ValueError(f"valor decimal invalido: {value!r}") from exc
        return str(dec) if dialect.name == "sqlite" else dec

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value)).quantize(self._quantum, rounding=ROUND_HALF_UP)


def Money() -> DecimalText:
    """Dinheiro em reais — Numeric(18,2)."""
    return DecimalText(18, 2)


def Energy() -> DecimalText:
    """Energia em MWh — Numeric(18,3)."""
    return DecimalText(18, 3)


def Price() -> DecimalText:
    """Preco em R$/MWh — Numeric(12,2)."""
    return DecimalText(12, 2)


def Percent() -> DecimalText:
    """Percentual em fracao — Numeric(9,6)."""
    return DecimalText(9, 6)


def Observation() -> DecimalText:
    """Valor generico de observacao de mercado — Numeric(28,8)."""
    return DecimalText(28, 8)


class UTCDateTime(TypeDecorator):
    """Datetime sempre tz-aware em UTC, nos dois dialetos."""

    impl = DateTime
    cache_ok = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(timezone=True, **kwargs)

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"esperado datetime, recebido {type(value).__name__}")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class EnumText(TypeDecorator):
    """Enum de dominio persistido como texto, validado na escrita (C8)."""

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[DomainEnum], length: int = 64, **kwargs: Any) -> None:
        self.enum_cls = enum_cls
        self._allowed = frozenset(member.value for member in enum_cls)
        super().__init__(length=length, **kwargs)

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value
        text = str(value)
        if text not in self._allowed:
            raise ValueError(
                f"valor invalido para {self.enum_cls.__name__}: {text!r}. "
                f"Aceitos: {sorted(self._allowed)}"
            )
        return text

    def process_result_value(self, value: Any, dialect: Dialect) -> DomainEnum | None:
        if value is None:
            return None
        return self.enum_cls(value)


def enum_check(column: str, enum_cls: type[DomainEnum]) -> CheckConstraint:
    """CHECK constraint com os valores aceitos do enum (C8).

    O nome curto e completado pela naming convention: ``ck_<tabela>_<nome>``.
    """
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=f"{column}_enum")


def utcnow() -> datetime:
    """Agora, em UTC e tz-aware."""
    return datetime.now(timezone.utc)


__all__ = [
    "DecimalText",
    "Energy",
    "EnumText",
    "Money",
    "Observation",
    "Percent",
    "Price",
    "UTCDateTime",
    "enum_check",
    "utcnow",
]
