"""Funcao VIGIAR: Watchdog deterministico.

Roda pelo script (`--once` / `--interval`) e pela interface, usando **a mesma
camada de servico**. Nao depende da UI aberta.

As regras de disparo sao 100% deterministicas. O LLM pode redigir a explicacao
do alerta, mas nao decide se o limite foi atingido.

Ciclo: carregar observacoes -> freshness -> avaliar gatilhos -> reavaliar
premissas -> recalcular risco -> gerar alertas -> registrar auditoria.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any

from src.config import get_settings
from src.database import repositories as R
from src.services import risk_service as RS

#: Idade acima da qual a fonte e considerada atrasada.
STALE_DAYS = 10
#: Consumo do limite que ja gera alerta.
WARN_UTILIZATION = Decimal("0.80")

_OPS = {
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
}


def evaluate_operator(observado: Decimal, operador: str, limiar: Decimal,
                      anterior: Decimal | None = None) -> bool:
    """Avaliacao pura. Deterministica e testavel isoladamente."""
    if operador == "delta_pct":
        if anterior is None or anterior == 0:
            return False
        variacao = abs((observado - anterior) / anterior) * 100
        return variacao >= limiar
    fn = _OPS.get(operador)
    if fn is None:
        raise ValueError(f"Operador desconhecido: {operador}")
    return fn(observado, limiar)


def raise_alert(
    conn: sqlite3.Connection, *, thesis_id: str | None, severity: str, kind: str,
    message: str, evidence_id: str, as_of: str, run_id: str | None = None,
    trigger_id: str | None = None, assumption_id: str | None = None,
    observed: str | None = None, expected: str | None = None, unit: str | None = None,
    dedup_key: str | None = None, explanation: str | None = None,
) -> str:
    """Emite alerta persistente. Repetido em aberto incrementa o contador."""
    if not evidence_id:
        raise ValueError("Alerta exige `evidence_id`: o dado que disparou precisa ser rastreavel.")
    if dedup_key:
        aberto = conn.execute(
            "SELECT id, occurrences FROM alerts WHERE dedup_key=? AND acknowledged_at IS NULL",
            (dedup_key,)).fetchone()
        if aberto:
            conn.execute("UPDATE alerts SET occurrences=?, as_of=? WHERE id=?",
                         (aberto["occurrences"] + 1, as_of, aberto["id"]))
            return aberto["id"]
    aid = R.new_id()
    conn.execute(
        "INSERT INTO alerts (id, run_id, thesis_id, trigger_id, assumption_id, severity, kind, "
        "message, explanation, observed, expected, unit, dedup_key, occurrences, as_of, "
        "evidence_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
        (aid, run_id, thesis_id, trigger_id, assumption_id, severity, kind, message,
         explanation, observed, expected, unit, dedup_key, as_of, evidence_id, R.now_iso()),
    )
    R.audit(conn, action="ALERT_RAISED", entity="alerta", entity_id=aid,
            output_data={"kind": kind, "severity": severity, "message": message},
            evidence_ids=[evidence_id], as_of=as_of)
    return aid


def acknowledge(conn: sqlite3.Connection, alert_id: str, *, decision: str,
                rationale: str, by: str = "trader") -> None:
    """Reconhecimento exige decisao e justificativa registradas."""
    if not rationale or not rationale.strip():
        raise ValueError("Reconhecer alerta exige justificativa registrada.")
    conn.execute(
        "UPDATE alerts SET acknowledged_at=?, acknowledged_by=?, decision=? WHERE id=?",
        (R.now_iso(), by, decision, alert_id),
    )
    R.audit(conn, action="DECISION", entity="alerta", entity_id=alert_id, actor=by,
            actor_type="HUMANO", output_data={"decision": decision, "rationale": rationale})


def open_alerts(conn: sqlite3.Connection, *, thesis_id: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM alerts WHERE acknowledged_at IS NULL"
    params: list[Any] = []
    if thesis_id:
        sql += " AND thesis_id = ?"
        params.append(thesis_id)
    return list(conn.execute(sql + " ORDER BY created_at DESC", params).fetchall())


def run_once(conn: sqlite3.Connection, *, as_of: str | None = None,
             actor: str = "watchdog") -> dict[str, Any]:
    """Um ciclo completo. Nunca levanta por falha de fonte."""
    settings = get_settings()
    as_of = as_of or settings.data_cut_off.isoformat()
    run_id = R.new_id()
    conn.execute(
        "INSERT INTO watchdog_runs (id, started_at, as_of, status, created_at) "
        "VALUES (?,?,?,'OK',?)", (run_id, R.now_iso(), as_of, R.now_iso()),
    )

    alertas = 0
    avaliados = 0
    teses = conn.execute(
        "SELECT * FROM theses WHERE status IN ('APROVADA','ATIVA','EM_REVISAO','EM_DEBATE')"
    ).fetchall()

    # 1. Freshness — fonte atrasada vira alerta, nunca silencio.
    atrasadas = []
    for item in R.source_freshness(conn, as_of=as_of):
        if item["age_days"] > STALE_DAYS:
            atrasadas.append(f"{item['metric']} ({item['age_days']}d)")
            eid = R.create_evidence(
                conn, kind="CALCULO", source_name="Watchdog",
                locator=f"freshness:{item['metric']}@{as_of}",
                excerpt=(f"Metrica {item['metric']} sem atualizacao ha {item['age_days']} dias "
                         f"(ultima referencia {item['last_ref_date']}). Ausencia de dado nao e "
                         "premissa valida."),
                as_of=as_of, classification="observado",
            )
            raise_alert(conn, thesis_id=None, severity="ATENCAO", kind="FONTE_ATRASADA",
                        message=f"{item['metric']} sem atualizacao ha {item['age_days']} dias.",
                        explanation="Fonte atrasada compromete a vigilancia das premissas "
                                    "que dependem dela. Reingerir antes de confiar no alerta "
                                    "ausente.",
                        evidence_id=eid, as_of=as_of, run_id=run_id,
                        dedup_key=f"stale:{item['metric']}")
            alertas += 1

    # 2. Gatilhos e premissas por tese.
    for tese in teses:
        gatilhos = conn.execute(
            "SELECT * FROM triggers WHERE thesis_id=? AND active=1", (tese["id"],)).fetchall()
        for gatilho in gatilhos:
            avaliados += 1
            observacao = R.latest_observation(conn, gatilho["metric"], as_of=as_of)
            if observacao is None:
                continue
            observado = Decimal(observacao["value"])
            limiar = Decimal(gatilho["threshold"])
            historico = R.metric_history(conn, gatilho["metric"], as_of=as_of)
            anterior = Decimal(historico[-2]["value"]) if len(historico) > 1 else None
            if not evaluate_operator(observado, gatilho["operator"], limiar, anterior):
                continue
            severidade = gatilho["severity"]
            tipo = {"SAIDA": "GATILHO_SAIDA", "INVALIDACAO": "INVALIDACAO"}.get(
                gatilho["rule_type"], "GATILHO_ALERTA")
            raise_alert(
                conn, thesis_id=tese["id"], severity=severidade, kind=tipo,
                message=(f"{gatilho['metric']} = {observado} {gatilho['unit']} "
                         f"{gatilho['operator']} {limiar}: gatilho de "
                         f"{gatilho['rule_type'].lower()} atingido."),
                explanation=(
                    f"A tese '{tese['title']}' precisa ser reavaliada: a condicao de "
                    f"{gatilho['rule_type'].lower()} registrada no cadastro foi satisfeita pelo "
                    f"dado de {observacao['ref_date']} ({observacao['classification']}). "
                    f"{gatilho['description'] or ''}"),
                evidence_id=observacao["evidence_id"], as_of=as_of, run_id=run_id,
                trigger_id=gatilho["id"], observed=str(observado), expected=str(limiar),
                unit=gatilho["unit"], dedup_key=f"trig:{gatilho['id']}",
            )
            alertas += 1
            if severidade == "CRITICO" and tese["status"] == "ATIVA":
                conn.execute("UPDATE theses SET status='EM_REVISAO', updated_at=? WHERE id=?",
                             (R.now_iso(), tese["id"]))
                R.audit(conn, action="STATUS_CHANGE", entity="tese", entity_id=tese["id"],
                        actor=actor, output_data={"para": "EM_REVISAO",
                        "motivo": "alerta critico do Watchdog"}, as_of=as_of)

        # 3. Premissas contra a faixa de tolerancia.
        premissas = conn.execute(
            "SELECT * FROM thesis_assumptions WHERE thesis_id=? AND metric IS NOT NULL",
            (tese["id"],)).fetchall()
        for premissa in premissas:
            observacao = R.latest_observation(conn, premissa["metric"], as_of=as_of)
            if observacao is None:
                continue
            avaliados += 1
            valor = Decimal(observacao["value"])
            baixo = R.to_decimal(premissa["tol_low"])
            alto = R.to_decimal(premissa["tol_high"])
            fora = (baixo is not None and valor < baixo) or (alto is not None and valor > alto)
            novo = "VIOLADA" if fora else "VALIDA"
            if premissa["status"] != novo:
                conn.execute("UPDATE thesis_assumptions SET status=? WHERE id=?",
                             (novo, premissa["id"]))
            if fora:
                raise_alert(
                    conn, thesis_id=tese["id"], severity="ATENCAO", kind="PREMISSA_VIOLADA",
                    message=(f"Premissa fora da faixa: {premissa['metric']} = {valor} "
                             f"{premissa['unit'] or ''} (faixa {baixo}..{alto})."),
                    explanation=(f"A premissa '{premissa['statement']}' sustentava a tese "
                                 f"'{tese['title']}'. Com o dado de {observacao['ref_date']} ela "
                                 "deixou de valer — a tese precisa ser reavaliada antes que o "
                                 "prejuizo apareca."),
                    evidence_id=observacao["evidence_id"], as_of=as_of, run_id=run_id,
                    assumption_id=premissa["id"], observed=str(valor),
                    expected=f"{baixo}..{alto}", unit=premissa["unit"],
                    dedup_key=f"assum:{premissa['id']}",
                )
                alertas += 1

        # 4. Recalculo de risco e consumo do limite.
        posicoes = conn.execute(
            "SELECT metric_key FROM positions WHERE thesis_id=?", (tese["id"],)).fetchall()
        if posicoes:
            precos = {}
            for p in posicoes:
                linha = R.latest_observation(conn, p["metric_key"], as_of=as_of)
                if linha:
                    precos[p["metric_key"]] = Decimal(linha["value"])
            if len(precos) == len({p["metric_key"] for p in posicoes}):
                try:
                    risco = RS.compute_risk(conn, tese["id"], as_of=as_of, prices=precos,
                                            actor=actor)
                except Exception:
                    risco = {"ok": False}
                if risco.get("ok"):
                    avaliados += 1
                    utilizacao = Decimal(risco["utilization"])
                    if not risco["within_limit"] or utilizacao >= WARN_UTILIZATION:
                        raise_alert(
                            conn, thesis_id=tese["id"],
                            severity="CRITICO" if not risco["within_limit"] else "ATENCAO",
                            kind="VAR_LIMITE",
                            message=(f"VaR total R$ {risco['var_total']} "
                                     f"({utilizacao:.2%} do limite)."),
                            explanation=("Consumo do limite de R$ 50 milhoes acima da faixa "
                                         "aceitavel. Reduzir sizing ou encerrar posicao."),
                            evidence_id=risco["evidence_id"], as_of=as_of, run_id=run_id,
                            observed=risco["var_total"], expected=risco.get("limit_value"),
                            unit="R$", dedup_key=f"var:{tese['id']}",
                        )
                        alertas += 1

    status = "PARCIAL" if atrasadas else "OK"
    conn.execute(
        "UPDATE watchdog_runs SET ended_at=?, status=?, theses_checked=?, "
        "triggers_evaluated=?, alerts_raised=?, stale_sources=? WHERE id=?",
        (R.now_iso(), status, len(teses), avaliados, alertas, ", ".join(atrasadas), run_id),
    )
    R.audit(conn, action="WATCHDOG_RUN", entity="watchdog", entity_id=run_id, actor=actor,
            output_data={"theses": len(teses), "evaluated": avaliados, "alerts": alertas,
                         "status": status, "stale": atrasadas}, as_of=as_of)
    return {"run_id": run_id, "status": status, "theses_checked": len(teses),
            "triggers_evaluated": avaliados, "alerts_raised": alertas,
            "stale_sources": atrasadas, "as_of": as_of}


def simulate_market_update(
    conn: sqlite3.Connection, *, metric: str, value: Decimal, unit: str,
    as_of: str | None = None, actor: str = "trader",
) -> dict[str, Any]:
    """Botao "Simular atualizacao de mercado": insere dado e reavalia na hora.

    Grava como `demonstracao` — nunca se confunde com dado real.
    """
    settings = get_settings()
    as_of = as_of or settings.data_cut_off.isoformat()
    oid, eid = R.insert_observation(
        conn, metric=metric, value=value, unit=unit, ref_date=as_of, as_of=as_of,
        source_name="Simulacao da mesa", classification="demonstracao",
        excerpt=(f"DADO DEMONSTRATIVO inserido manualmente: {metric} = {value} {unit} "
                 f"em {as_of}. Nao e observacao de mercado."),
    )
    R.audit(conn, action="SIMULATE", entity="observacao", entity_id=oid, actor=actor,
            actor_type="HUMANO", output_data={"metric": metric, "value": str(value)},
            evidence_ids=[eid], as_of=as_of)
    resultado = run_once(conn, as_of=as_of, actor=actor)
    resultado["observation_id"] = oid
    resultado["evidence_id"] = eid
    return resultado


def recent_runs(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM watchdog_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall())


__all__ = ["STALE_DAYS", "WARN_UTILIZATION", "acknowledge", "evaluate_operator",
           "open_alerts", "raise_alert", "recent_runs", "run_once", "simulate_market_update"]
