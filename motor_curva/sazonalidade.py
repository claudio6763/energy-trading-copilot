"""Componente sazonal com EWMA de calendario + selecao walk-forward.

NAO e um EWMA simples da serie. A estrutura e:
  log(flat_t) = log(nivel_t) + s(mes_t) + ruido
  nivel_t     = media geometrica movel dos ultimos 12 meses (apenas passado)
  s(m)        = media ponderada dos desvios sazonais observados, com dois pesos
                multiplicados:
                  (a) recencia  w_i = exp(-ln2 * idade_dias_i / meia_vida)
                  (b) proximidade de calendario K(d) = exp(-0.5 (d/sigma)^2),
                      d = distancia CIRCULAR em meses entre o mes da observacao
                      e o mes-alvo. Sem o kernel, 24 meses dariam apenas 2
                      observacoes por mes-calendario.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

LN2 = np.log(2.0)


def nivel_trailing(flat: pd.DataFrame, janela: int = 12) -> pd.DataFrame:
    d = flat.sort_values("mes_ref").copy()
    d["log_flat"] = np.log(d.flat)
    # min_periods = janela inteira. Com 6, os primeiros meses ganhavam um nivel
    # estimado com meia amostra e a planilha (que exige COUNT=12) nao reproduzia.
    d["log_nivel"] = d.log_flat.rolling(janela, min_periods=janela).mean()
    d["desvio"] = d.log_flat - d.log_nivel
    return d


def _dist_circular(m1: np.ndarray, m2: int) -> np.ndarray:
    d = np.abs(m1 - m2)
    return np.minimum(d, 12 - d)


def fatores_sazonais(flat: pd.DataFrame, ref: pd.Timestamp, meia_vida_dias: int,
                     janela_meses: int = 24, sigma_meses: float = 0.7,
                     winsor: tuple[float, float] = (0.01, 0.99)) -> tuple[pd.DataFrame, dict]:
    """Devolve (tabela de fatores por mes, diagnostico)."""
    d = nivel_trailing(flat).dropna(subset=["desvio"])
    d = d[d.mes_ref <= ref]
    corte = ref - pd.DateOffset(months=janela_meses)
    amostra = d[d.mes_ref > corte].copy()
    if len(amostra) < 12:
        amostra = d.tail(max(12, len(d) // 2)).copy()

    # robustez a spikes: winsoriza e REGISTRA quem foi tocado (nao apaga em silencio).
    # winsor=None desliga — usado no backcast, onde a planilha trabalha com o desvio
    # bruto porque a coluna winsorizada e zerada fora da janela corrente.
    if winsor:
        lo, hi = amostra.desvio.quantile(winsor[0]), amostra.desvio.quantile(winsor[1])
        tocados = amostra[(amostra.desvio < lo) | (amostra.desvio > hi)][["mes_ref", "desvio"]]
        amostra["desvio_w"] = amostra.desvio.clip(lo, hi)
    else:
        tocados = amostra.iloc[0:0][["mes_ref", "desvio"]]
        amostra["desvio_w"] = amostra.desvio

    idade = (ref - amostra.mes_ref).dt.days.to_numpy()
    w_rec = np.exp(-LN2 * idade / float(meia_vida_dias))
    meses = amostra.mes_ref.dt.month.to_numpy()

    linhas = []
    for m in range(1, 13):
        k = np.exp(-0.5 * (_dist_circular(meses, m) / sigma_meses) ** 2)
        w = w_rec * k
        if w.sum() <= 0:
            linhas.append({"mes": m, "log_fator": 0.0, "n_efetivo": 0.0})
            continue
        s = float(np.sum(w * amostra.desvio_w.to_numpy()) / w.sum())
        n_ef = float(w.sum() ** 2 / np.sum(w ** 2))          # tamanho amostral efetivo
        linhas.append({"mes": m, "log_fator": s, "n_efetivo": n_ef})

    tab = pd.DataFrame(linhas)
    tab["log_fator"] -= tab.log_fator.mean()                  # nivel medio anual preservado
    tab["fator"] = np.exp(tab.log_fator)
    tab["fator"] = tab.fator / tab.fator.mean()               # media aritmetica = 1
    diag = {
        "meia_vida_dias": meia_vida_dias,
        "janela_meses": janela_meses,
        "sigma_kernel_meses": sigma_meses,
        "n_observacoes": int(len(amostra)),
        "n_efetivo_medio": float(tab.n_efetivo.mean()),
        "peso_ultimos_12m": float(w_rec[(ref - amostra.mes_ref).dt.days <= 365].sum() / w_rec.sum()),
        "spikes_winsorizados": int(len(tocados)),
        "spikes_detalhe": tocados.assign(mes_ref=tocados.mes_ref.dt.strftime("%Y-%m")).to_dict("records"),
        "amplitude_fator": float(tab.fator.max() - tab.fator.min()),
    }
    return tab, diag


def nivel_ewma(flat: pd.DataFrame, tab: pd.DataFrame, meia_vida_meses: float = 6.0
               ) -> pd.DataFrame:
    """Nivel dessazonalizado por EWMA — o 'preco de tela' implicito do modelo.

    POR QUE TROCAR A MEDIA MOVEL DE 12 MESES
    ----------------------------------------
    A media movel de 12 meses e lisa por construcao: cada mes novo muda o nivel em
    apenas 1/12 do choque. Isso e adequado para separar sazonalidade, mas e um
    pessimo 'nivel corrente' — e, ao remarcar a posicao a mercado no passado, gera
    uma serie de forward artificialmente estavel e um VaR irrealisticamente baixo.

    O nivel usado para PRECIFICAR passa a ser um EWMA do log do flat dessazonalizado:
        x_t     = ln(flat_t) - s(mes_t)
        nivel_t = alpha*x_t + (1-alpha)*nivel_{t-1},  alpha = 1 - 0.5^(1/meia_vida)

    Sem circularidade: s vem dos desvios em relacao a media movel (coluna separada).
    """
    d = flat.sort_values("mes_ref").copy()
    f = tab.set_index("mes").log_fator
    d["x_deseason"] = np.log(d.flat) - d.mes_ref.dt.month.map(f)
    alpha = 1.0 - 0.5 ** (1.0 / float(meia_vida_meses))
    niveis, atual = [], None
    for x in d.x_deseason:
        atual = x if atual is None else alpha * x + (1 - alpha) * atual
        niveis.append(atual)
    d["nivel_ewma"] = niveis
    d["alpha"] = alpha
    return d


def prever(flat: pd.DataFrame, tab: pd.DataFrame, ref: pd.Timestamp,
           meses_alvo: pd.DatetimeIndex, meia_vida_nivel: float = 6.0,
           nivel_serie: pd.DataFrame | None = None) -> pd.DataFrame:
    """Projeta usando o nivel observado em `ref` e os fatores sazonais."""
    # `nivel_serie` permite injetar a coluna de nivel calculada UMA unica vez.
    # A planilha faz assim: o nivel e uma recursao EWMA sobre o log flat
    # dessazonalizado com a forma sazonal da data de referencia. Recalcular a forma
    # dentro da recursao a cada origem exigiria uma recursao por origem, inviavel em
    # celula. O efeito e de segunda ordem porque a forma sazonal e estavel, e a
    # magnitude aparece na sensibilidade a meia-vida. Aproximacao DECLARADA.
    d = nivel_serie if nivel_serie is not None else nivel_ewma(flat, tab, meia_vida_nivel)
    hist = d[d.mes_ref <= ref]
    if hist.empty:
        raise ValueError("sem nivel disponivel na origem")
    log_nivel = float(hist.nivel_ewma.iloc[-1])
    # BUG CORRIGIDO: usar `fator` (normalizado para media aritmetica 1) e nao
    # exp(log_fator). Como exp() e convexo, a media de exp(log_fator) e > 1 (Jensen),
    # e usar log_fator inflava a curva inteira em ~1,5%. A normalizacao aritmetica e
    # justamente o que preserva o nivel medio anual, conforme documentado.
    f = tab.set_index("mes").fator
    nivel = float(np.exp(log_nivel))
    return pd.DataFrame({
        "mes_ref": meses_alvo,
        "preco": [nivel * float(f.loc[m.month]) for m in meses_alvo],
    })


def walk_forward(flat: pd.DataFrame, meias_vidas: tuple[int, ...],
                 horizonte_meses: int = 3, n_origens: int = 18,
                 janela_meses: int = 24, sigma_meses: float = 0.7) -> pd.DataFrame:
    """Validacao sem informacao futura: em cada origem so usa dados <= origem."""
    d = flat.sort_values("mes_ref").reset_index(drop=True)
    origens = d.mes_ref.iloc[-(n_origens + horizonte_meses):-horizonte_meses]
    linhas = []
    for hl in meias_vidas:
        for o in origens:
            hist = d[d.mes_ref <= o]
            if len(hist) < 18:
                continue
            try:
                tab, _ = fatores_sazonais(hist, o, hl, janela_meses, sigma_meses)
                alvo = d[(d.mes_ref > o) & (d.mes_ref <= o + pd.DateOffset(months=horizonte_meses))]
                if alvo.empty:
                    continue
                prev = prever(hist, tab, o, pd.DatetimeIndex(alvo.mes_ref))
                for (_, a), (_, p) in zip(alvo.iterrows(), prev.iterrows()):
                    linhas.append({"meia_vida": hl, "origem": o, "mes_ref": a.mes_ref,
                                   "real": a.flat, "prev": p.preco,
                                   "erro": p.preco - a.flat,
                                   "erro_log": np.log(p.preco) - np.log(a.flat)})
            except Exception:
                continue
    return pd.DataFrame(linhas)


def resumo_walk_forward(wf: pd.DataFrame) -> pd.DataFrame:
    if wf.empty:
        return pd.DataFrame(columns=["meia_vida", "MAE", "RMSE", "vies", "MAE_log", "n"])
    g = wf.groupby("meia_vida").agg(
        MAE=("erro", lambda s: float(np.mean(np.abs(s)))),
        RMSE=("erro", lambda s: float(np.sqrt(np.mean(s ** 2)))),
        vies=("erro", "mean"),
        MAE_log=("erro_log", lambda s: float(np.mean(np.abs(s)))),
        n=("erro", "size"),
    ).reset_index()
    return g.sort_values("RMSE").reset_index(drop=True)
