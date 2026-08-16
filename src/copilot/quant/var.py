"""VaR: parametrico, EWMA, historico e de portfolio.

Tudo deterministico e em stdlib. `statistics.NormalDist` da o quantil normal com
precisao de maquina, sem NumPy/SciPy — o que mantem o motor reproduzivel bit a
bit e o nucleo com quatro dependencias (ADR-010).

**Convencao de sinal.** VaR e sempre um numero **positivo** que representa perda.
Exposicao entra assinada (comprado +, vendido -): e isso que faz posicoes opostas
se compensarem no portfolio em vez de somarem risco.

**Definicao operacional adotada** (premissa PR-03, enquanto a duvida D-01 nao e
respondida): 95% de confianca, horizonte de 21 dias uteis, portfolio consolidado,
retornos logaritmicos diarios. Confianca e horizonte sao sempre explicitos no
resultado — nunca implicitos.

**Escalonamento por horizonte.** `sigma_h = sigma_diario * sqrt(h)`, a regra da
raiz do tempo. Vale sob retornos i.i.d.; e uma aproximacao declarada, nao uma
verdade. Em mercado de energia com sazonalidade forte ela subestima cauda — por
isso existe o add-on de risco de modelo (`quant.addons`).

Amostra curta e dado faltante **nunca** viram numero fraco: viram excecao.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from statistics import NormalDist, fmean, stdev
from typing import Mapping, Sequence

from copilot.common.enums import QuantFunction
from copilot.common.errors import InsufficientSampleError, MissingDataError

MONEY = Decimal("0.01")

#: Premissa PR-03. Sempre carregada no resultado, nunca escondida.
DEFAULT_CONFIDENCE = Decimal("0.95")
DEFAULT_HORIZON_DAYS = 21

#: Minimo de retornos para estimar volatilidade parametrica.
MIN_SAMPLE_PARAMETRIC = 20
#: Minimo para VaR historico: o percentil de 5% precisa de cauda povoada.
MIN_SAMPLE_HISTORICAL = 60
#: Fator de decaimento EWMA. 0,94 e o valor RiskMetrics para dado diario.
EWMA_LAMBDA = 0.94
#: Buraco maximo tolerado entre observacoes consecutivas, em dias corridos.
MAX_GAP_DAYS = 7


# ---------------------------------------------------------------------------
# Serie de retornos
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ReturnSeries:
    """Retornos logaritmicos diarios de uma metrica."""

    metric_key: str
    dates: tuple[date, ...]
    returns: tuple[float, ...]

    def __len__(self) -> int:
        return len(self.returns)

    @property
    def by_date(self) -> dict[date, float]:
        return dict(zip(self.dates, self.returns))


def log_returns(
    observations: Sequence[tuple[date, Decimal]],
    *,
    metric_key: str = "",
    max_gap_days: int = MAX_GAP_DAYS,
    min_points: int = 2,
) -> ReturnSeries:
    """Retornos logaritmicos a partir de precos datados.

    Rejeita: datas fora de ordem, datas repetidas, preco nao positivo e buraco
    maior que `max_gap_days`. Buraco na serie e falta de dado, nao continuidade.
    """
    if len(observations) < min_points:
        raise InsufficientSampleError(
            f"{metric_key or 'serie'}: {len(observations)} observacoes, "
            f"minimo {min_points} para calcular retorno.",
            observed=len(observations),
            required=min_points,
        )

    dates: list[date] = []
    rets: list[float] = []
    anterior_data, anterior_preco = observations[0]
    if Decimal(anterior_preco) <= 0:
        raise MissingDataError(
            f"{metric_key or 'serie'}: preco nao positivo em "
            f"{anterior_data.isoformat()}; retorno logaritmico indefinido."
        )

    for atual_data, atual_preco in observations[1:]:
        if atual_data <= anterior_data:
            raise MissingDataError(
                f"{metric_key or 'serie'}: datas fora de ordem ou repetidas "
                f"({anterior_data.isoformat()} -> {atual_data.isoformat()})."
            )
        gap = (atual_data - anterior_data).days
        if gap > max_gap_days:
            raise MissingDataError(
                f"{metric_key or 'serie'}: buraco de {gap} dias entre "
                f"{anterior_data.isoformat()} e {atual_data.isoformat()} "
                f"(maximo tolerado {max_gap_days}). Serie incompleta nao vira retorno."
            )
        if Decimal(atual_preco) <= 0:
            raise MissingDataError(
                f"{metric_key or 'serie'}: preco nao positivo em {atual_data.isoformat()}."
            )
        rets.append(math.log(float(atual_preco) / float(anterior_preco)))
        dates.append(atual_data)
        anterior_data, anterior_preco = atual_data, atual_preco

    return ReturnSeries(metric_key=metric_key, dates=tuple(dates), returns=tuple(rets))


# ---------------------------------------------------------------------------
# Volatilidade
# ---------------------------------------------------------------------------
def sample_volatility(
    returns: Sequence[float], *, min_sample: int = MIN_SAMPLE_PARAMETRIC
) -> float:
    """Desvio-padrao amostral (ddof=1) dos retornos diarios."""
    if len(returns) < min_sample:
        raise InsufficientSampleError(
            f"Volatilidade amostral exige {min_sample} retornos; "
            f"recebidos {len(returns)}.",
            observed=len(returns),
            required=min_sample,
        )
    return stdev(returns)


def ewma_volatility(
    returns: Sequence[float],
    *,
    lam: float = EWMA_LAMBDA,
    min_sample: int = MIN_SAMPLE_PARAMETRIC,
) -> float:
    """Volatilidade EWMA: ``s2_t = lam*s2_{t-1} + (1-lam)*r_{t-1}^2``.

    Semeada com a variancia amostral da primeira metade da serie, para nao
    depender de um unico retorno inicial. Reage mais rapido a mudanca de regime
    que a janela fixa — util em hidrologia, onde o regime vira de uma semana
    para a outra.
    """
    if not 0.0 < lam < 1.0:
        raise ValueError(f"lambda deve estar em (0,1); recebido {lam}.")
    if len(returns) < min_sample:
        raise InsufficientSampleError(
            f"EWMA exige {min_sample} retornos; recebidos {len(returns)}.",
            observed=len(returns),
            required=min_sample,
        )
    metade = max(2, len(returns) // 2)
    var_atual = stdev(returns[:metade]) ** 2
    for r in returns:
        var_atual = lam * var_atual + (1.0 - lam) * (r * r)
    return math.sqrt(var_atual)


def z_score(confidence: Decimal | float = DEFAULT_CONFIDENCE) -> float:
    """Quantil da normal padrao. 95% -> 1,6449; 99% -> 2,3263."""
    c = float(confidence)
    if not 0.5 < c < 1.0:
        raise ValueError(f"Confianca deve estar em (0,5; 1,0); recebida {c}.")
    return NormalDist().inv_cdf(c)


def horizon_factor(horizon_days: int) -> float:
    """Raiz do tempo. Aproximacao declarada — ver docstring do modulo."""
    if horizon_days < 1:
        raise ValueError(f"Horizonte deve ser >= 1 dia; recebido {horizon_days}.")
    return math.sqrt(float(horizon_days))


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class VaRResult:
    """Resultado de VaR. `var_brl` positivo = perda potencial."""

    method: QuantFunction
    var_brl: Decimal
    expected_shortfall_brl: Decimal | None
    confidence: Decimal
    horizon_days: int
    sample_size: int
    sigma_daily: float
    #: Contribuicao de cada posicao (decomposicao de Euler). Soma = `var_brl`.
    component_var: dict[str, Decimal] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def var_daily_brl(self) -> Decimal:
        """VaR de 1 dia implicito, para comparacao entre horizontes."""
        return (self.var_brl / Decimal(str(horizon_factor(self.horizon_days)))).quantize(MONEY)


def _q(value: float) -> Decimal:
    return Decimal(repr(value)).quantize(MONEY)


# ---------------------------------------------------------------------------
# VaR de posicao unica
# ---------------------------------------------------------------------------
def parametric_var(
    exposure_brl: Decimal,
    sigma_daily: float,
    *,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    sample_size: int = 0,
    method: QuantFunction = QuantFunction.VAR_PARAMETRIC,
) -> VaRResult:
    """``VaR = z * sigma_diario * sqrt(h) * |exposicao|``.

    Normal simetrica: o sinal da exposicao nao muda o VaR de uma posicao
    isolada. Ele importa no portfolio.
    """
    if sigma_daily < 0:
        raise ValueError("Volatilidade nao pode ser negativa.")
    z = z_score(confidence)
    escala = z * sigma_daily * horizon_factor(horizon_days)
    var = abs(float(exposure_brl)) * escala
    # ES normal: E[L | L > VaR] = phi(z)/(1-c) * sigma * |E|
    densidade = NormalDist().pdf(z)
    es = abs(float(exposure_brl)) * sigma_daily * horizon_factor(horizon_days) * (
        densidade / (1.0 - float(confidence))
    )
    return VaRResult(
        method=method,
        var_brl=_q(var),
        expected_shortfall_brl=_q(es),
        confidence=Decimal(confidence),
        horizon_days=horizon_days,
        sample_size=sample_size,
        sigma_daily=sigma_daily,
    )


def ewma_var(
    exposure_brl: Decimal,
    returns: Sequence[float],
    *,
    lam: float = EWMA_LAMBDA,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> VaRResult:
    """VaR parametrico com volatilidade EWMA."""
    sigma = ewma_volatility(returns, lam=lam)
    resultado = parametric_var(
        exposure_brl,
        sigma,
        confidence=confidence,
        horizon_days=horizon_days,
        sample_size=len(returns),
        method=QuantFunction.VAR_EWMA,
    )
    return VaRResult(
        method=QuantFunction.VAR_EWMA,
        var_brl=resultado.var_brl,
        expected_shortfall_brl=resultado.expected_shortfall_brl,
        confidence=resultado.confidence,
        horizon_days=resultado.horizon_days,
        sample_size=len(returns),
        sigma_daily=sigma,
        notes=(f"EWMA lambda={lam}",),
    )


def percentile(values: Sequence[float], q: float) -> float:
    """Percentil por interpolacao linear sobre a amostra ordenada.

    Metodo declarado (equivalente ao `linear` do NumPy): posicao ``q*(n-1)``,
    interpolando entre os vizinhos. Explicito porque metodo de percentil muda
    o VaR historico em amostra pequena.
    """
    if not values:
        raise InsufficientSampleError("Percentil de amostra vazia.", observed=0, required=1)
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q deve estar em [0,1]; recebido {q}.")
    ordenados = sorted(values)
    if len(ordenados) == 1:
        return ordenados[0]
    posicao = q * (len(ordenados) - 1)
    inferior = math.floor(posicao)
    superior = math.ceil(posicao)
    if inferior == superior:
        return ordenados[int(posicao)]
    peso = posicao - inferior
    return ordenados[inferior] * (1 - peso) + ordenados[superior] * peso


def historical_var(
    exposure_brl: Decimal,
    returns: Sequence[float],
    *,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    min_sample: int = MIN_SAMPLE_HISTORICAL,
) -> VaRResult:
    """VaR historico: revaloriza a exposicao com cada retorno observado.

    Nao assume normalidade — e por isso que ele e o numero que se leva para a
    mesa quando a cauda importa.
    """
    if len(returns) < min_sample:
        raise InsufficientSampleError(
            f"VaR historico exige {min_sample} retornos para povoar a cauda de "
            f"{float(confidence):.0%}; recebidos {len(returns)}.",
            observed=len(returns),
            required=min_sample,
        )
    fator = horizon_factor(horizon_days)
    exposicao = float(exposure_brl)
    pnl = [exposicao * (math.exp(r * fator) - 1.0) for r in returns]

    corte = percentile(pnl, 1.0 - float(confidence))
    var = max(0.0, -corte)
    cauda = [p for p in pnl if p <= corte]
    es = max(0.0, -fmean(cauda)) if cauda else var

    return VaRResult(
        method=QuantFunction.VAR_HISTORICAL,
        var_brl=_q(var),
        expected_shortfall_brl=_q(es),
        confidence=Decimal(confidence),
        horizon_days=horizon_days,
        sample_size=len(returns),
        sigma_daily=stdev(returns) if len(returns) > 1 else 0.0,
        notes=("percentil linear sobre P&L revalorizado",),
    )


# ---------------------------------------------------------------------------
# VaR de portfolio
# ---------------------------------------------------------------------------
def portfolio_parametric_var(
    exposures: Mapping[str, Decimal],
    sigmas: Mapping[str, float],
    *,
    correlations: Mapping[tuple[str, str], float] | None = None,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> VaRResult:
    """VaR parametrico do portfolio com matriz de correlacao.

    ``sigma_p = sqrt( sum_i sum_j E_i E_j sigma_i sigma_j rho_ij )``

    Exposicoes assinadas: comprado e vendido na mesma metrica se cancelam.
    A decomposicao de Euler devolve a contribuicao de cada posicao, e ela
    **soma exatamente** o VaR total.
    """
    chaves = sorted(exposures)
    if not chaves:
        raise MissingDataError("Portfolio vazio: nao ha o que medir.")
    faltando = [k for k in chaves if k not in sigmas]
    if faltando:
        raise MissingDataError(
            "Sem volatilidade estimada para: " + ", ".join(faltando)
            + ". VaR parcial nao e VaR."
        )

    correlations = correlations or {}

    def rho(a: str, b: str) -> float:
        if a == b:
            return 1.0
        if (a, b) in correlations:
            return correlations[(a, b)]
        if (b, a) in correlations:
            return correlations[(b, a)]
        # Sem correlacao declarada, assume 1,0: o caso conservador.
        return 1.0

    e = {k: float(exposures[k]) for k in chaves}
    # c_i = sum_j E_j sigma_i sigma_j rho_ij
    c = {
        i: sum(e[j] * sigmas[i] * sigmas[j] * rho(i, j) for j in chaves) for i in chaves
    }
    variancia = sum(e[i] * c[i] for i in chaves)
    sigma_p = math.sqrt(max(0.0, variancia))

    z = z_score(confidence)
    fator = horizon_factor(horizon_days)
    var = z * sigma_p * fator

    componentes: dict[str, Decimal] = {}
    if sigma_p > 0:
        for i in chaves:
            componentes[i] = _q(z * fator * e[i] * c[i] / sigma_p)
    else:
        componentes = {i: Decimal("0.00") for i in chaves}

    densidade = NormalDist().pdf(z)
    es = sigma_p * fator * (densidade / (1.0 - float(confidence)))

    notas: list[str] = []
    if not correlations:
        notas.append("correlacao nao declarada: assumida 1,0 (conservador)")

    return VaRResult(
        method=QuantFunction.VAR_PORTFOLIO,
        var_brl=_q(var),
        expected_shortfall_brl=_q(es),
        confidence=Decimal(confidence),
        horizon_days=horizon_days,
        sample_size=len(chaves),
        sigma_daily=sigma_p,
        component_var=componentes,
        notes=tuple(notas),
    )


def portfolio_historical_var(
    exposures: Mapping[str, Decimal],
    series: Mapping[str, ReturnSeries],
    *,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    min_sample: int = MIN_SAMPLE_HISTORICAL,
) -> VaRResult:
    """VaR historico do portfolio sobre datas **comuns** a todas as series.

    Alinhar por data e obrigatorio: somar retornos de dias diferentes inventaria
    diversificacao que nao existe.
    """
    chaves = sorted(exposures)
    if not chaves:
        raise MissingDataError("Portfolio vazio: nao ha o que medir.")
    faltando = [k for k in chaves if k not in series]
    if faltando:
        raise MissingDataError("Sem serie historica para: " + ", ".join(faltando) + ".")

    mapas = {k: series[k].by_date for k in chaves}
    datas_comuns = sorted(set.intersection(*(set(m) for m in mapas.values())))
    if len(datas_comuns) < min_sample:
        raise InsufficientSampleError(
            f"Apenas {len(datas_comuns)} datas comuns as {len(chaves)} series; "
            f"minimo {min_sample}.",
            observed=len(datas_comuns),
            required=min_sample,
        )

    fator = horizon_factor(horizon_days)
    pnl = [
        sum(
            float(exposures[k]) * (math.exp(mapas[k][d] * fator) - 1.0) for k in chaves
        )
        for d in datas_comuns
    ]
    corte = percentile(pnl, 1.0 - float(confidence))
    var = max(0.0, -corte)
    cauda = [p for p in pnl if p <= corte]
    es = max(0.0, -fmean(cauda)) if cauda else var

    return VaRResult(
        method=QuantFunction.VAR_HISTORICAL,
        var_brl=_q(var),
        expected_shortfall_brl=_q(es),
        confidence=Decimal(confidence),
        horizon_days=horizon_days,
        sample_size=len(datas_comuns),
        sigma_daily=stdev(pnl) / abs(sum(float(v) for v in exposures.values()))
        if sum(abs(float(v)) for v in exposures.values()) > 0 and len(pnl) > 1
        else 0.0,
        notes=(f"{len(datas_comuns)} datas comuns as series",),
    )


__all__ = [
    "DEFAULT_CONFIDENCE",
    "DEFAULT_HORIZON_DAYS",
    "EWMA_LAMBDA",
    "MAX_GAP_DAYS",
    "MIN_SAMPLE_HISTORICAL",
    "MIN_SAMPLE_PARAMETRIC",
    "ReturnSeries",
    "VaRResult",
    "ewma_var",
    "ewma_volatility",
    "historical_var",
    "horizon_factor",
    "log_returns",
    "parametric_var",
    "percentile",
    "portfolio_historical_var",
    "portfolio_parametric_var",
    "sample_volatility",
    "z_score",
]
