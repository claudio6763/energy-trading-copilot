# DECISOES.md

Toda decisão tomada sozinho durante a execução do `PROMPT_FINAL_COPILOTO.md`,
com a razão em uma linha. Ordem cronológica.

## Motor / snapshot

- **`motor_curva/` existente foi renomeado para `motor_curva_source/`.** A
  pasta já existia no repositório, mas aninhada (`motor_curva/src/*.py`, com
  `data/raw` real e `outputs/` de uma rodada anterior) — provavelmente cópia de
  trabalho movida para cá por causa do limite de caminho do Windows
  (`motor_curva_source/FINALIZAR.md` descreve exatamente isso). Não é a
  vendorização plana que o prompt pede. Renomear preserva tudo (é reversível)
  e libera `motor_curva/` para a vendorização de verdade.
- **`motor_curva_source/src/book.py` estava desatualizado** (466 linhas, sem
  ladder) em relação a `projeto_curva_v4/src/book.py` (525 linhas, com
  ladder/notional/preço médio). Confirmado por diff. A vendorização usa
  `projeto_curva_v4` (OneDrive) como fonte, exatamente como o prompt pede —
  não `motor_curva_source`.
- **Dado real (`data/raw`, `fixtures/*.pdf`) copiado de `projeto_curva_v4` para
  a raiz do repo**, não versionado (`.gitignore`). Necessário porque
  `motor_curva/config.py` vendorizado resolve `DIR_RAW`/`DIR_FIX` relativos à
  raiz do repo (efeito colateral aceito, ver PROMPT_FINAL_COPILOTO.md).
- **Snapshot construído com `sys.settrace`**, não reimplementando
  `cmd_run`. `scripts/build_motor_snapshot.py` roda
  `motor_curva.cli.cmd_run(args)` inteiro, sem editar uma linha, e captura os
  locais do frame no retorno. Garante que o snapshot e `resumo_execucao.json`
  vêm da mesma execução, nunca de uma reimplementação paralela que possa
  divergir.
- **`avaliar()` e `MotorSnapshot` vivem em `src/motor/`, fora de
  `motor_curva/`.** `motor_curva/` só deve conter a cópia vendorizada +
  `VENDOR_MANIFEST.json` + `snapshots/*.json` (dado, não código) — assim um
  resync (`vendor_motor.py` de novo) nunca arrisca sobrescrever código meu.
- **`MotorSnapshot` é `dataclass`, não Pydantic.** `pydantic` não está entre as
  dependências instaladas e o núcleo ativo do copiloto é stdlib-first
  (ADR-011 do `SPRINT_STATUS.md`). Manter consistência com o que já roda.
- **Golden test usa `--confcutdir=tests/motor`.** `tests/conftest.py` (da
  camada SQLAlchemy legada, não usada em produção) importa `alembic`/
  `pydantic`/`copilot.config`, que não fazem parte do caminho stdlib ativo.
  Rodar `pytest tests/motor/ --confcutdir=tests/motor` isola o teste novo
  dessa árvore sem tocar no conftest legado. `alembic` e `SQLAlchemy` foram
  instalados no ambiente mesmo assim, porque `SQLAlchemy` passa a ser
  dependência real da Parte 2 (Postgres).
- **`requirements-app.txt` inclui `SQLAlchemy` e `psycopg[binary]`**, que não
  estavam no `requirements.txt` original — exigidos pela Parte 2 (Postgres
  gerenciado). `requirements.txt` original foi deixado como estava (usado por
  scripts existentes); os dois novos arquivos (`requirements-app.txt`,
  `requirements-motor-offline.txt`) são a separação que o prompt pede.

## Persistência (Parte 2)

