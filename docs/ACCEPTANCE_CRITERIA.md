# ACCEPTANCE_CRITERIA — Energy Trading Copilot

Versão 1.0 · Sprint 0. Critérios verificáveis. Um critério que não pode ser demonstrado ao vivo na defesa não conta como pronto.

Convenção: **Dado / Quando / Então**. Cada critério referencia o requisito de `PROJECT_SPEC.md`.

---

## 1. Definição de Pronto (vale para toda entrega)

Uma funcionalidade só está pronta quando, cumulativamente:

1. `pytest` passa integralmente.
2. Nenhum número exibido carece de `evidence_id` acessível pela UI.
3. A ação aparece na trilha de auditoria com ator, `as_of` e antes/depois.
4. Funciona com o banco persistente — reiniciar a aplicação não perde o registro.
5. `dataset_kind` está explícito na tela.
6. O comportamento é demonstrável em menos de 60 segundos na defesa.

---

## 2. F1 — Registrar

| # | Critério | Req. |
|---|---|---|
| AC-01 | **Dado** um trader com uma tese em linguagem natural, **quando** submete o formulário, **então** o sistema persiste tese, premissas, posição, fontes, riscos, gatilhos e condições de invalidação como entidades separadas e consultáveis. | RF-01…RF-07 |
| AC-02 | **Dado** um rascunho de tese, **quando** alguma premissa não tem `evidence_id`, **então** o salvamento é bloqueado com mensagem indicando exatamente qual premissa está sem lastro. | RF-02, P6 |
| AC-03 | **Dado** um gatilho informado como texto livre ("se a hidrologia piorar"), **quando** o trader tenta salvar, **então** o sistema exige métrica, operador, limiar e janela — e recusa o texto livre. | RF-06, RF-07 |
| AC-04 | **Dado** um resultado esperado informado como número único, **quando** o trader tenta salvar, **então** o sistema exige P5/P50/P95. | RF-08 |
| AC-05 | **Dado** uma tese em `APROVADA`, **quando** alguém a edita, **então** nasce a versão *n+1* com motivo obrigatório, e a versão *n* permanece consultável sem alteração. | RF-09 |
| AC-06 | **Dado** o servidor reiniciado (ou o navegador fechado e reaberto em outra máquina), **quando** a tese é buscada pelo id, **então** ela aparece íntegra com todas as relações. | RNF-01 |
| AC-07 | **Dado** um dado novo entregue verbalmente ou em arquivo durante a defesa, **quando** o trader o anexa como evidência, **então** o sistema cria `evidence` com `as_of`, `source_type=HUMAN_INPUT`/`EXTERNAL_FILE` e o número fica utilizável na tese em menos de 2 minutos. | RF-11 |
| AC-08 | **Dado** qualquer número na tela da tese, **quando** o avaliador clica nele, **então** aparece fonte, `as_of` e a consulta ou execução que o produziu. | RF-50 |

## 3. F2 — Desafiar

| # | Critério | Req. |
|---|---|---|
| AC-10 | **Dado** um rascunho de tese, **quando** o trader pede aprovação sem ter rodado o debate, **então** a aprovação é recusada. | RF-20 |
| AC-11 | **Dado** um debate concluído, **então** o registro contém, nomeados e separados: contra-argumento principal, premissa mais frágil (com id da premissa), cenário que quebra a posição (com `quant_run_id`) e avaliação de viés de confirmação. | RF-21 |
| AC-12 | **Dado** um conjunto de fontes onde ≥ 80% aponta na direção da tese e existe fonte contrária disponível no acervo não citada, **quando** o debate roda, **então** o sistema sinaliza viés de confirmação com o critério numérico explicitado. | RF-22 |
| AC-13 | **Dado** o log da sessão de debate, **quando** inspecionado, **então** o prompt do Agente de Risco não contém a argumentação de defesa do Agente Trader. | RF-23 |
| AC-14 | **Dado** um dimensionamento cujo VaR calculado excede R$ 50 mi, **quando** o trader tenta aprovar, **então** o Agente de Risco veta, a transição é bloqueada e o veto aparece na auditoria. | RF-23, RF-54 |
| AC-15 | **Dado** uma tese deliberadamente sólida, **quando** o debate roda, **então** ainda assim é produzido ao menos um contra-argumento com evidência; caso contrário a rodada é marcada `INCONCLUSIVA` e não libera aprovação. | RF-27 |
| AC-16 | **Dado** qualquer fala de agente contendo número, **quando** o Claim Verifier processa, **então** todo numeral está vinculado a `evidence_id` ou a fala é bloqueada. | RF-24, RF-51 |
| AC-17 | **Dado** um debate finalizado, **quando** o trader aprova, **então** sua resposta escrita à premissa mais frágil está registrada. | RF-26 |

