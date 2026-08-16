# DATA_CONTRACT — Energy Trading Copilot

Versão 1.0 · Sprint 0. Contrato de dados: entidades, proveniência, controle de data-base, licenciamento e separação demo/real. Nenhuma implementação nesta sprint.

---

## 1. Regras que valem para toda tabela

| Regra | Descrição |
|---|---|
| C1 | Toda tabela de domínio tem `id` (ULID string, PK), `created_at` (timestamptz UTC), `dataset_kind` (`DEMO` \| `REAL`). |
| C2 | Toda tabela que carrega informação de mercado ou de norma tem `as_of` (date, America/Sao_Paulo) — a data-base do dado, distinta de `created_at`. |
| C3 | Toda afirmação factual persistida referencia `evidence_id`. Coluna `NOT NULL` onde o campo é factual. |
| C4 | Dinheiro: `Numeric(18,2)`. Energia: `Numeric(18,3)` MWh. Preço: `Numeric(12,2)` R$/MWh. Percentual: `Numeric(9,6)` em fração. **Nunca `float`.** |
| C5 | Nenhuma consulta agrega linhas com `dataset_kind` diferente. Imposto por predicado obrigatório no Agente de Dados e por *check* nas views. |
| C6 | Nenhuma consulta retorna linha com `as_of >` o `as_of` do contexto (proteção contra look-ahead). |
| C7 | `audit_log` é append-only; o papel da aplicação não tem `UPDATE`/`DELETE` nela. |
| C8 | Enums são persistidos como texto com *check constraint*, não como enum nativo (facilita o fallback SQLite). |

---

## 2. Entidades

### 2.1 `evidence` — a peça central

Nenhum fato existe no sistema sem uma linha aqui.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | ULID | É o `evidence_id`. |
| `source_type` | enum | `RAG_DOC` · `SQL_QUERY` · `QUANT_RUN` · `HUMAN_INPUT` · `EXTERNAL_FILE` |
| `source_id` | ULID/text | FK lógica para `source`, `sql_execution` ou `quant_run`. |
| `locator` | text | Onde exatamente: `doc_id#chunk_id#page` · `sql_hash` · `run_id` · `arquivo#célula`. |
| `excerpt` | text | Trecho literal citado ou representação do valor. Obrigatório. |
| `value_numeric` | Numeric(28,8) | Preenchido quando a evidência é um número. |
| `unit` | text | `R$` · `MWh` · `R$/MWh` · `%` · `m³/s` · `MWmed`. |
| `content_hash` | text | SHA-256 do conteúdo citado. Detecta mudança silenciosa da fonte. |
| `as_of` | date | Data-base do dado. |
| `retrieved_at` | timestamptz | Quando foi obtido. |
| `license_class` | enum | ver §4. |
| `confidence` | enum | `HIGH` · `MEDIUM` · `LOW` — qualidade da fonte, declarada, não inferida por LLM. |
| `dataset_kind` | enum | `DEMO` \| `REAL`. |

### 2.2 `source` — catálogo de fontes

`id` · `name` (ex.: ONS, CCEE, ANEEL, INMET, NOAA/GFS) · `publisher` · `url` · `source_kind` (`OFICIAL` · `BOLETIM` · `MODELO_METEO` · `PROVEDOR_COMERCIAL` · `INTERNO` · `MANUAL`) · `license_class` · `authorized` (bool) · `authorization_ref` (text) · `update_frequency` · `notes`.

**Regra de ingestão:** `license_class ∈ {LICENSED_BLOCKED, CONFIDENTIAL_EXTERNAL}` ou `authorized = false` ⇒ ingestão **rejeitada** com log. Nada é ingerido "e filtrado depois".

### 2.3 `thesis` — a tese

