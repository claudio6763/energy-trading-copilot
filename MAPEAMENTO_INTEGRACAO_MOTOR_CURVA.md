# Mapeamento de integração — Copiloto × `motor_curva`

Documento de análise. Nenhum código foi escrito. Aguarda aprovação antes da Fatia 1.

Nota de escopo: o motor está em `motor_curva/`, não em `projeto_curva_v4/` (nome do prompt original) — já é um subdiretório deste mesmo repositório, então não é necessário `/add-dir`.

---

## 0. Achado estrutural prévio, que muda a costura

O copiloto hoje tem **duas implementações paralelas** para tese/persistência, e isso importa para onde a integração deve encostar:

| | Stack viva (o que `app.py` realmente usa) | Stack adormecida |
|---|---|---|
| Local | `src/database/` + `src/services/` | `src/copilot/db/`, `src/copilot/contracts/` |
| Persistência | `sqlite3` puro, schema em `src/database/schema.sql` | SQLAlchemy 2.x + Alembic (`migrations/versions/0001_initial_schema.py`) |
| Modelos | dicts/`sqlite3.Row` | Pydantic v2 + `Mapped` |
| Roda hoje? | Sim — `data/copilot.db` existe em disco (274 KB), sobrevive a restart | Não — zero chamadas em runtime a partir de `app.py` |

Isso é uma decisão documentada (ADR-011/012, `SPRINT_STATUS.md`), não um acidente. **Conclusão para este mapeamento: a integração deve encostar na stack viva (`src/services/thesis_service.py`, `src/database/repositories.py`), não na SQLAlchemy adormecida.** Migrar para a stack adormecida seria refatoração do copiloto — exatamente o que você pediu para não fazer a dois dias da entrega.

Uma exceção parcial: `src/services/risk_service.py` já importa `copilot.quant.*` (motor determinístico de VaR/cenários da própria stack adormecida) — ou seja, parte do "motor" que o copiloto já tem embutido (`src/copilot/quant/`) resolve um problema adjacente ao que `motor_curva` resolve, com metodologia própria (VaR 95%/21 du, portfolio consolidado — resolução provisória PR-03 em `SPRINT_STATUS.md`). **Isso é uma sobreposição a esclarecer com você (ver §6, pergunta 1) antes de escrever código**: o `risk_service.py` interno continua calculando um VaR próprio (usado pelo botão "Calcular risco e cenários" e pelo Watchdog) independente do VaR que `motor_curva/src/risco.py` calcula. Os dois não devem divergir silenciosamente no mesmo registro de tese.

---

## 1. Inventário do motor

Seu palpite estava quase certo. Correções, com base na leitura de `motor_curva/src/cli.py::cmd_run` (o único lugar que efetivamente encadeia os módulos):

**Núcleo confirmado** (todos realmente chamados por `cmd_run`, produzem número): `ingest`, `parse_infopld`, `parse_ipdo`, `boletins`, `sazonalidade`, `ancora`, `cenarios`, `premio`, `curva`, `risco`, `book`, `manifesto`, `qualidade`, `config`.

**Duas correções ao seu palpite:**
- **`posicao.py` entra no núcleo.** É legado (dimensionamento de posição única, pré-book), mas `cmd_run` ainda o chama (`cli.py:479-499`) e o resultado alimenta `resumo_execucao.json["var_unitario_referencia"]` — um VaR unitário por MWh usado como referência/cross-check do book. Se você não vai usar esse campo na tese, pode ignorá-lo na costura, mas o módulo continua sendo núcleo, não periferia.
- **`fontes.py` é uma categoria à parte: núcleo de *aquisição*, não de *cálculo*.** É o cliente CKAN que baixa dado bruto da CCEE/ONS (I/O de rede). O copiloto não deve chamá-lo — ele consome o **resultado já processado** de uma rodada do motor, não dispara novas rodadas de ingestão. Deixe-o fora do que o copiloto importa, mas não é "periferia" no sentido de excel/apresentação — é uma etapa anterior, fora do escopo da integração.

