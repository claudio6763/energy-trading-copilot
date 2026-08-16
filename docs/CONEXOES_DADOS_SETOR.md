# CONEXÕES DE DADOS DO SETOR ELÉTRICO E CURVA FORWARD

Versão 1.0 · Implementado em 09/08/2026. Referência: `PROMPT_INTEGRACOES_DADOS.md`.
Em conflito com `CLAUDE.md` ou o PDF do case, eles prevalecem.

---

## 1. Visão geral

O MVP já registrava, debatia e vigiava teses (Sprints 1–7). Esta rodada
implementou a coleta real de dados públicos do setor elétrico brasileiro
(ONS, CCEE, EPE), preparou a integração opcional com curva forward
licenciada (BBCE), verificou a disponibilidade pública da curva B3/N5X, e
adicionou uma curva pública de cenário estatístico para o MVP continuar
funcional sem depender de nenhuma fonte licenciada.

Nada disso substitui o RAG regulatório (`src/rag/`) nem o motor quantitativo
(`copilot.quant` / `src/services/risk_service.py`): dado estruturado continua
em SQL, cálculo continua em Python determinístico, e o LLM continua sem
poder de emitir número (P1–P5 de `CLAUDE.md`).

## 2. Arquitetura

```
copilot.ingest.adapters   →  coleta e normaliza (stdlib, sem banco, testável isolado)
        │  AdapterResult (dataclass)
        ▼
src.services.ingestion_bridge  →  única ponte: grava em sqlite3 + evidence_id + auditoria
        │
        ▼
src.database (sqlite3)    →  sources, market_observations, forward_curves,
                              forward_curve_points, ingest_snapshots, evidence
        │
        ▼
app.py (Streamlit) e src.agents.specialists.MarketAgent  →  leitura controlada,
                              nunca SQL arbitrário gerado por LLM
```

Por que uma ponte separada (`src/services/ingestion_bridge.py`): os adapters
em `copilot.ingest.adapters` são stdlib puro, sem dependência de banco, para
serem testáveis sem rede e sem SQLite (ADR do Sprint 2). O runtime do MVP
persiste em SQLite puro via `src.database` (ADR-011/012 — a camada
SQLAlchemy de `src/copilot/db/` nunca chegou a ser exercitada e foi mantida
apenas como caminho de evolução para Postgres/Supabase). A ponte é o único
módulo do projeto que importa dos dois mundos.

## 3. Matriz de fontes

| Fonte | Adapter | Tipo de acesso | Status verificado em 09/08/2026 | Dataset/endpoint |
|---|---|---|---|---|
| ONS | `ons` | `PUBLIC_NO_AUTH` | **ACTIVE** — validado com chamada real (3.644 observações) | CKAN `dados.ons.org.br`: `carga-energia`, `ena-diario-por-subsistema`, `ear-diario-por-subsistema`, `cmo-semanal` |
| CCEE | `ccee` | `PUBLIC_NO_AUTH` | **NOT_VERIFIED nesta rede** — WAF bloqueia com HTTP 403 mesmo na página raiz, a partir do ambiente de desenvolvimento usado aqui. Código pronto (mesmo padrão CKAN do ONS); reavaliar de rede sem bloqueio de IP/datacenter. | CKAN `dadosabertos.ccee.org.br`: `preco_liquidacao_diferenca` |
| EPE | `epe` | `PUBLIC_NO_AUTH` | **ACTIVE** — validado com chamada real (18.568 observações) | XLSX único, sem API: link descoberto na página oficial ou `EPE_CONSUMO_URL` |
| NOAA CPC (ENSO/ONI) | `enso_oni` | `PUBLIC_NO_AUTH` | **ACTIVE** (já existia; reconfirmado) | `cpc.ncep.noaa.gov/data/indices/oni.ascii.txt` |
| ANEEL | `aneel` | `PUBLIC_NO_AUTH` | Interface declarada, não implementada nesta sprint | `dadosabertos.aneel.gov.br` |
| ANA | `ana` | `PUBLIC_NO_AUTH` | Interface declarada, não implementada nesta sprint | HidroWeb |
| Clima (INMET/GFS) | `climate` | `PUBLIC_NO_AUTH` | Interface declarada — GRIB exige decodificador binário fora do escopo de dependências | INMET / NOAA GFS |
| B3 / N5X | `b3_n5x` | — | **NOT_VERIFIED** — verificação feita nesta sprint não encontrou endpoint público automatizável (apenas PDFs de metodologia) | ver seção 6 |
| BBCE | `bbce_forward` | `OPTIONAL_LICENSED` | **DISABLED_MISSING_CREDENTIALS** por padrão (`BBCE_API_ENABLED=false`) | `GET v1/curve/bbce-fwd` |
| Dcide e outras licenciadas | `licensed_curve_csv` | `MANUAL` | **MANUAL** — importação por CSV/XLSX, sem scraping | schema fixo, seção 7 |
| Curva estatística pública | `src.services.curve_service` | `PUBLIC_NO_AUTH` (derivada) | **ACTIVE quando há ≥ 3 anos de PLD histórico**; caso contrário `INSUFFICIENT_DATA` | PLD histórico já ingerido (CCEE) |

