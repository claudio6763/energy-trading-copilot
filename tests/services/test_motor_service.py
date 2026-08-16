"""Round-trip de persistencia: registra tese com book do motor, fecha a
conexao, abre uma NOVA e le de volta — prova que nao e estado de sessao
(PROMPT_FINAL_COPILOTO.md, Parte 5: "derrubar e subir o app... e a tese
continuar la")."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.database.connection import connect, init_db
from src.motor.snapshot import MotorSnapshot
from src.services import motor_service as MS

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden" / "motor"
SNAPSHOTS_DIR = Path(__file__).resolve().parents[2] / "motor_curva" / "snapshots"


def _snapshot() -> MotorSnapshot:
    ref = (GOLDEN_DIR / "snapshot_ref.txt").read_text(encoding="utf-8").strip()
    path = SNAPSHOTS_DIR / ref
    if not path.exists():
        pytest.skip(f"snapshot pinado {path} nao encontrado.")
    return MotorSnapshot.load(path)


@pytest.fixture()
def db_file(tmp_path, monkeypatch):
    path = tmp_path / "roundtrip.db"
    monkeypatch.setenv("COPILOT_DB", str(path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    conn = init_db()
    conn.close()
    return path


def test_registro_sobrevive_a_reabertura_da_conexao(db_file):
    snap = _snapshot()
    ref_mercado = snap.notas["ref_mercado_geracao"]

    conn1 = connect(db_file)
    resultado = MS.register_thesis_from_motor(
        conn1, snapshot=snap, ref_mercado=ref_mercado,
        title="Book Entrega 2 — SE/CO", summary="Venda de energia convencional flat SE/CO,\n"
        "ago-dez/26, calibrada contra a referencia de mesa.",
        direction="VENDER", product="Convencional flat mensal", submarket="SE/CO",
        owner="trader", as_of=snap.as_of, horizon_days=120,
        review_date="2026-09-15", exit_condition="premio abaixo de 15 R$/MWh",
        invalidation="ordenacao Seco>Base>Umido invertida",
        limite_var=Decimal("50000000.00"), preco_entrada_origem="leitura de mesa",
    )
    conn1.close()

    # conexao NOVA, processo "reiniciado" — nada de estado de sessao.
    conn2 = connect(db_file)
    tese = conn2.execute("SELECT * FROM theses WHERE id = ?", (resultado["thesis_id"],)).fetchone()
    assert tese is not None
    assert tese["title"] == "Book Entrega 2 — SE/CO"

    livro = MS.get_thesis_book(conn2, resultado["thesis_id"])
    conn2.close()

    assert livro is not None
    assert livro["id"] == resultado["book_id"]
    assert livro["snapshot_hash"] == snap.compute_hash()
    assert len(livro["legs"]) == 5
    assert livro["natures"]["var_total"] == "CALCULADO"

    meses = {p["mes_ref"] for p in livro["legs"]}
    assert meses == {"2026-08-01", "2026-09-01", "2026-10-01", "2026-11-01", "2026-12-01"}
    for perna in livro["legs"]:
        assert perna["lado"] == "VENDIDO"
        assert perna["preco_entrada_nature"] == "PREMISSA"
        assert perna["preco_entrada_origem"] == "leitura de mesa"
        assert perna["snapshot_hash"] == snap.compute_hash()

    ago = next(p for p in livro["legs"] if p["mes_ref"] == "2026-08-01")
    assert Decimal(ago["mwmed"]) == Decimal("43")
    assert Decimal(ago["mwh"]) == Decimal("31992")
    assert Decimal(ago["preco_entrada"]) == Decimal("142.0") or Decimal(ago["preco_entrada"]) == Decimal("142")

    notional = Decimal(livro["notional_brl"])
    assert notional == pytest.approx(Decimal("78972444.00"), abs=Decimal("1"))


def test_falha_explicita_sem_referencia_de_mercado_completa(db_file):
    snap = _snapshot()
    ref_incompleta = {"2026-08": 142.0}  # faltam set/out/nov/dez
    conn = connect(db_file)
    try:
        with pytest.raises(ValueError):
            MS.register_thesis_from_motor(
                conn, snapshot=snap, ref_mercado=ref_incompleta,
                title="x", summary="x", direction="VENDER", product="x", submarket="SE/CO",
                owner="trader", as_of=snap.as_of,
            )
    finally:
        conn.close()
