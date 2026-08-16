"""Utilitarios de linha de comando (`make doctor`).

Diagnostico de configuracao e conectividade, sem expor credencial (RNF-07).
"""

from __future__ import annotations

import json
import sys

from copilot.common.logging import setup_logging
from copilot.db.session import healthcheck


def doctor(argv: list[str] | None = None) -> int:
    """Imprime o estado da configuracao e do banco."""
    setup_logging()
    report = healthcheck()

    print("Energy Trading Copilot — diagnostico\n")
    settings = report.pop("settings", {})
    for key, value in settings.items():
        print(f"  {key:>22}: {value}")
    print()
    print(f"  {'backend':>22}: {report['backend']}")
    print(f"  {'banco acessivel':>22}: {'sim' if report['reachable'] else 'NAO'}")
    print(f"  {'tabelas':>22}: {report['tables']}")
    if report["error"]:
        print(f"  {'erro':>22}: {report['error']}")
        print("\nSugestao: rode `make migrate` ou confira DATABASE_URL no .env.")
        return 1
    if report["tables"] == 0:
        print("\nBanco vazio. Rode `make migrate` e depois `make seed-demo`.")
        return 1
    print("\nOK.")
    return 0


def doctor_json(argv: list[str] | None = None) -> int:  # pragma: no cover - conveniencia
    print(json.dumps(healthcheck(), ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    command = args[0] if args else "doctor"
    if command == "doctor":
        return doctor(args[1:])
    if command == "doctor-json":
        return doctor_json(args[1:])
    print(f"comando desconhecido: {command}. Use `doctor` ou `doctor-json`.")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