**Periferia confirmada, com dois acréscimos ao seu palpite:**
`excel_modelo.py`, `excel_book.py`, `excel_boletins.py`, `cli.py` (como ponto de entrada — o *corpo* de `cmd_run` é o que migra, não o arquivo), `apresentacao.py`, `importar.py`, `vba/` — **mais `saidas.py`** (gera `entrega_2_curva.xlsx` e os PNGs) **e `relatorio.py`** (gera `entrega_2.md`). Nenhum dos dois é núcleo — são formatação de saída para humano, redundante com o que a tela de registro vai mostrar.

**Módulo órfão, fora de ambas as listas:** `decks.py` (inspeção de decks NEWAVE/DECOMP) não é importado em nenhum lugar de `cli.py` — não está no caminho de execução de `cmd_run` hoje. Não importe.

---

## 2. A costura

`cmd_run` tem 1078 linhas. A parte que produz número (portável) é `cli.py:184-778`: ingest → qualidade → sazonalidade → boletins → curva → risco → book/posição → montagem do contexto (`ctx`). Essa faixa só toca DataFrames/dicts em memória e só chama módulos de `src/` — nunca argparse, nunca grava arquivo (com duas exceções pontuais, ver abaixo).

Proposta de assinatura, próxima da sua:

```python
def avaliar(
    submercado: str,
    as_of: date,
    ref_mercado: dict[str, float],
    limite_var: float,
    *,
    raw_dir: Path | None = None,   # None = usa fixtures (motor_curva/fixtures)
    dir_boletins: Path | None = None,
    fim_horizonte: date | None = None,  # None = usa config.FIM_HORIZONTE
) -> ResultadoAvaliacao
```

`ResultadoAvaliacao` = a mesma estrutura de `resumo_execucao.json` (§3) + os DataFrames-chave (`cb` = curva mensal, `sinal`, `book.pernas`, `book.resumo`) — o que hoje só existe como variáveis locais dentro de `cmd_run` e nunca sai da função.

### O que migra (linha a linha, por bloco)

| Bloco | Linhas | Migra? |
|---|---|---|
| Ingest PLD/ENA/EAR/MVE | `184-228` | Sim, tal qual |
| Checagem de qualidade | `230-242` | Sim, mas `raise SystemExit` (`240`) vira exceção de domínio |
| Sazonalidade (walk-forward) | `244-263` | Sim, tal qual |
| Ingestão de boletins InfoPLD/IPDO | `265-279` | Sim, tal qual |
| Construção da curva | `281-427` | Sim, tal qual |
| VaR (nível amortecido + challengers) | `430-476` | Sim, tal qual |
| Posição legada (única) | `478-539` | Sim — mantém `var_unitario_referencia` |
| Book multi-perna | `541-663` | Sim, **exceto** as duas escritas inline em CSV (`578`, `642-651`) — essas viram responsabilidade explícita de quem chama `avaliar`, não da função de cálculo |
| Montagem de `ctx`/manifesto | `665-778` | Sim, tal qual |
| Escrita de arquivos (CSV/JSON/XLSX/MD/print) | `780-888` | **Não migra.** Fica em `cli.py`, que passa a chamar `avaliar()` e depois escrever os arquivos a partir do retorno — CLI e serviço convergem no mesmo resultado, sem duplicar lógica |
| Excel (`excel_modelo`, `excel_book`, `excel_boletins`) | `810-881` | Não migra — periferia |
| `saidas.gerar_planilha/gerar_graficos`, `relatorio.gerar` | `884-886` | Não migra — periferia |
| `argparse`/`main` | `168-170`, `1044-1074` | Não migra — CLI |
| Geradores de texto narrativo (`_tese`, `_gatilhos`, `_invalidam`, `_limitacoes`) | `892-964` | Opcional — são só texto (não número), o copiloto pode reaproveitá-los como *rascunho* que o trader edita, ou ignorá-los e deixar o Desafiar/LLM redigir. Decisão sua, não bloqueia a costura. |

### Três ajustes de portabilidade que a extração precisa fazer (senão o `avaliar()` não é reutilizável fora do case atual)

