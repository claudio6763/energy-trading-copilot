"""Ponte entre os adapters de ingestão (`copilot.ingest`, mundo dataclass) e a
persistência sqlite3 do runtime (`src.database.repositories`).

Por que existe: os adapters de `copilot.ingest.adapters` são stdlib puro,
sem banco, para serem testáveis isoladamente (ver `copilot/ingest/contracts.py`).
O runtime do MVP usa sqlite3 direto (ADR-011, `SPRINT_STATUS.md`). Este módulo
é o único lugar que conhece os dois lados — nada mais no projeto deveria
precisar importar dos dois mundos ao mesmo tempo.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from copilot.common.enums import DataQuality
from copilot.ingest.contracts import AdapterResult
from src.database import repositories as R

#: AdapterStatus -> integration_status já existente em `sources` (schema não
#: é alterado; a classificação mais rica do prompt de integrações — PUBLIC_NO_AUTH,
#: OPTIONAL_LICENSED etc. — fica em `license_note`, texto livre já suportado).
_STATUS_TO_INTEGRATION = {
    "OK": "LIVE_VALIDATED",
    "PARCIAL": "LIVE_VALIDATED",
    "INDISPONÍVEL": "ERROR",
    "REJEITADO": "ERROR",
}

_QUALITY_TO_CLASSIFICATION = {
    DataQuality.OK: "observado",
    DataQuality.PRELIMINAR: "indicativo",
    DataQuality.ESTIMADO: "projetado",
    DataQuality.INCOMPLETO: "indicativo",
    DataQuality.SUSPEITO: "indicativo",
    DataQuality.PROXY: "proxy",
}


def _classification(quality: DataQuality) -> str:
    return _QUALITY_TO_CLASSIFICATION.get(quality, "indicativo")


def persist_adapter_result(
    conn: sqlite3.Connection,
    resultado: AdapterResult,
    *,
    as_of: str,
    access_label: str | None = None,
) -> dict[str, Any]:
    """Grava observações, curvas e o registro de execução (`ingest_snapshots`).

    Idempotente: reaproveita os `UNIQUE` de `market_observations` e
    `forward_curves` (upsert via `INSERT OR REPLACE` nos repositórios — rodar
    duas vezes com o mesmo `as_of`/`ref_date` não duplica linha). A run fica
    sempre registrada em `ingest_snapshots`, mesmo quando não há dado algum —
    é o que garante que uma fonte indisponível nunca vira silêncio (RF-36).
    """
    fonte = resultado.source
    houve_dado = bool(resultado.observations or resultado.curves)
    rotulo_acesso = access_label or fonte.license_class.value

    source_id = R.upsert_source(
        conn,
        name=fonte.name,
        institution=fonte.publisher,
        source_kind=fonte.source_kind.value,
        integration_status=(
            _STATUS_TO_INTEGRATION.get(resultado.status.value, "ERROR")
            if houve_dado
            else "NOT_CONFIGURED" if resultado.status.value in ("INDISPONÍVEL",) else "ERROR"
        ),
        url=fonte.url,
        license_note=f"[{rotulo_acesso}] {fonte.notes or ''}".strip(),
        authorized=fonte.authorized,
        update_frequency=fonte.update_frequency,
        notes=resultado.reason,
    )

    observacoes_gravadas = 0
    for linha in resultado.observations:
        R.insert_observation(
            conn,
            metric=linha.metric_key,
            value=linha.value,
            unit=linha.unit.value,
            ref_date=linha.ref_date.isoformat(),
            as_of=linha.as_of.isoformat(),
            source_name=fonte.name,
            source_id=source_id,
            classification=_classification(linha.quality),
            submarket=linha.submarket.value if linha.submarket else None,
            model_run=linha.model_run,
            excerpt=linha.evidence_excerpt(fonte.name),
        )
        observacoes_gravadas += 1

    curvas_gravadas = 0
    pontos_gravados = 0
    for curva in resultado.curves:
        curve_id, _eid = R.insert_curve(
            conn,
            curve_name=curva.curve_name,
            submarket=curva.submarket.value,
            as_of=curva.as_of.isoformat(),
            source_name=fonte.name,
            classification=_classification(curva.quality),
            origin=curva.origin.value,
            energy_source=curva.product_class.value,
            quote_type=curva.price_type.value,
            proxy_of=curva.proxy_of,
            source_id=source_id,
            notes=curva.notes,
        )
        for ponto in curva.points:
            R.insert_curve_point(
                conn, curve_id,
                tenor=ponto.tenor_label,
                delivery_start=ponto.delivery_start.isoformat(),
                delivery_end=ponto.delivery_end.isoformat(),
                price=ponto.price,
                source_name=fonte.name,
                as_of=curva.as_of.isoformat(),
                classification=_classification(ponto.quality),
            )
            pontos_gravados += 1
        curvas_gravadas += 1

    if houve_dado:
        R.mark_source_success(conn, source_id, "LIVE_VALIDATED")

    run_id = R.new_id()
    conn.execute(
        "INSERT INTO ingest_snapshots (id, adapter, source_name, status, as_of, storage_uri, "
        "payload_hash, byte_size, rows_written, reason, fetched_at, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            run_id, resultado.adapter, fonte.name, resultado.status.value, as_of,
            resultado.snapshot.storage_uri if resultado.snapshot else None,
            resultado.snapshot.payload_hash if resultado.snapshot else None,
            resultado.snapshot.byte_size if resultado.snapshot else None,
            observacoes_gravadas + pontos_gravados,
            "; ".join(resultado.issues) if resultado.issues else resultado.reason,
            resultado.fetched_at.isoformat(), R.now_iso(),
        ),
    )
    R.audit(
        conn,
        action="INGEST" if resultado.ok else "INGEST_REJECTED",
        entity="source", entity_id=source_id, actor="sistema", actor_type="SISTEMA",
        tool=resultado.adapter, input_data={"as_of": as_of},
        output_data={
            "status": resultado.status.value, "observations": observacoes_gravadas,
            "curves": curvas_gravadas, "issues": list(resultado.issues),
        },
        as_of=as_of,
    )

    return {
        "run_id": run_id, "source_id": source_id, "adapter": resultado.adapter,
        "status": resultado.status.value, "observations": observacoes_gravadas,
        "curves": curvas_gravadas, "issues": list(resultado.issues),
        "reason": resultado.reason, "ok": resultado.ok,
    }


__all__ = ["persist_adapter_result"]
