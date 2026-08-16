# -*- coding: utf-8 -*-
"""Book multi-perna: cada produto com preco de entrada e tamanho proprios.

MODELO DE DADOS
---------------
Uma PERNA e uma operacao: produto, lado, MWmed, preco de entrada, data.
Um PRODUTO pode ser mensal (AGO/26) ou agrupado (Q4/26).

Todo produto agrupado e explodido em EXPOSICAO MENSAL EQUIVALENTE antes de
qualquer conta. E isso que evita dupla contagem quando alguem compra Q4 e vende
outubro: as duas pernas viram exposicao mensal e se cancelam parcialmente em
outubro, preservando novembro e dezembro.

PRECO DE PRODUTO AGRUPADO
-------------------------
    Preco_Q4 = Σ(preco_mes × horas_mes) / Σ(horas_mes)
Ponderacao por HORAS, nunca media aritmetica simples: meses de 31 dias entregam
mais MWh e tem de pesar mais.

CONVENCAO DE SINAL
------------------
    compra  -> +1 : ganha quando o preco sobe
    venda   -> -1 : ganha quando o preco cai
    PnL = sinal × MWmed × horas × (preco_cenario − preco_entrada)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date

import numpy as np
import pandas as pd

MESES_PT = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
            "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def horas_do_mes(m) -> int:
    return pd.Period(pd.Timestamp(m), freq="M").days_in_month * 24


def rotulo_mes(m) -> str:
    t = pd.Timestamp(m)
    return f"{MESES_PT[t.month - 1]}/{t.year % 100:02d}"


def meses_do_produto(produto: str, disponiveis: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Resolve 'AGO/26', 'Q4/26' ou 'CAL/26' na lista de meses correspondente."""
    p = produto.strip().upper().replace(" ", "")
    if p.startswith("Q"):
        tri, ano = int(p[1]), 2000 + int(p.split("/")[1])
        alvo = [(tri - 1) * 3 + 1 + k for k in range(3)]
        return [m for m in disponiveis if m.year == ano and m.month in alvo]
    if p.startswith("CAL"):
        ano = 2000 + int(p.split("/")[1])
        return [m for m in disponiveis if m.year == ano]
    nome, ano = p.split("/")
    ano = 2000 + int(ano)
    mes = MESES_PT.index(nome) + 1
    return [m for m in disponiveis if m.year == ano and m.month == mes]


def preco_produto(produto: str, curva: pd.Series, disponiveis: pd.DatetimeIndex) -> float:
    """Preco de um produto: media dos meses ponderada por HORAS."""
    ms = meses_do_produto(produto, disponiveis)
    if not ms:
        raise ValueError(f"produto {produto} nao tem mes no horizonte")
    h = np.array([horas_do_mes(m) for m in ms], float)
    p = np.array([curva.loc[m] for m in ms], float)
    return float(np.sum(p * h) / np.sum(h))


@dataclass
class Perna:
    produto: str
    lado: str                # "C" (compra) ou "V" (venda)
    mwmed: float
    preco_entrada: float
    submercado: str = "SE"
    data_operacao: str = ""
    observacao: str = ""

    @property
    def sinal(self) -> int:
        s = self.lado.strip().upper()
        if s in ("C", "COMPRA", "COMPRADO", "BUY"):
            return 1
        if s in ("V", "VENDA", "VENDIDO", "SELL"):
            return -1
        raise ValueError(f"lado invalido: {self.lado}")

    def dict(self):
        return {**asdict(self), "sinal": self.sinal}


