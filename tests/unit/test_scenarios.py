"""Cenarios hidrologicos: seco, base, umido e extremo (RF-53 / AC-42)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from copilot.common.enums import HydroScenario, Side, Submarket
from copilot.common.errors import MissingDataError
from copilot.quant.periods import year_period
from copilot.quant.pnl import PositionSpec
from copilot.quant.scenarios import STANDARD_SCENARIOS, run_scenario, run_scenarios

PRECO_BASE = {"fwd_se_a1": Decimal("200.00")}
SIGMAS = {"fwd_se_a1": 0.02}


def vendido(mwmed: str = "50") -> PositionSpec:
    return PositionSpec(
        position_id="pos-1",
        side=Side.SHORT,
        volume_mwmed=Decimal(mwmed),
        price_contract=Decimal("200.00"),
        period=year_period(2027),
        submarket=Submarket.SE_CO,
        metric_key="fwd_se_a1",
    )


def comprado(mwmed: str = "50") -> PositionSpec:
    return PositionSpec(
        position_id="pos-2",
        side=Side.LONG,
        volume_mwmed=Decimal(mwmed),
        price_contract=Decimal("200.00"),
        period=year_period(2027),
        submarket=Submarket.SE_CO,
        metric_key="fwd_se_a1",
    )


def test_os_quatro_cenarios_estao_definidos() -> None:
    assert set(STANDARD_SCENARIOS) == {
        HydroScenario.SECO,
        HydroScenario.BASE,
        HydroScenario.UMIDO,
        HydroScenario.EXTREMO,
    }


def test_pesos_de_probabilidade_somam_um_sem_o_estresse() -> None:
    peso = sum(
        d.probability for d in STANDARD_SCENARIOS.values() if not d.is_stress
    )
    assert peso == Decimal("1.00")
    assert STANDARD_SCENARIOS[HydroScenario.EXTREMO].probability == Decimal("0.00")


def test_extremo_e_estresse_e_nao_previsao() -> None:
    extremo = STANDARD_SCENARIOS[HydroScenario.EXTREMO]
    assert extremo.is_stress
    assert "estresse" in extremo.description.lower()


def test_choque_de_preco_por_cenario() -> None:
    base = Decimal("200.00")
    assert STANDARD_SCENARIOS[HydroScenario.BASE].shock_price(base) == Decimal("200.00")
    assert STANDARD_SCENARIOS[HydroScenario.SECO].shock_price(base) == Decimal("270.00")
    assert STANDARD_SCENARIOS[HydroScenario.UMIDO].shock_price(base) == Decimal("150.00")
    assert STANDARD_SCENARIOS[HydroScenario.EXTREMO].shock_price(base) == Decimal("360.00")


def test_vendido_perde_no_seco_e_ganha_no_umido() -> None:
    """A direcao do resultado por cenario e o que a Entrega 2 precisa mostrar."""
    matriz = run_scenarios([vendido()], PRECO_BASE, sigma_daily=SIGMAS)
    seco = matriz.by_name(HydroScenario.SECO)
    umido = matriz.by_name(HydroScenario.UMIDO)
    assert seco is not None and umido is not None
    assert seco.pnl_brl < 0
    assert umido.pnl_brl > 0


def test_comprado_inverte_o_resultado() -> None:
    matriz = run_scenarios([comprado()], PRECO_BASE, sigma_daily=SIGMAS)
    assert matriz.by_name(HydroScenario.SECO).pnl_brl > 0
    assert matriz.by_name(HydroScenario.UMIDO).pnl_brl < 0


def test_cenario_base_tem_pnl_zero_no_preco_do_contrato() -> None:
    matriz = run_scenarios([vendido()], PRECO_BASE, sigma_daily=SIGMAS)
    assert matriz.by_name(HydroScenario.BASE).pnl_brl == Decimal("0.00")
    assert matriz.base_pnl_brl == Decimal("0.00")


def test_extremo_e_o_pior_caso_para_o_vendido() -> None:
    matriz = run_scenarios([vendido()], PRECO_BASE, sigma_daily=SIGMAS)
    assert matriz.worst_case.scenario is HydroScenario.EXTREMO


def test_var_sobe_no_seco_e_no_extremo() -> None:
    """Multiplicador de volatilidade eleva o VaR — e o delta fica explicito."""
    matriz = run_scenarios([vendido()], PRECO_BASE, sigma_daily=SIGMAS)
    assert matriz.by_name(HydroScenario.SECO).var_delta_brl > 0
    assert matriz.by_name(HydroScenario.EXTREMO).var_delta_brl > matriz.by_name(
        HydroScenario.SECO
    ).var_delta_brl
    assert matriz.by_name(HydroScenario.BASE).var_delta_brl == Decimal("0.00")


def test_esperanca_ignora_o_estresse() -> None:
    matriz = run_scenarios([vendido()], PRECO_BASE, sigma_daily=SIGMAS)
    esperado = sum(
        o.pnl_brl * o.probability for o in matriz.outcomes if not o.is_stress
    )
    assert matriz.expected_pnl_brl == esperado.quantize(Decimal("0.01"))


def test_cada_cenario_diz_o_que_muda_na_tese() -> None:
    """Exigencia literal da Entrega 2."""
    matriz = run_scenarios([vendido()], PRECO_BASE, sigma_daily=SIGMAS)
    for resultado in matriz.outcomes:
        assert resultado.thesis_delta
        assert resultado.description


def test_pelo_menos_dois_cenarios_hidrologicos_distintos() -> None:
    matriz = run_scenarios([vendido()], PRECO_BASE, sigma_daily=SIGMAS)
    assert matriz.hydrological_count >= 2


def test_cenario_sem_posicao_e_erro() -> None:
    with pytest.raises(MissingDataError, match="sem posicoes"):
        run_scenario([], PRECO_BASE, STANDARD_SCENARIOS[HydroScenario.BASE])


def test_cenario_sem_volatilidade_declarada() -> None:
    with pytest.raises(MissingDataError, match="volatilidade"):
        run_scenario(
            [vendido()],
            PRECO_BASE,
            STANDARD_SCENARIOS[HydroScenario.SECO],
            sigma_daily={},
        )


def test_matriz_exige_cenario_base() -> None:
    apenas_seco = {HydroScenario.SECO: STANDARD_SCENARIOS[HydroScenario.SECO]}
    with pytest.raises(MissingDataError, match="BASE"):
        run_scenarios([vendido()], PRECO_BASE, definitions=apenas_seco)


def test_matriz_e_reprodutivel() -> None:
    a = run_scenarios([vendido()], PRECO_BASE, sigma_daily=SIGMAS)
    b = run_scenarios([vendido()], PRECO_BASE, sigma_daily=SIGMAS)
    assert [(o.scenario, o.pnl_brl, o.var_brl) for o in a.outcomes] == [
        (o.scenario, o.pnl_brl, o.var_brl) for o in b.outcomes
    ]