`id` · `version` (int) · `parent_id` · `title` · `summary` (≤ 5 linhas) · `direction` (`COMPRA` \| `VENDA` \| `SPREAD` \| `ESTRUTURADO`) · `product` · `submarket` (`SE/CO` · `S` · `NE` · `N`) · `delivery_start` · `delivery_end` · `horizon_days` · `review_date` · `status` (`RASCUNHO` · `EM_DEBATE` · `APROVADA` · `ATIVA` · `EM_REVISÃO` · `ENCERRADA` · `INVALIDADA`) · `expected_pnl_p5` · `expected_pnl_p50` · `expected_pnl_p95` (Numeric 18,2) · `var_consumed` · `var_limit` (default 50.000.000,00) · `as_of` · `author` · `dataset_kind`.

Imutável após `APROVADA`: alteração cria nova `version` com `change_reason` e diff em `audit_log` (RF-09).

### 2.4 `assumption` — premissa

`id` · `thesis_id` · `kind` (`HIDROLÓGICA` · `PREÇO` · `CARGA` · `OFERTA` · `REGULATÓRIA` · `LIQUIDEZ` · `OUTRA`) · `statement` · `metric_key` (chave da série que a mede) · `expected_value` · `tolerance_low` · `tolerance_high` · `unit` · `evidence_id` (NOT NULL) · `criticality` (`ALTA` · `MÉDIA` · `BAIXA`) · `status` (`VÁLIDA` · `SOB_TENSÃO` · `VIOLADA`) · `last_checked_at` · `as_of`.

`metric_key` é o que torna a vigilância automática possível: sem série mensurável associada, a premissa é aceita mas marcada `NÃO_MONITORÁVEL` e isso aparece na UI.

### 2.5 `position` — dimensionamento

`id` · `thesis_id` · `instrument` (`PPA` · `FORWARD_CONV` · `FORWARD_I5` · `OPÇÃO` · `SWAP` · `ESTRUTURADO`) · `submarket` · `volume_mwh` · `price_ref` · `delivery_start` · `delivery_end` · `side` (`LONG` \| `SHORT`) · `notional` · `counterparty` (opcional, sem PII) · `var_contribution` · `evidence_id` · `as_of`.

### 2.6 `trigger_rule` — gatilhos e condições de invalidação

`id` · `thesis_id` · `rule_type` (`SAÍDA` \| `INVALIDAÇÃO` \| `ALERTA`) · `metric_key` · `operator` (`>` `>=` `<` `<=` `cross_up` `cross_down` `delta_pct`) · `threshold` (Numeric) · `unit` · `window` (ex.: `7d`, `1d`, `spot`) · `severity` (`INFO` · `ATENÇÃO` · `CRÍTICO`) · `active` · `description`.

**Não existe gatilho em texto livre.** Um gatilho que não pode ser avaliado por máquina não é gatilho.

### 2.7 `risk_item`

`id` · `thesis_id` · `category` (`MERCADO` · `HIDROLÓGICO` · `REGULATÓRIO` · `CRÉDITO` · `LIQUIDEZ` · `OPERACIONAL` · `BASE`) · `description` · `severity` · `likelihood` · `mitigation` · `evidence_id` (nullable para risco qualitativo, com `claim_type=OPINIÃO`).

### 2.8 `market_series` e `market_observation` — os números

`market_series`: `id` · `metric_key` (ex.: `ear_sudeste_pct`, `pld_se_semanal`, `ena_sin_mlt_pct`, `carga_sin_mwmed`, `fwd_conv_se_2027`) · `description` · `unit` · `frequency` · `source_id` · `license_class` · `dataset_kind`.

`market_observation`: `id` · `series_id` · `ref_date` (a data a que o valor se refere) · `as_of` (a data-base da publicação — permite reconstruir o que se sabia em 14/08) · `value` (Numeric 28,8) · `revision` (int) · `evidence_id` · `dataset_kind`.

O par (`ref_date`, `as_of`) é o que dá **bitemporalidade**: sem ele não é possível responder "o que sabíamos na data-corte" nem evitar look-ahead.

### 2.9 `quant_run` — execuções do motor

`id` (= `run_id`) · `function` (`var_historical` · `var_parametric` · `var_mc` · `pnl` · `scenario` · `optimize` · `pricing`) · `inputs_json` · `inputs_hash` · `outputs_json` · `seed` · `code_version` · `as_of` · `duration_ms` · `dataset_kind`.

