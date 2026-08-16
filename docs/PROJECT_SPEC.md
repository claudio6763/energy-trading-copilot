# PROJECT_SPEC — Energy Trading Copilot

Versão 1.0 · Sprint 0 (documentação) · Fonte prioritária: *Case Técnico — Trader II | Mesa de Energia* (PDF).
Em conflito entre este documento e o PDF, **o PDF prevalece**.

---

## 1. Problema

O case descreve o problema em termos explícitos: **não é falta de dado, é excesso de dado processado por um método que carrega viés e que não escala.**

Quatro sintomas declarados no PDF:

1. Volume de informação (dezenas de rodadas de modelos meteorológicos por dia, ensembles divergentes, previsão de vazão, boletins ONS e CCEE, leituras de mercado) chega diariamente "para uma cabeça só".
2. Viés cognitivo na condensação: ancoragem na última rodada, peso excessivo no modelo que confirma a posição existente, descarte rápido do que contraria a tese.
3. Premissas ficam na cabeça de quem teve a ideia; quando o cenário vira, não se reconstrói por que a posição existia.
4. Perda de rastreabilidade e de aprendizado — as duas coisas que separam um resultado bom de um resultado que se repete.

Consequência de desenho: o produto **não é um formulário que salva texto**. O valor está no que a ferramenta faz com a informação depois que ela entra.

## 2. Objetivo do produto

Uma mesa virtual que registra a tese de forma estruturada e auditável, a ataca antes de aceitá-la, e depois vigia automaticamente as premissas contra o mercado — emitindo o alerta **antes do prejuízo, não depois**.

## 3. Escopo

### 3.1 Núcleo obrigatório

- **F1 Registrar** — captura estruturada da tese.
- **F2 Desafiar** — crítica adversarial antes do salvamento.
- **F3 Vigiar** — monitoramento automático pós-registro.

### 3.2 Camada opcional (o case permite no máximo uma)

- **F4 Otimização de portfólio sob restrição de VaR** — dada a exposição registrada, qual a alocação marginal que melhora a relação risco-retorno sem estourar R$ 50 mi.

### 3.3 Entregas do case suportadas pela ferramenta

- A tese da **Entrega 2** (proposta de posição, data-corte 14/08, limite de VaR R$ 50 mi) deve estar **registrada e persistida** dentro da plataforma.
- Na defesa, a banca abrirá o registro, navegará por ele e pedirá **registro ao vivo de uma tese nova com um dado fornecido na hora** — o fluxo de registro precisa aceitar evidência nova em tempo de sessão.
- A **Entrega 3** (produto estruturado) é documento; a ferramenta não precisa gerá-la, mas o motor quant deve conseguir precificar o payoff proposto para sustentar a defesa.

---

## 4. Requisitos funcionais

### F1 — Registrar

| ID | Requisito | Prioridade |
|---|---|---|
| RF-01 | Registrar tese com campos obrigatórios: título, direção, produto, submercado, horizonte, data de reavaliação, resumo (≤ 5 linhas). | Must |
| RF-02 | Registrar **premissas** como entidades individuais, cada uma com tipo (hidrológica, preço, carga, regulatória, liquidez), enunciado, valor esperado, faixa de tolerância e `evidence_id`. | Must |
| RF-03 | Registrar **posição/dimensionamento**: volume (MWh), preço de referência, período de entrega, contraparte (opcional), e consumo do limite de VaR. | Must |
| RF-04 | Registrar **fontes** com URL/documento, autor/órgão, data de publicação, `as_of` e classificação de licença. | Must |
| RF-05 | Registrar **riscos** identificados com severidade e probabilidade qualitativa. | Must |
| RF-06 | Registrar **gatilhos** de saída como regras avaliáveis por máquina (métrica, operador, limiar, janela), não texto livre. | Must |
| RF-07 | Registrar **condições de invalidação** da tese, também como regras avaliáveis. | Must |
| RF-08 | Registrar **resultado esperado como intervalo** (P5/P50/P95), nunca número único. | Must |
| RF-09 | Toda tese é imutável após aprovação; alterações geram nova **versão** com diff e motivo. | Must |
| RF-10 | Estado da tese: `RASCUNHO → EM_DEBATE → APROVADA → ATIVA → EM_REVISÃO → ENCERRADA/INVALIDADA`. Transições registradas na trilha de auditoria. | Must |
| RF-11 | Anexar evidência ad-hoc durante a sessão (número, print, trecho de boletim) com criação de `evidence` própria — suporta o registro ao vivo na defesa. | Must |
| RF-12 | Exportar a tese completa (tese + premissas + evidências + debate + cenários) em um único documento. | Should |

