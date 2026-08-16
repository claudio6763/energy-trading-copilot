"""VaR e Expected Shortfall.

Principal : Simulacao Historica Filtrada (FHS) com volatilidade EWMA.
Challenger: VaR/ES historico puro (sem filtragem), para expor cauda e assimetria.

Decisao explicita variacao ABSOLUTA vs RETORNO LOG: o codigo calcula as duas,
mede qual produz residuo padronizado mais bem-comportado (curtose mais proxima
de 3 e menos autocorrelacao no quadrado) e registra a escolha. Nao se assume
que log-retorno e superior — no PLD, com piso administrativo, frequentemente
nao e.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def vol_ewma(x: np.ndarray, lam: float = 0.94, com_previsao: bool = False):
    """Volatilidade EWMA EX-ANTE.

    v[i] = sigma_{i|i-1}: usa apenas informacao ate i-1 para padronizar x_i.
    Se `com_previsao`, devolve tambem sigma_{T+1|T} — a previsao para o proximo
    periodo, que e o que escala o quantil do VaR. A planilha replica exatamente
    esta convencao em CALC_VAR (coluna vol_h = SQRT(ewma_var da linha anterior)).
    """
    v = np.empty(len(x))
    var = float(np.var(x[: max(20, len(x) // 10)])) if len(x) > 20 else float(np.var(x))
    for i, xi in enumerate(x):
        v[i] = np.sqrt(var)
        var = lam * var + (1 - lam) * xi ** 2
    return (v, float(np.sqrt(var))) if com_previsao else v


def _curtose(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if len(x) < 10 or x.std() == 0:
        return np.nan
    return float(np.mean(((x - x.mean()) / x.std()) ** 4))


def escolher_representacao(serie: pd.Series, lam: float = 0.94) -> dict:
    p = serie.dropna().to_numpy(float)
    abs_ = np.diff(p)
    log_ = np.diff(np.log(np.clip(p, 1e-9, None)))
    res = {}
    for nome, x in (("absoluta", abs_), ("log", log_)):
        v = vol_ewma(x, lam)
        z = x / np.where(v > 0, v, np.nan)
        z = z[np.isfinite(z)]
        arch = float(pd.Series(z ** 2).autocorr(lag=1)) if len(z) > 30 else np.nan
        res[nome] = {"curtose_z": _curtose(z), "autocorr_z2": arch, "n": int(len(z))}
    ka, kl = res["absoluta"]["curtose_z"], res["log"]["curtose_z"]
    aa, al = abs(res["absoluta"]["autocorr_z2"] or 9), abs(res["log"]["autocorr_z2"] or 9)
    score_a = abs((ka or 99) - 3) + 5 * aa
    score_l = abs((kl or 99) - 3) + 5 * al
    res["escolhida"] = "absoluta" if score_a <= score_l else "log"
    res["criterio"] = "menor |curtose(z)-3| + 5*|autocorr(z^2)|"
    return res


def fhs(serie: pd.Series, conf: float = 0.95, horizonte_du: int = 21,
        lam: float = 0.94, representacao: str = "absoluta",
        agregacao: str = "sobreposta", n_sim: int = 20000, seed: int = 42) -> dict:
    """FHS sobre variacoes de PRECO no horizonte.

    PARAMETRO `agregacao` — decisao metodologica que importa muito no PLD:

      "iid"        soma h choques diarios independentes reescalados pela vol atual.
                   Equivale a raiz-de-h. SUPERESTIMA o risco de uma serie com
                   reversao a media, porque ignora que a alta de hoje tende a ser
                   parcialmente desfeita amanha.
      "sobreposta" (padrao) aplica o FHS diretamente sobre variacoes acumuladas de
                   h dias uteis em janelas sobrepostas. Preserva a reversao a media
                   observada, ao custo de menos observacoes independentes.

    O PLD e fortemente revertente (hidrologia + limites administrativos), entao o
    padrao e "sobreposta". A versao "iid" fica disponivel como sensibilidade.
    """
    p = serie.dropna().to_numpy(float)
    if len(p) < 60:
        raise ValueError(f"serie curta demais para VaR (n={len(p)})")
    p0 = float(p[-1])

    def _var1(x):
        return np.diff(x) if representacao == "absoluta" else np.diff(np.log(np.clip(x, 1e-9, None)))

    x1 = _var1(p)
    rng = np.random.default_rng(seed)

    if agregacao == "iid":
        v, vol_prev = vol_ewma(x1, lam, com_previsao=True)
        z = x1 / np.where(v > 0, v, np.nan); z = z[np.isfinite(z)]
        vol_hoje = vol_prev
        soma = z[rng.integers(0, len(z), size=(n_sim, horizonte_du))].sum(axis=1) * vol_hoje
        n_ef = len(z)
    else:
        # variacao acumulada de h dias, em janelas sobrepostas
        if len(x1) <= horizonte_du + 30:
            raise ValueError("serie curta para agregacao sobreposta")
        xh = np.convolve(x1, np.ones(horizonte_du), mode="valid")
        v, vol_prev = vol_ewma(xh, lam, com_previsao=True)
        z = xh / np.where(v > 0, v, np.nan); z = z[np.isfinite(z)]
        vol_hoje = vol_prev
        # Quantil EMPIRICO exato: com agregacao sobreposta o bootstrap so adiciona
        # ruido de simulacao sobre a mesma distribuicao. A versao exata e reprodutivel
        # e e a que a planilha reproduz com PERCENTILE().
        soma = np.sort(z) * vol_hoje
        n_ef = len(z)

    pf = p0 + soma if representacao == "absoluta" else p0 * np.exp(soma)
    if agregacao != "iid":
        # amostra auxiliar para o histograma de PnL, sem afetar o quantil
        pf_hist = p0 * np.exp(z[rng.integers(0, len(z), size=n_sim)] * vol_hoje) \
            if representacao != "absoluta" else p0 + z[rng.integers(0, len(z), size=n_sim)] * vol_hoje
    dp = pf - p0
    q = float(np.quantile(dp, 1 - conf))
    es = float(dp[dp <= q].mean())
    q_choque = float(np.quantile(soma, 1 - conf))
    es_choque = float(soma[soma <= q_choque].mean())
    return {"q_choque": q_choque, "es_choque": es_choque,
            "metodo": f"FHS ({agregacao}) com vol EWMA e bootstrap de residuos padronizados",
            "agregacao": agregacao, "representacao": representacao, "conf": conf,
            "horizonte_du": horizonte_du, "lambda": lam, "n_obs": int(n_ef), "preco_ref": p0,
            "vol_ewma_1d": float(vol_ewma(x1, lam)[-1]), "vol_ewma_h": vol_hoje,
            "var_preco": abs(q), "es_preco": abs(es),
            "q_baixo": q, "q_alto": float(np.quantile(dp, conf)),
            "p5": float(np.quantile(pf, 0.05)), "p50": float(np.quantile(pf, 0.50)),
            "p95": float(np.quantile(pf, 0.95)),
            "amostra_pf": (pf_hist if agregacao != "iid" else pf)}


def meia_vida_reversao(serie: pd.Series) -> float:
    """Meia-vida de reversao a media por AR(1). Justifica a escolha de agregacao."""
    p = np.log(np.clip(serie.dropna().to_numpy(float), 1e-9, None))
    x, y = p[:-1], p[1:]
    X = np.column_stack([np.ones(len(x)), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    phi = float(b[1])
    return float(np.log(2) / -np.log(phi)) if 0 < phi < 1 else float("inf")


def historico(serie: pd.Series, conf: float = 0.95, horizonte_du: int = 21,
              representacao: str = "absoluta") -> dict:
    p = serie.dropna().to_numpy(float)
    x = np.diff(p) if representacao == "absoluta" else np.diff(np.log(np.clip(p, 1e-9, None)))
    # sobreposicao de janelas: variacao acumulada em `horizonte_du`
    if len(x) <= horizonte_du:
        raise ValueError("serie curta para VaR historico no horizonte pedido")
    acum = np.convolve(x, np.ones(horizonte_du), mode="valid")
    p0 = float(p[-1])
    dp = acum if representacao == "absoluta" else p0 * (np.exp(acum) - 1)
    q = float(np.quantile(dp, 1 - conf))
    es = float(dp[dp <= q].mean())
    return {"metodo": "Historico simples (janelas sobrepostas)", "conf": conf,
            "horizonte_du": horizonte_du, "representacao": representacao,
            "n_obs": int(len(dp)), "var_preco": abs(q), "es_preco": abs(es)}


def var_posicao(var_preco: float, mwm: float, horas: float, direcao: int) -> float:
    """VaR em R$ da posicao. |direcao| nao altera o modulo do VaR simetrico,
    mas mantemos o argumento para explicitar o mapeamento."""
    return abs(var_preco) * abs(mwm) * horas


def pnl(direcao: int, mwm: float, horas: float, p_entrada: float, p_saida: float) -> float:
    return direcao * mwm * horas * (p_saida - p_entrada)


def var_forward(retornos: pd.Series, preco_ref: float, conf: float = 0.95,
                lam: float = 0.90, horizonte_meses: float = 1.0) -> dict:
    """VaR de uma posicao A TERMO, sobre os log-retornos do proprio forward.

    Metodo principal: DELTA-NORMAL com volatilidade EWMA. Escolhido — e nao o
    historico — porque a serie de termo reconstruida e mensal e curta: estimar um
    quantil de 5% com poucas dezenas de observacoes e menos confiavel do que
    estimar uma volatilidade e aplicar o quantil normal. O historico entra como
    challenger, e a diferenca entre os dois mede o custo da hipotese de
    normalidade.
    """
    r = pd.Series(retornos).dropna().to_numpy(float)
    if len(r) < 12:
        raise ValueError(f"serie de forward curta demais para VaR (n={len(r)})")

    # Recursao EWMA IDENTICA a da planilha (aba CALC_FWD, colunas T/U):
    #   var_1 = r_1^2
    #   var_i = lambda*var_{i-1} + (1-lambda)*r_i^2
    #   vol ex-ante de r_i = sqrt(var_{i-1});  previsao = sqrt(var_n)
    # Inicializacao diferente entre as duas implementacoes produzia ~5% de
    # divergencia na volatilidade, que a aba CROSSCHECK acusou.
    var = r[0] ** 2
    v = np.empty(len(r)); v[0] = np.nan
    for i in range(1, len(r)):
        v[i] = np.sqrt(var)
        var = lam * var + (1 - lam) * r[i] ** 2
    vol_prev = float(np.sqrt(var))
    z = r[1:] / np.where(v[1:] > 0, v[1:], np.nan)
    z = z[np.isfinite(z)]
    sigma_h = vol_prev * np.sqrt(horizonte_meses)

    from math import erf, sqrt
    def _ppf(p):                       # inversa da normal padrao, sem scipy
        a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
             1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
        b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
             6.680131188771972e+01, -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
        dd = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
              3.754408661907416e+00]
        pl = 0.02425
        if p < pl:
            q = sqrt(-2 * np.log(p))
            return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((dd[0]*q+dd[1])*q+dd[2])*q+dd[3])*q+1)
        if p > 1 - pl:
            return -_ppf(1 - p)
        q = p - 0.5; rr = q * q
        return (((((a[0]*rr+a[1])*rr+a[2])*rr+a[3])*rr+a[4])*rr+a[5])*q / \
               (((((b[0]*rr+b[1])*rr+b[2])*rr+b[3])*rr+b[4])*rr+1)

    zq = _ppf(1 - conf)
    var_preco = abs(preco_ref * (np.exp(zq * sigma_h) - 1.0))
    dens = np.exp(-0.5 * zq ** 2) / np.sqrt(2 * np.pi)
    z_es = -dens / (1 - conf)
    es_preco = abs(preco_ref * (np.exp(z_es * sigma_h) - 1.0))

    q_hist = float(np.quantile(r, 1 - conf))
    var_hist = abs(preco_ref * (np.exp(q_hist * np.sqrt(horizonte_meses)) - 1.0))
    cauda = r[r <= q_hist]
    es_hist = abs(preco_ref * (np.exp(cauda.mean() * np.sqrt(horizonte_meses)) - 1.0)) \
        if len(cauda) else var_hist

    return {"metodo": "Delta-normal com vol EWMA sobre o forward reconstruido",
            "fator_risco": "preco a termo do proprio strip (mark-to-market walk-forward)",
            "conf": conf, "lambda": lam, "horizonte_meses": horizonte_meses,
            "n_obs": int(len(r)), "vol_ewma_mensal": float(vol_prev),
            "vol_horizonte": float(sigma_h), "z_quantil": float(zq),
            "preco_ref": float(preco_ref),
            "var_preco": float(var_preco), "es_preco": float(es_preco),
            "var_preco_hist": float(var_hist), "es_preco_hist": float(es_hist),
            "quantil_hist": float(q_hist),
            "curtose": float(pd.Series(r).kurtosis()),
            "amostra_ret": r, "vol_serie": v}


# --------------------------------------------------------------------------
# VaR sobre o FATOR DE NIVEL, com amortecimento de Samuelson
# --------------------------------------------------------------------------
def fator_nivel(flat: pd.DataFrame, fatores: pd.Series) -> pd.Series:
    """Serie do nivel dessazonalizado: flat(m) / fator_sazonal(mes(m)).

    Este e o fator de risco de um contrato a termo. O comprador de Out/26 nao
    corre risco da sazonalidade de outubro — ela e conhecida e ja esta no preco.
    O que ele corre e o risco de o NIVEL do periodo se deslocar.
    """
    d = flat.sort_values("mes_ref")
    f = d.mes_ref.dt.month.map(fatores).astype(float)
    return pd.Series((d.flat.to_numpy(float) / f.to_numpy()), index=d.mes_ref.to_numpy())


def var_nivel(flat: pd.DataFrame, fatores: pd.Series, precos: pd.Series,
              corte: pd.Timestamp, conf: float = 0.95,
              lam: float = 0.90, piso_vol: float | None = None) -> dict:
    """VaR a termo por vertice: vol do NIVEL amortecida ate a entrega.

    POR QUE NAO USAR O BACKCAST DO PROPRIO MODELO
    ---------------------------------------------
    O backcast remarca o strip com o nivel JA SUAVIZADO por uma EWMA de 6 meses.
    Uma media exponencial nao pula: o que ela mede e a volatilidade do proprio
    suavizador, nao a do mercado. Medido nesta base, o suavizador corta cerca de
    87% da volatilidade do nivel, e o VaR que sai dali e irreal — R$ 6/MWh sobre
    um preco de R$ 244, com cenarios publicos que abrem de R$ 70 a R$ 302.

    O QUE ENTRA NO LUGAR
    --------------------
    1. Volatilidade do nivel dessazonalizado, sem suavizacao — o choque de fato.
    2. Amortecimento de Samuelson: um choque de hoje reverte parcialmente antes
       da entrega, entao o forward longo balanca menos que o curto.
           vol_fwd(T) = vol_nivel x exp(-kappa x T)
       com kappa estimado do AR(1) do proprio nivel e T em meses ate o fim da
       entrega. Isso produz uma estrutura a termo de volatilidade DECRESCENTE,
       que e o comportamento observado em qualquer mercado de energia.
    3. VaR lognormal por vertice: VaR = P x (1 - exp(-z x vol_fwd)).

    O resultado NAO e uma opiniao: kappa e vol saem do historico e o unico juizo
    declarado e usar o fim do mes de entrega como T.
    """
    x = np.log(fator_nivel(flat, fatores).to_numpy(float))
    x = x[np.isfinite(x)]
    if len(x) < 24:
        raise ValueError(f"historico curto demais para o VaR de nivel (n={len(x)})")
    r = np.diff(x)

    # vol EWMA do nivel (mesma recursao da planilha)
    var_e = r[0] ** 2
    for i in range(1, len(r)):
        var_e = lam * var_e + (1 - lam) * r[i] ** 2
    vol_ewma = float(np.sqrt(var_e))
    vol_amostral = float(np.std(r, ddof=1))
    # A EWMA persegue o regime recente; a amostral e mais estavel. O piso entre as
    # duas evita que uma sequencia calma de poucos meses zere o risco.
    vol = max(vol_ewma, vol_amostral) if piso_vol is None else max(vol_ewma, piso_vol)

    xc = x - x.mean()
    phi = float(np.polyfit(xc[:-1], xc[1:], 1)[0])
    phi = min(max(phi, 1e-6), 0.999999)
    kappa = -np.log(phi)
    meia_vida = np.log(2) / kappa

    z = _ppf_normal(conf)
    linhas = []
    for m, p in zip(precos.index, precos.to_numpy(float)):
        m = pd.Timestamp(m)
        fim = m + pd.offsets.MonthEnd(0)
        T = max((fim - pd.Timestamp(corte)).days / 30.44, 0.5)
        amort = float(np.exp(-kappa * T))
        vol_f = vol * amort
        linhas.append({"mes_ref": m, "T_meses": T, "amortecimento": amort,
                       "vol_fwd_mensal": vol_f, "preco": p,
                       "var_rs_mwh": float(p * (1 - np.exp(-z * vol_f))),
                       "es_rs_mwh": float(p * (1 - np.exp(-vol_f * _es_z(conf))))})
    tab = pd.DataFrame(linhas)
    horas = np.array([pd.Period(m, freq="M").days_in_month * 24 for m in tab.mes_ref], float)
    return {"metodo": "Vol do nivel dessazonalizado com amortecimento de Samuelson",
            "tabela": tab, "amostra_ret": r, "vol_serie": None,
            "horizonte_meses": 1.0, "lambda": lam,
            "vol_horizonte": float(vol), "z_quantil": float(z),
            "preco_ref": float(np.average(tab.preco, weights=horas)),
            "es_preco_hist": float(np.average(tab.es_rs_mwh, weights=horas)),
            "quantil_hist": float(-z * vol),
            "curtose": float(pd.Series(r).kurtosis()),
            "fator_risco": ("nivel dessazonalizado do PLD (flat / fator sazonal), "
                            "amortecido ate a entrega pela reversao do proprio nivel"),
            "var_preco_hist": float(np.average(tab.var_rs_mwh, weights=horas)), "vol_nivel_mensal": vol, "vol_ewma": vol_ewma,
            "vol_amostral": vol_amostral, "phi": phi, "kappa": kappa,
            "meia_vida_nivel_meses": float(meia_vida), "n_obs": int(len(r)), "conf": conf,
            "var_preco": float(np.average(tab.var_rs_mwh, weights=horas)),
            "es_preco": float(np.average(tab.es_rs_mwh, weights=horas))}


def _ppf_normal(p: float) -> float:
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    dd = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
          3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = np.sqrt(-2 * np.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((dd[0]*q+dd[1])*q+dd[2])*q+dd[3])*q+1)
    if p > ph:
        q = np.sqrt(-2 * np.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((dd[0]*q+dd[1])*q+dd[2])*q+dd[3])*q+1)
    q = p - 0.5
    r2 = q * q
    return (((((a[0]*r2+a[1])*r2+a[2])*r2+a[3])*r2+a[4])*r2+a[5])*q / \
           (((((b[0]*r2+b[1])*r2+b[2])*r2+b[3])*r2+b[4])*r2+1)


def _es_z(conf: float) -> float:
    """z do Expected Shortfall normal: phi(z_conf)/(1-conf)."""
    z = _ppf_normal(conf)
    return float(np.exp(-z * z / 2) / np.sqrt(2 * np.pi) / (1 - conf))
