"""Coloca `src/` e a raiz no sys.path para os testes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for caminho in (str(ROOT), str(ROOT / "src")):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
