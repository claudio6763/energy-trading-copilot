"""Linhagem de dados: hash, proveniencia e manifesto imutavel."""
from __future__ import annotations
import hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from .config import DIR_RAW, RAIZ

MANIFESTO = RAIZ / "data_manifest.json"


def sha256(caminho: Path, bloco: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for pedaco in iter(lambda: fh.read(bloco), b""):
            h.update(pedaco)
    return h.hexdigest()


def _carrega() -> dict:
    if MANIFESTO.exists():
        return json.loads(MANIFESTO.read_text(encoding="utf-8"))
    return {"gerado_em": None, "itens": []}


def registrar(instituicao: str, conjunto: str, url_origem: str, url_recurso: str,
              caminho: Path, frequencia: str, colunas: list[str] | None = None,
              transformacoes: list[str] | None = None, limitacoes: str = "",
              periodo: tuple[str, str] | None = None) -> dict:
    caminho = Path(caminho)
    item = {
        "instituicao": instituicao,
        "conjunto": conjunto,
        "url_origem": url_origem,
        "url_recurso": url_recurso,
        "arquivo": str(caminho.relative_to(RAIZ)) if str(caminho).startswith(str(RAIZ)) else str(caminho),
        "baixado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_referencia": None,
        "periodo_coberto": list(periodo) if periodo else None,
        "frequencia_atualizacao": frequencia,
        "sha256": sha256(caminho) if caminho.exists() else None,
        "bytes": caminho.stat().st_size if caminho.exists() else None,
        "colunas_utilizadas": colunas or [],
        "transformacoes": transformacoes or [],
        "qualidade_limitacoes": limitacoes,
    }
    m = _carrega()
    m["itens"] = [i for i in m["itens"] if i["arquivo"] != item["arquivo"]] + [item]
    m["gerado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    MANIFESTO.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return item


def itens() -> list[dict]:
    return _carrega()["itens"]
