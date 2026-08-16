"""Desafiar — uma chamada de IA, bloqueante, sobre números do motor.

Os números do desafio (premissa mais frágil, preço de virada por vértice,
viés de confirmação) são calculados aqui, em código, a partir do resultado de
`avaliar()`. A IA só escreve o contra-argumento e o texto — nunca um número
(invariante 1). Se a chamada falhar ou não houver `ANTHROPIC_API_KEY`, cai em
roteiro determinístico (`LLMResult.mode == "DEMO"`), nunca apresentado como IA
real.
"""

from __future__ import annotations

from typing import Any

from src.agents.llm_client import LLMClient
from src.services.formatting import fmt_money, fmt_rs_mwh

SYSTEM_PROMPT = (
    "Você é o Agente de Risco de uma mesa de comercialização de energia. Sua "
    "única função é desafiar a tese do trader com o contra-argumento mais forte "
    "possível — o caso em que o MERCADO está certo e o MODELO está errado. "
    "Nunca escreva números: todos os números do desafio já foram calculados e "
    "estão no prompt. Se precisar citar um número, copie-o exatamente do "
    "prompt, nunca calcule ou estime um novo. Responda em português, direto, "
    "sem gentileza performática — o trader precisa do argumento mais forte "
    "contra a própria posição, não de um resumo educado."
)


def _vertices_por_fragilidade(resultado: dict[str, Any]) -> list[dict[str, Any]]:
    """Para cada vértice VENDIDO, a partir de que preço ele vira prejuízo, e
    quão perto o cenário Seco (adverso para venda) já está desse ponto."""
    seco_risco = resultado["curva"]["seco_risco"]
    linhas = []
    for perna in resultado["book"]["ladder"]:
        mes_label = perna["mes"]
        preco_entrada = perna["preco_entrada"]
        # mapeia "AGO/26" -> chave "YYYY-MM-01" usada em curva.seco_risco
        from src.services.motor_service import _label_para_mes_ref

        mes_ref = _label_para_mes_ref(mes_label)
        preco_seco = seco_risco.get(mes_ref)
        gap = (preco_seco - preco_entrada) if preco_seco is not None else None
        linhas.append({
            "vertice": mes_label, "preco_entrada": preco_entrada,
            "preco_cenario_seco": preco_seco, "gap_ate_prejuizo": gap,
        })
    # mais fragil = menor gap ate o prejuizo (cenario seco mais perto de virar prejuízo)
    linhas.sort(key=lambda x: (x["gap_ate_prejuizo"] if x["gap_ate_prejuizo"] is not None else 1e18))
    return linhas


def _vies_confirmacao(
    ref_mercado_atual: dict[str, float], ref_mercado_base: dict[str, float], direcao: str
) -> tuple[bool, str]:
    """Editou só nos vértices que reforçam o lado que já tinha? (VENDER: subir
    a referência aumenta o prêmio observado e reforça o sinal de venda)."""
    alterados = [
        mes for mes, valor in ref_mercado_atual.items()
        if mes in ref_mercado_base and abs(float(valor) - float(ref_mercado_base[mes])) > 1e-9
    ]
    if not alterados:
        return False, "Nenhum vértice foi alterado em relação ao snapshot original."
    reforca = 1 if direcao == "VENDER" else -1
    direcoes = [
        1 if (ref_mercado_atual[m] - ref_mercado_base[m]) > 0 else -1
        for m in alterados
    ]
    so_reforça = all(d == reforca for d in direcoes)
    if so_reforça:
        return True, (
            f"Todos os {len(alterados)} vértice(s) alterado(s) ({', '.join(alterados)}) "
            f"foram movidos na direção que REFORÇA a tese de {direcao.lower()} — "
            "nenhum ajuste testou o lado contrário."
        )
    return False, (
        f"{len(alterados)} vértice(s) alterado(s); a alteração não é unânime na "
        "direção que reforça a tese."
    )


