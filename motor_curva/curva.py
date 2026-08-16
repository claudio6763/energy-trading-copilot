"""Montagem da curva: ancora fundamental, sazonal EWMA, combinacao e MVE."""
from __future__ import annotations
import numpy as np
import pandas as pd

from .config import LIMITES_PLD, Rotulo
from . import sazonalidade as sz


def meses_alvo(inicio: pd.Timestamp, fim: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(inicio.to_period("M").to_timestamp(),
                         fim.to_period("M").to_timestamp(), freq="MS")


def aplicar_limites(precos: pd.Series, meses: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    """Aplica piso/teto estrutural do PLD. Devolve (serie, flag_de_truncamento)."""
    out, flag = [], []
    for p, m in zip(precos, meses):
        lim = LIMITES_PLD.get(int(m.year))
        if not lim:
            out.append(p); flag.append("sem_limite_publicado"); continue
        q = min(max(p, lim["min"]), lim["max_estrutural"])
        out.append(q)
        flag.append("piso" if q > p else ("teto" if q < p else ""))
    return pd.Series(out, index=precos.index), pd.Series(flag, index=precos.index)


# ---------------------------------------------------------------- fundamental
def ancora_fundamental(cmo: pd.DataFrame | None, alvo: pd.DatetimeIndex,
                       submercado: str) -> tuple[pd.Series, dict]:
    """Ancora fundamental a partir de CMO OFICIAL PUBLICADO.

    DISTINCAO CRITICA, descoberta durante o desenvolvimento e mantida explicita:

      * CMO semanal do ONS e REALIZADO. Cobre o passado e, no maximo, a semana
        operativa corrente. NAO projeta meses futuros.
      * O CMO por ESTAGIO FUTURO existe, mas vive dentro dos decks/saidas do
        DECOMP e do NEWAVE. Sem parsear o deck, nao ha ancora fundamental para
        o horizonte a frente.

    Portanto: se todos os meses-alvo forem posteriores ao ultimo CMO publicado,
    esta funcao devolve NaN e status 'indisponivel_para_horizonte_futuro'. Isso
    NAO e uma falha do codigo: e a recusa a usar CMO passado como se fosse
    projecao. O peso da combinacao migra integralmente para o componente
    sazonal e o fato fica declarado na Entrega 2.
    """
    info = {"rotulo": Rotulo.CALCULADO,
            "base": "CMO semanal ONS (saida publicada da cadeia NEWAVE/DECOMP)"}
    if cmo is None or len(cmo) == 0:
        info["status"] = "indisponivel"
        info["motivo"] = ("CMO semanal do ONS nao baixado ou nao parseado; componente "
                          "fundamental ausente e declarado.")
        return pd.Series(np.nan, index=alvo), info

    c = cmo[cmo.submercado == submercado].copy()
    if c.empty:
        info["status"] = "indisponivel"
        info["motivo"] = f"sem CMO para o submercado {submercado}"
        return pd.Series(np.nan, index=alvo), info

    c["mes_ref"] = pd.to_datetime(c.data).values.astype("datetime64[M]")
    m = c.groupby("mes_ref").valor.mean()
    ultimo = m.index.max()
    serie = pd.Series([m.get(x, np.nan) for x in alvo], index=alvo)

    if serie.notna().sum() == 0:
        info["status"] = "indisponivel_para_horizonte_futuro"
        info["ultimo_cmo"] = str(pd.Timestamp(ultimo).date())
        info["motivo"] = (
            f"o CMO publicado vai ate {pd.Timestamp(ultimo):%m/%Y} e todos os meses-alvo sao "
            f"posteriores. CMO realizado nao e projecao — usar seria erro metodologico. "
            f"Para ter ancora fundamental a frente e preciso extrair o CMO por estagio dos "
            f"decks do DECOMP/NEWAVE (ver src/decks.py).")
        return serie, info

    info["status"] = "ok"
    info["meses_com_dado"] = int(serie.notna().sum())
    info["ultimo_cmo"] = str(pd.Timestamp(ultimo).date())
    info["obs"] = ("Apenas meses ja cobertos por CMO publicado recebem peso fundamental; "
                   "nos demais o peso migra para o componente sazonal.")
    return serie, info


# ------------------------------------------------------------------- sazonal
def curva_sazonal(flat: pd.DataFrame, ref: pd.Timestamp, meia_vida: int,
                  alvo: pd.DatetimeIndex, janela_meses: int, sigma: float,
                  winsor, mv_nivel: float = 6.0) -> tuple[pd.Series, pd.DataFrame, dict]:
    tab, diag = sz.fatores_sazonais(flat, ref, meia_vida, janela_meses, sigma, winsor)
    prev = sz.prever(flat, tab, ref, alvo, mv_nivel)
    return pd.Series(prev.preco.to_numpy(), index=alvo), tab, diag


# --------------------------------------------------------------- combinacao
def peso_por_backtest(flat: pd.DataFrame, cmo: pd.DataFrame | None, submercado: str,
                      meia_vida: int, janela_meses: int, sigma: float, winsor,
                      horizonte: int = 3, n_origens: int = 15) -> tuple[float, pd.DataFrame]:
    """Escolhe w (peso do fundamental) minimizando RMSE fora da amostra."""
    d = flat.sort_values("mes_ref").reset_index(drop=True)
    origens = list(d.mes_ref.iloc[-(n_origens + horizonte):-horizonte])
    grade = np.round(np.arange(0, 1.01, 0.1), 2)
    linhas = []
    for o in origens:
        hist = d[d.mes_ref <= o]
        if len(hist) < 18:
            continue
        alvo = d[(d.mes_ref > o) & (d.mes_ref <= o + pd.DateOffset(months=horizonte))]
        if alvo.empty:
            continue
        idx = pd.DatetimeIndex(alvo.mes_ref)
        try:
            s, _, _ = curva_sazonal(hist, o, meia_vida, idx, janela_meses, sigma, winsor)
        except Exception:
            continue
        f, _ = ancora_fundamental(cmo[cmo.data <= o.date()] if cmo is not None and not cmo.empty else None,
                                  idx, submercado)
        for w in grade:
            ww = np.where(f.notna(), w, 0.0)
            mix = ww * f.fillna(0).to_numpy() + (1 - ww) * s.to_numpy()
            for k, mes in enumerate(idx):
                linhas.append({"w": w, "origem": o, "mes_ref": mes,
                               "real": float(alvo.flat.iloc[k]), "prev": float(mix[k])})
    bt = pd.DataFrame(linhas)
    if bt.empty:
        return 0.0, bt
    bt["erro"] = bt.prev - bt.real
    res = bt.groupby("w").agg(RMSE=("erro", lambda s: float(np.sqrt(np.mean(s ** 2)))),
                              MAE=("erro", lambda s: float(np.mean(np.abs(s)))),
                              vies=("erro", "mean"), n=("erro", "size")).reset_index()
    melhor = float(res.sort_values("RMSE").w.iloc[0])
    return melhor, res.sort_values("w").reset_index(drop=True)


# --------------------------------------------------------------------- MVE
def proxy_mve(mve: pd.DataFrame, submercado: str, alvo: pd.DatetimeIndex,
              dias_recencia: int = 365, montante_min: float = 0.0) -> tuple[pd.DataFrame, dict]:
    """Filtra negocios comparaveis. Sem comparabilidade -> devolve vazio e diz por que."""
    info = {"rotulo": Rotulo.PROXY, "criterio": "submercado, vigencia sobreposta ao alvo, recencia"}
    if mve is None or mve.empty:
        info["status"] = "sem_dado"
        info["motivo"] = "dataset MVE nao disponivel ou sem coluna de preco reconhecida"
        return pd.DataFrame(), info
    d = mve.copy()
    if d.submercado.notna().any():
        d = d[(d.submercado == submercado) | d.submercado.isna()]
    if d.data_negociacao.notna().any():
        lim = d.data_negociacao.max() - pd.Timedelta(days=dias_recencia)
        d = d[d.data_negociacao >= lim]
    if d.vigencia_ini.notna().any() and d.vigencia_fim.notna().any():
        ini, fim = alvo.min(), alvo.max() + pd.offsets.MonthEnd(0)
        d = d[(d.vigencia_ini <= fim) & (d.vigencia_fim >= ini)]
    if montante_min and d.montante.notna().any():
        d = d[d.montante.fillna(0) >= montante_min]
    info["status"] = "ok" if len(d) else "sem_comparavel"
    info["n_negocios"] = int(len(d))
    if len(d):
        pesos = d.montante.fillna(1.0).clip(lower=1e-9)
        info["preco_medio_ponderado"] = float(np.average(d.preco, weights=pesos))
        info["preco_mediano"] = float(d.preco.median())
        info["montante_total"] = float(d.montante.fillna(0).sum())
    else:
        info["motivo"] = ("sem negocio publico comparavel em produto/vigencia/submercado -> "
                          "recomendacao sera CONDICIONAL, com preco limite de entrada")
    return d, info


# ------------------------------------------------------- backcast do forward
def backcast_forward(flat: pd.DataFrame, alvo: pd.DatetimeIndex, meia_vida: int,
                     janela_meses: int, sigma: float, winsor,
                     n_origens: int = 60, mv_nivel: float = 6.0) -> pd.DataFrame:
    """Reconstroi o valor a termo DA MESMA POSICAO em cada data passada.

    POR QUE ISTO E O FATOR DE RISCO CERTO
    -------------------------------------
    O risco de uma posicao a termo em Ago-Dez/26 nao e a volatilidade do PLD spot.
    E a volatilidade do PRECO A TERMO daquele periodo de entrega — o que o mercado
    marcaria a mercado a cada dia. Spot oscila muito mais que termo (reversao a
    media, piso e teto administrativos), entao VaR calculado sobre spot superestima
    grosseiramente o risco de carregar um termo.

    Nao existe serie forward publica no Brasil. A reconstrucao honesta e: em cada
    origem t, avaliar ESTE MESMO strip de entrega usando exclusivamente dados <= t.
    A serie resultante e o mark-to-market historico da posicao segundo o proprio
    modelo — walk-forward, sem vazamento.

    LIMITACAO QUE PRECISA SER DECLARADA
    -----------------------------------
    O nivel do modelo e uma funcao SUAVIZADA do spot realizado. Um forward de
    verdade reprecifica com expectativa — previsao meteorologica, revisao de ENA,
    mudanca de FCF — e se move mais do que uma media exponencial de realizados.
    Portanto a volatilidade medida aqui e um PISO da volatilidade verdadeira do
    termo, e o VaR dela derivado e otimista.

    E por isso que o dimensionamento NAO se apoia so neste VaR: ele e cruzado com
    (i) um teto de liquidez e (ii) a perda no cenario hidrologico adverso carregado
    ate a entrega, e o VaR sobre spot e reportado como TETO. A posicao fica na menor
    das restricoes.

    Devolve [origem, fv, ln_fv, ret] com ret = log-retorno mensal do termo.
    """
    from . import sazonalidade as sz
    d = flat.sort_values("mes_ref").reset_index(drop=True)
    tab_ref, _ = sz.fatores_sazonais(d, pd.Timestamp(d.mes_ref.max()), meia_vida,
                                     janela_meses, sigma, winsor)
    nivel_col = sz.nivel_ewma(d, tab_ref, mv_nivel)      # calculado uma unica vez
    origens = list(d.mes_ref.iloc[-n_origens:]) if n_origens else list(d.mes_ref)
    horas = np.array([pd.Period(m, freq="M").days_in_month * 24 for m in alvo], float)
    linhas = []
    for o in origens:
        hist = d[d.mes_ref <= o]
        if len(hist) < 18:
            continue
        try:
            # SEM winsorizacao no backcast: a coluna winsorizada e zerada fora da
            # janela corrente de 24 meses, o que impediria reestimar fatores em
            # origens antigas. A planilha faz igual, usando o desvio bruto.
            tab, _ = sz.fatores_sazonais(hist, o, meia_vida, janela_meses, sigma, None)
            prev = sz.prever(hist, tab, o, alvo, mv_nivel, nivel_serie=nivel_col)
        except Exception:
            continue
        linhas.append({"origem": o,
                       "fv": float(np.average(prev.preco.to_numpy(), weights=horas))})
    out = pd.DataFrame(linhas)
    if out.empty:
        return out
    out["ln_fv"] = np.log(out.fv)
    out["ret"] = out.ln_fv.diff()
    return out
