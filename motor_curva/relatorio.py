"""Gera outputs/entrega_2.md. Todo numero vem de campo calculado no ctx."""
from __future__ import annotations
from pathlib import Path
import numpy as np


def brl(x, casas=1, mi=True):
    if x is None or not np.isfinite(x):
        return "n/d"
    return f"R$ {x/1e6:,.{casas}f} mi".replace(",", "X").replace(".", ",").replace("X", ".") if mi \
        else f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def num(x, casas=2):
    if x is None or not np.isfinite(x):
        return "n/d"
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar(caminho: Path, c: dict):
    p = c["posicao"]; e = c["efeitos"]; v = c["var_info"]
    cb = c["curva"]
    cond = p["tipo"] != "DIRECIONAL"
    L = []
    A = L.append

    A(f"# Entrega 2 — Proposta de Posição")
    A("")
    A(f"**{c['nome_curva']}**  ")
    A(f"Status do run: **{c['status']}** · Data de corte: {c['data_corte']} · Gerado em {c['gerado_em']}")
    A("")
    if c["status"] != "DEFINITIVO":
        A(f"> ⚠️ {c['status_motivo']}")
        A("")
    A("---")
    A("")

    A("## 1. Tese")
    A("")
    for ln in c["tese"]:
        A(ln)
    A("")

    A("## 2. Instrumento, direção e preço de entrada")
    A("")
    A(f"- **Produto:** {c['produto']}")
    A(f"- **Vigência:** {cb.mes_ref.min():%b/%Y} a {cb.mes_ref.max():%b/%Y} ({int(c['horas_total'])} horas)")
    if cond:
        A(f"- **Tipo de recomendação:** CONDICIONAL — {p.get('motivo','')}")
        A(f"- **Comprar até:** {num(p['comprar_ate'])} R$/MWh")
        A(f"- **Vender acima de:** {num(p['vender_acima_de'])} R$/MWh")
    else:
        A(f"- **Direção:** {'COMPRADO' if p['direcao']>0 else 'VENDIDO'}")
        A(f"- **Preço de entrada de referência:** {num(p['preco_entrada'])} R$/MWh ({c['fonte_entrada']})")
        A(f"- **Edge vs fair value:** {num(p['edge'])} R$/MWh")
    A(f"- **Fair value flat calculado:** {num(p['fair_value_flat'])} R$/MWh — FAIR_VALUE")
    A("")

    A("## 3. Dimensionamento")
    A("")
    A(f"- **Tamanho:** {num(p.get('mwm',0),0)} MWm")
    A(f"- **Energia:** {num(p.get('mwm',0)*c['horas_total']/1000,0)} GWh no período")
    A(f"- **Orçamento de risco usado:** {brl(c['orcamento'])} de teto de {brl(c['limite'])} "
      f"(buffer de {num((1-c['frac_orcamento'])*100,0)}%)")
    A("")

    A("## 4. VaR")
    A("")
    A(f"- **Fator de risco:** {v['fator_risco']}")
    A(f"- **Metodologia principal:** {v['metodo']}")
    A(f"- **Confiança / horizonte / λ:** {v['conf']:.0%} · {v['horizonte_meses']:.0f} mês · λ={v['lambda']}")
    A(f"- **Amostra:** {v['n_obs']} remarcações mensais do mesmo strip, walk-forward; "
      f"vol EWMA mensal de {v['vol_ewma_mensal']:.2%}")
    A(f"- **VaR de preço:** {num(v['var_preco'])} R$/MWh · **ES de preço:** {num(v['es_preco'])} R$/MWh")
    A(f"- **VaR da posição:** {brl(c['var_brl'])} = **{num(c['consumo_limite']*100,1)}% do limite de R$ 50 mi**")
    A(f"- **Expected Shortfall da posição:** {brl(c['es_brl'])}")
    A(f"- **Challenger 1 (histórico sobre o mesmo forward):** {num(v['var_preco_hist'])} R$/MWh")
    A(f"- **Challenger 2 (FHS sobre PLD spot):** {num(c['var_spot'])} R$/MWh — "
      f"{num(c['var_spot']/max(v['var_preco'],1e-9),1)}x o VaR do termo. Spot não é o fator de "
      f"risco de um contrato a termo; serve de teto, não de medida.")
    A("")
    A(f"**Restrição que dimensionou a posição: {c['restricao'].upper()}.** "
      f"Por VaR caberiam {num(c['mwm_var'],0)} MWm; por liquidez, {num(c['mwm_liq'],0)} MWm; "
      f"pela perda no cenário adverso carregado até a entrega, {num(c['mwm_cen'],0)} MWm.")
    A("")

    A("## 5. Resultado esperado (intervalo, não ponto)")
    A("")
    A("| Cenário | Preço médio (R$/MWh) | PnL | Prob. |")
    A("|---|---|---|---|")
    for nome in ("base", "seco", "umido"):
        A(f"| {nome.capitalize()} | {num(c['preco_cen'][nome])} | {brl(c['pnl_cen'][nome])} | "
          f"{c['prob'][nome]:.0%} |")
    A(f"| **Esperado (ponderado)** | **{num(c['preco_esperado'])}** | **{brl(c['pnl_esperado'])}** | — |")
    A("")
    A(f"- **Intervalo P5–P95 do PnL:** {brl(c['pnl_p5'])} a {brl(c['pnl_p95'])}")
    A(f"- **VPL até 31/12/2026** (taxa {c['taxa_desconto']:.2%} a.a.): {brl(c['vpl'])}")
    A(f"- **Retorno / VaR:** {num(c['ret_var'])} · **Retorno / ES:** {num(c['ret_es'])}")
    A("")

    A("## 6. Horizonte e reavaliação")
    A("")
    A(f"- **Horizonte:** até {c['fim_produto']} (fim do ultimo mes do produto)")
    A(f"- **Reavaliação:** {c['data_reavaliacao']} — após a próxima revisão semanal do DECOMP "
      f"e a publicação do PMO subsequente")
    A("")

    A("## 7. Gatilhos de saída")
    A("")
    for g in c["gatilhos"]:
        A(f"- {g}")
    A("")

    A("## 8. O que invalida a tese")
    A("")
    for g in c["invalidam"]:
        A(f"- {g}")
    A("")

    A("## 9. Premissas e fontes")
    A("")
    A("| Premissa | Valor | Rótulo |")
    A("|---|---|---|")
    for k, val, just in c["premissas_tab"]:
        rot = "CALCULADO" if str(just).startswith("CALCULADO") else "PREMISSA"
        A(f"| {k} | {val} | {rot} |")
    A("")
    A("**Fontes efetivamente utilizadas:**")
    A("")
    for it in c["manifesto"].itertuples(index=False):
        A(f"- {it.instituicao} · {it.conjunto} · `{it.sha256[:12] if isinstance(it.sha256,str) else 'n/d'}` "
          f"· {it.url_origem}")
    A("")

    A("## 10. Cenários hidrológicos")
    A("")
    A(f"Regimes classificados por índice combinado ENA %MLT (65%) e EAR %max (35%), com corte nos "
      f"quantis {c['q_seco']:.0%} e {c['q_umido']:.0%}. Efeito sobre log(preço) estimado por MQO com "
      f"dummies de mês, sobre {e['n_obs']} observações ({e['amostra_de']} a {e['amostra_ate']}).")
    A("")
    A("| Cenário | Multiplicador | Erro padrão | t | n |")
    A("|---|---|---|---|---|")
    A(f"| Seco | {num(e['k_seco'],3)} | {num(e['ep_seco'],3)} | {num(e['t_seco'],2)} | {e['n_seco']} |")
    A(f"| Base | 1,000 | — | — | {e['n_obs']-e['n_seco']-e['n_umido']} |")
    A(f"| Úmido | {num(e['k_umido'],3)} | {num(e['ep_umido'],3)} | {num(e['t_umido'],2)} | {e['n_umido']} |")
    A("")
    A(f"- Ordenação Seco > Base > Úmido: **{'coerente' if e['ordenacao_coerente'] else 'INVERTIDA — investigar'}**")
    A(f"- R² do modelo de regime: {num(e['r2'],3)}")
    A(f"- VaR por cenário: Base {brl(c['var_cen']['base'])} · Seco {brl(c['var_cen']['seco'])} · "
      f"Úmido {brl(c['var_cen']['umido'])}")
    A("")

    A("## 11. Impacto na margem e no VPL até 31/12")
    A("")
    A(f"- Contribuição esperada de margem no exercício: {brl(c['pnl_esperado'])}")
    A(f"- VPL a {c['taxa_desconto']:.2%} a.a.: {brl(c['vpl'])}")
    A(f"- Perda em stress (ES): {brl(c['es_brl'])}")
    A("")

    A("## 12. Limitações e risco de base")
    A("")
    for g in c["limitacoes"]:
        A(f"- {g}")
    A("")
    A("---")
    A("")
    A("*Nenhum número deste documento foi escrito por LLM. Todos vêm de campos calculados pelo "
      "pipeline em `src/`, reproduzíveis por `make all`. A camada de IA foi usada apenas para "
      "redação, crítica de premissas e desenho de cenários adversos.*")

    Path(caminho).write_text("\n".join(L), encoding="utf-8")
