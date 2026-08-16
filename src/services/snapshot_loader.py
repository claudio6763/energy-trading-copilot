"""Acesso ao snapshot congelado do motor, cacheado por processo.

`@st.cache_data` no carregamento do snapshot: recarregar o JSON a cada rerun
do Streamlit mataria a meta de menos de 10s do registro ao vivo (o snapshot
em si nao muda entre reruns — so a referencia de mercado que o trader digita).
"""

from __future__ import annotations

from pathlib import Path

from src.motor.snapshot import MotorSnapshot

SNAPSHOTS_DIR = Path(__file__).resolve().parents[2] / "motor_curva" / "snapshots"


def list_snapshot_paths() -> list[Path]:
    if not SNAPSHOTS_DIR.exists():
        return []
    return sorted(SNAPSHOTS_DIR.glob("*.json"))


def _load_snapshot_cached(path_str: str) -> MotorSnapshot:
    return MotorSnapshot.load(Path(path_str))


try:
    import streamlit as st

    _load_snapshot_cached = st.cache_data(show_spinner="Carregando snapshot do motor…")(
        _load_snapshot_cached
    )
except Exception:  # pragma: no cover - uso fora do Streamlit (scripts, testes)
    pass


def load_snapshot(path: str | Path) -> MotorSnapshot:
    return _load_snapshot_cached(str(path))


def load_default_snapshot() -> MotorSnapshot | None:
    """O snapshot mais recente (ordenacao por nome: `<as_of>_<hash>.json`)."""
    arquivos = list_snapshot_paths()
    if not arquivos:
        return None
    return load_snapshot(arquivos[-1])


__all__ = ["load_default_snapshot", "load_snapshot", "list_snapshot_paths"]