class Book:
    """Conjunto de pernas, consolidado em exposicao mensal equivalente."""

    def __init__(self, pernas: list[Perna], meses: pd.DatetimeIndex):
        self.pernas = list(pernas)
        self.meses = meses

    # ------------------------------------------------------------ exposicao
    def exposicao_mensal(self) -> pd.DataFrame:
        """Explode cada perna em meses. Uma linha por (perna, mes)."""
        linhas = []
        for i, pn in enumerate(self.pernas):
            ms = meses_do_produto(pn.produto, self.meses)
            if not ms:
                continue
            for m in ms:
                linhas.append({
                    "perna": i, "produto": pn.produto, "lado": pn.lado,
                    "sinal": pn.sinal, "mes_ref": m, "horas": horas_do_mes(m),
                    "mwmed": pn.mwmed, "mwmed_assinado": pn.sinal * pn.mwmed,
                    "preco_entrada": pn.preco_entrada,
                    "submercado": pn.submercado,
                    "energia_mwh": pn.mwmed * horas_do_mes(m),
                })
        return pd.DataFrame(linhas)

    def posicao_liquida(self) -> pd.DataFrame:
        """Exposicao liquida por mes — o que realmente esta em risco.

        E aqui que a dupla contagem morre: comprar Q4 e vender OUT/26 deixa
        outubro liquido em zero e preserva novembro e dezembro.
        """
        e = self.exposicao_mensal()
        if e.empty:
            return pd.DataFrame(columns=["mes_ref", "mwmed_liquido", "horas",
                                         "energia_liquida_mwh", "n_pernas",
                                         "preco_entrada_medio"])
        g = e.groupby("mes_ref").apply(lambda d: pd.Series({
            "mwmed_liquido": d.mwmed_assinado.sum(),
            "mwmed_bruto": d.mwmed.sum(),
            "horas": d.horas.iloc[0],
            "n_pernas": d.perna.nunique(),
            # preco de entrada medio ponderado pelo tamanho assinado; so faz
            # sentido quando ha posicao liquida
            "preco_entrada_medio": (
                float(np.average(d.preco_entrada, weights=d.mwmed_assinado.abs()))
                if d.mwmed_assinado.abs().sum() > 0 else np.nan),
        }), include_groups=False).reset_index()
        g["energia_liquida_mwh"] = g.mwmed_liquido * g.horas
        return g

    # ------------------------------------------------------------------ PnL
    def pnl(self, curvas: dict[str, pd.Series]) -> pd.DataFrame:
        """PnL por perna, mes e cenario. `curvas` = {'Esperado': serie, ...}."""
        e = self.exposicao_mensal()
        if e.empty:
            return pd.DataFrame()
        out = e.copy()
        for nome, curva in curvas.items():
            out[f"preco_{nome}"] = [float(curva.loc[m]) for m in out.mes_ref]
            out[f"pnl_{nome}"] = (out.sinal * out.mwmed * out.horas
                                  * (out[f"preco_{nome}"] - out.preco_entrada))
        return out

    def resumo_por_perna(self, curvas: dict[str, pd.Series]) -> pd.DataFrame:
        p = self.pnl(curvas)
        if p.empty:
            return p
        cols = {f"pnl_{k}": "sum" for k in curvas}
        g = p.groupby(["perna", "produto", "lado", "mwmed", "preco_entrada"]
                      ).agg({**cols, "energia_mwh": "sum"}).reset_index()
        base = list(curvas)[0]
        g["preco_medio_cenario"] = [
            preco_produto(r.produto, curvas[base], self.meses) for _, r in g.iterrows()]
        return g.sort_values("perna").reset_index(drop=True)

    def vpl(self, curvas: dict[str, pd.Series], taxa_aa: float, hoje: date,
            cenario: str = "Esperado") -> pd.DataFrame:
        """VPL mes a mes: o PnL de cada mes e descontado ate a liquidacao."""
        p = self.pnl(curvas)
        if p.empty:
            return p
        g = p.groupby("mes_ref")[f"pnl_{cenario}"].sum().reset_index()
        g.columns = ["mes_ref", "pnl"]
        g["data_liquidacao"] = [pd.Timestamp(m).to_period("M").to_timestamp("M").date()
                                for m in g.mes_ref]
        g["dias"] = [(d - hoje).days for d in g.data_liquidacao]
        g["fator_desconto"] = 1.0 / (1.0 + taxa_aa) ** (g.dias / 365.0)
        g["vp"] = g.pnl * g.fator_desconto
        g["vp_acumulado"] = g.vp.cumsum()
        return g

    # ----------------------------------------------------------------- risco
    @staticmethod
    def _por_mes(x, meses):
        """Aceita escalar ou Series por mes. A estrutura a termo de volatilidade
        nao e plana, entao usar a media do strip em vez do valor do vertice
        produzia dois valores para a mesma grandeza em abas diferentes."""
        if isinstance(x, pd.Series):
            v = pd.Series(meses).map(x).astype(float)
            return v.fillna(float(x.mean())).to_numpy()
        return float(x)

    def risco(self, var_preco_rs_mwh, es_preco_rs_mwh,
              limite: float) -> pd.DataFrame:
        """VaR e ES da posicao LIQUIDA, com contribuicao marginal por mes.

        A contribuicao usa a posicao liquida, nao a bruta: comprar e vender o
        mesmo mes nao consome risco de preco (sobra risco operacional e de
        credito, que este modulo nao mede).
        """
        pos = self.posicao_liquida()
        if pos.empty:
            return pos
        _v = self._por_mes(var_preco_rs_mwh, pos.mes_ref)
        _e = self._por_mes(es_preco_rs_mwh, pos.mes_ref)
        pos["var_mes"] = pos.mwmed_liquido.abs() * pos.horas * _v
        pos["es_mes"] = pos.mwmed_liquido.abs() * pos.horas * _e
        total = pos.var_mes.sum()
        pos["contrib_var_pct"] = pos.var_mes / total if total else 0.0
        pos["consumo_limite_pct"] = pos.var_mes / limite
        return pos

    def resumo(self, curvas: dict[str, pd.Series], var_preco: float, es_preco: float,
               limite: float, taxa_aa: float, hoje: date) -> dict:
        pos = self.posicao_liquida()
        risco = self.risco(var_preco, es_preco, limite)
        cen_vpl = "Convergencia" if "Convergencia" in curvas else list(curvas)[0]
        vpl = self.vpl(curvas, taxa_aa, hoje, cenario=cen_vpl)
        pn = self.pnl(curvas)
        tot = {f"pnl_{k}": float(pn[f"pnl_{k}"].sum()) for k in curvas}
        # VaR do book: soma dos VaR mensais (conservador, correlacao 1 entre meses).
        # Meses do mesmo submercado sao de fato altamente correlacionados; assumir
        # diversificacao seria otimista e nao ha amostra para estimar a matriz.
        var_total = float(risco.var_mes.sum()) if len(risco) else 0.0
        es_total = float(risco.es_mes.sum()) if len(risco) else 0.0
        # O pior cenario e entre os de CARREGO ATE A ENTREGA. Convergencia do
        # premio e outra dimensao de risco e nao entra nessa comparacao.
        entrega = {k: x for k, x in tot.items() if "Entrega" in k}
        pior = min(entrega.values()) if entrega else (min(tot.values()) if tot else 0.0)
        # ----------------------------------------------------------------
        # TAMANHO DO BOOK — nao existe um numero unico em MWm
        #
        # Duas maneiras erradas de resumir este book num MWm so:
        #
        #   SOMA das pernas (486)      MWm e potencia. Somar 43 de agosto com
        #                              188 de setembro conta a mesma potencia
        #                              cinco vezes; nunca coexistem.
        #   EQUIVALENTE FLAT (96,8)    aritmeticamente correto, mas descreve
        #                              uma posicao plana que nao e esta. O
        #                              shape (concentracao em set/out) E a
        #                              tese; o achatamento apaga justamente
        #                              o que se quer mostrar.
        #
        # Para strip curto de produtos MENSAIS, o tamanho e o proprio ladder
        # por vertice, mais dois agregados que nao dependem de shape:
        #
        #   energia   soma(MWm(m) x horas(m))              em MWh / GWh
        #   notional  soma(MWm(m) x horas(m) x preco(m))   em R$
        #
        # O equivalente flat continua calculado, rotulado como comparacao
        # contra produto flat — e o que faz sentido num flat de trimestre ou
        # de ano (o caso da visao anual da v5), nao aqui.
        #
        # A soma segue existindo porque e o insumo certo na alocacao de
        # orcamento de risco por vertice e no teto operacional por mes.
        # ----------------------------------------------------------------
        horas_tot = float(pos.horas.sum()) if len(pos) else 0.0
        e_abs = float(pos.energia_liquida_mwh.abs().sum()) if len(pos) else 0.0
        e_liq = float(pos.energia_liquida_mwh.sum()) if len(pos) else 0.0
        e_bruta = float((pos.mwmed_bruto * pos.horas).sum()) if len(pos) else 0.0
        # preco medio de entrada ponderado por MWh, nao por MWm: meses tem
        # numeros de horas diferentes (720 x 744) e o mes mais longo pesa mais.
        if len(pos) and e_bruta > 0:
            pe = float((pos.preco_entrada_medio * pos.mwmed_bruto * pos.horas).sum()
                       / e_bruta)
        else:
            pe = float("nan")
        notional = float((pos.preco_entrada_medio * pos.mwmed_bruto * pos.horas).sum()) \
            if len(pos) else 0.0
        # o ladder e a posicao; os agregados sao resumo dela
        ladder = [{"mes": rotulo_mes(m), "mwmed": float(r.mwmed_bruto),
                   "horas": float(r.horas), "mwh": float(r.mwmed_bruto * r.horas),
                   "preco_entrada": float(r.preco_entrada_medio)}
                  for m, r in pos.set_index("mes_ref").iterrows()] if len(pos) else []
        return {
            "n_pernas": len(self.pernas),
            "horas_totais": horas_tot,
            # -- TAMANHO: o ladder por vertice, e os agregados sem shape --
            "ladder": ladder,
            "energia_liquida_gwh": e_abs / 1000,
            "notional_brl": notional,
            "preco_entrada_medio_mwh": pe,
            # -- comparacao contra produto flat; nao e como o book se opera --
            "mwmed_equivalente_flat": (e_bruta / horas_tot) if horas_tot else 0.0,
            "mwmed_equivalente_liquido": (e_liq / horas_tot) if horas_tot else 0.0,
            # -- insumo interno de alocacao de risco; NAO e tamanho --
            "soma_mwm_pernas": float(pos.mwmed_bruto.sum()) if len(pos) else 0.0,
            "mwmed_bruto": float(pos.mwmed_bruto.sum()) if len(pos) else 0.0,
            "mwmed_liquido_abs": float(pos.mwmed_liquido.abs().sum()) if len(pos) else 0.0,
            "obs_mwm": ("nao ha MWm unico para strip mensal com quantidade "
                        "diferente por mes: o tamanho e o ladder por vertice, "
                        "resumido em energia (GWh) e notional (R$). "
                        "mwmed_equivalente_flat serve so para comparar com "
                        "produto flat; mwmed_bruto e soma e nao mede nada."),
            **tot,
            "pior_cenario": pior,
            "vpl": float(vpl.vp.sum()) if len(vpl) else 0.0,
            "var_total": var_total, "es_total": es_total,
            "consumo_limite": var_total / limite if limite else 0.0,
            # UMA definicao de retorno sobre risco em todo o projeto: PnL do
            # carrego esperado dividido pelo risco do book. A planilha usa esta
            # mesma; antes o JSON usava a convergencia e os dois numeros
            # apareciam com o mesmo nome.
            "retorno_risco_carrego": ((tot.get("pnl_Entrega_Esperado", 0.0) / var_total)
                                      if var_total else float("nan")),
            "retorno_risco_convergencia": ((tot.get("pnl_Convergencia", 0.0) / var_total)
                                           if var_total else float("nan")),
            "retorno_var": ((tot.get("pnl_Convergencia", tot.get("pnl_Esperado", 0.0))
                             / var_total) if var_total else np.nan),
            "premissa_correlacao": ("VaR somado entre meses (correlacao 1). Assumir "
                                    "diversificacao entre meses do mesmo submercado "
                                    "seria otimista e nao ha amostra para estimar a "
                                    "matriz de correlacao do termo."),
        }


