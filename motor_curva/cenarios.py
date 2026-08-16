"""Regimes hidrologicos a partir de variaveis observaveis (ENA %MLT, EAR %).

Nao usa multiplicador arbitrario. Estima, por minimos quadrados, o efeito do
regime sobre log(preco flat mensal) controlando por mes-calendario:

    log(flat_t) = alpha + sum_m beta_m * D_mes + g_seco*D_seco + g_umido*D_umido

Os multiplicadores de cenario sao exp(g). Se a ordenacao Seco > Base > Umido
nao aparecer, o codigo REPORTA a inversao em vez de forcar.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def classificar(ena: pd.DataFrame, ear: pd.DataFrame, submercado: str,
                q_seco: float = 0.25, q_umido: float = 0.75) -> pd.DataFrame:
    e = ena[ena.submercado == submercado].copy()
    e["mes_ref"] = pd.to_datetime(e.data).values.astype("datetime64[M]")
    ena_m = e.groupby("mes_ref").agg(ena_pct=("pct", "mean"), ena_val=("valor", "mean")).reset_index()

    a = ear[ear.submercado == submercado].copy()
    a["mes_ref"] = pd.to_datetime(a.data).values.astype("datetime64[M]")
    ear_m = a.groupby("mes_ref").agg(ear_pct=("pct", "mean")).reset_index()

    d = ena_m.merge(ear_m, on="mes_ref", how="outer").sort_values("mes_ref")
    if d.ena_pct.notna().sum() < 12:
        raise ValueError("ENA %MLT insuficiente para classificar regimes")

    # o regime combina afluencia do mes com o estoque, que carrega memoria
    z_ena = (d.ena_pct - d.ena_pct.mean()) / d.ena_pct.std(ddof=0)
    z_ear = (d.ear_pct - d.ear_pct.mean()) / d.ear_pct.std(ddof=0) if d.ear_pct.notna().any() else 0.0
    d["indice_hidro"] = 0.65 * z_ena + 0.35 * (z_ear if isinstance(z_ear, pd.Series) else 0.0)
    lo, hi = d.indice_hidro.quantile(q_seco), d.indice_hidro.quantile(q_umido)
    d["regime"] = np.where(d.indice_hidro <= lo, "seco",
                           np.where(d.indice_hidro >= hi, "umido", "base"))
    d["limiar_seco"], d["limiar_umido"] = lo, hi
    return d


def estimar_efeitos(flat: pd.DataFrame, regimes: pd.DataFrame,
                    anos_amostra: int = 6) -> tuple[dict, pd.DataFrame]:
    d = flat.merge(regimes[["mes_ref", "regime", "ena_pct", "ear_pct", "indice_hidro"]],
                   on="mes_ref", how="inner").dropna(subset=["flat", "regime"])
    corte = d.mes_ref.max() - pd.DateOffset(years=anos_amostra)
    d = d[d.mes_ref > corte]
    if len(d) < 24:
        raise ValueError(f"amostra insuficiente para estimar efeito de regime (n={len(d)})")

    y = np.log(d.flat.to_numpy())
    mes = pd.get_dummies(d.mes_ref.dt.month, prefix="m", drop_first=True).to_numpy(float)
    ds = (d.regime == "seco").to_numpy(float).reshape(-1, 1)
    du = (d.regime == "umido").to_numpy(float).reshape(-1, 1)
    X = np.column_stack([np.ones(len(d)), mes, ds, du])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    gl = max(1, len(d) - X.shape[1])
    s2 = float(resid @ resid / gl)
    cov = s2 * np.linalg.pinv(X.T @ X)
    i_s, i_u = X.shape[1] - 2, X.shape[1] - 1
    g_s, g_u = float(beta[i_s]), float(beta[i_u])
    ep_s, ep_u = float(np.sqrt(cov[i_s, i_s])), float(np.sqrt(cov[i_u, i_u]))

    efeitos = {
        "k_seco": float(np.exp(g_s)), "k_umido": float(np.exp(g_u)), "k_base": 1.0,
        "g_seco": g_s, "g_umido": g_u, "ep_seco": ep_s, "ep_umido": ep_u,
        "t_seco": g_s / ep_s if ep_s else np.nan, "t_umido": g_u / ep_u if ep_u else np.nan,
        "n_obs": int(len(d)),
        "n_seco": int(ds.sum()), "n_umido": int(du.sum()),
        "r2": float(1 - resid.var() / y.var()) if y.var() else np.nan,
        "ordenacao_coerente": bool(g_s > 0 > g_u),
        "amostra_de": str(d.mes_ref.min().date()), "amostra_ate": str(d.mes_ref.max().date()),
    }
    return efeitos, d


def estimar_efeitos_residual(flat: pd.DataFrame, regimes: pd.DataFrame,
                             fatores: pd.DataFrame, anos_amostra: int = 6) -> dict:
    """Estimador RESIDUAL — o mesmo que a planilha reproduz em formulas.

    resid_t = ln(flat_t) - nivel_trailing_t - s(mes_t)
    k_regime = exp( media(resid | regime) - media(resid | base) )

    Diferenca para `estimar_efeitos` (MQO com dummies de mes): aqui o efeito de
    mes e removido pelos proprios fatores sazonais ja estimados, em vez de por
    dummies. E menos eficiente estatisticamente, mas e transparente em formula
    de planilha e auditavel celula a celula. Os dois sao reportados lado a lado.
    """
    from .sazonalidade import nivel_trailing
    d = nivel_trailing(flat).dropna(subset=["desvio"])
    d = d.merge(regimes[["mes_ref", "regime"]], on="mes_ref", how="inner")
    d = d[d.mes_ref > d.mes_ref.max() - pd.DateOffset(years=anos_amostra)]
    f = fatores.set_index("mes").log_fator
    d["resid"] = d.desvio - d.mes_ref.dt.month.map(f)
    m = d.groupby("regime").resid.mean()
    base = m.get("base", 0.0)
    return {
        "k_seco": float(np.exp(m.get("seco", base) - base)),
        "k_umido": float(np.exp(m.get("umido", base) - base)),
        "n_seco": int((d.regime == "seco").sum()),
        "n_umido": int((d.regime == "umido").sum()),
        "n_base": int((d.regime == "base").sum()),
        "metodo": "residual (replicado na planilha)",
    }