## 4. F3 — Vigiar

| # | Critério | Req. |
|---|---|---|
| AC-20 | **Dado** uma tese `ATIVA` e nenhuma interação humana por 24h, **quando** se consulta o histórico, **então** existem ≥ 4 execuções de Watchdog registradas. | RF-30 |
| AC-21 | **Dado** uma premissa com faixa de tolerância declarada, **quando** o dado novo sai da faixa, **então** a premissa muda para `VIOLADA` e é emitido alerta com valor observado, valor esperado, delta e `evidence_id` do dado novo. | RF-32, RF-33 |
| AC-22 | **Dado** um gatilho de saída satisfeito, **quando** o Watchdog roda, **então** o alerta é `CRÍTICO` e a tese vai para `EM_REVISÃO` automaticamente. | RF-34 |
| AC-23 | **Dado** uma fonte indisponível no ciclo, **quando** o Watchdog termina, **então** o run é `PARCIAL`, existe alerta `COBERTURA_DADOS` e nenhuma premissa dependente daquela fonte é marcada `VÁLIDA`. | RF-36 |
| AC-24 | **Dado** o mesmo gatilho disparando em ciclos consecutivos na mesma janela, **quando** os alertas são listados, **então** há um alerta com contador, não N alertas idênticos. | RF-37 |
| AC-25 | **Dado** um alerta `CRÍTICO`, **quando** o trader o reconhece, **então** é obrigatória uma decisão (`MANTER`/`AJUSTAR`/`ENCERRAR`) com justificativa, registrada em auditoria. | RF-34, RF-55 |
| AC-26 | **Dado** o VaR recalculado no ciclo, **quando** ultrapassa R$ 50 mi, **então** alerta `VAR_LIMITE` crítico é emitido independentemente do estado das premissas. | RF-54 |
| AC-27 | **Dado** a demonstração da defesa, **quando** se injeta um dado que viola uma premissa registrada, **então** o alerta correspondente aparece no ciclo seguinte, sem edição manual de nenhum campo de revisão. | RF-30, RF-31 |

## 5. F4 — Otimização sob restrição de VaR (opcional)

| # | Critério | Req. |
|---|---|---|
| AC-30 | **Dado** um portfólio registrado, **quando** o VaR é calculado, **então** também são apresentadas as contribuições marginais por posição, somando ao VaR total dentro da tolerância declarada. | RF-40 |
| AC-31 | **Dado** o portfólio e o limite de R$ 50 mi, **quando** a otimização roda, **então** a alocação proposta respeita o limite e melhora a relação risco-retorno em relação ao ponto atual, com `quant_run_id` reprodutível. | RF-41 |
| AC-32 | **Dado** a explicação textual da otimização, **quando** verificada, **então** todo número nela é idêntico ao do `quant_run` correspondente (tolerância zero). | RF-43 |

## 6. Motor quantitativo

| # | Critério | Req. |
|---|---|---|
| AC-40 | **Dado** as mesmas entradas, o mesmo `as_of`, a mesma seed e a mesma versão de código, **quando** o cálculo roda duas vezes, **então** os resultados são idênticos bit a bit. | RF-56, RNF-04 |
| AC-41 | **Dado** os casos de referência em `tests/golden/`, **quando** o VaR é calculado nos três métodos, **então** os valores batem com os esperados dentro da tolerância documentada. | RF-52 |
| AC-42 | **Dado** uma tese qualquer, **quando** os cenários são executados, **então** existem ao menos **dois cenários hidrológicos distintos** com P&L esperado, impacto no VaR e descrição do que muda na tese em cada um. | RF-53 |
| AC-43 | **Dado** notionais de R$ 49,9 mi / 50,0 mi / 50,1 mi de VaR, **quando** o verificador de limite roda, **então** os vereditos são `OK` / `OK` / `VIOLADO` — testado explicitamente na fronteira. | RF-54 |
| AC-44 | **Dado** qualquer resultado do motor quant, **quando** rastreado, **então** existe `quant_run` com entradas, hash, seed e versão de código. | RF-52, RF-56 |

