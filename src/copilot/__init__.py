"""Energy Trading Copilot — mesa virtual de trading de energia.

Sprint 1: fundacao, configuracao, banco de dados e persistencia.
As camadas de RAG, agentes, Watchdog e UI completa entram nas sprints seguintes;
aqui existem apenas os contratos (`copilot.contracts`) que elas consumirao.
"""

__version__ = "0.1.0"

# Versao do codigo gravada em `quant_run.code_version` e em `audit_log.agent_version`
# para garantir reprodutibilidade (RF-56).
CODE_VERSION = __version__
