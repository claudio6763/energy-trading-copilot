#!/usr/bin/env python3
"""Atualiza dados do setor eletrico (ONS, CCEE, EPE, clima, curva forward).

    .\\.venv\\Scripts\\python.exe scripts\\update_sector_data.py --source all
    .\\.venv\\Scripts\\python.exe scripts\\update_sector_data.py --source ons
    .\\.venv\\Scripts\\python.exe scripts\\update_sector_data.py --source forward --dry-run

Cada fonte falha isoladamente: uma fonte fora do ar nunca derruba as outras
nem impede o codigo de saida refletir sucesso parcial (RF-36). `--dry-run`
executa os adapters e mostra o resumo sem gravar nada no banco.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from copilot.ingest.contracts import AdapterResult  # noqa: E402
from copilot.ingest.registry import get_adapter  # noqa: E402
from copilot.ingest.snapshots import SnapshotStore  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.database.connection import init_db  # noqa: E402
from src.services import curve_service as CS  # noqa: E402
from src.services.ingestion_bridge import persist_adapter_result  # noqa: E402

#: Nome do adapter por fonte do CLI. "climate" cobre o unico conector de sinal
#: climatico implementado nesta sprint (ENSO/ONI do NOAA CPC).
SOURCE_ADAPTERS: dict[str, tuple[str, ...]] = {
    "ccee": ("ccee",),
    "ons": ("ons",),
    "epe": ("epe",),
    "climate": ("enso_oni",),
    "forward": ("b3_n5x", "bbce_forward"),  # + curva estatistica, tratada a parte
}

#: Classificacao de acesso (secao 3 do prompt de integracoes) por adapter —
#: nao muda o schema, so o texto gravado em `sources.license_note`.
ACCESS_LABELS: dict[str, str] = {
    "ons": "PUBLIC_NO_AUTH", "ccee": "PUBLIC_NO_AUTH", "epe": "PUBLIC_NO_AUTH",
    "enso_oni": "PUBLIC_NO_AUTH", "aneel": "PUBLIC_NO_AUTH", "ana": "PUBLIC_NO_AUTH",
    "climate": "PUBLIC_NO_AUTH", "b3_n5x": "NOT_VERIFIED", "bbce_forward": "OPTIONAL_LICENSED",
}


def _run_source(nome_fonte: str, *, as_of: date, snapshots: SnapshotStore) -> list[AdapterResult]:
    resultados = []
    for nome_adapter in SOURCE_ADAPTERS[nome_fonte]:
        adapter = get_adapter(nome_adapter, snapshot_store=snapshots)
        resultados.append(adapter.run(as_of=as_of))
    return resultados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atualizacao de dados do setor eletrico.")
    parser.add_argument(
        "--source", required=True,
        choices=["ccee", "ons", "epe", "climate", "forward", "all"],
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--dry-run", action="store_true", help="roda os adapters sem gravar no banco")
    args = parser.parse_args(argv)

    as_of = args.as_of or get_settings().data_cut_off
    fontes = list(SOURCE_ADAPTERS) if args.source == "all" else [args.source]
    snapshots = SnapshotStore(ROOT / "data" / "snapshots")

    conn = None if args.dry_run else init_db()
    total_ok = total_falha = 0
    try:
        for fonte in fontes:
            print(f"\n== {fonte} ==")
            for resultado in _run_source(fonte, as_of=as_of, snapshots=snapshots):
                rotulo = ACCESS_LABELS.get(resultado.adapter, resultado.source.license_class.value)
                if args.dry_run:
                    print(f"  [{rotulo}] {resultado.summary()}")
                else:
                    saida = persist_adapter_result(conn, resultado, as_of=as_of.isoformat(), access_label=rotulo)
                    print(
                        f"  [{rotulo}] {resultado.adapter}: {saida['status']} — "
                        f"{saida['observations']} observação(ões), {saida['curves']} curva(s)"
                        + (f" — {saida['reason']}" if saida["reason"] else "")
                    )
                if resultado.ok:
                    total_ok += 1
                else:
                    total_falha += 1

            if fonte == "forward":
                print("  curva estatística pública (P10/P50/P90 sobre PLD histórico):")
                if args.dry_run:
                    print("    [dry-run] cálculo pulado — use sem --dry-run para gerar e persistir.")
                else:
                    resultado_curva = CS.refresh_all_submarkets(conn, as_of=as_of.isoformat())
                    for submercado, r in resultado_curva.items():
                        print(f"    {submercado}: {r['status']}"
                              + (f" — {r.get('message')}" if r.get("message") else ""))

        print(f"\nResumo: {total_ok} fonte(s) ok/parcial, {total_falha} indisponível/rejeitada.")
        return 0 if total_ok > 0 or total_falha == 0 else 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
