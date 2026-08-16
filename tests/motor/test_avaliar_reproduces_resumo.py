"""Golden test: `avaliar()` sobre o snapshot pinado reproduz `resumo_execucao.json`.

Pinado de proposito: carrega dois arquivos fixos (`motor_curva/snapshots/*.json`
e `tests/golden/motor/resumo_execucao_2026-08-14.json`), nunca gera dado novo e
nunca compara contra `outputs/` vivo. Se `avaliar()` divergir de um centavo, a
extracao esta errada — nao o snapshot.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.motor.avaliar import avaliar
from src.motor.snapshot import MotorSnapshot

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden" / "motor"
SNAPSHOTS_DIR = Path(__file__).resolve().parents[2] / "motor_curva" / "snapshots"

#: Tolerancia de arredondamento entre o float do motor e o round-trip JSON.
TOL_ABS = 1e-6
TOL_REL = 1e-9


def _snapshot_path() -> Path:
    ref = (GOLDEN_DIR / "snapshot_ref.txt").read_text(encoding="utf-8").strip()
    path = SNAPSHOTS_DIR / ref
    if not path.exists():
        pytest.skip(
            f"snapshot pinado {path} nao encontrado — rode "
            "scripts/build_motor_snapshot.py para gerar (fora do escopo do CI)."
        )
    return path


def _resumo_golden() -> dict:
    candidatos = sorted(GOLDEN_DIR.glob("resumo_execucao_*.json"))
    if not candidatos:
        pytest.skip("nenhum tests/golden/motor/resumo_execucao_*.json commitado.")
    return json.loads(candidatos[0].read_text(encoding="utf-8"))


def _assert_close(nome: str, esperado, obtido) -> None:
    if esperado is None:
        assert obtido is None, f"{nome}: esperado None, obtido {obtido!r}"
        return
    if isinstance(esperado, (int, float)):
        assert obtido == pytest.approx(esperado, abs=TOL_ABS, rel=TOL_REL), (
            f"{nome}: esperado {esperado!r}, obtido {obtido!r}"
        )
    else:
        assert obtido == esperado, f"{nome}: esperado {esperado!r}, obtido {obtido!r}"


@pytest.fixture(scope="module")
def resultado():
    snap = MotorSnapshot.load(_snapshot_path())
    resumo = _resumo_golden()

    ref_mercado_geracao = snap.notas.get("ref_mercado_geracao")
    assert ref_mercado_geracao, (
        "snapshot sem 'ref_mercado_geracao' em notas — nao da para reproduzir "
        "o resumo golden sem saber qual referencia de mercado gerou ele."
    )
    hoje_geracao = date.fromisoformat(snap.notas["hoje_geracao"])

    # P8 / CLAUDE.md: limite de VaR do case, R$ 50 milhoes. Constante do
    # projeto, nao derivada do golden.
    LIMITE_VAR_BRL = 50_000_000.00
    saida = avaliar(snap, ref_mercado_geracao, LIMITE_VAR_BRL, hoje=hoje_geracao)
    return saida, resumo


def test_status_e_metadados(resultado):
    saida, resumo = resultado
    assert saida["status"] == resumo["status"]
    assert saida["submercado"] == resumo["submercado"]
    assert saida["meia_vida_dias"] == resumo["meia_vida_dias"]
    _assert_close("k_seco", resumo["k_seco"], saida["k_seco"])
    _assert_close("k_umido", resumo["k_umido"], saida["k_umido"])
    _assert_close("premio_nivel_rs_mwh", resumo["premio_nivel_rs_mwh"], saida["premio_nivel_rs_mwh"])
    _assert_close("k_premio_por_dispersao", resumo["k_premio_por_dispersao"], saida["k_premio_por_dispersao"])


def test_ladder_por_vertice(resultado):
    saida, resumo = resultado
    ladder_esperado = {linha["mes"]: linha for linha in resumo["book"]["ladder"]}
    ladder_obtido = {linha["mes"]: linha for linha in saida["book"]["ladder"]}
    assert set(ladder_obtido) == set(ladder_esperado), (
        f"vertices diferentes: esperado {sorted(ladder_esperado)}, "
        f"obtido {sorted(ladder_obtido)}"
    )
    for mes, esperado in ladder_esperado.items():
        obtido = ladder_obtido[mes]
        for campo in ("mwmed", "horas", "mwh", "preco_entrada"):
            _assert_close(f"ladder[{mes}].{campo}", esperado[campo], obtido[campo])


def test_agregados_do_book(resultado):
    saida, resumo = resultado
    campos = (
        "energia_liquida_gwh", "notional_brl", "preco_entrada_medio_mwh",
        "mwmed_equivalente_flat", "soma_mwm_pernas", "mwmed_bruto", "mwmed_liquido_abs",
        "var_total", "es_total", "consumo_limite",
        "pnl_Convergencia", "pnl_Entrega_Esperado", "pnl_Entrega_Seco", "pnl_Entrega_Umido",
        "vpl",
    )
    for campo in campos:
        _assert_close(campo, resumo["book"][campo], saida["book"][campo])


def test_var_dentro_do_limite_e_consumo_esperado(resultado):
    saida, _resumo = resultado
    book = saida["book"]
    assert book["var_total"] > 0
    assert 0 < book["consumo_limite"] < 1
