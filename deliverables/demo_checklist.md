# Checklist de demonstração

Status: `PASS` / `FAIL` / `NOT_APPLICABLE`. Nenhuma etapa obrigatória pode
permanecer `NOT_TESTED`.

## Fluxo manual

| # | Etapa | Status | Evidência |
|---|---|---|---|
| 1 | Abrir a aplicação | `NOT_APPLICABLE` | Streamlit não instalável no ambiente de build; `app.py` compila e `verify_agent` valida a importação |
| 2 | Cadastrar tese | `PASS` | `verify_agent.py` etapa 6 |
| 3 | Salvar | `PASS` | `verify_agent.py` etapa 6 |
| 4 | Recuperar após reconexão | `PASS` | `verify_agent.py` etapa 7 (8.760 h, 438.000 MWh preservados) |
| 5 | Iniciar debate | `PASS` | `verify_agent.py` etapa 16 |
| 6 | Consultar documento (RAG) | `PASS` | `verify_agent.py` etapa 15 (com página e vigência) |
| 7 | Calcular risco | `PASS` | `verify_agent.py` etapa 11 |
| 8 | Emitir veredito | `PASS` | `verify_agent.py` etapa 16 |
| 9 | Inserir novo dado | `PASS` | `verify_agent.py` etapa 19 (simulação) |
| 10 | Ativar gatilho | `PASS` | `verify_agent.py` etapa 19 (275 ≥ 260) |
| 11 | Gerar alerta | `PASS` | `verify_agent.py` etapa 19 |
| 12 | Visualizar histórico | `PASS` | `verify_agent.py` etapa 16 (2 rodadas preservadas) |
| 13 | Consultar auditoria | `PASS` | `verify_agent.py` etapa 20 |
| 14 | Exportar resultado | `PASS` | `scripts/build_deliverables.py` |

## Controles

| # | Controle | Status | Evidência |
|---|---|---|---|
| 15 | Premissa sem `evidence_id` é recusada | `PASS` | `verify_agent.py` etapa 17 |
| 16 | Número órfão é bloqueado | `PASS` | `verify_agent.py` etapa 17 |
| 17 | Dado posterior ao corte é bloqueado | `PASS` | `verify_agent.py` etapa 17 |
| 18 | PLD não entra como curva negociada | `PASS` | `verify_agent.py` etapa 9 |
| 19 | Amostra insuficiente não devolve número | `PASS` | `verify_agent.py` etapa 12 |
| 20 | Auditoria não pode ser editada | `PASS` | `verify_agent.py` etapa 20 |
| 21 | Modo demonstração é sinalizado | `PASS` | `LLMResult.mode` = `DEMO` na UI e no audit log |

## Pendente de validação manual pelo candidato

| # | Etapa | Comando |
|---|---|---|
| A | Abrir a interface e navegar as 5 áreas | `streamlit run app.py` |
| B | Registro ao vivo cronometrado (meta ≤ 10 min) | Teses → Cadastrar |
| C | Watchdog em modo contínuo | `python scripts/run_watchdog.py --interval 300` |
