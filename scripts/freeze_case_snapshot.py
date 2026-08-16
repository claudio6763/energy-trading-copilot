#!/usr/bin/env python3
"""Congela o estado dos dados numa data-base, com hash.

    python scripts/freeze_case_snapshot.py --as-of 2026-08-14
"""
from __future__ import annotations

import argparse, hashlib, json, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from src.database import repositories as R  # noqa: E402
from src.database.connection import init_db  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Congela snapshot da data-base.")
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    args = p.parse_args(argv)
    as_of = args.as_of.isoformat()

    conn = init_db()
    try:
        dados = {
            "as_of": as_of,
            "observations": [dict(r) for r in conn.execute(
                "SELECT metric, value, unit, ref_date, as_of, classification, source_id "
                "FROM market_observations WHERE as_of <= ? ORDER BY metric, ref_date",
                (as_of,)).fetchall()],
            "curves": [dict(r) for r in conn.execute(
                "SELECT * FROM forward_curves WHERE as_of <= ?", (as_of,)).fetchall()],
            "curve_points": [dict(r) for r in conn.execute(
                "SELECT p.* FROM forward_curve_points p JOIN forward_curves c "
                "ON c.id=p.curve_id WHERE c.as_of <= ?", (as_of,)).fetchall()],
            "sources": [dict(r) for r in R.list_sources(conn)],
            "documents": [dict(r) for r in conn.execute("SELECT * FROM documents").fetchall()],
        }
        bruto = json.dumps(dados, ensure_ascii=False, indent=2, default=str)
        digest = hashlib.sha256(bruto.encode("utf-8")).hexdigest()
        destino = ROOT / "data" / "snapshots" / f"case_snapshot_{as_of}.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(bruto, encoding="utf-8")
        (destino.with_suffix(".sha256")).write_text(digest, encoding="utf-8")
        R.audit(conn, action="SNAPSHOT", entity="dataset", entity_id=as_of,
                output_data={"sha256": digest, "observations": len(dados["observations"])},
                as_of=as_of)
    finally:
        conn.close()

    print(f"Snapshot congelado: {destino}")
    print(f"  observacoes : {len(dados['observations'])}")
    print(f"  curvas      : {len(dados['curves'])} ({len(dados['curve_points'])} pontos)")
    print(f"  sha256      : {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
