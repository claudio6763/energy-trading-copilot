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


def _split_statements(script: str) -> list[str]:
    """Split ingenuo por `;` de fim de linha — schema.sql nao tem `;` dentro
    de string literal nem em corpo de trigger no trecho que roda aqui."""
    out = []
    for stmt in script.split(";"):
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


def connect_postgres(database_url: str) -> PgConnectionShim:
    import psycopg
    from psycopg.rows import dict_row

    # autocommit=True para casar com o isolation_level=None do sqlite3 usado
    # em connection.py: cada .execute() fora de um BEGIN explicito ja vale.
    # `session()` continua funcionando porque BEGIN/COMMIT/ROLLBACK explicitos
    # abrem/fecham bloco de transacao normalmente em cima de autocommit.
    conn = psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
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
