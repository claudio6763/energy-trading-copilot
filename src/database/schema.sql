-- Energy Trading Copilot — schema do MVP (SQLite puro, stdlib).
-- Toda tabela de dominio carrega: fonte, unidade, data-base, classificacao e
-- evidence_id. Sem isso um numero nao existe para o sistema.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- catalogo
CREATE TABLE IF NOT EXISTS sources (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL UNIQUE,
    institution       TEXT,
    url               TEXT,
    source_kind       TEXT NOT NULL,          -- OFICIAL|BOLETIM|MODELO|COMERCIAL|MANUAL|DEMO
    integration_status TEXT NOT NULL,         -- LIVE_VALIDATED|MANUAL_IMPORT|LOCAL_SNAPSHOT|DEMO|NOT_CONFIGURED|ERROR
    license_note      TEXT,
    authorized        INTEGER NOT NULL DEFAULT 1,
    update_frequency  TEXT,
    last_success_at   TEXT,
    notes             TEXT,
    created_at        TEXT NOT NULL,
    CHECK (integration_status IN
        ('LIVE_VALIDATED','MANUAL_IMPORT','LOCAL_SNAPSHOT','DEMO','NOT_CONFIGURED','ERROR'))
);

-- ---------------------------------------------------------------- evidencia
-- Peca central: nenhum fato existe sem uma linha aqui.
CREATE TABLE IF NOT EXISTS evidence (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,              -- OBSERVACAO|CURVA|DOCUMENTO|CALCULO|MANUAL
    source_id     TEXT REFERENCES sources(id),
    source_name   TEXT NOT NULL,
    locator       TEXT,                       -- doc#pagina, metric@data, run_id
    excerpt       TEXT NOT NULL,
    value_numeric TEXT,                       -- Decimal como texto: sem float em dinheiro
    unit          TEXT,
    as_of         TEXT NOT NULL,              -- data-base (YYYY-MM-DD)
    classification TEXT NOT NULL,             -- observado|projetado|negociado|indicativo|proxy|manual|demonstracao
    content_hash  TEXT,
    ingested_at   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    CHECK (classification IN
        ('observado','projetado','negociado','indicativo','proxy','manual','demonstracao'))
);
CREATE INDEX IF NOT EXISTS ix_evidence_asof ON evidence(as_of);

-- ------------------------------------------------------------ observacoes
CREATE TABLE IF NOT EXISTS market_observations (
    id             TEXT PRIMARY KEY,
    metric         TEXT NOT NULL,
    value          TEXT NOT NULL,
    unit           TEXT NOT NULL,
    submarket      TEXT,
    period_start   TEXT,
    period_end     TEXT,
    ref_date       TEXT NOT NULL,             -- a que o dado se refere
    as_of          TEXT NOT NULL,             -- quando se soube (bitemporal)
    source_id      TEXT REFERENCES sources(id),
    classification TEXT NOT NULL,
    model_run      TEXT NOT NULL DEFAULT '',  -- divergencia entre rodadas preservada
    ingested_at    TEXT NOT NULL,
    evidence_id    TEXT NOT NULL REFERENCES evidence(id),
    created_at     TEXT NOT NULL,
    UNIQUE (metric, ref_date, as_of, model_run)
);
CREATE INDEX IF NOT EXISTS ix_obs_metric ON market_observations(metric, ref_date, as_of);

