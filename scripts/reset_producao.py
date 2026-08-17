"""Reset completo do banco ativo (`DATABASE_URL`/`COPILOT_DB`): apaga tudo e
registra de novo a tese da Entrega 2.

Existe para garantir, a qualquer momento antes da defesa, que o banco volta
a um estado conhecido — sem depender de lembrar a sequência manual de
TRUNCATE + `seed_producao.py` + verificação (foi assim, à mão, que se
limpou o Neon depois do incidente descrito em DECISOES.md; este script
existe para nunca precisar repetir isso à mão de novo).

Seguro de rodar várias vezes: sempre termina no mesmo estado (1 tese,
5 pernas, VaR do book), independente de quantas vezes já rodou antes.

Uso:
    python scripts/reset_producao.py
    DATABASE_URL=postgresql://... python scripts/reset_producao.py
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.config import load_dotenv  # noqa: E402

load_dotenv()  # popula DATABASE_URL/COPILOT_DB do .env antes de qualquer leitura de config

from src.database.connection import connect, dialect_of, get_database_url  # noqa: E402

# Mesmas tabelas de schema.sql (schema compartilhado SQLite/Postgres).
# `chunk_fts` (SQLite-only, ver schema_sqlite_only.sql) e tratada à parte.
TABELAS = [
    "sources", "evidence", "market_observations", "forward_curves", "forward_curve_points",
    "documents", "document_chunks", "theses", "thesis_assumptions", "thesis_risks",
    "thesis_sources", "positions", "risk_limits", "risk_results", "scenario_results",
    "debate_sessions", "debate_turns", "triggers", "watchdog_runs", "alerts", "audit_log",
    "ingest_snapshots", "thesis_book", "thesis_book_legs",
]

VAR_ESPERADO = Decimal("29892814.54")
CONSUMO_ESPERADO = 0.5979


def _apagar_tudo(conn) -> None:
    """Zera todas as tabelas de domínio. Postgres: TRUNCATE CASCADE resolve a
    ordem de FK sozinho. SQLite: sem TRUNCATE — desliga a checagem de FK,
    apaga tabela a tabela, religa."""
    if dialect_of(conn) == "postgres":
        conn.execute("TRUNCATE TABLE " + ", ".join(TABELAS) + " CASCADE")
        conn.commit()
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    for tabela in TABELAS + ["chunk_fts"]:
        try:
            conn.execute(f"DELETE FROM {tabela}")
        except Exception:  # pragma: no cover - tabela pode nao existir (instalacao nova)
            pass
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()


def _verificar(conn) -> bool:
    """Imprime e confere: exatamente 1 tese (`owner='trader'`), 5 pernas,
    VaR e consumo do book batendo com o golden da Entrega 2."""
    teses = conn.execute(
        "SELECT t.id, t.owner, t.title FROM theses t JOIN thesis_book b ON b.thesis_id = t.id"
    ).fetchall()
    if len(teses) != 1:
        print(f"FALHA: esperado 1 tese com book, achei {len(teses)}.")
        return False
    tese = teses[0]
    if tese["owner"] != "trader":
        print(f"FALHA: owner da tese e {tese['owner']!r}, esperado 'trader'.")
        return False

    livro = conn.execute(
        "SELECT * FROM thesis_book WHERE thesis_id = ?", (tese["id"],)
    ).fetchone()
    pernas = conn.execute(
        "SELECT COUNT(*) AS n FROM thesis_book_legs WHERE book_id = ?", (livro["id"],)
    ).fetchone()["n"]
    var_total = Decimal(str(livro["var_total"]))
    consumo = float(livro["consumo_limite"])

    ok = True
    if pernas != 5:
        print(f"FALHA: {pernas} perna(s), esperado 5.")
        ok = False
    if abs(var_total - VAR_ESPERADO) >= Decimal("1"):
        print(f"FALHA: VaR R$ {var_total}, esperado ~R$ {VAR_ESPERADO}.")
        ok = False
    if abs(consumo - CONSUMO_ESPERADO) >= 1e-3:
        print(f"FALHA: consumo {consumo:.2%}, esperado ~{CONSUMO_ESPERADO:.2%}.")
        ok = False

    n_audit_estranho = conn.execute(
        "SELECT COUNT(*) AS n FROM audit_log WHERE actor NOT IN ('trader','sistema','seed_producao')"
    ).fetchone()["n"]
    if n_audit_estranho:
        print(f"FALHA: {n_audit_estranho} linha(s) de audit_log com ator inesperado.")
        ok = False

    print(f"tese: {tese['id']} ({tese['title']}, owner={tese['owner']})")
    print(f"pernas: {pernas}")
    print(f"VaR: R$ {var_total:,.2f}  consumo: {consumo:.2%}")
    print(f"audit_log: {conn.execute('SELECT COUNT(*) AS n FROM audit_log').fetchone()['n']} linha(s), todas de origem conhecida")
    return ok


def main() -> int:
    url = get_database_url()
    print(f"banco alvo: {'(nao definida — usando SQLite local)' if not url else url.split('@')[-1]}")

    conn = connect()
    print(f"dialeto ativo: {dialect_of(conn)}")
    _apagar_tudo(conn)
    conn.close()
    print("banco zerado.")

    from scripts.seed_producao import main as seed_main

    codigo = seed_main(["--force"])
    if codigo != 0:
        print("FALHA: seed_producao.py retornou erro.")
        return codigo

    conn = connect()
    try:
        ok = _verificar(conn)
    finally:
        conn.close()

    if not ok:
        print("FALHA na verificacao pos-seed.")
        return 1
    print("OK: reset completo, banco no estado esperado da Entrega 2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