### F2 — Desafiar

| ID | Requisito | Prioridade |
|---|---|---|
| RF-20 | Antes de permitir a aprovação, executar rodada de **debate multi-agente** com, no mínimo, Trader (defesa), Risco (ataque), Regulatório (RAG) e Inteligência de Mercado. | Must |
| RF-21 | O debate deve produzir explicitamente: (a) contra-argumento principal, (b) **premissa mais frágil** identificada e justificada, (c) **cenário que quebra a posição** com impacto quantificado pelo motor quant, (d) sinalização de **viés de confirmação**. | Must |
| RF-22 | Detecção de viés de confirmação baseada em critério mensurável: proporção de fontes citadas cuja direção concorda com a tese; ausência de fonte contrária disponível no acervo; concentração de fontes em uma única janela temporal ou em um único emissor. | Must |
| RF-23 | O Agente de Risco é **independente**: não recebe o prompt de defesa do Trader, não pode ser sobrescrito pelo Orquestrador e tem poder de veto sobre `APROVADA` quando o limite de VaR é violado. | Must |
| RF-24 | Toda afirmação numérica feita no debate deve vir do motor quant ou de SQL, com `evidence_id`; afirmação sem evidência é bloqueada pelo Claim Verifier. | Must |
| RF-25 | O resultado do debate (todas as falas, ferramentas chamadas, evidências, veredito) é persistido e vinculado à versão da tese. | Must |
| RF-26 | O trader deve responder por escrito à premissa mais frágil antes de aprovar — resposta registrada. | Should |
| RF-27 | Se o debate não gerar nenhum contra-argumento com evidência, o sistema marca a rodada como **inconclusiva** e não libera aprovação. | Must |

### F3 — Vigiar

| ID | Requisito | Prioridade |
|---|---|---|
| RF-30 | **Watchdog automático** em execução agendada (padrão: a cada 6h + sob demanda), sem depender de ação do trader. | Must |
| RF-31 | A cada ciclo, reavaliar: (a) cada premissa contra o dado mais recente, (b) cada gatilho de saída, (c) cada condição de invalidação, (d) VaR recalculado contra o limite, (e) mudanças regulatórias relevantes via RAG. | Must |
| RF-32 | Classificar cada premissa em `VÁLIDA / SOB_TENSÃO / VIOLADA` conforme a faixa de tolerância declarada em RF-02. | Must |
| RF-33 | Emitir alerta com severidade (`INFO / ATENÇÃO / CRÍTICO`), premissa afetada, dado que mudou, `evidence_id` do dado novo e delta em relação ao valor esperado. | Must |
| RF-34 | Alerta crítico move a tese para `EM_REVISÃO` automaticamente e exige decisão registrada (manter / ajustar / encerrar) com justificativa. | Must |
| RF-35 | Histórico de execuções do Watchdog visível: quando rodou, o que checou, o que não conseguiu checar e por quê (fonte indisponível ≠ premissa válida). | Must |
| RF-36 | **Falha de dado nunca é silenciosa.** Fonte indisponível gera alerta de cobertura, não ausência de alerta. | Must |
| RF-37 | Deduplicação e supressão de alerta repetido (mesmo gatilho, mesma janela) para evitar fadiga de alerta. | Should |

### F4 — Otimização sob restrição de VaR (camada opcional)

| ID | Requisito | Prioridade |
|---|---|---|
| RF-40 | Dado o conjunto de posições registradas, calcular VaR do portfólio e a contribuição marginal de cada posição. | Must |
| RF-41 | Propor alocação marginal que maximize retorno esperado sujeito a VaR ≤ R$ 50 mi, resolvida numericamente (SciPy), não pelo LLM. | Must |
| RF-42 | Apresentar fronteira risco-retorno e o ponto atual do portfólio sobre ela. | Should |
| RF-43 | O LLM apenas **explica** a solução em linguagem de mesa; não altera nenhum número da otimização. | Must |

### Transversais — evidência, risco e auditoria

