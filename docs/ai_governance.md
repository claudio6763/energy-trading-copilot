# Governança de IA

## Onde há IA

| Função | Agente | Por quê |
|---|---|---|
| Redigir a apresentação da tese | Trader | Problema de linguagem |
| Construir o contra-argumento | Risco | Argumentação; não há função fechada para "premissa mais frágil" |
| Interpretar norma já recuperada | Regulatório | Leitura, ancorada em trecho citado |
| Explicar um alerta | Watchdog | Comunicação, não decisão |

## Onde **não** há IA

| Função | Por quê |
|---|---|
| VaR, P&L, cenários, add-ons | Precisam ser reprodutíveis e auditáveis |
| Verificação do limite de R$ 50 mi | Limite de risco é regra, não julgamento |
| Disparo de gatilho | O Watchdog precisa ser previsível às 3h da manhã |
| Veredito do debate | Função pura sobre o resultado do quant e do verificador |
| Freshness, hashes, trilha de auditoria | Integridade |
| **Qualquer número factual** | Princípio central do produto |

## Claim Verifier

Portão *fail-closed* entre a saída do LLM e o registro. Cinco checagens:

1. **Número órfão** — numeral no texto sem claim declarada correspondente.
2. **Lastro** — claim numérica/factual sem `evidence_id` é bloqueada.
3. **Existência** — o `evidence_id` precisa existir no banco.
4. **Data-base** — evidência posterior ao corte (`2026-08-14`) é bloqueada.
5. **Recomputação** — o valor afirmado tem de bater com o da evidência.

Número correto **por acaso** também é bloqueado se não tiver `evidence_id`.
Quando falta evidência, a interface mostra:

> Não disponível — evidência insuficiente.

## evidence_id

Gerado automaticamente em `create_evidence()`. Toda observação, ponto de curva,
trecho de documento e execução do motor quant produz um. Guarda: tipo, fonte,
localizador, trecho literal, valor, unidade, data-base, classificação e hash.

## Controle de data-base

Toda consulta de mercado filtra `as_of ≤ data-base do contexto`. Não há caminho
para look-ahead: está no repositório, não na consulta escrita à mão.

## Dados ausentes

Nunca viram zero nem estimativa silenciosa. As funções levantam
`MissingDataError` ou `InsufficientSampleError`, e a interface mostra o motivo.

## Prompt injection

Documentos recuperados são **dados não confiáveis**. `store.sanitize()` neutraliza
padrões de instrução ("ignore as instruções anteriores", "you are now") antes de
o trecho chegar ao prompt. Instrução dentro de PDF não altera as regras do sistema.

## Modo real e modo demonstração

Sem `ANTHROPIC_API_KEY`, os agentes usam roteiros determinísticos. A interface
mostra o aviso em toda tela de debate e o campo `mode` grava `DEMO` no banco e no
audit log. **Nenhuma saída demonstrativa é apresentada como IA.**

No modo real, o audit log registra: modelo, horário, agente, prompt, ferramentas,
evidências e resultado.

## Limitações

- O Claim Verifier detecta número órfão por varredura léxica; número escrito por
  extenso ("quarenta e sete por cento") escapa da detecção automática.
- O sistema garante que o número **veio da fonte declarada**; não garante que a
  fonte esteja correta.
- Máximo de 4 chamadas ao LLM por debate — respostas longas podem ser truncadas.
