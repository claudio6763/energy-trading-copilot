# BACKLOG — Sprints 1 a 8

Versão 1.0 · Sprint 0. Restrição dura: **entrega segunda-feira, 17/08, até 10h00**. Hoje é sábado, 08/08 — restam 9 dias corridos. Cada sprint tem cerca de um dia. Defesa em 18 ou 19/08.

Regra de sequenciamento: **o núcleo obrigatório (Registrar, Desafiar, Vigiar) precede a camada opcional.** O case é explícito: *"preferimos três funções que funcionam a dez que abrem"*. Se o prazo apertar, o corte começa pelo Sprint 7-B (otimização), nunca pelos Sprints 1–6.

| Sprint | Janela | Tema | Gate de saída |
|---|---|---|---|
| 0 | sáb 08/08 | Documentação e estrutura | Docs revisados contra o PDF |
| 1 | sáb 08/08 – dom 09/08 | Fundação e persistência | Schema migrado, app sobe |
| 2 | dom 09/08 – seg 10/08 | Dados, SQL e evidência | Número na tela com fonte |
| 3 | seg 10/08 – ter 11/08 | Motor quantitativo | VaR reprodutível, limite testado |
| 4 | ter 11/08 – qua 12/08 | RAG e Claim Verifier | Suíte adversarial bloqueia 100% |
| 5 | qua 12/08 – qui 13/08 | Debate multi-agente (**Desafiar**) | Debate produz contra-argumento com evidência |
| 6 | qui 13/08 – sex 14/08 | Watchdog (**Vigiar**) | Alerta automático sem toque humano |
| 7 | sex 14/08 – sáb 15/08 | UI, deploy e otimização sob VaR | Link público com credencial de teste |
| 8 | sáb 15/08 – dom 16/08 | Entregas 2 e 3, vídeo, ensaio | Pacote fechado e ensaiado |

---

## Sprint 1 — Fundação e persistência

**Objetivo.** Um esqueleto que sobe, persiste e audita. Sem inteligência ainda.

- S1-01 Projeto Python 3.12, gerenciamento de dependências, `pyproject.toml`, lint e formatação.
- S1-02 Modelos SQLAlchemy 2.x para todas as entidades de `DATA_CONTRACT.md`.
- S1-03 Modelos Pydantic v2 espelhando os contratos de entrada/saída dos agentes.
- S1-04 Migração inicial Alembic; `upgrade`/`downgrade` verificados.
- S1-05 Camada de conexão com Postgres/Supabase e fallback SQLite automático.
- S1-06 `audit_log` append-only com permissões restritas; helper de escrita usado por todo caminho de gravação.
- S1-07 Contexto de `as_of` global (sessão) e injeção em repositórios.
- S1-08 Impositor de `dataset_kind` na camada de repositório.
- S1-09 Esqueleto Streamlit: navegação, indicador permanente de `as_of` e de `dataset_kind`.
- S1-10 `docker compose` (app + Postgres + pgvector) e `.env.example`.
- S1-11 CI mínimo: `pytest` + varredura de segredos.
- S1-12 ADR-001, 002, 008, 009 redigidos.

**Gate.** `alembic upgrade head` funciona nos dois bancos; app sobe; gravação de teste aparece em `audit_log`; `pytest` verde. → AC-06 parcial, AC-61, AC-73, AC-75.

---

## Sprint 2 — Dados, SQL e evidência (RF-50, RF-58, P2/P6/P7)

**Objetivo.** Do dado bruto público até um número na tela com proveniência clicável.

- S2-01 Catálogo de fontes preenchido com ficha de licença (ONS, CCEE, ANEEL, INMET, NOAA/GFS).
- S2-02 Ingestores para as séries mínimas de `DATA_CONTRACT.md §6`, com `ref_date` + `as_of` (bitemporal).
- S2-03 Guarda de licenciamento na ingestão: rejeição de `LICENSED_BLOCKED` / `CONFIDENTIAL_EXTERNAL`.
- S2-04 Fábrica de `evidence`: toda observação nasce com `evidence_id`, `content_hash` e `as_of`.
- S2-05 Agente de Dados e SQL: templates parametrizados para as consultas recorrentes.
- S2-06 Validador de SQL por AST: somente `SELECT`, allowlist, `LIMIT`, timeout, injeção obrigatória de `as_of` e `dataset_kind`.
- S2-07 Registro de `sql_execution` → `evidence` do tipo `SQL_QUERY`.
- S2-08 Preservação de divergência entre modelos meteorológicos (sem média na ingestão).
- S2-09 Dataset `DEMO` sintético e rotulado, para desenvolvimento e testes.
- S2-10 Componente de UI "número com evidência" (clique abre fonte, `as_of`, consulta).
- S2-11 Teste de look-ahead: consulta com `as_of = 14/08` não retorna dado de 15/08.

**Gate.** AC-08, AC-55, AC-56, AC-57.

---

## Sprint 3 — Motor quantitativo (RF-52…RF-54, P3)

**Objetivo.** Números defensáveis. Nenhum LLM no caminho.

