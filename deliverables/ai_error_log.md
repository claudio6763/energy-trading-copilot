# Log de erros reais da IA durante o desenvolvimento

Registro honesto de falhas **efetivamente observadas** durante a construção,
com como foram detectadas e corrigidas. Nada aqui é hipotético.

## Erro 1 — VaR zero silencioso com dicionário de volatilidade vazio

- **Onde:** `src/copilot/quant/scenarios.py`, função `run_scenario`.
- **O que aconteceu:** o código gerado usava `if sigma_daily:`. Um dicionário
  vazio é falso em Python, então a função **pulava o cálculo de VaR inteiro** e
  devolvia `Decimal("0.00")` — indistinguível de "risco zero".
- **Por que é grave:** é exatamente o modo de falha que o produto existe para
  impedir. Ausência de dado virando zero, em silêncio, num número de risco.
- **Como foi detectado:** teste
  `tests/unit/test_scenarios.py::test_cenario_sem_volatilidade_declarada`,
  escrito para exigir `MissingDataError`. Falhou com `DID NOT RAISE`.
- **Correção:** `if sigma_daily is not None:`. `None` = não pedido; `{}` = pedido
  e sem dado, que falha alto.
- **Status:** corrigido e coberto por teste.

## Erro 2 — tolerância numérica irreal em teste de VaR

- **Onde:** `tests/unit/test_var.py::test_var_parametrico_composicao_da_formula`.
- **O que aconteceu:** o teste comparava o VaR com tolerância relativa de `1e-9`,
  mas o resultado é quantizado em centavos de propósito. Diferença de R$ 0,0025
  reprovava um cálculo correto.
- **Por que importa:** um teste que reprova código correto é pior que nenhum
  teste — ensina a ignorar falha vermelha.
- **Como foi detectado:** execução da suíte; 37 passaram, 1 falhou.
- **Correção:** tolerância absoluta de um centavo, mais uma âncora exata
  (`Decimal("32897.07")`) para travar regressão.
- **Status:** corrigido.

## Erro 3 — colisão de nome entre parâmetro de `fetch` e de `parse`

- **Onde:** `src/copilot/ingest/adapters/base.py`.
- **O que aconteceu:** `parse(payload, ..., **kwargs)` com `payload` também em
  `kwargs` (usado para reprocessar snapshot sem rede) causava
  `TypeError: got multiple values for argument 'payload'`.
- **Como foi detectado:** teste
  `test_adapters.py::test_oni_offline_usa_payload_injetado`.
- **Correção:** o parâmetro posicional de `parse` passou a se chamar `raw`.
- **Status:** corrigido.

## Erro 4 — schema SQLite com expressão em constraint UNIQUE

- **Onde:** `src/database/schema.sql`.
- **O que aconteceu:** `UNIQUE (metric, ref_date, as_of, COALESCE(model_run,''))`.
  O SQLite recusa expressão em UNIQUE: `expressions prohibited in PRIMARY KEY and
  UNIQUE constraints`.
- **Como foi detectado:** primeira execução de `init_db()`.
- **Correção:** `model_run TEXT NOT NULL DEFAULT ''` e UNIQUE sobre a coluna.
- **Status:** corrigido.

## Padrão observado

Os quatro erros têm a mesma assinatura: **a IA produz código que parece correto e
falha em silêncio no caso de borda**. Nenhum foi pego por leitura — todos por
teste que exigia comportamento explícito em caso de dado ausente ou inválido.

É a razão de o produto ser *fail-closed* por princípio, e não por preferência.