Reexecutar com o mesmo `inputs_hash`, `seed` e `code_version` deve produzir `outputs_json` idêntico (RF-56).

### 2.10 `scenario` e `scenario_result`

`scenario`: `id` · `name` (ex.: `Base`, `Seco`, `Úmido`) · `kind` (`HIDROLÓGICO` · `PREÇO` · `CARGA` · `COMBINADO`) · `definition_json` (choques declarados) · `probability_weight` · `source_evidence_id`.

`scenario_result`: `id` · `thesis_id` · `scenario_id` · `quant_run_id` · `pnl_p5` · `pnl_p50` · `pnl_p95` · `var_impact` · `thesis_delta` (o que muda na tese) · `as_of`.

Mínimo obrigatório: **dois cenários hidrológicos distintos** por tese (RF-53).

### 2.11 `debate_session` e `debate_turn`

`debate_session`: `id` · `thesis_id` · `thesis_version` · `run_id` · `verdict` (`APROVÁVEL` · `BLOQUEADA` · `INCONCLUSIVA`) · `weakest_assumption_id` · `breaking_scenario_id` · `confirmation_bias_score` (Numeric) · `bias_rationale` · `trader_response` · `cost_usd` · `started_at` · `ended_at`.

`debate_turn`: `id` · `session_id` · `agent` (`TRADER` · `RISCO` · `REGULATÓRIO` · `DADOS_SQL` · `INTELIGÊNCIA_MERCADO` · `ORQUESTRADOR`) · `role` (`DEFESA` \| `ATAQUE` \| `CONSULTA`) · `content` · `tools_called_json` · `evidence_ids[]` · `verifier_status` · `model` · `prompt_version` · `seq`.

### 2.12 `claim` — saída do Claim Verifier

`id` · `turn_id` (ou `alert_id`) · `claim_text` · `claim_type` (`NUMÉRICA` · `FACTUAL` · `OPINIÃO`) · `value_numeric` · `unit` · `evidence_id` (nullable) · `status` (`VERIFIED` · `UNVERIFIED` · `CONTRADICTED` · `BLOCKED`) · `tolerance_applied` · `reason`.

Regra: existe `claim` com status `CONTRADICTED` ou `BLOCKED` vinculada a uma versão de tese ⇒ transição para `APROVADA` bloqueada (RF-51).

### 2.13 `watchdog_run` e `alert`

`watchdog_run`: `id` · `started_at` · `ended_at` · `as_of` · `theses_checked` · `assumptions_checked` · `rules_evaluated` · `sources_ok[]` · `sources_failed[]` · `status` (`OK` · `PARCIAL` · `FALHA`).

`alert`: `id` · `watchdog_run_id` · `thesis_id` · `assumption_id` (nullable) · `trigger_rule_id` (nullable) · `severity` (`INFO` · `ATENÇÃO` · `CRÍTICO`) · `alert_kind` (`PREMISSA_VIOLADA` · `GATILHO_DISPARADO` · `INVALIDAÇÃO` · `VAR_LIMITE` · `MUDANÇA_REGULATÓRIA` · `COBERTURA_DADOS`) · `message` · `observed_value` · `expected_value` · `delta` · `evidence_id` (NOT NULL) · `as_of` · `acknowledged_by` · `acknowledged_at` · `decision` (`MANTER` · `AJUSTAR` · `ENCERRAR`) · `decision_rationale`.

`alert_kind = COBERTURA_DADOS` é o que garante que falha de fonte não vire silêncio (RF-36).

### 2.14 `document` e `document_chunk` — acervo RAG

`document`: `id` · `source_id` · `title` · `doc_type` (`RESOLUÇÃO` · `REGRA_COMERCIALIZAÇÃO` · `PROCEDIMENTO_REDE` · `BOLETIM` · `RELATÓRIO` · `NOTA_MERCADO`) · `publisher` · `published_at` · `effective_from` · `effective_to` · `url` · `file_hash` · `license_class` · `authorized` · `as_of` · `dataset_kind`.

