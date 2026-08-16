# -*- coding: utf-8 -*-
"""Ancora fundamental do InfoPLD, cenarios coerentes e nowcast do IPDO.

    Curva = ancora fundamental + ajuste de nowcast + componente estatistico
            + premio/basis DECLARADO

DISTINCAO QUE NAO PODE SER PERDIDA
----------------------------------
A projecao de PLD da CCEE e a expectativa do PRECO SPOT durante o mes de
entrega. Nao e o preco de um contrato bilateral a termo. Entre as duas ha o
premio de risco a termo, que no Brasil NAO e observavel em fonte publica.
Enquanto nao houver referencia publica comparavel, o premio fica em zero como
PREMISSA EXPLICITA e o resultado se chama fair value fundamental — nunca
cotacao de mercado.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRAJ_ORDEM = ["RNA", "SMAP 2023", "SMAP 2018", "SMAP CFS VE", "SMAP CFS LI"]
# CFS LI e stress meteorologico de curto prazo: horizonte curto por natureza.
TRAJ_CURTO_PRAZO = ["SMAP CFS VE", "SMAP CFS LI"]


# --------------------------------------------------------------- 1. ancora
def matriz_trajetorias(df_info: pd.DataFrame, variavel: str, submercado: str,
                       alvo: pd.DatetimeIndex) -> pd.DataFrame:
    """[mes_ref x trajetoria] para PLD_PROJ_TRAJ, ENA_PROJ_TRAJ ou EARM_PROJ_TRAJ."""
    d = df_info[(df_info.variavel == variavel) & (df_info.submercado == submercado)].copy()
    if d.empty:
        return pd.DataFrame(index=alvo)
    d["mes"] = pd.to_datetime(d.periodo + "-01")
    piv = d.pivot_table(index="mes", columns="cenario", values="valor", aggfunc="last")
    return piv.reindex(alvo)


def ancora_pld(df_info: pd.DataFrame, submercado: str, alvo: pd.DatetimeIndex,
               trajetoria_central: str = "RNA") -> tuple[pd.Series, pd.DataFrame, dict]:
    """Ancora fundamental mensal: projecao oficial de PLD da CCEE.

    Usa a precisao de 2 casas da pagina de resumo onde ela existe (tipicamente o
    mes corrente e os dois seguintes) e o inteiro da tabela de trajetorias no
    restante do horizonte.
    """
    from .parse_infopld import projecao_pld_consolidada
    cons = projecao_pld_consolidada(df_info, submercado)
    cons["mes"] = pd.to_datetime(cons.periodo + "-01")
    piv = cons.pivot_table(index="mes", columns="cenario", values="valor",
                           aggfunc="last").reindex(alvo)
    if trajetoria_central not in piv.columns:
        raise ValueError(f"trajetoria {trajetoria_central} ausente; "
                         f"disponiveis: {list(piv.columns)}")
    serie = piv[trajetoria_central]
    prec = cons[cons.cenario == trajetoria_central].set_index("mes")["precisao"]
    info = {
        "fonte": "InfoPLD — projecao oficial de PLD da CCEE",
        "trajetoria_central": trajetoria_central,
        "documento": cons.documento.iloc[0] if len(cons) else "",
        "paginas": sorted(set(cons.pagina.tolist())) if len(cons) else [],
        "meses_cobertos": int(serie.notna().sum()),
        "meses_alta_precisao": [str(m.date()) for m in prec.index
                                if str(prec.get(m, "")).startswith("2 casas")],
        "natureza": "PROJETADO — expectativa de PLD SPOT no mes de entrega",
        "aviso": ("NAO e preco de contrato bilateral a termo. Falta o premio de "
                  "risco, que nao e observavel em fonte publica."),
    }
    return serie, piv, info


# ------------------------------------------------------------- 2. cenarios
def score_hidrologico(df_info: pd.DataFrame, alvo: pd.DatetimeIndex,
                      submercado_ena: str = "SIN",
                      submercado_earm: str = "SE") -> pd.DataFrame:
    """Score de umidade por trajetoria, sobre TODO o horizonte.

    Nao classifica cenario pelo preco de um mes. Combina, ao longo do alvo:
        - ENA media em %MLT do SIN            (fluxo)
        - EARM media em %EARMmax do SE/CO     (estoque, onde esta a maior parte)
    Ambos padronizados entre as trajetorias e somados com pesos 0,6 e 0,4.
    Score alto = trajetoria umida.
    """
    ena = matriz_trajetorias(df_info, "ENA_PROJ_TRAJ", submercado_ena, alvo)
    earm = matriz_trajetorias(df_info, "EARM_PROJ_TRAJ", submercado_earm, alvo)
    linhas = []
    for t in [c for c in TRAJ_ORDEM if c in set(ena.columns) | set(earm.columns)]:
        e = ena[t].dropna() if t in ena.columns else pd.Series(dtype=float)
        a = earm[t].dropna() if t in earm.columns else pd.Series(dtype=float)
        linhas.append({"trajetoria": t,
                       "ena_media_pct_mlt": float(e.mean()) if len(e) else np.nan,
                       "earm_media_pct": float(a.mean()) if len(a) else np.nan,
                       "meses_ena": int(len(e)), "meses_earm": int(len(a)),
                       "cobertura_horizonte": float(max(len(e), len(a)) / max(len(alvo), 1))})
    d = pd.DataFrame(linhas)
    for c, novo in (("ena_media_pct_mlt", "z_ena"), ("earm_media_pct", "z_earm")):
        s = d[c]
        d[novo] = (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) else 0.0
    d["score_umidade"] = 0.6 * d.z_ena.fillna(0) + 0.4 * d.z_earm.fillna(0)
    return d.sort_values("score_umidade").reset_index(drop=True)


def selecionar_cenarios(df_info: pd.DataFrame, submercado: str, alvo: pd.DatetimeIndex,
                        trajetoria_central: str = "RNA",
                        cobertura_minima: float = 0.99) -> tuple[pd.DataFrame, dict]:
    """Esperado, Seco e Umido como TRAJETORIAS INTEIRAS, nunca combinadas.

    Esperado = trajetoria central declarada (RNA e a referencia da CCEE).
    Seco     = menor score de umidade entre as que cobrem o horizonte.
    Umido    = maior score de umidade entre as que cobrem o horizonte.

    Trajetorias que nao cobrem o horizonte inteiro (CFS VE e CFS LI sao stress
    de curto prazo) ficam disponiveis como sensibilidade, mas nao sao elegiveis
    a cenario principal — usa-las obrigaria a completar meses com outro modelo,
    que e exatamente o "Frankenstein" que queremos evitar.
    """
    precos = matriz_trajetorias(df_info, "PLD_PROJ_TRAJ", submercado, alvo)
    from .parse_infopld import projecao_pld_consolidada
    cons = projecao_pld_consolidada(df_info, submercado)
    cons["mes"] = pd.to_datetime(cons.periodo + "-01")
    precos = cons.pivot_table(index="mes", columns="cenario", values="valor",
                              aggfunc="last").reindex(alvo)

    # MES CORRENTE: a tabela de trajetorias comeca no mes seguinte, porque e ali
    # que os modelos passam a divergir. Para o mes corrente a CCEE publica uma
    # expectativa UNICA no resumo — ela ja e dominada pelos dias realizados.
    # Replicar esse valor unico em todas as trajetorias e correto e fica declarado;
    # deixar NaN eliminaria todas as trajetorias por "cobertura incompleta".
    meses_unicos = []
    for m in alvo:
        col_ok = precos.loc[m].notna()
        if col_ok.sum() == 1 and trajetoria_central in precos.columns \
                and pd.notna(precos.at[m, trajetoria_central]):
            v = precos.at[m, trajetoria_central]
            precos.loc[m, :] = v
            meses_unicos.append(str(m.date()))

    score = score_hidrologico(df_info, alvo)
    elegiveis = score[score.cobertura_horizonte >= cobertura_minima].copy()
    # so podem ser cenario principal as que tambem tem preco em todo o horizonte
    ok_preco = [t for t in elegiveis.trajetoria
                if t in precos.columns and precos[t].notna().all()]
    elegiveis = elegiveis[elegiveis.trajetoria.isin(ok_preco)]
    if elegiveis.empty:
        raise ValueError("nenhuma trajetoria cobre o horizonte inteiro em ENA/EARM e preco")

    seco = elegiveis.iloc[0].trajetoria
    umido = elegiveis.iloc[-1].trajetoria
    if trajetoria_central not in precos.columns:
        raise ValueError(f"trajetoria central {trajetoria_central} sem preco no horizonte")

    out = pd.DataFrame({
        "mes_ref": alvo,
        "Esperado": precos[trajetoria_central].to_numpy(),
        "Seco": precos[seco].to_numpy(),
        "Umido": precos[umido].to_numpy(),
    })
    horas = np.array([pd.Period(m, freq="M").days_in_month * 24 for m in alvo], float)
    med = {c: float(np.average(out[c], weights=horas)) for c in ("Esperado", "Seco", "Umido")}

    diag = {
        "trajetoria_esperado": trajetoria_central,
        "trajetoria_seco": seco, "trajetoria_umido": umido,
        "score": score.to_dict("records"),
        "elegiveis": list(elegiveis.trajetoria),
        "excluidas_por_horizonte": [t for t in score.trajetoria
                                    if t not in list(elegiveis.trajetoria)],
        "preco_medio": med,
        "meses_valor_unico_resumo": meses_unicos,
        "ordenacao_coerente": bool(med["Seco"] >= med["Esperado"] >= med["Umido"]),
    }
    # A checagem que importa: o cenario central pode estar no extremo do leque.
    pos = list(elegiveis.trajetoria).index(trajetoria_central) \
        if trajetoria_central in list(elegiveis.trajetoria) else None
    diag["posicao_central_no_leque"] = (
        None if pos is None else
        ("mais seca" if pos == 0 else
         "mais umida" if pos == len(elegiveis) - 1 else "intermediaria"))
    if diag["posicao_central_no_leque"] in ("mais seca", "mais umida"):
        diag["alerta"] = (
            f"A trajetoria central ({trajetoria_central}) e a {diag['posicao_central_no_leque']} "
            f"entre as elegiveis. O cenario Esperado ja embute hidrologia de extremo, "
            f"e o risco fica assimetrico. Isso e um achado, nao um defeito: significa "
            f"que a referencia da CCEE esta conservadora nesse horizonte.")
    if not diag["ordenacao_coerente"]:
        diag["alerta_ordenacao"] = (
            f"Ordenacao Seco>=Esperado>=Umido NAO se verifica "
            f"(Seco {med['Seco']:.1f}, Esperado {med['Esperado']:.1f}, "
            f"Umido {med['Umido']:.1f}). Causa provavel: o cenario central e mais seco "
            f"que o 'Seco' por score hidrologico, ou ha efeito intertemporal de "
            f"armazenamento. Investigar antes de operar; NAO forcar a ordem.")
    return out, diag


# -------------------------------------------------------------- 3. nowcast
def nowcast(df_ipdo: pd.DataFrame, df_info: pd.DataFrame, alvo: pd.DatetimeIndex,
            meia_vida_meses: float = 1.5,
            sensibilidades: dict | None = None) -> tuple[pd.Series, pd.DataFrame, dict]:
    """Ajuste de curto prazo a partir das surpresas do IPDO.

    Surpresa padronizada -> impacto em % sobre o preco, com DECAIMENTO no
    horizonte: o que aconteceu ontem move muito o mes corrente e quase nada
    dezembro.

        ajuste(mes) = Σ_driver  sens_driver × z_driver × 0,5^(h/meia_vida)

    As sensibilidades sao PREMISSAS DECLARADAS enquanto nao houver amostra para
    estimar por regressao — o backcast precisa de varias edicoes de IPDO, e uma
    unica edicao nao permite estimar nada. Com o historico acumulado, trocar
    este dicionario por coeficientes estimados e o proximo passo natural.
    """
    from .parse_ipdo import surpresas
    sens = sensibilidades or {
        # driver          : impacto no preco por 1 desvio-padrao de surpresa
        "CARGA": +0.35,             # carga acima do programado -> preco sobe
        "GER_HIDRONACIONAL": -0.20,  # mais hidro -> preco cai
        "GER_EOLICA": -0.10,
        "GER_SOLAR": -0.08,
        "GER_TERMOCONVENCIO": +0.15,  # mais termica -> sistema mais apertado
    }
    # Escala tipica de surpresa diaria (premissa): 2% para carga, 8% para fontes.
    escala = {"CARGA": 0.02, "GER_HIDRONACIONAL": 0.08, "GER_EOLICA": 0.15,
              "GER_SOLAR": 0.12, "GER_TERMOCONVENCIO": 0.20}

    s = surpresas(df_ipdo)
    s = s[s.submercado == "SIN"]
    linhas = []
    total_z = 0.0
    for _, r in s.iterrows():
        if r.variavel not in sens:
            continue
        z = r.surpresa_pct / escala.get(r.variavel, 0.10)
        contrib = sens[r.variavel] * z
        total_z += contrib
        linhas.append({"driver": r.variavel, "programado": r.valor_prog,
                       "realizado": r.valor_real, "surpresa_pct": r.surpresa_pct,
                       "z": z, "sensibilidade": sens[r.variavel],
                       "contribuicao_pct": contrib})
    det = pd.DataFrame(linhas)

    h = np.arange(len(alvo), dtype=float)
    decai = 0.5 ** (h / meia_vida_meses)
    ajuste = pd.Series(total_z * decai / 100.0, index=alvo)   # contrib esta em %

    diag = {
        "n_drivers": len(det), "contribuicao_total_pct": float(total_z),
        "meia_vida_meses": meia_vida_meses,
        "ajuste_primeiro_mes_pct": float(ajuste.iloc[0] * 100) if len(ajuste) else 0.0,
        "ajuste_ultimo_mes_pct": float(ajuste.iloc[-1] * 100) if len(ajuste) else 0.0,
        "sensibilidades": sens, "escalas": escala,
        "natureza": "PREMISSA — sensibilidades declaradas, nao estimadas",
        "limitacao": ("com uma unica edicao de IPDO nao ha amostra para estimar "
                      "as sensibilidades por regressao; sao premissas ate o "
                      "historico de boletins permitir o backtest"),
    }
    return ajuste, det, diag


# -------------------------------------------------------- 4. curva completa
def compor_curva(ancora: pd.Series, estatistico: pd.Series, ajuste_nowcast: pd.Series,
                 peso_fundamental: float, premio_basis: float = 0.0
                 ) -> tuple[pd.DataFrame, dict]:
    """Combina os quatro componentes em uma curva unica e auditavel."""
    idx = ancora.index
    a = ancora.astype(float)
    e = estatistico.reindex(idx).astype(float)
    w = float(peso_fundamental)
    base = np.where(a.notna(), w * a.fillna(0) + (1 - w) * e, e)
    com_nowcast = base * (1.0 + ajuste_nowcast.reindex(idx).fillna(0).to_numpy())
    final = com_nowcast + premio_basis

    df = pd.DataFrame({
        "mes_ref": idx,
        "ancora_infopld": a.to_numpy(),
        "estatistico_ewma": e.to_numpy(),
        "peso_fundamental": w,
        "base_combinada": base,
        "ajuste_nowcast_pct": ajuste_nowcast.reindex(idx).fillna(0).to_numpy() * 100,
        "premio_basis": premio_basis,
        "fair_value": final,
    })
    diag = {
        "peso_fundamental": w,
        "premio_basis": premio_basis,
        "premio_declarado": ("ZERO por premissa explicita: nao ha referencia publica "
                             "de transacao comparavel para estimar o premio a termo. "
                             "O resultado e FAIR VALUE FUNDAMENTAL, nao cotacao."),
        "meses_com_ancora": int(a.notna().sum()),
        "meses_sem_ancora": [str(m.date()) for m in idx[a.isna()]],
    }
    return df, diag
