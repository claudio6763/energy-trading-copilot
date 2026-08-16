"""Periodo de entrega e conversao MWmed <-> MWh.

O erro mais caro e mais silencioso de uma mesa de energia e confundir potencia
media (MWmed) com energia (MWh). Todo contrato do mercado livre brasileiro e
negociado em MWmed; o P&L e o VaR precisam de MWh. A ponte e o numero de horas
do periodo — e ele muda com ano bissexto.

Premissa declarada: **24 horas por dia civil.** O Brasil nao adota horario de
verao desde 2019 (Decreto 9.772/2019), entao nao ha dias de 23 ou 25 horas no
horizonte do case. Se o horario de verao voltar, esta funcao e o unico ponto a
mudar.

Convencao: periodo **inclusivo** nas duas pontas. `2027-01-01` a `2027-12-31`
e o ano inteiro.
"""

from __future__ import annotations

from calendar import isleap, monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from copilot.common.errors import InvalidPeriodError

#: Horas por dia civil. Ver premissa no docstring do modulo.
HOURS_PER_DAY = 24


@dataclass(frozen=True, slots=True)
class DeliveryPeriod:
    """Periodo de entrega, inclusivo nas duas pontas."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start is None or self.end is None:
            raise InvalidPeriodError("Periodo de entrega exige data de inicio e de fim.")
        if self.end < self.start:
            raise InvalidPeriodError(
                f"Fim ({self.end.isoformat()}) anterior ao inicio ({self.start.isoformat()})."
            )

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def hours(self) -> int:
        return self.days * HOURS_PER_DAY

    @property
    def label(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def overlap(self, other: "DeliveryPeriod") -> "DeliveryPeriod | None":
        """Intersecao com outro periodo, ou None. Base do calculo de basis."""
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        return DeliveryPeriod(start, end) if start <= end else None


def period_hours(start: date, end: date) -> int:
    """Horas do periodo inclusivo. Trata ano bissexto pelo calendario real."""
    return DeliveryPeriod(start, end).hours


def year_period(year: int) -> DeliveryPeriod:
    """Ano civil completo (`A+1`, `A+2`...). 8784 h em bissexto, 8760 fora."""
    return DeliveryPeriod(date(year, 1, 1), date(year, 12, 31))


def year_hours(year: int) -> int:
    return (366 if isleap(year) else 365) * HOURS_PER_DAY


def month_period(year: int, month: int) -> DeliveryPeriod:
    if not 1 <= month <= 12:
        raise InvalidPeriodError(f"Mes invalido: {month}")
    return DeliveryPeriod(date(year, month, 1), date(year, month, monthrange(year, month)[1]))


def quarter_period(year: int, quarter: int) -> DeliveryPeriod:
    if not 1 <= quarter <= 4:
        raise InvalidPeriodError(f"Trimestre invalido: {quarter}")
    first = 3 * (quarter - 1) + 1
    last = first + 2
    return DeliveryPeriod(
        date(year, first, 1), date(year, last, monthrange(year, last)[1])
    )


def mwmed_to_mwh(mwmed: Decimal, period: DeliveryPeriod) -> Decimal:
    """MWh = MWmed x horas do periodo."""
    return (Decimal(mwmed) * Decimal(period.hours)).quantize(Decimal("0.001"))


def mwh_to_mwmed(mwh: Decimal, period: DeliveryPeriod) -> Decimal:
    """MWmed = MWh / horas do periodo."""
    if period.hours == 0:  # pragma: no cover - impossivel por construcao
        raise InvalidPeriodError("Periodo com zero horas.")
    return (Decimal(mwh) / Decimal(period.hours)).quantize(Decimal("0.001"))


def business_days(period: DeliveryPeriod, holidays: frozenset[date] = frozenset()) -> int:
    """Dias uteis do periodo. Usado no escalonamento de VaR por horizonte."""
    count = 0
    day = period.start
    while day <= period.end:
        if day.weekday() < 5 and day not in holidays:
            count += 1
        day += timedelta(days=1)
    return count


__all__ = [
    "HOURS_PER_DAY",
    "DeliveryPeriod",
    "business_days",
    "month_period",
    "mwh_to_mwmed",
    "mwmed_to_mwh",
    "period_hours",
    "quarter_period",
    "year_hours",
    "year_period",
]
