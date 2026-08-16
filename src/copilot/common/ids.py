"""ULID — identificador ordenavel por tempo, em string de 26 caracteres.

CLAUDE.md secao 5 exige ULID para `evidence_id`, `thesis_id` e `run_id`.
Implementado aqui em stdlib para nao introduzir dependencia nova (evita ADR
desnecessario e mantem o Sprint 1 com quatro dependencias).

Formato: 48 bits de timestamp em milissegundos + 80 bits aleatorios,
codificados em Crockford Base32 (26 caracteres, lexicograficamente ordenavel).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

#: Crockford Base32 — sem I, L, O, U (evita confusao visual).
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {ch: idx for idx, ch in enumerate(_ALPHABET)}

ULID_LENGTH = 26
_TIME_CHARS = 10
_RANDOM_BYTES = 10


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def new_ulid(when: datetime | None = None) -> str:
    """Gera um ULID novo.

    :param when: instante a codificar. Padrao: agora, em UTC.
    """
    if when is None:
        millis = int(time.time() * 1000)
    else:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        millis = int(when.astimezone(timezone.utc).timestamp() * 1000)
    randomness = int.from_bytes(os.urandom(_RANDOM_BYTES), "big")
    return _encode(millis, _TIME_CHARS) + _encode(randomness, ULID_LENGTH - _TIME_CHARS)


def is_ulid(value: str | None) -> bool:
    """True se `value` for um ULID sintaticamente valido."""
    if not isinstance(value, str) or len(value) != ULID_LENGTH:
        return False
    return all(ch in _DECODE for ch in value)


def ulid_timestamp(value: str) -> datetime:
    """Extrai o instante embutido no ULID (UTC)."""
    if not is_ulid(value):
        raise ValueError(f"ULID invalido: {value!r}")
    millis = 0
    for ch in value[:_TIME_CHARS]:
        millis = millis * 32 + _DECODE[ch]
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


def short(value: str, size: int = 8) -> str:
    """Sufixo curto para exibicao em log e UI. Nunca usar como chave."""
    return value[-size:] if isinstance(value, str) else str(value)


__all__ = ["ULID_LENGTH", "is_ulid", "new_ulid", "short", "ulid_timestamp"]