- **Adaptador (`pg_shim.py`), não reescrita de `repositories.py`.** Portar as
  ~25 funções de `?`-posicional para `text(":nome")` do SQLAlchemy trocaria um
  problema de infraestrutura por risco real de regressão em 15+ recursos que
  já funcionam (Dashboard, Debate demo, Watchdog, Dados e fontes). O
  `schema.sql` existente já é SQL padrão — as únicas partes SQLite-only são o
  FTS5 e a sintaxe de trigger, isoladas em `schema_sqlite_only.sql` e nunca
  executadas contra Postgres. `PgConnectionShim` faz uma conexão `psycopg` se
  comportar como `sqlite3.Connection` o bastante (`.execute(sql, params)` com
  `?`, linha por nome de coluna, `.commit()`) para todo código existente
  funcionar sem alteração nos dois bancos.
- **Corte documentado:** `INSERT OR REPLACE` (forward_curves,
  forward_curve_points, scenario_results — 3 ocorrências) não tem equivalente
  em Postgres e não foi portado. Nada do fluxo novo usa essas funções; só
  quebraria se alguém rodasse a aba antiga "Dados e fontes → Curva pública"
  sobre Postgres. RAG por FTS5 também fica SQLite/DEMO-only pelo mesmo motivo.
- **`theses` ganhou 5 colunas novas** (`trader_response`,
  `desafio_premissa_fragil`, `desafio_cenario_quebra`,
  `desafio_contra_argumento`, `desafio_vies_confirmacao`) via `ALTER TABLE`
  idempotente (`ensure_theses_extra_columns`) — instalação nova já nasce com
  elas no `CREATE TABLE`; banco local existente (`data/copilot.db`, 1 tese) foi
  preservado, não recriado.
- **`thesis_book`/`thesis_book_legs` aditivas, `positions` intocada** —
  exatamente como combinado: book do motor é posição proposta, `positions` é
  posição real, tabelas separadas, sem discriminador (a existência da linha em
  `thesis_book` é o próprio fato).
- **Rótulo de natureza gravado no INSERT** (`HEADER_FIELD_NATURES`/
  `LEG_FIELD_NATURES` em `motor_service.py` são só o *default* usado uma vez
  na escrita; leitura sempre vem da coluna gravada, nunca recalculada).
- **Vigiar não terá tabela própria** (decisão adiantada da fatia 8): o usuário
  definiu que os 3 gatilhos comparam parâmetros da tese salva contra
  parâmetros correntes da SESSÃO, não snapshot-vs-snapshot — isso é uma
  função pura sobre `thesis_book` + estado de sessão, computada a cada
  renderização da tela, sem necessidade de tabela de alertas persistida nesta
  passada.
- **Postgres não testado contra servidor real** (sem Docker/Postgres local
  disponível no ambiente de desenvolvimento). O caminho SQLite foi validado de
  ponta a ponta (33/35 testes pré-existentes + todos os novos passando). O
  caminho Postgres é estruturalmente correto (mesmo `schema.sql`, mesmo
  `pg_shim`) mas precisa de um teste real contra Supabase/Neon antes da defesa
  — ver checklist de deploy.
- **`pyproject.toml` ganhou `pythonpath = [".", "src"]`** no
  `[tool.pytest.ini_options]` — sem isso, testes fora de `tests/mvp` não
  encontravam `copilot`/`src.*` (pré-existente, não causado por esta sessão;
  `app.py` já fazia esse duplo insert de path manualmente).
- **Ambiente local recebeu as dependências que já eram declaradas mas não
  instaladas**: `streamlit`, `pandas`, `numpy`, `scipy`, `pydantic`,
  `pydantic-settings`, `SQLAlchemy`, `alembic`, `psycopg[binary]`,
  `plotly`, `anthropic`, `pymupdf`, `pypdf`, `reportlab`, `openpyxl`. Nenhuma
  delas é nova em relação ao que `pyproject.toml`/`requirements.txt` já
  declaravam — só não estavam instaladas no ambiente de desenvolvimento.

## Deploy — o que eu não posso fazer sozinho

Git foi inicializado localmente e o primeiro commit está feito (250 arquivos,
identidade local `Energy Trading Copilot <copilot@local>` — troque para a sua
com `git config user.name`/`user.email` se quiser seu nome nos commits).

