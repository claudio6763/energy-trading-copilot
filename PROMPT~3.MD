# Prompt final — Copiloto do trader, Entrega 1 com a Entrega 2 dentro

> Salve este arquivo em `C:\projetos\energy-copilot-v2\` e no Claude Code digite:
> `Leia PROMPT_FINAL_COPILOTO.md e execute até o fim.`
>
> Garanta que ele enxerga o motor:
> `/add-dir C:\Users\claud\OneDrive\Área de Trabalho\projeto_curva_v4`

---

Este é o escopo completo. Já combinamos o desenho; aqui está consolidado para
você executar sem parar a cada passo. Leia tudo antes de começar.

## O que estamos entregando

Processo seletivo para Trader II numa mesa de energia. Prazo: **segunda 17/08
às 10h**. Defesa presencial 18 ou 19/08, 60 minutos.

Três entregas. Duas estão neste repositório:

- **Entrega 1** — copiloto de decisão da mesa, protótipo funcional publicado
- **Entrega 2** — proposta de posição, cujo motor quantitativo é o
  `projeto_curva_v4`

O case exige que **a tese da Entrega 2 viva dentro da ferramenta da Entrega 1**.
Na defesa eles vão abrir o registro, navegar por ele e **pedir que eu registre
uma tese nova ao vivo, com um dado que darão na hora**.

Hoje o copiloto roda mas a tela de cadastrar tese é um formulário de texto sem
book. Numa mesa, tese **é posição**: sem ladder, sem dimensionamento e sem
risco, é opinião. É isso que estamos consertando.

## Critério de avaliação, para você calibrar decisões

| peso | critério |
|---|---|
| 35% | proposta de posição: tese, dimensionamento e disciplina de risco |
| 30% | copiloto: funciona, resolve o problema certo, IA aplicada com critério |
| 20% | produto estruturado (fora deste repositório) |
| 15% | postura na defesa: capacidade de revisar diante de evidência nova |

Texto literal do case: *"preferimos três funções que funcionam a dez que
abrem"*. Na dúvida entre profundidade e superfície, escolha profundidade.

---

# Parte 1 — O motor

## Vendorização

`scripts/vendor_motor.py` copia `projeto_curva_v4/src/*.py` para
`motor_curva/`, byte a byte, e grava `motor_curva/VENDOR_MANIFEST.json` com
SHA-256 de cada par fonte × vendorizado.

Todos os 17 imports internos do motor são **relativos** (`from .config`,
`from . import risco`) — renomear o pacote de `src` para `motor_curva` funciona
sem tocar em uma linha. **O script deve falhar explicitamente** se algum dia
aparecer um `from src.` no fonte, porque aí a cópia fiel quebraria calada.

`config.py` entra inteiro, com o `mkdir` da linha 20. Vendorizado, o
`RAIZ = Path(__file__).resolve().parents[1]` passa a ser a raiz do repositório e
o import cria `<repo>/data/raw`, `<repo>/data/processed` e `<repo>/outputs`.
Adicione os três ao `.gitignore`.

**Nunca edite `motor_curva/` à mão.** Conserto é na fonte seguido de resync.

## Snapshot

`scripts/build_motor_snapshot.py` roda offline contra o motor vendorizado e
grava `motor_curva/snapshots/2026-08-14_<hash>.json`: âncora, cenários oficiais
inteiros, fatores sazonais, volatilidade por vértice, manifesto com SHA-256 das
fontes, data de corte, status.

O snapshot **vai versionado no repositório**. O app nunca lê `data/raw` — no
servidor de deploy esses gigabytes não existem.

## `avaliar()`

Extraia de `cli.py::cmd_run` o serviço:

```python
avaliar(snapshot, ref_mercado: dict, limite_var: float) -> dict
```

Só a parte barata: prêmio → sinal → dimensionamento por risco → VaR → PnL →
VPL. Milissegundos. Mesma estrutura do `resumo_execucao.json`, mais os
DataFrames de curva, sinal e pernas.

## Teste golden, pinado

Comite `tests/golden/motor/resumo_execucao_2026-08-14.json` junto com o snapshot
exato que o gerou. O teste carrega os dois arquivos fixos e **nunca** compara
contra saída viva.

Estes são os números reais, com dado oficial, status `DEFINITIVO`:

| vértice | lado | MWm | horas | MWh | entrada R$/MWh |
|---|---|---|---|---|---|
| ago/26 | VENDIDO | 43 | 744 | 31.992 | 142,00 |
| set/26 | VENDIDO | 188 | 720 | 135.360 | 178,00 |
| out/26 | VENDIDO | 119 | 744 | 88.536 | 232,50 |
| nov/26 | VENDIDO | 74 | 720 | 53.280 | 290,00 |
| dez/26 | VENDIDO | 62 | 744 | 46.128 | 310,00 |

- energia **355.296 MWh** · notional **R$ 78.972.444,00**
- preço médio **222,27 R$/MWh**, ponderado por MWh
- VaR **R$ 29.892.814,54** = **59,79%** do limite de R$ 50 milhões
- ES R$ 35.632.546,19 · VPL R$ 3.670.973,69
- PnL Seco **−R$ 19.691.794,06** · Esperado **R$ 17.559.624,24** · Úmido
  **R$ 54.814.228,80**
- prêmio de nível 39,01 R$/MWh · k_seco 1,6066 · k_umido 0,8465
- VaR de preço 84,37 R$/MWh · meia-vida 365 dias

Se `avaliar()` divergir num centavo, a extração está errada.

## Requirements separados

- `requirements-app.txt` — pandas, numpy, streamlit, SQLAlchemy, driver do
  Postgres, cliente de IA
- `requirements-motor-offline.txt` — pdfplumber, matplotlib, python-pptx,
  python-docx. Só para `build_motor_snapshot.py`, **nunca instalado no deploy**

---

# Parte 2 — Persistência

**O Streamlit Cloud não tem disco persistente.** Container efêmero: reboot,
redeploy ou o app dormindo e acordando zeram o filesystem. SQLite em arquivo
local perde tudo, e o case exige que o registro continue lá na defesa.

**Postgres gerenciado, fora do container** — Supabase ou Neon, plano gratuito.
Confirme os limites atuais antes de escolher. SQLAlchemy com uma única
`DATABASE_URL`: SQLite local, Postgres em produção, mesmo código. A URL vai em
`st.secrets`, nunca no repositório.

Cinco consequências que você trata junto:

1. **`@st.cache_resource` no engine.** O Streamlit reexecuta o script a cada
   interação; sem cache você abre conexão por clique e esgota o pool.
2. **`@st.cache_data` no snapshot.** Recarregar a cada rerun mata o requisito de
   menos de 10 segundos.
3. **`session_state` no wizard de 4 etapas**, e o rascunho da tese persistido no
   banco a cada etapa concluída, com status de rascunho. Se o navegador cair no
   meio da demonstração, eu reabro e continuo.
4. **DDL idempotente no boot.** Não haverá shell no ambiente publicado.
5. **Schema compatível com Postgres.** JSON como `JSONB`.

## Schema — aditivo, sem tocar em `positions`

O book da tese é posição **proposta**; `positions` é posição real. Não misture,
não crie discriminador. A existência da linha em `thesis_book` já é o fato.

**`thesis_book`** — um por `avaliar()` salvo:
`id`, `thesis_id` (FK), `snapshot_hash`, `ref_mercado_json`, `modo_sinal`,
`premio_nivel_rs_mwh`, `k_premio`, `var_total`, `es_total`, `var_limit`,
`consumo_limite`, **`energia_mwh`**, **`notional_brl`**,
`preco_entrada_medio_mwh`, `mwmed_equivalente_flat`, `soma_mwm_pernas`,
`pnl_convergencia`, `pnl_entrega_esperado`, `pnl_entrega_seco`,
`pnl_entrega_umido`, `vpl`, `natures_json`, `evidence_id`, `created_at`.

**`thesis_book_legs`** — uma por vértice:
`id`, `book_id` (FK), `mes_ref`, `lado`, `mwmed` + `mwmed_nature`,
`horas` + `horas_nature`, `mwh` + `mwh_nature`,
`preco_entrada` + `preco_entrada_nature` + `preco_entrada_origem`
(`"leitura de mesa"` | `"informado na defesa"`), `snapshot_hash`, `created_at`.

Os `*_nature` são preenchidos no INSERT a partir de um default por campo.
**Depois disso ninguém lê o default**: toda leitura vem da linha gravada. Se o
rótulo vivesse só no código, um deploy novo reetiquetaria registros antigos
retroativamente — e aí o registro deixa de ser auditável, que é justamente o que
o case pede.

`energia_mwh` e `notional_brl` são os agregados de tamanho.
`mwmed_equivalente_flat` (96,76) pode ir para a tela como KPI rotulado
`MWm eq.`; `soma_mwm_pernas` (486) fica só no banco. Nenhum dos dois em campo ou
coluna chamado simplesmente `volume` ou `tamanho` — o nome tem de dizer qual das
três leituras é.

---

# Parte 3 — As três funções

## Registrar

Wizard em 4 etapas, não formulário longo.

**Etapa 1 — Parâmetros.** Submercado, data de corte, referência de mercado por
vértice. Botão **Gerar book** chama `avaliar()`. O book proposto aparece na tela
com o ladder completo.

Aqui mora, **em destaque**, o bloco de **registro ao vivo**: alterar a
referência de um vértice ou injetar uma leitura hidrológica, recalcular, e ver o
book novo ao lado do anterior com o **diff** — o que mudou por vértice, no VaR e
no consumo do limite. Meta: **menos de 10 segundos** entre digitar e ver.

**Etapa 2 — Narrativa.** O trader escreve: resumo em até 5 linhas, horizonte,
data de reavaliação, gatilhos de saída e condição de invalidação. Campos
digitados são **visualmente distintos** dos calculados pelo motor.

**Etapa 3 — Desafiar.** Bloqueante, não dá para pular.

**Etapa 4 — Salvar.**

## Desafiar

Roda sobre os **números do motor**, não sobre o texto:

- **premissa mais frágil** — identifique pelo dado. A referência de mercado é
  PREMISSA sem fonte pública e o prêmio de 39,01 R$/MWh depende inteiramente
  dela. Comece por aí.
- **cenário que quebra a posição** — use o cenário adverso do motor por vértice
  e diga **a partir de que preço** cada perna vira prejuízo.
- **contra-argumento** — o caso em que o mercado está certo e o modelo errado.
- **viés de confirmação** — se o trader só mexeu nos vértices que reforçam o
  lado que já tinha, aponte.

Resposta do trader é **obrigatória** antes de avançar. A IA escreve o argumento;
os números do desafio vêm do motor.

## Vigiar

**Precisa ser demonstrável com um snapshot só.** Se a vigilância comparar
snapshot contra snapshot, nada dispara nunca e os alertas viram enfeite.

Avalie os gatilhos comparando **os parâmetros registrados na tese contra os
parâmetros correntes da sessão**: referência de um vértice mudou, prêmio caiu
abaixo do limiar de 15 R$/MWh, consumo do limite passou de 60% do orçamento,
score hidrológico virou de sinal, trajetória oficial revisada.

Cada alerta diz **qual premissa caiu, qual número mudou, de quanto para quanto**
e qual gatilho de saída isso aciona.

Isso entrega o melhor momento da defesa: eles dão o dado, eu injeto no registro
ao vivo, e a tese registrada acende alerta na frente deles. Deixe esse caminho
funcionando ponta a ponta.

**Gatilhos são side-aware.** A posição é vendida: úmido é o cenário favorável, o
que invalida é seco. O motor já tem essa lógica — o cenário adverso depende do
lado. Derive de lá em vez de fixar direção na tela.

## Camada opcional — escolha exatamente uma

**Otimização de portfólio sob restrição de VaR.** Já está pronta no motor
(`book.dimensionar_por_risco`). Exponha: dado o book atual e a folga até o
limite, qual a alocação marginal que melhora a relação risco-retorno.

Não implemente as outras três do case.

---

# Parte 4 — As quatro telas

Ordem de construção: **Registrar primeiro**, Mesa e Dados depois — as duas
dependem de já existir tese registrada para não ficarem vazias.

## 1. Mesa (home)

Alertas abertos no topo, sempre visíveis. **BOOK PROPOSTO** — não "vigente": o
case diz que não há book posicionado de partida, e chamar de vigente sugere
posição executada. Ladder por vértice com badges de natureza, energia, notional,
preço médio, gauge de VaR com consumo e folga até o stop. Abaixo, a lista de
teses registradas.

Sem tese, mostre estado vazio explícito — "Nenhuma tese registrada" — nunca zero
silencioso.

## 2. Registrar tese

O wizard descrito acima.

## 3. Tese (detalhe)

Este é o registro que eles vão abrir na defesa. Ele precisa conter, item por
item, **tudo que o case exige da Entrega 2**:

- tese em até 5 linhas
- dimensionamento e quanto do limite de VaR consome
- resultado esperado **como intervalo**, nunca número único
- horizonte e data de reavaliação
- gatilhos de saída e, explicitamente, o que invalidaria a tese
- premissas de cenário com fonte e rótulo de natureza
- comportamento em **pelo menos dois cenários hidrológicos**, lado a lado:
  resultado, impacto no VaR e o que muda na tese

Mais: ladder congelado nesta versão, histórico de alertas com o que já foi
violado e qual foi a decisão, e link para versões anteriores.

## 4. Dados e procedência

Snapshot com hash, status e data de geração. Tabela do manifesto: instituição,
conjunto, SHA-256, data de coleta. Botão **Verificar hashes** que recalcula e
compara.

Esta tela é a resposta *visível* à pergunta obrigatória do case sobre como a
ferramenta não inventa número. Em vez de eu afirmar no texto, eu abro a tela.
Primeira a cortar se o prazo apertar, mas é barata.

## Regras de layout, valem nas quatro

- número calculado pelo motor é visualmente distinto de campo digitado
- todo número mostra o rótulo de natureza
- texto gerado por IA leva badge próprio, distinto de número e de texto do trader
- formatação pt-BR: ponto para milhar, vírgula para decimal. `355.296 MWh` ou
  `355,3 GWh`, nunca `355,296 MWh`

### MWm na tela — três casos distintos

MWm é a unidade nativa da mesa. Ninguém diz "vendi 135.360 MWh em setembro";
diz "vendi 188 MWm". A regra não é banir MWm, é não deixar um número único em
MWm passar por "o tamanho" sem o ladder ao lado.

- **MWm por vértice — sempre.** É como o produto é negociado, cotado e
  liquidado. Destaque no ladder.
- **MWm equivalente flat — pode ser KPI**, rotulado `MWm eq.` com a janela
  declarada: `96,8 MWm eq. ago–dez/26`. Sempre com o ladder visível na mesma
  tela, e ao lado de energia e notional, nunca no lugar deles. Dá noção de
  escala imediata para quem é da área, coisa que 355,3 GWh não dá.
- **Soma de MWm entre meses — nunca**, em nenhuma tela. 486 não mede nada: são
  potências de meses diferentes que jamais coexistem. Fica só no banco, como
  `soma_mwm_pernas`, campo informativo.

É o ladder ao lado que impede a leitura errada de que a posição é plana.

---

# Invariantes

Cada uma é um bug que já aconteceu e custou horas.

1. **Nenhum número sai de um modelo de linguagem.** A IA escreve texto,
   argumento, crítica. Campo numérico sem origem rastreável não pode existir.
2. **Todo número carrega rótulo de natureza**, gravado no registro e propagado
   até a tela.
3. **Procedência com hash.** O registro guarda qual snapshot gerou cada número.
4. **Falha explícita, nunca silenciosa** — e nunca crash: mensagem tratada na
   tela. Sem valor padrão, sem interpolação, sem último valor conhecido.
5. **Risco é o VaR, e só ele.** Consumo do limite é o VaR de marcação de 1 mês
   somado entre vértices, sem diversificação. Perda no cenário adverso é stress
   e não dimensiona. O `risk_service.py` existente **não** é chamado para tese
   vinda do motor.
6. **Cenários são trajetórias oficiais inteiras** da CCEE. Nunca combine o mês de
   uma com o mês de outra.
7. **O fator de risco é o preço a termo, não o PLD spot.**
8. **MWm nunca se soma entre meses.** Dimensionamento é por vértice, e é em MWm
   que ele se expressa. Agregado de posição em MWh e R$; MWm equivalente flat
   só rotulado como tal e com a janela declarada.
9. **A referência de mercado é PREMISSA, leitura de mesa, sem identificação de
   fonte.** Rotule exatamente assim, não atribua a nenhum provedor.

---

# Parte 5 — Entregáveis, além do código

## Seed obrigatório

Um script que registra **a tese da Entrega 2 no banco de produção**. Se eles
abrirem o link e estiver vazio, o requisito de verificação falhou. Rode o seed
contra o Postgres publicado e confirme.

## Teste de aceitação da persistência

Registrar a tese, **derrubar e subir o app no ambiente publicado** — não local —
e a tese continuar lá com ladder, premissas e rótulos intactos. Quero ver esse
teste passando.

## Acesso

O case pede "link do protótipo rodando, com acesso de teste". App público, ou
credencial simples documentada no README. Nada que os impeça de entrar.

## `DECISOES.md`

Toda decisão que você tomou sozinho, com a razão em uma linha. Anote também que
o app publicado dorme por inatividade e demora a acordar, para eu abrir a URL
dez minutos antes da defesa.

## Documento de até 1 página

Ao final, escreva `ENTREGA_1_PROTOTIPO.md`: qual problema resolve, escolhas de
arquitetura, o que ficou de fora e por quê, e o que eu teria feito diferente com
mais duas semanas. Direto, sem enrolação.

---

# Como trabalhar

Fatias verticais. A partir da fatia 3, **cada fatia termina em tela
funcionando**. Porte os testes antes do código.

| # | entrega | termina em |
|---|---|---|
| 1 | vendorizar + snapshot + `avaliar()` | golden passando, sem UI |
| 2 | schema + `motor_service.py` | round-trip no banco |
| 3 | Registrar — parâmetros → book proposto na tela | tela funcionando |
| 4 | salvar tese com persistência real | tese lida de volta após restart |
| 5 | registro ao vivo em menos de 10s, com diff | requisito de verificação coberto |
| 6 | Desafiar | tela funcionando |
| 7 | Tese (detalhe) | tela funcionando |
| 8 | Vigiar + Mesa | alertas disparando de verdade |
| 9 | otimização sob VaR | tela funcionando |
| 10 | Dados e procedência | primeira a cortar se apertar |

**Não me pergunte a cada decisão.** Na dúvida, adote o caminho mais razoável
tecnicamente, registre no `DECISOES.md` e siga. Vá até o fim sem parar para
confirmação.

Três exceções em que você **deve** parar e me chamar:

- se precisar mudar qualquer arquivo do motor
- se aparecer um segundo cálculo de risco concorrendo com o VaR do motor
- se descobrir que algo que combinamos é impossível

## Não faça

- não reescreva o motor
- não crie um segundo cálculo de VaR
- não invente número para preencher tela
- não implemente mais de uma camada opcional
- não mostre soma de MWm entre meses, nem um MWm único sem o ladder ao lado

Comece pela fatia 1.