def book_por_sinal(sinal: pd.DataFrame, mwmed_por_mes: float | dict,
                   curva_entrada: pd.Series, por_conviccao: bool = True,
                   mwmed_max: float = 120.0, neutralizar_nivel: bool = False
                   ) -> list[Perna]:
    """Monta um book a partir do sinal do modelo, uma perna por mes.

    Cada mes vira uma perna independente, com o SEU preco de entrada (o preco de
    mercado daquele mes) e o SEU tamanho. E o oposto de tratar o strip como um
    bloco unico com um preco medio.
    """
    pernas = []
    for _, r in sinal.iterrows():
        if r.acao == "FORA":
            continue
        m = pd.Timestamp(r.mes_ref)
        base = mwmed_por_mes.get(rotulo_mes(m), 0.0) if isinstance(mwmed_por_mes, dict) \
            else float(mwmed_por_mes)
        if por_conviccao and r.limiar:
            # Tamanho proporcional a conviccao: um edge de 2x o limiar merece o dobro
            # da posicao de um edge no limiar. Teto para nao concentrar tudo num mes.
            mw = min(base * float(r.conviccao_rs) / float(r.limiar), mwmed_max)
            mw = float(np.floor(mw))
        else:
            mw = base
        if not mw:
            continue
        pernas.append(Perna(
            produto=rotulo_mes(m),
            lado="C" if r.acao == "COMPRAR" else "V",
            mwmed=mw,
            # entrada e o preco NEGOCIAVEL do mes, nao o fair value do modelo
            preco_entrada=float(curva_entrada.loc[m]),
            observacao=(f"edge {float(r.edge if 'edge' in r.index else r.residuo_vs_mercado):+.2f} R$/MWh = "
                        f"{float(r.conviccao_rs)/float(r.limiar):.1f}x o limiar")))
    if neutralizar_nivel and pernas:
        # EXECUCAO COERENTE COM A TESE: um sinal de VALOR RELATIVO tem de ser
        # executado como SPREAD. Uma ponta solta carrega o risco de nivel
        # inteiro — no teste, uma compra seca de dezembro tem cauda de
        # -R$ 10,7 mi no cenario umido para capturar +R$ 0,6 mi de convergencia.
        # Aqui as pernas de sinal sao financiadas por pernas contrarias nos
        # meses de edge oposto, dimensionadas para zerar o MWmed liquido.
        liq = sum(p.sinal * p.mwmed for p in pernas)
        if abs(liq) > 1e-9:
            lado_falta = "V" if liq > 0 else "C"
            alvo_sinal = -1 if liq > 0 else 1
            cand = sinal[(np.sign(sinal.edge) == -alvo_sinal) &
                         (sinal.acao == "FORA")].copy()
            cand = cand[cand.conviccao_rs > 0].sort_values("conviccao_rs", ascending=False)
            if len(cand):
                peso = cand.conviccao_rs / cand.conviccao_rs.sum()
                for (_, r), w in zip(cand.iterrows(), peso):
                    mw = float(np.floor(abs(liq) * w))
                    if mw < 1:
                        continue
                    m = pd.Timestamp(r.mes_ref)
                    pernas.append(Perna(
                        produto=rotulo_mes(m), lado=lado_falta, mwmed=mw,
                        preco_entrada=float(curva_entrada.loc[m]),
                        observacao=(f"perna de financiamento: neutraliza o nivel; "
                                    f"edge {float(r.edge):+.2f} R$/MWh")))
    return pernas



