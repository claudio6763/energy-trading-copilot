"""Adaptador: uma conexao `psycopg` (Postgres) se comportando como
`sqlite3.Connection` o bastante para todo o codigo existente (`repositories.py`,
`thesis_service.py`, `risk_service.py`, `watchdog_service.py`, `app.py`)
funcionar sem alteracao — `conn.execute(sql, params)` com `?` posicional,
linha acessivel por nome de coluna, `conn.commit()`.

Por que um adaptador e nao reescrever tudo para `text(":nome")`: o schema.sql
existente e SQL padrao (funciona em SQLite e Postgres quase sem mudanca — as
duas excecoes, FTS5 e a sintaxe de trigger do SQLite, ficam isoladas em
`schema_sqlite_only.sql`, nunca executadas contra Postgres). Reescrever ~25
funcoes de `?` para bind nomeado trocaria um problema de infraestrutura por um
risco real de regressao em tudo que ja funciona. Ver DECISOES.md.

Limitacao conhecida e documentada: `INSERT OR REPLACE` (3 ocorrencias, em
`forward_curves`/`forward_curve_points`/`scenario_results`) e sintaxe do
SQLite sem equivalente aqui — nada do fluxo novo (motor_service.py, Registrar,
Desafiar, Vigiar, Mesa) usa essas funcoes, entao isso so importa se alguem
clicar na aba antiga "Dados e fontes -> Curva publica" rodando sobre Postgres.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence


class _PgRow(dict):
    """Dict que tambem aceita indice posicional, como sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class PgCursorShim:
    def __init__(self, real_cursor):
        self._cur = real_cursor

    def fetchone(self):
        row = self._cur.fetchone()
        return _PgRow(row) if row is not None else None

    def fetchall(self):
        return [_PgRow(r) for r in self._cur.fetchall()]

    def __iter__(self):
        for row in self._cur:
            yield _PgRow(row)

    @property
    def lastrowid(self):
        return None  # IDs deste projeto sao ULID gerados em Python, nao autoincrement


def _qmark_to_pyformat(sql: str) -> str:
    """Troca `?` posicional por `%s`. Nao ha literal `?` em string SQL neste
    projeto (checado manualmente nas queries existentes)."""
    return sql.replace("?", "%s")


def _strip_line_comments(script: str) -> str:
    """Remove `-- comentario` ate o fim da linha, ANTES do split por `;`.

    Comentario de schema.sql pode ter `;` no meio do texto em portugues
    ("verifica; ver DECISOES.md") — sem tirar o comentario primeiro, o split
    ingenuo por `;` corta o comentario ao meio e a segunda metade deixa de
    comecar com `--`, quebrando a deteccao de "isto e so comentario".
    Seguro aqui: schema.sql e DDL, sem string literal com `--` dentro.
    """
    linhas = []
    for linha in script.splitlines():
        pos = linha.find("--")
        linhas.append(linha[:pos] if pos != -1 else linha)
    return "\n".join(linhas)


def _split_statements(script: str) -> list[str]:
    """Split por `;` de fim de linha, depois de remover comentarios."""
    sem_comentarios = _strip_line_comments(script)
    out = []
    for stmt in sem_comentarios.split(";"):
        s = stmt.strip()
        if s:
            out.append(s)
    return out


class PgConnectionShim:
    """`sqlite3.Connection`-like sobre uma conexao `psycopg` real."""

    def __init__(self, pg_conn):
        self._conn = pg_conn

    def execute(self, sql: str, params: Sequence[Any] | dict = ()) -> PgCursorShim:
        sql2 = _qmark_to_pyformat(sql)
        cur = self._conn.execute(sql2, tuple(params) if params else None)
        return PgCursorShim(cur)

    def executescript(self, script: str) -> None:
        for stmt in _split_statements(script):
            # remove linhas de comentario `-- ...` antes de checar o tipo do
            # comando: o primeiro "statement" do arquivo e so comentario + PRAGMA.
            sem_comentarios = "\n".join(
                linha for linha in stmt.splitlines() if not linha.strip().startswith("--")
            ).strip()
            if not sem_comentarios:
                continue
            if sem_comentarios.upper().startswith("PRAGMA"):
                # `PRAGMA foreign_keys = ON` e sintaxe do SQLite; FK e sempre
                # obrigatoria no Postgres, sem equivalente a pedir.
                continue
            try:
                self._conn.execute(stmt)
            except Exception as exc:  # pragma: no cover - diagnostico no boot
                raise RuntimeError(f"Falha no DDL (Postgres):\n{stmt}\n\n{exc}") from exc

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def cursor(self):
        return PgCursorShim(self._conn.cursor())


def _normalize_dsn(database_url: str) -> str:
    """psycopg fala libpq puro: `postgresql://...`. Aceita e normaliza a
    notacao de dialeto do SQLAlchemy (`postgresql+psycopg://...`,
    `postgres+psycopg2://...`) removendo o `+driver` — psycopg nao entende
    esse sufixo e erraria a conexao se ele passasse adiante sem tratamento.
    Essa normalizacao mora aqui (codigo), nunca exigida do valor em `.env`.
    """
    import re

    return re.sub(r"^(postgres(?:ql)?)\+\w+://", r"\1://", database_url)


def connect_postgres(database_url: str) -> PgConnectionShim:
    import psycopg
    from psycopg.rows import dict_row

    dsn = _normalize_dsn(database_url)
    # autocommit=True para casar com o isolation_level=None do sqlite3 usado
    # em connection.py: cada .execute() fora de um BEGIN explicito ja vale.
    # `session()` continua funcionando porque BEGIN/COMMIT/ROLLBACK explicitos
    # abrem/fecham bloco de transacao normalmente em cima de autocommit.
    conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
    return PgConnectionShim(conn)


def ensure_theses_extra_columns(conn, *, dialect: str) -> None:
    """Colunas do Desafiar (trader_response, desafio_*) — idempotente.

    `theses` criada por uma instalacao anterior a este schema nao tem essas
    colunas; instalacao nova (CREATE TABLE IF NOT EXISTS ja as inclui) fica
    como no-op. Nunca falha se a coluna ja existir.
    """
    colunas = [
        ("trader_response", "TEXT"),
        ("desafio_premissa_fragil", "TEXT"),
        ("desafio_cenario_quebra", "TEXT"),
        ("desafio_contra_argumento", "TEXT"),
        ("desafio_vies_confirmacao", "TEXT"),
    ]
    if dialect == "postgres":
        for nome, tipo in colunas:
            conn.execute(f"ALTER TABLE theses ADD COLUMN IF NOT EXISTS {nome} {tipo}")
        conn.commit()
        return

    existentes = {row[1] for row in conn.execute("PRAGMA table_info(theses)").fetchall()}
    for nome, tipo in colunas:
        if nome not in existentes:
            conn.execute(f"ALTER TABLE theses ADD COLUMN {nome} {tipo}")


__all__ = ["PgConnectionShim", "connect_postgres", "ensure_theses_extra_columns"]
