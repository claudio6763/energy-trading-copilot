#!/usr/bin/env python3
"""Watchdog: vigilancia automatica, sem a interface aberta.

    python scripts/run_watchdog.py --once
    python scripts/run_watchdog.py --interval 300
"""
from __future__ import annotations
import argparse, sys, time
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from src.config import get_settings  # noqa: E402
from src.database.connection import init_db  # noqa: E402
from src.services import watchdog_service as WD  # noqa: E402

def ciclo(conn, as_of: str) -> None:
    r = WD.run_once(conn, as_of=as_of)
    print(f"[{r['run_id'][-6:]}] {r['status']}: {r['theses_checked']} teses, "
          f"{r['triggers_evaluated']} regras, {r['alerts_raised']} alertas"
          + (f", atrasadas: {', '.join(r['stale_sources'])}" if r["stale_sources"] else ""))

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Watchdog do Energy Trading Copilot.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true", help="um ciclo e sai")
    g.add_argument("--interval", type=int, metavar="SEGUNDOS", help="loop continuo")
    p.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = p.parse_args(argv)
    as_of = (args.as_of or get_settings().data_cut_off).isoformat()
    conn = init_db()
    try:
        if args.once:
            ciclo(conn, as_of)
            return 0
        print(f"Watchdog a cada {args.interval}s (Ctrl+C para parar).")
        while True:
            ciclo(conn, as_of)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nEncerrado.")
        return 0
    finally:
        conn.close()

if __name__ == "__main__":
    raise SystemExit(main())
