"""ULID: formato, ordenacao temporal e unicidade."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from copilot.common.ids import ULID_LENGTH, is_ulid, new_ulid, short, ulid_timestamp


def test_formato_e_tamanho() -> None:
    value = new_ulid()
    assert len(value) == ULID_LENGTH == 26
    assert is_ulid(value)


def test_alfabeto_crockford_sem_letras_ambiguas() -> None:
    for _ in range(200):
        value = new_ulid()
        assert not set(value) & set("ILOU")


def test_unicidade() -> None:
    values = {new_ulid() for _ in range(5000)}
    assert len(values) == 5000


def test_ordenacao_lexicografica_segue_o_tempo() -> None:
    base = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    earlier = new_ulid(base)
    later = new_ulid(base + timedelta(seconds=1))
    assert earlier < later


def test_timestamp_embutido_e_recuperavel() -> None:
    moment = datetime(2026, 8, 14, 10, 30, 0, tzinfo=timezone.utc)
    recovered = ulid_timestamp(new_ulid(moment))
    assert abs((recovered - moment).total_seconds()) < 0.01


def test_valores_invalidos() -> None:
    assert not is_ulid(None)
    assert not is_ulid("")
    assert not is_ulid("curto")
    assert not is_ulid("I" * 26)  # letra fora do alfabeto


def test_short_para_exibicao() -> None:
    value = new_ulid()
    assert short(value) == value[-8:]