- S3-01 `quant/var.py`: VaR paramétrico, histórico e Monte Carlo com seed fixa; Expected Shortfall.
- S3-02 VaR marginal e componente por posição.
- S3-03 `quant/pnl.py`: P&L realizado, marcação a mercado e carrego; atribuição tese × carrego × mercado.
- S3-04 `quant/scenarios.py`: motor de cenários; definição declarativa de choques.
- S3-05 Dois cenários hidrológicos distintos parametrizados (ex.: Base e Seco), com fonte declarada.
- S3-06 `quant/limits.py`: verificação do limite de R$ 50 mi como função pura.
- S3-07 Persistência de `quant_run` com `inputs_hash`, `seed`, `code_version`, `as_of`.
- S3-08 Valores de referência em `tests/golden/` e testes de reprodutibilidade.
- S3-09 Teste de fronteira do limite: 49,9 / 50,0 / 50,1 mi.
- S3-10 Página de UI: VaR e cenários com resultado em intervalo (P5/P50/P95).

**Gate.** AC-40 a AC-44, AC-42, AC-43.

---

## Sprint 4 — RAG regulatório e Claim Verifier (RF-51, P1)

**Objetivo.** A defesa contra invenção de número, pronta e testada. **Sprint mais crítico do projeto.**

- S4-01 Pipeline de ingestão documental: download, hash, chunking, metadados de vigência e licença.
- S4-02 Embeddings + pgvector; índice lexical para busca híbrida; reranking.
- S4-03 Filtro de vigência por `as_of` na recuperação.
- S4-04 Agente Regulatório: resposta sempre com trecho literal, documento, página e `evidence_id`; "não encontrado no acervo" quando não houver lastro.
- S4-05 Claim Verifier — extração e classificação de afirmações (`NUMÉRICA`/`FACTUAL`/`OPINIÃO`).
- S4-06 Claim Verifier — detector de número órfão (parser numérico sobre o texto renderizado).
- S4-07 Claim Verifier — vinculação a `evidence_id` e recomputação com tolerância declarada.
- S4-08 Renderizador de placeholders: marcador sem evidência ⇒ falha visível, nunca texto plausível.
- S4-09 Persistência de `claim` e bloqueio de transição de estado em `CONTRADICTED`/`BLOCKED`.
- S4-10 **Suíte adversarial**: saídas de LLM com números inventados; meta de bloqueio 100%.
- S4-11 ADR-003 e ADR-006.

**Gate.** AC-50 a AC-54. Sem 100% em AC-50, o sprint não fecha.

---

## Sprint 5 — Debate multi-agente · função **Desafiar** (RF-20…RF-27)

**Objetivo.** Uma ferramenta que discorda com fundamento.

- S5-01 Agente Orquestrador: roteamento, montagem de contexto com `as_of`, orçamento de custo/tempo.
- S5-02 Agente Trader: estruturação da tese e defesa.
- S5-03 Agente de Risco independente: contexto isolado, prompt e versão próprios, poder de veto.
- S5-04 Agente de Inteligência de Mercado: busca ativa da leitura contrária; divergência explicitada.
- S5-05 Protocolo de rodadas: defesa → ataque → réplica → consolidação.
- S5-06 Identificação da premissa mais frágil, vinculada ao `assumption_id`.
- S5-07 Geração do cenário que quebra a posição, executada pelo motor quant.
- S5-08 Escore de viés de confirmação por critério numérico (RF-22) + leitura qualitativa.
- S5-09 Veredito consolidado; `INCONCLUSIVA` quando não há contra-argumento com evidência.
- S5-10 Veto de VaR integrado ao fluxo de aprovação.
- S5-11 Resposta escrita do trader à premissa mais frágil, obrigatória antes de aprovar.
- S5-12 Persistência completa de `debate_session` / `debate_turn` / `claim`.
- S5-13 Testes com teses deliberadamente frágeis e deliberadamente sólidas.
- S5-14 ADR-004.

**Gate.** AC-10 a AC-17.

---

## Sprint 6 — Watchdog · função **Vigiar** (RF-30…RF-37)

**Objetivo.** O alerta que chega antes do prejuízo. Zero dependência de ação humana.

- S6-01 Scheduler (padrão a cada 6h) + execução sob demanda + gatilho por chegada de dado.
- S6-02 Avaliador determinístico de regras: métrica, operador, limiar, janela.
- S6-03 Reavaliação de premissas contra faixa de tolerância → `VÁLIDA`/`SOB_TENSÃO`/`VIOLADA`.
- S6-04 Avaliação de gatilhos de saída e de condições de invalidação.
- S6-05 Recálculo de VaR e verificação do limite a cada ciclo.
- S6-06 Checagem regulatória via RAG: norma nova com vigência posterior ao registro da tese.
- S6-07 Geração de alertas com valor observado, esperado, delta e `evidence_id`.
- S6-08 Alerta de cobertura quando a fonte falha; run marcado `PARCIAL`.
- S6-09 Deduplicação e supressão por janela.
- S6-10 Escalonamento: `CRÍTICO` move a tese para `EM_REVISÃO`; decisão humana obrigatória e registrada.
- S6-11 UI: painel de alertas, histórico de execuções e o que não foi checado.
- S6-12 Teste ponta a ponta: injetar dado violador → alerta no ciclo seguinte, sem toque manual.
- S6-13 ADR-005.