| ID | Requisito | Prioridade |
|---|---|---|
| RF-50 | Todo número exibido na UI é clicável e revela a evidência: fonte, `as_of`, consulta ou execução que o produziu. | Must |
| RF-51 | **Claim Verifier** intercepta toda saída de LLM, extrai afirmações, classifica em `NUMÉRICA / FACTUAL / OPINIÃO` e valida contra evidências. Numérica ou factual sem lastro é bloqueada. | Must |
| RF-52 | Motor quant determinístico: VaR (histórico, paramétrico e Monte Carlo com seed fixa), P&L (realizado, marcação a mercado, carrego) e cenários hidrológicos. | Must |
| RF-53 | Cenários hidrológicos mínimos: **dois distintos** (ex.: Base e Seco, ou Úmido e Seco), com resultado esperado, impacto no VaR e o que muda na tese em cada um — conforme exigido na Entrega 2. | Must |
| RF-54 | Limite de VaR de **R$ 50 milhões** verificado em código no salvamento, no debate e a cada ciclo do Watchdog. | Must |
| RF-55 | **Trilha de auditoria** append-only: ator (humano ou agente), ação, entidade, antes/depois, `as_of`, timestamp, `run_id`, modelo e versão de prompt quando aplicável. | Must |
| RF-56 | Reprodutibilidade: dado um `run_id`, reconstruir a entrada exata do motor quant e obter o mesmo resultado. | Must |
| RF-57 | Separação `DEMO` / `REAL` visível na UI e imposta no banco; nenhuma agregação mistura os dois. | Must |
| RF-58 | Toda consulta e todo cálculo recebem `as_of` explícito; nenhum dado com data posterior ao `as_of` entra no resultado (proteção contra look-ahead). | Must |

---

## 5. Requisitos não funcionais

| ID | Requisito |
|---|---|
| RNF-01 | **Persistência real.** O registro deve continuar existindo quando a banca abrir a aplicação na defesa. Estado de sessão não atende. |
| RNF-02 | Deploy público com **acesso de teste** (link + credencial). Repositório **privado** — o conteúdo do case é confidencial. |
| RNF-03 | Latência: registro e consulta < 2 s; rodada de debate < 90 s; ciclo do Watchdog < 5 min. |
| RNF-04 | Determinismo: mesmo `as_of` + mesmas entradas ⇒ mesmo número. LLM com `temperature` baixa e prompts versionados; números nunca dependem do LLM. |
| RNF-05 | Custo de LLM por rodada de debate limitado e observável; orçamento por rodada configurável. |
| RNF-06 | Degradação graciosa: sem chave de LLM, F1 e F3 continuam funcionando; sem Postgres, SQLite local assume. |
| RNF-07 | Segurança: segredos fora do código; sem PII de contraparte; conexão TLS ao banco. |
| RNF-08 | **Licenciamento de dados** verificado na ingestão. Fonte licenciada sem autorização é rejeitada, não mascarada. |
| RNF-09 | Testabilidade: `pytest` verde como gate de fim de sprint; motor quant com valores de referência em `tests/golden/`. |
| RNF-10 | Observabilidade: log estruturado por `run_id`, com custo, latência e ferramentas chamadas por agente. |
| RNF-11 | Portabilidade: `docker compose up` sobe a aplicação completa localmente. |
| RNF-12 | Acessibilidade operacional: a ferramenta é para uma mesa pequena; nada de configuração que exija DBA. |

---

## 6. Fora de escopo (Sprints 1–8)

Declarado explicitamente para não virar dívida silenciosa:

- Execução de ordens, conexão a broker ou a plataformas de negociação (BBCE e afins).
- Contabilização oficial, liquidação CCEE e conciliação financeira.
- Multi-tenant, RBAC granular, SSO corporativo.
- Modelagem hidrológica própria (SMAP/ONS) — usaremos saídas publicadas, não recalcularemos.
- Fine-tuning de modelo; treinamento próprio de previsor de preço.
- Post-mortem automatizado, síntese multi-fonte e geração assistida de teses — as outras três camadas opcionais do case, descartadas pela regra "escolha no máximo uma".
- Aplicativo móvel.

---

## 7. Premissas declaradas

O case determina: *"Premissa declarada não é erro. Premissa escondida é."*