1. **`date.today()` → `as_of` explícito.** `cli.py:171-182` decide `DEFINITIVO`/`PROVISORIO` comparando `date.today()` com `DATA_CORTE`. Uma função de serviço não pode depender de relógio de parede (viola P7 do seu CLAUDE.md). `as_of` vira parâmetro.
2. **`DATA_CORTE`/`FIM_HORIZONTE` hardcoded em `config.py:23-24` → parâmetros.** Hoje são constantes de módulo específicas deste case. Precisam ser injetáveis para a tese "ao vivo" da defesa (dado novo, corte novo).
3. **`PREMISSAS.ref_mercado` hardcoded (`config.py:125-127`) → parâmetro `ref_mercado: dict`.** Já está na sua assinatura proposta — bom, porque hoje é um dict estático de marcações de mesa, sem fonte declarada. Isso também resolve, de quebra, uma pendência do próprio motor (P10-adjacente: hoje esse dict não tem proveniência).

Todos os `raise SystemExit(...)` dentro da faixa portável (linhas `187,197,202,240,251,285,439`) precisam virar exceções tipadas (`ex.: FonteObrigatoriaFaltando`, `CoberturaInsuficiente`) — a CLI captura e converte pra saída de processo; o serviço deixa a exceção subir, e é isso que vira mensagem de erro na tela de registro em vez de crash silencioso.

---

## 3. Mapa campo a campo

Convenção: OBSERVADO (dado direto de fonte externa), CALCULADO (saída determinística do motor), PREMISSA (parâmetro declarado em `config.py`, sem cálculo), GAP (o motor não produz isso — o copiloto/trader precisa suprir).

| Campo da tese (form atual / RF-xx) | Origem no motor | Rótulo |
|---|---|---|
| Submercado | `resumo.submercado` | OBSERVADO (parâmetro de entrada) |
| Produto | `PREMISSAS.produto` ("Convencional Flat mensal SE/CO") | PREMISSA (config estático) |
| Dimensionamento por vértice (MWmed) | `book_pernas.csv`, coluna `mwmed`, uma linha por mês (5 pernas na rodada atual: Ago 43, Set 188, Out 119, Nov 74, Dez 62) | CALCULADO |
| Dimensionamento agregado (MWmed bruto/líquido) | `resumo.book.mwmed_bruto` / `mwmed_liquido_abs` | CALCULADO |
| Preço de entrada por vértice | `book_pernas.csv`, coluna `preco_entrada` | CALCULADO (saída do sinal, não digitado) |
| Início/fim de entrega | `curva_mensal_base_seco_umido.csv`, `mes_ref` mín/máx do book | CALCULADO |
| Direção (COMPRAR/VENDER) | `book_pernas.csv`, coluna `lado` ("V"→VENDER); ou `book_dimensionamento_risco.csv`, coluna `acao` | CALCULADO |
| Consumo do limite de VaR | `resumo.book.consumo_limite` (ex.: 0,5979 = 59,79%) | CALCULADO |
| VaR total (R$) | `resumo.book.var_total` | CALCULADO |
| ES total (R$) | `resumo.book.es_total` | CALCULADO |
| VPL | `resumo.book.vpl` | CALCULADO |
| Resultado esperado — baixo | `resumo.book.pnl_Entrega_Seco` (= `pior_cenario` na rodada atual) | CALCULADO |
| Resultado esperado — central | `resumo.book.pnl_Entrega_Esperado` | CALCULADO |
| Resultado esperado — alto | `resumo.book.pnl_Entrega_Umido` | CALCULADO |
| Premissa de cenário (trajetória hidrológica) | `parse_infopld.extrair` / `ancora.selecionar_cenarios`; fonte = PDF InfoPLD + página, hash via `manifesto` | OBSERVADO |
| k_seco / k_umido (multiplicador de cenário) | `resumo.k_seco` / `resumo.k_umido` | CALCULADO |
| Meia-vida de sazonalidade escolhida | `resumo.meia_vida_dias` | CALCULADO |
| Nível do prêmio de mercado (R$/MWh) | `resumo.premio_nivel_rs_mwh` | CALCULADO |
| VaR por MWh (insumo de risco) | `resumo.var_preco_rs_mwh` | CALCULADO |
| Data-base (`as_of`) | parâmetro de entrada `data_corte` | OBSERVADO |
| Status da rodada (DEFINITIVO/PROVISÓRIO/FIXTURE) | `resumo.status` + `resumo.motivo` | CALCULADO (governa se o número pode virar tese real ou só DEMO) |
| Fonte/proveniência de cada arquivo de entrada | `data_manifest.json`, item por `arquivo`, com `sha256` e `baixado_em_utc` | OBSERVADO (evidência com hash) |
| Data de reavaliação | — | **GAP.** O motor não recomenda uma data. Sugestão: próxima publicação prevista do InfoPLD (mensal) — decisão do trader, não do motor. |
| Gatilho de saída (metric/operator/threshold estruturado) | — | **GAP.** O motor tem sinais internos que *poderiam* virar gatilho (ex.: `PREMISSAS.limiar_sinal_rs = 15.0`, `book_dimensionamento_risco.csv` coluna `risco_vinculante`/`restricao`), mas não emite um objeto de gatilho pronto. Precisa de tradução manual ou de uma etapa nova na costura (fora do escopo de "importar, não reescrever" — decisão sua, ver §6). |
| O que invalida a tese | — | **GAP.** `ancora.py` tem `alerta_ordenacao` (Seco/Esperado/Úmido fora de ordem) e `qualidade.checar_risco`/`reconciliar` (falha de dado), que são bons candidatos a condição de invalidação, mas de novo não saem como texto/regra pronta. |
| Contraparte | — | GAP — não se aplica ao motor (é um dado de negociação, não de modelagem). Fica sempre vazio. |