Estados possíveis (vocabulário do prompt de integrações): `ACTIVE`,
`PUBLIC_NO_AUTH`, `OPTIONAL_LICENSED`, `REQUIRES_MANUAL_REGISTRATION`,
`DISABLED_MISSING_CREDENTIALS`, `NOT_VERIFIED`, `MANUAL`. O schema do banco
(`sources.integration_status`) não foi alterado — continua com os valores já
existentes (`LIVE_VALIDATED`, `NOT_CONFIGURED`, `ERROR`, `MANUAL_IMPORT`,
`LOCAL_SNAPSHOT`, `DEMO`); o rótulo mais rico acima é gravado em
`sources.license_note` (prefixo `[PUBLIC_NO_AUTH]` etc.) e é o que a UI e
este documento mostram. Decisão tomada para não recriar uma tabela que já
cobre o mesmo propósito.

## 4. ONS — carga, ENA, EAR e CMO semanal

Portal: <https://dados.ons.org.br/>. API CKAN pública, sem chave.

O adapter (`copilot.ingest.adapters.public.OnsAdapter`) descobre o recurso
CSV atual via `package_show` para cada um dos quatro datasets, escolhe o
arquivo do ano-base (ou do ano anterior, se o ano corrente ainda não tiver
sido publicado) — **nunca uma URL anual fixa no código**. Cada dataset falha
isoladamente: um recurso fora do ar não impede os outros três.

Colunas verificadas em 09/08/2026 (delimitador `;`):

- `carga-energia`: `id_subsistema;nom_subsistema;din_instante;val_cargaenergiamwmed`
- `ena-diario-por-subsistema`: `..;ena_data;ena_bruta_regiao_mwmed;ena_bruta_regiao_percentualmlt;ena_armazenavel_regiao_mwmed;ena_armazenavel_regiao_percentualmlt`
- `ear-diario-por-subsistema`: `..;ear_data;ear_max_subsistema;ear_verif_subsistema_mwmes;ear_verif_subsistema_percentual`
- `cmo-semanal`: `..;din_instante;val_cmomediasemanal;val_cmoleve;val_cmomedia;val_cmopesada`

`metric_key` grava o submercado no nome (convenção de `DATA_CONTRACT.md`
seção 6, ex. `ear_sudeste_pct`): `carga_verificada_mwmed_seco`,
`ena_bruta_pct_mlt_ne`, `ear_verificada_pct_s`, `cmo_semanal_brl_mwh_n` etc.
Isso é obrigatório porque `market_observations` tem
`UNIQUE (metric, ref_date, as_of, model_run)` sem coluna de submercado — sem
o sufixo, os quatro submercados do mesmo dia colidiriam e só o último
sobreviveria (bug encontrado e corrigido durante esta implementação).

## 5. CCEE — PLD horário/diário/semanal/mensal

Portal: <https://dadosabertos.ccee.org.br/> (mesma plataforma CKAN do ONS).
O adapter (`CceeAdapter`) usa a mesma estratégia de descoberta dinâmica,
apontada para o pacote `preco_liquidacao_diferenca`, e escolhe o recurso CSV
pelo nome da granularidade pedida (`horario`/`diario`/`semanal`/`mensal`).