| ID | Premissa | Motivo |
|---|---|---|
| PR-01 | Não há book posicionado de partida; o portfólio inicial é vazio. | Declarado no PDF. |
| PR-02 | O limite de R$ 50 mi é o **único** constraint dado; alocação, produto, prazo e direção são escolha nossa. | Declarado no PDF. |
| PR-03 | Definição operacional de VaR adotada **provisoriamente**: paramétrico e histórico a 95% de confiança sobre horizonte de 21 dias úteis, no portfólio consolidado, em R$ nominais. Configurável. | O PDF não define confiança, horizonte nem metodologia. → **Dúvida D-01**, a enviar até 10/08. |
| PR-04 | Data-corte de dados da análise: **14/08**. Dados posteriores existem apenas como evento de Watchdog, nunca como base da tese. | Declarado no PDF. |
| PR-05 | Fontes públicas (ONS, CCEE, ANEEL, INMET, NOAA/GFS, ECMWF aberto) são a base; provedores licenciados (curvas forward comerciais, terminais de mercado) ficam **bloqueados** salvo autorização escrita. | Princípio P10. → **Dúvida D-02**. |
| PR-06 | Metas de margem e VPL até 31/12 entram como **restrição de horizonte**: posições cujo horizonte ultrapassa 31/12 devem declarar o efeito no ano corrente. | O PDF pede considerar "da forma que julgar correta". |
| PR-07 | Perfil de risco da mesa: aversão moderada; preferência declarada no case por "tese modesta e bem fundamentada" sobre "tese ambiciosa sem sustentação". Consumo-alvo do limite de VaR: parcial, não integral. | Critério de avaliação do PDF. |
| PR-08 | Um único usuário/perfil de acesso para a defesa (credencial compartilhada de teste). | Simplificação de prazo. → **Dúvida D-05**. |
| PR-09 | Dados de teste em `dataset_kind=DEMO` são sintéticos e rotulados; a tese da Entrega 2 vive em `REAL`. | Princípio P9. |
| PR-10 | Fuso horário de referência America/Sao_Paulo para `as_of`; armazenamento em UTC. | Convenção. |

---

## 8. Dúvidas a enviar à banca (prazo do case: segunda-feira, 10/08)

| ID | Dúvida | Bloqueia |
|---|---|---|
| D-01 | Qual a definição do limite de VaR de R$ 50 mi: nível de confiança (95% ou 99%), horizonte (1 dia ou horizonte da posição), metodologia aceita, e se é VaR da posição isolada ou da mesa consolidada? | Dimensionamento da Entrega 2 e RF-54. Contornável por PR-03, mas altera o resultado. |
| D-02 | Há autorização para usar dados de provedores licenciados (curvas forward comerciais)? Se não, proxy público declarado é aceito para marcação? | Qualidade da precificação. Contornável com proxy declarado. |
| D-03 | O "dado que daremos na hora" na defesa virá em qual formato (número solto, PDF, planilha, link)? | Desenho do RF-11. Contornável suportando os quatro. |
| D-04 | O limite de VaR é *hard* (bloqueia) ou *soft* (alerta com aprovação)? | Comportamento do veto do Agente de Risco. Assumido *hard*. |
| D-05 | Credencial de teste compartilhada é aceitável, ou a banca espera contas individuais? | RNF-02. Assumido compartilhada. |

Nenhuma destas impede o início do Sprint 1. D-01 é a única com impacto material no resultado da Entrega 2.

---

## 9. Rastreabilidade ao PDF

| Exigência do PDF | Onde é atendida |
|---|---|
| Registrar: premissas, dados com fonte, dimensionamento, resultado esperado, horizonte, gatilhos de saída, o que invalidaria | RF-01…RF-08 |
| Auditável depois | RF-09, RF-55, RF-56 |
| Desafiar antes de salvar; contra-argumento; premissa mais frágil; cenário que quebra; viés de confirmação | RF-20…RF-22, RF-27 |
| "Se a ferramenta só concorda com o trader, ela não serve para nada" | RF-23, RF-27 |
| Vigilância automática, não campo manual | RF-30, RF-36 |
| "O alerta que chega antes do prejuízo" | RF-31…RF-34 |
| Camada opcional (uma só): otimização sob VaR | RF-40…RF-43 |
| "Como você impede a ferramenta de inventar número?" | RF-51, RF-50, `ARCHITECTURE.md §6` |
| "Onde usar IA e onde não usar?" | `ARCHITECTURE.md §7` |
| Limite de VaR R$ 50 mi | RF-54 |
| Dois cenários hidrológicos distintos | RF-53 |
| Resultado esperado como intervalo | RF-08 |
| Data-corte 14/08 | RF-58, PR-04 |
| Persistência que sobrevive à sessão | RNF-01 |
| Registro ao vivo de tese nova na defesa | RF-11 |
| Confidencialidade do case | RNF-02 |
