"""Validacoes automaticas. Cada check devolve (nome, status, detalhe)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .config import DATA_CORTE, LIMITES_PLD

OK, ALERTA, FALHA = "OK", "ALERTA", "FALHA"


def _c(nome, cond, detalhe, severidade=FALHA):
    return {"check": nome, "status": OK if cond else severidade, "detalhe": detalhe}


def checar_pld(pld: pd.DataFrame, submercado: str) -> pd.DataFrame:
    r = []
    d = pld[pld.submercado == submercado]
    r.append(_c("chave unica (ts, submercado)",
                not pld.duplicated(["ts", "submercado"]).any(),
                f"{int(pld.duplicated(['ts','submercado']).sum())} duplicata(s)"))
    r.append(_c("sem dado apos a data de corte", (pld.ts.dt.date <= DATA_CORTE).all(),
                f"max = {pld.ts.max()}"))
    r.append(_c("PLD nao negativo", (d.pld >= 0).all(), f"min = {d.pld.min():.2f}"))
    faltas = []
    for ano, g in d[d.granularidade == "horaria"].groupby(d.ts.dt.year):
        esperado = 366 * 24 if ano % 4 == 0 else 365 * 24
        if ano == DATA_CORTE.year:
            esperado = int((pd.Timestamp(DATA_CORTE) - pd.Timestamp(f"{ano}-01-01")).days + 1) * 24
        faltas.append((ano, len(g), esperado, 1 - len(g) / esperado))
    ft = pd.DataFrame(faltas, columns=["ano", "obs", "esperado", "faltante"])
    pior = float(ft.faltante.max()) if len(ft) else 0.0
    r.append(_c("cobertura horaria >= 95%", pior <= 0.05,
                "; ".join(f"{int(a)}: {f:.1%} faltante" for a, _, _, f in faltas), ALERTA))
    for ano in sorted(d.ts.dt.year.unique()):
        lim = LIMITES_PLD.get(int(ano))
        if not lim:
            continue
        g = d[d.ts.dt.year == ano]
        fora = ((g.pld < lim["min"] * 0.999) | (g.pld > lim["max_horario"] * 1.001)).mean()
        r.append(_c(f"PLD {ano} dentro de piso/teto", fora < 0.001,
                    f"{fora:.3%} fora de [{lim['min']}, {lim['max_horario']}]", ALERTA))
        no_piso = (g.pld <= lim["min"] * 1.001).mean()
        r.append(_c(f"censura no piso {ano}", True,
                    f"{no_piso:.1%} das horas no piso - distribuicao truncada a esquerda", OK))
    return pd.DataFrame(r)


def reconciliar(pld: pd.DataFrame, flat: pd.DataFrame, submercado: str) -> pd.DataFrame:
    """PLD horario agregado deve bater com o flat mensal calculado."""
    d = pld[(pld.submercado == submercado) & (pld.granularidade == "horaria")].copy()
    if d.empty:
        return pd.DataFrame([_c("reconciliacao horario->mensal", True, "sem serie horaria", ALERTA)])
    d["mes_ref"] = d.ts.values.astype("datetime64[M]")
    m = d.groupby("mes_ref").pld.mean()
    j = flat.set_index("mes_ref").flat.reindex(m.index)
    dif = (m - j).abs().max()
    return pd.DataFrame([_c("reconciliacao horario->mensal", (dif < 1e-6) or np.isnan(dif),
                            f"maior divergencia = {dif:.10f} R$/MWh")])


def checar_cobertura_flat(flat: pd.DataFrame, minimo: float = 0.98) -> pd.DataFrame:
    ruins = flat[flat.cobertura < minimo]
    return pd.DataFrame([_c("meses com cobertura horaria completa", len(ruins) == 0,
                            "; ".join(f"{r.mes_ref:%Y-%m}={r.cobertura:.1%}" for _, r in ruins.iterrows())
                            or "todos completos", ALERTA)])


def consolidar(*tabelas) -> pd.DataFrame:
    t = pd.concat([x for x in tabelas if x is not None and len(x)], ignore_index=True)
    ordem = {FALHA: 0, ALERTA: 1, OK: 2}
    return t.sort_values("status", key=lambda s: s.map(ordem)).reset_index(drop=True)


def checar_risco(var_brl: float, pior_cenario_pnl: float, es_brl: float,
                 consumo: float) -> pd.DataFrame:
    """Coerencia entre VaR de curto prazo e perda em cenario mantido ate o fim."""
    r = [
        _c("VaR abaixo do teto de R$ 50 mi", var_brl <= 50e6,
           f"VaR = R$ {var_brl/1e6:.1f} mi ({consumo:.1%} do limite)"),
        _c("ES pior ou igual ao VaR", es_brl >= var_brl - 1e-6,
           f"ES = R$ {es_brl/1e6:.1f} mi vs VaR = R$ {var_brl/1e6:.1f} mi"),
        _c("perda do pior cenario coberta pelo VaR", abs(min(pior_cenario_pnl, 0)) <= var_brl,
           (f"pior cenario = R$ {pior_cenario_pnl/1e6:.1f} mi vs VaR = R$ {var_brl/1e6:.1f} mi. "
            f"Se maior, ha DESCASAMENTO DE HORIZONTE: o VaR mede desmontagem em dias uteis, "
            f"o cenario hidrologico e carregado ate o vencimento. Dimensionar pelo cenario, "
            f"nao so pelo VaR."), ALERTA),
    ]
    return pd.DataFrame(r)