O resto do deploy exige login/OAuth no navegador em contas que só você pode
criar — não consigo fazer por você. Checklist, nessa ordem:

1. **Criar repositório privado no GitHub** (CLAUDE.md exige privado) e:
   ```
   git remote add origin <url-do-seu-repo>
   git push -u origin main
   ```
2. **Provisionar Postgres gerenciado** — Supabase ou Neon, plano gratuito
   (confirme os limites atuais antes de escolher, mudam com frequência).
   Copie a `DATABASE_URL` (formato `postgresql://usuario:senha@host:porta/banco`).
3. **Streamlit Community Cloud → New app**, apontando para o seu repositório,
   branch `main`, arquivo principal `app.py`. Em **Advanced settings → Python
   dependencies file**, aponte para `requirements-app.txt` (não o
   `requirements.txt` da raiz, que é do MVP anterior; e nunca
   `requirements-motor-offline.txt`, que traria `pdfplumber`/`matplotlib` sem
   necessidade).
4. Em **Advanced settings → Secrets**, cole:
   ```toml
   DATABASE_URL = "postgresql://...."
   ANTHROPIC_API_KEY = "..."   # opcional; sem ela o app roda em modo demonstracao
   ```
5. Deploy. Na primeira carga, `_garantir_schema()` roda `init_db()` sozinho
   (DDL idempotente, sem shell) — schema.sql inteiro funciona em Postgres
   exceto FTS5/triggers (puladas automaticamente, ver acima).
6. **Rodar o seed de produção** (fatia final, Parte 5) contra essa mesma
   `DATABASE_URL` antes da defesa — sem isso o link abre vazio.
7. Testar a persistência de verdade: registrar a tese, **fechar a aba,
   reabrir a URL** (não basta dar refresh no mesmo processo — o objetivo é
   provar que sobrevive a um redeploy/sleep do container).

O app publicado dorme por inatividade no plano gratuito do Streamlit Cloud e
demora a acordar — abra a URL uns 10 minutos antes da defesa (repetido no
`DECISOES.md` para não perder na correria).

## Manifesto do snapshot corrigido

O primeiro snapshot gerado veio com `manifesto` marcado `FIXTURE`/"dado
sintético" — não porque o dado fosse sintético (é real, CCEE/ONS, importado
por `motor_curva_source/importar.py`), mas porque `motor_curva.manifesto.itens()`
só é populado pelo mecanismo de `sync` (que registra URL/hash na hora do
download), e eu copiei os arquivos direto em vez de rodar o sync. Isso teria
feito a tela "Dados e procedência" afirmar o oposto da verdade — exatamente o
tipo de erro que essa tela existe para impedir. Corrigido substituindo o campo
`manifesto` do snapshot pelo conteúdo real de
`motor_curva_source/data_manifest.json` (mesmas chaves, hashes batendo com os
arquivos usados) e regravando o hash do snapshot. Os números do book
(`avaliar()`) não usam `manifesto` em nada — só a tela de procedência —,
então nada além dela é afetado.

## Postgres real (Neon) — verificado ponta a ponta

Provisionado pelo usuário; encontrei três incompatibilidades reais do
`schema.sql` contra Postgres, todas corrigidas em código (nunca no `.env`):

1. **`get_database_url()` não reconhecia `COPILOT_DB`** apontando para
   Postgres — só olhava `DATABASE_URL`. Corrigido: `COPILOT_DB` é aceito como
   alias quando o valor tem cara de URL de Postgres (`postgres(ql)(+driver)://`).
2. **Split de statements por `;` quebrava dentro de comentário** — uma linha
   de comentário em português tinha um `;` no meio da frase
   ("...verifica; ver DECISOES.md"), e o split ingênuo cortava o comentário ao
   meio; a segunda metade parava de começar com `--` e virava "SQL" inválido.
   Corrigido removendo comentários de linha ANTES do split (`pg_shim.py`).
