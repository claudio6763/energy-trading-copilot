"""Vigiar — três gatilhos fixos, sessão contra registro salvo.

Demonstrável com um snapshot só: nunca compara snapshot contra snapshot (isso
nunca dispararia nada). Compara os PARÂMETROS REGISTRADOS na tese (o
`ref_mercado_json`/`premio_nivel_rs_mwh`/`consumo_limite` gravados em
`thesis_book`) contra os PARÂMETROS CORRENTES DA SESSÃO — o que o trader (ou a
banca, na defesa) acabou de digitar. `avaliar()` roda de novo sobre o mesmo
snapshot com a referência nova; nada aqui recalcula o que o motor já calculou.

Side-aware: o cenário adverso depende do lado (vendido -> seco é o que
invalida), e essa lógica já mora no motor (`book.risco_por_vertice`); aqui só
se lê o resultado, nunca se fixa a direção na tela.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from src.motor.avaliar import avaliar
from src.motor.snapshot import MotorSnapshot
from src.services.formatting import fmt_pct, fmt_rs_mwh

LIMIAR_PREMIO_RS_MWH = 15.0
LIMIAR_CONSUMO_LIMITE = 0.60


def avaliar_gatilhos(
    livro: dict[str, Any],
    snapshot: MotorSnapshot,
    ref_mercado_sessao: dict[str, float],
    *,
    limite_var: Decimal = Decimal("50000000.00"),
) -> list[dict[str, Any]]:
    """Recalcula com `ref_mercado_sessao` e compara contra `livro` (salvo).

    Devolve uma lista de alertas — cada um diz qual premissa caiu, qual
    número mudou, de quanto para quanto, e qual gatilho de saída isso aciona.
    """
    ref_salva: dict[str, float] = json.loads(livro["ref_mercado_json"]) if isinstance(
        livro["ref_mercado_json"], str
    ) else livro["ref_mercado_json"]

    alertas: list[dict[str, Any]] = []

    # 1. referencia de vertice mudou
    for mes, valor_salvo in ref_salva.items():
        valor_sessao = ref_mercado_sessao.get(mes)
        if valor_sessao is not None and abs(float(valor_sessao) - float(valor_salvo)) > 1e-9:
            alertas.append({
                "gatilho": "Referência de vértice mudou",
                "severidade": "ATENÇÃO",
                "premissa": f"referência de mercado de {mes}",
                "de": fmt_rs_mwh(valor_salvo),
                "para": fmt_rs_mwh(valor_sessao),
                "mensagem": (
                    f"A referência de {mes} saiu de {fmt_rs_mwh(valor_salvo)} (registrado) "
                    f"para {fmt_rs_mwh(valor_sessao)} (sessão)."
                ),
                "gatilho_de_saida_acionado": "revisar prêmio e dimensionamento do vértice",
            })

    try:
        novo = avaliar(snapshot, ref_mercado_sessao, limite_var)
    except ValueError as exc:
        alertas.append({
            "gatilho": "Referência incompleta", "severidade": "CRÍTICO",
            "premissa": "referência de mercado da sessão", "de": "—", "para": "—",
            "mensagem": str(exc), "gatilho_de_saida_acionado": None,
        })
        return alertas

    premio_salvo = float(livro["premio_nivel_rs_mwh"]) if livro.get("premio_nivel_rs_mwh") else None
    premio_novo = novo.get("premio_nivel_rs_mwh")
    if premio_novo is not None and premio_novo < LIMIAR_PREMIO_RS_MWH:
        alertas.append({
            "gatilho": "Prêmio abaixo do limiar de sinal",
            "severidade": "CRÍTICO",
            "premissa": "prêmio de nível", "de": fmt_rs_mwh(premio_salvo), "para": fmt_rs_mwh(premio_novo),
            "mensagem": (
                f"Prêmio de nível caiu para {fmt_rs_mwh(premio_novo)}, abaixo do limiar de "
                f"{fmt_rs_mwh(LIMIAR_PREMIO_RS_MWH)} — sinal deixa de justificar a posição."
            ),
            "gatilho_de_saida_acionado": "prêmio abaixo de R$ 15/MWh (declarado na tese)",
        })

    consumo_salvo = float(livro["consumo_limite"]) if livro.get("consumo_limite") else None
    consumo_novo = novo["book"]["consumo_limite"]
    if consumo_novo > LIMIAR_CONSUMO_LIMITE:
        alertas.append({
            "gatilho": "Consumo do limite acima do orçamento",
            "severidade": "ATENÇÃO" if consumo_novo < 1.0 else "CRÍTICO",
            "premissa": "consumo do limite de VaR",
            "de": fmt_pct(consumo_salvo), "para": fmt_pct(consumo_novo),
            "mensagem": (
                f"Consumo do limite foi de {fmt_pct(consumo_salvo)} (registrado) para "
                f"{fmt_pct(consumo_novo)} (sessão) — acima do orçamento de "
                f"{fmt_pct(LIMIAR_CONSUMO_LIMITE)}."
            ),
            "gatilho_de_saida_acionado": (
                "aprovação bloqueada por código (P8)" if consumo_novo >= 1.0
                else "revisão obrigatória do tamanho"
            ),
        })

    return alertas


__all__ = ["LIMIAR_CONSUMO_LIMITE", "LIMIAR_PREMIO_RS_MWH", "avaliar_gatilhos"]
