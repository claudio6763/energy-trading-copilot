# Respostas às questões obrigatórias sobre IA

## 1. Como o sistema impede números inventados

Cinco camadas, todas verificáveis no código e nos testes.

**Privação.** O agente recebe um bloco `DADOS` em JSON com os únicos números
permitidos. O prompt de sistema diz explicitamente: nunca escreva um número que
não esteja nos DADOS.

**Ferramentas como única fonte.** Números só nascem de três origens: consulta ao
banco, execução do motor quantitativo, ou entrada humana em arquivo. Cada uma
cria uma linha em `evidence` **antes** de o número existir para o sistema.

**Placeholders.** `resolve_placeholders()` falha visivelmente quando o marcador
não tem evidência, em vez de gerar texto plausível.

**Claim Verifier (`src/services/claim_verifier.py`).** Portão *fail-closed* com
cinco checagens: número órfão no texto, lastro (`evidence_id`), existência da
evidência no banco, data-base posterior ao corte de 14/08/2026, e recomputação do
valor contra a evidência. Bloqueio impede a persistência e leva o veredito a
`NAO_OPERAR_DADOS_INSUFICIENTES`.

**Prova visível.** Todo número na interface mostra `evidence_id`, fonte e
data-base. Quando falta evidência: *"Não disponível — evidência insuficiente."*

O que isso **não** resolve, declarado: o sistema garante que o número veio da
fonte declarada; não garante que a fonte esteja correta.

## 2. Onde usa IA

- Redigir a apresentação da tese (Agente Trader).
- Construir o contra-argumento e apontar a premissa mais frágil (Agente de Risco).
- Interpretar norma **já recuperada** pelo RAG (Agente Regulatório).
- Explicar por que um alerta importa.

Critério: problema de linguagem, julgamento ou geração de hipótese.

## 3. Onde **não** usa IA

- VaR, P&L, cenários, add-ons, NPV — Python determinístico.
- Verificação do limite de R$ 50 milhões — função pura, testada na fronteira.
- Disparo de gatilho — `evaluate_operator()`, determinística.
- Veredito do debate — `decide_verdict()`, função pura sobre o resultado do quant
  e do verificador.
- Freshness, hashes, `evidence_id`, trilha de auditoria.

Critério: aritmética, regra ou limite. Um VaR não determinístico é indefensável
perante risco, e o Watchdog precisa ser previsível às 3h da manhã.

## 4. Qual erro real da IA foi identificado

Ver `deliverables/ai_error_log.md`. O caso mais relevante: durante o
desenvolvimento assistido, a função de cenários aceitava `sigma_daily={}` (dicionário
vazio) e devolvia **VaR igual a zero** em silêncio, em vez de sinalizar dado ausente.

## 5. Como foi detectado

Por um teste escrito antes da correção
(`tests/unit/test_scenarios.py::test_cenario_sem_volatilidade_declarada`), que
esperava `MissingDataError` e recebeu sucesso com zero. O teste falhou e expôs o
comportamento.

## 6. Como foi corrigido

Trocando `if sigma_daily:` por `if sigma_daily is not None:` em
`src/copilot/quant/scenarios.py`. A distinção passou a ser explícita: `None`
significa "VaR não pedido"; `{}` significa "pedido e sem dado", e falha alto.
O teste passou a acompanhar a regressão.