## 7. Antialucinação — a suíte que mais importa

Referência direta à pergunta obrigatória nº 1 do case.

| # | Critério | Req. |
|---|---|---|
| AC-50 | **Dado** um conjunto adversarial de saídas de LLM contendo números inventados (armazenamento, PLD, curva, volume), **quando** o Claim Verifier processa, **então** **100%** são classificados `BLOCKED` ou `CONTRADICTED`. Meta não negociável. | RF-51 |
| AC-51 | **Dado** um número correto porém sem `evidence_id`, **quando** processado, **então** é bloqueado do mesmo jeito. Acertar por acaso não é aceitável. | RF-51, P6 |
| AC-52 | **Dado** um valor afirmado divergente do valor da evidência vinculada, **quando** a recomputação roda, **então** o status é `CONTRADICTED` e a persistência da tese é bloqueada. | RF-51 |
| AC-53 | **Dado** o LLM sem acesso a ferramentas, **quando** é solicitado um número factual, **então** a resposta renderizada não contém número algum — apenas a indicação de dado indisponível. | P5 |
| AC-54 | **Dado** uma pergunta regulatória cuja resposta não está no acervo, **quando** o Agente Regulatório responde, **então** a resposta é "não encontrado no acervo", sem interpretação de memória paramétrica. | §3.4 ARCH |
| AC-55 | **Dado** uma consulta com `as_of = 14/08`, **quando** existe dado publicado em 15/08 no banco, **então** ele não aparece em nenhum resultado. | RF-58 |
| AC-56 | **Dado** uma fonte com `license_class = LICENSED_BLOCKED`, **quando** a ingestão é tentada, **então** é rejeitada com log — e nada daquela fonte existe no banco. | RNF-08, P10 |
| AC-57 | **Dado** um gráfico ou tabela qualquer, **quando** inspecionado, **então** não há mistura de `DEMO` e `REAL` na mesma agregação. | RF-57 |

## 8. Auditoria

| # | Critério | Req. |
|---|---|---|
| AC-60 | **Dado** uma tese encerrada, **quando** se abre a auditoria, **então** é possível reconstruir: por que a posição foi montada, quais premissas a sustentavam, quem contestou o quê e qual dado deveria ter disparado a reavaliação — com datas. | RF-55 |
| AC-61 | **Dado** qualquer linha de `audit_log`, **quando** se tenta alterá-la ou apagá-la pelo papel da aplicação, **então** a operação falha. | C7 |
| AC-62 | **Dado** um `run_id`, **quando** reexecutado, **então** as entradas exatas são reconstruídas e o resultado é reproduzido. | RF-56 |

## 9. Não funcionais

| # | Critério | Req. |
|---|---|---|
| AC-70 | Registro e consulta respondem em < 2 s; rodada de debate < 90 s; ciclo de Watchdog < 5 min. | RNF-03 |
| AC-71 | Sem chave de LLM configurada, Registrar e Vigiar continuam operando; Desafiar exibe indisponibilidade clara em vez de falhar em silêncio. | RNF-06 |
| AC-72 | Sem Postgres, a aplicação sobe em SQLite com aviso visível de degradação da busca semântica. | RNF-06 |
| AC-73 | `docker compose up` sobe a aplicação completa a partir de repositório limpo. | RNF-11 |
| AC-74 | A aplicação publicada é acessível por link com credencial de teste, e o repositório é privado. | RNF-02 |
| AC-75 | Nenhum segredo no repositório (varredura em CI). | RNF-07 |

## 10. Critérios da defesa (ensaio obrigatório no Sprint 8)

| # | Critério |
|---|---|
| AC-80 | A tese da Entrega 2 está registrada, persistida e navegável na plataforma publicada. |
| AC-81 | Registro ao vivo de uma tese nova, com um dado fornecido na hora, concluído em ≤ 10 minutos incluindo debate. |
| AC-82 | Qualquer número apresentado pode ter sua evidência aberta na hora, diante da banca. |
| AC-83 | Uma pergunta hostil sobre dimensionamento pode ser respondida rodando um cenário novo ao vivo. |
| AC-84 | O vídeo de 3 minutos demonstra as três funções do núcleo, não a interface. |
| AC-85 | O documento de 1 página responde às duas perguntas obrigatórias e declara o que ficou de fora e por quê. |
