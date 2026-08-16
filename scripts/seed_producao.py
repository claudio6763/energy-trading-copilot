"""Registra a tese da Entrega 2 no banco de PRODUÇÃO (a DATABASE_URL ativa).

Sem isto, se a banca abrir o link publicado, o requisito de verificação falha
— a Mesa aparece vazia (PROMPT_FINAL_COPILOTO.md, Parte 5: "seed obrigatório").

Roda o mesmo caminho que a tela Registrar tese usa (avaliar() -> Desafiar ->
register_thesis_from_motor), programático, sem UI. Precisa de `DATABASE_URL`
apontando para o Postgres de produção (ou roda sem ela para popular o SQLite
local, útil para testar antes do deploy).

Uso:
    python scripts/seed_producao.py                      # so registra se nao houver tese
    python scripts/seed_producao.py --force               # registra de novo mesmo se ja houver
    DATABASE_URL=postgresql://... python scripts/seed_producao.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from decimal import Decimal  # noqa: E402

from src.config import load_dotenv  # noqa: E402

load_dotenv()  # popula DATABASE_URL/COPILOT_DB do .env antes de qualquer leitura de config

from src.agents.llm_client import get_client  # noqa: E402
from src.database.connection import connect, dialect_of, get_database_url, init_db  # noqa: E402
from src.services import desafio_service as DES  # noqa: E402
from src.services import motor_service as MS  # noqa: E402
from src.services import snapshot_loader as SNAP  # noqa: E402
from src.motor.avaliar import avaliar  # noqa: E402

LIMITE_VAR_BRL = Decimal("50000000.00")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="registra mesmo se ja houver tese")
    args = parser.parse_args(argv)

    url = get_database_url()
    print(f"DATABASE_URL: {'(nao definida — usando SQLite local)' if not url else url.split('@')[-1]}")

    conn = init_db()
    print(f"dialeto ativo: {dialect_of(conn)}")

    if not args.force:
        existentes = conn.execute(
            "SELECT COUNT(*) AS n FROM theses t JOIN thesis_book b ON b.thesis_id = t.id"
        ).fetchone()["n"]
        if existentes:
            print(f"Já existem {existentes} tese(s) com book do motor. Nada a fazer "
                  f"(use --force para registrar de novo).")
            conn.close()
            return 0

    snapshot = SNAP.load_default_snapshot()
    if snapshot is None:
        print("FALHA: nenhum snapshot em motor_curva/snapshots/. Rode "
              "scripts/build_motor_snapshot.py e commite o resultado antes do seed.")
        conn.close()
        return 1

    ref_mercado = snapshot.notas.get("ref_mercado_geracao")
    if not ref_mercado:
        print("FALHA: snapshot sem 'ref_mercado_geracao' em notas.")
        conn.close()
        return 1

    resultado = avaliar(snapshot, ref_mercado, LIMITE_VAR_BRL)
    book = resultado["book"]
    print(f"book: {len(book['ladder'])} vertice(s), VaR {book['var_total']:.2f} "
          f"({book['consumo_limite']:.2%} do limite)")

    cliente = get_client()
    desafio = DES.montar_desafio(
        resultado, direcao="VENDER", client=cliente, conn=conn,
        ref_mercado_atual=ref_mercado, ref_mercado_base=ref_mercado,
    )
    print(f"Desafiar rodado em modo {desafio['modo_ia']}.")

    registro = MS.register_thesis_from_motor(
        conn, snapshot=snapshot, ref_mercado=ref_mercado,
        title="Book Entrega 2 — SE/CO",
        summary=(
            f"Venda de {book['n_pernas']} vértices de energia convencional flat SE/CO, "
            f"ago–dez/26, calibrada contra a referência de mesa declarada no snapshot."
        ),
        direction="VENDER", product="Convencional flat mensal SE/CO", submarket="SE/CO",
        owner="trader", as_of=snapshot.as_of, horizon_days=140,
        review_date="2026-09-15",
        exit_condition="Prêmio de nível abaixo de R$ 15/MWh",
        invalidation="Ordenação Seco > Base > Úmido invertida na reestimação",
        limite_var=LIMITE_VAR_BRL, actor="seed_producao",
        avaliado=resultado,
        trader_response=(
            "Aceito o risco declarado: a referência de mercado é premissa de mesa sem "
            "fonte pública, e o cenário Seco é o que quebra a posição. O consumo do "
            "limite (59,79%) deixa folga para o orçamento de risco."
        ),
        desafio_premissa_fragil=desafio["premissa_fragil"],
        desafio_cenario_quebra=desafio["cenario_quebra"],
        desafio_contra_argumento=desafio["contra_argumento"],
        desafio_vies_confirmacao=desafio["vies_confirmacao_texto"],
    )
    conn.close()
    print(f"Tese registrada: thesis_id={registro['thesis_id']} book_id={registro['book_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
