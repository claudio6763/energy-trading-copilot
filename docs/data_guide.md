# Guia de dados

## Classificações

Toda observação carrega uma classificação, visível na interface:

| Classificação | Significa |
|---|---|
| `observado` | Medido e publicado por fonte oficial |
| `projetado` | Saída de modelo (previsão) |
| `negociado` | Preço de transação ou cotação firme |
| `indicativo` | Cotação de referência, sem negócio fechado |
| `proxy` | Substituto declarado (ex.: PLD no lugar de forward) |
| `manual` | Digitado pelo operador |
| `demonstracao` | Sintético, do seed. **Nunca é recomendação real** |

## Importar CSV/XLSX

**Dados e fontes → Observações → Importar.**

### Observações

```csv
metric_key,ref_date,value,unit,quality
ear_sudeste_pct,2026-08-13,52.4,%,OK
pld_se_semanal,2026-08-13,231.40,R$/MWh,OK
```

Aceita nomes em português: `metrica`, `data`, `valor`, `unidade`, `qualidade`.
Números aceitam `1.234,56` e `1234.56`.

### Curva forward

```csv
tenor,delivery_start,delivery_end,price,submarket
A+1,2027-01-01,2027-12-31,195.00,SE/CO
A+2,2028-01-01,2028-12-31,188.50,SE/CO
```

A curva exige: produto, fonte de energia, submercado, início e fim da entrega,
preço, unidade, tipo de cotação, data-base e fonte.

### Eventos e gatilhos

```csv
metric,operator,threshold,unit,rule_type,severity
fwd_se_a1_conv,>=,260,R$/MWh,SAIDA,CRITICO
ear_sudeste_pct,<,45,%,INVALIDACAO,CRITICO
```

## PLD e CMO

**PLD e CMO não são curva forward negociada.** São preços de curto prazo
formados por modelo de despacho. Se usados como referência de longo prazo:

1. cadastre a curva com `origin=PROXY_SPOT`;
2. informe `proxy_of` (qual preço está sendo substituído);
3. o sistema aplica o add-on de proxy de 25% no risco.

Tentar cadastrar curva com "PLD" ou "CMO" no nome como `NEGOCIADA` é recusado.

## Arquivo rejeitado

A validação é estrita e diz linha e coluna. Erros comuns:

| Erro | Correção |
|---|---|
| `colunas obrigatorias ausentes` | Confira o cabeçalho da primeira linha |
| `obrigatorio e veio vazio` | Campo vazio não vira zero: preencha ou remova a linha |
| `data nao reconhecida` | Use `AAAA-MM-DD` ou `DD/MM/AAAA` |
| `abaixo do minimo` | Preço negativo é recusado |
| `tenor repetido` | Curva não pode ter dois pontos com o mesmo tenor |

## Freshness

**Dados e fontes → Observações** mostra a idade de cada métrica. Acima de 10 dias
a fonte é marcada atrasada e o Watchdog gera alerta de cobertura. Ausência de
dado **não** é premissa válida.

## Data de corte

O corte oficial é `2026-08-14` (`DATA_CUT_OFF` no `.env`). Nenhuma consulta
devolve dado posterior. Isso está no repositório, não na consulta — não há como
esquecer.

## Congelar snapshot

```bash
python scripts/freeze_case_snapshot.py --as-of 2026-08-14
```

Grava o estado dos dados naquela data-base em `data/snapshots/`, com hash.

## Substituir dados demonstrativos por reais

1. `python scripts/seed_demo.py --reset` limpa o dataset demonstrativo.
2. Importe os arquivos reais (CSV/XLSX) por **Dados e fontes**.
3. Confira em **Integrações** que o status saiu de `DEMO`.
4. Rode `python scripts/verify_agent.py` de novo.

Fontes licenciadas (BBCE, DCIDE) só com autorização escrita. Ficam bloqueadas
por padrão.
