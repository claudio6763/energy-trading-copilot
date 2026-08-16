"""Add-ons de risco e consumo do limite de R$ 50 milhoes.

O teste que mais importa: usar PLD como referencia de curva **tem** que custar
mais caro que usar curva negociada. Se nao custar, a penalizacao virou enfeite.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from copilot.common.enums import AddOnKind, CurveOrigin, DataQuality
from copilot.common.errors import VarLimitExceeded
from copilot.quant.addons import (
    AddOnBundle,
    basis_addon,
    build_addons,
    liquidity_addon,
    model_risk_addon,
    proxy_addon,
)
from copilot.quant.limits import (
    VAR_LIMIT_BRL,
    WARNING_UTILIZATION,
    assert_within_limit,
    check_var_limit,
    max_exposure_under_limit,
)

EXPOSICAO = Decimal("100000000.00")  # R$ 100 mi


# --------------------------------------------------------------- liquidez
def test_liquidez_cresce_com_a_posicao_frente_ao_giro() -> None:
    pequena = liquidity_addon(
        EXPOSICAO, position_mwmed=Decimal("10"), market_adv_mwmed=Decimal("100")
    )
    grande = liquidity_addon(
        EXPOSICAO, position_mwmed=Decimal("500"), market_adv_mwmed=Decimal("100")
    )
    assert grande.amount_brl > pequena.amount_brl
    assert grande.kind is AddOnKind.LIQUIDEZ


def test_liquidez_tem_piso_de_um_dia() -> None:
    """Posicao minuscula ainda paga meio spread: nao existe saida gratis."""
    addon = liquidity_addon(
        EXPOSICAO, position_mwmed=Decimal("1"), market_adv_mwmed=Decimal("10000")
    )
    esperado = float(EXPOSICAO) * (0.020 / 2) * 1.0
    assert float(addon.amount_brl) == pytest.approx(esperado, abs=0.01)


def test_liquidez_e_limitada_pelo_teto_de_desmontagem() -> None:
    enorme = liquidity_addon(
        EXPOSICAO, position_mwmed=Decimal("100000"), market_adv_mwmed=Decimal("1")
    )
    teto = float(EXPOSICAO) * (0.020 / 2) * math.sqrt(60)
    assert float(enorme.amount_brl) == pytest.approx(teto, abs=0.01)


def test_giro_zero_e_erro() -> None:
    with pytest.raises(ValueError):
        liquidity_addon(EXPOSICAO, position_mwmed=Decimal("1"), market_adv_mwmed=Decimal("0"))


# ------------------------------------------------------------------ basis
def test_hedge_perfeito_nao_gera_basis() -> None:
    addon = basis_addon(EXPOSICAO, basis_vol_daily=0.03, correlation=1.0)
    assert addon.amount_brl == Decimal("0.00")


def test_correlacao_zero_deixa_o_risco_inteiro() -> None:
    addon = basis_addon(EXPOSICAO, basis_vol_daily=0.03, correlation=0.0, horizon_days=1)
    esperado = 1.6448536269514722 * 0.03 * float(EXPOSICAO)
    assert float(addon.amount_brl) == pytest.approx(esperado, abs=0.01)


def test_basis_cresce_quando_a_correlacao_cai() -> None:
    alta = basis_addon(EXPOSICAO, basis_vol_daily=0.03, correlation=0.95)
    baixa = basis_addon(EXPOSICAO, basis_vol_daily=0.03, correlation=0.60)
    assert baixa.amount_brl > alta.amount_brl


def test_correlacao_invalida() -> None:
    with pytest.raises(ValueError):
        basis_addon(EXPOSICAO, basis_vol_daily=0.03, correlation=1.4)


# ------------------------------------------------------------------ proxy
def test_curva_negociada_nao_paga_proxy() -> None:
    addon = proxy_addon(EXPOSICAO, curve_origin=CurveOrigin.NEGOCIADA, quality=DataQuality.OK)
    assert addon.amount_brl == Decimal("0.00")
    assert "sem penalizacao" in addon.rationale


def test_pld_como_referencia_e_a_penalizacao_mais_cara() -> None:
    """PLD/CMO nao e curva negociada. Usar custa, e o custo aparece no numero."""
    negociada = proxy_addon(EXPOSICAO, curve_origin=CurveOrigin.NEGOCIADA)
    modelo = proxy_addon(EXPOSICAO, curve_origin=CurveOrigin.PROXY_MODELO)
    spot = proxy_addon(EXPOSICAO, curve_origin=CurveOrigin.PROXY_SPOT)
    assert spot.amount_brl > modelo.amount_brl > negociada.amount_brl
    assert spot.amount_brl == Decimal("25000000.00")  # 25% de R$ 100 mi


def test_qualidade_ruim_soma_penalizacao() -> None:
    limpa = proxy_addon(EXPOSICAO, curve_origin=CurveOrigin.PROXY_SPOT, quality=DataQuality.OK)
    suja = proxy_addon(
        EXPOSICAO, curve_origin=CurveOrigin.PROXY_SPOT, quality=DataQuality.SUSPEITO
    )
    assert suja.amount_brl > limpa.amount_brl
    assert "SUSPEITO" in suja.rationale


def test_proxy_declara_os_parametros_usados() -> None:
    addon = proxy_addon(EXPOSICAO, curve_origin=CurveOrigin.PROXY_SPOT, quality=DataQuality.PROXY)
    assert addon.parameters["origem"] == "PROXY_SPOT"
    assert addon.parameters["qualidade"] == "PROXY"


# ----------------------------------------------------------- risco de modelo
def test_risco_de_modelo_e_proporcional_ao_var() -> None:
    addon = model_risk_addon(Decimal("10000000.00"))
    assert addon.amount_brl == Decimal("1000000.00")  # 10%


def test_multiplicador_negativo_e_erro() -> None:
    with pytest.raises(ValueError):
        model_risk_addon(Decimal("1000000.00"), multiplier=Decimal("-0.1"))


# ----------------------------------------------------------------- pacote
def test_pacote_completo_soma_os_componentes() -> None:
    pacote = build_addons(
        var_market_brl=Decimal("10000000.00"),
        gross_exposure_brl=EXPOSICAO,
        position_mwmed=Decimal("50"),
        market_adv_mwmed=Decimal("200"),
        basis_vol_daily=0.02,
        basis_correlation=0.8,
        curve_origin=CurveOrigin.PROXY_SPOT,
        quality=DataQuality.PROXY,
    )
    assert pacote.total_brl == sum(a.amount_brl for a in pacote.items)
    assert {a.kind for a in pacote.items} == set(AddOnKind)
    assert len(pacote.explain()) == 4


def test_pacote_omite_componente_sem_parametro_declarado() -> None:
    """Sem giro de mercado declarado, nao inventamos liquidez."""
    pacote = build_addons(
        var_market_brl=Decimal("10000000.00"), gross_exposure_brl=EXPOSICAO
    )
    assert pacote.by_kind(AddOnKind.LIQUIDEZ) == Decimal("0.00")
    assert pacote.by_kind(AddOnKind.BASIS) == Decimal("0.00")
    assert pacote.by_kind(AddOnKind.RISCO_MODELO) > 0


# ------------------------------------------------------------------ limite
def test_limite_padrao_e_o_do_case() -> None:
    assert VAR_LIMIT_BRL == Decimal("50000000.00")


@pytest.mark.parametrize(
    ("var", "dentro"),
    [
        ("49900000.00", True),
        ("50000000.00", True),
        ("50000000.01", False),
        ("50100000.00", False),
    ],
)
def test_fronteira_do_limite(var: str, dentro: bool) -> None:
    """AC-43: testado exatamente na fronteira, inclusive um centavo acima."""
    resultado = check_var_limit(Decimal(var))
    assert resultado.within_limit is dentro


def test_addons_contam_no_consumo_do_limite() -> None:
    """Medir so o VaR de mercado subestimaria exatamente onde mais importa."""
    addons = AddOnBundle((proxy_addon(Decimal("40000000.00"), curve_origin=CurveOrigin.PROXY_SPOT),))
    sozinho = check_var_limit(Decimal("45000000.00"))
    com_addons = check_var_limit(Decimal("45000000.00"), addons=addons)
    assert sozinho.within_limit is True
    assert com_addons.within_limit is False
    assert com_addons.addons_brl == Decimal("10000000.00")


def test_utilizacao_e_folga() -> None:
    resultado = check_var_limit(Decimal("25000000.00"))
    assert resultado.utilization == Decimal("0.500000")
    assert resultado.headroom_brl == Decimal("25000000.00")
    assert not resultado.warning


def test_faixa_de_atencao() -> None:
    resultado = check_var_limit(VAR_LIMIT_BRL * WARNING_UTILIZATION)
    assert resultado.within_limit and resultado.warning
    assert "atencao" in resultado.message


def test_estouro_bloqueia_no_caminho_de_aprovacao() -> None:
    """D-04: limite e *hard*."""
    with pytest.raises(VarLimitExceeded, match="excede o limite"):
        assert_within_limit(Decimal("50000000.01"))


def test_aprovacao_passa_dentro_do_limite() -> None:
    resultado = assert_within_limit(Decimal("30000000.00"))
    assert resultado.within_limit


def test_breakdown_por_tipo_de_addon() -> None:
    pacote = build_addons(
        var_market_brl=Decimal("10000000.00"),
        gross_exposure_brl=Decimal("50000000.00"),
        curve_origin=CurveOrigin.PROXY_SPOT,
    )
    resultado = check_var_limit(Decimal("10000000.00"), addons=pacote)
    assert AddOnKind.PROXY.value in resultado.addon_breakdown
    assert AddOnKind.RISCO_MODELO.value in resultado.addon_breakdown


def test_dimensionamento_reverso() -> None:
    """Quanto cabe no limite, dado o VaR por real exposto."""
    maximo = max_exposure_under_limit(Decimal("0.05"))
    assert maximo == Decimal("1000000000.00")  # 50 mi / 0,05
    com_carga = max_exposure_under_limit(Decimal("0.05"), addon_load=Decimal("0.05"))
    assert com_carga == Decimal("500000000.00")


def test_dimensionamento_com_var_nao_positivo() -> None:
    with pytest.raises(ValueError):
        max_exposure_under_limit(Decimal("0"))


def test_limite_nao_positivo() -> None:
    with pytest.raises(ValueError):
        check_var_limit(Decimal("1000"), limit_brl=Decimal("0"))
