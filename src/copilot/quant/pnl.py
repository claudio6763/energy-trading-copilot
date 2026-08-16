"""P&L de posicao comprada e vendida.

Convencao de sinal, unica em todo o projeto:

* **Comprado (LONG)** — travou preco de compra. Ganha quando o mercado sobe.
  ``P&L = (P_mercado - P_contrato) x MWh``
* **Vendido (SHORT)** — travou preco de venda. Ganha quando o mercado cai.
  ``P&L = (P_contrato - P_mercado) x MWh``

Exposicao assinada (`signed_exposure`) e o que entra no VaR de portfolio: e ela
que faz posicoes opostas se compensarem em vez de somarem risco.

Sem `float` em dinheiro: tudo em `Decimal` (CLAUDE.md secao 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence

from copilot.common.enums import Side, Submarket
from copilot.common.errors import MissingDataError
from copilot.quant.periods import DeliveryPeriod, mwmed_to_mwh

MONEY = Decimal("0.01")
ENERGY = Decimal("0.001")


def _side_sign(side: Side) -> Decimal:
    """+1 comprado, -1 vendido."""
    return Decimal(1) if side is Side.LONG else Decimal(-1)


@dataclass(frozen=True, slots=True)
class PositionSpec:
    """Posicao para fins de calculo. Espelha `db.models.thesis.Position`."""

    position_id: str
    side: Side
    #: Volume em MWmed (como o mercado negocia).
    volume_mwmed: Decimal
    #: Preco travado no contrato, R$/MWh.
    price_contract: Decimal
    period: DeliveryPeriod
    submarket: Submarket
    #: Chave da curva/serie usada para marcar a posicao.
    metric_key: str
    instrument: str = "FORWARD_CONV"

    @property
    def volume_mwh(self) -> Decimal:
        return mwmed_to_mwh(self.volume_mwmed, self.period)

    @property
    def sign(self) -> Decimal:
        return _side_sign(self.side)

    def notional(self) -> Decimal:
        """Valor absoluto do contrato, R$. Sempre positivo."""
        return (abs(self.volume_mwh) * self.price_contract).quantize(MONEY)

    def signed_exposure(self, price_market: Decimal) -> Decimal:
        """Exposicao assinada a marcado, R$.

        Positiva para comprado, negativa para vendido. E a sensibilidade da
        posicao a um movimento de preco — a entrada do VaR.
        """
        return (self.sign * self.volume_mwh * Decimal(price_market)).quantize(MONEY)


@dataclass(frozen=True, slots=True)
class PositionPnL:
    position_id: str
    side: Side
    volume_mwh: Decimal
    price_contract: Decimal
    price_market: Decimal
    hours: int
    pnl_brl: Decimal
    notional_brl: Decimal
    signed_exposure_brl: Decimal
    metric_key: str

    @property
    def is_gain(self) -> bool:
        return self.pnl_brl > 0


@dataclass(frozen=True, slots=True)
class PortfolioPnL:
    positions: tuple[PositionPnL, ...]
    total_pnl_brl: Decimal
    gross_notional_brl: Decimal
    net_exposure_brl: Decimal
    gross_exposure_brl: Decimal
    as_of: date | None = None

    @property
    def is_directional(self) -> bool:
        """Portfolio direcional: exposicao liquida relevante frente a bruta."""
        if self.gross_exposure_brl == 0:
            return False
        return abs(self.net_exposure_brl) / self.gross_exposure_brl > Decimal("0.5")


def position_pnl(
    position: PositionSpec,
    price_market: Decimal,
    *,
    as_of: date | None = None,
) -> PositionPnL:
    """P&L de marcacao a mercado de uma posicao.

    :param price_market: preco de marcacao em R$/MWh, ja escolhido pela camada
        de dados (curva negociada quando existe; proxy declarado caso contrario).
    """
    if price_market is None:
        raise MissingDataError(
            f"Posicao {position.position_id}: sem preco de mercado para "
            f"{position.metric_key}. Marcacao sem preco nao e zero — e falta de dado."
        )
    price_market = Decimal(price_market)
    volume_mwh = position.volume_mwh
    delta = (Decimal(price_market) - Decimal(position.price_contract)) * position.sign
    pnl = (delta * volume_mwh).quantize(MONEY)
    return PositionPnL(
        position_id=position.position_id,
        side=position.side,
        volume_mwh=volume_mwh,
        price_contract=Decimal(position.price_contract).quantize(MONEY),
        price_market=price_market.quantize(MONEY),
        hours=position.period.hours,
        pnl_brl=pnl,
        notional_brl=position.notional(),
        signed_exposure_brl=position.signed_exposure(price_market),
        metric_key=position.metric_key,
    )


def portfolio_pnl(
    positions: Sequence[PositionSpec],
    prices: dict[str, Decimal],
    *,
    as_of: date | None = None,
) -> PortfolioPnL:
    """P&L agregado. Preco ausente para qualquer posicao interrompe o calculo."""
    if not positions:
        return PortfolioPnL((), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), as_of)

    faltando = sorted({p.metric_key for p in positions if p.metric_key not in prices})
    if faltando:
        raise MissingDataError(
            "Marcacao interrompida: sem preco para " + ", ".join(faltando) + ". "
            "O portfolio nao e marcado parcialmente (RF-36)."
        )

    detalhes = tuple(
        position_pnl(p, prices[p.metric_key], as_of=as_of) for p in positions
    )
    total = sum((d.pnl_brl for d in detalhes), Decimal("0.00")).quantize(MONEY)
    bruto = sum((d.notional_brl for d in detalhes), Decimal("0.00")).quantize(MONEY)
    liquido = sum((d.signed_exposure_brl for d in detalhes), Decimal("0.00")).quantize(MONEY)
    exposicao_bruta = sum(
        (abs(d.signed_exposure_brl) for d in detalhes), Decimal("0.00")
    ).quantize(MONEY)
    return PortfolioPnL(detalhes, total, bruto, liquido, exposicao_bruta, as_of)


def carry_pnl(
    position: PositionSpec,
    price_market: Decimal,
    *,
    elapsed_hours: int,
) -> Decimal:
    """Parcela do P&L ja 'entregue' — carrego, pro rata das horas decorridas.

    Separar carrego de tese e o que permite o post-mortem honesto: quanto do
    resultado veio da leitura e quanto veio simplesmente do tempo passar.
    """
    if elapsed_hours < 0 or elapsed_hours > position.period.hours:
        raise MissingDataError(
            f"Horas decorridas ({elapsed_hours}) fora do periodo "
            f"({position.period.hours} h)."
        )
    total = position_pnl(position, price_market).pnl_brl
    if position.period.hours == 0:  # pragma: no cover
        return Decimal("0.00")
    fracao = Decimal(elapsed_hours) / Decimal(position.period.hours)
    return (total * fracao).quantize(MONEY)


__all__ = [
    "PortfolioPnL",
    "PositionPnL",
    "PositionSpec",
    "carry_pnl",
    "portfolio_pnl",
    "position_pnl",
]
