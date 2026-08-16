"""RAG lexical sobre SQLite FTS5. Stdlib pura — sem vector db, sem embeddings.

Decisao (ADR-012): busca lexical resolve o caso de uso. Norma do setor eletrico
tem jargao fixo e numeracao de artigo; busca densa erra referencia com mais
frequencia do que acerta sinonimo. FTS5 vem no `sqlite3` da stdlib.

Toda recuperacao devolve **pagina** e `evidence_id`. Resposta sem trecho
recuperado e "Regra nao confirmada nas fontes disponiveis" — nunca conhecimento
parametrico do modelo.

Documento recuperado e **dado nao confiavel**: `sanitize()` neutraliza instrucao
embutida antes de o trecho chegar ao prompt.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from src.database import repositories as R

NOT_CONFIRMED = "Regra não confirmada nas fontes disponíveis."
CHUNK_CHARS = 1100
CHUNK_OVERLAP = 150

#: Padroes de injecao que podem aparecer dentro de um PDF.
_INJECTION = re.compile(
    r"(ignore (as |todas as )?instru|desconsidere.{0,20}(anterior|acima)|"
    r"system prompt|voce agora e|you are now|disregard (all )?previous)",
    re.IGNORECASE,
)


def sanitize(texto: str) -> str:
    """Neutraliza instrucao embutida no documento. Conteudo != comando."""
    return _INJECTION.sub("[trecho neutralizado pelo filtro de injecao]", texto or "")


def chunk_page(texto: str, *, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Divide o texto da pagina, quebrando preferencialmente em fim de frase."""
    limpo = re.sub(r"[ \t]+", " ", (texto or "").strip())
    if not limpo:
        return []
    if len(limpo) <= size:
        return [limpo]
    pedacos, inicio = [], 0
    while inicio < len(limpo):
        fim = min(inicio + size, len(limpo))
        if fim < len(limpo):
            corte = max(limpo.rfind(". ", inicio, fim), limpo.rfind("\n", inicio, fim))
            if corte > inicio + size // 2:
                fim = corte + 1
        pedacos.append(limpo[inicio:fim].strip())
        if fim >= len(limpo):
            break
        inicio = max(fim - overlap, inicio + 1)
    return [p for p in pedacos if p]


def add_document(
    conn: sqlite3.Connection,
    *,
    title: str,
    institution: str,
    doc_type: str,
    pages: Sequence[str],
    version: str | None = None,
    published_at: str | None = None,
    effective_from: str | None = None,
    effective_to: str | None = None,
    file_path: str | None = None,
    url: str | None = None,
    file_hash: str | None = None,
) -> str:
    """Ingere o documento pagina a pagina e indexa no FTS5."""
    if not pages:
        raise ValueError("Documento sem paginas legiveis. PDF pode ser imagem sem OCR.")
    did = R.new_id()
    conn.execute(
        "INSERT INTO documents (id, title, institution, doc_type, version, published_at, "
        "effective_from, effective_to, file_path, url, file_hash, page_count, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (did, title, institution, doc_type, version, published_at, effective_from,
         effective_to, file_path, url, file_hash or R.content_hash("".join(pages)),
         len(pages), R.now_iso()),
    )
    total = 0
    for numero, bruto in enumerate(pages, start=1):
        for indice, pedaco in enumerate(chunk_page(sanitize(bruto))):
            cid = R.new_id()
            conn.execute(
                "INSERT INTO document_chunks (id, document_id, page, chunk_index, text, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (cid, did, numero, indice, pedaco, R.now_iso()),
            )
            conn.execute(
                "INSERT INTO chunk_fts (text, chunk_id, document_id) VALUES (?,?,?)",
                (pedaco, cid, did),
            )
            total += 1
    R.audit(conn, action="INGEST", entity="documento", entity_id=did,
            output_data={"title": title, "institution": institution,
                         "pages": len(pages), "chunks": total})
    return did


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_title: str
    institution: str
    version: str | None
    effective_from: str | None
    effective_to: str | None
    page: int
    text: str
    score: float
    evidence_id: str | None = None

    def citation(self) -> str:
        partes = [self.institution, self.document_title]
        if self.version:
            partes.append(f"versao {self.version}")
        partes.append(f"p. {self.page}")
        if self.effective_from:
            partes.append(f"vigente desde {self.effective_from}")
        return " — ".join(partes)


