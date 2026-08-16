-- Complemento SQLite-only de schema.sql. Nunca roda contra Postgres — nem
-- FTS5 nem a sintaxe de trigger do SQLite existem la. Ver connection.py:
-- init_db() so executa este arquivo quando o dialeto e sqlite.

-- Indice lexical FTS5 (stdlib). Sem vector db: busca lexical resolve.
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    text, chunk_id UNINDEXED, document_id UNINDEXED, tokenize='unicode61'
);

-- Append-only: a trilha nao pode ser reescrita nem pela aplicacao.
CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log e append-only'); END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log e append-only'); END;
