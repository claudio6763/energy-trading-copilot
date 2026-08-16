"""Tipos de coluna e enums de dominio.

O ponto sensivel e o Decimal: CLAUDE.md proibe `float` para dinheiro, e o SQLite
nao tem decimal nativo. `DecimalText` e a peca que sustenta essa regra.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from copilot.common.enums import (
    BLOCKED_LICENSE_CLASSES,
    THESIS_TRANSITIONS,
    AlertKind,
    ClaimStatus,
    DatasetKind,
    LicenseClass,
    ThesisStatus,
    Unit,
)
from copilot.db.types import DecimalText, EnumText, Money, UTCDateTime, enum_check

SQLITE = sqlite.dialect()
POSTGRES = postgresql.dialect()


# ------------------------------------------------------------------- decimais
def test_dinheiro_faz_round_trip_exato_no_sqlite() -> None:
    tipo = Money()
    valor = Decimal("49999999.99")
    gravado = tipo.process_bind_param(valor, SQLITE)
    assert isinstance(gravado, str)
    assert tipo.process_result_value(gravado, SQLITE) == valor


def test_dinheiro_usa_numeric_nativo_no_postgres() -> None:
    tipo = Money()
    gravado = tipo.process_bind_param(Decimal("1234.56"), POSTGRES)
    assert isinstance(gravado, Decimal)


def test_float_em_coluna_monetaria_e_erro_explicito() -> None:
    """CLAUDE.md secao 5: nunca float para dinheiro."""
    with pytest.raises(TypeError, match="float"):
        Money().process_bind_param(0.1 + 0.2, SQLITE)


def test_precisao_preservada_onde_o_float_falharia() -> None:
    tipo = Money()
    total = Decimal("0")
    for _ in range(10):
        total += Decimal("0.1")
    gravado = tipo.process_bind_param(total, SQLITE)
    assert tipo.process_result_value(gravado, SQLITE) == Decimal("1.00")


def test_escala_e_aplicada_com_half_up() -> None:
    tipo = DecimalText(18, 2)
    assert tipo.process_bind_param(Decimal("1.005"), SQLITE) == "1.01"
    assert tipo.process_bind_param(Decimal("-1.005"), SQLITE) == "-1.01"


def test_valores_grandes_e_negativos() -> None:
    tipo = DecimalText(28, 8)
    for valor in (Decimal("-50000000.00000001"), Decimal("999999999999.12345678")):
        gravado = tipo.process_bind_param(valor, SQLITE)
        assert tipo.process_result_value(gravado, SQLITE) == valor


def test_none_atravessa() -> None:
    assert Money().process_bind_param(None, SQLITE) is None
    assert Money().process_result_value(None, SQLITE) is None


# ----------------------------------------------------------------- timestamps
def test_datetime_naive_vira_utc_aware() -> None:
    tipo = UTCDateTime()
    resultado = tipo.process_bind_param(datetime(2026, 8, 14, 12, 0), SQLITE)
    assert resultado.tzinfo is timezone.utc


def test_datetime_com_fuso_e_convertido_para_utc() -> None:
    from datetime import timedelta

    brasilia = timezone(timedelta(hours=-3))
    resultado = UTCDateTime().process_bind_param(
        datetime(2026, 8, 14, 9, 0, tzinfo=brasilia), SQLITE
    )
    assert resultado == datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def test_leitura_de_naive_assume_utc() -> None:
    resultado = UTCDateTime().process_result_value(datetime(2026, 8, 14, 12, 0), SQLITE)
    assert resultado.tzinfo is timezone.utc


# ---------------------------------------------------------------------- enums
def test_enum_text_valida_na_escrita() -> None:
    tipo = EnumText(DatasetKind)
    assert tipo.process_bind_param(DatasetKind.DEMO, SQLITE) == "DEMO"
    assert tipo.process_bind_param("REAL", SQLITE) == "REAL"
    with pytest.raises(ValueError, match="invalido"):
        tipo.process_bind_param("PRODUCAO", SQLITE)


def test_enum_text_devolve_membro() -> None:
    assert EnumText(DatasetKind).process_result_value("DEMO", SQLITE) is DatasetKind.DEMO


def test_check_constraint_lista_todos_os_valores() -> None:
    """C8: enum vira texto com CHECK, nao enum nativo."""
    sql = str(enum_check("dataset_kind", DatasetKind).sqltext)
    assert "'DEMO'" in sql and "'REAL'" in sql


def test_valores_acentuados_sobrevivem() -> None:
    assert ThesisStatus.EM_REVISAO.value == "EM_REVISÃO"
    assert AlertKind.MUDANCA_REGULATORIA.value == "MUDANÇA_REGULATÓRIA"
    assert Unit.M3_S.value == "m³/s"


def test_maquina_de_estados_da_tese() -> None:
    """RF-10: estados terminais nao tem saida."""
    assert ThesisStatus.APROVADA in THESIS_TRANSITIONS[ThesisStatus.EM_DEBATE]
    assert THESIS_TRANSITIONS[ThesisStatus.ENCERRADA] == frozenset()
    assert THESIS_TRANSITIONS[ThesisStatus.INVALIDADA] == frozenset()
    for estado in ThesisStatus:
        assert estado in THESIS_TRANSITIONS


def test_classes_de_licenca_bloqueadas() -> None:
    """P10: bloqueio na entrada."""
    assert LicenseClass.LICENSED_BLOCKED in BLOCKED_LICENSE_CLASSES
    assert LicenseClass.CONFIDENTIAL_EXTERNAL in BLOCKED_LICENSE_CLASSES
    assert LicenseClass.PUBLIC_OPEN not in BLOCKED_LICENSE_CLASSES


def test_status_de_claim_que_bloqueiam_aprovacao() -> None:
    from copilot.common.enums import BLOCKING_CLAIM_STATUSES

    assert BLOCKING_CLAIM_STATUSES == frozenset(
        {ClaimStatus.CONTRADICTED, ClaimStatus.BLOCKED}
    )