3. **`window` é palavra reservada no Postgres** (funções de janela) — a
   coluna `triggers.window` existia sem aspas desde antes desta sessão. A
   camada SQLAlchemy legada (`src/copilot/db/models/thesis.py`) já documentava
   esse mesmo problema e usa `eval_window` como nome — não segui essa rota
   (renomear coluna é mais invasivo) e apliquei aspas duplas (`"window"`) no
   DDL e nos dois pontos de `thesis_service.py` que montam SQL com esse nome,
   mantendo a chave do dict de leitura sem aspas (mesmo nome de coluna).
4. **`PRAGMA foreign_keys = ON`** (primeira linha do schema): SQLite-only,
   sem equivalente em Postgres (FK sempre obrigatória lá). `executescript` do
   adaptador agora pula qualquer `PRAGMA` ao rodar contra Postgres.

Depois dos quatro ajustes: `init_db()` roda limpo contra o Neon (idempotente,
testado rodando duas vezes seguidas), `thesis_book`/`thesis_book_legs`
confirmadas via `information_schema`, `scripts/seed_producao.py` registrou a
tese real, e uma leitura com conexão nova devolveu os cinco vértices, VaR
R$ 29.892.814,54 e consumo 59,79% — vindos do Postgres, não do snapshot local
(prova em `tests/services/test_motor_service_postgres.py`, marcador
`postgres`, roda só com `DATABASE_URL`/`COPILOT_DB` de Postgres configurada).

**Alembic não entrou nessa verificação.** O usuário pediu para rodar as
migrações Alembic contra o Postgres — mas `thesis_book`/`thesis_book_legs` e
o `theses` que este app usa não são modelados em nenhuma migration de
`migrations/versions/` (essas migrations pertencem à camada SQLAlchemy
paralela, não usada em produção). Rodar `alembic upgrade` criaria um schema
diferente e não cumpriria o pedido real (confirmar que essas duas tabelas
existem). Troquei pela ferramenta que de fato governa esse schema —
`init_db()` — e disse isso ao usuário antes de agir, em vez de rodar Alembic
sem explicar e deixar a lacuna escondida.

**Exposição de credencial**: o usuário sinalizou que a senha do Postgres
apareceu numa captura de tela e pediu para rotacionar antes do deploy. Ela
apareceu no `.env` que precisei ler para executar os itens pedidos — auditoria
confirmou que nunca foi commitada (`git log --all -- .env` vazio,
`git check-ignore -v .env` confirma que está ignorada). Mesmo assim, o valor
ficou visível nesta transcrição de sessão — se ainda não foi rotacionada
depois do aviso inicial, vale considerar isso mais um motivo para rotacionar,
não menos.

## Estado final desta sessão

Fatias 1 a 8 e 10 fechadas, com testes passando (golden do motor, round-trip
de persistência, smoke tests de UI via `AppTest` real do Streamlit — não
mock). Camada opcional: nenhuma, por instrução explícita. Ordem seguida foi a
reprioritizada: motor → schema → (esqueleto de deploy preparado, não
publicado) → Registrar → salvar → ao vivo → Desafiar → Tese → Vigiar/Mesa →
Dados e procedência.

**O que só o usuário pode terminar** (exige OAuth/conta em navegador, listado
acima em "Deploy"): criar o repositório GitHub e dar push, provisionar
Supabase/Neon, conectar o Streamlit Cloud, colar os secrets, rodar
`scripts/seed_producao.py` contra a `DATABASE_URL` de produção, e o teste de
aceitação final (registrar, fechar a aba, reabrir a URL publicada).

Nenhuma das três exceções que exigiam parar e perguntar (mudar arquivo do
motor, segundo cálculo de risco concorrente, algo combinado impossível)
ocorreu — segui até aqui sem interromper, como pedido.

*(Continua conforme as fatias seguintes forem fechadas.)*