**Verificado nesta sprint:** requisições reais contra
`dadosabertos.ccee.org.br` — inclusive a página raiz, sem tocar em API —
retornaram HTTP 403 de um WAF, com a mensagem "Access was blocked because it
did not comply with CCEE security policies", a partir da rede de
desenvolvimento usada nesta implementação. Não é ausência de endpoint: é
bloqueio de acesso automatizado por IP/rede (comum em datacenter/nuvem). O
adapter fica pronto para redes onde o portal responde (testado offline via
payload injetado — `tests/unit/test_sector_connectors.py`). PLD ingerido por
este conector é sempre observação de spot, nunca curva forward — a mesma
regra dura que já existia para uploads manuais.

Colunas de PLD não foram confirmadas contra uma resposta real (bloqueio de
rede); o parser tenta várias variações plausíveis de nome de coluna
(`din_instante`/`data`, `nom_submercado`/`id_subsistema`, `val_pld`/`pld`) e
declara `INDISPONIVEL` com a lista de colunas encontradas se nenhuma bater —
nunca ingere meia linha.

## 6. EPE — consumo mensal de energia elétrica

Portal: <https://www.epe.gov.br/pt/publicacoes-dados-abertos/dados-abertos/dados-do-consumo-mensal-de-energia-eletrica>.
**A EPE não publica API** — um único arquivo XLSX (~13 MB, hospedado em
SharePoint) é atualizado no mesmo link. O adapter (`EpeAdapter`) localiza o
link `.xlsx` na página oficial (regex sobre o HTML público, sem login),
aceita `EPE_CONSUMO_URL` como sobrescrita manual, e **valida que o domínio
resolvido pertence a `epe.gov.br`** antes de baixar — recusa qualquer link de
terceiro que porventura apareça na página.

Planilha usada: `CONSUMO E NUMCONS SAM` (a menor das quatro grandes,
verificada em 09/08/2026). Colunas: `Data` (AAAAMMDD), `Regiao`, `Sistema`,
`Classe`, `TipoConsumidor`, `Consumo` (MWh), `Consumidores`, `DataVersao`.
`metric_key` = `consumo_mensal_mwh__<classe>_<tipo>`; a região e a
combinação completa ficam em `model_run` (`regiao:classe:tipo`), o que evita
a mesma colisão de unicidade descrita na seção 4. Layout mudou → adapter
retorna `INDISPONIVEL` com mensagem legível, nunca ingestão parcial de
colunas erradas.

## 7. Curvas licenciadas — BBCE, Dcide e importação manual

### BBCE (`bbce_forward`)

Portal do desenvolvedor: <https://portaldodesenvolvedor.bbce.com.br/>.
Endpoint documentado: `GET v1/curve/bbce-fwd?referenceDate=AAAA-MM-DD`.

Desligado por padrão (`BBCE_API_ENABLED=false`). Só tenta a rede quando as
quatro variáveis de ambiente estão presentes
(`BBCE_API_ENABLED=true`, `BBCE_API_BASE_URL`, `BBCE_API_KEY`,
`BBCE_AUTH_TOKEN`); sem elas, devolve `DISABLED_MISSING_CREDENTIALS` sem
tocar em rede — testado em `test_bbce_nunca_chama_rede_sem_credenciais`.
HTTP 401/403 vira `INDISPONIVEL` (sem autorização), nunca dado inventado. O
schema de resposta real da BBCE **não foi confirmado** (exige plano pago); o
parser aceita o formato mais comum de curva (lista de pontos com
início/fim de entrega e preço) e declara `INDISPONIVEL` se a resposta vier
em outro formato — ajustar após a primeira chamada autenticada real.
Cadastro, plano e primeiro login são manuais, no portal do desenvolvedor.
Segredos nunca aparecem em log (`mask_secret`, mascara tudo exceto os dois
primeiros/últimos caracteres) nem em `sources`/`evidence`/testes.

### Dcide e demais curvas licenciadas (`licensed_curve_csv`)

Sem scraping automático. Importação manual por CSV/XLSX com schema fixo:
`reference_date, delivery_start, delivery_end, submarket, energy_type,
product, price_brl_mwh, source, curve_type`. `curve_type` precisa ser um dos
quatro valores da seção 8; linha com produto reconhecido como PLD/CMO (regex
`\b(pld|cmo)\b`) e `curve_type` diferente de `STATISTICAL_SCENARIO_PUBLIC` é
recusada — a mesma regra dura de `ForwardCurveUploadAdapter`. Exemplo com
valores fictícios em `data/samples/curva_manual_SAMPLE.csv` (nunca
apresentado como dado real).