Onde o form pede **um único** volume/preço/janela de entrega e o motor produz **cinco vértices** com volume e preço diferentes por mês, isso é uma incompatibilidade de modelo, não um gap de dado — ver §4 e §5 (Fatia 0 trata isso explicitamente).

---

## 4. Lacunas do copiloto

**Persistência de verdade** — já existe e já sobrevive a restart (`data/copilot.db` em disco, stack `sqlite3` viva). Não é lacuna. O que falta é *disciplina de schema*: o `schema.sql` é editado à mão, sem Alembic — o que contraria a seção 5 do seu CLAUDE.md ("Toda mudança de schema passa por migração Alembic"). Pré-existente, não introduzido por esta integração; sinalizo mas não recomendo mexer sob prazo de dois dias.

**Navegação pelo histórico** — existe (aba "Consultar" + Dashboard). Funcional o suficiente para a defesa. Um detalhe menor: `thesis_service.lineage()` (histórico de versões por `parent_id`) existe no serviço mas não é chamado por `app.py` — não é bloqueante.

**Fluxo de registro ao vivo — a maior lacuna, confirmada.** O formulário "Cadastrar" de hoje (`app.py:127-166`) pede **todo número por digitação manual**: volume, preço, os três valores do resultado esperado. Não há nenhuma chamada a `TS.add_position`, `TS.add_trigger` ou `TS.add_risk` em `app.py` — só `TS.create_thesis` (a tese em si) e `TS.add_assumption` (premissa, via subformulário). As funções de serviço para posição e gatilho **já existem, já são testadas, já exigem `evidence_id`** — só não têm UI. Isso é exatamente o alvo da Fatia 1.

Achado adicional, mais estrutural que a UI: **`TS.create_thesis` não recebe `evidence_id` nenhum.** Volume, preço e o intervalo de resultado esperado, quando gravados hoje, entram na tabela `theses` **sem qualquer vínculo de evidência** — mesmo que a UI algum dia os pré-preenchesse com número do motor, o valor cairia numa coluna sem rastro de proveniência. Isso viola P6 do seu CLAUDE.md para esses campos especificamente (premissas e posições, por outro lado, já exigem `evidence_id` corretamente). A Fatia 1 precisa decidir: mover esses campos para dentro de `Position`/`Assumption` (que já têm evidência), ou estender `create_thesis`/a tabela `theses` para aceitar evidência por campo. Recomendo a primeira opção — é o que o schema já modela (RF-03: posição é entidade própria) e evita mexer no formato da tabela `theses`.

