"""Energy Trading Copilot — interface Streamlit.

Cinco areas: Dashboard, Teses, Debate, Monitor, Dados e fontes.
A aplicacao inicia mesmo sem credenciais externas (modo demonstracao).
"""

from __future__ import annotations

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
from src.rag import store as RAG  # noqa: E402
from src.services import debate_service as DS  # noqa: E402
from src.services import risk_service as RS  # noqa: E402
from src.services import thesis_service as TS  # noqa: E402
from src.services import watchdog_service as WD  # noqa: E402

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
    area = st.sidebar.radio("Área", ["Dashboard", "Teses", "Debate", "Monitor", "Dados e fontes"])

    # ============================================================== DASHBOARD
    if area == "Dashboard":
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
