# Entrega 1 — Protótipo do Copiloto

## Qual problema resolve

Numa mesa de energia, tese é posição: ladder por vértice, dimensionamento por
risco, VaR contra um limite. A ferramenta que existia cadastrava tese como
texto livre — um número digitado à mão, sem book, sem risco, sem procedência.
Isso é opinião, não tese, e não sobrevive a uma pergunta de auditoria seis
meses depois.

O protótipo resolve isso ligando a Entrega 2 (o motor quantitativo de
`projeto_curva_v4`) dentro da ferramenta da Entrega 1: o trader escolhe uma
referência de mercado, o motor devolve o book — ladder, VaR, cenários — e a
tese só é registrada depois de passar por um desafio adversarial e de o
trader responder ao contra-argumento. Nenhum número da tela sai de um modelo
de linguagem; todo número carrega rótulo de natureza e o hash do snapshot que
o gerou.

## Escolhas de arquitetura

**Vendorização + snapshot, não pipeline ao vivo.** O motor foi copiado byte a
byte para `motor_curva/` (script com manifesto de SHA-256, falha explícita se
a cópia deixar de ser fiel). A parte cara do pipeline (ingestão, sazonalidade
walk-forward, ancoragem, classificação de regime) roda uma vez offline e
congela num snapshot versionado; `avaliar()` recombina esse snapshot com uma
referência de mercado nova em milissegundos — é isso que faz o registro ao
vivo caber em segundos, não minutos.

**Persistência aditiva, sem tocar no que funciona.** `thesis_book` e
`thesis_book_legs` são tabelas novas — o book do motor é posição *proposta*,
`positions` é posição real, e misturar as duas teria sido o mesmo bug de dois
cálculos de risco concorrentes que já custou tempo neste projeto antes. Cada
perna grava seu rótulo de natureza e a origem do preço ("leitura de mesa" vs.
"informado na defesa") no momento do INSERT, nunca recalculado depois — um
deploy novo não pode reetiquetar um registro antigo.

**Adaptador de conexão, não reescrita para SQLAlchemy puro.** Streamlit Cloud
não tem disco persistente; a tese precisa sobreviver a um redeploy. Em vez de
reescrever ~25 funções de acesso a dado existentes (Dashboard, Watchdog,
Debate, RAG) para bind nomeado, um adaptador faz uma conexão Postgres se
comportar como `sqlite3.Connection` o bastante para o código atual funcionar
sem alteração nos dois bancos. Custo: `INSERT OR REPLACE` (3 usos, fora do
caminho novo) e busca lexical por FTS5 ficam SQLite-only.

**Vigiar sem tabela própria.** Os três gatilhos comparam os parâmetros
registrados na tese contra os parâmetros da sessão corrente — nunca snapshot
contra snapshot, que nunca dispararia nada. É uma função pura sobre o que já
está salvo, recalculada a cada render.

## O que ficou de fora, e por quê

- **Camada opcional de otimização sob VaR** — cortada por instrução explícita
  nesta rodada (zero camadas opcionais).
- **Verificação de hash ao vivo** na tela Dados e procedência — a tabela do
  manifesto está lá; o botão de recalcular e comparar não.
- **Watchdog genérico e Debate multi-agente antigos** ficaram como estavam,
  não migrados para o caminho Postgres — a mesa nova (Registrar → Desafiar →
  Vigiar → Mesa) não depende deles.
- **Versionamento de tese** (`new_version`) não está ligado à Mesa nova; toda
  tese registrada nasce v1. Lineage existe no schema, não na tela.
- **Postgres não testado contra um servidor real** — sem ambiente disponível
  para isso na sessão de desenvolvimento. O caminho está estruturalmente
  pronto (mesmo schema, mesmo adaptador); falta o teste de aceitação real
  contra Supabase/Neon antes da defesa.

## O que eu teria feito diferente com mais duas semanas

Rodar o `sync` de verdade do motor (não copiar arquivos à mão) para o
manifesto nascer correto na primeira tentativa, em vez de eu ter que
substituí-lo depois de notar que ele dizia "FIXTURE" sobre dado real —
pequeno, mas é exatamente o tipo de erro que a tela de procedência existe
para pegar, e quase escapou por vir do próprio processo de geração.

Trocaria o adaptador de conexão por uma migração real para SQLAlchemy Core
com bind nomeado nas ~25 funções de `repositories.py` — o adaptador atual é
uma ponte deliberada para não arriscar regressão sob prazo, não a forma
final. E daria a Vigiar uma tabela de histórico de fato: hoje o "o que já foi
violado" da tela Tese é só o resultado da última verificação, não uma trilha
persistida — para uma mesa de verdade, isso devia ficar gravado, não recalculado
a cada vez que alguém abre a tela.