### B3 / N5X (`b3_n5x`)

Página oficial: <https://www.b3.com.br/pt_br/produtos-e-servicos/outros-servicos/servicos-de-natureza-informacional/plataforma-de-energia-da-b3/>.
A documentação declara divulgação gratuita da curva N5X com cinco dias úteis
de atraso. **Verificação feita em 09/08/2026:** a página oficial só expõe
downloads de PDF de metodologia (`fileDownload.jsp`); nenhum endpoint
JSON/CSV público e automatizável foi localizado. Não foi feito scraping
frágil de HTML para simular uma tabela. Adapter fica `NOT_VERIFIED` /
desabilitado; reavaliar se a B3 publicar API ou arquivo de download direto.

## 8. Classificação das curvas

Quatro categorias, nunca misturadas na mesma agregação:

| Categoria | Onde aparece nesta implementação |
|---|---|
| `MARKET_FORWARD_DELAYED_PUBLIC` | Reservada para B3/N5X quando (e se) houver endpoint verificado |
| `MARKET_FORWARD_LICENSED` | BBCE, quando habilitada e autenticada |
| `STATISTICAL_SCENARIO_PUBLIC` | Curva de cenário estatístico (seção 9) — a única ativa por padrão |
| `MANUAL_AUTHORIZED_CURVE` | Importação manual de CSV/XLSX (Dcide e afins) |

O schema (`forward_curves`) não ganhou uma coluna nova para essa
classificação: ela é derivada de `origin` + `classification` + o texto de
`notes` (que sempre grava a categoria como prefixo, ex.
`"STATISTICAL_SCENARIO_PUBLIC. ..."`). Decisão de manter o schema estável em
vez de adicionar uma coluna que duplicaria informação já presente em três
campos existentes.

## 9. Curva pública de cenário estatístico

Implementada em `src/services/curve_service.py`. Metodologia:

1. Para cada submercado e cada horizonte de M+1 a M+12, localiza os valores
   históricos do PLD no **mesmo mês-calendário** em anos anteriores
   (`metric LIKE 'pld_%'`, filtrado por `as_of` — nunca olha além da
   data-base, RF-58).
2. Exige no mínimo **3 observações anuais** por ponto. Sem isso, o ponto
   fica `INSUFFICIENT_DATA` — nunca interpolado, nunca preenchido com valor
   inventado (nem a partir de outro mês, nem por regressão).
3. Calcula P10/P50/P90 por interpolação linear sobre a amostra ordenada.
4. Persiste três cabeçalhos de curva (`quote_type` = `P10`/`P50`/`P90`),
   `origin=PROXY_MODELO`, `classification=projetado`, só com os pontos que
   tiveram histórico suficiente.
5. A UI e qualquer agente devem exibir literalmente:

   > "Cenário estatístico baseado no histórico público de PLD. Não
   > representa cotação negociada, recomendação de compra ou venda, nem
   > curva forward de mercado."

6. P50 é chamado de "cenário central", nunca de "preço de mercado".
7. ENA, EAR, carga e CMO aparecem ao lado como indicadores fundamentais
   independentes — não ajustam o preço da curva nesta versão (nenhum ajuste
   arbitrário por hidrologia/carga/CMO, conforme o prompt de integrações).

Sem PLD histórico suficiente no banco (situação desta sprint, já que a CCEE
está bloqueada na rede de desenvolvimento — seção 5), a curva retorna
`INSUFFICIENT_DATA` de forma honesta em vez de inventar percentil. Assim que
`ccee`/importação manual alimentar 3+ anos de PLD por submercado, a mesma
chamada passa a `OK` sem nenhuma mudança de código.

## 10. Variáveis de ambiente

Ver `.env.example`. Nenhuma delas é obrigatória para ONS/CCEE/EPE/ENSO — só
`EPE_CONSUMO_URL` (sobrescrita opcional) e as quatro `BBCE_API_*` (opcional,
desligado por padrão). Nenhum segredo tem valor de exemplo diferente de
vazio; nenhuma delas é lida de log, teste ou fixture.

## 11. Execução manual e agendamento

```powershell
.\.venv\Scripts\python.exe scripts\update_sector_data.py --source all
.\.venv\Scripts\python.exe scripts\update_sector_data.py --source ons
.\.venv\Scripts\python.exe scripts\update_sector_data.py --source forward --dry-run
```

