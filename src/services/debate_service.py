"""Funcao DESAFIAR: maquina de estados de 4 etapas, no maximo 4 chamadas ao LLM.

Sem LangGraph: quatro etapas sequenciais resolvem, e uma maquina de estados
simples e auditavel linha a linha.

    TESE -> CONTESTACAO -> VERIFICACAO -> VEREDITO   (+ REPLICA opcional)

O Orquestrador consolida mas **nao calcula e nao cria fato**: o veredito e
decidido por regra deterministica sobre o resultado do motor quant e do Claim
Verifier. O LLM redige; nao decide se o limite estourou.

Nova rodada nao apaga historico: incrementa `round_number`.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from typing import Any

from src.agents.llm_client import MAX_LLM_CALLS_PER_DEBATE, LLMClient, get_client
from src.agents.specialists import (
    AgentOutput,
    MarketAgent,
    RegulatoryAgent,
    RiskAgent,
    TraderAgent,
)
from src.config import get_settings
from src.database import repositories as R
from src.services import claim_verifier as CV
from src.services import risk_service as RS
from src.services import thesis_service as TS

VERDICTS = (
    "COMPRAR", "VENDER", "MANTER", "REDUZIR", "REESTRUTURAR",
    "NAO_OPERAR_DADOS_INSUFICIENTES", "BLOQUEADA_POR_RISCO",
)


def build_context(conn: sqlite3.Connection, thesis_id: str, *, as_of: str,
                  prices: dict[str, Decimal] | None = None) -> dict[str, Any]:
    """Monta o contexto do debate: tese, dados, risco e cenarios. Deterministico."""
    completa = TS.get_thesis_full(conn, thesis_id)
    if not completa:
        raise LookupError(f"Tese {thesis_id} nao encontrada.")

    posicoes = completa["positions"]
    if prices is None:
        prices = {}
        for p in posicoes:
            linha = R.latest_observation(conn, p["metric_key"], as_of=as_of)
            if linha:
                prices[p["metric_key"]] = Decimal(linha["value"])

    curva = R.latest_curve(conn, as_of=as_of, submarket=completa["thesis"]["submarket"])
    contexto: dict[str, Any] = {
        "as_of": as_of, "thesis": completa["thesis"], "assumptions": completa["assumptions"],
        "risks": completa["risks"], "positions": posicoes, "triggers": completa["triggers"],
        "curve": dict(curva) if curva else None, "prices": prices,
    }

    if posicoes and prices:
        try:
            contexto["risk"] = RS.compute_risk(
                conn, thesis_id, as_of=as_of, prices=prices,
                curve_origin=(curva["origin"] if curva else "PROXY_MODELO"),
                curve_classification=(curva["classification"] if curva else "demonstracao"),
            )
        except Exception as exc:
            contexto["risk"] = {"ok": False, "message": RS.INSUFFICIENT_MSG, "detail": str(exc)}
        risco = contexto["risk"]
        if risco.get("ok"):
            risco["limit_value"] = str(RS.var_limit(conn))
            try:
                contexto["scenarios"] = RS.compute_scenarios(
                    conn, thesis_id, as_of=as_of,
                    base_prices={k: Decimal(v) for k, v in prices.items()},
                    sigma_daily=risco["sigma_daily"],
                )
            except Exception as exc:
                contexto["scenarios"] = []
                risco.setdefault("warnings", []).append(f"Cenarios nao calculados: {exc}")
    else:
        contexto["risk"] = {"ok": False,
                            "message": "Tese sem posicao ou sem preco de marcacao no banco."}
    return contexto


def decide_verdict(contexto: dict[str, Any], relatorio: CV.VerificationReport) -> tuple[str, str]:
    """Regra deterministica. O LLM nao decide isto."""
    risco = contexto.get("risk") or {}
    tese = contexto["thesis"]

    if relatorio.blocked:
        return ("NAO_OPERAR_DADOS_INSUFICIENTES",
                "Claim Verifier bloqueou afirmacoes sem lastro: " + relatorio.summary())
    if not risco.get("ok"):
        return ("NAO_OPERAR_DADOS_INSUFICIENTES",
                risco.get("message", "Risco nao calculado com os dados disponiveis."))
    if not risco.get("within_limit"):
        return ("BLOQUEADA_POR_RISCO",
                f"VaR total de R$ {risco['var_total']} excede o limite de "
                f"R$ {risco.get('limit_value')}. Veto do agente de risco.")

    utilizacao = Decimal(risco["utilization"])
    if utilizacao >= Decimal("0.80"):
        return ("REDUZIR",
                f"Consumo de {utilizacao:.2%} do limite. Dentro, mas acima da faixa de "
                "atencao de 80%: reduzir sizing antes de executar.")

    cenarios = contexto.get("scenarios") or []
    nao_estresse = [c for c in cenarios if not c["is_stress"]]
    if nao_estresse and all(Decimal(c["pnl"]) < 0 for c in nao_estresse):
        return ("REESTRUTURAR",
                "Todos os cenarios nao-estresse dao perda. A direcao esta contra a "
                "estrutura de precos: reestruturar antes de montar.")

    if not tese.get("exit_condition") or not tese.get("invalidation"):
        return ("MANTER",
                "Sem condicao de saida ou de invalidacao declarada, a posicao nao pode "
                "ser vigiada. Completar o registro antes de executar.")

    direcao = tese["direction"]
    if direcao in ("COMPRAR", "VENDER"):
        return (direcao,
                f"Risco dentro do limite ({utilizacao:.2%}), cenarios calculados e "
                "gatilhos registrados. Direcao mantida.")
    return ("MANTER", "Tese registrada sem direcao operacional definida.")


def run_debate(
    conn: sqlite3.Connection,
    thesis_id: str,
    *,
    as_of: str | None = None,
    prices: dict[str, Decimal] | None = None,
    regulatory_question: str | None = None,
    client: LLMClient | None = None,
    actor: str = "trader",
) -> dict[str, Any]:
    """Executa uma rodada completa. No maximo 4 chamadas ao LLM."""
    settings = get_settings()
    as_of = as_of or settings.data_cut_off.isoformat()
    client = client or get_client()

    contexto = build_context(conn, thesis_id, as_of=as_of, prices=prices)
    if regulatory_question:
        contexto["regulatory_question"] = regulatory_question

    anterior = conn.execute(
        "SELECT MAX(round_number) AS r FROM debate_sessions WHERE thesis_id=?", (thesis_id,)
    ).fetchone()
    rodada = (anterior["r"] or 0) + 1

    sid = R.new_id()
    conn.execute(
        "INSERT INTO debate_sessions (id, thesis_id, thesis_version, round_number, mode, model, "
        "llm_calls, started_at, created_at) VALUES (?,?,?,?,?,?,0,?,?)",
        (sid, thesis_id, contexto["thesis"]["version"], rodada, client.mode,
         settings.anthropic_model if client.mode == "REAL" else None, R.now_iso(), R.now_iso()),
    )
    tese = conn.execute("SELECT status FROM theses WHERE id=?", (thesis_id,)).fetchone()
    if tese and tese["status"] == "RASCUNHO":
        TS.set_status(conn, thesis_id, "EM_DEBATE", actor=actor, note=f"rodada {rodada}")

    chamadas_iniciais = client.calls
    saidas: list[AgentOutput] = [
        TraderAgent().run(client, conn, contexto),         # etapa 1 (LLM)
        RiskAgent().run(client, conn, contexto),           # etapa 2 (LLM)
        RegulatoryAgent().run(client, conn, contexto),     # etapa 3a (deterministico)
        MarketAgent().run(client, conn, contexto),         # etapa 3b (deterministico)
    ]

    todas = [c for s in saidas for c in s.claims]
    texto = "\n\n".join(s.text for s in saidas)
    relatorio = CV.verify(conn, todas, cut_off=settings.data_cut_off.isoformat(), text=texto)
    CV.persist_claims(conn, relatorio, session_id=sid, thesis_id=thesis_id)

    veredito, justificativa = decide_verdict(contexto, relatorio)
    contra = next((s.text for s in saidas if s.agent == "RISCO"), "")
    fragil = _weakest_statement(contexto.get("assumptions", []))
    vieses = _detect_bias(contexto, relatorio)

    for seq, saida in enumerate(saidas, start=1):
        seguro = CV.render_safe(saida.text, relatorio) if saida.mode != "DETERMINISTICO" else saida.text
        conn.execute(
            "INSERT INTO debate_turns (id, session_id, seq, stage, agent, content, payload_json, "
            "evidence_ids, verifier_status, model, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (R.new_id(), sid, seq, saida.stage, saida.agent, seguro,
             json.dumps(saida.payload, ensure_ascii=False, default=str),
             ",".join(saida.evidence_ids), "BLOCKED" if relatorio.blocked else "VERIFIED",
             saida.model, R.now_iso()),
        )

    texto_veredito = (
        f"VEREDITO: {veredito}\n{justificativa}\n"
        f"Verificacao: {relatorio.summary()}\n"
        f"Modo: {client.mode} ({'IA real' if client.mode == 'REAL' else 'roteiro demonstrativo, nao e IA'})."
    )
    conn.execute(
        "INSERT INTO debate_turns (id, session_id, seq, stage, agent, content, payload_json, "
        "evidence_ids, verifier_status, model, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (R.new_id(), sid, len(saidas) + 1, "VEREDITO", "ORQUESTRADOR", texto_veredito,
         json.dumps({"verdict": veredito}, ensure_ascii=False),
         ",".join(relatorio.verified_ids), "BLOCKED" if relatorio.blocked else "VERIFIED",
         None, R.now_iso()),
    )

    usadas = client.calls - chamadas_iniciais
    conn.execute(
        "UPDATE debate_sessions SET verdict=?, counter_thesis=?, weakest_assumption=?, "
        "biases=?, rationale=?, llm_calls=?, ended_at=? WHERE id=?",
        (veredito, contra[:4000], fragil, "; ".join(vieses), justificativa,
         min(usadas, MAX_LLM_CALLS_PER_DEBATE), R.now_iso(), sid),
    )
    R.audit(conn, action="DEBATE", entity="debate", entity_id=sid, actor=actor,
            agent="ORQUESTRADOR", actor_type="AGENTE",
            input_data={"thesis_id": thesis_id, "round": rodada},
            output_data={"verdict": veredito, "blocked": relatorio.blocked, "llm_calls": usadas},
            evidence_ids=relatorio.verified_ids, as_of=as_of)

    return {
        "session_id": sid, "round": rodada, "mode": client.mode, "verdict": veredito,
        "rationale": justificativa, "counter_thesis": contra,
        "weakest_assumption": fragil, "biases": vieses,
        "verification": relatorio.summary(), "blocked": relatorio.blocked,
        "llm_calls": usadas, "turns": [
            {"agent": s.agent, "stage": s.stage, "mode": s.mode,
             "text": CV.render_safe(s.text, relatorio) if s.mode != "DETERMINISTICO" else s.text,
             "evidence_ids": s.evidence_ids} for s in saidas
        ] + [{"agent": "ORQUESTRADOR", "stage": "VEREDITO", "mode": "DETERMINISTICO",
              "text": texto_veredito, "evidence_ids": relatorio.verified_ids}],
        "risk": contexto.get("risk"), "scenarios": contexto.get("scenarios", []),
    }


def add_reply(conn: sqlite3.Connection, session_id: str, reply: str,
              *, actor: str = "trader") -> None:
    """Replica do trader. Entra no historico sem apagar nada."""
    proximo = conn.execute(
        "SELECT COALESCE(MAX(seq),0)+1 AS s FROM debate_turns WHERE session_id=?", (session_id,)
    ).fetchone()["s"]
    conn.execute(
        "INSERT INTO debate_turns (id, session_id, seq, stage, agent, content, created_at) "
        "VALUES (?,?,?,'REPLICA','TRADER_HUMANO',?,?)",
        (R.new_id(), session_id, proximo, reply, R.now_iso()),
    )
    conn.execute("UPDATE debate_sessions SET trader_reply=? WHERE id=?", (reply, session_id))
    R.audit(conn, action="REPLICA", entity="debate", entity_id=session_id, actor=actor,
            actor_type="HUMANO", output_data={"reply": reply[:1000]})


def list_sessions(conn: sqlite3.Connection, thesis_id: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM debate_sessions WHERE thesis_id=? ORDER BY round_number DESC",
        (thesis_id,)).fetchall())


def session_turns(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM debate_turns WHERE session_id=? ORDER BY seq", (session_id,)).fetchall())


def _weakest_statement(premissas: list[dict[str, Any]]) -> str | None:
    sem = [p for p in premissas if not p.get("metric")]
    if sem:
        return f"{sem[0]['statement']} (sem serie associada: nao e vigiavel)"
    altas = [p for p in premissas if p.get("criticality") == "ALTA"]
    alvo = (altas or premissas or [None])[0]
    return alvo["statement"] if alvo else None


def _detect_bias(contexto: dict[str, Any], relatorio: CV.VerificationReport) -> list[str]:
    """Vies medido por criterio numerico, nao por opiniao do modelo."""
    vieses: list[str] = []
    premissas = contexto.get("assumptions", [])
    if premissas:
        sem_metrica = sum(1 for p in premissas if not p.get("metric"))
        if sem_metrica / len(premissas) > 0.5:
            vieses.append(
                f"{sem_metrica} de {len(premissas)} premissas sem serie mensuravel: "
                "a tese nao e verificavel contra o mercado")
    if not contexto.get("scenarios"):
        vieses.append("Nenhum cenario adverso calculado: ancoragem no cenario central")
    else:
        adversos = [c for c in contexto["scenarios"] if Decimal(c["pnl"]) < 0]
        if not adversos:
            vieses.append("Nenhum cenario produz perda: calibragem otimista demais")
    curva = contexto.get("curve")
    if curva and curva["origin"] != "NEGOCIADA":
        vieses.append(f"Marcacao por {curva['origin']} tratada como preco de mercado")
    if relatorio.orphan_numbers:
        vieses.append(f"{len(relatorio.orphan_numbers)} numero(s) sem lastro no texto")
    return vieses or ["Nenhum vies detectado pelos criterios automaticos"]


__all__ = ["VERDICTS", "add_reply", "build_context", "decide_verdict", "list_sessions",
           "run_debate", "session_turns"]
