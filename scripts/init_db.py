#!/usr/bin/env python3
"""Cria o banco e o schema. Idempotente."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from src.database.connection import healthcheck, init_db  # noqa: E402

def main() -> int:
    conn = init_db()
    conn.close()
    estado = healthcheck()
    print(f"Banco: {estado['path']}")
    print(f"Tabelas: {estado['tables']} | FTS5: {estado.get('fts5')}")
    if not estado["ok"]:
        print("FALHA:", estado.get("error", "schema vazio"))
        return 1
    print("OK. Proximo passo: python scripts/seed_demo.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
