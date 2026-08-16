# Arquitetura — Energy Trading Copilot

Aplicação **monolítica local**. Sem microsserviços, sem fila, sem Kubernetes.

## 1. Ideia central

**O LLM decide o que perguntar e o que significa. O banco, o RAG e o Python
decidem qual é o número.** Entre os dois há um portão obrigatório: o Claim Verifier.

```text
              Streamlit (app.py) — 5 áreas
                       |
   Serviços: thesis · debate · risk · watchdog · claim_verifier
                       |
   Agentes: Orquestrador · Trader · Risco · Regulatório · Mercado
            (classes Python; o LLM só redige e interpreta)
                       |
   Dados: SQLite (stdlib) · FTS5 (RAG) · quant (stdlib) · audit append-only
```

## 2. Os cinco agentes

| Agente | Responsabilidade | Não pode |
|---|---|---|
| **Orquestrador** | Conduz as 4 etapas, consolida o veredito, persiste | Calcular métrica, criar fato |
| **Trader** | Estrutura e defende a tese; otimiza retorno ajustado ao risco | Emitir número fora do bloco DADOS |
| **Risco** | Segunda linha independente; ataca a tese; pode bloquear | Ser instruído pelo Trader; calcular "de cabeça" |
| **Regulatório** | Consulta o RAG; toda conclusão com instituição, documento, página, versão, vigência e `evidence_id` | Responder de memória |
| **Mercado** | Consulta dados estruturados com data-base | Criar atualização ausente no banco |

O Agente de Risco tem **veto**: VaR acima do limite produz
`BLOQUEADA_POR_RISCO`, decidido por função pura, não por julgamento do modelo.

## 3. Serviço de Dados

Determinístico, sem LLM. Consulta SQL, importa arquivos, valida unidades,
verifica data-base e freshness, gera `evidence_id` e entrega aos agentes.

## 4. Como impedimos número inventado

1. **Privação** — o agente recebe um bloco `DADOS` em JSON; é a única origem de número permitida.
2. **Ferramentas como única fonte** — números só nascem de SQL, do motor quant ou de entrada humana, e cada origem cria uma linha em `evidence` antes.
3. **Placeholders** — `resolve_placeholders()` falha visivelmente se o marcador não tiver evidência, em vez de gerar texto plausível.
4. **Claim Verifier** — cinco checagens: número órfão, lastro, existência, data-base, recomputação.
5. **Prova visível** — todo número na interface mostra `evidence_id`, fonte e data-base.

Ver `docs/ai_governance.md` para o detalhamento.

## 5. Decisões (ADRs)

| ADR | Decisão | Motivo |
|---|---|---|
| 010 | Motor quantitativo sem NumPy/SciPy | `statistics.NormalDist` dá o quantil normal com precisão de máquina; resultado reproduzível bit a bit |
| 011 | Núcleo em `sqlite3` da stdlib, não SQLAlchemy | Aplicação local, schema estável, zero dependência binária. A camada SQLAlchemy fica em `src/copilot/db/` como caminho de evolução para PostgreSQL/Supabase |
| 012 | RAG lexical com FTS5, sem embeddings | Norma tem jargão fixo e numeração de artigo; busca densa erra referência mais do que acerta sinônimo |
| 013 | Máquina de estados de 4 etapas, sem LangGraph | Quatro etapas sequenciais resolvem e são auditáveis linha a linha |
| 014 | `Decimal` gravado como TEXTO no SQLite | Dinheiro nunca passa por `float` |
| 015 | `audit_log` append-only por trigger de banco | A garantia não pode depender do código da aplicação |

## 6. Fronteira entre IA e determinismo

| Faz IA | Não faz IA |
|---|---|
| Redigir tese e contra-argumento | Calcular VaR, P&L, cenários, add-ons |
| Interpretar norma já recuperada | Decidir se o limite estourou |
| Explicar um alerta | Decidir se o gatilho disparou |
| Sintetizar leitura de mercado | Gerar qualquer número factual |

## 7. Fluxo do debate

`TESE → CONTESTAÇÃO → VERIFICAÇÃO → VEREDITO`, no máximo **4 chamadas ao LLM**.
As etapas de verificação (Regulatório e Mercado) são 100% determinísticas.
O veredito sai de `decide_verdict()`, função pura sobre o resultado do motor
quant e do Claim Verifier. Nova rodada incrementa `round_number` sem apagar
histórico.

## 8. Persistência

SQLite local, 28 tabelas. Bitemporalidade (`ref_date` × `as_of`) em toda
observação de mercado — é o que permite responder "o que sabíamos em 14/08" e
impedir look-ahead. `audit_log` é append-only por trigger.

## 9. Riscos de arquitetura

| Risco | Mitigação |
|---|---|
| Cobertura de dados públicos insuficiente | Upload manual + adapter genérico; classificação `proxy` explícita |
| RAG lexical erra sinônimo | Filtros por instituição e vigência; resposta "não confirmado" quando não há trecho |
| SQLite em pasta de rede falha | Fallback automático de WAL para DELETE; `COPILOT_DB` aponta disco local |
| Debate degenerar em concordância | Agente de Risco com prompt próprio e veto; vieses medidos por critério numérico |
