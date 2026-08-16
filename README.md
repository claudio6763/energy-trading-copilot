# Energy Trading Copilot

Mesa virtual de trading de energia. O trader **registra** uma tese, **debate** com
agentes especializados e o sistema **vigia** as premissas contra o mercado.

O que o produto garante, por construção:

- **nenhum número factual vem do LLM** — todo valor tem `evidence_id`, fonte, unidade e data-base;
- **cálculo é Python determinístico** — VaR, P&L e cenários nunca passam por modelo de linguagem;
- **PLD e CMO não são curva forward** — se usados como referência, são declarados e penalizados;
- **a trilha de auditoria é append-only** — garantido por trigger no banco, não pelo código;
- **a aplicação inicia sem credencial externa** — modo demonstração explícito, nunca disfarçado de IA.

## Quickstart (10 minutos)

Requisito: **Python 3.12**.

### Linux / macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/init_db.py
python scripts/seed_demo.py
pytest -q
streamlit run app.py
```

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python scripts\init_db.py
python scripts\seed_demo.py
pytest -q
streamlit run app.py
```

A interface abre em <http://localhost:8501>.

### Watchdog (vigilância sem a interface aberta)

```bash
python scripts/run_watchdog.py --once
python scripts/run_watchdog.py --interval 300
```

### Verificação e entregáveis

```bash
python scripts/verify_agent.py        # trava de liberação do agente (retorna 0 ou 1)
python scripts/build_deliverables.py  # gera one-pager, planilha e PDFs
python scripts/verify_mvp.py          # verificador ponta a ponta
```

### Dados do setor elétrico (ONS, CCEE, EPE, curva forward)

```bash
python scripts/update_sector_data.py --source all       # todas as fontes
python scripts/update_sector_data.py --source ons        # só uma fonte
python scripts/update_sector_data.py --source forward --dry-run  # roda sem gravar
```

ONS, CCEE e EPE são públicas e não exigem credencial. Detalhes, matriz de
status e limitações verificadas: [docs/CONEXOES_DADOS_SETOR.md](docs/CONEXOES_DADOS_SETOR.md).

## Modo demonstração x modo real

Sem `ANTHROPIC_API_KEY` no `.env`, a aplicação sobe em **modo demonstração**: os
textos dos agentes são roteiros determinísticos, sinalizados na interface como
*"não é IA"*. Os números continuam vindo do banco e do motor quantitativo — ou
seja, risco, cenários, gatilhos e alertas funcionam igual.

Para o modo real: preencha `ANTHROPIC_API_KEY` e defina `DEMO_MODE=false`.

## Estrutura

```text
app.py                  Interface Streamlit (5 áreas)
src/database/           SQLite: schema, conexão, repositórios, auditoria
src/services/           Registrar, Desafiar, Vigiar, risco, Claim Verifier
src/agents/             Orquestrador, Trader, Risco, Regulatório, Mercado
src/rag/                RAG lexical sobre FTS5 + leitura de PDF
src/copilot/quant/      Motor quantitativo determinístico (stdlib)
src/copilot/ingest/     Adapters, validação de CSV/XLSX, snapshots
scripts/                init_db, seed_demo, run_watchdog, verify_*, build_deliverables
docs/                   Instalação, manual, dados, RAG, risco, governança de IA
deliverables/           One-pager, matriz do case, roteiro de defesa, Entrega 2
tests/                  Testes essenciais
```

## Documentação

| Documento | Para quê |
|---|---|
| [docs/CONEXOES_DADOS_SETOR.md](docs/CONEXOES_DADOS_SETOR.md) | ONS, CCEE, EPE, curva forward pública/licenciada e cenário estatístico |
| [docs/installation.md](docs/installation.md) | Instalar em Windows, Linux e macOS |
| [docs/user_guide.md](docs/user_guide.md) | Usar a ferramenta do início ao fim |
| [docs/data_guide.md](docs/data_guide.md) | Importar dados e substituir os demonstrativos |
| [docs/data_sources.md](docs/data_sources.md) | Catálogo de fontes e status das integrações |
| [docs/rag_methodology.md](docs/rag_methodology.md) | Ingerir e consultar documentos regulatórios |
| [docs/risk_methodology.md](docs/risk_methodology.md) | Fórmulas, premissas e limitações |
| [docs/ai_governance.md](docs/ai_governance.md) | Onde há IA, onde não há, e por quê |
| [docs/architecture.md](docs/architecture.md) | Decisões de arquitetura |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Sintoma, causa, diagnóstico, solução, fallback |

## Limitações declaradas

- O banco padrão é SQLite local. Não há multiusuário concorrente.
- O RAG é lexical (FTS5). Não há embeddings — busca por sinônimo é limitada.
- ONS e EPE estão `LIVE_VALIDATED` (chamada real feita e validada). CCEE está
  com o código pronto mas bloqueado por WAF na rede de desenvolvimento usada
  aqui (HTTP 403). BBCE e B3/N5X seguem sem dado real — ver
  [docs/CONEXOES_DADOS_SETOR.md](docs/CONEXOES_DADOS_SETOR.md).
- Os dados do seed são **demonstrativos** e assim rotulados em toda a interface.
