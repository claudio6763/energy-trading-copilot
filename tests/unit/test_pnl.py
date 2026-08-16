"""P&L: sinais de posicao comprada e vendida, e dado ausente.

O teste central e o de simetria: comprado e vendido no mesmo contrato tem P&L
exatamente oposto. Se isso quebrar, todo o resto do motor esta errado.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from copilot.common.enums import Side, Submarket
from copilot.common.errors import MissingDataError
from copilot.quant.periods import year_period
from copilot.quant.pnl import PositionSpec, carry_pnl, portfolio_pnl, position_pnl

PERIODO = year_period(2027)  # 8760 h


def posicao(side: Side, *, mwmed: str = "50", preco: str = "200.00", key: str = "fwd_se_a1"):
    return PositionSpec(
        position_id=f"pos-{side.value.lower()}",
        side=side,
        volume_mwmed=Decimal(mwmed),
        price_contract=Decimal(preco),
        period=PERIODO,
        submarket=Submarket.SE_CO,
        metric_key=key,
    )


def test_volume_em_mwh_usa_as_horas_do_periodo() -> None:
    assert posicao(Side.LONG).volume_mwh == Decimal("438000.000")


def test_comprado_ganha_quando_o_mercado_sobe() -> None:
    """(220 - 200) x 438.000 = R$ 8.760.000."""
    resultado = position_pnl(posicao(Side.LONG), Decimal("220.00"))
    assert resultado.pnl_brl == Decimal("8760000.00")
    assert resultado.is_gain


def test_comprado_perde_quando_o_mercado_cai() -> None:
    resultado = position_pnl(posicao(Side.LONG), Decimal("180.00"))
    assert resultado.pnl_brl == Decimal("-8760000.00")
    assert not resultado.is_gain


def test_vendido_ganha_quando_o_mercado_cai() -> None:
    """(200 - 180) x 438.000 = R$ 8.760.000."""
    resultado = position_pnl(posicao(Side.SHORT), Decimal("180.00"))
    assert resultado.pnl_brl == Decimal("8760000.00")


def test_vendido_perde_quando_o_mercado_sobe() -> None:
    resultado = position_pnl(posicao(Side.SHORT), Decimal("220.00"))
    assert resultado.pnl_brl == Decimal("-8760000.00")


@pytest.mark.parametrize("preco", ["150.00", "200.00", "260.00"])
def test_comprado_e_vendido_sao_exatamente_opostos(preco: str) -> None:
    comprado = position_pnl(posicao(Side.LONG), Decimal(preco)).pnl_brl
    vendido = position_pnl(posicao(Side.SHORT), Decimal(preco)).pnl_brl
    assert comprado == -vendido


def test_pnl_zero_no_preco_do_contrato() -> None:
    for side in (Side.LONG, Side.SHORT):
        assert position_pnl(posicao(side), Decimal("200.00")).pnl_brl == Decimal("0.00")


def test_exposicao_assinada_segue_a_direcao() -> None:
    comprado = position_pnl(posicao(Side.LONG), Decimal("200.00"))
    vendido = position_pnl(posicao(Side.SHORT), Decimal("200.00"))
    assert comprado.signed_exposure_brl > 0
    assert vendido.signed_exposure_brl < 0
    assert comprado.signed_exposure_brl == -vendido.signed_exposure_brl


def test_notional_e_sempre_positivo() -> None:
    for side in (Side.LONG, Side.SHORT):
        assert posicao(side).notional() == Decimal("87600000.00")


def test_portfolio_soma_as_posicoes() -> None:
    posicoes = [posicao(Side.LONG), posicao(Side.SHORT)]
    resultado = portfolio_pnl(posicoes, {"fwd_se_a1": Decimal("230.00")})
    assert resultado.total_pnl_brl == Decimal("0.00")  # travadas, se cancelam
    assert resultado.net_exposure_brl == Decimal("0.00")
    assert resultado.gross_exposure_brl > 0
    assert not resultado.is_directional


def test_portfolio_direcional() -> None:
    posicoes = [
        posicao(Side.SHORT, key="fwd_se_a1"),
        posicao(Side.SHORT, mwmed="10", key="fwd_se_a2"),
    ]
    resultado = portfolio_pnl(
        posicoes, {"fwd_se_a1": Decimal("210.00"), "fwd_se_a2": Decimal("210.00")}
    )
    assert resultado.is_directional
    assert resultado.total_pnl_brl < 0


def test_preco_ausente_interrompe_a_marcacao() -> None:
    """Dado faltante nunca vira zero (RF-36)."""
    posicoes = [posicao(Side.LONG, key="fwd_se_a1"), posicao(Side.SHORT, key="fwd_se_a2")]
    with pytest.raises(MissingDataError, match="fwd_se_a2"):
        portfolio_pnl(posicoes, {"fwd_se_a1": Decimal("200.00")})


def test_preco_none_em_posicao_isolada() -> None:
    with pytest.raises(MissingDataError, match="sem preco"):
        position_pnl(posicao(Side.LONG), None)  # type: ignore[arg-type]


def test_portfolio_vazio_devolve_zero_explicito() -> None:
    resultado = portfolio_pnl([], {})
    assert resultado.total_pnl_brl == Decimal("0.00")
    assert resultado.positions == ()


def test_carrego_e_pro_rata_das_horas() -> None:
    p = posicao(Side.SHORT)
    metade = p.period.hours // 2
    total = position_pnl(p, Decimal("180.00")).pnl_brl
    carrego = carry_pnl(p, Decimal("180.00"), elapsed_hours=metade)
    assert carrego == (total / 2).quantize(Decimal("0.01"))


def test_carrego_fora_do_periodo_e_erro() -> None:
    p = posicao(Side.LONG)
    with pytest.raises(MissingDataError, match="fora do periodo"):
        carry_pnl(p, Decimal("200.00"), elapsed_hours=p.period.hours + 1)


def test_ano_bissexto_muda_o_pnl() -> None:
    """Mesma potencia, mesmo delta de preco, um dia a mais de entrega."""
    from copilot.quant.periods import year_period as yp

    comum = PositionSpec("a", Side.LONG, Decimal("50"), Decimal("200.00"), yp(2027),
                         Submarket.SE_CO, "k")
    bissexto = PositionSpec("b", Side.LONG, Decimal("50"), Decimal("200.00"), yp(2028),
                            Submarket.SE_CO, "k")
    delta = position_pnl(bissexto, Decimal("210.00")).pnl_brl - position_pnl(
        comum, Decimal("210.00")
    ).pnl_brl
    assert delta == Decimal("12000.00")  # 10 R$/MWh x 50 MW x 24 h