**Vigilância automática** — o Watchdog (`watchdog_service.py`) está implementado e funciona (freshness, gatilhos, premissas, VaR), mas roda sob demanda (botão) ou via script avulso — sem agendador de verdade (o RF-30 pede execução periódica). Mais relevante para esta integração: o Watchdog reavalia contra `market_observations`/`forward_curves` já gravados no banco do copiloto, **não** contra uma nova rodada do `motor_curva`. Não há hoje uma ponte que, ao rodar `avaliar()` de novo, alimente essas tabelas com o resultado fresco. Sem essa ponte, o Watchdog nunca vê o motor recalcular — fica cego à origem de verdade dos números que ele deveria vigiar.

---

## 5. Plano em fatias verticais

### Fatia 0 — sem código, hoje

Registrar a tese da Entrega 2 usando exclusivamente o formulário "Cadastrar" que já existe, com os números abaixo, lidos de `motor_curva/outputs/resumo_execucao.json` e dos CSVs em `motor_curva/outputs/` (rodada atual, `submercado=SE`, `status=DEFINITIVO`).

O formulário pede posição única; o motor produz 5 vértices. Para a Fatia 0, use os agregados abaixo e registre o detalhe por vértice como texto no Resumo (a tabela completa) — a Fatia 1 substitui isso por 5 `Position` reais, uma por perna.

| Campo do formulário | Valor a digitar | Origem |
|---|---|---|
| Título | ex.: "Venda flat SE/CO Ago–Dez/26 sobre prêmio InfoPLD (Entrega 2)" | — |
| Direção | **VENDER** | `book_pernas.csv`, todas as 5 pernas com `lado=V` |
| Resumo | Narrativa própria + colar a tabela de `book_pernas.csv` (perna, mês, MWmed, preço de entrada) para não perder o detalhe por vértice nesta fatia | `book_pernas.csv` |
| Produto | **Convencional Flat mensal SE/CO** | `PREMISSAS.produto` |
| Submercado | **SE/CO** | `resumo.submercado = "SE"` |
| Fonte de energia | CONVENCIONAL (default já correto) | — |
| Início da entrega | **2026-08-01** | `curva_mensal_base_seco_umido.csv`, primeiro `mes_ref` |
| Fim da entrega | **2026-12-31** | `curva_mensal_base_seco_umido.csv`, último `mes_ref` |
| Volume (MWmed) | **486** (soma bruta das 5 pernas: 43+188+119+74+62) | `resumo.book.mwmed_bruto` |
| Preço de referência (R$/MWh) | **222,05** (média das 5 pernas ponderada por MWmed — simplificação só desta fatia; a Fatia 1 grava os 5 preços individualmente) | calculado a partir de `book_pernas.csv` |
| Data do preço | **2026-08-14** | `DATA_CORTE` / `settings.data_cut_off` |
| Data de reavaliação | **2026-09-15** (próxima publicação InfoPLD estimada — não é saída do motor, é convenção sua) | GAP — decisão do trader |
| Resultado esperado — baixo (R$) | **-19.691.794,06** | `resumo.book.pnl_Entrega_Seco` |
| Resultado esperado — central (R$) | **17.559.624,24** | `resumo.book.pnl_Entrega_Esperado` |
| Resultado esperado — alto (R$) | **54.814.228,80** | `resumo.book.pnl_Entrega_Umido` |
| Condição de saída | ex.: "Prêmio de mercado sobre a curva fundamental cair abaixo de R$ 15,00/MWh (limiar do motor) ou consumo do limite de VaR ultrapassar 80%." | rascunho seu — motor não emite texto de gatilho (GAP §3) |
| Condição de invalidação | ex.: "Trajetória InfoPLD 'Seco' deixar de ser a mais seca elegível (alerta de ordenação do motor), ou falha de cobertura em PLD/ENA/EAR/InfoPLD (checagem de qualidade do motor)." | rascunho seu — idem |
| Responsável | seu nome | — |

Depois de salvar, use o subformulário "Adicionar premissa" uma vez, com:
- Enunciado: "Prêmio de mercado sobre a curva fundamental (R$ 39,01/MWh) supera o limiar mínimo de sinal do motor (R$ 15,00/MWh), sustentando a tese vendedora."
- Métrica vigiável: `premio_mercado_rs_mwh`
- Esperado: **39,01** (`resumo.premio_nivel_rs_mwh`)
- Tolerância mínima: **15,00** (`PREMISSAS.limiar_sinal_rs`, abaixo disso a tese perde sustentação)
- Tolerância máxima: fica a seu critério — o motor não declara um teto (sinalizar como PREMISSA sua, não do motor)

