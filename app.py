"""Energy Trading Copilot — interface Streamlit.

Cinco areas: Dashboard, Teses, Debate, Monitor, Dados e fontes.
A aplicacao inicia mesmo sem credenciais externas (modo demonstracao).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st  # noqa: E402

from src.agents.llm_client import get_client  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.database import repositories as R  # noqa: E402
from src.database.connection import connect, init_db  # noqa: E402
from src.motor.avaliar import avaliar  # noqa: E402
from src.rag import store as RAG  # noqa: E402
from src.services import debate_service as DS  # noqa: E402
from src.services import desafio_service as DES  # noqa: E402
from src.services import formatting as FMT  # noqa: E402
from src.services import motor_service as MS  # noqa: E402
from src.services import risk_service as RS  # noqa: E402
from src.services import snapshot_loader as SNAP  # noqa: E402
from src.services import thesis_service as TS  # noqa: E402
from src.services import vigiar_service as VIG  # noqa: E402
from src.services import watchdog_service as WD  # noqa: E402

LIMITE_VAR_BRL = Decimal("50000000.00")  # P8 / CLAUDE.md — o limite do case

st.set_page_config(page_title="Energy Trading Copilot", page_icon="⚡", layout="wide")

CLASS_BADGE = {
    "observado": "🟢 real", "negociado": "🟢 negociado", "projetado": "🟡 projetado",
    "indicativo": "🟡 indicativo", "proxy": "🟠 proxy", "manual": "🔵 manual",
    "demonstracao": "⚪ demonstração",
}


@st.cache_resource
def _garantir_schema() -> None:
    """Cria/atualiza o schema uma vez por processo — sem guardar a conexao.

    `sqlite3.Connection` nao pode atravessar threads, e o Streamlit reexecuta
    o script (potencialmente em thread nova) a cada rerun. Por isso nenhuma
    conexao fica em cache; cada execucao abre a sua propria via `connect()`.
    """
    c = init_db()
    c.close()


def badge(classificacao: str) -> str:
    return CLASS_BADGE.get(classificacao, classificacao)


settings = get_settings()
_garantir_schema()
conn = connect()
cliente = get_client()
AS_OF = settings.data_cut_off.isoformat()

try:
    st.sidebar.title("⚡ Energy Trading Copilot")
    st.sidebar.caption(f"Data-base oficial: **{AS_OF}**")
    if cliente.banner:
        st.sidebar.warning(f"🔵 MODO DEMONSTRAÇÃO\n\n{cliente.banner}")
    else:
        from datetime import datetime as _dt
        st.sidebar.success(
            f"🟢 MODO IA REAL\n\nModelo: **{settings.anthropic_model}**\n\n"
            f"Verificado: {_dt.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
    area = st.sidebar.radio(
        "Área",
        ["Mesa", "Registrar tese", "Tese", "Dados e procedência", "Dashboard", "Teses",
         "Debate", "Monitor", "Dados e fontes"],
    )

    def _teses_com_book() -> list[dict]:
        linhas = conn.execute(
            "SELECT t.* FROM theses t JOIN thesis_book b ON b.thesis_id = t.id "
            "ORDER BY t.created_at DESC"
        ).fetchall()
        return [dict(r) for r in linhas]

    # ================================================== DADOS E PROCEDÊNCIA
    if area == "Dados e procedência":
        st.title("Dados e procedência")
        st.caption(
            "Resposta visível à pergunta do case sobre como a ferramenta não "
            "inventa número: em vez de afirmar no texto, esta tela mostra a fonte."
        )
        snap_proc = SNAP.load_default_snapshot()
        if snap_proc is None:
            st.info("Nenhum snapshot do motor encontrado.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Status do motor", snap_proc.status_motor)
            c2.metric("Data de corte", snap_proc.as_of)
            c3.metric("Gerado em", snap_proc.gerado_em[:19].replace("T", " "))
            st.caption(f"hash do snapshot: `{snap_proc.compute_hash()}`")

            st.subheader("Manifesto de fontes")
            st.dataframe(
                [
                    {
                        "instituição": item.get("instituicao"),
                        "conjunto": item.get("conjunto"),
                        "sha256": (item.get("sha256") or "")[:16] + "…",
                        "bytes": item.get("bytes"),
                        "coletado em (UTC)": item.get("baixado_em_utc"),
                        "limitações": item.get("qualidade_limitacoes"),
                    }
                    for item in snap_proc.manifesto
                ],
                use_container_width=True, hide_index=True,
            )
            st.caption(
                "Tabela simples — sem recálculo de hash aqui (verificação ao vivo "
                "fica para uma fatia futura, se sobrar tempo)."
            )

    # ================================================================== MESA
    elif area == "Mesa":
        st.title("Mesa")
        teses_motor = _teses_com_book()

        if not teses_motor:
            st.info("Nenhuma tese registrada. Vá em **Registrar tese** para cadastrar.")
        else:
            tese_atual = teses_motor[0]
            livro_atual = MS.get_thesis_book(conn, tese_atual["id"])

            with st.expander("🔴 Atualizar leitura de mercado e vigiar", expanded=False):
                st.caption(
                    "Compara os parâmetros REGISTRADOS na tese contra os parâmetros "
                    "correntes desta sessão — nunca snapshot contra snapshot."
                )
                snap_mesa = SNAP.load_default_snapshot()
                ref_salva = json.loads(livro_atual["ref_mercado_json"])
                cols_v = st.columns(len(ref_salva))
                ref_sessao = {}
                for col, (mes, valor) in zip(cols_v, sorted(ref_salva.items())):
                    ref_sessao[mes] = col.number_input(
                        f"{mes[5:7]}/{mes[2:4]}", value=float(valor), step=1.0,
                        format="%.2f", key=f"vigiar_{mes}",
                    )
                if st.button("Verificar vigilância"):
                    st.session_state["mesa_alertas"] = VIG.avaliar_gatilhos(
                        livro_atual, snap_mesa, ref_sessao, limite_var=LIMITE_VAR_BRL
                    )

            alertas_mesa = st.session_state.get("mesa_alertas", [])
            st.subheader("Alertas abertos")
            if alertas_mesa:
                for a in alertas_mesa:
                    icone = "🔴" if a["severidade"] == "CRÍTICO" else "🟠"
                    with st.expander(f"{icone} [{a['severidade']}] {a['gatilho']}", expanded=True):
                        st.write(a["mensagem"])
                        st.caption(
                            f"premissa: {a['premissa']} · de {a['de']} para {a['para']} · "
                            f"gatilho acionado: {a['gatilho_de_saida_acionado'] or '—'}"
                        )
            else:
                st.info("Nenhum alerta aberto. Nenhum zero silencioso: isto é um estado "
                        "verificado, não a ausência de verificação.")

            st.subheader(f"BOOK PROPOSTO — {tese_atual['title']}")
            st.caption(
                "\"Proposto\", não \"vigente\": o case não dá book posicionado de "
                "partida."
            )
            st.dataframe(
                [
                    {
                        "vértice": p["mes_ref"], "lado": p["lado"],
                        "MWm": FMT.fmt_mwm(p["mwmed"]) + " " + FMT.nature_badge(p["mwmed_nature"]),
                        "MWh": FMT.fmt_mwh(p["mwh"]),
                        "preço entrada": FMT.fmt_rs_mwh(p["preco_entrada"])
                                         + " " + FMT.nature_badge(p["preco_entrada_nature"]),
                        "origem": p["preco_entrada_origem"],
                    }
                    for p in livro_atual["legs"]
                ],
                use_container_width=True, hide_index=True,
            )
            m1, m2, m3 = st.columns(3)
            m1.metric("Energia", FMT.fmt_mwh(livro_atual["energia_mwh"]))
            m2.metric("Notional", FMT.fmt_money_mi(livro_atual["notional_brl"]))
            m3.metric("MWm eq.", FMT.fmt_mwm(livro_atual["mwmed_equivalente_flat"]))
            consumo_mesa = float(livro_atual["consumo_limite"])
            st.progress(min(consumo_mesa, 1.0),
                        text=f"VaR {FMT.fmt_money(livro_atual['var_total'])} — "
                             f"{FMT.fmt_pct(consumo_mesa)} do limite de "
                             f"{FMT.fmt_money(livro_atual['var_limit'])} "
                             f"(folga {FMT.fmt_money(float(livro_atual['var_limit']) - float(livro_atual['var_total']))})")

            st.subheader("Teses registradas")
            st.dataframe(
                [
                    {"título": t["title"], "direção": t["direction"], "status": t["status"],
                     "versão": t["version"], "responsável": t["owner"], "data-base": t["as_of"]}
                    for t in teses_motor
                ],
                use_container_width=True, hide_index=True,
            )

    # =================================================================== TESE
    elif area == "Tese":
        st.title("Tese (detalhe)")
        teses_motor = _teses_com_book()
        if not teses_motor:
            st.info("Nenhuma tese registrada.")
        else:
            por_id = {t["id"]: t for t in teses_motor}
            escolhido = st.selectbox(
                "Tese", list(por_id.keys()),
                format_func=lambda tid: f"{por_id[tid]['title']} (v{por_id[tid]['version']}, {por_id[tid]['status']})",
            )
            t = por_id[escolhido]
            livro = MS.get_thesis_book(conn, t["id"])

            st.header(t["title"])
            st.caption(f"{t['direction']} · {t['status']} · v{t['version']} · {t['owner']} · {t['as_of']}")
            st.markdown(f"**Tese (até 5 linhas)** {FMT.TRADER_BADGE}")
            st.write(t["summary"])

            st.markdown(f"**Ladder congelado nesta versão** · snapshot `{livro['snapshot_hash'][:12]}`")
            st.dataframe(
                [
                    {"vértice": p["mes_ref"], "lado": p["lado"],
                     "MWm": FMT.fmt_mwm(p["mwmed"]), "MWh": FMT.fmt_mwh(p["mwh"]),
                     "preço entrada": FMT.fmt_rs_mwh(p["preco_entrada"]),
                     "natureza": FMT.nature_badge(p["preco_entrada_nature"]),
                     "origem": p["preco_entrada_origem"]}
                    for p in livro["legs"]
                ],
                use_container_width=True, hide_index=True,
            )
            dc1, dc2, dc3 = st.columns(3)
            dc1.metric("Notional", FMT.fmt_money_mi(livro["notional_brl"]))
            dc2.metric("VaR", FMT.fmt_money_mi(livro["var_total"]))
            dc3.metric("Consumo do limite", FMT.fmt_pct(float(livro["consumo_limite"])))
            st.caption(
                f"Evidência: `{livro['evidence_id']}` · rótulos: "
                f"{', '.join(f'{k}={v}' for k, v in livro['natures'].items())}"[:400]
            )

            st.markdown("**Resultado esperado — intervalo, nunca número único**")
            r1, r2, r3 = st.columns(3)
            r1.metric("Seco (adverso — vendido)", FMT.fmt_money_mi(livro["pnl_entrega_seco"]))
            r2.metric("Esperado", FMT.fmt_money_mi(livro["pnl_entrega_esperado"]))
            r3.metric("Úmido (favorável — vendido)", FMT.fmt_money_mi(livro["pnl_entrega_umido"]))
            st.caption(
                "Cenários lado a lado — trajetórias oficiais inteiras da CCEE, nunca "
                "combinadas mês a mês. Impacto no VaR: o dimensionamento já usa o VaR "
                "de marcação por vértice; a perda em cenário é stress, não dimensiona."
            )

            hc1, hc2 = st.columns(2)
            hc1.metric("Horizonte (dias)", t["horizon_days"] or "—")
            hc2.metric("Data de reavaliação", t["review_date"] or "—")
            st.markdown(f"**Gatilho de saída** {FMT.TRADER_BADGE}")
            st.write(t["exit_condition"] or "—")
            st.markdown(f"**O que invalidaria a tese** {FMT.TRADER_BADGE}")
            st.write(t["invalidation"] or "—")

            st.subheader("Desafiar — registrado")
            if t["desafio_premissa_fragil"]:
                st.markdown(f"**Premissa mais frágil** {FMT.nature_badge('CALCULADO')}")
                st.write(t["desafio_premissa_fragil"])
                st.markdown(f"**Cenário que quebra** {FMT.nature_badge('CALCULADO')}")
                st.write(t["desafio_cenario_quebra"])
                st.markdown(f"**Contra-argumento** {FMT.IA_BADGE}")
                st.write(t["desafio_contra_argumento"])
                st.markdown(f"**Resposta do trader** {FMT.TRADER_BADGE}")
                st.write(t["trader_response"] or "—")
            else:
                st.warning("Esta tese não passou pelo Desafiar (registrada antes da fatia 6).")

            st.subheader("Histórico de alertas (vigilância, sessão atual)")
            st.caption(
                "Vá em **Mesa** para injetar um dado novo e ver o que dispara contra "
                "esta tese em tempo real."
            )

    # ========================================================= REGISTRAR TESE
    elif area == "Registrar tese":
        st.title("Registrar tese")
        st.caption(
            "O trader escolhe a referência de mercado; o motor devolve o book "
            "proposto. Nenhum número nesta tela é digitado sem procedência."
        )

        snapshot = SNAP.load_default_snapshot()
        if snapshot is None:
            st.error(
                "Nenhum snapshot do motor encontrado em `motor_curva/snapshots/`. "
                "Rode `python scripts/build_motor_snapshot.py` (offline) e "
                "commite o resultado antes de registrar uma tese."
            )
        else:
            st.subheader("Etapa 1 — Parâmetros")
            c1, c2 = st.columns(2)
            c1.metric("Submercado", snapshot.submercado)
            c2.metric("Data de corte (as_of)", snapshot.as_of)
            st.caption(
                f"snapshot `{snapshot.compute_hash()[:12]}` · status do motor: "
                f"**{snapshot.status_motor}** · meia-vida sazonal: {snapshot.hl_dias} dias"
            )

            st.markdown(
                "### 🔴 Registro ao vivo\n"
                "Altere a referência de qualquer vértice — ou injete o dado que "
                "derem na defesa — e clique em **Gerar book** de novo. Meta: "
                "menos de 10 segundos entre digitar e ver o book novo."
            )
            st.caption(
                "🟠 PREMISSA — leitura de mesa, sem identificação de fonte. "
                "Vértice alterado em relação ao valor original do snapshot é "
                "gravado como **\"informado na defesa\"** na hora de salvar."
            )
            default_ref = snapshot.notas.get("ref_mercado_geracao") or {}
            cols = st.columns(len(snapshot.alvo))
            ref_mercado: dict[str, float] = {}
            for col, mes in zip(cols, snapshot.alvo):
                rotulo = f"{mes[5:7]}/{mes[2:4]}"
                default_val = float(default_ref.get(mes, 0.0))
                ref_mercado[mes] = col.number_input(
                    rotulo, value=default_val, step=1.0, format="%.2f",
                    key=f"ref_mkt_{mes}",
                )
                if abs(ref_mercado[mes] - default_val) > 1e-9:
                    col.caption("🟠 informado na defesa")

            if st.button("Gerar book", type="primary"):
                import time as _time

                inicio = _time.perf_counter()
                try:
                    resultado = avaliar(snapshot, ref_mercado, LIMITE_VAR_BRL)
                    duracao_ms = (_time.perf_counter() - inicio) * 1000
                    if st.session_state.get("registrar_resultado") is not None:
                        st.session_state["registrar_resultado_anterior"] = (
                            st.session_state["registrar_resultado"]
                        )
                    st.session_state["registrar_snapshot_path"] = str(
                        SNAP.list_snapshot_paths()[-1]
                    )
                    st.session_state["registrar_ref_mercado"] = ref_mercado
                    st.session_state["registrar_resultado"] = resultado
                    st.session_state["registrar_duracao_ms"] = duracao_ms
                    st.toast(f"Book recalculado em {duracao_ms:.0f} ms", icon="⚡")
                except ValueError as exc:
                    st.error(f"Falha explícita do motor: {exc}")

            resultado = st.session_state.get("registrar_resultado")
            anterior = st.session_state.get("registrar_resultado_anterior")
            duracao_ms = st.session_state.get("registrar_duracao_ms")
            if resultado and anterior:
                st.markdown("#### Diff — book novo × book anterior")
                if duracao_ms is not None:
                    st.caption(f"recalculado em {duracao_ms:.0f} ms")
                book_ant = anterior["book"]
                ladder_ant = {l["mes"]: l for l in book_ant["ladder"]}
                linhas_diff = []
                for linha in resultado["book"]["ladder"]:
                    ant = ladder_ant.get(linha["mes"])
                    delta_preco = linha["preco_entrada"] - ant["preco_entrada"] if ant else None
                    delta_mwm = linha["mwmed"] - ant["mwmed"] if ant else None
                    linhas_diff.append({
                        "vértice": linha["mes"],
                        "preço antes": FMT.fmt_rs_mwh(ant["preco_entrada"]) if ant else "—",
                        "preço agora": FMT.fmt_rs_mwh(linha["preco_entrada"]),
                        "Δ preço": (f"{'+' if delta_preco >= 0 else ''}{FMT.fmt_num(delta_preco)}"
                                    if delta_preco is not None else "—"),
                        "MWm antes": FMT.fmt_mwm(ant["mwmed"]) if ant else "—",
                        "MWm agora": FMT.fmt_mwm(linha["mwmed"]),
                        "Δ MWm": (f"{'+' if delta_mwm >= 0 else ''}{FMT.fmt_num(delta_mwm, 0)}"
                                  if delta_mwm is not None else "—"),
                    })
                st.dataframe(linhas_diff, use_container_width=True, hide_index=True)
                dvar = resultado["book"]["var_total"] - book_ant["var_total"]
                dcons = resultado["book"]["consumo_limite"] - book_ant["consumo_limite"]
                dc1, dc2 = st.columns(2)
                dc1.metric("VaR total", FMT.fmt_money_mi(resultado["book"]["var_total"]),
                           delta=FMT.fmt_money_mi(dvar))
                dc2.metric("Consumo do limite", FMT.fmt_pct(resultado["book"]["consumo_limite"]),
                           delta=FMT.fmt_pct(dcons))

            if resultado:
                book = resultado["book"]
                st.subheader("Book proposto")
                st.dataframe(
                    [
                        {
                            "vértice": linha["mes"],
                            "lado": "VENDIDO",
                            "MWm": FMT.fmt_mwm(linha["mwmed"]),
                            "horas": int(linha["horas"]),
                            "MWh": FMT.fmt_mwh(linha["mwh"]),
                            "preço entrada": FMT.fmt_rs_mwh(linha["preco_entrada"]),
                            "natureza (preço)": FMT.nature_badge("PREMISSA"),
                        }
                        for linha in book["ladder"]
                    ],
                    use_container_width=True, hide_index=True,
                )

                k1, k2, k3, k4 = st.columns(4)
                k1.metric(f"Energia {FMT.nature_badge('CALCULADO')}",
                          FMT.fmt_gwh(book["energia_liquida_gwh"] * 1000))
                k2.metric(f"Notional {FMT.nature_badge('CALCULADO')}",
                          FMT.fmt_money_mi(book["notional_brl"]))
                k3.metric(f"Preço médio {FMT.nature_badge('CALCULADO')}",
                          FMT.fmt_rs_mwh(book["preco_entrada_medio_mwh"]))
                k4.metric("MWm eq. (ago–dez/26)", FMT.fmt_mwm(book["mwmed_equivalente_flat"]),
                          help="Comparação com produto flat — nunca o tamanho. Veja o ladder acima.")

                st.markdown("**Risco — VaR (a única definição; nunca soma com stress de cenário)**")
                consumo = book["consumo_limite"]
                st.progress(min(consumo, 1.0),
                            text=f"VaR {FMT.fmt_money(book['var_total'])} de "
                                 f"{FMT.fmt_money(LIMITE_VAR_BRL)} — {FMT.fmt_pct(consumo)} do limite "
                                 f"(folga {FMT.fmt_money(float(LIMITE_VAR_BRL) - book['var_total'])})")
                if consumo >= 1.0:
                    st.error("VaR acima do limite — aprovação bloqueada por código (P8).")
                elif consumo >= 0.80:
                    st.warning("Consumo do limite acima da faixa de atenção (80%).")

                st.markdown("**Resultado esperado — nunca número único**")
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("Seco", FMT.fmt_money_mi(book["pnl_Entrega_Seco"]))
                sc2.metric("Esperado", FMT.fmt_money_mi(book["pnl_Entrega_Esperado"]))
                sc3.metric("Úmido", FMT.fmt_money_mi(book["pnl_Entrega_Umido"]))
                sc4.metric("Convergência do prêmio", FMT.fmt_money_mi(book["pnl_Convergencia"]))

                st.caption(
                    f"prêmio de nível: {FMT.fmt_rs_mwh(resultado.get('premio_nivel_rs_mwh'))} "
                    f"{FMT.nature_badge('CALCULADO')} · modo de sinal: {resultado['modo_sinal']} · "
                    f"VPL: {FMT.fmt_money_mi(book['vpl'])}"
                )
                st.divider()
                st.subheader("Etapa 2 — Narrativa")
                st.caption(
                    "Campos que você digita ficam visualmente distintos dos calculados pelo motor."
                )
                titulo = st.text_input(
                    f"Título* {FMT.TRADER_BADGE}", "Book Entrega 2 — SE/CO",
                    key="registrar_titulo",
                )
                resumo = st.text_area(
                    f"Resumo* (até 5 linhas) {FMT.TRADER_BADGE}", height=110,
                    key="registrar_resumo",
                    value=(
                        f"Venda de {book['n_pernas']} vértices de energia convencional flat "
                        f"{snapshot.submercado}, calibrada contra a referência de mesa."
                    ),
                )
                nc1, nc2, nc3 = st.columns(3)
                responsavel = nc1.text_input(f"Responsável* {FMT.TRADER_BADGE}", "trader",
                                              key="registrar_owner")
                horizonte = nc2.number_input(f"Horizonte (dias) {FMT.TRADER_BADGE}", value=140,
                                              step=1, key="registrar_horizonte")
                reavaliacao = nc3.date_input(f"Data de reavaliação* {FMT.TRADER_BADGE}",
                                              key="registrar_reavaliacao")
                saida = st.text_input(
                    f"Gatilho de saída* {FMT.TRADER_BADGE}",
                    "Prêmio de nível abaixo de R$ 15/MWh", key="registrar_saida",
                )
                invalidacao = st.text_input(
                    f"O que invalidaria a tese* {FMT.TRADER_BADGE}",
                    "Ordenação Seco > Base > Úmido invertida na reestimação",
                    key="registrar_invalidacao",
                )

                direcao = "VENDER"  # todas as pernas deste book sao VENDIDO

                st.divider()
                st.subheader("Etapa 3 — Desafiar")
                st.caption("Bloqueante — não dá para pular. Roda sobre os números do motor.")
                if st.button("Rodar Desafiar"):
                    desafio = DES.montar_desafio(
                        resultado, direcao=direcao, client=cliente, conn=conn,
                        ref_mercado_atual=st.session_state.get("registrar_ref_mercado"),
                        ref_mercado_base=snapshot.notas.get("ref_mercado_geracao"),
                    )
                    st.session_state["registrar_desafio"] = desafio

                desafio = st.session_state.get("registrar_desafio")
                if desafio:
                    badge_ia = FMT.IA_BADGE if desafio["modo_ia"] == "REAL" else "🤖 ROTEIRO DEMONSTRATIVO (não é IA)"
                    st.markdown(f"**Premissa mais frágil** {FMT.nature_badge('CALCULADO')}")
                    st.write(desafio["premissa_fragil"])
                    st.markdown(f"**Cenário que quebra a posição** {FMT.nature_badge('CALCULADO')}")
                    st.write(desafio["cenario_quebra"])
                    st.markdown(f"**Contra-argumento** {badge_ia}")
                    st.write(desafio["contra_argumento"])
                    st.markdown("**Viés de confirmação**")
                    if desafio["vies_confirmacao_detectado"]:
                        st.warning(desafio["vies_confirmacao_texto"])
                    else:
                        st.write(desafio["vies_confirmacao_texto"])
                    resposta_trader = st.text_area(
                        f"Resposta do trader* {FMT.TRADER_BADGE}",
                        key="registrar_trader_response",
                        help="Obrigatória antes de salvar — o case exige que o trader "
                             "responda ao contra-argumento, não apenas concorde.",
                    )
                else:
                    resposta_trader = ""
                    st.info("Rode o Desafiar para liberar o registro.")

                st.subheader("Etapa 4 — Salvar")
                pronto = bool(
                    titulo.strip() and resumo.strip() and responsavel.strip()
                    and saida.strip() and invalidacao.strip()
                    and desafio and resposta_trader.strip()
                )
                if not pronto:
                    st.caption(
                        "Preencha título, resumo, responsável, gatilho de saída, condição de "
                        "invalidação, rode o Desafiar e responda ao contra-argumento."
                    )
                if st.button("Salvar tese", type="primary", disabled=not pronto):
                    try:
                        registro = MS.register_thesis_from_motor(
                            conn, snapshot=snapshot,
                            ref_mercado=st.session_state["registrar_ref_mercado"],
                            title=titulo, summary=resumo, direction=direcao,
                            product=f"Convencional flat mensal {snapshot.submercado}",
                            submarket="SE/CO" if snapshot.submercado == "SE" else snapshot.submercado,
                            owner=responsavel, as_of=snapshot.as_of, horizon_days=int(horizonte),
                            review_date=reavaliacao.isoformat(), exit_condition=saida,
                            invalidation=invalidacao, limite_var=LIMITE_VAR_BRL,
                            preco_entrada_origem="leitura de mesa", actor=responsavel,
                            avaliado=resultado, trader_response=resposta_trader,
                            desafio_premissa_fragil=desafio["premissa_fragil"],
                            desafio_cenario_quebra=desafio["cenario_quebra"],
                            desafio_contra_argumento=desafio["contra_argumento"],
                            desafio_vies_confirmacao=desafio["vies_confirmacao_texto"],
                        )
                        st.success(
                            f"Tese registrada: `{registro['thesis_id']}` — veja em **Teses**."
                        )
                        for chave in ("registrar_resultado", "registrar_resultado_anterior",
                                      "registrar_ref_mercado", "registrar_snapshot_path",
                                      "registrar_desafio"):
                            st.session_state.pop(chave, None)
                    except Exception as exc:
                        st.error(f"Não foi possível registrar: {exc}")

    # ============================================================== DASHBOARD
    elif area == "Dashboard":
        st.title("Dashboard")
        teses = TS.list_theses(conn)
        alertas = WD.open_alerts(conn)
        criticos = [a for a in alertas if a["severity"] == "CRÍTICO" or a["severity"] == "CRITICO"]
        atrasadas = [f for f in R.source_freshness(conn, as_of=AS_OF) if f["age_days"] > WD.STALE_DAYS]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Teses", len(teses))
        c2.metric("Alertas abertos", len(alertas), delta=f"{len(criticos)} críticos" if criticos else None)
        c3.metric("Fontes atrasadas", len(atrasadas))
        limite = RS.var_limit(conn)
        ativa = next((t for t in teses if t["status"] in ("ATIVA", "APROVADA")), None)
        risco = RS.latest_risk(conn, ativa["id"]) if ativa else None
        c4.metric("Consumo do limite",
                  f"{Decimal(risco['utilization'])*100:.1f}%" if risco else "—",
                  help=f"Limite de R$ {limite}")

        if alertas:
            st.subheader("Alertas abertos")
            st.dataframe([{"severidade": a["severity"], "tipo": a["kind"],
                           "mensagem": a["message"], "data-base": a["as_of"],
                           "ocorrências": a["occurrences"]} for a in alertas],
                         use_container_width=True)

        st.subheader("Teses")
        if teses:
            st.dataframe([{"título": t["title"], "direção": t["direction"],
                           "status": t["status"], "versão": t["version"],
                           "responsável": t["owner"], "data-base": t["as_of"]} for t in teses],
                         use_container_width=True)
        else:
            st.info("Nenhuma tese registrada. Vá em **Teses** para cadastrar.")

        curva = R.latest_curve(conn, as_of=AS_OF)
        if curva:
            st.subheader(f"Curva forward — {curva['curve_name']}  {badge(curva['classification'])}")
            if curva["origin"] != "NEGOCIADA":
                st.warning(f"Origem **{curva['origin']}** — não é preço negociado. "
                           f"Proxy de: {curva['proxy_of'] or 'não declarado'}. "
                           "O risco aplica add-on de proxy.")
            pontos = R.curve_points(conn, curva["id"])
            st.dataframe([{"tenor": p["tenor"], "início": p["delivery_start"],
                           "fim": p["delivery_end"], "preço": p["price"], "unidade": p["unit"]}
                          for p in pontos], use_container_width=True)

    # ================================================================= TESES
    elif area == "Teses":
        st.title("Teses")
        aba_nova, aba_ver = st.tabs(["Cadastrar", "Consultar"])

        with aba_nova:
            with st.form("nova_tese"):
                col1, col2 = st.columns(2)
                titulo = col1.text_input("Título*")
                direcao = col2.selectbox("Direção*", TS.DIRECTIONS)
                resumo = st.text_area("Resumo* (até 5 linhas)", height=110)
                col3, col4, col5 = st.columns(3)
                produto = col3.text_input("Produto*", "Forward convencional A+1")
                submercado = col4.selectbox("Submercado*", ["SE/CO", "S", "NE", "N"])
                fonte_energia = col5.selectbox("Fonte de energia*",
                                               ["CONVENCIONAL", "I0", "I5", "I100"])
                col6, col7, col8 = st.columns(3)
                inicio = col6.date_input("Início da entrega", date(2027, 1, 1))
                fim = col7.date_input("Fim da entrega", date(2027, 12, 31))
                volume = col8.number_input("Volume (MWmed)", value=50.0, step=1.0)
                col9, col10, col11 = st.columns(3)
                preco = col9.number_input("Preço de referência (R$/MWh)", value=195.0, step=1.0)
                data_preco = col10.date_input("Data do preço", settings.data_cut_off)
                reavaliacao = col11.date_input("Data de reavaliação", date(2026, 9, 15))
                col12, col13, col14 = st.columns(3)
                baixo = col12.number_input("Resultado esperado — baixo (R$)", value=-8_000_000.0)
                central = col13.number_input("Central (R$)", value=4_000_000.0)
                alto = col14.number_input("Alto (R$)", value=15_000_000.0)
                saida = st.text_input("Condição de saída*")
                invalidacao = st.text_input("Condição de invalidação*")
                responsavel = st.text_input("Responsável*", "trader")
                if st.form_submit_button("Registrar tese"):
                    try:
                        tid = TS.create_thesis(
                            conn, title=titulo, summary=resumo, direction=direcao, product=produto,
                            submarket=submercado, energy_source=fonte_energia, owner=responsavel,
                            as_of=AS_OF, delivery_start=inicio.isoformat(),
                            delivery_end=fim.isoformat(), volume_mwm=Decimal(str(volume)),
                            price_ref=Decimal(str(preco)), price_ref_date=data_preco.isoformat(),
                            review_date=reavaliacao.isoformat(),
                            expected_low=Decimal(str(baixo)), expected_mid=Decimal(str(central)),
                            expected_high=Decimal(str(alto)), exit_condition=saida,
                            invalidation=invalidacao, actor=responsavel)
                        st.success(f"Tese registrada: {tid}")
                    except Exception as exc:
                        st.error(f"Não foi possível registrar: {exc}")

        with aba_ver:
            teses = [dict(t) for t in TS.list_theses(conn)]
            if not teses:
                st.info("Nenhuma tese registrada.")
            else:
                teses_por_id = {t["id"]: t for t in teses}
                id_escolhido = st.selectbox(
                    "Tese", list(teses_por_id.keys()),
                    format_func=lambda tid: (
                        f"{teses_por_id[tid]['title']} "
                        f"(v{teses_por_id[tid]['version']}, {teses_por_id[tid]['status']})"
                    ),
                )
                escolha = teses_por_id[id_escolhido]
                completa = TS.get_thesis_full(conn, escolha["id"])
                st.json(completa["thesis"], expanded=False)
                st.subheader("Premissas")
                st.dataframe(completa["assumptions"] or [{"—": "nenhuma"}], use_container_width=True)
                st.subheader("Posições")
                st.dataframe(completa["positions"] or [{"—": "nenhuma"}], use_container_width=True)
                st.subheader("Gatilhos")
                st.dataframe(completa["triggers"] or [{"—": "nenhum"}], use_container_width=True)

                st.subheader("Adicionar premissa")
                with st.form("premissa"):
                    enunciado = st.text_input("Enunciado*")
                    metrica = st.text_input("Métrica vigiável", "ear_sudeste_pct")
                    cl1, cl2, cl3 = st.columns(3)
                    esperado = cl1.number_input("Esperado", value=52.0)
                    tol_baixo = cl2.number_input("Tolerância mínima", value=45.0)
                    tol_alto = cl3.number_input("Tolerância máxima", value=100.0)
                    if st.form_submit_button("Adicionar"):
                        try:
                            eid = R.create_evidence(
                                conn, kind="MANUAL", source_name="Entrada do trader",
                                excerpt=f"Premissa registrada na interface: {enunciado}",
                                value=Decimal(str(esperado)), unit="%", as_of=AS_OF,
                                classification="manual")
                            TS.add_assumption(conn, escolha["id"], kind="OUTRA",
                                              statement=enunciado, evidence_id=eid, metric=metrica,
                                              expected=Decimal(str(esperado)),
                                              tol_low=Decimal(str(tol_baixo)),
                                              tol_high=Decimal(str(tol_alto)), unit="%")
                            st.success("Premissa registrada com evidência.")
                        except Exception as exc:
                            st.error(str(exc))

                if st.button("Calcular risco e cenários"):
                    try:
                        precos = {}
                        for p in completa["positions"]:
                            obs = R.latest_observation(conn, p["metric_key"], as_of=AS_OF)
                            if obs:
                                precos[p["metric_key"]] = Decimal(obs["value"])
                        risco = RS.compute_risk(conn, escolha["id"], as_of=AS_OF, prices=precos)
                        if risco["ok"]:
                            st.metric("VaR total", f"R$ {risco['var_total']}",
                                      f"{Decimal(risco['utilization'])*100:.2f}% do limite")
                            st.write(risco["limit_message"])
                            st.write("Add-ons:", risco["addons"])
                            cen = RS.compute_scenarios(conn, escolha["id"], as_of=AS_OF,
                                                       base_prices=precos,
                                                       sigma_daily=risco["sigma_daily"])
                            st.dataframe(cen, use_container_width=True)
                        else:
                            st.warning(risco["message"])
                    except Exception as exc:
                        st.error(str(exc))

    # ================================================================ DEBATE
    elif area == "Debate":
        st.title("Debate")
        teses = [dict(t) for t in TS.list_theses(conn)]
        if not teses:
            st.info("Cadastre uma tese antes de debater.")
        else:
            teses_por_id = {t["id"]: t for t in teses}
            id_escolhido = st.selectbox(
                "Tese", list(teses_por_id.keys()),
                format_func=lambda tid: f"{teses_por_id[tid]['title']} (v{teses_por_id[tid]['version']})",
            )
            escolha = teses_por_id[id_escolhido]
            if st.button("Executar debate (máx. 4 chamadas ao LLM)"):
                with st.spinner("Trader → Risco → Verificação → Veredito"):
                    try:
                        resultado = DS.run_debate(conn, escolha["id"], as_of=AS_OF)
                        st.session_state["debate"] = resultado
                    except Exception as exc:
                        st.error(str(exc))

            resultado = st.session_state.get("debate")
            if resultado:
                if resultado["mode"] == "DEMO":
                    st.warning("Roteiro demonstrativo — **não é saída de IA**. "
                               "Os números continuam vindo do banco e do motor quantitativo.")
                st.caption(
                    f"Data-base: **{AS_OF}** · Modo da IA: **{resultado['mode']}** · "
                    f"Modelo: **{settings.anthropic_model if resultado['mode'] == 'REAL' else '—'}**"
                )
                st.subheader(f"Veredito: {resultado['verdict']}")
                st.write(resultado["rationale"])
                st.caption(f"Verificação: {resultado['verification']}")
                st.write("**Vieses detectados:**", "; ".join(resultado["biases"]))
                st.write("**Premissa mais frágil:**", resultado["weakest_assumption"])
                for turno in resultado["turns"]:
                    with st.expander(f"{turno['agent']} — {turno['stage']} ({turno['mode']})",
                                     expanded=turno["stage"] in ("CONTESTACAO", "VEREDITO")):
                        st.write(turno["text"])
                        if turno["evidence_ids"]:
                            st.caption("evidence_id: " + ", ".join(turno["evidence_ids"][:6]))
                replica = st.text_area("Réplica do trader")
                col_r1, col_r2 = st.columns(2)
                if col_r1.button("Registrar réplica") and replica.strip():
                    DS.add_reply(conn, resultado["session_id"], replica)
                    st.success("Réplica registrada no histórico.")
                if col_r2.button("Limpar conversa"):
                    del st.session_state["debate"]
                    st.rerun()

            st.subheader("Histórico de rodadas")
            for sessao in DS.list_sessions(conn, escolha["id"]):
                st.write(f"Rodada {sessao['round_number']} — {sessao['verdict']} "
                         f"({sessao['mode']}, {sessao['llm_calls']} chamadas LLM) "
                         f"— {sessao['started_at']}")

    # =============================================================== MONITOR
    elif area == "Monitor":
        st.title("Monitor — Watchdog")
        col1, col2 = st.columns(2)
        if col1.button("Executar Watchdog agora"):
            resultado = WD.run_once(conn, as_of=AS_OF)
            st.success(f"Ciclo {resultado['status']}: {resultado['triggers_evaluated']} regras, "
                       f"{resultado['alerts_raised']} alertas.")
            if settings.ai_auto_review_on_alert and resultado["alerts_raised"]:
                criticos = [a for a in WD.open_alerts(conn)
                           if a["severity"] in ("CRITICO", "CRÍTICO") and a["thesis_id"]]
                teses_criticas = {a["thesis_id"] for a in criticos}
                for tid in teses_criticas:
                    with st.spinner(f"AI_AUTO_REVIEW_ON_ALERT: redebatendo tese {tid}…"):
                        try:
                            revisao = DS.run_debate(conn, tid, as_of=AS_OF, actor="watchdog_auto")
                            st.info(f"Debate automatico (alerta critico) — tese {tid}: "
                                    f"veredito {revisao['verdict']} ({revisao['mode']}).")
                        except Exception as exc:
                            st.warning(f"Nao foi possivel redebater {tid} automaticamente: {exc}")
        with col2.form("simular"):
            st.write("**Simular atualização de mercado**")
            metrica = st.selectbox("Métrica", R.distinct_metrics(conn) or ["fwd_se_a1_conv"])
            valor = st.number_input("Novo valor", value=275.0)
            if st.form_submit_button("Inserir e reavaliar"):
                resultado = WD.simulate_market_update(conn, metric=metrica,
                                                      value=Decimal(str(valor)), unit="R$/MWh",
                                                      as_of=AS_OF)
                st.success(f"Dado demonstrativo inserido. {resultado['alerts_raised']} alertas.")

        st.subheader("Alertas abertos")
        abertos = WD.open_alerts(conn)
        if not abertos:
            st.info("Nenhum alerta aberto.")
        for alerta in abertos:
            with st.expander(f"[{alerta['severity']}] {alerta['kind']} — {alerta['message']}"):
                st.write(alerta["explanation"] or "—")
                st.caption(f"observado {alerta['observed']} | esperado {alerta['expected']} "
                           f"| data-base {alerta['as_of']} | evidence_id {alerta['evidence_id']}")
                with st.form(f"ack_{alerta['id']}"):
                    decisao = st.selectbox("Decisão", ["MANTER", "AJUSTAR", "ENCERRAR"],
                                           key=f"d_{alerta['id']}")
                    justificativa = st.text_input("Justificativa*", key=f"j_{alerta['id']}")
                    if st.form_submit_button("Reconhecer"):
                        try:
                            WD.acknowledge(conn, alerta["id"], decision=decisao,
                                           rationale=justificativa)
                            st.success("Alerta reconhecido.")
                        except ValueError as exc:
                            st.error(str(exc))

        st.subheader("Execuções recentes")
        st.dataframe([{"início": r["started_at"], "status": r["status"],
                       "teses": r["theses_checked"], "regras": r["triggers_evaluated"],
                       "alertas": r["alerts_raised"], "fontes atrasadas": r["stale_sources"]}
                      for r in WD.recent_runs(conn)] or [{"—": "nenhuma"}],
                     use_container_width=True)

    # ======================================================== DADOS E FONTES
    else:
        st.title("Dados e fontes")
        t1, t2, t3, t4, t5 = st.tabs(
            ["Observações", "Documentos e RAG", "Integrações", "Auditoria", "Curva pública"]
        )

        with t1:
            st.subheader("Freshness por métrica")
            st.dataframe(R.source_freshness(conn, as_of=AS_OF) or [{"—": "sem dados"}],
                         use_container_width=True)
            arquivo = st.file_uploader("Importar observações (CSV/XLSX)", type=["csv", "xlsx"])
            if arquivo is not None:
                from copilot.ingest.adapters.uploads import ManualObservationAdapter
                from copilot.ingest.snapshots import SnapshotStore
                try:
                    resultado = ManualObservationAdapter(
                        snapshot_store=SnapshotStore(ROOT / "data" / "snapshots")
                    ).run(as_of=settings.data_cut_off, file=arquivo.getvalue(),
                          filename=arquivo.name)
                    for linha in resultado.observations:
                        R.insert_observation(conn, metric=linha.metric_key, value=linha.value,
                                             unit=linha.unit.value, ref_date=linha.ref_date.isoformat(),
                                             as_of=linha.as_of.isoformat(),
                                             source_name="Upload manual", classification="manual")
                    st.success(f"{len(resultado.observations)} observações importadas.")
                except Exception as exc:
                    st.error(f"Arquivo rejeitado: {exc}")

        with t2:
            st.dataframe([{"título": d["title"], "instituição": d["institution"],
                           "versão": d["version"], "vigência": d["effective_from"],
                           "páginas": d["page_count"]} for d in RAG.list_documents(conn)]
                         or [{"—": "nenhum"}], use_container_width=True)
            pergunta = st.text_input("Pesquisar no acervo", "penalidade por insuficiência de lastro")
            if st.button("Buscar"):
                hits = RAG.search_with_evidence(conn, pergunta, as_of=AS_OF)
                if not hits:
                    st.warning(RAG.NOT_CONFIRMED)
                for hit in hits:
                    st.markdown(f"**{hit.citation()}**")
                    st.write(hit.text[:600])
                    st.caption(f"evidence_id: {hit.evidence_id}")

        with t3:
            st.dataframe([{"fonte": s["name"], "instituição": s["institution"],
                           "status": s["integration_status"], "licença": s["license_note"],
                           "última coleta": s["last_success_at"] or "—"}
                          for s in R.list_sources(conn)] or [{"—": "nenhuma"}],
                         use_container_width=True)
            st.caption("`LIVE_VALIDATED` só após chamada real, schema validado e dado persistido.")

            st.subheader("Atualizar agora")
            st.caption(
                "Cada fonte falha isoladamente — uma indisponível não impede as demais "
                "(RF-36). Reproduz `scripts/update_sector_data.py` a partir da interface."
            )
            from copilot.ingest.registry import get_adapter
            from copilot.ingest.snapshots import SnapshotStore
            from src.services import curve_service as CVS
            from src.services.ingestion_bridge import persist_adapter_result
            from scripts.update_sector_data import ACCESS_LABELS, SOURCE_ADAPTERS

            colunas = st.columns(len(SOURCE_ADAPTERS))
            for coluna, fonte_cli in zip(colunas, SOURCE_ADAPTERS):
                if coluna.button(fonte_cli, key=f"upd_{fonte_cli}"):
                    with st.spinner(f"Atualizando {fonte_cli}…"):
                        snapshots = SnapshotStore(ROOT / "data" / "snapshots")
                        for nome_adapter in SOURCE_ADAPTERS[fonte_cli]:
                            resultado = get_adapter(nome_adapter, snapshot_store=snapshots).run(
                                as_of=settings.data_cut_off
                            )
                            rotulo = ACCESS_LABELS.get(nome_adapter, resultado.source.license_class.value)
                            saida = persist_adapter_result(
                                conn, resultado, as_of=AS_OF, access_label=rotulo
                            )
                            if saida["ok"]:
                                st.success(
                                    f"[{rotulo}] {nome_adapter}: {saida['status']} — "
                                    f"{saida['observations']} observação(ões), {saida['curves']} curva(s)."
                                )
                            else:
                                st.warning(f"[{rotulo}] {nome_adapter}: {saida['status']} — {saida['reason']}")
                        if fonte_cli == "forward":
                            resultado_curva = CVS.refresh_all_submarkets(conn, as_of=AS_OF)
                            for submercado, r in resultado_curva.items():
                                if r["status"] == "OK":
                                    st.success(f"Curva estatística {submercado}: gerada.")
                                else:
                                    st.info(f"Curva estatística {submercado}: {r['status']} — {r.get('message', '')}")

        with t4:
            st.dataframe([{"quando": a["created_at"], "ator": a["actor"], "ação": a["action"],
                           "agente": a["agent"], "entidade": a["entity"], "modelo": a["model"]}
                          for a in R.audit_trail(conn, limit=300)] or [{"—": "vazio"}],
                         use_container_width=True)

        with t5:
            from src.services import curve_service as CVS

            st.subheader("Curva forward / cenário estatístico")
            nomes_curva = [r["curve_name"] for r in conn.execute(
                "SELECT DISTINCT curve_name FROM forward_curves ORDER BY curve_name"
            ).fetchall()]
            if not nomes_curva:
                st.info("Nenhuma curva disponível ainda. Rode a atualização em **Integrações** "
                        "ou importe uma curva manualmente abaixo.")
            else:
                colf1, colf2 = st.columns(2)
                curva_escolhida = colf1.selectbox("Curva", nomes_curva)
                submercado_escolhido = colf2.selectbox("Submercado", ["SE/CO", "S", "NE", "N"])

                cabecalhos = list(conn.execute(
                    "SELECT * FROM forward_curves WHERE curve_name=? AND submarket=? AND as_of<=? "
                    "ORDER BY quote_type, as_of DESC",
                    (curva_escolhida, submercado_escolhido, AS_OF),
                ).fetchall())
                if not cabecalhos:
                    st.warning("Sem pontos para essa combinação de curva/submercado até a data-base.")
                else:
                    linhas_tabela = []
                    for cab in cabecalhos:
                        for p in R.curve_points(conn, cab["id"]):
                            linhas_tabela.append({
                                "quote_type": cab["quote_type"], "tenor": p["tenor"],
                                "início": p["delivery_start"], "fim": p["delivery_end"],
                                "preço (R$/MWh)": p["price"],
                            })
                    cab0 = cabecalhos[0]
                    st.write(
                        f"**Origem:** {cab0['origin']}  ·  **Classificação:** {badge(cab0['classification'])}"
                        f"  ·  **Data-base:** {cab0['as_of']}"
                    )
                    if cab0["origin"] != "NEGOCIADA":
                        st.warning(
                            f"Origem **{cab0['origin']}** — não é preço negociado. "
                            f"Proxy de: {cab0['proxy_of'] or 'não declarado'}."
                        )
                    if curva_escolhida == CVS.CURVE_NAME:
                        st.info(f"⚠️ {CVS.DISCLAIMER}")
                    st.dataframe(linhas_tabela, use_container_width=True)
                    try:
                        import pandas as pd
                        import plotly.express as px
                        df = pd.DataFrame(linhas_tabela)
                        df["preço (R$/MWh)"] = df["preço (R$/MWh)"].astype(float)
                        fig = px.line(df, x="início", y="preço (R$/MWh)", color="quote_type",
                                      markers=True, title=f"{curva_escolhida} — {submercado_escolhido}")
                        st.plotly_chart(fig, use_container_width=True)
                    except Exception:
                        pass
                    with st.expander("Metodologia e notas"):
                        st.write(cab0["notes"] or "—")

            st.subheader("Importar curva licenciada manualmente (CSV/XLSX)")
            st.caption(
                "Schema fixo: reference_date, delivery_start, delivery_end, submarket, "
                "energy_type, product, price_brl_mwh, source, curve_type "
                "(MARKET_FORWARD_DELAYED_PUBLIC | MARKET_FORWARD_LICENSED | "
                "STATISTICAL_SCENARIO_PUBLIC | MANUAL_AUTHORIZED_CURVE). "
                "Veja `data/samples/curva_manual_SAMPLE.csv`."
            )
            arquivo_curva = st.file_uploader(
                "Arquivo da curva", type=["csv", "xlsx"], key="curva_licenciada_upload"
            )
            if arquivo_curva is not None:
                from copilot.ingest.adapters.uploads import LicensedCurveCsvAdapter
                from copilot.ingest.snapshots import SnapshotStore as _SnapshotStore
                from src.services.ingestion_bridge import persist_adapter_result as _persist
                try:
                    resultado = LicensedCurveCsvAdapter(
                        snapshot_store=_SnapshotStore(ROOT / "data" / "snapshots")
                    ).run(as_of=settings.data_cut_off, file=arquivo_curva.getvalue(),
                          filename=arquivo_curva.name)
                    saida = _persist(conn, resultado, as_of=AS_OF, access_label="MANUAL")
                    st.success(f"{saida['curves']} curva(s) importada(s) e persistida(s).")
                except Exception as exc:
                    st.error(f"Arquivo rejeitado: {exc}")
finally:
    conn.close()
