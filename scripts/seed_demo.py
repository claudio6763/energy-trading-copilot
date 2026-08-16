#!/usr/bin/env python3
"""Popula o banco com catalogo de fontes, series e documentos DEMONSTRATIVOS.

Tudo que entra aqui e classificado como `demonstracao` e assim aparece na UI.
Nenhum valor sai de fonte de mercado: todos vem de uma funcao deterministica.
Substituir por dado real: ver `docs/data_guide.md`.

Uso::

    python scripts/seed_demo.py
    python scripts/seed_demo.py --reset --as-of 2026-08-14
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from src.config import get_settings  # noqa: E402
from src.database import repositories as R  # noqa: E402
from src.database.connection import init_db  # noqa: E402
from src.rag import store as RAG  # noqa: E402

DEMO_MARK = "DADO DEMONSTRATIVO — não é observação de mercado"

#: Catalogo do case. Status inicial honesto: nada e LIVE_VALIDATED sem chamada real.
CATALOG = [
    ("ONS", "ONS", "https://dados.ons.org.br/", "OFICIAL", "NOT_CONFIGURED",
     "Dados abertos, atribuicao exigida.", "EAR, ENA, carga, geracao, restricoes."),
    ("CCEE", "CCEE", "https://www.ccee.org.br/", "OFICIAL", "NOT_CONFIGURED",
     "Parte publica apenas; area de agente exige credencial.",
     "PLD e regras de comercializacao. PLD e spot, NUNCA curva forward."),
    ("ANEEL", "ANEEL", "https://dadosabertos.aneel.gov.br/", "OFICIAL", "NOT_CONFIGURED",
     "Dados abertos.", "Resolucoes e dados de geracao."),
    ("ANA", "ANA", "https://www.snirh.gov.br/hidroweb/", "OFICIAL", "NOT_CONFIGURED",
     "Dados abertos, atribuicao exigida.", "Vazoes e niveis de reservatorio."),
    ("EPE", "EPE", "https://www.epe.gov.br/", "OFICIAL", "NOT_CONFIGURED",
     "Publicacoes abertas.", "Planejamento e balanco de energia."),
    ("INMET", "INMET", "https://portal.inmet.gov.br/", "OFICIAL", "NOT_CONFIGURED",
     "Dados abertos.", "Precipitacao e temperatura observadas."),
    ("CPTEC/INPE", "INPE", "https://www.cptec.inpe.br/", "MODELO", "NOT_CONFIGURED",
     "Dados abertos.", "Previsao meteorologica por rodada."),
    ("NOAA CPC", "NOAA", "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
     "OFICIAL", "MANUAL_IMPORT", "Dominio publico (governo dos EUA).",
     "ONI/ENSO. Adapter implementado; requer rede para virar LIVE_VALIDATED."),
    ("ECMWF", "ECMWF", "https://www.ecmwf.int/", "MODELO", "NOT_CONFIGURED",
     "Parte aberta, parte licenciada.", "Ensembles de previsao."),
    ("BBCE", "BBCE", None, "COMERCIAL", "NOT_CONFIGURED",
     "LICENCIADO — nao ingerir sem autorizacao escrita.",
     "Curva negociada. Bloqueado ate autorizacao."),
    ("DCIDE", "DCIDE", None, "COMERCIAL", "NOT_CONFIGURED",
     "LICENCIADO — nao ingerir sem autorizacao escrita.",
     "Curva indicativa. Bloqueado ate autorizacao."),
    ("Simulacao da mesa", "Interna", None, "DEMO", "DEMO",
     "Dado sintetico gerado localmente.", "Usado no botao de simulacao e no seed."),
]

#: (metrica, unidade, submercado, base, amplitude, periodo, fase)
SERIES = [
    ("fwd_se_a1_conv", "R$/MWh", "SE/CO", 195.0, 9.0, 40.0, 0.0),
    ("pld_se_semanal", "R$/MWh", "SE/CO", 180.0, 55.0, 45.0, 5.0),
    ("cmo_se", "R$/MWh", "SE/CO", 175.0, 50.0, 45.0, 6.0),
    ("ear_sudeste_pct", "%", "SE/CO", 52.0, 9.0, 90.0, 0.0),
    ("ena_sin_mlt_pct", "%", None, 88.0, 20.0, 60.0, 12.0),
    ("carga_sin_mwmed", "MWmed", None, 71000.0, 2400.0, 30.0, 3.0),
    ("enso_oni_anomaly", "adimensional", None, 0.2, 0.8, 180.0, 0.0),
    ("precip_prev_7d", "mm", "SE/CO", 42.0, 17.0, 21.0, 0.0),
]

DOCS = [
    ("Regras de Comercializacao — Modulo de Lastro e Penalidades", "CCEE", "REGRA", "2026.1",
     "2026-01-01", [
        "MODULO 1 — LASTRO. O lastro de venda de cada agente e apurado por periodo "
        "de apuracao anual, considerando a energia assegurada, os contratos de compra "
        "registrados e a geracao propria verificada.",
        "MODULO 2 — PENALIDADE. A insuficiencia de lastro de venda sujeita o agente a "
        "penalidade calculada sobre o montante nao lastreado, valorado pelo maior valor "
        "entre o PLD e o custo marginal de expansao vigente no periodo.",
        "MODULO 3 — SAZONALIZACAO E MODULACAO. A sazonalizacao da garantia fisica e "
        "declarada anualmente. A modulacao define a distribuicao horaria e afeta a "
        "exposicao do agente ao mercado de curto prazo.",
     ]),
    ("Procedimentos de Rede — Submodulo de Restricoes Operativas", "ONS", "PROCEDIMENTO",
     "2026.1", "2026-01-01", [
        "SUBMODULO 1 — RESTRICAO HIDRAULICA. As restricoes hidraulicas de vazao minima "
        "e maxima a jusante condicionam o despacho das usinas hidreletricas e podem "
        "reduzir a energia disponivel independentemente do armazenamento.",
        "SUBMODULO 2 — CURTAILMENT. O corte de geracao renovavel por restricao de "
        "escoamento (constrained-off) e apurado pelo ONS e pode gerar ressarcimento "
        "conforme regra vigente.",
        "SUBMODULO 3 — MRE. O Mecanismo de Realocacao de Energia redistribui a energia "
        "entre os participantes. O GSF, razao entre geracao e garantia fisica, mede o "
        "risco hidrologico nao coberto pelo mecanismo.",
     ]),
]


def wave(i: int, base: float, amp: float, per: float, fase: float) -> float:
    return base + amp * math.sin((i + fase) * 2 * math.pi / per)


def seed(conn, as_of: date, *, history_days: int = 180) -> dict[str, int]:
    contagem = {"sources": 0, "observations": 0, "curve_points": 0, "documents": 0}

    fontes: dict[str, str] = {}
    for nome, inst, url, tipo, status, licenca, notas in CATALOG:
        fontes[nome] = R.upsert_source(
            conn, name=nome, institution=inst, url=url, source_kind=tipo,
            integration_status=status, license_note=licenca, notes=notas,
            authorized=("LICENCIADO" not in (licenca or "")),
        )
        contagem["sources"] += 1

    demo = fontes["Simulacao da mesa"]
    for metrica, unidade, submercado, base, amp, per, fase in SERIES:
        for deslocamento in range(history_days, 0, -1):
            ref = as_of - timedelta(days=deslocamento)
            casas = "0.0001" if unidade in ("%", "adimensional") else "0.01"
            valor = Decimal(repr(round(wave(deslocamento, base, amp, per, fase), 6))).quantize(
                Decimal(casas))
            R.insert_observation(
                conn, metric=metrica, value=valor, unit=unidade, ref_date=ref.isoformat(),
                as_of=ref.isoformat(), source_name="Simulacao da mesa",
                classification="demonstracao", source_id=demo, submarket=submercado,
                excerpt=f"{DEMO_MARK}: {metrica} = {valor} {unidade} em {ref.isoformat()}.",
            )
            contagem["observations"] += 1

    cid, _ = R.insert_curve(
        conn, curve_name="Curva demonstrativa SE/CO convencional", submarket="SE/CO",
        as_of=as_of.isoformat(), source_name="Simulacao da mesa",
        classification="demonstracao", origin="PROXY_MODELO", quote_type="INDICATIVO",
        source_id=demo, proxy_of="gerador sintetico",
        notes=f"{DEMO_MARK}. Nao e preco negociado; penalizada no risco pelo add-on de proxy.",
    )
    for deslocamento, preco in ((1, "195.00"), (2, "188.50"), (3, "182.00")):
        ano = as_of.year + deslocamento
        R.insert_curve_point(
            conn, cid, tenor=f"A+{deslocamento}", delivery_start=f"{ano}-01-01",
            delivery_end=f"{ano}-12-31", price=Decimal(preco),
            source_name="Simulacao da mesa", as_of=as_of.isoformat(),
            classification="demonstracao",
        )
        contagem["curve_points"] += 1

    for titulo, inst, tipo, versao, vigencia, paginas in DOCS:
        RAG.add_document(conn, title=titulo, institution=inst, doc_type=tipo, version=versao,
                         effective_from=vigencia, published_at=vigencia, pages=paginas)
        contagem["documents"] += 1

    R.audit(conn, action="SEED", entity="dataset", output_data=contagem,
            as_of=as_of.isoformat())
    return contagem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Popula dados demonstrativos.")
    parser.add_argument("--reset", action="store_true", help="apaga dados antes de popular")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--history-days", type=int, default=180)
    args = parser.parse_args(argv)

    as_of = args.as_of or get_settings().data_cut_off
    conn = init_db()
    try:
        if args.reset:
            for tabela in ("alerts", "watchdog_runs", "debate_turns", "debate_sessions",
                           "scenario_results", "risk_results", "triggers", "positions",
                           "thesis_sources", "thesis_risks", "thesis_assumptions", "theses",
                           "forward_curve_points", "forward_curves", "market_observations",
                           "chunk_fts", "document_chunks", "documents", "evidence",
                           "ingest_snapshots"):
                conn.execute(f"DELETE FROM {tabela}")
            print("Dados anteriores removidos (audit_log preservado: e append-only).")
        contagem = seed(conn, as_of, history_days=args.history_days)
    finally:
        conn.close()

    print(f"Seed demonstrativo concluido (data-base {as_of.isoformat()}):")
    for chave in sorted(contagem):
        print(f"  {chave:>16}: {contagem[chave]}")
    print("\nTodos os valores estao classificados como 'demonstracao'.")
    print("Para usar dado real, veja docs/data_guide.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
