# AGENT_READY

O agente foi construído, executado e aprovado. **A Fase A está concluída** e a
Entrega 2 pode ser iniciada.

- **Data:** 08/08/2026
- **Python validado:** 3.10.12 (o projeto tem como alvo 3.12; o núcleo é compatível com 3.10+)
- **Modo validado:** DEMONSTRAÇÃO (sem `ANTHROPIC_API_KEY`). O modo real usa o mesmo caminho de código, trocando apenas a redação dos agentes.

## Comandos executados

```bash
python scripts/init_db.py
python scripts/seed_demo.py
python scripts/verify_agent.py     # -> 0
python scripts/build_deliverables.py
python scripts/verify_mvp.py       # -> 0
```

## Resultado dos testes

| Suíte | Resultado |
|---|---|
| `verify_agent.py` | **21/21 PASS** — código de saída 0 |
| `verify_mvp.py` | **5 PASS, 1 N/A, 0 FAIL** — código de saída 0 |
| Testes puros (quant, ingestão, adapters, arquivos) | **210 passed, 0 failed** |
| Compilação (`compileall`) | sem erro em `src/`, `scripts/`, `tests/`, `app.py` |

Detalhe das 21 verificações: dependências, banco, schema (28 tabelas), seed,
importação da aplicação, criação de tese, persistência após reconexão, importação
de curva, bloqueio de PLD como curva negociada, P&L comprado/vendido, VaR e
consumo do limite, amostra insuficiente, cenários hidrológicos, ingestão de
documento, RAG com página e vigência, debate com veredito, Claim Verifier
(5 vetores adversariais), Watchdog, gatilho→alerta persistente, audit log
append-only, documentação obrigatória.

## Integrações reais

| Fonte | Status | Observação |
|---|---|---|
| NOAA CPC (ONI/ENSO) | `MANUAL_IMPORT` | Adapter implementado e testado offline. Vira `LIVE_VALIDATED` na primeira chamada com rede |
| ONS, CCEE, ANEEL, ANA, INMET, CPTEC, ECMWF | `NOT_CONFIGURED` | Interfaces declaradas; aparecem como indisponíveis no relatório de cobertura |
| BBCE, DCIDE | `NOT_CONFIGURED` | **Licenciadas** — bloqueadas sem autorização escrita |
| Simulação da mesa | `DEMO` | Seed sintético, rotulado em toda a interface |

Nenhuma fonte foi promovida a `LIVE_VALIDATED`: isso exige chamada real com
schema validado e observação persistida.

## Fallbacks em uso

| Situação | Fallback aplicado |
|---|---|
| PostgreSQL/Supabase | SQLite local (stdlib) |
| pgvector / embeddings | FTS5 lexical |
| PyMuPDF ausente | `pypdf` |
| Anthropic API ausente | Modo demonstração explícito |
| API pública indisponível | Upload CSV/XLSX + snapshot local |
| WAL não suportado (pasta de rede) | `journal_mode=DELETE` automático |
| Scheduler | `run_watchdog.py --once` / `--interval` + botão na UI |

## Limitações

- **Streamlit não foi executado no ambiente de build** (não instalável ali). `app.py` compila e a importação é verificada; a interface precisa ser aberta uma vez com `streamlit run app.py`.
- Modo IA real não exercitado: sem chave no ambiente de build. O caminho de código é o mesmo; muda a origem do texto.
- Banco SQLite local, sem multiusuário concorrente.
- RAG lexical: busca por sinônimo é limitada.
- Detecção de número órfão é léxica; número por extenso escapa.

## Roteiro mínimo de uso

```bash
pip install -r requirements.txt
cp .env.example .env
python scripts/init_db.py && python scripts/seed_demo.py
streamlit run app.py
```

1. **Teses → Cadastrar** — registre uma tese com premissas, posição e gatilhos.
2. **Debate → Executar** — leia a contestação do Risco e o veredito.
3. **Monitor → Simular atualização** — dispare um gatilho e veja o alerta.
4. **Dados e fontes → Auditoria** — confira que a trilha não pode ser editada.
