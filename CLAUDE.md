# CLAUDE.md — Energy Trading Copilot

Instruções permanentes. Leia antes de qualquer alteração. Concisas de propósito.

## 1. O que é

Mesa virtual de trading para a mesa de comercialização de energia. Três funções obrigatórias:

1. **Registrar** — tese estruturada: premissas, posição, dimensionamento, fontes, riscos, horizonte, gatilhos de saída, condições de invalidação. Auditável depois.
2. **Desafiar** — debate adversarial entre agentes antes do salvamento: contra-argumento, premissa mais frágil, cenário que quebra a posição, sinalização de viés de confirmação.
3. **Vigiar** — Watchdog automático sobre dados, riscos, regras e gatilhos. Sem campo de revisão manual.

Camada opcional escolhida (apenas uma, por regra do case): **otimização de portfólio sob restrição de VaR**.

Fonte de verdade: `docs/` + o PDF do case. **Em qualquer conflito, o PDF do case prevalece.**

## 2. Princípios invioláveis

Estes não são preferências. Violação = bug bloqueante.

| # | Regra |
|---|---|
| P1 | **RAG para documentos.** Texto normativo, boletim, relatório → recuperação com citação de trecho. |
| P2 | **SQL para números.** Todo número factual vem de consulta ao banco, nunca de memória de modelo. |
| P3 | **Python para cálculo.** VaR, P&L, cenários e otimização em código determinístico e testado. |
| P4 | **LLM para interpretação e debate.** Só isso. |
| P5 | **Nenhum número factual gerado pelo LLM.** Números aparecem por *substituição de placeholder* a partir de resultados de SQL ou do motor quant. |
| P6 | **Toda afirmação factual carrega `evidence_id`.** Sem `evidence_id`, a afirmação não é persistida nem exibida como fato. |
| P7 | **Controle de data-base.** Toda consulta e todo cálculo recebem `as_of`. Nada usa dado posterior ao `as_of` do contexto. Data-corte da análise do case: **14/08**. |
| P8 | **Limite de VaR: R$ 50.000.000.** Verificado por código, não por prompt. Ultrapassagem bloqueia a aprovação da tese. |
| P9 | **Dados demonstrativos separados dos reais.** `dataset_kind ∈ {DEMO, REAL}` em toda linha e todo gráfico. Nunca misturar na mesma agregação. |
| P10 | **Nada confidencial ou licenciado sem autorização.** Fonte sem licença compatível é bloqueada na ingestão, não filtrada na saída. |

## 3. Fronteira de camadas

```
LLM  →  pode: interpretar, hipotetizar, criticar, redigir, classificar, escolher qual ferramenta chamar
     →  não pode: emitir número, afirmar fato sem evidência, aprovar tese, calcular VaR/P&L,
                  escrever SQL executado sem validação, alterar limites de risco
```

Toda saída de agente passa pelo **Claim Verifier** antes de virar registro ou UI. Saída não verificada é marcada `UNVERIFIED` e renderizada como opinião, nunca como dado.

## 4. Stack

Python 3.12 · Streamlit · SQLAlchemy 2.x · Alembic · PostgreSQL/Supabase (SQLite como fallback local) · pgvector · Anthropic SDK · Pydantic v2 · pandas · NumPy · SciPy · Plotly · pytest · Docker.

Deploy alvo: **Streamlit Cloud + Supabase**. Repositório privado (o conteúdo do case é confidencial).

Não introduza dependência nova sem registrar ADR em `docs/adr/`.

## 5. Convenções

- Toda entrada e saída de agente é um modelo **Pydantic**. Nada de `dict` solto atravessando fronteira.
- Toda mudança de schema passa por **migração Alembic**. Sem `create_all` em produção.
- `evidence_id`, `thesis_id`, `run_id`: ULID em string.
- Timestamps em UTC, `timestamptz`. `as_of` é **date** no fuso America/Sao_Paulo, separado de `created_at`.
- Dinheiro em `Numeric(18,2)`, energia em MWh `Numeric(18,3)`, preço em R$/MWh `Numeric(12,2)`. **Nunca `float` para dinheiro.**
- Nada de segredo em código. `.env` local, secrets do Streamlit em produção.
- Nomes de domínio em português (`tese`, `premissa`, `gatilho`); nomes de código em inglês.

## 6. Testes

- Motor quant: testes determinísticos com valores de referência (`tests/golden/`). Seed fixa em Monte Carlo.
- Claim Verifier: suíte adversarial com saídas de LLM contendo números inventados. Deve bloquear 100%.
- Limite de VaR: teste de fronteira em R$ 49,9 mi / 50,0 mi / 50,1 mi.
- Nenhuma chamada de LLM em teste unitário. Respostas mockadas.
- `pytest` deve passar antes de fechar qualquer sprint.

## 7. Fluxo de trabalho

- Sprint atual e próximos passos: `SPRINT_STATUS.md`. Atualize ao fim de cada sprint.
- Backlog: `docs/BACKLOG.md`. Não trabalhe fora do sprint corrente.
- Requisitos: `docs/PROJECT_SPEC.md` (IDs `RF-xx` / `RNF-xx`). Todo commit relevante referencia um ID.
- Critérios de pronto: `docs/ACCEPTANCE_CRITERIA.md`.
- Contrato de dados: `docs/DATA_CONTRACT.md`.

## 8. Nunca

- Nunca inventar dado, fonte, número ou requisito. Se falta informação, declare a premissa em `docs/PROJECT_SPEC.md §7` e siga.
- Nunca fazer o Watchdog depender de ação humana.
- Nunca deixar o copiloto apenas concordar com o trader — se o debate não produziu contra-argumento acionável, é falha.
- Nunca commitar dado real de contraparte, preço licenciado ou conteúdo do case em repositório público.
