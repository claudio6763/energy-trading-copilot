# Matriz de atendimento ao case

`PASS` = implementado e verificado por execução. `PARTIAL` = implementado com
limitação declarada. `BLOCKED` = depende de insumo externo. `NOT_APPLICABLE`.

| # | Requisito | Arquivo / tela | Teste | Status | Evidência | Pendência |
|---|---|---|---|---|---|---|
| 1 | Registrar tese estruturada | `src/services/thesis_service.py` · Teses | `verify_agent` 6 | PASS | 24 campos, premissas, riscos, fontes, gatilhos | — |
| 2 | Resumo em até 5 linhas | `thesis_service.validate_summary` | `verify_agent` 6 | PASS | Recusa 6+ linhas | — |
| 3 | Resultado esperado como intervalo | `thesis_service.validate_range` | `verify_agent` 6 | PASS | Recusa número único | — |
| 4 | Persistência após reinício | `src/database/connection.py` | `verify_agent` 7 | PASS | Grafo íntegro em nova conexão | — |
| 5 | Versionamento de tese | `thesis_service.new_version` | — | PASS | Copia premissas, posições e gatilhos | — |
| 6 | Desafiar: debate entre 5 agentes | `src/agents/` · Debate | `verify_agent` 16 | PASS | 4 etapas + veredito, ≤ 4 chamadas LLM | — |
| 7 | Contra-tese e premissa frágil | `specialists.RiskAgent` | `verify_agent` 16 | PASS | Campos `counter_thesis`, `weakest_assumption` | — |
| 8 | Identificar vieses | `debate_service._detect_bias` | `verify_agent` 16 | PASS | Critério numérico, não opinião | — |
| 9 | Réplica do trader | `debate_service.add_reply` | `verify_agent` 16 | PASS | Persistida sem apagar histórico | — |
| 10 | Nova rodada preserva histórico | `debate_service.run_debate` | `verify_agent` 16 | PASS | `round_number` incrementa | — |
| 11 | Vigiar automático (sem UI) | `scripts/run_watchdog.py` | `verify_agent` 18 | PASS | `--once` e `--interval` | — |
| 12 | Gatilho gera alerta persistente | `watchdog_service` · Monitor | `verify_agent` 19 | PASS | 275 ≥ 260 dispara; alerta com `evidence_id` | — |
| 13 | Inserir dado ao vivo e reavaliar | `simulate_market_update` · Monitor | `verify_agent` 19 | PASS | Insere, dispara, recalcula, audita | — |
| 14 | Explicar por que reavaliar | `alerts.explanation` | `verify_agent` 19 | PASS | Texto por alerta | — |
| 15 | Nenhum número inventado pelo LLM | `claim_verifier.py` | `verify_agent` 17 | PASS | 5 vetores adversariais bloqueados | — |
| 16 | Todo valor com `evidence_id` | `repositories.create_evidence` | `verify_agent` 17 | PASS | Geração automática | — |
| 17 | Bloqueio de dado posterior ao corte | `claim_verifier.verify` | `verify_agent` 17 | PASS | Corte 2026-08-14 | — |
| 18 | IA separada de cálculo determinístico | `docs/ai_governance.md` | `verify_agent` 11,17 | PASS | Quant sem LLM; veredito é função pura | — |
| 19 | Limite de VaR de R$ 50 mi | `risk_limits` · `quant/limits.py` | `verify_agent` 11 | PASS | No banco; fronteira testada | — |
| 20 | VaR paramétrico, EWMA, histórico | `quant/var.py` | `test_var.py` (37) | PASS | Máximo dos três é o adotado | — |
| 21 | P&L comprado e vendido | `quant/pnl.py` | `verify_agent` 10 | PASS | Simetria exata verificada | — |
| 22 | Horas do período | `quant/periods.py` | `test_periods.py` (17) | PASS | 8.760 / 8.784 bissexto | — |
| 23 | Cenários seco/base/úmido/extremo | `quant/scenarios.py` | `verify_agent` 13 | PASS | 4 cenários; ≥ 2 hidrológicos | — |
| 24 | Amostra insuficiente | `quant/var.py` | `verify_agent` 12 | PASS | Levanta exceção, não devolve número | — |
| 25 | Add-on de proxy / risco de modelo | `quant/addons.py` | `test_addons_limits.py` | PASS | PLD = 25%, o mais caro | — |
| 26 | PLD/CMO não são curva forward | `uploads.py` · `schema.sql` | `verify_agent` 9 | PASS | Bloqueado no adapter e no banco | — |
| 27 | Margem / NPV até 31/12 | `risk_service.npv_to_year_end` | — | PASS | Desconto pro rata, taxa declarada | — |
| 28 | RAG com página e citação | `src/rag/store.py` | `verify_agent` 15 | PASS | FTS5; instituição, versão, página, vigência | — |
| 29 | Filtro por vigência | `store.search` | `verify_agent` 15 | PASS | Regra revogada não retorna | — |
| 30 | Prompt injection neutralizada | `store.sanitize` | `verify_agent` 15 | PASS | Documento é dado, não comando | — |
| 31 | Importação CSV/XLSX validada | `copilot/ingest/files.py` | `test_ingest_files.py` (40) | PASS | XLSX em stdlib puro | — |
| 32 | Catálogo de fontes e freshness | `sources` · Dados e fontes | `verify_agent` 18 | PASS | 12 fontes; alerta > 10 dias | — |
| 33 | Snapshots auditáveis | `copilot/ingest/snapshots.py` | `test_adapters.py` (48) | PASS | Hash SHA-256 + metadados | — |
| 34 | Integração pública funcional | `adapters/public.py` (ENSO/ONI) | `test_adapters.py` | PARTIAL | Adapter implementado e testado offline | Sem rede no build: status `MANUAL_IMPORT`, não `LIVE_VALIDATED` |
| 35 | ONS/CCEE/ANEEL/ANA/clima | `adapters/public.py` | `test_adapters.py` | PARTIAL | Interfaces declaradas, visíveis como indisponíveis | Endpoints não verificados |
| 36 | Audit log completo | `audit_log` · Auditoria | `verify_agent` 20 | PASS | Append-only por trigger de banco | — |
| 37 | Modo demonstração explícito | `llm_client.py` · UI | `verify_agent` 5 | PASS | `mode=DEMO` na UI e no audit log | — |
| 38 | Aplicação inicia sem credencial | `src/config.py` | `verify_agent` 5 | PASS | Sem chave, sobe em DEMO | — |
| 39 | Interface com 5 áreas | `app.py` | `verify_agent` 5 | PARTIAL | Compila; 5 áreas implementadas | Streamlit não instalável no ambiente de build — validar com `streamlit run app.py` |
| 40 | One-pager (1 página) | `deliverables/entrega_1_one_pager.*` | `build_deliverables` | PASS | Markdown + PDF | — |
| 41 | Respostas sobre IA | `respostas_questoes_ia.md` | `verify_agent` 21 | PASS | 6 perguntas respondidas | — |
| 42 | Erro real da IA | `ai_error_log.md` | `verify_agent` 21 | PASS | 4 erros reais, com o teste que pegou cada um | — |
| 43 | Anexo de prompts | `prompts_appendix.md` | `verify_agent` 21 | PASS | Prompts íntegros | — |
| 44 | Roteiro da defesa 15/20/25 | `defense_script_60min.md` | `verify_agent` 21 | PASS | Com perguntas prováveis | — |
| 45 | Documentação completa | `docs/` (9 arquivos) | `verify_agent` 21 | PASS | Comandos testados | — |
| 46 | Entrega 2: posição oficial | `deliverables/entrega_2_*` | `verify_entrega_2` | BLOCKED | Pipeline pronto e testado | Dados reais de 14/08/2026 não existem em 08/08/2026. Ver `READY_FOR_ENTREGA_2.md` |
| 47 | Planilha aberta com fórmulas | `entrega_2_modelo.xlsx` | `build_deliverables` | PASS | 8 abas, fórmulas vivas, sem valor colado | Preenchida com dados reais na geração oficial |
| 48 | Limite de páginas (1 + 2) | `build_deliverables.py` | `verify_mvp` | PASS | Validado com `pypdf` | — |