`document_chunk`: `id` · `document_id` · `chunk_index` · `text` · `page` · `section` · `token_count` · `embedding` (`vector(1536)`, pgvector) · `tsv` (índice lexical para BM25/híbrido).

Recuperação filtra por `effective_from <= as_of` e `license_class` autorizada.

### 2.15 `audit_log`

`id` · `actor_type` (`HUMANO` \| `AGENTE` \| `SISTEMA`) · `actor` · `agent_version` · `action` · `entity` · `entity_id` · `before_json` · `after_json` · `run_id` · `model` · `prompt_version` · `evidence_ids[]` · `as_of` · `created_at`.

---

## 3. Controle de data-base (`as_of`)

1. Toda sessão de trabalho tem um `as_of` de contexto. Padrão da Entrega 2: **14/08** (data-corte do case).
2. Toda consulta SQL recebe `WHERE as_of <= :context_as_of` injetado pelo Agente de Dados — não por confiança no SQL gerado.
3. Toda execução do motor quant grava o `as_of` das entradas.
4. Recuperação RAG filtra por vigência ≤ `as_of`.
5. O Watchdog roda com `as_of` **corrente** e compara contra a tese registrada com `as_of` da data-corte — é exatamente essa diferença que produz o alerta.
6. A UI exibe o `as_of` ativo de forma permanente. Nenhum número aparece sem sua data-base.

---

## 4. Classificação de licença

| `license_class` | Significado | Ingestão |
|---|---|---|
| `PUBLIC_OPEN` | Dado público aberto (ONS, CCEE público, ANEEL, INMET, NOAA/GFS). | Permitida. |
| `PUBLIC_ATTRIB` | Público com exigência de atribuição. | Permitida, atribuição obrigatória na UI. |
| `LICENSED_AUTHORIZED` | Provedor comercial **com** autorização registrada em `source.authorization_ref`. | Permitida. |
| `LICENSED_BLOCKED` | Provedor comercial sem autorização (curvas forward comerciais, terminais). | **Rejeitada.** |
| `CONFIDENTIAL_INTERNAL` | Dado interno da companhia. | Permitida, nunca exportada nem exibida em `DEMO`. |
| `CONFIDENTIAL_EXTERNAL` | Confidencial de terceiro. | **Rejeitada.** |

O conteúdo do próprio case é `CONFIDENTIAL_EXTERNAL`: não vai para repositório público nem para o acervo RAG.

---

## 5. Separação DEMO / REAL

- `dataset_kind` obrigatório em toda linha de domínio.
- Chave alternada no topo da UI; o rótulo do dataset ativo é persistente e visível em todo gráfico e toda tabela.
- Consultas do Agente de Dados injetam `dataset_kind = :context_kind`. Agregação cruzada é impossível por construção.
- Dado `DEMO` é sintético e assim rotulado; nunca é derivado de dado real por transformação, para não gerar confusão de proveniência.
- A tese da Entrega 2 vive em `REAL`. Dados de demonstração para desenvolvimento e testes vivem em `DEMO`.

---

## 6. Séries mínimas para o Watchdog funcionar

`metric_key` inicial a instrumentar (todas de fontes públicas, cada uma com ficha em `source`):

- Hidrologia: energia armazenada por subsistema, ENA em % da MLT, vazão prevista.
- Preço: PLD por submercado, referência de preço forward (proxy público declarado enquanto D-02 não for respondida).
- Sistema: carga verificada e prevista, geração por fonte, restrição de operação.
- Meteorologia: precipitação prevista por rodada e por ensemble, com **divergência entre modelos preservada** — nunca reduzida a média antes do armazenamento.
- Regulatório: publicações normativas com data de vigência.

Nenhum valor destas séries é preenchido nesta sprint. A instrumentação ocorre no Sprint 2, e toda observação carrega `evidence_id`.

---

## 7. Migrações

Toda mudança de schema é uma revisão Alembic com `upgrade` e `downgrade`. Sem `create_all` fora de teste. O SQLite de fallback usa o mesmo grafo de migrações, exceto a coluna `vector` (substituída por `blob` inativa e busca lexical).
