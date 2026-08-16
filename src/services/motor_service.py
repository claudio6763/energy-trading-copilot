"""Ponte entre `avaliar()` (motor) e o banco. Registra tese com book do motor.

Nenhum numero aqui vem de LLM (invariante 1). Todo campo numerico carrega
rotulo de natureza GRAVADO no INSERT (invariante 2, nunca recalculado depois)
e o `snapshot_hash` de origem (invariante 3). `risk_service.py` (VaR por
log-retorno de `market_observations`) NUNCA e chamado neste caminho —
`thesis_book` e a UNICA definicao de risco para tese do motor (invariante 5).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from src.database import repositories as R
from src.motor.avaliar import avaliar
from src.motor.snapshot import MotorSnapshot
from src.services import thesis_service as TS

MESES_PT = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]

#: Natureza fixa de cada campo agregado do book — usada so como DEFAULT no
#: INSERT. Depois de gravada em `thesis_book.natures_json`, e essa copia que
#: vale; mudar este dict nao reetiqueta registro velho (invariante 2).
HEADER_FIELD_NATURES: dict[str, str] = {
    "energia_mwh": "CALCULADO",
    "notional_brl": "CALCULADO",
    "preco_entrada_medio_mwh": "CALCULADO",
    "mwmed_equivalente_flat": "CALCULADO",
    "soma_mwm_pernas": "CALCULADO",
    "var_total": "CALCULADO",
    "es_total": "CALCULADO",
    "consumo_limite": "CALCULADO",
    "pnl_convergencia": "CALCULADO",
    "pnl_entrega_esperado": "CALCULADO",
    "pnl_entrega_seco": "CALCULADO",
    "pnl_entrega_umido": "CALCULADO",
    "vpl": "CALCULADO",
    "premio_nivel_rs_mwh": "CALCULADO",
    "k_premio": "CALCULADO",
}

LEG_FIELD_NATURES: dict[str, str] = {
    "mwmed": "CALCULADO",
    "horas": "CALCULADO",
    "mwh": "CALCULADO",
    "preco_entrada": "PREMISSA",
}


def _label_para_mes_ref(label: str) -> str:
    """'AGO/26' -> '2026-08-01'. Inverso de `motor_curva.book.rotulo_mes`."""
    nome, ano2 = label.split("/")
    mes = MESES_PT.index(nome.upper()) + 1
    ano = 2000 + int(ano2)
    return f"{ano:04d}-{mes:02d}-01"


def _num(valor: Any) -> str | None:
    """Numero (motor usa float) -> texto, nunca via float perdendo centavo
    na escrita: `Decimal(str(...))` normaliza antes de persistir como texto."""
    if valor is None:
        return None
    return str(Decimal(str(valor)))


def register_thesis_from_motor(
    conn,
    *,
    snapshot: MotorSnapshot,
    ref_mercado: dict[str, float],
    title: str,
    summary: str,
    direction: str,
    product: str,
    submarket: str,
    owner: str,
    as_of: str,
    horizon_days: int | None = None,
    review_date: str | None = None,
    exit_condition: str | None = None,
    invalidation: str | None = None,
    limite_var: Decimal = Decimal("50000000.00"),
    preco_entrada_origem: str = "leitura de mesa",
    actor: str = "trader",
    avaliado: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Registra a tese com o book proposto pelo motor. Devolve `{thesis_id, book_id, evidence_id}`.

    `avaliado`: se ja tiver o resultado de `avaliar()` a mao (ex.: o mesmo que
    a tela mostrou antes de "Salvar"), passe aqui para nao rodar de novo — mas
    o resultado tem de ser exatamente o de `avaliar(snapshot, ref_mercado,
    limite_var)`, senao o que fica salvo diverge do que a tela mostrou.
    """
    resultado = avaliado if avaliado is not None else avaliar(snapshot, ref_mercado, limite_var)
    book = resultado["book"]
    ladder = book.get("ladder", [])
    if not ladder:
        raise ValueError(
            "FALHA EXPLICITA: o motor nao propos nenhuma perna para essa referencia "
            "de mercado (sinal FORA em todos os vertices). Nao ha book para registrar."
        )

    tid = TS.create_thesis(
        conn, title=title, summary=summary, direction=direction, product=product,
        submarket=submarket, owner=owner, as_of=as_of, horizon_days=horizon_days,
        review_date=review_date, exit_condition=exit_condition, invalidation=invalidation,
        actor=actor,
    )

    excerto = (
        f"Motor de curva (snapshot {snapshot.compute_hash()[:12]}): book de "
        f"{len(ladder)} vertice(s), VaR total R$ {book['var_total']:.2f} "
        f"({book['consumo_limite']:.2%} do limite de R$ {float(limite_var):.2f}), "
        f"notional R$ {book['notional_brl']:.2f}, energia {book['energia_liquida_gwh']*1000:.0f} MWh."
    )
    eid = R.create_evidence(
        conn, kind="CALCULO", source_name="Motor de Curva (motor_curva)",
        locator=f"motor:{snapshot.compute_hash()}", excerpt=excerto,
        value=Decimal(str(book["var_total"])), unit="R$", as_of=as_of,
        classification="projetado",
    )

    natures_header = dict(HEADER_FIELD_NATURES)
    bid = R.new_id()
    conn.execute(
        "INSERT INTO thesis_book (id, thesis_id, snapshot_hash, ref_mercado_json, modo_sinal, "
        "premio_nivel_rs_mwh, k_premio, var_total, es_total, var_limit, consumo_limite, "
        "energia_mwh, notional_brl, preco_entrada_medio_mwh, mwmed_equivalente_flat, "
        "soma_mwm_pernas, pnl_convergencia, pnl_entrega_esperado, pnl_entrega_seco, "
        "pnl_entrega_umido, vpl, natures_json, evidence_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            bid, tid, snapshot.compute_hash(), json.dumps(ref_mercado, ensure_ascii=False),
            resultado["modo_sinal"], _num(resultado.get("premio_nivel_rs_mwh")),
            _num(resultado.get("k_premio_por_dispersao")), _num(book["var_total"]),
            _num(book.get("es_total")), _num(limite_var), _num(book["consumo_limite"]),
            _num(book["energia_liquida_gwh"] * 1000),  # GWh do motor -> MWh (CLAUDE.md: energia em MWh)
            _num(book["notional_brl"]), _num(book.get("preco_entrada_medio_mwh")),
            _num(book.get("mwmed_equivalente_flat")), _num(book.get("soma_mwm_pernas")),
            _num(book.get("pnl_Convergencia")), _num(book.get("pnl_Entrega_Esperado")),
            _num(book.get("pnl_Entrega_Seco")), _num(book.get("pnl_Entrega_Umido")),
            _num(book.get("vpl")), json.dumps(natures_header, ensure_ascii=False), eid, R.now_iso(),
        ),
    )

    for linha in ladder:
        mes_ref = _label_para_mes_ref(linha["mes"])
        lid = R.new_id()
        conn.execute(
            "INSERT INTO thesis_book_legs (id, book_id, mes_ref, lado, mwmed, mwmed_nature, "
            "horas, horas_nature, mwh, mwh_nature, preco_entrada, preco_entrada_nature, "
            "preco_entrada_origem, snapshot_hash, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                lid, bid, mes_ref, "VENDIDO",
                _num(linha["mwmed"]), LEG_FIELD_NATURES["mwmed"],
                int(linha["horas"]), LEG_FIELD_NATURES["horas"],
                _num(linha["mwh"]), LEG_FIELD_NATURES["mwh"],
                _num(linha["preco_entrada"]), LEG_FIELD_NATURES["preco_entrada"],
                preco_entrada_origem, snapshot.compute_hash(), R.now_iso(),
            ),
        )

    R.audit(
        conn, action="QUANT_RUN", entity="thesis_book", entity_id=bid, actor=actor,
        tool="motor_curva.avaliar", evidence_ids=[eid], as_of=as_of,
        input_data={"snapshot_hash": snapshot.compute_hash(), "ref_mercado": ref_mercado},
        output_data={"var_total": str(book["var_total"]), "consumo_limite": str(book["consumo_limite"])},
    )
    if hasattr(conn, "commit"):
        conn.commit()

    return {"thesis_id": tid, "book_id": bid, "evidence_id": eid}


def get_thesis_book(conn, thesis_id: str) -> dict[str, Any] | None:
    """Le de volta o book de uma tese (o mais recente), com ladder e naturezas."""
    row = conn.execute(
        "SELECT * FROM thesis_book WHERE thesis_id = ? ORDER BY created_at DESC LIMIT 1",
        (thesis_id,),
    ).fetchone()
    if not row:
        return None
    livro = dict(row)
    livro["ref_mercado"] = json.loads(livro["ref_mercado_json"])
    livro["natures"] = json.loads(livro["natures_json"])
    pernas = conn.execute(
        "SELECT * FROM thesis_book_legs WHERE book_id = ? ORDER BY mes_ref", (livro["id"],)
    ).fetchall()
    livro["legs"] = [dict(p) for p in pernas]
    return livro


__all__ = [
    "HEADER_FIELD_NATURES", "LEG_FIELD_NATURES", "get_thesis_book",
    "register_thesis_from_motor",
]