`--source` aceita `ccee`, `ons`, `epe`, `climate`, `forward` (B3/BBCE +
curva estatística) e `all`. `--dry-run` roda os adapters e mostra o resumo
sem gravar no banco. Cada fonte falha isoladamente; o código de saída é 0
sempre que pelo menos uma fonte respondeu ok/parcial ou nenhuma foi tentada,
e reflete falha total apenas se todas as fontes pedidas falharam.

Também é possível atualizar pela interface: **Dados e fontes → Integrações
→ Atualizar agora** (reusa exatamente os mesmos adapters e a mesma ponte de
persistência do script).

**Agendador de Tarefas do Windows** (não implementado nesta sprint, uso
futuro): criar uma tarefa que execute

```
Programa: C:\projetos\energy-trading-copilot\.venv\Scripts\python.exe
Argumentos: scripts\update_sector_data.py --source all
Iniciar em: C:\projetos\energy-trading-copilot
```

com disparo diário, por exemplo às 07:00 (após a publicação matinal do
ONS). Não é necessário nenhum scheduler adicional (Celery, cron em
container etc.) — o script já é idempotente e seguro para rodar de novo.

## 12. Interpretação das curvas na UI

Aba **Dados e fontes → Curva pública**: seletor de curva e submercado,
tabela de pontos, gráfico por `quote_type`, badge de classificação/origem, e
o aviso metodológico obrigatório quando a curva é a estatística. Curva com
`origin != NEGOCIADA` sempre mostra o aviso de que não é preço negociado e
qual preço está sendo usado como substituto (`proxy_of`).

## 13. Limitações conhecidas

- CCEE não pôde ser validada com chamada real nesta rede de desenvolvimento
  (bloqueio de WAF, HTTP 403) — código pronto, sem dado real coletado aqui.
- Sem PLD histórico de 3+ anos por submercado, a curva estatística fica
  `INSUFFICIENT_DATA` (comportamento esperado, não um bug).
- BBCE e B3/N5X não têm dado real: a primeira por exigir assinatura paga, a
  segunda por não ter endpoint público automatizável verificado.
- O schema do PLD da CCEE (nomes de coluna) não foi confirmado contra uma
  resposta real; o parser tenta variações plausíveis e falha de forma
  legível se nenhuma bater.
- EPE só cobre a planilha `CONSUMO E NUMCONS SAM`; as demais abas do mesmo
  arquivo (setor industrial por UF, séries 1970–2003 etc.) ficam para uma
  próxima sprint.

## 14. Segurança e tratamento de erros

- Nenhuma credencial em código, log, teste, fixture ou URL. `mask_secret`
  mascara token/apiKey antes de qualquer log da chamada BBCE.
- Toda chamada HTTP tem timeout, User-Agent identificável, e trata 4xx/5xx
  sem derrubar o processo — vira `AdapterUnavailable` com motivo legível.
- Content-type inesperado (HTML onde se espera JSON/CSV) é tratado como
  bloqueio/erro, não como dado — evita ingerir página de erro como se fosse
  CSV.
- Toda execução (sucesso, falha ou rejeição por licença) grava uma linha em
  `ingest_snapshots`, nunca só as que deram certo — é o que garante que uma
  fonte indisponível vira alerta de cobertura, não silêncio (RF-36).

## 15. Solução de problemas

| Sintoma | Causa provável | Ação |
|---|---|---|
| `ccee: INDISPONÍVEL ... HTTP 403` | WAF da CCEE bloqueando a rede atual | Rodar de outra rede/IP; não é bug do adapter |
| `epe: INDISPONÍVEL ... layout` | EPE trocou o nome da aba ou das colunas | Ajustar `EpeAdapter.SHEET_NAME`/colunas em `public.py` |
| `bbce_forward: DISABLED_MISSING_CREDENTIALS` | Variáveis de ambiente ausentes | Preencher as quatro `BBCE_API_*` após assinar o plano |
| Curva estatística sempre `INSUFFICIENT_DATA` | Menos de 3 anos de PLD no banco para aquele mês/submercado | Rodar `--source ccee` com sucesso ou importar histórico via CSV manual |
| `ons`/`epe` funcionam localmente mas falham no Streamlit Cloud | Egress de rede bloqueado no ambiente de deploy | Rodar `update_sector_data.py` fora do Cloud e importar o snapshot, ou liberar egress |