-- ---------------------------------------------------------- curva forward
CREATE TABLE IF NOT EXISTS forward_curves (
    id             TEXT PRIMARY KEY,
    curve_name     TEXT NOT NULL,
    submarket      TEXT NOT NULL,
    energy_source  TEXT NOT NULL DEFAULT 'CONVENCIONAL',  -- CONVENCIONAL|I0|I5|I100
    quote_type     TEXT NOT NULL,             -- MID|BID|ASK|INDICATIVO|PROXY
    origin         TEXT NOT NULL,             -- NEGOCIADA|PROXY_SPOT|PROXY_MODELO|INTERNA
    proxy_of       TEXT,                      -- obrigatorio quando origin=PROXY_SPOT
    as_of          TEXT NOT NULL,
    source_id      TEXT REFERENCES sources(id),
    classification TEXT NOT NULL,
    evidence_id    TEXT NOT NULL REFERENCES evidence(id),
    notes          TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE (curve_name, submarket, energy_source, quote_type, as_of),
    CHECK (origin IN ('NEGOCIADA','PROXY_SPOT','PROXY_MODELO','INTERNA')),
    -- PLD/CMO nunca entram como curva negociada sem declarar o substituido.
    CHECK (origin <> 'PROXY_SPOT' OR proxy_of IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS forward_curve_points (
    id             TEXT PRIMARY KEY,
    curve_id       TEXT NOT NULL REFERENCES forward_curves(id) ON DELETE CASCADE,
    tenor          TEXT NOT NULL,
    delivery_start TEXT NOT NULL,
    delivery_end   TEXT NOT NULL,
    price          TEXT NOT NULL,
    unit           TEXT NOT NULL DEFAULT 'R$/MWh',
    evidence_id    TEXT NOT NULL REFERENCES evidence(id),
    created_at     TEXT NOT NULL,
    UNIQUE (curve_id, tenor),
    CHECK (delivery_end >= delivery_start)
);

-- --------------------------------------------------------------- acervo RAG
CREATE TABLE IF NOT EXISTS documents (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    institution    TEXT NOT NULL,             -- CCEE|ONS|ANEEL|ANA|EPE|OUTRO
    doc_type       TEXT NOT NULL,
    version        TEXT,
    published_at   TEXT,
    effective_from TEXT,
    effective_to   TEXT,
    file_path      TEXT,
    url            TEXT,
    file_hash      TEXT,
    page_count     INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id           TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page         INTEGER NOT NULL,
    chunk_index  INTEGER NOT NULL,
    text         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE (document_id, page, chunk_index)
);

-- Indice lexical FTS5: SQLite-only, ver schema_sqlite_only.sql. Postgres nao
-- tem equivalente nativo — RAG por busca lexical fica indisponivel la por ora
-- (nao faz parte do que a defesa verifica; ver DECISOES.md).

-- ---------------------------------------------------------------- teses
CREATE TABLE IF NOT EXISTS theses (
    id                TEXT PRIMARY KEY,
    version           INTEGER NOT NULL DEFAULT 1,
    parent_id         TEXT REFERENCES theses(id),
    title             TEXT NOT NULL,
    summary           TEXT NOT NULL,          -- ate 5 linhas (validado em codigo)
    direction         TEXT NOT NULL,          -- COMPRAR|VENDER|MANTER|NAO_OPERAR
    product           TEXT NOT NULL,
    energy_source     TEXT NOT NULL,
    submarket         TEXT NOT NULL,
    delivery_start    TEXT,
    delivery_end      TEXT,
    volume_mwm        TEXT,
    price_ref         TEXT,
    price_ref_date    TEXT,
    horizon_days      INTEGER,
    review_date       TEXT,
    expected_low      TEXT,                   -- intervalo, nunca numero unico
    expected_mid      TEXT,
    expected_high     TEXT,
    exit_condition    TEXT,
    invalidation      TEXT,
    owner             TEXT NOT NULL,
    as_of             TEXT NOT NULL,
    status            TEXT NOT NULL,          -- RASCUNHO|EM_DEBATE|APROVADA|ATIVA|EM_REVISAO|ENCERRADA|INVALIDADA
    change_reason     TEXT,
    -- Desafiar (PROMPT_FINAL_COPILOTO.md Parte 3) — uma chamada de IA, bloqueante.
    -- Instalacoes existentes ganham essas colunas via ALTER idempotente em
    -- connection.py (fresh installs ja nascem com elas aqui).
    trader_response          TEXT,
    desafio_premissa_fragil  TEXT,
    desafio_cenario_quebra   TEXT,
    desafio_contra_argumento TEXT,
    desafio_vies_confirmacao TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    CHECK (direction IN ('COMPRAR','VENDER','MANTER','NAO_OPERAR')),
    CHECK (status IN ('RASCUNHO','EM_DEBATE','APROVADA','ATIVA','EM_REVISAO','ENCERRADA','INVALIDADA'))
);

CREATE TABLE IF NOT EXISTS thesis_assumptions (
    id          TEXT PRIMARY KEY,
    thesis_id   TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    statement   TEXT NOT NULL,
    metric      TEXT,                          -- sem metrica: nao e vigiavel
    expected    TEXT,
    tol_low     TEXT,
    tol_high    TEXT,
    unit        TEXT,
    criticality TEXT NOT NULL DEFAULT 'MEDIA',
    status      TEXT NOT NULL DEFAULT 'VALIDA', -- VALIDA|SOB_TENSAO|VIOLADA|NAO_MONITORAVEL
    evidence_id TEXT REFERENCES evidence(id),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thesis_risks (
    id          TEXT PRIMARY KEY,
    thesis_id   TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    category    TEXT NOT NULL,
    description TEXT NOT NULL,
    severity    TEXT NOT NULL,
    mitigation  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thesis_sources (
    id          TEXT PRIMARY KEY,
    thesis_id   TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    reference   TEXT,
    evidence_id TEXT REFERENCES evidence(id),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id             TEXT PRIMARY KEY,
    thesis_id      TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    side           TEXT NOT NULL,              -- COMPRADO|VENDIDO
    instrument     TEXT NOT NULL,
    submarket      TEXT NOT NULL,
    energy_source  TEXT NOT NULL DEFAULT 'CONVENCIONAL',
    volume_mwm     TEXT NOT NULL,
    price_entry    TEXT NOT NULL,
    delivery_start TEXT NOT NULL,
    delivery_end   TEXT NOT NULL,
    hours          INTEGER NOT NULL,
    volume_mwh     TEXT NOT NULL,
    notional       TEXT,
    metric_key     TEXT NOT NULL,              -- curva usada para marcar
    evidence_id    TEXT NOT NULL REFERENCES evidence(id),
    created_at     TEXT NOT NULL,
    CHECK (side IN ('COMPRADO','VENDIDO'))
);

-- ------------------------------------------------------------------ risco
CREATE TABLE IF NOT EXISTS risk_limits (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    limit_value   TEXT NOT NULL,
    unit          TEXT NOT NULL,
    confidence    TEXT,
    horizon_days  INTEGER,
    notes         TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_results (
    id             TEXT PRIMARY KEY,
    thesis_id      TEXT REFERENCES theses(id) ON DELETE CASCADE,
    method         TEXT NOT NULL,              -- var_parametric|var_ewma|var_historical|var_portfolio|pnl
    var_market     TEXT,
    addons_total   TEXT,
    var_total      TEXT,
    limit_value    TEXT,
    utilization    TEXT,
    within_limit   INTEGER,
    expected_shortfall TEXT,
    confidence     TEXT,
    horizon_days   INTEGER,
    sample_size    INTEGER,
    sigma_daily    TEXT,
    inputs_json    TEXT NOT NULL,
    outputs_json   TEXT NOT NULL,
    methodology    TEXT NOT NULL,
    as_of          TEXT NOT NULL,
    evidence_id    TEXT NOT NULL REFERENCES evidence(id),
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_results (
    id            TEXT PRIMARY KEY,
    thesis_id     TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    scenario      TEXT NOT NULL,               -- SECO|BASE|UMIDO|EXTREMO
    is_stress     INTEGER NOT NULL DEFAULT 0,
    probability   TEXT,
    shocked_price TEXT,
    pnl           TEXT NOT NULL,
    var_impact    TEXT,
    thesis_delta  TEXT,
    as_of         TEXT NOT NULL,
    evidence_id   TEXT NOT NULL REFERENCES evidence(id),
    created_at    TEXT NOT NULL,
    UNIQUE (thesis_id, scenario, as_of)
);

-- ----------------------------------------------------------------- debate
CREATE TABLE IF NOT EXISTS debate_sessions (
    id             TEXT PRIMARY KEY,
    thesis_id      TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    thesis_version INTEGER NOT NULL DEFAULT 1,
    round_number   INTEGER NOT NULL DEFAULT 1,
    mode           TEXT NOT NULL,              -- REAL|DEMO
    model          TEXT,
    verdict        TEXT,                       -- COMPRAR|VENDER|MANTER|REDUZIR|REESTRUTURAR|NAO_OPERAR_DADOS_INSUFICIENTES|BLOQUEADA_POR_RISCO
    counter_thesis TEXT,
    weakest_assumption TEXT,
    biases         TEXT,
    trader_reply   TEXT,
    rationale      TEXT,
    llm_calls      INTEGER NOT NULL DEFAULT 0,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS debate_turns (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES debate_sessions(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    stage        TEXT NOT NULL,                -- TESE|CONTESTACAO|VERIFICACAO|VEREDITO|REPLICA
    agent        TEXT NOT NULL,
    content      TEXT NOT NULL,
    payload_json TEXT,
    evidence_ids TEXT,
    verifier_status TEXT,
    model        TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE (session_id, seq)
);

-- --------------------------------------------------------- gatilhos/alertas
CREATE TABLE IF NOT EXISTS triggers (
    id          TEXT PRIMARY KEY,
    thesis_id   TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    rule_type   TEXT NOT NULL,                 -- SAIDA|INVALIDACAO|ALERTA
    metric      TEXT NOT NULL,
    operator    TEXT NOT NULL,                 -- >|>=|<|<=|delta_pct
    threshold   TEXT NOT NULL,
    unit        TEXT NOT NULL,
    "window"    TEXT NOT NULL DEFAULT 'spot',
    severity    TEXT NOT NULL DEFAULT 'ATENCAO',
    active      INTEGER NOT NULL DEFAULT 1,
    description TEXT,
    created_at  TEXT NOT NULL,
    CHECK (operator IN ('>','>=','<','<=','delta_pct'))
);

CREATE TABLE IF NOT EXISTS watchdog_runs (
    id            TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    as_of         TEXT NOT NULL,
    status        TEXT NOT NULL,               -- OK|PARCIAL|FALHA
    theses_checked INTEGER NOT NULL DEFAULT 0,
    triggers_evaluated INTEGER NOT NULL DEFAULT 0,
    alerts_raised INTEGER NOT NULL DEFAULT 0,
    stale_sources TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id             TEXT PRIMARY KEY,
    run_id         TEXT REFERENCES watchdog_runs(id),
    thesis_id      TEXT REFERENCES theses(id) ON DELETE CASCADE,
    trigger_id     TEXT REFERENCES triggers(id),
    assumption_id  TEXT REFERENCES thesis_assumptions(id),
    severity       TEXT NOT NULL,              -- INFO|ATENCAO|CRITICO
    kind           TEXT NOT NULL,
    message        TEXT NOT NULL,
    explanation    TEXT,
    observed       TEXT,
    expected       TEXT,
    unit           TEXT,
    dedup_key      TEXT,
    occurrences    INTEGER NOT NULL DEFAULT 1,
    as_of          TEXT NOT NULL,
    evidence_id    TEXT NOT NULL REFERENCES evidence(id),
    acknowledged_at TEXT,
    acknowledged_by TEXT,
    decision       TEXT,
    created_at     TEXT NOT NULL,
    CHECK (severity IN ('INFO','ATENCAO','CRITICO'))
);
CREATE INDEX IF NOT EXISTS ix_alerts_open ON alerts(thesis_id, acknowledged_at);

-- --------------------------------------------------------------- auditoria
CREATE TABLE IF NOT EXISTS audit_log (
    id           TEXT PRIMARY KEY,
    actor        TEXT NOT NULL,
    actor_type   TEXT NOT NULL,                -- HUMANO|AGENTE|SISTEMA
    action       TEXT NOT NULL,
    agent        TEXT,
    tool         TEXT,
    entity       TEXT NOT NULL,
    entity_id    TEXT,
    input_json   TEXT,
    output_json  TEXT,
    evidence_ids TEXT,
    model        TEXT,
    as_of        TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_log(entity, entity_id);

-- Append-only (audit_log_no_update/audit_log_no_delete): SQLite-only, ver
-- schema_sqlite_only.sql — sintaxe de trigger do SQLite nao roda em Postgres.

-- --------------------------------------------------------------- ingestao
CREATE TABLE IF NOT EXISTS ingest_snapshots (
    id            TEXT PRIMARY KEY,
    adapter       TEXT NOT NULL,
    source_name   TEXT NOT NULL,
    status        TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    storage_uri   TEXT,
    payload_hash  TEXT,
    byte_size     INTEGER,
    rows_written  INTEGER NOT NULL DEFAULT 0,
    reason        TEXT,
    fetched_at    TEXT,
    created_at    TEXT NOT NULL
);

-- --------------------------------------------------------- book do motor
-- Aditivo, nunca toca em `positions`: o book do motor e posicao PROPOSTA;
-- `positions` e posicao REAL. Um `thesis_book` por avaliar() salvo. A
-- existencia da linha aqui e o proprio fato de que a tese usa o VaR do motor
-- — nao existe coluna de discriminador em `theses` (P8/invariante 5:
-- risk_service.py nunca e chamado para tese com thesis_book).
CREATE TABLE IF NOT EXISTS thesis_book (
    id                      TEXT PRIMARY KEY,
    thesis_id               TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    snapshot_hash           TEXT NOT NULL,
    ref_mercado_json        TEXT NOT NULL,      -- {"2026-08": 142.0, ...} — PREMISSA, leitura de mesa
    modo_sinal              TEXT NOT NULL,
    premio_nivel_rs_mwh     TEXT,
    k_premio                TEXT,
    var_total               TEXT NOT NULL,
    es_total                TEXT,
    var_limit               TEXT NOT NULL,
    consumo_limite          TEXT NOT NULL,
    -- tamanho do book: SO estes dois agregados. Nunca "volume"/"tamanho".
    energia_mwh             TEXT NOT NULL,
    notional_brl            TEXT NOT NULL,
    preco_entrada_medio_mwh TEXT,
    mwmed_equivalente_flat  TEXT,               -- KPI opcional "MWm eq.", nunca "volume"
    soma_mwm_pernas         TEXT,               -- so informativo; nunca vai pra tela como tamanho
    pnl_convergencia        TEXT,
    pnl_entrega_esperado    TEXT,
    pnl_entrega_seco        TEXT,
    pnl_entrega_umido       TEXT,
    vpl                     TEXT,
    -- Rotulo de natureza por campo agregado, gravado no INSERT — nunca
    -- recalculado depois (um deploy novo nao pode reetiquetar registro velho).
    natures_json            TEXT NOT NULL,
    evidence_id             TEXT NOT NULL REFERENCES evidence(id),
    created_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_thesis_book_thesis ON thesis_book(thesis_id);

CREATE TABLE IF NOT EXISTS thesis_book_legs (
    id                      TEXT PRIMARY KEY,
    book_id                 TEXT NOT NULL REFERENCES thesis_book(id) ON DELETE CASCADE,
    mes_ref                 TEXT NOT NULL,      -- "2026-08-01"
    lado                    TEXT NOT NULL,      -- COMPRADO|VENDIDO
    mwmed                   TEXT NOT NULL,
    mwmed_nature            TEXT NOT NULL,
    horas                   INTEGER NOT NULL,
    horas_nature            TEXT NOT NULL,
    mwh                     TEXT NOT NULL,
    mwh_nature              TEXT NOT NULL,
    preco_entrada           TEXT NOT NULL,
    preco_entrada_nature    TEXT NOT NULL,
    preco_entrada_origem    TEXT NOT NULL,      -- "leitura de mesa" | "informado na defesa"
    snapshot_hash           TEXT NOT NULL,      -- denormalizado do book, de proposito
    created_at              TEXT NOT NULL,
    CHECK (lado IN ('COMPRADO','VENDIDO'))
);
CREATE INDEX IF NOT EXISTS ix_thesis_book_legs_book ON thesis_book_legs(book_id);
