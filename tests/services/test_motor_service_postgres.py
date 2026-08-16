"""Round-trip contra Postgres real — só roda com DATABASE_URL/COPILOT_DB
apontando para um Postgres (marcador `postgres`, pulado por padrão).

    DATABASE_URL=postgresql://... pytest -m postgres tests/services/test_motor_service_postgres.py

Existe para não depender de verificação manual: prova, de forma repetível,
que `init_db()` cria `thesis_book`/`thesis_book_legs` em Postgres, que o seed
roda contra ele, e que o ladder/VaR/consumo lidos de volta com uma conexão
NOVA batem com o golden — não com o snapshot local.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from src.config import load_dotenv
from src.database.connection import dialect_of, get_database_url

load_dotenv()  # popula DATABASE_URL/COPILOT_DB do .env antes do skipif de coleta

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden" / "motor"


def _tem_postgres_configurado() -> bool:
    url = get_database_url()
    return bool(url) and url.startswith(("postgres://", "postgresql://"))


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not _tem_postgres_configurado(),
        reason="DATABASE_URL/COPILOT_DB nao aponta para Postgres nesta execucao.",
    ),
]


def test_schema_cria_thesis_book_em_postgres():
    from src.database.connection import connect, init_db, table_names

    conn = init_db()
    try:
        assert dialect_of(conn) == "postgres"
        tabs = table_names(conn)
        assert "thesis_book" in tabs
        assert "thesis_book_legs" in tabs
        assert "theses" in tabs
    finally:
        conn.close()


def test_seed_e_round_trip_contra_postgres():
    import json

    from src.database.connection import connect, init_db
    from src.motor.avaliar import avaliar
    from src.services import motor_service as MS
    from src.services.snapshot_loader import load_default_snapshot

    conn = init_db()
    try:
        snapshot = load_default_snapshot()
        assert snapshot is not None, "commite um snapshot em motor_curva/snapshots/ antes deste teste"
        ref_mercado = snapshot.notas["ref_mercado_geracao"]
        resultado = avaliar(snapshot, ref_mercado, Decimal("50000000.00"))

        registro = MS.register_thesis_from_motor(
            conn, snapshot=snapshot, ref_mercado=ref_mercado,
            title="[teste-postgres] Book Entrega 2", summary="Round-trip automatizado.",
            direction="VENDER", product="Convencional flat mensal SE/CO", submarket="SE/CO",
            owner="pytest", as_of=snapshot.as_of, avaliado=resultado,
        )
    finally:
        conn.close()

    # conexao NOVA, processo logicamente separado do insert acima.
    conn2 = connect()
    try:
        assert dialect_of(conn2) == "postgres"
        livro = MS.get_thesis_book(conn2, registro["thesis_id"])
        assert livro is not None
        assert len(livro["legs"]) == 5

        var_total = Decimal(str(livro["var_total"]))
        assert var_total == pytest.approx(Decimal("29892814.54"), abs=Decimal("1"))
        assert float(livro["consumo_limite"]) == pytest.approx(0.5979, abs=1e-3)

        por_mes = {p["mes_ref"]: p for p in livro["legs"]}
        assert Decimal(por_mes["2026-08-01"]["mwmed"]) == Decimal("43")
        assert Decimal(por_mes["2026-09-01"]["mwmed"]) == Decimal("188")
        assert Decimal(por_mes["2026-10-01"]["mwmed"]) == Decimal("119")
        assert Decimal(por_mes["2026-11-01"]["mwmed"]) == Decimal("74")
        assert Decimal(por_mes["2026-12-01"]["mwmed"]) == Decimal("62")
    finally:
        # limpeza: nao deixar lixo de teste na base de producao.
        conn2.execute("DELETE FROM theses WHERE id = ?", (registro["thesis_id"],))
        conn2.commit()
        conn2.close()