def dimensionar_por_var(sinal: pd.DataFrame, var_preco_rs_mwh: float,
                        orcamento_var: float, curva_entrada: pd.Series,
                        mwmed_max_por_perna: float | None = None,
                        lote: float = 1.0) -> tuple[list[Perna], pd.DataFrame]:
    """O VaR determina o tamanho de cada vertice. E o VaR e o stop.

    LOGICA
    ------
    O orcamento de risco e repartido entre os vertices em proporcao a
    CONVICCAO (|edge|), e o tamanho de cada um sai da divisao pelo VaR unitario
    daquele mes:

        VaR_unitario(m) = var_preco x horas(m)          [R$ por MWmed]
        orcamento(m)    = orcamento_total x peso(m)
        MWmed(m)        = orcamento(m) / VaR_unitario(m)

    Assim o consumo total do limite bate com o orcamento por construcao: o
    ponto de parada e exatamente a otimizacao do uso do VaR, e nao um tamanho
    escolhido a mao. Meses mais longos (744h) recebem menos MWmed que meses
    curtos para o mesmo risco, o que e o correto.
    """
    d = sinal[sinal.acao.isin(["COMPRAR", "VENDER"])].copy()
    if d.empty or var_preco_rs_mwh <= 0:
        return [], pd.DataFrame()
    d["horas"] = [horas_do_mes(m) for m in d.mes_ref]
    d["var_unitario"] = var_preco_rs_mwh * d.horas
    d["peso"] = d.conviccao_rs / d.conviccao_rs.sum()
    d["orcamento_mes"] = orcamento_var * d.peso
    d["mwmed_bruto"] = d.orcamento_mes / d.var_unitario
    d["mwmed"] = np.floor(d.mwmed_bruto / lote) * lote
    d["limitado_por_liquidez"] = False
    if mwmed_max_por_perna:
        excede = d.mwmed > mwmed_max_por_perna
        d.loc[excede, "mwmed"] = mwmed_max_por_perna
        d.loc[excede, "limitado_por_liquidez"] = True
    d["var_consumido"] = d.mwmed * d.var_unitario
    d["pct_limite"] = d.var_consumido / orcamento_var if orcamento_var else 0.0

    pernas = [Perna(produto=rotulo_mes(r.mes_ref),
                    lado="C" if r.acao == "COMPRAR" else "V",
                    mwmed=float(r.mwmed),
                    preco_entrada=float(curva_entrada.loc[pd.Timestamp(r.mes_ref)]),
                    observacao=(f"edge {float(r.edge):+.2f} R$/MWh | "
                                f"VaR unitario R$ {r.var_unitario:,.0f}/MWm | "
                                f"consome R$ {r.var_consumido/1e6:.2f} mi"
                                + (" | CAPADO por liquidez" if r.limitado_por_liquidez else "")))
              for _, r in d.iterrows() if r.mwmed > 0]
    cols = ["mes_ref", "acao", "edge", "conviccao_rs", "horas", "var_unitario",
            "peso", "orcamento_mes", "mwmed_bruto", "mwmed", "var_consumido",
            "pct_limite", "limitado_por_liquidez"]
    return pernas, d[cols].reset_index(drop=True)


