"""Snapshots auditaveis do payload bruto.

Antes de virar dado, todo payload e gravado em disco e hasheado. Sem isso nao e
possivel responder a pergunta que a banca vai fazer: *"esse numero mudou, ou a
fonte mudou por baixo?"*.

Layout::

    data/snapshots/<dataset_kind>/<YYYY-MM-DD>/<adapter>__<ulid>.<ext>
    data/snapshots/<dataset_kind>/<YYYY-MM-DD>/<adapter>__<ulid>.meta.json

O `.meta.json` fica ao lado do payload para que o arquivo continue legivel mesmo
sem o banco — util na defesa, quando alguem pede para ver o dado cru.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from copilot.common.enums import DatasetKind
from copilot.common.ids import new_ulid
from copilot.common.logging import get_logger
from copilot.ingest.contracts import SnapshotRef

log = get_logger(__name__)

DEFAULT_SNAPSHOT_DIR = Path("data") / "snapshots"

#: Extensao por tipo de conteudo. Serve so para o arquivo ficar legivel.
_EXTENSIONS = {
    "text/csv": ".csv",
    "text/plain": ".txt",
    "application/json": ".json",
    "application/xml": ".xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


def payload_hash(payload: bytes) -> str:
    """SHA-256 do payload bruto. E o que detecta mudanca silenciosa da fonte."""
    return hashlib.sha256(payload).hexdigest()


class SnapshotStore:
    """Arquiva payloads brutos com hash e metadados."""

    def __init__(self, root: Path | str = DEFAULT_SNAPSHOT_DIR) -> None:
        self.root = Path(root)

    def path_for(
        self, adapter: str, *, as_of: date, dataset_kind: DatasetKind, snapshot_id: str,
        media_type: str,
    ) -> Path:
        extensao = _EXTENSIONS.get(media_type, ".bin")
        seguro = "".join(c if c.isalnum() or c in "-_" else "_" for c in adapter)
        return (
            self.root
            / dataset_kind.value
            / as_of.isoformat()
            / f"{seguro}__{snapshot_id}{extensao}"
        )

    def save(
        self,
        payload: bytes,
        *,
        adapter: str,
        as_of: date,
        dataset_kind: DatasetKind,
        media_type: str = "application/octet-stream",
        source_name: str | None = None,
        origin_uri: str | None = None,
    ) -> SnapshotRef:
        """Grava o payload e devolve a referencia auditavel."""
        snapshot_id = new_ulid()
        destino = self.path_for(
            adapter,
            as_of=as_of,
            dataset_kind=dataset_kind,
            snapshot_id=snapshot_id,
            media_type=media_type,
        )
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(payload)

        digest = payload_hash(payload)
        buscado_em = datetime.now(tz=timezone.utc)
        metadados = {
            "snapshot_id": snapshot_id,
            "adapter": adapter,
            "source_name": source_name,
            "origin_uri": origin_uri,
            "as_of": as_of.isoformat(),
            "dataset_kind": dataset_kind.value,
            "media_type": media_type,
            "byte_size": len(payload),
            "payload_sha256": digest,
            "fetched_at": buscado_em.isoformat(),
        }
        destino.with_suffix(destino.suffix + ".meta.json").write_text(
            json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        log.info(
            "snapshot_gravado",
            extra={
                "adapter": adapter,
                "snapshot_id": snapshot_id,
                "bytes": len(payload),
                "sha256": digest[:12],
            },
        )
        return SnapshotRef(
            snapshot_id=snapshot_id,
            payload_hash=digest,
            byte_size=len(payload),
            storage_uri=str(destino),
            fetched_at=buscado_em,
            media_type=media_type,
        )

    def load(self, ref: SnapshotRef) -> bytes:
        """Le o payload arquivado e confere o hash.

        Divergencia de hash e corrupcao ou adulteracao — nunca e ignorada.
        """
        caminho = Path(ref.storage_uri)
        if not caminho.exists():
            raise FileNotFoundError(f"Snapshot ausente: {caminho}")
        payload = caminho.read_bytes()
        atual = payload_hash(payload)
        if atual != ref.payload_hash:
            raise ValueError(
                f"Snapshot {ref.snapshot_id} com hash divergente: "
                f"esperado {ref.payload_hash[:12]}, encontrado {atual[:12]}."
            )
        return payload

    def verify(self, ref: SnapshotRef) -> bool:
        try:
            self.load(ref)
        except (FileNotFoundError, ValueError):
            return False
        return True


__all__ = ["DEFAULT_SNAPSHOT_DIR", "SnapshotStore", "payload_hash"]