def _fts_query(pergunta: str) -> str:
    """Monta consulta FTS5 tolerante: termos com >=3 letras, com prefixo."""
    termos = re.findall(r"[0-9A-Za-zÀ-ÿ]{3,}", pergunta or "")
    if not termos:
        return ""
    return " OR ".join(f'"{t}"*' for t in termos[:12])


def search(
    conn: sqlite3.Connection,
    pergunta: str,
    *,
    as_of: str,
    institution: str | None = None,
    doc_type: str | None = None,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """Recupera de 3 a 5 trechos, filtrando por vigencia e instituicao.

    Filtro de vigencia: `effective_from <= as_of` e (`effective_to` nulo ou
    `>= as_of`). Regra revogada nao volta como se valesse.
    """
    consulta = _fts_query(pergunta)
    if not consulta:
        return []
    sql = (
        "SELECT f.chunk_id, f.document_id, c.page, c.text, bm25(chunk_fts) AS score, "
        "d.title, d.institution, d.version, d.effective_from, d.effective_to "
        "FROM chunk_fts f "
        "JOIN document_chunks c ON c.id = f.chunk_id "
        "JOIN documents d ON d.id = f.document_id "
        "WHERE chunk_fts MATCH ? "
        "AND (d.effective_from IS NULL OR d.effective_from <= ?) "
        "AND (d.effective_to IS NULL OR d.effective_to >= ?) "
    )
    params: list[Any] = [consulta, as_of, as_of]
    if institution:
        sql += " AND d.institution = ?"
        params.append(institution)
    if doc_type:
        sql += " AND d.doc_type = ?"
        params.append(doc_type)
    sql += " ORDER BY score LIMIT ?"
    params.append(top_k)

    try:
        linhas = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []

    return [
        RetrievedChunk(
            chunk_id=r["chunk_id"], document_id=r["document_id"], document_title=r["title"],
            institution=r["institution"], version=r["version"],
            effective_from=r["effective_from"], effective_to=r["effective_to"],
            page=r["page"], text=r["text"], score=float(r["score"]),
        )
        for r in linhas
    ]


def search_with_evidence(
    conn: sqlite3.Connection, pergunta: str, *, as_of: str, **kwargs: Any
) -> list[RetrievedChunk]:
    """Recupera e cria `evidence` para cada trecho — todo trecho citavel."""
    resultados = search(conn, pergunta, as_of=as_of, **kwargs)
    comevidencia = []
    for r in resultados:
        eid = R.create_evidence(
            conn, kind="DOCUMENTO", source_name=r.institution,
            locator=f"{r.document_id}#p{r.page}#{r.chunk_id}",
            excerpt=r.text[:1500], as_of=r.effective_from or as_of,
            classification="observado",
        )
        comevidencia.append(RetrievedChunk(**{**r.__dict__, "evidence_id": eid}))
    return comevidencia


def list_documents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM documents ORDER BY institution, title").fetchall())


def document_stats(conn: sqlite3.Connection) -> dict[str, int]:
    docs = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
    chunks = conn.execute("SELECT COUNT(*) AS n FROM document_chunks").fetchone()["n"]
    return {"documents": docs, "chunks": chunks}


__all__ = [
    "CHUNK_CHARS", "NOT_CONFIRMED", "RetrievedChunk", "add_document", "chunk_page",
    "document_stats", "list_documents", "sanitize", "search", "search_with_evidence",
]
