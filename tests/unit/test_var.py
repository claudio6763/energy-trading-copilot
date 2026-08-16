"""VaR: formulas, amostra insuficiente, dados ausentes e reprodutibilidade.

Os valores de referencia sao derivados no proprio teste a partir de constantes
conhecidas (z de 95% e 99%), nao transcritos da saida do codigo. Assim o teste
verifica a composicao da formula, e nao apenas que ela nao mudou.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

import pytest

from copilot.common.enums import QuantFunction
from copilot.common.errors import InsufficientSampleError, MissingDataError
from copilot.quant.var import (
    DEFAULT_CONFIDENCE,
    MIN_SAMPLE_HISTORICAL,
    MIN_SAMPLE_PARAMETRIC,
    ReturnSeries,
    ewma_var,
    ewma_volatility,
    historical_var,
    horizon_factor,
    log_returns,
    parametric_var,
    percentile,
    portfolio_historical_var,
    portfolio_parametric_var,
    sample_volatility,
    z_score,
)

Z95 = 1.6448536269514722
Z99 = 2.3263478740408408
INICIO = date(2026, 1, 5)


def serie_precos(n: int, *, base: float = 200.0, amplitude: float = 0.02) -> list[tuple[date, Decimal]]:
    """Serie deterministica de precos uteis, sem `random`."""
    saida = []
    dia = INICIO
    preco = base
    for i in range(n):
        preco = base * (1.0 + amplitude * math.sin(i * 0.7))
        saida.append((dia, Decimal(repr(round(preco, 4)))))
        dia += timedelta(days=1 if dia.weekday() < 4 else 3)
    return saida


def retornos(n: int, *, escala: float = 0.01) -> list[float]:
    return [escala * math.sin(i * 0.9) for i in range(n)]


# --------------------------------------------------------------------- z e h
def test_quantis_normais_conhecidos() -> None:
    assert z_score(Decimal("0.95")) == pytest.approx(Z95, rel=1e-12)
    assert z_score(Decimal("0.99")) == pytest.approx(Z99, rel=1e-12)


def test_confianca_fora_da_faixa() -> None:
    for c in (Decimal("0.5"), Decimal("1.0"), Decimal("1.5")):
        with pytest.raises(ValueError):
            z_score(c)


def test_raiz_do_tempo() -> None:
    assert horizon_factor(1) == 1.0
    assert horizon_factor(21) == pytest.approx(math.sqrt(21))
    with pytest.raises(ValueError):
        horizon_factor(0)


# -------------------------------------------------------------- log-retornos
def test_log_retornos_basicos() -> None:
    precos = [
        (date(2026, 1, 5), Decimal("100")),
        (date(2026, 1, 6), Decimal("110")),
        (date(2026, 1, 7), Decimal("99")),
    ]
    serie = log_returns(precos, metric_key="x")
    assert len(serie) == 2
    assert serie.returns[0] == pytest.approx(math.log(1.1))
    assert serie.returns[1] == pytest.approx(math.log(99 / 110))
    assert serie.dates == (date(2026, 1, 6), date(2026, 1, 7))


def test_buraco_na_serie_e_dado_ausente() -> None:
    precos = [
        (date(2026, 1, 5), Decimal("100")),
        (date(2026, 2, 20), Decimal("110")),
    ]
    with pytest.raises(MissingDataError, match="buraco"):
        log_returns(precos, metric_key="pld")


def test_datas_repetidas_ou_fora_de_ordem() -> None:
    with pytest.raises(MissingDataError, match="fora de ordem"):
        log_returns(
            [(date(2026, 1, 6), Decimal("100")), (date(2026, 1, 5), Decimal("101"))]
        )


def test_preco_nao_positivo_nao_vira_retorno() -> None:
    with pytest.raises(MissingDataError, match="nao positivo"):
        log_returns([(date(2026, 1, 5), Decimal("0")), (date(2026, 1, 6), Decimal("10"))])


def test_serie_curta_demais_para_retorno() -> None:
    with pytest.raises(InsufficientSampleError):
        log_returns([(date(2026, 1, 5), Decimal("100"))])


# --------------------------------------------------------------- volatilidade
def test_volatilidade_amostral_exige_minimo() -> None:
    with pytest.raises(InsufficientSampleError) as exc:
        sample_volatility(retornos(MIN_SAMPLE_PARAMETRIC - 1))
    assert exc.value.required == MIN_SAMPLE_PARAMETRIC


def test_volatilidade_de_serie_constante_e_zero() -> None:
    assert sample_volatility([0.0] * 30) == pytest.approx(0.0)


def test_ewma_exige_minimo_e_lambda_valido() -> None:
    with pytest.raises(InsufficientSampleError):
        ewma_volatility(retornos(5))
    with pytest.raises(ValueError):
        ewma_volatility(retornos(50), lam=1.5)


def test_ewma_reage_mais_que_a_janela_fixa_a_um_choque() -> None:
    """Regime calmo seguido de choque: EWMA sobe acima da vol amostral."""
    base = [0.001] * 60
    choque = base + [0.08] * 5
    assert ewma_volatility(choque) > sample_volatility(choque[-20:])


def test_ewma_e_deterministica() -> None:
    r = retornos(80)
    assert ewma_volatility(r) == ewma_volatility(r)


# --------------------------------------------------------- VaR parametrico
def test_var_parametrico_composicao_da_formula() -> None:
    """VaR = z * sigma * sqrt(h) * |exposicao|."""
    esperado = Z95 * 0.02 * 1.0 * 1_000_000  # 32.897,0725...
    resultado = parametric_var(
        Decimal("1000000.00"), 0.02, confidence=Decimal("0.95"), horizon_days=1
    )
    # Tolerancia de um centavo: o resultado e quantizado em Decimal de proposito.
    assert float(resultado.var_brl) == pytest.approx(esperado, abs=0.01)
    assert resultado.var_brl == Decimal("32897.07")
    assert resultado.confidence == Decimal("0.95")
    assert resultado.horizon_days == 1


def test_var_escala_com_a_raiz_do_horizonte() -> None:
    um = parametric_var(Decimal("1000000.00"), 0.02, horizon_days=1)
    vinte_um = parametric_var(Decimal("1000000.00"), 0.02, horizon_days=21)
    assert float(vinte_um.var_brl) == pytest.approx(
        float(um.var_brl) * math.sqrt(21), rel=1e-6
    )


def test_confianca_maior_gera_var_maior() -> None:
    a = parametric_var(Decimal("1000000.00"), 0.02, confidence=Decimal("0.95"))
    b = parametric_var(Decimal("1000000.00"), 0.02, confidence=Decimal("0.99"))
    assert b.var_brl > a.var_brl
    assert float(b.var_brl / a.var_brl) == pytest.approx(Z99 / Z95, rel=1e-6)


def test_var_de_posicao_isolada_independe_do_sinal() -> None:
    comprado = parametric_var(Decimal("1000000.00"), 0.02)
    vendido = parametric_var(Decimal("-1000000.00"), 0.02)
    assert comprado.var_brl == vendido.var_brl


def test_expected_shortfall_maior_que_var() -> None:
    r = parametric_var(Decimal("1000000.00"), 0.02)
    assert r.expected_shortfall_brl > r.var_brl


def test_var_diario_implicito() -> None:
    r = parametric_var(Decimal("1000000.00"), 0.02, horizon_days=21)
    esperado = float(r.var_brl) / math.sqrt(21)
    assert float(r.var_daily_brl) == pytest.approx(esperado, rel=1e-6)


def test_volatilidade_negativa_e_erro() -> None:
    with pytest.raises(ValueError):
        parametric_var(Decimal("1000000.00"), -0.01)


def test_var_ewma_reporta_metodo_e_amostra() -> None:
    r = ewma_var(Decimal("1000000.00"), retornos(80))
    assert r.method is QuantFunction.VAR_EWMA
    assert r.sample_size == 80
    assert r.var_brl > 0


# ------------------------------------------------------------- percentil
def test_percentil_interpolado() -> None:
    valores = [0.0, 10.0, 20.0, 30.0]
    assert percentile(valores, 0.0) == 0.0
    assert percentile(valores, 1.0) == 30.0
    assert percentile(valores, 0.5) == pytest.approx(15.0)


def test_percentil_de_amostra_vazia() -> None:
    with pytest.raises(InsufficientSampleError):
        percentile([], 0.5)


def test_percentil_fora_da_faixa() -> None:
    with pytest.raises(ValueError):
        percentile([1.0, 2.0], 1.5)


# -------------------------------------------------------- VaR historico
def test_var_historico_exige_cauda_povoada() -> None:
    with pytest.raises(InsufficientSampleError) as exc:
        historical_var(Decimal("1000000.00"), retornos(MIN_SAMPLE_HISTORICAL - 1))
    assert exc.value.required == MIN_SAMPLE_HISTORICAL


def test_var_historico_e_positivo_e_reprodutivel() -> None:
    r = retornos(200, escala=0.02)
    a = historical_var(Decimal("1000000.00"), r)
    b = historical_var(Decimal("1000000.00"), r)
    assert a.var_brl > 0
    assert a.var_brl == b.var_brl
    assert a.method is QuantFunction.VAR_HISTORICAL


def test_var_historico_de_serie_sem_variacao_e_zero() -> None:
    r = historical_var(Decimal("1000000.00"), [0.0] * 100)
    assert r.var_brl == Decimal("0.00")


def test_es_historico_nunca_menor_que_o_var() -> None:
    r = historical_var(Decimal("1000000.00"), retornos(200, escala=0.02))
    assert r.expected_shortfall_brl >= r.var_brl


# -------------------------------------------------------- VaR de portfolio
def test_posicoes_opostas_perfeitamente_correlacionadas_se_cancelam() -> None:
    """Comprado e vendido no mesmo risco: VaR de portfolio proximo de zero."""
    r = portfolio_parametric_var(
        {"a": Decimal("1000000.00"), "b": Decimal("-1000000.00")},
        {"a": 0.02, "b": 0.02},
        correlations={("a", "b"): 1.0},
    )
    assert float(r.var_brl) == pytest.approx(0.0, abs=1.0)


def test_correlacao_ausente_assume_um_conservador() -> None:
    r = portfolio_parametric_var(
        {"a": Decimal("1000000.00"), "b": Decimal("1000000.00")}, {"a": 0.02, "b": 0.02}
    )
    soma_isolada = 2 * float(parametric_var(Decimal("1000000.00"), 0.02).var_brl)
    assert float(r.var_brl) == pytest.approx(soma_isolada, rel=1e-6)
    assert any("correlacao" in n for n in r.notes)


def test_diversificacao_reduz_o_var() -> None:
    exposicoes = {"a": Decimal("1000000.00"), "b": Decimal("1000000.00")}
    sigmas = {"a": 0.02, "b": 0.02}
    perfeita = portfolio_parametric_var(exposicoes, sigmas, correlations={("a", "b"): 1.0})
    parcial = portfolio_parametric_var(exposicoes, sigmas, correlations={("a", "b"): 0.3})
    assert parcial.var_brl < perfeita.var_brl


def test_componentes_somam_o_var_total() -> None:
    """Decomposicao de Euler: a soma das contribuicoes e o VaR total."""
    r = portfolio_parametric_var(
        {"a": Decimal("2000000.00"), "b": Decimal("-500000.00")},
        {"a": 0.02, "b": 0.03},
        correlations={("a", "b"): 0.4},
    )
    soma = sum(r.component_var.values())
    assert float(soma) == pytest.approx(float(r.var_brl), abs=0.05)


def test_portfolio_sem_volatilidade_para_uma_chave() -> None:
    with pytest.raises(MissingDataError, match="volatilidade"):
        portfolio_parametric_var(
            {"a": Decimal("1"), "b": Decimal("1")}, {"a": 0.02}
        )


def test_portfolio_vazio() -> None:
    with pytest.raises(MissingDataError, match="vazio"):
        portfolio_parametric_var({}, {})


def test_portfolio_historico_alinha_por_data() -> None:
    datas = [INICIO + timedelta(days=i) for i in range(120)]
    a = ReturnSeries("a", tuple(datas), tuple(retornos(120, escala=0.02)))
    b = ReturnSeries("b", tuple(datas), tuple(retornos(120, escala=0.01)))
    r = portfolio_historical_var(
        {"a": Decimal("1000000.00"), "b": Decimal("500000.00")}, {"a": a, "b": b}
    )
    assert r.sample_size == 120
    assert r.var_brl >= 0


def test_portfolio_historico_com_poucas_datas_comuns() -> None:
    datas_a = [INICIO + timedelta(days=i) for i in range(120)]
    datas_b = [INICIO + timedelta(days=i) for i in range(100, 220)]
    a = ReturnSeries("a", tuple(datas_a), tuple(retornos(120)))
    b = ReturnSeries("b", tuple(datas_b), tuple(retornos(120)))
    with pytest.raises(InsufficientSampleError, match="datas comuns"):
        portfolio_historical_var(
            {"a": Decimal("1000000.00"), "b": Decimal("1000000.00")}, {"a": a, "b": b}
        )


def test_portfolio_historico_sem_serie() -> None:
    with pytest.raises(MissingDataError, match="serie historica"):
        portfolio_historical_var({"a": Decimal("1")}, {})


# ------------------------------------------------------- reprodutibilidade
def test_mesmas_entradas_produzem_o_mesmo_numero() -> None:
    """AC-40: sem RNG no caminho, o resultado e identico bit a bit."""
    precos = serie_precos(150)
    serie = log_returns(precos, metric_key="fwd")
    a = historical_var(Decimal("12345678.90"), serie.returns)
    b = historical_var(Decimal("12345678.90"), serie.returns)
    assert (a.var_brl, a.expected_shortfall_brl, a.sample_size) == (
        b.var_brl,
        b.expected_shortfall_brl,
        b.sample_size,
    )