def montar_desafio(
    resultado: dict[str, Any],
    *,
    direcao: str,
    client: LLMClient,
    conn=None,
    ref_mercado_atual: dict[str, float] | None = None,
    ref_mercado_base: dict[str, float] | None = None,
) -> dict[str, Any]:
    book = resultado["book"]
    frageis = _vertices_por_fragilidade(resultado)
    mais_fragil_vertice = frageis[0] if frageis else None

    premissa_fragil = (
        f"A referência de mercado é PREMISSA sem fonte pública, e o prêmio de "
        f"nível de {fmt_rs_mwh(resultado.get('premio_nivel_rs_mwh'))} depende "
        f"inteiramente dela — sem ela não há sinal, só o fair value fundamental."
    )

    if mais_fragil_vertice and mais_fragil_vertice["preco_cenario_seco"] is not None:
        gap = mais_fragil_vertice["gap_ate_prejuizo"]
        cenario_quebra = (
            f"Vértice mais frágil: {mais_fragil_vertice['vertice']}, vendido a "
            f"{fmt_rs_mwh(mais_fragil_vertice['preco_entrada'])}. A partir desse preço a "
            f"perna vira prejuízo. No cenário Seco (adverso para posição vendida — úmido "
            f"é o favorável) o motor projeta "
            f"{fmt_rs_mwh(mais_fragil_vertice['preco_cenario_seco'])} para esse vértice, "
            f"{'já ACIMA da entrada' if gap < 0 else f'a {fmt_rs_mwh(gap)} da entrada'}."
        )
    else:
        cenario_quebra = "Não foi possível calcular o cenário Seco por vértice (dado ausente)."

    tem_vies, vies_texto = (
        _vies_confirmacao(ref_mercado_atual, ref_mercado_base, direcao)
        if ref_mercado_atual and ref_mercado_base else (False, "Sem comparação de sessão disponível.")
    )

    prompt_numeros = (
        f"Book: {book['n_pernas']} vértices, VaR total {fmt_money(book['var_total'])} "
        f"({book['consumo_limite']:.2%} do limite), notional {fmt_money(book['notional_brl'])}.\n"
        f"PnL por cenário: Seco {fmt_money(book['pnl_Entrega_Seco'])}, "
        f"Esperado {fmt_money(book['pnl_Entrega_Esperado'])}, "
        f"Úmido {fmt_money(book['pnl_Entrega_Umido'])}.\n"
        f"Premissa mais frágil (calculada): {premissa_fragil}\n"
        f"Cenário que quebra a posição (calculado): {cenario_quebra}\n"
        f"Viés de confirmação (calculado): {vies_texto}\n\n"
        "Escreva, em até 4 frases, o contra-argumento mais forte: o caso em que "
        "o mercado está certo e este modelo está errado. Use só os números acima "
        "se precisar citar algum — não invente nenhum novo."
    )

    demo_fallback = {
        "text": (
            "O mercado pode estar certo e o modelo errado se o prêmio observado "
            "refletir informação real sobre risco hidrológico que o modelo não "
            "captura — por exemplo, uma revisão de ENA ainda não publicada nos "
            "boletins usados. A referência de mercado sendo premissa de mesa, "
            "sem fonte auditável, é o ponto onde essa divergência mais provavelmente "
            "mora: se ela estiver sistematicamente alta, o sinal de venda está "
            "capturando ruído de leitura, não edge real."
        )
    }
    resposta = client.complete(
        system=SYSTEM_PROMPT, user=prompt_numeros, demo_fallback=demo_fallback,
        conn=conn, agent="AGENTE_RISCO_DESAFIO", max_tokens=400,
    )

    return {
        "premissa_fragil": premissa_fragil,
        "cenario_quebra": cenario_quebra,
        "contra_argumento": resposta.text,
        "vies_confirmacao_detectado": tem_vies,
        "vies_confirmacao_texto": vies_texto,
        "modo_ia": resposta.mode,
        "modelo": resposta.model,
    }


__all__ = ["montar_desafio"]
