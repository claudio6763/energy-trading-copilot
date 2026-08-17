"""Repositorios sqlite3 e trilha de auditoria.

Regras que valem em todo o modulo:

* `evidence_id` e gerado aqui, automaticamente, para todo fato que entra;
* `Decimal` entra e sai como texto — nunca passa por `float`;
* nenhuma consulta de dado de mercado devolve linha posterior ao `as_of` pedido;
* toda escrita relevante deixa linha em `audit_log`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Sequence

from copilot.common.ids import new_ulid

VALID_CLASSIFICATIONS = (
    "observado", "projetado", "negociado", "indicativo", "proxy", "manual", "demonstracao",
)
#: Classificacoes que nao representam preco negociado e pagam add-on de proxy.
PROXY_CLASSIFICATIONS = ("proxy", "projetado", "indicativo", "demonstracao")


def new_id() -> str:
    return new_ulid()


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def to_decimal(value: Any) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def upsert_row(
    conn: Any, *, table: str, columns: Sequence[str], values: Sequence[Any],
    conflict_cols: Sequence[str],
) -> None:
    """Grava substituindo por chave unica. `INSERT OR REPLACE` (SQLite) nao
    existe no Postgres — la vira `INSERT ... ON CONFLICT (...) DO UPDATE`,
    igual em efeito (linha da chave unica e sobrescrita, resto intocado)."""
    placeholders = ",".join("?" * len(columns))
    cols_sql = ",".join(columns)
    if isinstance(conn, sqlite3.Connection):
        conn.execute(
            f"INSERT OR REPLACE INTO {table} ({cols_sql}) VALUES ({placeholders})",
            values,
        )
        return
    update_cols = [c for c in columns if c not in conflict_cols]
    set_sql = ",".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
    conn.execute(
        f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({','.join(conflict_cols)}) DO UPDATE SET {set_sql}",
        values,
    )


# ===========================================================================
# Auditoria
# ===========================================================================
def audit(
    conn: sqlite3.Connection,
    *,
    action: str,
    entity: str,
    entity_id: str | None = None,
    actor: str = "sistema",
    actor_type: str = "SISTEMA",
    agent: str | None = None,
    tool: str | None = None,
    input_data: Any = None,
    output_data: Any = None,
    evidence_ids: Sequence[str] | None = None,
    model: str | None = None,
    as_of: str | None = None,
) -> str:
    """Acrescenta um evento a trilha. Nunca atualiza nem apaga."""
    rid = new_id()
    conn.execute(
        "INSERT INTO audit_log (id, actor, actor_type, action, agent, tool, entity, "
        "entity_id, input_json, output_json, evidence_ids, model, as_of, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            rid, actor, actor_type, action, agent, tool, entity, entity_id,
            json.dumps(input_data, ensure_ascii=False, default=str) if input_data is not None else None,
            json.dumps(output_data, ensure_ascii=False, default=str) if output_data is not None else None,
            ",".join(evidence_ids) if evidence_ids else None,
            model, as_of, now_iso(),
        ),
    )
    return rid


def audit_trail(
    conn: sqlite3.Connection, *, entity: str | None = None,
    entity_id: str | None = None, limit: int = 200,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM audit_log WHERE 1=1"
    params: list[Any] = []
    if entity:
        sql += " AND entity = ?"
        params.append(entity)
    if entity_id:
        sql += " AND entity_id = ?"
        params.append(entity_id)
    sql += " ORDER BY created_at ASC, id ASC LIMIT ?"
    params.append(limit)
    return list(conn.execute(sql, params).fetchall())


# ===========================================================================
# Evidencia — geracao automatica de evidence_id
# ===========================================================================
def create_evidence(
    conn: sqlite3.Connection,
    *,
    kind: str,
    source_name: str,
    excerpt: str,
    as_of: str,
    classification: str,
    source_id: str | None = None,
    locator: str | None = None,
    value: Decimal | None = None,
    unit: str | None = None,
) -> str:
    """Cria a evidencia e devolve o `evidence_id`. Todo numero nasce daqui."""
    if classification not in VALID_CLASSIFICATIONS:
        raise ValueError(
            f"Classificacao invalida: {classification!r}. "
            f"Aceitas: {', '.join(VALID_CLASSIFICATIONS)}."
        )
    if not excerpt or not excerpt.strip():
        raise ValueError("Evidencia exige `excerpt`: sem trecho citado nao ha lastro.")
    eid = new_id()
    conn.execute(
        "INSERT INTO evidence (id, kind, source_id, source_name, locator, excerpt, "
        "value_numeric, unit, as_of, classification, content_hash, ingested_at, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, kind, source_id, source_name, locator, excerpt, as_text(value), unit,
         as_of, classification, content_hash(excerpt), now_iso(), now_iso()),
    )
    return eid


def get_evidence(conn: sqlite3.Connection, evidence_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()


# ===========================================================================
# Fontes
# ===========================================================================
def upsert_source(
    conn: sqlite3.Connection,
    *,
    name: str,
    institution: str | None = None,
    source_kind: str = "OFICIAL",
    integration_status: str = "NOT_CONFIGURED",
    url: str | None = None,
    license_note: str | None = None,
    authorized: bool = True,
    update_frequency: str | None = None,
    notes: str | None = None,
) -> str:
    linha = conn.execute("SELECT id FROM sources WHERE name = ?", (name,)).fetchone()
    if linha:
        conn.execute(
            "UPDATE sources SET integration_status=?, url=COALESCE(?,url), "
            "notes=COALESCE(?,notes) WHERE id=?",
            (integration_status, url, notes, linha["id"]),
        )
        return linha["id"]
    sid = new_id()
    conn.execute(
        "INSERT INTO sources (id, name, institution, url, source_kind, integration_status, "
        "license_note, authorized, update_frequency, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (sid, name, institution, url, source_kind, integration_status, license_note,
         1 if authorized else 0, update_frequency, notes, now_iso()),
    )
    return sid


def list_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM sources ORDER BY name").fetchall())


def mark_source_success(conn: sqlite3.Connection, source_id: str, status: str) -> None:
    """`LIVE_VALIDATED` so e gravado depois de resposta valida e dado persistido."""
    conn.execute(
        "UPDATE sources SET integration_status=?, last_success_at=? WHERE id=?",
        (status, now_iso(), source_id),
    )


# ===========================================================================
# Observacoes de mercado
# ===========================================================================
def insert_observation(
    conn: sqlite3.Connection,
    *,
    metric: str,
    value: Decimal,
    unit: str,
    ref_date: str,
    as_of: str,
    source_name: str,
    classification: str,
    source_id: str | None = None,
    submarket: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    model_run: str | None = None,
    excerpt: str | None = None,
) -> tuple[str, str]:
    """Grava a observacao e a evidencia correspondente. Devolve (obs_id, evidence_id)."""
    texto = excerpt or (
        f"{source_name}: {metric} = {value} {unit} em {ref_date} "
        f"(data-base {as_of}, classificacao {classification})."
    )
    eid = create_evidence(
        conn, kind="OBSERVACAO", source_name=source_name, source_id=source_id,
        locator=f"{metric}@{ref_date}", excerpt=texto, value=value, unit=unit,
        as_of=as_of, classification=classification,
    )
    oid = new_id()
    upsert_row(
        conn, table="market_observations",
        columns=("id", "metric", "value", "unit", "submarket", "period_start", "period_end",
                 "ref_date", "as_of", "source_id", "classification", "model_run",
                 "ingested_at", "evidence_id", "created_at"),
        values=(oid, metric, as_text(value), unit, submarket, period_start, period_end, ref_date,
                as_of, source_id, classification, model_run or "", now_iso(), eid, now_iso()),
        conflict_cols=("metric", "ref_date", "as_of", "model_run"),
    )
    return oid, eid


def metric_history(
    conn: sqlite3.Connection, metric: str, *, as_of: str,
    model_run: str | None = None, limit: int = 1000,
) -> list[sqlite3.Row]:
    """Historico ate a data-base. Nunca devolve dado posterior (anti look-ahead)."""
    sql = ("SELECT * FROM market_observations WHERE metric = ? AND as_of <= ? "
           "AND ref_date <= ?")
    params: list[Any] = [metric, as_of, as_of]
    if model_run is not None:
        sql += " AND model_run = ?"
        params.append(model_run or "")
    sql += " ORDER BY ref_date ASC, as_of ASC LIMIT ?"
    params.append(limit)
    return list(conn.execute(sql, params).fetchall())


def latest_observation(
    conn: sqlite3.Connection, metric: str, *, as_of: str, model_run: str | None = None
) -> sqlite3.Row | None:
    sql = ("SELECT * FROM market_observations WHERE metric = ? AND as_of <= ? "
           "AND ref_date <= ?")
    params: list[Any] = [metric, as_of, as_of]
    if model_run is not None:
        sql += " AND model_run = ?"
        params.append(model_run or "")
    sql += " ORDER BY ref_date DESC, as_of DESC LIMIT 1"
    return conn.execute(sql, params).fetchone()


def distinct_metrics(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT metric FROM market_observations ORDER BY metric"
    ).fetchall()
    return [r["metric"] for r in rows]


def source_freshness(conn: sqlite3.Connection, *, as_of: str) -> list[dict[str, Any]]:
    """Idade de cada metrica em dias. Fonte atrasada aparece; nunca some.

    `classification` acompanha a observacao mais recente (maior `ref_date`,
    desempate por `as_of`) — nao e um agregado, entao nao pode ir solto ao
    lado de `MAX()`/`COUNT()` num `GROUP BY metric` (SQLite tolera coluna nao
    agregada fora do GROUP BY e devolve uma linha arbitraria; Postgres recusa
    com `GroupingError`). Window function resolve nos dois dialetos: agrega
    por `metric` e escolhe a linha mais recente do grupo via `ROW_NUMBER`.
    """
    rows = conn.execute(
        "SELECT metric, last_ref, last_asof, n, classification FROM ("
        "  SELECT metric, ref_date, as_of, classification,"
        "         COUNT(*) OVER (PARTITION BY metric) AS n,"
        "         MAX(ref_date) OVER (PARTITION BY metric) AS last_ref,"
        "         MAX(as_of) OVER (PARTITION BY metric) AS last_asof,"
        "         ROW_NUMBER() OVER ("
        "             PARTITION BY metric ORDER BY ref_date DESC, as_of DESC"
        "         ) AS rn"
        "  FROM market_observations WHERE as_of <= ?"
        ") t WHERE rn = 1 ORDER BY metric",
        (as_of,),
    ).fetchall()
    referencia = date.fromisoformat(as_of)
    saida = []
    for r in rows:
        idade = (referencia - date.fromisoformat(r["last_ref"])).days
        saida.append({
            "metric": r["metric"], "last_ref_date": r["last_ref"],
            "last_as_of": r["last_asof"], "observations": r["n"],
            "classification": r["classification"], "age_days": idade,
        })
    return saida


# ===========================================================================
# Curva forward
# ===========================================================================
def insert_curve(
    conn: sqlite3.Connection,
    *,
    curve_name: str,
    submarket: str,
    as_of: str,
    source_name: str,
    classification: str,
    origin: str = "NEGOCIADA",
    energy_source: str = "CONVENCIONAL",
    quote_type: str = "MID",
    proxy_of: str | None = None,
    source_id: str | None = None,
    notes: str | None = None,
) -> tuple[str, str]:
    """Cria o cabecalho da curva. PLD/CMO exigem `origin=PROXY_SPOT` + `proxy_of`."""
    if origin == "PROXY_SPOT" and not proxy_of:
        raise ValueError(
            "Curva PROXY_SPOT exige `proxy_of`: PLD e CMO sao precos de curto prazo "
            "formados por modelo de despacho, nao precos negociados."
        )
    eid = create_evidence(
        conn, kind="CURVA", source_name=source_name, source_id=source_id,
        locator=f"curva:{curve_name}@{as_of}",
        excerpt=(f"{source_name}: curva {curve_name} ({submarket}/{energy_source}), "
                 f"origem {origin}, cotacao {quote_type}, data-base {as_of}."),
        as_of=as_of, classification=classification,
    )
    cid = new_id()
    upsert_row(
        conn, table="forward_curves",
        columns=("id", "curve_name", "submarket", "energy_source", "quote_type", "origin",
                 "proxy_of", "as_of", "source_id", "classification", "evidence_id", "notes",
                 "created_at"),
        values=(cid, curve_name, submarket, energy_source, quote_type, origin, proxy_of, as_of,
                source_id, classification, eid, notes, now_iso()),
        conflict_cols=("curve_name", "submarket", "energy_source", "quote_type", "as_of"),
    )
    return cid, eid


def insert_curve_point(
    conn: sqlite3.Connection, curve_id: str, *, tenor: str, delivery_start: str,
    delivery_end: str, price: Decimal, source_name: str, as_of: str,
    classification: str, unit: str = "R$/MWh",
) -> tuple[str, str]:
    eid = create_evidence(
        conn, kind="CURVA", source_name=source_name,
        locator=f"curva:{curve_id}#{tenor}",
        excerpt=(f"{source_name}: tenor {tenor} ({delivery_start}..{delivery_end}) "
                 f"= {price} {unit}, data-base {as_of}."),
        value=price, unit=unit, as_of=as_of, classification=classification,
    )
    pid = new_id()
    upsert_row(
        conn, table="forward_curve_points",
        columns=("id", "curve_id", "tenor", "delivery_start", "delivery_end", "price", "unit",
                 "evidence_id", "created_at"),
        values=(pid, curve_id, tenor, delivery_start, delivery_end, as_text(price), unit, eid,
                now_iso()),
        conflict_cols=("curve_id", "tenor"),
    )
    return pid, eid


def latest_curve(
    conn: sqlite3.Connection, *, as_of: str, submarket: str | None = None,
    curve_name: str | None = None, energy_source: str | None = None,
) -> sqlite3.Row | None:
    sql = "SELECT * FROM forward_curves WHERE as_of <= ?"
    params: list[Any] = [as_of]
    for campo, valor in (("submarket", submarket), ("curve_name", curve_name),
                         ("energy_source", energy_source)):
        if valor:
            sql += f" AND {campo} = ?"
            params.append(valor)
    sql += " ORDER BY as_of DESC, created_at DESC LIMIT 1"
    return conn.execute(sql, params).fetchone()


def curve_points(conn: sqlite3.Connection, curve_id: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM forward_curve_points WHERE curve_id = ? ORDER BY delivery_start",
        (curve_id,),
    ).fetchall())


def compare_curves(
    conn: sqlite3.Connection, curve_a: str, curve_b: str
) -> list[dict[str, Any]]:
    """Compara dois cabecalhos de curva tenor a tenor."""
    a = {r["tenor"]: r for r in curve_points(conn, curve_a)}
    b = {r["tenor"]: r for r in curve_points(conn, curve_b)}
    saida = []
    for tenor in sorted(set(a) | set(b)):
        pa = to_decimal(a[tenor]["price"]) if tenor in a else None
        pb = to_decimal(b[tenor]["price"]) if tenor in b else None
        delta = (pb - pa) if (pa is not None and pb is not None) else None
        saida.append({
            "tenor": tenor, "price_a": pa, "price_b": pb, "delta": delta,
            "delta_pct": (delta / pa) if (delta is not None and pa) else None,
        })
    return saida


__all__ = [
    "PROXY_CLASSIFICATIONS", "VALID_CLASSIFICATIONS", "as_text", "audit", "audit_trail",
    "compare_curves", "content_hash", "create_evidence", "curve_points", "distinct_metrics",
    "get_evidence", "insert_curve", "insert_curve_point", "insert_observation",
    "latest_curve", "latest_observation", "list_sources", "mark_source_success",
    "metric_history", "new_id", "now_iso", "source_freshness", "to_decimal", "upsert_row",
    "upsert_source",
]
