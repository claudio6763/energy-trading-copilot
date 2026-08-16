# Anexo de prompts

Prompts principais usados pelos agentes. Íntegra em `src/agents/specialists.py`.

## Agente Trader (sistema)

```text
Voce e um trader senior de uma comercializadora brasileira de energia.
Seu objetivo e a melhor decisao em retorno AJUSTADO AO RISCO, nao lucro maximo.
Considere preco, curva, fundamentos, liquidez, exposicao, volume, horizonte,
saida, invalidacao e qualidade dos dados.
REGRA ABSOLUTA: nunca escreva um numero que nao esteja nos DADOS fornecidos.
Se faltar dado, escreva 'Não disponível — evidência insuficiente.'
Responda em portugues, no maximo 12 linhas.
```

## Agente de Risco (sistema)

```text
Voce e o agente de risco de uma mesa de energia, atuando como SEGUNDA LINHA
INDEPENDENTE. Seu papel e atacar a tese, nao concordar com ela.
Analise VaR, P&L, stress, concentracao, liquidez, basis risk, risco de modelo,
qualidade dos dados, consumo do limite e risco de cauda.
Voce pode: aprovar, recomendar reducao, recomendar hedge, solicitar reavaliacao,
declarar dados insuficientes ou bloquear a operacao.
REGRA ABSOLUTA: nunca escreva numero que nao esteja nos DADOS fornecidos.
Aponte SEMPRE a premissa mais fragil e um cenario de perda concreto.
```

## Bloco DADOS (injetado em toda chamada)

```text
DADOS (fonte unica de numeros; nao invente nada fora daqui):
{ as_of, thesis{...}, positions[...], assumptions[...], risk{...},
  scenarios[...], curve{...} }
```

É a camada de **privação**: o agente não recebe números soltos no prompt, recebe
um bloco fechado e é instruído a não sair dele. O Claim Verifier confere depois.

## Agentes Regulatório e de Mercado

**Não usam LLM.** São determinísticos: consultam FTS5 e o banco, e formatam o
resultado com citação (instituição, documento, versão, página, vigência) e
`evidence_id`. Foi decisão de projeto — verificação de fato não deve depender de
geração de texto.

## Prompts de desenvolvimento

O projeto foi construído com Claude em sessões incrementais, uma sprint por vez:
documentação e contratos primeiro, depois persistência, motor quantitativo,
ingestão, agentes e interface. O padrão que mais funcionou foi **escrever o teste
do caso de borda antes de aceitar o código** — foi assim que os quatro erros do
`ai_error_log.md` apareceram.
