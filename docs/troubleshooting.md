# Troubleshooting

Cada item: sintoma, causa provável, diagnóstico, solução, fallback.

## A aplicação não inicia

- **Sintoma:** `streamlit: command not found` ou `ModuleNotFoundError`.
- **Causa:** ambiente virtual não ativado.
- **Diagnóstico:** `python -c "import streamlit; print(streamlit.__version__)"`.
- **Solução:** ative o venv e `pip install -r requirements.txt`.
- **Fallback:** o núcleo roda sem Streamlit — use `scripts/verify_agent.py` e `scripts/run_watchdog.py`.

## Dependência ausente

- **Sintoma:** `ModuleNotFoundError: pymupdf`.
- **Causa:** roda binária indisponível para a plataforma.
- **Diagnóstico:** `python -c "import fitz"`.
- **Solução:** `pip install pymupdf`.
- **Fallback:** o leitor cai automaticamente para `pypdf`.

## Banco bloqueado / disk I/O error

- **Sintoma:** `sqlite3.OperationalError: database is locked` ou `disk I/O error`.
- **Causa:** banco em pasta de rede, OneDrive ou montagem que não suporta lock.
- **Diagnóstico:** `python scripts/init_db.py` e veja o caminho impresso.
- **Solução:** aponte `COPILOT_DB` para um disco local (`C:\\dados\\copilot.db`).
- **Fallback:** o sistema já troca WAL por DELETE automaticamente.

## Erro no upload

- **Sintoma:** "Arquivo rejeitado: N problemas de validação".
- **Causa:** cabeçalho, tipo ou campo obrigatório vazio.
- **Diagnóstico:** a mensagem traz linha e coluna.
- **Solução:** corrija e reenvie. Ver `docs/data_guide.md`.
- **Fallback:** cadastre a observação manualmente pela interface.

## PDF sem texto

- **Sintoma:** "nenhuma página com texto".
- **Causa:** PDF digitalizado sem OCR.
- **Diagnóstico:** abra o PDF e tente selecionar texto.
- **Solução:** `ocrmypdf entrada.pdf saida.pdf`.
- **Fallback:** cole o trecho num `.txt` e ingira o arquivo de texto.

## RAG sem resultado

- **Sintoma:** "Regra não confirmada nas fontes disponíveis."
- **Causa:** acervo vazio, ou filtro de vigência excluiu o documento.
- **Diagnóstico:** **Dados e fontes → Documentos** e confira `effective_from`.
- **Solução:** ingira o documento com a vigência correta.
- **Fallback:** é o comportamento correto — melhor não confirmar do que inventar.

## Anthropic API indisponível

- **Sintoma:** banner de modo demonstração mesmo com chave.
- **Causa:** chave inválida, sem crédito, ou `DEMO_MODE=true`.
- **Diagnóstico:** veja `audit_log`, ação `LLM_CALL`, campo de erro.
- **Solução:** confira a chave e defina `DEMO_MODE=false`.
- **Fallback:** modo demonstração — todos os números continuam corretos.

## Fonte externa indisponível

- **Sintoma:** adapter retorna `INDISPONÍVEL`.
- **Causa:** sem rede ou endpoint mudou.
- **Diagnóstico:** o resultado traz o motivo declarado.
- **Solução:** reprocesse um snapshot com `payload=`.
- **Fallback:** upload manual de CSV.

## Curva inválida

- **Sintoma:** `ProxyNotDeclaredError`.
- **Causa:** curva de PLD/CMO declarada como `NEGOCIADA`, ou `PROXY_SPOT` sem `proxy_of`.
- **Diagnóstico:** confira o nome e a origem da curva.
- **Solução:** use `origin=PROXY_SPOT` e informe `proxy_of`.
- **Fallback:** nenhum — é uma regra dura do produto.

## VaR não calculado / amostra insuficiente

- **Sintoma:** "Dados insuficientes para cálculo confiável."
- **Causa:** menos de 20 retornos (paramétrico) ou 60 (histórico), ou buraco > 7 dias.
- **Diagnóstico:** **Dados e fontes → freshness**.
- **Solução:** importe mais histórico da métrica.
- **Fallback:** nenhum — número fraco é pior que nenhum número.

## Watchdog não executa

- **Sintoma:** nenhuma execução em **Monitor**.
- **Causa:** script não iniciado, ou nenhuma tese em estado vigiável.
- **Diagnóstico:** `python scripts/run_watchdog.py --once`.
- **Solução:** a tese precisa estar em `EM_DEBATE`, `APROVADA`, `ATIVA` ou `EM_REVISAO`.
- **Fallback:** botão **Executar Watchdog agora**.

## Alerta não dispara

- **Sintoma:** dado fora da faixa e nenhum alerta.
- **Causa:** gatilho inativo, métrica com nome diferente, ou alerta já aberto (deduplicação).
- **Diagnóstico:** confira `triggers.metric` e o nome exato da observação.
- **Solução:** corrija a métrica ou reconheça o alerta anterior.
- **Fallback:** **Simular atualização de mercado** para testar a regra.

## Entregável não é gerado

- **Sintoma:** `build_deliverables.py` falha.
- **Causa:** `openpyxl` ou `reportlab` ausente.
- **Diagnóstico:** `python -c "import openpyxl, reportlab"`.
- **Solução:** `pip install openpyxl reportlab pypdf`.
- **Fallback:** os arquivos `.md` são gerados mesmo sem as bibliotecas de PDF/XLSX.
