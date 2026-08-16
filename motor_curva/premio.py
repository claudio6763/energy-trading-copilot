# -*- coding: utf-8 -*-
"""Premio a termo: a ponte entre projecao de PLD e preco de contrato.

O PROBLEMA QUE ESTE MODULO RESOLVE
----------------------------------
A projecao da CCEE e expectativa de PLD SPOT no mes de entrega. O contrato a
termo negocia acima disso, porque quem vende energia a termo cobra premio por
assumir risco hidrologico. Ate aqui o modelo mantinha esse premio em ZERO por
falta de referencia, e o resultado ficava sistematicamente abaixo do mercado.

Com uma referencia de mercado disponivel, o premio deixa de ser premissa cega e
passa a ser CALIBRADO:

    premio(m) = referencia_mercado(m) - ancora_fundamental(m)

TRATAMENTO DA FONTE
-------------------
A referencia de mercado entra como PREMISSA DECLARADA, sem identificacao de
fonte, exatamente como manda a regra do case para informacao de mesa que nao
pode ser demonstrada publicamente. Ela e rotulada REFERENCIA_MERCADO e fica
isolada em aba propria, editavel. Nenhum resultado depende dela sem que isso
esteja visivel.

DOIS MODOS, E A DIFERENCA IMPORTA
---------------------------------
    mercado_consistente  premio por mes -> a curva reproduz o mercado.
                         Serve para MARCAR A MERCADO um book existente.
    visao_propria        premio medio (nivel) -> a forma da curva continua sendo
                         do modelo. A diferenca entre o modelo e o mercado, mes a
                         mes, e o SINAL DE NEGOCIACAO.

Um modelo que so reproduz o mercado nao gera sinal nenhum. Um modelo que ignora
o mercado nao consegue marcar posicao. Por isso os dois modos convivem.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def horas_do_mes(m) -> int:
    return pd.Period(pd.Timestamp(m), freq="M").days_in_month * 24


def calibrar(ancora: pd.Series, referencia: pd.Series) -> tuple[pd.DataFrame, dict]:
    """Decompoe o premio em NIVEL e FORMA.

    nivel = media ponderada por horas do premio, em R$/MWh
    forma = desvio de cada mes em relacao ao nivel
    """
    idx = ancora.index
    ref = referencia.reindex(idx)
    horas = np.array([horas_do_mes(m) for m in idx], float)
    premio = ref - ancora
    validos = premio.notna()
    if not validos.any():
        raise ValueError("nenhum mes com referencia de mercado e ancora simultaneamente")

    nivel = float(np.average(premio[validos], weights=horas[validos]))
    nivel_pct = float(np.average((premio / ancora)[validos], weights=horas[validos]))
    forma = premio - nivel

    df = pd.DataFrame({
        "mes_ref": idx,
        "ancora": ancora.to_numpy(),
        "referencia_mercado": ref.to_numpy(),
        "premio_rs": premio.to_numpy(),
        "premio_pct": (premio / ancora).to_numpy(),
        "premio_nivel": nivel,
        "premio_forma": forma.to_numpy(),
        "horas": horas,
    })
    # a literatura brasileira descreve premio crescente e depois decrescente com
    # a maturidade; se o formato aparecer, vale registrar
    p = premio[validos].to_numpy()
    formato = "indefinido"
    if len(p) >= 4:
        topo = int(np.argmax(p))
        if 0 < topo < len(p) - 1:
            formato = f"corcova com pico em {pd.Timestamp(idx[topo]):%b/%y}"
        elif topo == 0:
            formato = "decrescente com a maturidade"
        else:
            formato = "crescente com a maturidade"

    diag = {
        "rotulo": "REFERENCIA_MERCADO",
        "natureza": "PREMISSA — leitura de mesa, sem identificacao de fonte",
        "nivel_rs_mwh": nivel,
        "nivel_pct": nivel_pct,
        "premio_min": float(premio[validos].min()),
        "premio_max": float(premio[validos].max()),
        "formato_termo": formato,
        "meses_calibrados": int(validos.sum()),
        "aviso": ("A referencia de mercado nao e dado publico demonstravel. Entra "
                  "como premissa declarada e fica isolada em aba propria; a curva "
                  "sem ela continua disponivel para auditoria."),
    }
    return df, diag


def dispersao_cenarios(seco: pd.Series, esperado: pd.Series,
                       umido: pd.Series) -> pd.Series:
    """(Seco - Umido) / Esperado. E INVARIANTE A ESCALA.

    Como os tres cenarios saem das mesmas trajetorias do InfoPLD reescaladas
    pelo mesmo fator, a razao nao depende do nivel da curva. Isso quebra a
    circularidade: da para calcular a dispersao ANTES de montar a curva e usar
    o premio justo na propria construcao dela.
    """
    e = esperado.to_numpy(float)
    return pd.Series((seco.to_numpy(float) - umido.to_numpy(float))
                     / np.where(e != 0, e, np.nan), index=esperado.index)


def calibrar_k(cal: pd.DataFrame, dispersao: pd.Series) -> float:
    """k tal que a media ponderada de k*dispersao reproduza o premio observado."""
    d = dispersao.reindex(cal.mes_ref).to_numpy(float)
    h, pr = cal.horas.to_numpy(float), cal.premio_rs.to_numpy(float)
    ok = np.isfinite(d) & (d > 0) & np.isfinite(pr)
    if ok.sum() < 2:
        raise ValueError("dispersao insuficiente para calibrar k")
    return float(np.average(pr[ok], weights=h[ok]) / np.average(d[ok], weights=h[ok]))


def aplicar(ancora: pd.Series, estatistico: pd.Series, peso_ancora: float,
            ajuste_nowcast: pd.Series, cal: pd.DataFrame, modo: str = "visao_propria",
            premio_justo_serie: pd.Series | None = None
            ) -> tuple[pd.DataFrame, dict]:
    """Monta a curva final com o premio calibrado.

    base    = peso*ancora + (1-peso)*estatistico, ajustada pelo nowcast
    premio  = nivel (visao_propria) ou nivel+forma (mercado_consistente)
    """
    idx = ancora.index
    a = ancora.astype(float)
    e = estatistico.reindex(idx).astype(float)
    base = (peso_ancora * a.fillna(0) + (1 - peso_ancora) * e)
    base = base * (1 + ajuste_nowcast.reindex(idx).fillna(0))

    c = cal.set_index("mes_ref")
    if modo == "mercado_consistente":
        premio = c.premio_rs.reindex(idx)
    elif modo == "visao_propria":
        premio = pd.Series(float(c.premio_nivel.iloc[0]), index=idx)
    elif modo == "premio_justo":
        if premio_justo_serie is None:
            raise ValueError("modo premio_justo exige a serie de premio justo")
        premio = premio_justo_serie.reindex(idx)
    elif modo == "sem_premio":
        premio = pd.Series(0.0, index=idx)
    else:
        raise ValueError(f"modo desconhecido: {modo}")

    fv = base + premio
    ref = c.referencia_mercado.reindex(idx)
    df = pd.DataFrame({
        "mes_ref": idx, "base_modelo": base.to_numpy(),
        "premio_aplicado": premio.to_numpy(), "fair_value": fv.to_numpy(),
        "referencia_mercado": ref.to_numpy(),
        "residuo_vs_mercado": (fv - ref).to_numpy(),
    })
    df["sinal"] = np.where(df.residuo_vs_mercado > 0, "BARATO (comprar)",
                           np.where(df.residuo_vs_mercado < 0, "CARO (vender)", "neutro"))
    diag = {"modo": modo,
            "explicacao": {
                "visao_propria": ("premio de NIVEL apenas; a forma da curva e do "
                                  "modelo e o residuo por mes e o sinal"),
                "mercado_consistente": ("premio por mes; a curva reproduz o mercado "
                                        "e serve para marcacao, nao gera sinal"),
                "premio_justo": ("premio proporcional a abertura do leque de cada "
                                 "mes; o NIVEL bate com o mercado e a FORMA e do "
                                 "modelo — postura de valor relativo"),
                "sem_premio": "fair value fundamental puro, sem premio",
            }[modo]}
    return df, diag


def sinal_por_mes(df: pd.DataFrame, limiar_rs: float = 15.0) -> pd.DataFrame:
    """Onde o modelo discorda do mercado o suficiente para operar.

    O limiar deve ser comparavel ao erro do proprio modelo — abaixo disso a
    diferenca e ruido, nao oportunidade.
    """
    d = df.copy()
    d["acao"] = np.where(d.residuo_vs_mercado >= limiar_rs, "COMPRAR",
                         np.where(d.residuo_vs_mercado <= -limiar_rs, "VENDER", "FORA"))
    d["conviccao_rs"] = d.residuo_vs_mercado.abs()
    d["limiar"] = limiar_rs
    return d[["mes_ref", "fair_value", "referencia_mercado", "residuo_vs_mercado",
              "acao", "conviccao_rs", "limiar"]]


# ==================================================================
# SINAL DE VALOR RELATIVO — a versao que sobrevive a critica de mesa
# ==================================================================
def premio_justo(cal: pd.DataFrame, seco: pd.Series, umido: pd.Series,
                 esperado: pd.Series) -> pd.DataFrame:
    """Premio que CADA MES deveria pagar, dado o risco daquele mes.

    POR QUE UM PREMIO UNICO PARA TODOS OS MESES ESTA ERRADO
    -------------------------------------------------------
    O premio a termo remunera quem carrega risco hidrologico. Um mes que ja
    esta quase inteiro realizado quase nao tem risco a carregar — o premio dele
    tem de ser pequeno. Um mes distante, com o leque de cenarios totalmente
    aberto, tem de pagar muito mais.

    Aplicar o premio MEDIO ao mes corrente infla artificialmente o edge dele.
    Foi exatamente isso que fez a versao anterior comprar 72 MWm de agosto: o
    maior tamanho do book estava num mes que ja nao tinha risco para justificar
    o premio que lhe foi atribuido.

    A medida de risco de cada mes ja existe no modelo: a ABERTURA DO LEQUE de
    cenarios.
        dispersao(m) = (Seco(m) - Umido(m)) / Esperado(m)
        premio_justo(m) = k * dispersao(m)
    com k calibrado para que a media ponderada por horas reproduza o premio
    observado. Assim o NIVEL vem do mercado e a FORMA vem do risco.
    """
    idx = cal.mes_ref
    d = pd.Series(((seco.to_numpy() - umido.to_numpy())
                   / np.where(esperado.to_numpy() != 0, esperado.to_numpy(), np.nan)),
                  index=idx)
    horas = cal.horas.to_numpy()
    prem_obs = cal.premio_rs.to_numpy()
    validos = np.isfinite(d.to_numpy()) & (d.to_numpy() > 0) & np.isfinite(prem_obs)
    if validos.sum() < 2:
        raise ValueError("dispersao insuficiente para calibrar o premio justo")
    k = float(np.average((prem_obs / d.to_numpy())[validos], weights=horas[validos]))
    out = cal.copy()
    out["dispersao"] = d.to_numpy()
    out["k_premio"] = k
    out["premio_justo"] = k * d.to_numpy()
    out["sinal_relativo"] = out.premio_rs - out.premio_justo
    return out


def limiar_calibrado(edges: np.ndarray, horas: np.ndarray, k_sigma: float = 1.0,
                     custo_execucao: float = 5.0) -> tuple[float, dict]:
    """Limiar auto-calibrado pelo proprio erro de ajuste do premio.

    Um limiar fixo em R$/MWh e arbitrario e, pior, e o MESMO para uma aposta
    direcional e para um spread. Nao deveria ser: num spread o risco de nivel
    esta neutralizado, entao o limiar tem de ser menor.

    Aqui o limiar e o maior entre:
      - o custo estimado de executar (spread de tela, premissa declarada);
      - k_sigma desvios-padrao do residuo do ajuste do premio.
    Assim ele acompanha a qualidade do ajuste: quando o modelo explica bem a
    forma do premio, o residuo e pequeno e ate desvios modestos viram sinal.
    """
    e = np.asarray(edges, float)
    ok = np.isfinite(e)
    sigma = float(np.sqrt(np.average((e[ok] - np.average(e[ok], weights=horas[ok])) ** 2,
                                     weights=horas[ok]))) if ok.sum() > 1 else 0.0
    lim = max(custo_execucao, k_sigma * sigma)
    return lim, {"sigma_residuo": sigma, "k_sigma": k_sigma,
                 "custo_execucao": custo_execucao, "limiar": lim,
                 "vinculante": "custo de execucao" if custo_execucao >= k_sigma * sigma
                 else f"{k_sigma:g} desvio-padrao do residuo"}


def sinal(cal_justo: pd.DataFrame, limiar_rs: float = 15.0,
          modo: str = "valor_relativo", auto_limiar: bool = True,
          k_sigma: float = 1.0, custo_execucao: float = 5.0) -> pd.DataFrame:
    """Decide comprado ou vendido em cada mes. Tres modos, e a escolha importa.

    valor_relativo  (padrao) compara o premio OBSERVADO com o premio JUSTO do
                    mes. Sinal positivo = o mercado paga premio demais por esse
                    mes = forward caro = VENDER. Soma quase neutra em nivel:
                    e um SPREAD, nao uma aposta na direcao do premio.

    direcional_premio  compara o preco de mercado com a projecao de PLD do
                    InfoPLD. Como o forward negocia acima da projecao em todos
                    os meses, isso resulta em VENDER TUDO — e uma aposta
                    direcional de que a hidrologia vem normal ou melhor, nao um
                    sinal de valor relativo. Legitimo, mas outra estrategia,
                    com cauda esquerda pesada no cenario seco.

    modelo_vs_mercado  compara o fair value do modelo com o mercado. Depende de
                    o componente estatistico estar bem calibrado em NIVEL, o que
                    e a parte mais fragil do modelo.
    """
    d = cal_justo.copy()
    if modo == "valor_relativo":
        d["edge"] = d.sinal_relativo
        d["interpretacao"] = "premio observado menos premio justo do mes"
    elif modo == "direcional_premio":
        d["edge"] = d.premio_rs
        d["interpretacao"] = "mercado menos projecao de PLD (vende o premio)"
    elif modo == "modelo_vs_mercado":
        if "fair_value_modelo" not in d.columns:
            raise ValueError("modo exige a coluna fair_value_modelo")
        d["edge"] = d.referencia_mercado - d.fair_value_modelo
        d["interpretacao"] = "mercado menos fair value do modelo"
    else:
        raise ValueError(f"modo desconhecido: {modo}")

    horas = d.horas.to_numpy(float)
    if auto_limiar and modo == "valor_relativo":
        limiar_rs, diag_lim = limiar_calibrado(d.edge.to_numpy(), horas,
                                               k_sigma, custo_execucao)
        d["sigma_residuo"] = diag_lim["sigma_residuo"]
        d["limiar_vinculante"] = diag_lim["vinculante"]
    else:
        d["sigma_residuo"] = np.nan
        d["limiar_vinculante"] = "fixo (premissa)"
    d["z_edge"] = d.edge / d.sigma_residuo if d.sigma_residuo.iloc[0] else np.nan

    # edge POSITIVO = o mercado esta pagando demais = forward caro = VENDER
    d["acao"] = np.where(d.edge >= limiar_rs, "VENDER",
                         np.where(d.edge <= -limiar_rs, "COMPRAR", "FORA"))
    d["conviccao_rs"] = d.edge.abs()
    d["limiar"] = limiar_rs
    d["modo"] = modo
    horas = d.horas.to_numpy()
    d["edge_nivel"] = float(np.average(d.edge, weights=horas))
    d["edge_forma"] = d.edge - d.edge_nivel
    return d[["mes_ref", "ancora", "referencia_mercado", "premio_rs", "dispersao",
              "premio_justo", "edge", "z_edge", "edge_nivel", "edge_forma", "acao",
              "conviccao_rs", "limiar", "sigma_residuo", "limiar_vinculante",
              "modo", "interpretacao"]]