**Gate.** AC-20 a AC-27.

> **Marco externo: 14/08 é a data-corte da análise.** Ao fim deste sprint, congelar o `as_of` da Entrega 2 e etiquetar o estado dos dados.

---

## Sprint 7 — UI, deploy e otimização sob VaR

**7-A · Núcleo (prioridade absoluta)**

- S7-01 Fluxo Registrar completo e utilizável por quem não conhece o sistema.
- S7-02 Fluxo Desafiar com o veredito legível e o contra-argumento em destaque.
- S7-03 Painel Vigiar com premissas, alertas e histórico.
- S7-04 Navegador de auditoria: linha do tempo da tese, quem contestou o quê, o que mudou.
- S7-05 Anexo de evidência ad-hoc — o caminho do registro ao vivo na defesa (RF-11).
- S7-06 Deploy em Streamlit Cloud + Supabase; repositório privado; credencial de teste.
- S7-07 Verificação de persistência pós-deploy: reiniciar, reabrir, registro íntegro.
- S7-08 Ensaio cronometrado do registro ao vivo (meta ≤ 10 min).

**7-B · Camada opcional — otimização sob restrição de VaR (cortável)**

- S7-10 `quant/optimize.py`: maximizar retorno esperado sujeito a VaR ≤ R$ 50 mi (SciPy).
- S7-11 Contribuições marginais e fronteira risco-retorno (Plotly).
- S7-12 Página de UI com o ponto atual do portfólio sobre a fronteira.
- S7-13 Explicação em linguagem de mesa gerada por LLM, com números idênticos ao `quant_run`.
- S7-14 ADR-007.

**Gate.** AC-30 a AC-32, AC-70 a AC-74, AC-80.

---

## Sprint 8 — Entregas 2 e 3, vídeo e ensaio

**Objetivo.** Fechar o pacote. Nenhuma funcionalidade nova.

- S8-01 **Entrega 2 — proposta de posição** (até 2 páginas): tese em até 5 linhas; dimensionamento e consumo do limite de R$ 50 mi; resultado esperado como intervalo; horizonte e data de reavaliação; gatilhos de saída e o que invalidaria a tese; premissas com fonte; comportamento em dois cenários hidrológicos distintos com impacto no VaR.
- S8-02 Consideração explícita das metas de margem e VPL até 31/12.
- S8-03 **Planilha aberta**, com fórmulas visíveis e **sem valores colados** — exportada a partir do motor quant.
- S8-04 Registro da tese da Entrega 2 dentro da plataforma, em `dataset_kind=REAL`, com debate rodado e evidências vinculadas.
- S8-05 **Entrega 3 — produto estruturado** (até 1 página): conceito e payoff, perfil de cliente e dor, por que ainda não é comum, como a mesa se protege, risco residual na companhia, precificação aproximada e margem esperada.
- S8-06 Documento de 1 página da Entrega 1: problema resolvido, escolhas de arquitetura, o que ficou de fora e por quê, o que faríamos com mais duas semanas.
- S8-07 Respostas escritas às duas perguntas obrigatórias (invenção de número; onde usar e não usar IA) — derivadas de `ARCHITECTURE.md §6` e §7.
- S8-08 Anexo de transparência de IA: prompts principais + parágrafo sobre onde a IA errou e como percebemos.
- S8-09 Declaração de todas as fontes utilizadas, com data-corte 14/08.
- S8-10 **Vídeo de até 3 minutos** demonstrando as três funções do núcleo.
- S8-11 Verificação de formato: até 4 páginas no total, fora anexos.
- S8-12 Ensaio da defesa: 15 min de demonstração + 20 min de apresentação + simulação de discussão hostil.
- S8-13 Revisão final de confidencialidade: nada do case em lugar público.

**Gate.** AC-80 a AC-85 e a lista de conformidade do case fechada.

---

## Marcos externos

| Data | Marco |
|---|---|
| seg 10/08 | Prazo para enviar dúvidas à banca (D-01…D-05 em `PROJECT_SPEC.md §8`) |
| sex 14/08 | Data-corte dos dados da análise |
| seg 17/08, 10h00 | **Entrega** |
| 18 ou 19/08 | Defesa presencial, 60 minutos |

## Política de corte, em ordem

1. Sprint 7-B (otimização sob VaR) — a camada opcional inteira.
2. Requisitos `Should` (RF-12, RF-26, RF-37, RF-42).
3. Profundidade do acervo RAG (menos documentos, mesma disciplina de citação).
4. Riqueza da UI.

**Nunca cortar:** Claim Verifier, verificação do limite de VaR, persistência, trilha de auditoria, automatismo do Watchdog.
