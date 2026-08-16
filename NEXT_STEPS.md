# NEXT_STEPS

Estado atual: **agente aprovado** (`AGENT_READY.md`), Fase A concluída,
Entrega 2 estruturada e aguardando dados reais (`READY_FOR_ENTREGA_2.md`).

## 1. Validar a interface (única etapa não executada)

```bash
pip install -r requirements.txt
streamlit run app.py --server.headless true
```

Confira as 5 áreas: Dashboard, Teses, Debate, Monitor, Dados e fontes.
Atualize `deliverables/demo_checklist.md`, item A, de `NOT_APPLICABLE` para `PASS`.

## 2. Rodar a suíte pytest

```bash
pytest -q
```

Cobre 21 fluxos em `tests/mvp/test_end_to_end.py` mais os testes de quant e
ingestão. No ambiente de build o pytest não estava instalável; os mesmos fluxos
foram verificados por `scripts/verify_agent.py` (21/21).

## 3. Ativar o modo IA real

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
DEMO_MODE=false
```

A barra lateral deve mostrar **Modo REAL**. Rode um debate e confira em
**Dados e fontes → Auditoria** que a ação `LLM_CALL` gravou modelo e prompt.

## 4. Promover a integração ENSO a LIVE_VALIDATED

```bash
python -c "
from copilot.ingest.adapters.public import EnsoOniAdapter
from datetime import date
r = EnsoOniAdapter().run(as_of=date(2026,8,14))
print(r.summary())
"
```

Com rede, o adapter busca o ONI do NOAA. Persista as observações e atualize o
status da fonte com `mark_source_success`.

## 5. Em 14/08/2026 — gerar a Entrega 2

Siga `READY_FOR_ENTREGA_2.md`.

## Comandos de verificação (sempre)

```bash
python scripts/verify_agent.py    # 21/21, retorna 0
python scripts/verify_mvp.py      # retorna 0
python scripts/run_watchdog.py --once
```
