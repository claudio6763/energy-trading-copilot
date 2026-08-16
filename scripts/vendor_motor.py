"""Vendoriza o motor (`projeto_curva_v4/src`) para `motor_curva/`, byte a byte.

Copia plana: cada `<source>/src/*.py` vira `motor_curva/*.py`. Todos os imports
internos do motor sao relativos (`from .config`, `from . import risco`), entao
achatar o pacote de `src` para `motor_curva` funciona sem tocar em uma linha.

Se algum arquivo do motor tiver `from src.` (import absoluto), a copia fiel
quebraria calada — o script falha explicitamente nesse caso, em vez de copiar.

Nunca edite `motor_curva/*.py` a mao. Conserto e na fonte (`projeto_curva_v4`),
seguido de resync (rodar este script de novo). `motor_curva/VENDOR_MANIFEST.json`
grava o SHA-256 de cada arquivo fonte x vendorizado, para auditar depois se a
copia ainda bate.

`motor_curva/snapshots/` nunca e tocado por este script — e artefato de dados
gerado por `scripts/build_motor_snapshot.py`, nao codigo vendorizado.

Uso:
    python scripts/vendor_motor.py --source "C:\\caminho\\para\\projeto_curva_v4"
    python scripts/vendor_motor.py --source ... --check   # so verifica, nao copia
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEST_DIR = REPO_ROOT / "motor_curva"
MANIFEST_PATH = DEST_DIR / "VENDOR_MANIFEST.json"

#: Import absoluto que quebraria calado ao achatar o pacote.
FORBIDDEN_IMPORT_RE = re.compile(r"^\s*from\s+src(\.|@|\s)", re.MULTILINE)
FORBIDDEN_IMPORT_RE2 = re.compile(r"^\s*import\s+src(\.|@|\s|$)", re.MULTILINE)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def find_source_files(source_src: Path) -> list[Path]:
    if not source_src.is_dir():
        raise SystemExit(f"FALHA: pasta de origem nao encontrada: {source_src}")
    arquivos = sorted(source_src.glob("*.py"))
    if not arquivos:
        raise SystemExit(f"FALHA: nenhum .py encontrado em {source_src}")
    return arquivos


def assert_no_absolute_imports(arquivos: list[Path]) -> None:
    """Falha explicita se algum arquivo importar `src.` de forma absoluta.

    Achatar `src/` -> `motor_curva/` so e seguro porque hoje todo import interno
    e relativo. Se isso mudar na fonte, a copia fiel quebraria em silencio — o
    resync tem de parar aqui, nao produzir um `motor_curva/` quebrado.
    """
    ofensores: list[str] = []
    for arquivo in arquivos:
        texto = arquivo.read_text(encoding="utf-8")
        if FORBIDDEN_IMPORT_RE.search(texto) or FORBIDDEN_IMPORT_RE2.search(texto):
            ofensores.append(arquivo.name)
    if ofensores:
        raise SystemExit(
            "FALHA: import absoluto 'from src.' / 'import src' encontrado em: "
            + ", ".join(ofensores)
            + ". A vendorizacao plana (src/*.py -> motor_curva/*.py) quebraria esses "
              "imports silenciosamente. Corrija a FONTE para import relativo antes de "
              "vendorizar — nunca edite a copia vendorizada para contornar isso."
        )


def vendor(source_root: Path, *, check_only: bool = False) -> dict:
    source_src = source_root / "src"
    arquivos = find_source_files(source_src)
    assert_no_absolute_imports(arquivos)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    pares = []
    divergencias = []
    for src_file in arquivos:
        dest_file = DEST_DIR / src_file.name
        src_hash = sha256_of(src_file)
        if check_only:
            if not dest_file.exists():
                divergencias.append(f"{src_file.name}: ausente em motor_curva/")
            elif sha256_of(dest_file) != src_hash:
                divergencias.append(f"{src_file.name}: hash diverge da fonte")
        else:
            dest_file.write_bytes(src_file.read_bytes())
        pares.append({
            "arquivo": src_file.name,
            "sha256_fonte": src_hash,
            "sha256_vendorizado": src_hash if not check_only else (
                sha256_of(dest_file) if dest_file.exists() else None
            ),
        })

    if check_only:
        if divergencias:
            raise SystemExit("FALHA no --check:\n  " + "\n  ".join(divergencias))
        print(f"OK: {len(arquivos)} arquivo(s) vendorizado(s) batem com a fonte.")
        return {"checked": len(arquivos)}

    manifest = {
        "gerado_em": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "fonte": str(source_root),
        "n_arquivos": len(pares),
        "arquivos": pares,
        "aviso": (
            "Nunca edite motor_curva/*.py a mao. Conserto e na fonte, seguido de "
            "resync (python scripts/vendor_motor.py --source <projeto_curva_v4>)."
        ),
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Vendorizados {len(pares)} arquivo(s) de {source_src} para {DEST_DIR}")
    print(f"Manifesto: {MANIFEST_PATH}")
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", required=True,
        help="Caminho da raiz do projeto do motor (contem src/*.py), ex.: projeto_curva_v4",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Nao copia; so verifica se motor_curva/ ainda bate com a fonte.",
    )
    args = parser.parse_args(argv)
    vendor(Path(args.source).resolve(), check_only=args.check)


if __name__ == "__main__":
    main(sys.argv[1:])
