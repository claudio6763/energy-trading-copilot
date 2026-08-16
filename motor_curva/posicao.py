"""Tese, dimensionamento, PnL e VPL."""
from __future__ import annotations
import calendar
from datetime import date
import numpy as np
import pandas as pd

from . import risco


def horas_do_mes(m: pd.Timestamp) -> int:
    return calendar.monthrange(m.year, m.month)[1] * 24


def horas_produto(meses: pd.DatetimeIndex) -> float:
    return float(sum(horas_do_mes(m) for m in meses))


def vpl(fluxos: list[tuple[date, float]], taxa_aa: float, hoje: date) -> float:
    return float(sum(v / (1 + taxa_aa) ** ((d - hoje).days / 365.0) for d, v in fluxos))


def definir_posicao(fair_value: pd.Series, preco_entrada: float | None,
                    edge_minimo: float, var_preco: float, orcamento_var: float,
                    meses: pd.DatetimeIndex, referencia_alternativa: float | None = None,
                    fonte_referencia: str = "", mwm_teto: float | None = None,
                    perda_cenario_por_mwm: float | None = None,
                    orcamento_cenario: float | None = None) -> dict:
    """Regra deterministica de direcao e tamanho.

    Tres desfechos possiveis, todos com dimensionamento:

    DIRECIONAL  ha preco publico de transacao comparavel e o edge supera o minimo.
    CONDICIONAL nao ha preco comparavel. A ordem e limitada: define-se o preco
                maximo de compra e o minimo de venda, e dimensiona-se a posicao
                COMO SE executada no limite. Isso entrega dimensionamento sem
                inventar preco de entrada.
    SEM_POSICAO ha preco comparavel, mas o edge nao supera o minimo de conviccao.
    """
    fv = float(np.average(fair_value.to_numpy(), weights=[horas_do_mes(m) for m in meses]))
    h = horas_produto(meses)
    comprar_ate, vender_acima = fv - edge_minimo, fv + edge_minimo
    # TRES RESTRICOES, e vale a menor. Reportar qual delas prendeu e parte da disciplina.
    #   (1) VaR       — risco de marcacao a mercado / desmontagem em 1 mes
    #   (2) LIQUIDEZ  — quanto o mercado absorve sem mover o proprio preco
    #   (3) CENARIO   — perda se a posicao for CARREGADA ATE A ENTREGA no cenario
    #                   hidrologico adverso. Para um termo levado ao vencimento, esta
    #                   costuma ser a restricao que realmente morde: o VaR mensal mede
    #                   o risco de sair, nao o risco de ficar.
    mwm_var = float(np.floor(orcamento_var / (abs(var_preco) * h))) if var_preco > 0 else 0.0
    mwm_liq = float(mwm_teto) if mwm_teto else float("inf")
    if perda_cenario_por_mwm and perda_cenario_por_mwm > 0:
        mwm_cen = float(np.floor((orcamento_cenario or orcamento_var) / perda_cenario_por_mwm))
    else:
        mwm_cen = float("inf")
    candidatos = {"VaR": mwm_var, "liquidez": mwm_liq, "cenario adverso": mwm_cen}
    restricao = min(candidatos, key=candidatos.get)
    mwm_max = float(np.floor(min(candidatos.values())))
    out = {"fair_value_flat": fv, "horas": h,
           "mwm_por_VaR": mwm_var, "mwm_por_liquidez": mwm_liq, "mwm_por_cenario": mwm_cen,
           "restricao_vinculante": restricao,
           "comprar_ate": comprar_ate, "vender_acima_de": vender_acima,
           "meses": [str(m.date()) for m in meses]}

    if preco_entrada is None or not np.isfinite(preco_entrada):
        # direcao indicativa: fair value contra a ultima referencia observavel
        dir_ind = 0
        if referencia_alternativa is not None and np.isfinite(referencia_alternativa):
            dir_ind = 1 if fv > referencia_alternativa else -1
        out.update({
            "tipo": "CONDICIONAL",
            "motivo": "sem preco publico de transacao comparavel na data de corte",
            "direcao": dir_ind or 1,
            "direcao_indicativa_por": fonte_referencia or "convencao (compra no limite)",
            "referencia_alternativa": referencia_alternativa,
            "preco_entrada": comprar_ate if (dir_ind or 1) > 0 else vender_acima,
            "mwm": mwm_max,
            "var_brl": risco.var_posicao(var_preco, mwm_max, h, dir_ind or 1),
            "observacao": ("tamanho dimensionado no preco-limite; a ordem so e executada se o "
                           "mercado imprimir nesse nivel"),
        })
        out["pnl_esperado"] = risco.pnl(out["direcao"], mwm_max, h, out["preco_entrada"], fv)
        return out

    edge = fv - preco_entrada
    if abs(edge) < edge_minimo:
        out.update({"tipo": "SEM_POSICAO", "edge": edge, "direcao": 0, "mwm": 0.0,
                    "var_brl": 0.0, "preco_entrada": preco_entrada,
                    "motivo": f"|edge| {abs(edge):.2f} < minimo {edge_minimo:.2f} R$/MWh",
                    "pnl_esperado": 0.0})
        return out

    direcao = 1 if edge > 0 else -1
    out.update({"tipo": "DIRECIONAL", "edge": edge, "direcao": direcao,
                "preco_entrada": preco_entrada, "mwm": mwm_max,
                "var_brl": risco.var_posicao(var_preco, mwm_max, h, direcao),
                "pnl_esperado": risco.pnl(direcao, mwm_max, h, preco_entrada, fv)})
    return out
