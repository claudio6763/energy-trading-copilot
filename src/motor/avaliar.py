"""`avaliar()` — a parte barata do motor: premio -> sinal -> risco por vertice
-> book -> PnL -> VPL. Milissegundos, nunca toca `data/raw`.

Reproduz exatamente a sequencia de `motor_curva.cli.cmd_run` a partir do ponto
em que a curva (ancora + sazonal + cenarios + VaR por vertice) ja esta pronta —
ou seja, tudo que esta congelado em `MotorSnapshot`. `avaliar()` nunca
recalcula ancora, fatores sazonais, cenarios oficiais nem VaR/ES por vertice:
esses numeros sao lidos do snapshot. So o que depende da referencia de mercado
(premissa do trader, pode mudar a cada chamada) e recalculado aqui.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from motor_curva import book as BK
from motor_curva import curva as CV
from motor_curva import premio as PRM
from motor_curva.config import PREMISSAS

from src.motor.snapshot import MotorSnapshot


def _serie(valores: dict[str, float], idx: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(
        {pd.Timestamp(k): float(v) for k, v in valores.items()}, dtype=float
    ).reindex(idx)


def _chave_mes(chave: str) -> pd.Timestamp:
    return pd.Timestamp(chave + "-01" if len(chave) == 7 else chave)


def avaliar(
    snapshot: MotorSnapshot,
    ref_mercado: dict[str, float],
    limite_var: Decimal | float,
    *,
    modo_sinal: str | None = None,
    premio_modo: str | None = None,
    limiar_sinal_rs: float | None = None,
    auto_limiar: bool | None = None,
    k_sigma_limiar: float | None = None,
    custo_execucao_rs: float | None = None,
    var_orcamento_frac: float | None = None,
    mwm_maximo_operacional: float | None = None,
    taxa_desconto_aa: float | None = None,
    hoje: date | None = None,
) -> dict[str, Any]:
    """Book proposto a partir do snapshot + uma referencia de mercado nova.

    `ref_mercado`: `{"2026-08": 142.0, ...}` (ou `"2026-08-01"`), uma entrada
    por vertice do `snapshot.alvo`. Falha explicita (ValueError) se faltar
    vertice — nunca interpolacao, nunca ultimo valor conhecido em silencio.

    Todo parametro de premissa (modo de sinal, limiar, orcamento de risco...)
    tem default vindo de `motor_curva.config.PREMISSAS` — a MESMA fonte que o
    pipeline pesado usa. Nao existe um segundo conjunto de defaults aqui.
    """
    modo_sinal = PREMISSAS.modo_sinal if modo_sinal is None else modo_sinal
    premio_modo = PREMISSAS.premio_modo if premio_modo is None else premio_modo
    limiar_sinal_rs = PREMISSAS.limiar_sinal_rs if limiar_sinal_rs is None else limiar_sinal_rs
    auto_limiar = PREMISSAS.auto_limiar if auto_limiar is None else auto_limiar
    k_sigma_limiar = PREMISSAS.k_sigma_limiar if k_sigma_limiar is None else k_sigma_limiar
    custo_execucao_rs = PREMISSAS.custo_execucao_rs if custo_execucao_rs is None else custo_execucao_rs
    var_orcamento_frac = PREMISSAS.var_orcamento_frac if var_orcamento_frac is None else var_orcamento_frac
    mwm_maximo_operacional = (
        PREMISSAS.mwm_maximo_operacional if mwm_maximo_operacional is None else mwm_maximo_operacional
    )
    taxa_desconto_aa = PREMISSAS.taxa_desconto_aa if taxa_desconto_aa is None else taxa_desconto_aa
    hoje = date.today() if hoje is None else hoje
    limite_var = float(limite_var)

    idx = pd.DatetimeIndex([pd.Timestamp(m) for m in snapshot.alvo])

    s_fun = _serie(snapshot.s_fun, idx)
    s_saz = _serie(snapshot.s_saz, idx)
    ajuste_now = _serie(snapshot.ajuste_now, idx)
    var_vert = _serie(snapshot.var_vert, idx)
    es_vert = _serie(snapshot.es_vert, idx)

    ref_mkt = pd.Series(
        {_chave_mes(k): float(v) for k, v in ref_mercado.items()}, dtype=float
    ).reindex(idx)
    faltando = [str(m.date()) for m in idx if pd.isna(ref_mkt.get(m))]
    if faltando:
        raise ValueError(
            "FALHA EXPLICITA: referencia de mercado faltando para "
            + ", ".join(faltando)
            + ". Sem premissa declarada para esses vertices nao ha premio "
              "calibravel — nunca interpolado, nunca preenchido em silencio."
        )

    cal_prem, diag_prem = PRM.calibrar(s_fun, ref_mkt)

    seco0 = _serie(snapshot.cenarios_oficiais["Seco"], idx)
    esperado0 = _serie(snapshot.cenarios_oficiais["Esperado"], idx)
    umido0 = _serie(snapshot.cenarios_oficiais["Umido"], idx)

    disp0 = PRM.dispersao_cenarios(seco0, esperado0, umido0)
    k_prem = PRM.calibrar_k(cal_prem, disp0)
    premio_justo_s = (k_prem * disp0).rename("premio_justo")

    modo_curva = "premio_justo" if modo_sinal == "valor_relativo" else premio_modo
    curva_prem, diag_modo = PRM.aplicar(
        s_fun, s_saz, snapshot.w, ajuste_now, cal_prem, modo_curva, premio_justo_s
    )
    fv, flag_limites = CV.aplicar_limites(
        pd.Series(curva_prem.fair_value.to_numpy(), index=idx), idx
    )

    # Risco por vertice usa Seco/Umido de RISCO (razao sobre o fair value final,
    # ou fair_value*k_seco quando o leque oficial nao tem cenario mais seco que
    # o central) — DIFERENTE das trajetorias oficiais usadas no PnL de cenario
    # abaixo. Nunca confundir as duas (invariante 6).
    razao = fv.to_numpy() / np.where(esperado0.to_numpy() > 0, esperado0.to_numpy(), np.nan)
    if snapshot.seco_por_estimador:
        cb_seco_risco = fv * snapshot.k_seco
    else:
        cb_seco_risco = pd.Series(seco0.to_numpy() * razao, index=idx)
    cb_umido_risco = pd.Series(umido0.to_numpy() * razao, index=idx)

    cal_justo = cal_prem.copy()
    cal_justo["dispersao"] = disp0.to_numpy()
    cal_justo["k_premio"] = k_prem
    cal_justo["premio_justo"] = premio_justo_s.to_numpy()
    cal_justo["sinal_relativo"] = cal_justo.premio_rs - cal_justo.premio_justo
    cal_justo["fair_value_modelo"] = fv.to_numpy()

    sinal_df = PRM.sinal(
        cal_justo, limiar_sinal_rs, modo_sinal, auto_limiar, k_sigma_limiar, custo_execucao_rs
    )

    risco_v = BK.risco_por_vertice(sinal_df, cb_seco_risco, cb_umido_risco, ref_mkt, var_vert)
    orcamento = limite_var * var_orcamento_frac
    pernas, dim_var = BK.dimensionar_por_risco(
        risco_v, orcamento, mwmed_max=mwm_maximo_operacional
    )

    bk = BK.Book(pernas, idx)
    conv = s_fun + premio_justo_s.reindex(idx)
    # Cenarios do PnL sao as TRAJETORIAS OFICIAIS inteiras (invariante 6) — nao
    # o Seco/Umido de risco calculados acima.
    curvas = {
        "Convergencia": conv,
        "Entrega_Esperado": s_fun,
        "Entrega_Seco": seco0,
        "Entrega_Umido": umido0,
    }
    book_res = bk.resumo(curvas, var_vert, es_vert, limite_var, taxa_desconto_aa, hoje)

    return {
        "book": book_res,
        "premio_nivel_rs_mwh": diag_prem.get("nivel_rs_mwh"),
        "premio_formato": diag_prem.get("formato_termo"),
        "premio_modo": premio_modo,
        "modo_sinal": modo_sinal,
        "k_premio_por_dispersao": k_prem,
        "status": snapshot.status_motor,
        "submercado": snapshot.submercado,
        "meia_vida_dias": snapshot.hl_dias,
        "k_seco": snapshot.k_seco,
        "k_umido": snapshot.k_umido,
        "snapshot_hash": snapshot.compute_hash(),
        "as_of": snapshot.as_of,
        "ref_mercado": {str(m.date()): float(ref_mkt[m]) for m in idx},
        "sinal": sinal_df.to_dict(orient="records"),
        "dimensionamento": dim_var.to_dict(orient="records") if len(dim_var) else [],
        "curva": {
            "fair_value": {str(m.date()): float(fv[m]) for m in idx},
            "seco_risco": {str(m.date()): float(cb_seco_risco[m]) for m in idx},
            "umido_risco": {str(m.date()): float(cb_umido_risco[m]) for m in idx},
        },
    }


__all__ = ["avaliar"]
