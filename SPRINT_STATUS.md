# SPRINT_STATUS

**Estado:** MVP executável entregue. Fase A concluída e aprovada.
**Data:** sábado, 08/08/2026
**Próximo marco:** 14/08/2026 — carregar dados reais e gerar a Entrega 2.

---

## Resultado da execução

| Verificação | Resultado |
|---|---|
| `python scripts/verify_agent.py` | **21/21 PASS — código 0** |
| `python scripts/verify_mvp.py` | **5 PASS, 1 N/A, 0 FAIL — código 0** |
| Testes puros (quant, ingestão, adapters, arquivos) | **210 passed, 0 failed** |
| `python -m compileall` | sem erro |
| `AGENT_READY.md` | criado |
| Entrega 2 | estruturada; ver `READY_FOR_ENTREGA_2.md` |

## Decisão de arquitetura desta etapa

O núcleo foi construído em **stdlib + sqlite3 + FTS5** (ADR-011, ADR-012). Motivo:
a camada SQLAlchemy/Alembic dos Sprints 1–2 nunca chegou a ser executada, e o
ambiente de build não permite instalar dependências binárias. Com stdlib, banco,
RAG, motor quantitativo, Claim Verifier, Watchdog, debate e entregáveis **rodam e
são verificados de ponta a ponta**.

A camada SQLAlchemy foi **preservada** em `src/copilot/db/` como caminho de
evolução para PostgreSQL/Supabase. O motor quantitativo (`src/copilot/quant/`) e a
ingestão (`src/copilot/ingest/`) foram reaproveitados na íntegra — já eram stdlib.

## O que foi construído

| Camada | Arquivos |
|---|---|
| Persistência | `src/database/` — schema (28 tabelas), conexão, repositórios, auditoria append-only por trigger |
| Registrar | `src/services/thesis_service.py` |
| Desafiar | `src/services/debate_service.py` + `src/agents/` (5 agentes) |
| Vigiar | `src/services/watchdog_service.py` + `scripts/run_watchdog.py` |
| Risco | `src/services/risk_service.py` sobre `copilot.quant` |
| Antialucinação | `src/services/claim_verifier.py` |
| RAG | `src/rag/` — FTS5 + leitura de PDF com fallback |
| Interface | `app.py` — 5 áreas |
| Scripts | `init_db`, `seed_demo`, `run_watchdog`, `verify_agent`, `verify_mvp`, `build_deliverables`, `freeze_case_snapshot`, `verify_entrega_2` |
| Documentação | 9 documentos em `docs/` |
| Entregáveis | 7 documentos + one-pager PDF (1 pág.) + planilha (8 abas, 44 fórmulas) |

## Pendências reais

1. **Streamlit não foi executado** — não instalável no ambiente de build. `app.py`
   compila e a importação é verificada. Rode `streamlit run app.py` uma vez e
   atualize `deliverables/demo_checklist.md`, item A.
2. **`pytest -q` não foi executado** — pytest indisponível no build. Os mesmos 21
   fluxos foram cobertos por `verify_agent.py`.
3. **Modo IA real não exercitado** — sem chave no build. Caminho de código idêntico.
4. **Nenhuma fonte em `LIVE_VALIDATED`** — exige chamada real com schema validado.
5. **Entrega 2 aguarda 14/08/2026.**

## Dúvidas à banca (prazo 10/08)

| # | Dúvida | Contorno adotado |
|---|---|---|
| D-01 | Definição do VaR de R$ 50 mi: confiança, horizonte, metodologia, isolado ou consolidado | 95%, 21 dias úteis, consolidado (premissa PR-03, declarada no resultado) |
| D-02 | Autorização para dados licenciados (BBCE/DCIDE) | Bloqueados; proxy público declarado e penalizado |
| D-04 | Limite *hard* ou *soft* | *Hard*: veredito `BLOQUEADA_POR_RISCO` |
