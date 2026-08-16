"""Funcao REGISTRAR: cadastro, versionamento e persistencia da tese."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any

from copilot.quant.periods import DeliveryPeriod, mwmed_to_mwh
from src.database import repositories as R

MAX_SUMMARY_LINES = 5
DIRECTIONS = ("COMPRAR", "VENDER", "MANTER", "NAO_OPERAR")
STATUSES = ("RASCUNHO", "EM_DEBATE", "APROVADA", "ATIVA", "EM_REVISAO", "ENCERRADA", "INVALIDADA")
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "RASCUNHO": ("EM_DEBATE", "ENCERRADA"),
    "EM_DEBATE": ("RASCUNHO", "APROVADA", "ENCERRADA"),
    "APROVADA": ("ATIVA", "ENCERRADA"),
    "ATIVA": ("EM_REVISAO", "ENCERRADA", "INVALIDADA"),
    "EM_REVISAO": ("ATIVA", "ENCERRADA", "INVALIDADA"),
    "ENCERRADA": (),
    "INVALIDADA": (),
}
IMMUTABLE = ("APROVADA", "ATIVA", "EM_REVISAO", "ENCERRADA", "INVALIDADA")


def validate_summary(summary: str) -> None:
    linhas = [l for l in (summary or "").strip().splitlines() if l.strip()]
    if not linhas:
        raise ValueError("A tese precisa de resumo.")
    if len(linhas) > MAX_SUMMARY_LINES:
        raise ValueError(
            f"Resumo com {len(linhas)} linhas; o case limita a {MAX_SUMMARY_LINES}."
        )


def validate_range(low: Any, mid: Any, high: Any) -> None:
    """Resultado esperado e intervalo, nunca numero unico."""
    dados = [v for v in (low, mid, high) if v not in (None, "")]
    if not dados:
        return
    if len(dados) != 3:
        raise ValueError(
            "Resultado esperado deve ser intervalo completo (baixo/central/alto), "
            "nao numero unico."
        )
    a, b, c = (Decimal(str(v)) for v in (low, mid, high))
    if not (a <= b <= c):
        raise ValueError("Intervalo invalido: exige baixo <= central <= alto.")


def create_thesis(
    conn: sqlite3.Connection,
    *,
    title: str,
    summary: str,
    direction: str,
    product: str,
    submarket: str,
    owner: str,
    as_of: str,
    energy_source: str = "CONVENCIONAL",
    delivery_start: str | None = None,
    delivery_end: str | None = None,
    volume_mwm: Decimal | None = None,
    price_ref: Decimal | None = None,
    price_ref_date: str | None = None,
    horizon_days: int | None = None,
    review_date: str | None = None,
    expected_low: Decimal | None = None,
    expected_mid: Decimal | None = None,
    expected_high: Decimal | None = None,
    exit_condition: str | None = None,
    invalidation: str | None = None,
    actor: str = "trader",
) -> str:
    validate_summary(summary)
    validate_range(expected_low, expected_mid, expected_high)
    if direction not in DIRECTIONS:
        raise ValueError(f"Direcao invalida: {direction}. Aceitas: {', '.join(DIRECTIONS)}.")

    tid = R.new_id()
    agora = R.now_iso()
    conn.execute(
        "INSERT INTO theses (id, version, parent_id, title, summary, direction, product, "
        "energy_source, submarket, delivery_start, delivery_end, volume_mwm, price_ref, "
        "price_ref_date, horizon_days, review_date, expected_low, expected_mid, expected_high, "
        "exit_condition, invalidation, owner, as_of, status, change_reason, created_at, updated_at) "
        "VALUES (?,1,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'RASCUNHO',NULL,?,?)",
        (tid, title, summary, direction, product, energy_source, submarket, delivery_start,
         delivery_end, R.as_text(volume_mwm), R.as_text(price_ref), price_ref_date, horizon_days,
         review_date, R.as_text(expected_low), R.as_text(expected_mid), R.as_text(expected_high),
         exit_condition, invalidation, owner, as_of, agora, agora),
    )
    R.audit(conn, action="CREATE", entity="tese", entity_id=tid, actor=actor,
            actor_type="HUMANO", output_data={"title": title, "direction": direction}, as_of=as_of)
    return tid


def get_thesis(conn: sqlite3.Connection, thesis_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM theses WHERE id = ?", (thesis_id,)).fetchone()


def list_theses(conn: sqlite3.Connection, *, status: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM theses"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    return list(conn.execute(sql, params).fetchall())


def get_thesis_full(conn: sqlite3.Connection, thesis_id: str) -> dict[str, Any] | None:
    tese = get_thesis(conn, thesis_id)
    if not tese:
        return None
    q = lambda sql: list(conn.execute(sql, (thesis_id,)).fetchall())  # noqa: E731
    return {
        "thesis": dict(tese),
        "assumptions": [dict(r) for r in q("SELECT * FROM thesis_assumptions WHERE thesis_id=?")],
        "risks": [dict(r) for r in q("SELECT * FROM thesis_risks WHERE thesis_id=?")],
        "sources": [dict(r) for r in q("SELECT * FROM thesis_sources WHERE thesis_id=?")],
        "positions": [dict(r) for r in q("SELECT * FROM positions WHERE thesis_id=?")],
        "triggers": [dict(r) for r in q("SELECT * FROM triggers WHERE thesis_id=?")],
    }


def _assert_mutable(tese: sqlite3.Row) -> None:
    if tese["status"] in IMMUTABLE:
        raise ValueError(
            f"Tese em {tese['status']} e imutavel. Crie nova versao com motivo declarado."
        )


def add_assumption(
    conn: sqlite3.Connection, thesis_id: str, *, kind: str, statement: str,
    evidence_id: str, metric: str | None = None, expected: Decimal | None = None,
    tol_low: Decimal | None = None, tol_high: Decimal | None = None,
    unit: str | None = None, criticality: str = "MEDIA",
) -> str:
    """Premissa exige `evidence_id` valido. Sem lastro, nada e gravado."""
    tese = get_thesis(conn, thesis_id)
    if not tese:
        raise LookupError(f"Tese {thesis_id} nao encontrada.")
    _assert_mutable(tese)
    if not evidence_id or R.get_evidence(conn, evidence_id) is None:
        raise ValueError(
            "Premissa exige `evidence_id` existente. Afirmacao sem lastro nao e persistida."
        )
    monitoravel = bool(metric) and (tol_low is not None or tol_high is not None)
    aid = R.new_id()
    conn.execute(
        "INSERT INTO thesis_assumptions (id, thesis_id, kind, statement, metric, expected, "
        "tol_low, tol_high, unit, criticality, status, evidence_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (aid, thesis_id, kind, statement, metric, R.as_text(expected), R.as_text(tol_low),
         R.as_text(tol_high), unit, criticality,
         "VALIDA" if monitoravel else "NAO_MONITORAVEL", evidence_id, R.now_iso()),
    )
    R.audit(conn, action="CREATE", entity="premissa", entity_id=aid,
            evidence_ids=[evidence_id], output_data={"metric": metric})
    return aid


def add_risk(conn: sqlite3.Connection, thesis_id: str, *, category: str,
             description: str, severity: str, mitigation: str | None = None) -> str:
    rid = R.new_id()
    conn.execute(
        "INSERT INTO thesis_risks (id, thesis_id, category, description, severity, "
        "mitigation, created_at) VALUES (?,?,?,?,?,?,?)",
        (rid, thesis_id, category, description, severity, mitigation, R.now_iso()),
    )
    return rid


def add_source(conn: sqlite3.Connection, thesis_id: str, *, label: str,
               reference: str | None = None, evidence_id: str | None = None) -> str:
    sid = R.new_id()
    conn.execute(
        "INSERT INTO thesis_sources (id, thesis_id, label, reference, evidence_id, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (sid, thesis_id, label, reference, evidence_id, R.now_iso()),
    )
    return sid


def add_position(
    conn: sqlite3.Connection, thesis_id: str, *, side: str, instrument: str,
    submarket: str, volume_mwm: Decimal, price_entry: Decimal,
    delivery_start: str, delivery_end: str, metric_key: str, evidence_id: str,
    energy_source: str = "CONVENCIONAL",
) -> str:
    """Dimensionamento. MWh = MWmed x horas do periodo — calculado, nunca informado."""
    tese = get_thesis(conn, thesis_id)
    if not tese:
        raise LookupError(f"Tese {thesis_id} nao encontrada.")
    _assert_mutable(tese)
    if not evidence_id or R.get_evidence(conn, evidence_id) is None:
        raise ValueError("Posicao exige `evidence_id` existente (preco de referencia).")
    if side not in ("COMPRADO", "VENDIDO"):
        raise ValueError("Lado deve ser COMPRADO ou VENDIDO.")

    periodo = DeliveryPeriod(date.fromisoformat(delivery_start), date.fromisoformat(delivery_end))
    mwh = mwmed_to_mwh(Decimal(volume_mwm), periodo)
    notional = (mwh * Decimal(price_entry)).quantize(Decimal("0.01"))
    pid = R.new_id()
    conn.execute(
        "INSERT INTO positions (id, thesis_id, side, instrument, submarket, energy_source, "
        "volume_mwm, price_entry, delivery_start, delivery_end, hours, volume_mwh, notional, "
        "metric_key, evidence_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, thesis_id, side, instrument, submarket, energy_source, R.as_text(volume_mwm),
         R.as_text(price_entry), delivery_start, delivery_end, periodo.hours, R.as_text(mwh),
         R.as_text(notional), metric_key, evidence_id, R.now_iso()),
    )
    R.audit(conn, action="CREATE", entity="posicao", entity_id=pid, evidence_ids=[evidence_id],
            output_data={"side": side, "mwh": str(mwh), "hours": periodo.hours})
    return pid


def add_trigger(
    conn: sqlite3.Connection, thesis_id: str, *, rule_type: str, metric: str,
    operator: str, threshold: Decimal, unit: str, window: str = "spot",
    severity: str = "ATENCAO", description: str | None = None,
) -> str:
    """Gatilho avaliavel por maquina. Texto livre nao e gatilho."""
    if not metric or not metric.strip():
        raise ValueError(
            "Gatilho exige `metric`: sem serie mensuravel o Watchdog nao consegue avaliar."
        )
    if operator not in (">", ">=", "<", "<=", "delta_pct"):
        raise ValueError(f"Operador invalido: {operator}.")
    tid = R.new_id()
    conn.execute(
        "INSERT INTO triggers (id, thesis_id, rule_type, metric, operator, threshold, unit, "
        '"window", severity, active, description, created_at) VALUES (?,?,?,?,?,?,?,?,?,1,?,?)',
        (tid, thesis_id, rule_type, metric, operator, R.as_text(threshold), unit, window,
         severity, description, R.now_iso()),
    )
    R.audit(conn, action="CREATE", entity="gatilho", entity_id=tid,
            output_data={"metric": metric, "operator": operator, "threshold": str(threshold)})
    return tid


def set_status(conn: sqlite3.Connection, thesis_id: str, new_status: str,
               *, actor: str = "sistema", note: str | None = None) -> None:
    tese = get_thesis(conn, thesis_id)
    if not tese:
        raise LookupError(f"Tese {thesis_id} nao encontrada.")
    atual = tese["status"]
    if new_status not in TRANSITIONS.get(atual, ()):
        raise ValueError(
            f"Transicao {atual} -> {new_status} nao permitida. "
            f"Permitidas: {', '.join(TRANSITIONS.get(atual, ())) or 'nenhuma'}."
        )
    conn.execute("UPDATE theses SET status=?, updated_at=? WHERE id=?",
                 (new_status, R.now_iso(), thesis_id))
    R.audit(conn, action="STATUS_CHANGE", entity="tese", entity_id=thesis_id, actor=actor,
            input_data={"de": atual}, output_data={"para": new_status, "nota": note})


def new_version(conn: sqlite3.Connection, thesis_id: str, *, change_reason: str,
                actor: str = "trader") -> str:
    """Versao n+1 copiando premissas, posicoes e gatilhos. A versao n fica intacta."""
    if not change_reason or not change_reason.strip():
        raise ValueError("Nova versao exige motivo declarado.")
    original = get_thesis(conn, thesis_id)
    if not original:
        raise LookupError(f"Tese {thesis_id} nao encontrada.")
    novo = R.new_id()
    agora = R.now_iso()
    conn.execute(
        "INSERT INTO theses (id, version, parent_id, title, summary, direction, product, "
        "energy_source, submarket, delivery_start, delivery_end, volume_mwm, price_ref, "
        "price_ref_date, horizon_days, review_date, expected_low, expected_mid, expected_high, "
        "exit_condition, invalidation, owner, as_of, status, change_reason, created_at, updated_at) "
        "SELECT ?, version+1, id, title, summary, direction, product, energy_source, submarket, "
        "delivery_start, delivery_end, volume_mwm, price_ref, price_ref_date, horizon_days, "
        "review_date, expected_low, expected_mid, expected_high, exit_condition, invalidation, "
        "owner, as_of, 'RASCUNHO', ?, ?, ? FROM theses WHERE id = ?",
        (novo, change_reason, agora, agora, thesis_id),
    )
    # "window" e palavra reservada no Postgres (funcoes de janela) — precisa
    # de aspas duplas no SQL, mas a CHAVE do dict de retorno da linha continua
    # sem aspas (mesmo nome de coluna). `campos` (para indexar `linha[c]`) e
    # `colunas_sql` (para o texto SQL) sao mantidos separados de proposito.
    def _aspas_se_reservada(col: str) -> str:
        return f'"{col}"' if col == "window" else col

    for tabela, colunas in (
        ("thesis_assumptions",
         "kind, statement, metric, expected, tol_low, tol_high, unit, criticality, status, evidence_id"),
        ("thesis_risks", "category, description, severity, mitigation"),
        ("thesis_sources", "label, reference, evidence_id"),
        ("triggers",
         "rule_type, metric, operator, threshold, unit, window, severity, active, description"),
    ):
        campos = colunas.replace(" ", "").split(",")
        colunas_sql = ", ".join(_aspas_se_reservada(c) for c in campos)
        linhas = conn.execute(
            f"SELECT {colunas_sql} FROM {tabela} WHERE thesis_id = ?", (thesis_id,)
        ).fetchall()
        for linha in linhas:
            marcadores = ",".join("?" * (len(campos) + 3))
            conn.execute(
                f"INSERT INTO {tabela} (id, thesis_id, {colunas_sql}, created_at) VALUES ({marcadores})",
                (R.new_id(), novo, *[linha[c] for c in campos], agora),
            )
    R.audit(conn, action="VERSION", entity="tese", entity_id=novo, actor=actor,
            input_data={"origem": thesis_id}, output_data={"motivo": change_reason})
    return novo


def lineage(conn: sqlite3.Connection, thesis_id: str) -> list[sqlite3.Row]:
    cadeia, atual, vistos = [], get_thesis(conn, thesis_id), set()
    while atual is not None and atual["id"] not in vistos:
        cadeia.append(atual)
        vistos.add(atual["id"])
        atual = get_thesis(conn, atual["parent_id"]) if atual["parent_id"] else None
    return list(reversed(cadeia))


__all__ = [
    "DIRECTIONS", "MAX_SUMMARY_LINES", "STATUSES", "TRANSITIONS", "add_assumption",
    "add_position", "add_risk", "add_source", "add_trigger", "create_thesis",
    "get_thesis", "get_thesis_full", "lineage", "list_theses", "new_version",
    "set_status", "validate_range", "validate_summary",
]
