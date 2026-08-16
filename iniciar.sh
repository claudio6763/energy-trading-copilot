#!/usr/bin/env bash
# ===================================================================
#  Energy Trading Copilot - iniciar (Linux / macOS)
#  Faz tudo: ambiente, dependencias, banco, dados e abre o navegador.
# ===================================================================
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "  ==============================================="
echo "   ENERGY TRADING COPILOT"
echo "  ==============================================="
echo

# --- 1. Encontrar o Python -----------------------------------------
PY=""
for candidato in python3.12 python3.11 python3; do
    if command -v "$candidato" >/dev/null 2>&1; then PY="$candidato"; break; fi
done
if [ -z "$PY" ]; then
    echo "  [ERRO] Python 3 nao encontrado."
    echo "  Instale com: brew install python@3.12   (macOS)"
    echo "               sudo apt install python3.12 python3.12-venv   (Ubuntu)"
    exit 1
fi
echo "  [1/5] Python encontrado: $($PY --version)"

# --- 2. Ambiente virtual -------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
    echo "  [2/5] Criando ambiente virtual (primeira vez, ~1 min)..."
    "$PY" -m venv .venv
else
    echo "  [2/5] Ambiente virtual ja existe."
fi
VENV_PY=".venv/bin/python"

# --- 3. Dependencias -----------------------------------------------
if ! "$VENV_PY" -c "import streamlit" >/dev/null 2>&1; then
    echo "  [3/5] Instalando dependencias (primeira vez, 2-4 min)..."
    "$VENV_PY" -m pip install --upgrade pip --quiet
    "$VENV_PY" -m pip install -r requirements.txt --quiet
else
    echo "  [3/5] Dependencias ja instaladas."
fi

# --- 4. Configuracao e banco ---------------------------------------
[ -f .env ] || cp .env.example .env
echo "  [4/5] Preparando banco de dados..."
"$VENV_PY" scripts/init_db.py

if ! "$VENV_PY" - <<'PY' >/dev/null 2>&1
import sys, pathlib
sys.path[:0] = [".", "src"]
from src.database.connection import connect
c = connect()
n = c.execute("SELECT COUNT(*) FROM market_observations").fetchone()[0]
c.close()
sys.exit(0 if n > 0 else 1)
PY
then
    echo "        Carregando dados demonstrativos..."
    "$VENV_PY" scripts/seed_demo.py
fi

# --- 5. Abrir a aplicacao ------------------------------------------
echo "  [5/5] Abrindo no navegador..."
echo
echo "  ---------------------------------------------------"
echo "   Endereco: http://localhost:8501"
echo "   Para encerrar: Ctrl+C"
echo "  ---------------------------------------------------"
echo
exec "$VENV_PY" -m streamlit run app.py
