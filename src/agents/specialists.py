"""Os cinco agentes do produto, como classes Python simples.

Divisao de trabalho, sem excecao:

* **Serviço de Dados / motor quant** produzem os numeros (deterministico).
* **Agentes** interpretam, argumentam e redigem — nunca calculam nem criam fato.
* **Orquestrador** conduz e consolida; nao calcula metrica nem cria fato.

Cada agente devolve `AgentOutput` com texto, claims declaradas e evidence_ids.
As claims sao o que o Claim Verifier confere depois.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence

from src.agents.llm_client import LLMClient, LLMResult
from src.database import repositories as R
from src.rag import store as RAG
from src.services.claim_verifier import Claim


@dataclass
class AgentOutput:
    agent: str
    stage: str
    text: str
    mode: str
    claims: list[Claim] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    model: str | None = None


def _fmt(valor: Any) -> str:
    try:
        return f"{Decimal(str(valor)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor)


# ===========================================================================
class TraderAgent:
    """Trader senior de comercializadora. Otimiza retorno ajustado ao risco."""

    name = "TRADER"
    SYSTEM = (
        "Voce e um trader senior de uma comercializadora brasileira de energia. "
        "Seu objetivo e a melhor decisao em retorno AJUSTADO AO RISCO, nao lucro maximo. "
        "Considere preco, curva, fundamentos, liquidez, exposicao, volume, horizonte, "
        "saida, invalidacao e qualidade dos dados. "
        "REGRA ABSOLUTA: nunca escreva um numero que nao esteja nos DADOS fornecidos. "
        "Se faltar dado, escreva 'Não disponível — evidência insuficiente.' "
        "Responda em portugues, no maximo 12 linhas."
    )

    def run(self, client: LLMClient, conn: sqlite3.Connection, contexto: dict[str, Any]) -> AgentOutput:
        tese = contexto["thesis"]
        risco = contexto.get("risk") or {}
        claims: list[Claim] = []
        evidencias: list[str] = []

        for p in contexto.get("positions", []):
            if p.get("evidence_id"):
                claims.append(Claim(f"Preco de entrada {p['price_entry']} R$/MWh", "NUMERICA",
                                    Decimal(str(p["price_entry"])), "R$/MWh", p["evidence_id"]))
                evidencias.append(p["evidence_id"])

        linhas = [
            f"POSICAO: {tese['direction']} {tese['product']} ({tese['submarket']}).",
            f"VOLUME: {tese.get('volume_mwm') or (contexto.get('positions') or [{}])[0].get('volume_mwm','n/d')} MWmed.",
            f"HORIZONTE: entrega {tese.get('delivery_start')} a {tese.get('delivery_end')}; "
            f"reavaliacao em {tese.get('review_date') or 'a definir'}.",
            f"JUSTIFICATIVA: {tese['summary'].splitlines()[0] if tese.get('summary') else 'n/d'}",
            f"PREMISSAS: {len(contexto.get('assumptions', []))} registradas, todas com evidencia.",
            f"SAIDA: {tese.get('exit_condition') or 'nao declarada'}.",
            f"INVALIDACAO: {tese.get('invalidation') or 'nao declarada'}.",
        ]
        if risco.get("ok"):
            linhas.append(
                f"CONSUMO DE LIMITE: R$ {_fmt(risco['var_total'])} de R$ "
                f"{_fmt(risco.get('limit_value', '50000000.00'))} "
                f"({Decimal(risco['utilization']) * 100:.2f}%)."
            )
        texto_demo = "\n".join(linhas)

        resultado = client.complete(
            system=self.SYSTEM,
            user=_prompt_dados(contexto) + "\n\nApresente a tese seguindo o roteiro: posicao, "
                 "preco, volume, horizonte, justificativa, premissas, fontes, saida, invalidacao.",
            demo_fallback={"text": texto_demo}, conn=conn, agent=self.name,
        )
        return AgentOutput(self.name, "TESE", resultado.text or texto_demo, resultado.mode,
                           claims, evidencias, resultado.payload, resultado.model)


# ===========================================================================
class RiskAgent:
    """Segunda linha independente. Pode bloquear a operacao."""

    name = "RISCO"
    SYSTEM = (
        "Voce e o agente de risco de uma mesa de energia, atuando como SEGUNDA LINHA "
        "INDEPENDENTE. Seu papel e atacar a tese, nao concordar com ela. "
        "Analise VaR, P&L, stress, concentracao, liquidez, basis risk, risco de modelo, "
        "qualidade dos dados, consumo do limite e risco de cauda. "
        "Voce pode: aprovar, recomendar reducao, recomendar hedge, solicitar reavaliacao, "
        "declarar dados insuficientes ou bloquear a operacao. "
        "REGRA ABSOLUTA: nunca escreva numero que nao esteja nos DADOS fornecidos. "
        "Aponte SEMPRE a premissa mais fragil e um cenario de perda concreto. "
        "Responda em portugues, no maximo 14 linhas."
    )

    def run(self, client: LLMClient, conn: sqlite3.Connection, contexto: dict[str, Any]) -> AgentOutput:
        risco = contexto.get("risk") or {}
        cenarios = contexto.get("scenarios", [])
        premissas = contexto.get("assumptions", [])
        claims: list[Claim] = []
        evidencias: list[str] = []

        if risco.get("ok"):
            claims.append(Claim(f"VaR total R$ {risco['var_total']}", "NUMERICA",
                                Decimal(risco["var_total"]), "R$", risco["evidence_id"]))
            evidencias.append(risco["evidence_id"])

        pior = min(cenarios, key=lambda c: Decimal(c["pnl"])) if cenarios else None
        if pior:
            claims.append(Claim(f"Perda no cenario {pior['scenario']}: R$ {pior['pnl']}",
                                "NUMERICA", Decimal(pior["pnl"]), "R$", pior["evidence_id"]))
            evidencias.append(pior["evidence_id"])

        fragil = _weakest(premissas)
        avisos = risco.get("warnings", []) if risco.get("ok") else [risco.get("message", "")]

        linhas = ["CONTRA-ARGUMENTO: o dimensionamento assume que a curva de marcacao se "
                  "realiza; o resultado depende de hidrologia, que e exatamente a variavel "
                  "que a mesa nao controla."]
        if fragil:
            linhas.append(f"PREMISSA MAIS FRAGIL: {fragil['statement']} "
                          f"(metrica {fragil.get('metric') or 'sem serie associada'}).")
        if pior:
            linhas.append(f"CENARIO DE PERDA: {pior['scenario']} — P&L R$ {_fmt(pior['pnl'])}. "
                          f"{pior['thesis_delta']}")
            linhas.append("RISCO DE CAUDA: o cenario EXTREMO e estresse, nao previsao; "
                          "serve para dimensionar, nao para descartar.")
        if risco.get("ok"):
            linhas.append(f"VaR: R$ {_fmt(risco['var_total'])} "
                          f"({Decimal(risco['utilization'])*100:.2f}% do limite). "
                          f"Add-ons: R$ {_fmt(risco['addons_total'])}.")
            linhas.append("SIZING: " + (
                "dentro do limite; ha folga para manter." if risco["within_limit"]
                else "ACIMA DO LIMITE — reduzir volume ate caber."))
        else:
            linhas.append(f"DADOS AUSENTES: {risco.get('message', 'risco nao calculado')}")
        for a in avisos:
            if a:
                linhas.append(f"ALERTA DE QUALIDADE: {a}")

        texto_demo = "\n".join(linhas)
        resultado = client.complete(
            system=self.SYSTEM,
            user=_prompt_dados(contexto) + "\n\nApresente: contra-argumento principal, premissa "
                 "mais fragil, cenario de perda, risco de cauda, VaR, consumo do limite, sizing "
                 "recomendado e dados ausentes.",
            demo_fallback={"text": texto_demo}, conn=conn, agent=self.name,
        )
        return AgentOutput(self.name, "CONTESTACAO", resultado.text or texto_demo, resultado.mode,
                           claims, evidencias, resultado.payload, resultado.model)


# ===========================================================================
class RegulatoryAgent:
    """Consulta o RAG. Toda conclusao carrega instituicao, documento e pagina."""

    name = "REGULATORIO"

    def run(self, client: LLMClient, conn: sqlite3.Connection,
            contexto: dict[str, Any]) -> AgentOutput:
        pergunta = contexto.get("regulatory_question") or (
            "lastro penalidade contabilizacao sazonalizacao modulacao MRE GSF curtailment"
        )
        trechos = RAG.search_with_evidence(conn, pergunta, as_of=contexto["as_of"], top_k=4)
        claims: list[Claim] = []
        evidencias = [t.evidence_id for t in trechos if t.evidence_id]

        if not trechos:
            texto = RAG.NOT_CONFIRMED + (
                " Nenhum documento do acervo cobre a pergunta na data-base "
                f"{contexto['as_of']}. Ingerir CCEE/ONS antes de concluir."
            )
        else:
            linhas = ["VERIFICACAO REGULATORIA (cada item com fonte, pagina e vigencia):"]
            for t in trechos:
                claims.append(Claim(t.text[:160], "FACTUAL", None, None, t.evidence_id))
                linhas.append(f"- {t.citation()}: “{t.text[:220].strip()}…”")
            linhas.append("Conclusao limitada ao que consta no acervo. "
                          "O que nao estiver aqui e tratado como nao confirmado.")
            texto = "\n".join(linhas)

        R.audit(conn, action="RAG_QUERY", entity="debate", agent=self.name,
                actor_type="AGENTE", tool="rag.search",
                input_data={"question": pergunta}, output_data={"hits": len(trechos)},
                evidence_ids=evidencias)
        return AgentOutput(self.name, "VERIFICACAO", texto, "DETERMINISTICO", claims, evidencias)


# ===========================================================================
class MarketAgent:
    """Consulta dados estruturados. Nao cria atualizacao ausente no banco."""

    name = "MERCADO"
    #: Metricas demonstrativas (seed) + metricas reais ingeridas por
    #: `scripts/update_sector_data.py` (ONS, CCEE, EPE, NOAA CPC — ver
    #: `docs/CONEXOES_DADOS_SETOR.md`). Ausencia de uma delas no banco vira
    #: "SEM DADO NO BANCO" abaixo, nunca numero inventado (P5/RF-36).
    WATCHED = (
        "pld_se_semanal", "cmo_se", "ena_sin_mlt_pct", "ear_sudeste_pct",
        "carga_sin_mwmed", "enso_oni_anomaly", "precip_prev_7d",
        "carga_verificada_mwmed_seco", "ear_verificada_pct_seco", "ena_bruta_pct_mlt_seco",
        "cmo_semanal_brl_mwh_seco", "pld_mensal_seco", "pld_semanal_seco",
    )

    def run(self, client: LLMClient, conn: sqlite3.Connection,
            contexto: dict[str, Any]) -> AgentOutput:
        as_of = contexto["as_of"]
        linhas = ["VERIFICACAO DE DADOS (data-base " + as_of + "):"]
        claims: list[Claim] = []
        evidencias: list[str] = []
        ausentes: list[str] = []

        metricas = list(dict.fromkeys(
            [p["metric_key"] for p in contexto.get("positions", [])] + list(self.WATCHED)
        ))
        for metrica in metricas:
            linha = R.latest_observation(conn, metrica, as_of=as_of)
            if linha is None:
                ausentes.append(metrica)
                continue
            idade = (RAG_date(as_of) - RAG_date(linha["ref_date"])).days
            claims.append(Claim(f"{metrica} = {linha['value']} {linha['unit']}", "NUMERICA",
                                Decimal(linha["value"]), linha["unit"], linha["evidence_id"]))
            evidencias.append(linha["evidence_id"])
            marca = "" if idade <= 10 else f"  [ATRASADA: {idade} dias]"
            linhas.append(f"- {metrica}: {linha['value']} {linha['unit']} "
                          f"({linha['classification']}, ref {linha['ref_date']}){marca}")

        if ausentes:
            linhas.append("SEM DADO NO BANCO (nao estimado, nao inventado): "
                          + ", ".join(ausentes))
        curva = contexto.get("curve")
        if curva:
            aviso = ("" if curva["origin"] == "NEGOCIADA"
                     else f"  [ATENCAO: origem {curva['origin']} — nao e preco negociado, "
                          f"proxy de {curva.get('proxy_of') or 'nao declarado'}]")
            linhas.append(f"- curva {curva['curve_name']} ({curva['quote_type']}, "
                          f"{curva['classification']}){aviso}")

        R.audit(conn, action="DATA_QUERY", entity="debate", agent=self.name,
                actor_type="AGENTE", tool="repositories.latest_observation",
                output_data={"metrics": len(claims), "missing": ausentes},
                evidence_ids=evidencias, as_of=as_of)
        return AgentOutput(self.name, "VERIFICACAO", "\n".join(linhas), "DETERMINISTICO",
                           claims, evidencias, {"missing": ausentes})


def RAG_date(texto: str):  # helper local, evita import extra no topo
    from datetime import date as _d

    return _d.fromisoformat(texto)


def _weakest(premissas: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Premissa mais fragil: sem metrica primeiro, depois criticidade alta."""
    if not premissas:
        return None
    sem_metrica = [p for p in premissas if not p.get("metric")]
    if sem_metrica:
        return sem_metrica[0]
    altas = [p for p in premissas if p.get("criticality") == "ALTA"]
    return (altas or list(premissas))[0]


def _prompt_dados(contexto: dict[str, Any]) -> str:
    """Bloco DADOS: os unicos numeros que o agente pode usar."""
    import json

    seguro = {
        "as_of": contexto.get("as_of"),
        "thesis": {k: contexto["thesis"].get(k) for k in
                   ("title", "summary", "direction", "product", "submarket",
                    "delivery_start", "delivery_end", "volume_mwm", "price_ref",
                    "exit_condition", "invalidation", "review_date")},
        "positions": contexto.get("positions", []),
        "assumptions": [{"statement": a.get("statement"), "metric": a.get("metric"),
                         "criticality": a.get("criticality")}
                        for a in contexto.get("assumptions", [])],
        "risk": contexto.get("risk"),
        "scenarios": contexto.get("scenarios"),
        "curve": contexto.get("curve"),
    }
    return (
        "DADOS (fonte unica de numeros; nao invente nada fora daqui):\n"
        + json.dumps(seguro, ensure_ascii=False, indent=2, default=str)
    )


__all__ = ["AgentOutput", "MarketAgent", "RegulatoryAgent", "RiskAgent", "TraderAgent"]
