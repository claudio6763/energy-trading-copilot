"""Extracao de texto de PDF, pagina a pagina.

Cadeia de fallback (Secao 17 do escopo): PyMuPDF -> pypdf -> erro explicito.
Nenhuma das duas presente, ou PDF sem camada de texto (digitalizado sem OCR),
resulta em erro claro em vez de documento vazio indexado.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class PdfExtractionError(RuntimeError):
    """PDF ilegivel. Nunca degrada para documento vazio."""


def available_backend() -> str | None:
    for modulo, nome in (("fitz", "pymupdf"), ("pypdf", "pypdf")):
        try:
            __import__(modulo)
            return nome
        except ImportError:
            continue
    return None


def file_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extract_pages(path: str | Path) -> list[str]:
    """Devolve uma string por pagina."""
    caminho = Path(path)
    if not caminho.exists():
        raise PdfExtractionError(f"Arquivo nao encontrado: {caminho}")

    try:  # preferencial
        import fitz  # type: ignore

        with fitz.open(str(caminho)) as documento:
            paginas = [pagina.get_text("text") or "" for pagina in documento]
        if any(p.strip() for p in paginas):
            return paginas
    except ImportError:
        pass
    except Exception as exc:  # pragma: no cover - PDF corrompido
        raise PdfExtractionError(f"PyMuPDF falhou em {caminho.name}: {exc}") from exc

    try:  # fallback
        from pypdf import PdfReader  # type: ignore

        leitor = PdfReader(str(caminho))
        paginas = [(p.extract_text() or "") for p in leitor.pages]
        if any(p.strip() for p in paginas):
            return paginas
        raise PdfExtractionError(
            f"{caminho.name}: nenhuma pagina com texto. PDF provavelmente digitalizado "
            "sem OCR — converta antes de ingerir."
        )
    except ImportError as exc:
        raise PdfExtractionError(
            "Nenhum leitor de PDF disponivel. Instale `pymupdf` ou `pypdf`."
        ) from exc


def extract_text_file(path: str | Path) -> list[str]:
    """Fallback para .txt/.md: uma 'pagina' a cada 3000 caracteres."""
    texto = Path(path).read_text(encoding="utf-8", errors="replace")
    return [texto[i:i + 3000] for i in range(0, len(texto), 3000)] or [""]


def load_pages(path: str | Path) -> list[str]:
    """Despacha por extensao. Aceita PDF, TXT e MD."""
    sufixo = Path(path).suffix.lower()
    if sufixo == ".pdf":
        return extract_pages(path)
    if sufixo in {".txt", ".md"}:
        return extract_text_file(path)
    raise PdfExtractionError(f"Extensao nao suportada para acervo: {sufixo}")


__all__ = [
    "PdfExtractionError", "available_backend", "extract_pages", "extract_text_file",
    "file_hash", "load_pages",
]
