# Instalação

## Requisitos

- **Python 3.12** (o núcleo roda em 3.10+, mas o projeto é validado em 3.12)
- 200 MB de disco
- Nenhum banco externo: o SQLite vem na stdlib

## Windows (PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python scripts\init_db.py
python scripts\seed_demo.py
```

Se o PowerShell recusar a ativação:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Linux / macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/init_db.py
python scripts/seed_demo.py
```

## Variáveis de ambiente

| Variável | Padrão | Para quê |
|---|---|---|
| `ANTHROPIC_API_KEY` | vazio | Modo IA real. Vazio = modo demonstração |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Modelo usado no debate |
| `LLM_EFFORT` | `medium` | Esforço de raciocínio |
| `LLM_MAX_OUTPUT_TOKENS` | `4000` | Teto por chamada |
| `DEMO_MODE` | `true` | `true` força roteiro determinístico |
| `DATA_CUT_OFF` | `2026-08-14` | Corte oficial do case |
| `VAR_LIMIT_BRL` | `50000000.00` | Limite de VaR da mesa |
| `COPILOT_DB` | `data/copilot.db` | Caminho do banco |

## Anthropic API

1. Gere a chave em <https://console.anthropic.com>.
2. Coloque em `.env`: `ANTHROPIC_API_KEY=sk-ant-...`
3. Mude `DEMO_MODE=false`.
4. Reinicie a aplicação. A barra lateral deve mostrar **Modo REAL**.

Sem chave, tudo funciona exceto a redação dos agentes por IA — e isso fica
avisado na tela.

## Erros comuns de instalação

| Erro | Solução |
|---|---|
| `python: command not found` | Use `py -3.12` (Windows) ou `python3.12` |
| `ModuleNotFoundError: streamlit` | O venv não está ativo. Reative e reinstale |
| `sqlite3.OperationalError: disk I/O error` | Banco em pasta de rede/OneDrive. Aponte `COPILOT_DB` para disco local |
| `pymupdf` não instala | Ignore: o projeto cai para `pypdf` automaticamente |
| `pip` lento ou bloqueado | Use `pip install --index-url https://pypi.org/simple -r requirements.txt` |