def risco_por_vertice(sinal: pd.DataFrame, seco: pd.Series, umido: pd.Series,
                      entrada: pd.Series, var_mtm_rs_mwh) -> pd.DataFrame:
    """Risco de CADA vertice, dependente do LADO. Dados reais do InfoPLD.

    O cenario adverso nao e o mesmo para os dois lados:
        COMPRADO -> adverso e o UMIDO   (preco cai)
        VENDIDO  -> adverso e o SECO    (preco sobe)

    perda_por_MWm = horas x max(0, -sinal x (preco_adverso - entrada))

    PISO: quando o cenario adverso e favoravel (acontece quando o mercado ja
    negocia alem do cenario), a perda de cenario da zero e o dimensionamento
    explodiria. Nesses casos vale o VaR de marcacao a mercado de 1 mes. O risco
    do vertice e o MAIOR dos dois, e a coluna 'risco_vinculante' diz qual mandou.
    """
    d = sinal[sinal.acao.isin(["COMPRAR", "VENDER"])].copy()
    if d.empty:
        return pd.DataFrame()
    d["sinal_num"] = np.where(d.acao == "COMPRAR", 1, -1)
    d["horas"] = [horas_do_mes(m) for m in d.mes_ref]
    d["entrada"] = [float(entrada.loc[pd.Timestamp(m)]) for m in d.mes_ref]
    d["cenario_adverso"] = np.where(d.sinal_num > 0, "UMIDO", "SECO")
    d["preco_adverso"] = [float((umido if s > 0 else seco).loc[pd.Timestamp(m)])
                          for m, s in zip(d.mes_ref, d.sinal_num)]
    d["preco_favoravel"] = [float((seco if s > 0 else umido).loc[pd.Timestamp(m)])
                            for m, s in zip(d.mes_ref, d.sinal_num)]
    d["perda_cenario_mwm"] = d.horas * np.maximum(
        0.0, -d.sinal_num * (d.preco_adverso - d.entrada))
    # var_mtm_rs_mwh aceita escalar ou Series por mes: a estrutura a termo de
    # volatilidade e decrescente, entao o VaR de marcacao nao e o mesmo em todos
    # os vertices.
    if isinstance(var_mtm_rs_mwh, pd.Series):
        _v = d.mes_ref.map(var_mtm_rs_mwh).astype(float)
        if _v.isna().any():
            _v = _v.fillna(float(var_mtm_rs_mwh.mean()))
    else:
        _v = float(var_mtm_rs_mwh)
    d["var_preco_mwh"] = _v
    d["var_mtm_mwm"] = _v * d.horas
    # RISCO = VaR. A perda no cenario adverso permanece na tabela como
    # informacao de stress, mas nao entra no dimensionamento nem no consumo de
    # limite: sao horizontes diferentes (1 mes de remarcacao contra carregar ate
    # a entrega) e maximizar entre as duas nao tem leitura unica de limite.
    d["risco_mwm"] = d.var_mtm_mwm
    d["risco_vinculante"] = "VaR de marcacao"
    d["cobertura_cenario"] = np.where(
        d.var_mtm_mwm > 0, d.perda_cenario_mwm / d.var_mtm_mwm, np.nan)
    d["ganho_favoravel_mwm"] = d.horas * np.maximum(
        0.0, d.sinal_num * (d.preco_favoravel - d.entrada))
    return d.reset_index(drop=True)