Contexto para citar no Resumo, útil para a defesa: VaR total R$ 29.892.814,54 = 59,79% do limite de R$ 50MM (`resumo.book.consumo_limite`), VPL R$ 3.670.973,69, k_seco 1,6066 / k_umido 0,8465, meia-vida de sazonalidade 365 dias.

Isso atende o requisito de verificação hoje, com rastreabilidade explicada em texto (já que `create_thesis` ainda não grava `evidence_id` por campo — Fatia 1 resolve isso).

### Fatias com código (ordem por redução de risco)

1. **Fatia 1 — extrair `avaliar()` + registrar com número vindo do motor, com evidência real.** Escopo já definido no seu segundo prompt: extração do serviço (§2), modelo de dados por campo com natureza+origem+hash, tela que pré-preenche a partir de `avaliar()`, persistência sobrevivendo a restart. Resolve a lacuna de `evidence_id` ausente em `create_thesis` (§4) migrando volume/preço/resultado esperado para `Position` (que já exige evidência) em vez de campos soltos em `theses`. Sem Desafiar/Vigiar.
2. **Fatia 2 — múltiplas posições (uma por vértice).** Usa `add_position` 5x (uma por perna do book), cada uma com seu próprio `evidence_id` apontando para a linha do `data_manifest.json` que originou aquele mês. Resolve o descompasso "form pede 1 posição, motor produz 5" identificado em §3/§5.
3. **Fatia 3 — gatilhos estruturados a partir do motor.** Traduz os candidatos identificados em §3 (limiar de sinal, alerta de ordenação de cenário, falhas de qualidade) em `TriggerRule` reais via `add_trigger`, fechando o gap de "gatilho em texto livre" (RF-06/07).
4. **Fatia 4 — Desafiar sobre a tese com número do motor.** `debate_service` já existe e funciona; o trabalho aqui é garantir que o contexto do debate (`build_context`) enxergue as `Position`s da Fatia 2 (hoje ele só computa risco/cenário se `positions` não estiver vazio — com Fatia 1/2 isso passa a acontecer automaticamente).
5. **Fatia 5 — ponte Vigiar ↔ motor.** Job (manual ou agendado) que roda `avaliar()` de novo com um novo `as_of` e grava o resultado em `market_observations`/`forward_curves`, para que o Watchdog (já funcional) tenha algo fresco do motor para comparar contra os gatilhos e premissas da tese.
6. **Fatia 6 (opcional, "Should")** — exportação completa da tese (RF-12) e visão de lineage/versão (`thesis_service.lineage()`, já existe no serviço, sem UI).

---

## 6. Perguntas antes de eu escrever qualquer código

1. `src/services/risk_service.py` já calcula um VaR próprio (`copilot.quant`, metodologia PR-03: 95%/21 du/portfolio consolidado) para o botão "Calcular risco e cenários" e para o Watchdog. `motor_curva/src/risco.py` calcula VaR com metodologia diferente (nível dessazonalizado amortecido, soma entre meses com correlação 1, ver §5 do inventário do motor). Quando a tese vier do `motor_curva`, o VaR que conta para o limite de R$ 50MM e para o veredito do Desafiar é o do `motor_curva` (`resumo.book.var_total`) ou o `risk_service.py` deve ser chamado para recalcular a partir das posições? Se forem os dois, o que fazer se divergirem?
2. Para o gatilho estruturado (Fatia 3): tudo bem eu propor a tradução dos sinais internos do motor (limiar de sinal, alerta de ordenação de cenário) em `metric_key`/`operator`/`threshold`, ou você quer definir pessoalmente quais viram gatilho formal antes de eu implementar?
3. Confirma que a Fatia 0 pode ficar com o "preço de referência" agregado como média ponderada (simplificação só para o registro imediato), sabendo que a Fatia 2 substitui isso por preço por vértice?
