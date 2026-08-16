"""Smoke test da tela Registrar tese: carrega, gera o book com o motor real
e o ladder aparece — sem exception, sem número inventado."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[2] / "app.py")


@pytest.fixture()
def app_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DB", str(tmp_path / "registrar_smoke.db"))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_MODE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from src.config import reset_settings
    reset_settings()

    # `_garantir_schema()` em app.py e @st.cache_resource SEM argumentos: numa
    # suite com varios testes usando tmp_path (COPILOT_DB) diferentes, o
    # cache do primeiro teste faz o init_db() dos seguintes virar no-op contra
    # o arquivo errado. Garantir o schema aqui, uma vez por teste, evita
    # depender da ordem de execucao.
    from src.database.connection import init_db
    init_db().close()


def _rodar_desafiar_e_responder(at, resposta="Concordo com o risco, mas a folga até o limite justifica manter o tamanho."):
    desafiar = [b for b in at.button if b.label == "Rodar Desafiar"]
    assert desafiar, "botao 'Rodar Desafiar' nao encontrado"
    desafiar[0].click().run()
    campos = [ta for ta in at.text_area if ta.key == "registrar_trader_response"]
    assert campos, "campo de resposta do trader nao encontrado apos Desafiar"
    campos[0].set_value(resposta).run()


def test_salvar_fica_bloqueado_sem_desafiar(app_env):
    """Etapa 3 e bloqueante: sem rodar Desafiar, 'Salvar tese' fica desabilitado."""
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    [b for b in at.button if b.label == "Gerar book"][0].click().run()
    assert not at.exception

    salvar = [b for b in at.button if b.label == "Salvar tese"][0]
    assert salvar.disabled is True

    _rodar_desafiar_e_responder(at)
    salvar = [b for b in at.button if b.label == "Salvar tese"][0]
    assert salvar.disabled is False


def test_registrar_tese_gera_book_do_motor(app_env):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception
    assert at.sidebar.radio[0].value == "Registrar tese"  # e o default agora

    botoes = [b for b in at.button if b.label == "Gerar book"]
    assert botoes, "botao 'Gerar book' nao encontrado na Etapa 1"
    botoes[0].click().run()
    assert not at.exception

    texto = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Book proposto" in texto or any(
        "Book proposto" in h.value for h in at.subheader
    )

    metricas = {m.label: m.value for m in at.metric}
    assert any("Energia" in k for k in metricas)
    assert any("Notional" in k for k in metricas)


def test_registrar_tese_salva_e_persiste_apos_reconexao(app_env, tmp_path):
    # `_garantir_schema()` em app.py e @st.cache_resource sem argumentos: dentro
    # do mesmo processo pytest, uma segunda AppTest com outro COPILOT_DB nao
    # reaciona o init_db(). Mesmo padrao do `_seed()` de test_app_smoke.py —
    # garante o schema no arquivo-alvo antes de subir o app.
    from src.database.connection import init_db
    init_db().close()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    [b for b in at.button if b.label == "Gerar book"][0].click().run()
    assert not at.exception
    _rodar_desafiar_e_responder(at)

    salvar = [b for b in at.button if b.label == "Salvar tese"]
    assert salvar, "botao 'Salvar tese' nao encontrado"
    salvar[0].click().run()
    assert not at.exception
    sucesso = " ".join(s.value for s in at.success)
    assert "Tese registrada" in sucesso, f"sem mensagem de sucesso: {sucesso!r}; erros: {[e.value for e in at.error]}"

    # conexao NOVA — prova que nao e estado de sessao.
    from src.database.connection import connect
    from src.services import motor_service as MS

    conn = connect(str(tmp_path / "registrar_smoke.db"))
    teses = conn.execute("SELECT * FROM theses ORDER BY created_at DESC LIMIT 1").fetchone()
    assert teses is not None
    livro = MS.get_thesis_book(conn, teses["id"])
    conn.close()
    assert livro is not None
    assert len(livro["legs"]) == 5


def test_registro_ao_vivo_mostra_diff_e_marca_origem_do_vertice_alterado(app_env, tmp_path):
    from src.database.connection import init_db
    init_db().close()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()

    gerar = [b for b in at.button if b.label == "Gerar book"][0]
    gerar.click().run()
    assert not at.exception

    # dado novo "na defesa": sobe o preco de dezembro (ultimo number_input)
    entradas_dez = [ni for ni in at.number_input if ni.key == "ref_mkt_2026-12-01"]
    assert entradas_dez, "campo de referencia de dez/26 nao encontrado"
    entradas_dez[0].set_value(350.0).run()
    gerar.click().run()
    assert not at.exception

    texto = " ".join(m.value for m in at.markdown)
    assert "Diff" in texto

    _rodar_desafiar_e_responder(at)
    salvar = [b for b in at.button if b.label == "Salvar tese"][0]
    salvar.click().run()
    assert not at.exception
    assert any("Tese registrada" in s.value for s in at.success), [e.value for e in at.error]

    from src.database.connection import connect
    from src.services import motor_service as MS

    conn = connect(str(tmp_path / "registrar_smoke.db"))
    tid = conn.execute("SELECT id FROM theses ORDER BY created_at DESC LIMIT 1").fetchone()["id"]
    livro = MS.get_thesis_book(conn, tid)
    conn.close()

    por_mes = {p["mes_ref"]: p for p in livro["legs"]}
    assert por_mes["2026-12-01"]["preco_entrada_origem"] == "informado na defesa"
    assert float(por_mes["2026-12-01"]["preco_entrada"]) == pytest.approx(350.0)
    for mes in ("2026-08-01", "2026-09-01", "2026-10-01", "2026-11-01"):
        assert por_mes[mes]["preco_entrada_origem"] == "leitura de mesa"
