"""Coloca `src/` e a raiz no sys.path para os testes."""
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
for caminho in (str(ROOT), str(ROOT / "src")):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
_POSTGRES_URL_RE = re.compile(r"^postgres(ql)?(\+\w+)?://")  # mesma regra de connection.py


def _aponta_para_postgres_remoto(valor: str | None) -> bool:
    """`True` só para uma URL de Postgres que não seja local (produção/Neon)."""
    if not valor or not _POSTGRES_URL_RE.match(valor):
        return False
    return not any(host in valor for host in _LOCAL_HOSTS)


@pytest.fixture(autouse=True)
def _bloquear_postgres_remoto_fora_do_marcador(request, monkeypatch):
    """Trava: teste sem o marcador `postgres` nunca pode ver uma
    `DATABASE_URL`/`COPILOT_DB` remota no ambiente — a variavel e removida
    ANTES do corpo do teste rodar, ou seja, antes de qualquer `connect()`.

    Sem isso, `.env` configurado para o deploy (Neon) faz qualquer teste que
    não isole o backend (ou que dependesse do bug de `connect(path=...)`
    ignorar `path` explicito) conectar em produção sem avisar — foi
    exatamente o que poluiu o Neon numa sessão de validação (ver
    DECISOES.md, "Incidente: poluição do Neon por teste").
    """
    if "postgres" not in request.node.keywords:
        for nome in ("DATABASE_URL", "COPILOT_DB"):
            if _aponta_para_postgres_remoto(os.environ.get(nome)):
                monkeypatch.delenv(nome, raising=False)
    yield
