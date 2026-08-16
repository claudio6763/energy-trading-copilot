"""Horas do periodo e conversao MWmed <-> MWh.

Confundir MWmed com MWh e o erro mais caro e mais silencioso de uma mesa de
energia: erra o notional, o P&L e o VaR de uma vez so, e no mesmo fator.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from copilot.common.errors import InvalidPeriodError
from copilot.quant.periods import (
    HOURS_PER_DAY,
    DeliveryPeriod,
    business_days,
    month_period,
    mwh_to_mwmed,
    mwmed_to_mwh,
    period_hours,
    quarter_period,
    year_hours,
    year_period,
)


def test_ano_comum_tem_8760_horas() -> None:
    assert year_hours(2027) == 8760
    assert year_period(2027).hours == 8760


def test_ano_bissexto_tem_8784_horas() -> None:
    """2028 e bissexto: 24 horas a mais. Ignorar isso erra o notional em 0,27%."""
    assert year_hours(2028) == 8784
    assert year_period(2028).hours == 8784
    assert year_period(2028).days == 366


def test_periodo_e_inclusivo_nas_duas_pontas() -> None:
    assert period_hours(date(2027, 1, 1), date(2027, 1, 1)) == 24
    assert period_hours(date(2027, 1, 1), date(2027, 1, 2)) == 48


def test_fevereiro_bissexto() -> None:
    assert month_period(2028, 2).days == 29
    assert month_period(2027, 2).days == 28
    assert month_period(2028, 2).hours == 29 * HOURS_PER_DAY


@pytest.mark.parametrize(
    ("trimestre", "dias"),
    [(1, 31 + 28 + 31), (2, 30 + 31 + 30), (3, 31 + 31 + 30), (4, 31 + 30 + 31)],
)
def test_trimestres_de_2027(trimestre: int, dias: int) -> None:
    assert quarter_period(2027, trimestre).days == dias


def test_soma_dos_meses_fecha_o_ano() -> None:
    total = sum(month_period(2028, m).hours for m in range(1, 13))
    assert total == year_hours(2028)


def test_fim_antes_do_inicio_e_erro() -> None:
    with pytest.raises(InvalidPeriodError, match="anterior"):
        DeliveryPeriod(date(2027, 12, 31), date(2027, 1, 1))


def test_periodo_sem_data_e_erro() -> None:
    with pytest.raises(InvalidPeriodError):
        DeliveryPeriod(None, date(2027, 1, 1))  # type: ignore[arg-type]


def test_conversao_mwmed_para_mwh() -> None:
    """50 MWmed no ano de 2027 = 50 x 8760 = 438.000 MWh."""
    periodo = year_period(2027)
    assert mwmed_to_mwh(Decimal("50"), periodo) == Decimal("438000.000")


def test_conversao_ida_e_volta() -> None:
    periodo = year_period(2028)
    mwh = mwmed_to_mwh(Decimal("37.5"), periodo)
    assert mwh_to_mwmed(mwh, periodo) == Decimal("37.500")


def test_mesma_potencia_em_ano_bissexto_gera_mais_energia() -> None:
    comum = mwmed_to_mwh(Decimal("50"), year_period(2027))
    bissexto = mwmed_to_mwh(Decimal("50"), year_period(2028))
    assert bissexto - comum == Decimal("1200.000")  # 50 MW x 24 h


def test_intersecao_de_periodos() -> None:
    a = DeliveryPeriod(date(2027, 1, 1), date(2027, 6, 30))
    b = DeliveryPeriod(date(2027, 4, 1), date(2027, 12, 31))
    overlap = a.overlap(b)
    assert overlap is not None
    assert overlap.start == date(2027, 4, 1) and overlap.end == date(2027, 6, 30)


def test_periodos_disjuntos_nao_se_cruzam() -> None:
    a = DeliveryPeriod(date(2027, 1, 1), date(2027, 3, 31))
    b = DeliveryPeriod(date(2027, 4, 1), date(2027, 6, 30))
    assert a.overlap(b) is None


def test_contains() -> None:
    periodo = year_period(2027)
    assert periodo.contains(date(2027, 7, 1))
    assert not periodo.contains(date(2028, 1, 1))


def test_dias_uteis_de_uma_semana_cheia() -> None:
    # 2027-01-04 e segunda-feira; 2027-01-10 e domingo.
    semana = DeliveryPeriod(date(2027, 1, 4), date(2027, 1, 10))
    assert business_days(semana) == 5


def test_feriado_sai_da_contagem() -> None:
    semana = DeliveryPeriod(date(2027, 1, 4), date(2027, 1, 8))
    assert business_days(semana, holidays=frozenset({date(2027, 1, 6)})) == 4