def dimensionar_por_risco(risco: pd.DataFrame, orcamento: float,
                          mwmed_max: float | None = None,
                          lote: float = 1.0) -> tuple[list[Perna], pd.DataFrame]:
    """Reparte o orcamento de risco entre os vertices, em proporcao a conviccao.

        MWmed(m) = orcamento x peso(m) / risco_mwm(m)

    Vertices de risco menor recebem MAIS MWmed para o mesmo consumo de limite —
    e o comportamento correto de um dimensionamento por risco, e nao por tamanho.
    """
    if risco.empty or orcamento <= 0:
        return [], pd.DataFrame()
    d = risco.copy()
    d["peso"] = d.conviccao_rs / d.conviccao_rs.sum()
    d["orcamento_mes"] = orcamento * d.peso
    d["mwmed_por_risco"] = np.where(d.risco_mwm > 0,
                                    d.orcamento_mes / d.risco_mwm, 0.0)
    d["mwmed"] = np.floor(d.mwmed_por_risco / lote) * lote
    d["capado_liquidez"] = False
    if mwmed_max:
        exc = d.mwmed > mwmed_max
        d.loc[exc, "mwmed"] = mwmed_max
        d.loc[exc, "capado_liquidez"] = True
    d["risco_consumido"] = d.mwmed * d.risco_mwm
    d["restricao"] = np.where(d.capado_liquidez, "liquidez", "risco")
    pernas = [Perna(produto=rotulo_mes(r.mes_ref),
                    lado="C" if r.sinal_num > 0 else "V",
                    mwmed=float(r.mwmed), preco_entrada=float(r.entrada),
                    observacao=(f"edge {float(r.edge):+.2f} | adverso {r.cenario_adverso} "
                                f"@ {r.preco_adverso:.2f} | risco R$ {r.risco_mwm:,.0f}/MWm "
                                f"({r.risco_vinculante}) | consome "
                                f"R$ {r.risco_consumido/1e6:.2f} mi"))
              for _, r in d.iterrows() if r.mwmed > 0]
    return pernas, d.reset_index(drop=True)
