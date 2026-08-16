"""Orquestrador. `python -m src.cli run` executa o pipeline inteiro."""
from __future__ import annotations
import argparse, glob, json, logging, sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (DATA_CORTE, FIM_HORIZONTE, DIR_RAW, DIR_PROC, DIR_OUT, DIR_FIX,
                     FONTES, LIMITES_PLD, NOME_CURVA, PREMISSAS, Rotulo)
from . import fontes as F, ingest, qualidade, sazonalidade as sz, cenarios, curva as CV
from . import risco, posicao, saidas, relatorio, manifesto, excel_modelo
from . import boletins as BOL, parse_infopld as PI, parse_ipdo as PJ
from . import ancora as ANC, excel_boletins as XB
from . import premio as PRM, book as BK, excel_book as XBK

log = logging.getLogger("curva")


def _setup_log(v=False):
    # pdfminer/pdfplumber emitem uma linha de DEBUG por token do PDF. Com -v, um
    # boletim de 15 MB gera centenas de milhares de linhas e o run, que leva ~90s,
    # passa de varios minutos. O -v serve para ver o NOSSO log, nao o do parser.
    for _ruidoso in ("pdfminer", "pdfplumber", "PIL", "matplotlib", "fontTools"):
        logging.getLogger(_ruidoso).setLevel(logging.WARNING)
        logging.getLogger(_ruidoso).propagate = False
    logging.basicConfig(level=logging.DEBUG if v else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")


def _arquivos(base: Path, chave: str) -> list[Path]:
    d = base / chave
    if not d.exists():
        return []
    return sorted([Path(p) for p in glob.glob(str(d / "*")) if Path(p).is_file()])



# ------------------------------------------------------------ boletins
def _ingerir_boletins(pasta: Path, log) -> dict:
    """Encontra, identifica, registra e extrai InfoPLD e IPDO da pasta.

    Respeita a DATA DE CORTE: boletim publicado depois de 14/08/2026 nao existe
    para o modelo. E assim que o Modo Case fica congelado e reproduzivel.
    """
    out = {"ok": False, "motivo": ""}
    pasta = Path(pasta)
    pdfs = sorted(pasta.glob("*.pdf")) + sorted((pasta / "boletins").glob("*.pdf")) \
        if pasta.exists() else []
    if not pdfs:
        out["motivo"] = f"nenhum PDF em {pasta}"
        log.info("boletins: %s — seguindo com a ancora antiga (CMO)", out["motivo"])
        return out

    repo = BOL.Repositorio(DIR_PROC / "boletins")
    docs, por_tipo = [], {}
    for f in pdfs:
        try:
            d = BOL.identificar(f)
        except Exception as e:
            log.warning("boletins: %s ignorado (%s)", f.name, e)
            continue
        if d.tipo == "DESCONHECIDO":
            log.warning("boletins: %s nao identificado; ignorado", f.name)
            continue
        if date.fromisoformat(d.data_referencia) > DATA_CORTE:
            log.warning("boletins: %s (%s) e POSTERIOR a data de corte %s — excluido",
                        f.name, d.data_referencia, DATA_CORTE)
            continue
        novo, msg = repo.registrar(d)
        docs.append(d.dict())
        ant = por_tipo.get(d.tipo)
        if ant is None or d.data_referencia > ant.data_referencia:
            por_tipo[d.tipo] = d
        log.info("boletins: %s | %s | ref %s | %s", d.tipo, f.name, d.data_referencia, msg)

    if "INFOPLD" not in por_tipo:
        out["motivo"] = "nenhum InfoPLD valido ate a data de corte"
        log.info("boletins: %s", out["motivo"])
        return out

    dinfo = por_tipo["INFOPLD"]
    info_df, diag_info = PI.extrair(dinfo.caminho)
    log.info("InfoPLD %s: %s observacoes (resumo pag %s, PLD pag %s, ENA pag %s, EARM pag %s)",
             dinfo.data_referencia, diag_info["total_obs"], diag_info["resumo"]["pagina"],
             diag_info["traj_PLD"]["pagina"], diag_info["traj_ENA"]["pagina"],
             diag_info["traj_EARM"]["pagina"])

    ipdo_df, diag_ipdo = (pd.DataFrame(), {})
    if "IPDO" in por_tipo:
        dip = por_tipo["IPDO"]
        ipdo_df, diag_ipdo = PJ.extrair(dip.caminho)
        log.info("IPDO %s: %s observacoes", dip.data_referencia, diag_ipdo["total_obs"])
        defasagem = (date.fromisoformat(dinfo.data_referencia)
                     - date.fromisoformat(dip.data_referencia)).days
        if abs(defasagem) > 3:
            log.warning("FONTES COM DATAS INCONSISTENTES: InfoPLD %s x IPDO %s (%s dias). "
                        "Revisar antes de usar a curva.", dinfo.data_referencia,
                        dip.data_referencia, defasagem)
        out["defasagem_dias"] = defasagem
    out.update({"ok": True, "infopld_df": info_df, "ipdo_df": ipdo_df,
                "diag_info": diag_info, "diag_ipdo": diag_ipdo, "docs": docs,
                "doc_infopld": Path(dinfo.caminho).name,
                "data_infopld": dinfo.data_referencia,
                "data_ipdo": por_tipo["IPDO"].data_referencia if "IPDO" in por_tipo else None})
    return out


def _cenarios_boletim(bol: dict, sub: str, alvo, log) -> dict:
    if not bol.get("ok"):
        return bol
    cen, dcen = ANC.selecionar_cenarios(bol["infopld_df"], sub, alvo,
                                        PREMISSAS.trajetoria_central)
    bol["cenarios"], bol["diag_cen"] = cen, dcen
    if dcen.get("alerta"):
        log.warning("ACHADO: %s", dcen["alerta"])
    if dcen.get("alerta_ordenacao"):
        log.warning("%s", dcen["alerta_ordenacao"])
    if len(bol.get("ipdo_df", [])):
        aj, det, dn = ANC.nowcast(bol["ipdo_df"], bol["infopld_df"], alvo,
                                  PREMISSAS.nowcast_meia_vida_meses)
        log.info("nowcast IPDO: %.2f%% no mes corrente, %.3f%% no ultimo mes",
                 dn["ajuste_primeiro_mes_pct"], dn["ajuste_ultimo_mes_pct"])
    else:
        aj = pd.Series(0.0, index=alvo)
        det = pd.DataFrame(columns=["driver", "programado", "realizado", "surpresa_pct",
                                    "z", "sensibilidade", "contribuicao_pct"])
        dn = {"meia_vida_meses": PREMISSAS.nowcast_meia_vida_meses,
              "contribuicao_total_pct": 0.0, "ajuste_primeiro_mes_pct": 0.0,
              "ajuste_ultimo_mes_pct": 0.0, "limitacao": "sem IPDO"}
    bol["ajuste_nowcast"], bol["nowcast_det"], bol["diag_nowcast"] = aj, det, dn
    return bol

# ------------------------------------------------------------------ comandos
def cmd_boletins(args):
    """Ingere os boletins e mostra o que foi extraido, sem tocar na curva."""
    _setup_log(args.verbose)
    pasta = Path(args.pasta) if args.pasta else Path(PREMISSAS.dir_boletins)
    bol = _ingerir_boletins(pasta, log)
    if not bol.get("ok"):
        raise SystemExit(f"FALHA: {bol.get('motivo')}")
    alvo = CV.meses_alvo(pd.Timestamp("2026-08-01"), pd.Timestamp(FIM_HORIZONTE))
    bol = _cenarios_boletim(bol, PREMISSAS.submercado, alvo, log)
    print("\n=== PROJECAO OFICIAL DE PLD (SE/CO) ===")
    print(bol["cenarios"].round(2).to_string(index=False))
    d = bol["diag_cen"]
    print(f"\n  Esperado={d['trajetoria_esperado']}  Seco={d['trajetoria_seco']}  "
          f"Umido={d['trajetoria_umido']}")
    print(f"  medias flat: {({k: round(v, 2) for k, v in d['preco_medio'].items()})}")
    print("\n=== SCORE HIDROLOGICO ===")
    print(pd.DataFrame(d["score"])[["trajetoria", "ena_media_pct_mlt", "earm_media_pct",
                                    "score_umidade"]].round(2).to_string(index=False))
    if d.get("alerta"):
        print("\n  ACHADO:", d["alerta"])
    print("\n=== SURPRESAS DO IPDO ===")
    print(bol["nowcast_det"][["driver", "programado", "realizado", "surpresa_pct",
                              "contribuicao_pct"]].round(4).to_string(index=False))


def cmd_sync(args):
    _setup_log(args.verbose)
    log.info("sincronizando fontes publicas (CKAN CCEE + ONS)")
    F.sincronizar_tudo(log=log.info)
    log.info("manifesto: %s itens", len(manifesto.itens()))


def cmd_run(args):
    _setup_log(args.verbose)
    base = DIR_FIX if args.fixtures else (Path(args.raw_dir) if args.raw_dir else DIR_RAW)
    hoje = date.today()
    provisorio = hoje < DATA_CORTE
    status = "FIXTURE_NAO_USAR_PARA_TESE" if args.fixtures else ("PROVISORIO" if provisorio else "DEFINITIVO")
    motivo = ""
    if args.fixtures:
        motivo = ("Execucao sobre FIXTURES com o schema das fontes oficiais. Serve para validar o "
                  "pipeline; NAO sustenta tese. Rode `make sync && make run` com internet.")
    elif provisorio:
        motivo = (f"Execucao em {hoje:%d/%m/%Y}, antes da data de corte {DATA_CORTE:%d/%m/%Y}. "
                  f"Somente dados ja publicados foram usados. Reexecutar em 14/08/2026.")
    log.info("status do run: %s", status)
    _status_base, _motivo_base = status, motivo

    # ---------------------------------------------------------------- ingest
    arq_pld = _arquivos(base, "pld_horario")
    if not arq_pld:
        raise SystemExit(
            f"FALHA EXPLICITA: nenhum arquivo de PLD em {base/'pld_horario'}.\n"
            f"Rode `python -m src.cli sync` (precisa de internet) ou use --fixtures para validar o codigo.")
    pld = ingest.normalizar_pld(arq_pld)
    log.info("PLD: %s obs, %s a %s", len(pld), pld.ts.min(), pld.ts.max())

    sub = args.submercado
    flat = ingest.flat_mensal(pld, sub)
    flat = flat[flat.cobertura >= 0.98]                     # mes incompleto nao vira mes barato
    if len(flat) < 24:
        raise SystemExit(f"FALHA: apenas {len(flat)} meses completos de PLD para {sub}; "
                         f"a metodologia exige >= 24.")

    arq_ena, arq_ear = _arquivos(base, "ena_diario"), _arquivos(base, "ear_diario")
    if not arq_ena or not arq_ear:
        raise SystemExit("FALHA EXPLICITA: ENA/EAR do ONS ausentes. Sem eles nao ha classificacao "
                         "de regime hidrologico. Rode sync ou use --fixtures.")
    ena = ingest.normalizar_ons_diario(arq_ena, "ena")
    ear = ingest.normalizar_ons_diario(arq_ear, "ear")

    arq_cmo = _arquivos(base, "cmo_semanal")
    cmo = ingest.normalizar_ons_diario(arq_cmo, "ena") if False else None
    if arq_cmo:
        try:
            c = []
            for a in arq_cmo:
                df = ingest.ler_csv_flex(a)
                c_dt = ingest._col(df, ["din_instante", "data"], [r"data", r"^din"], "data")
                c_sb = ingest._col(df, ["id_subsistema", "nom_subsistema"], [r"subsist"], "subsistema")
                c_vl = ingest._col(df, ["val_cmomediasemanal", "val_cmo"], [r"cmo"], "CMO")
                c.append(pd.DataFrame({"data": ingest._dt(df[c_dt]).dt.date,
                                       "submercado": ingest._sub(df[c_sb]),
                                       "valor": pd.to_numeric(df[c_vl], errors="coerce")}))
            cmo = pd.concat(c, ignore_index=True).dropna()
            cmo = cmo[cmo.data <= DATA_CORTE]
            log.info("CMO semanal: %s obs", len(cmo))
        except Exception as e:
            log.warning("CMO nao parseado (%s) - componente fundamental fica ausente e declarado", e)
            cmo = None

    arq_mve = _arquivos(base, "mve")
    mve = ingest.normalizar_mve(arq_mve) if arq_mve else pd.DataFrame()

    # -------------------------------------------------------------- qualidade
    checks = qualidade.consolidar(
        qualidade.checar_pld(pld, sub),
        qualidade.reconciliar(pld, ingest.flat_mensal(pld, sub), sub),
        qualidade.checar_cobertura_flat(ingest.flat_mensal(pld, sub)),
    )
    falhas = checks[checks.status == qualidade.FALHA]
    if len(falhas):
        log.error("checks com FALHA:\n%s", falhas.to_string(index=False))
        if not args.ignorar_falhas:
            raise SystemExit("FALHA: checks de qualidade reprovaram. Use --ignorar-falhas para forcar.")
    log.info("qualidade: %s OK, %s alerta, %s falha",
             (checks.status == "OK").sum(), (checks.status == "ALERTA").sum(), len(falhas))

    # ------------------------------------------------------------ sazonalidade
    ref = pd.Timestamp(flat.mes_ref.max())
    wf = sz.walk_forward(flat, PREMISSAS.meias_vidas_teste,
                         janela_meses=PREMISSAS.janela_sazonal_meses,
                         sigma_meses=PREMISSAS.kernel_calendario_dias / 30.0)
    res_wf = sz.resumo_walk_forward(wf)
    if res_wf.empty:
        raise SystemExit("FALHA: walk-forward sem observacoes suficientes.")
    hl = int(res_wf.meia_vida.iloc[0])
    log.info("meia-vida escolhida por walk-forward: %s dias\n%s", hl, res_wf.to_string(index=False))

    sens = []
    for h in PREMISSAS.meias_vidas_teste:
        t, _ = sz.fatores_sazonais(flat, ref, h, PREMISSAS.janela_sazonal_meses,
                                   PREMISSAS.kernel_calendario_dias / 30.0, PREMISSAS.winsor)
        sens.append(t.assign(meia_vida=h))
    sens = pd.concat(sens, ignore_index=True)

    fatores, diag_sz = sz.fatores_sazonais(flat, ref, hl, PREMISSAS.janela_sazonal_meses,
                                           PREMISSAS.kernel_calendario_dias / 30.0, PREMISSAS.winsor)

    # ------------------------------------------------- BOLETINS (InfoPLD/IPDO)
    # A ancora fundamental deixa de ser o CMO realizado do ONS (que nunca cobria o
    # horizonte a frente) e passa a ser a projecao oficial de PLD da CCEE.
    bol = _ingerir_boletins(Path(base if args.fixtures else PREMISSAS.dir_boletins), log)
    if bol.get("ok") and status.startswith("FIXTURE"):
        # Os boletins sao documentos OFICIAIS de verdade; a serie historica de PLD
        # e que continua sintetica. Dizer so "FIXTURE" seria injusto com a ancora,
        # e dizer "DEFINITIVO" seria mentira sobre a serie. Entao: MISTO.
        status = "MISTO — ancora e cenarios OFICIAIS; serie historica em fixture"
        motivo = (f"Ancora fundamental, cenarios e nowcast vem do InfoPLD "
                  f"{bol['data_infopld']} e do IPDO {bol.get('data_ipdo')}, documentos "
                  f"oficiais reais. A serie historica de PLD diario usada na "
                  f"sazonalidade e no VaR continua sintetica (fixture). Para a entrega, "
                  f"rodar `make sync` e trocar a serie por dado da CCEE.")
        log.info("status revisado: %s", status)

    # ------------------------------------------------------------------ curva
    inicio = (ref + pd.DateOffset(months=1))
    alvo = CV.meses_alvo(inicio, pd.Timestamp(FIM_HORIZONTE))
    if len(alvo) == 0:
        raise SystemExit("FALHA: horizonte vazio - o ultimo mes observado ja passou de 31/12/2026.")

    bol = _cenarios_boletim(bol, sub, alvo, log)

    s_saz, _, _ = CV.curva_sazonal(flat, ref, hl, alvo, PREMISSAS.janela_sazonal_meses,
                                   PREMISSAS.kernel_calendario_dias / 30.0, PREMISSAS.winsor,
                                   PREMISSAS.meia_vida_nivel_meses)
    nivel_col = sz.nivel_ewma(flat, fatores, PREMISSAS.meia_vida_nivel_meses)
    reg = cenarios.classificar(ena, ear, sub, PREMISSAS.quantil_seco, PREMISSAS.quantil_umido)
    efeitos_mqo, amostra_reg = cenarios.estimar_efeitos(flat, reg)      # challenger
    ef_res = cenarios.estimar_efeitos_residual(flat, reg, fatores)      # OFICIAL
    # O estimador oficial e o RESIDUAL porque e o unico que a planilha consegue
    # reproduzir celula a celula. O MQO com dummies de mes fica como challenger, e a
    # diferenca entre os dois e reportada como incerteza de modelo, nao escondida.
    efeitos = dict(efeitos_mqo)
    efeitos.update({"k_seco": ef_res["k_seco"], "k_umido": ef_res["k_umido"],
                    "metodo": "residual (replicado na planilha)",
                    "k_seco_mqo": efeitos_mqo["k_seco"], "k_umido_mqo": efeitos_mqo["k_umido"],
                    "ordenacao_coerente": bool(ef_res["k_seco"] > 1 > ef_res["k_umido"])})
    if bol.get("ok") and bol["diag_cen"]["trajetoria_seco"] == \
            bol["diag_cen"]["trajetoria_esperado"]:
        # O leque oficial nao tem trajetoria mais seca que a central. O cenario
        # Seco efetivo passa a ser o estimador estatistico, e essa substituicao
        # e feita AQUI, na origem, para que planilha e Python enxerguem a MESMA
        # coluna Seco. Fazer a troca so no Python deixava a dispersao do Excel
        # zerada em agosto e o sinal divergia.
        bol["cenarios"]["Seco"] = bol["cenarios"].Esperado * efeitos["k_seco"]
        bol["diag_cen"]["trajetoria_seco"] = (
            f"estatistico k={efeitos['k_seco']:.3f} (leque oficial sem cenario "
            f"mais seco que o central)")
        bol["diag_cen"]["seco_por_estimador"] = True
        log.info("cenario SECO substituido pelo estimador estatistico na origem")
    log.info("k oficial (residual): seco=%.3f umido=%.3f | challenger MQO: seco=%.3f umido=%.3f",
             efeitos["k_seco"], efeitos["k_umido"],
             efeitos_mqo["k_seco"], efeitos_mqo["k_umido"])

    if bol.get("ok"):
        s_fun, piv_traj, info_fun = ANC.ancora_pld(bol["infopld_df"], sub, alvo,
                                                   PREMISSAS.trajetoria_central)
        info_fun["status"] = "ok" if s_fun.notna().any() else "sem cobertura"
        log.info("ancora InfoPLD (%s): %s meses, alta precisao em %s",
                 PREMISSAS.trajetoria_central, info_fun["meses_cobertos"],
                 info_fun["meses_alta_precisao"])
    else:
        s_fun, info_fun = CV.ancora_fundamental(cmo, alvo, sub)
    if bol.get("ok"):
        # Com ancora oficial disponivel, o peso e PREMISSA declarada e nao backtest:
        # nao ha historico de projecoes do InfoPLD armazenado para validar fora da
        # amostra. Assim que houver varias edicoes arquivadas, trocar por backtest.
        w = PREMISSAS.peso_ancora_infopld
        bt_pesos = pd.DataFrame([{"w": w, "RMSE": np.nan, "MAE": np.nan, "vies": np.nan,
                                  "n": 0, "obs": "peso premissa (sem historico de "
                                                 "boletins para backtest)"}])
        log.info("peso da ancora InfoPLD: %.2f (premissa declarada)", w)
    else:
        w, bt_pesos = CV.peso_por_backtest(flat, cmo, sub, hl, PREMISSAS.janela_sazonal_meses,
                                           PREMISSAS.kernel_calendario_dias / 30.0,
                                           PREMISSAS.winsor)
        log.info("peso do fundamental por backtest: %.1f", w)

    ajuste_now = bol.get("ajuste_nowcast")
    if ajuste_now is None:
        ajuste_now = pd.Series(0.0, index=alvo)

    # ---- premio a termo calibrado contra a referencia de mercado
    ref_mkt = pd.Series({pd.Timestamp(k + "-01"): v
                         for k, v in PREMISSAS.ref_mercado.items()}).reindex(alvo)
    cal_prem, diag_prem = None, {}
    if bol.get("ok") and ref_mkt.notna().any():
        cal_prem, diag_prem = PRM.calibrar(s_fun, ref_mkt)
        log.info("premio a termo: nivel R$ %.2f/MWh (%.1f%%), formato %s",
                 diag_prem["nivel_rs_mwh"], diag_prem["nivel_pct"] * 100,
                 diag_prem["formato_termo"])
        # Dispersao vem das trajetorias do InfoPLD e e invariante a escala,
        # entao pode ser calculada antes da curva — sem circularidade.
        cenb0 = bol["cenarios"]
        disp0 = PRM.dispersao_cenarios(
            pd.Series(cenb0.Seco.to_numpy(), index=alvo),
            pd.Series(cenb0.Esperado.to_numpy(), index=alvo),
            pd.Series(cenb0.Umido.to_numpy(), index=alvo))
        k_prem = PRM.calibrar_k(cal_prem, disp0)
        premio_justo_s = (k_prem * disp0).rename("premio_justo")
        log.info("premio justo por dispersao: k=%.1f | %s", k_prem,
                 " ".join(f"{pd.Timestamp(m):%b}={v:.1f}"
                          for m, v in premio_justo_s.items()))
        modo_curva = ("premio_justo" if PREMISSAS.modo_sinal == "valor_relativo"
                      else PREMISSAS.premio_modo)
        curva_prem, diag_modo = PRM.aplicar(s_fun, s_saz, w, ajuste_now, cal_prem,
                                            modo_curva, premio_justo_s)
        diag_modo["k_premio"] = k_prem
        comp = curva_prem.rename(columns={"base_modelo": "base_combinada"})
        comp["ancora_infopld"] = s_fun.to_numpy()
        comp["estatistico_ewma"] = s_saz.to_numpy()
        comp["ajuste_nowcast_pct"] = ajuste_now.to_numpy() * 100
        diag_comp = {**diag_prem, **diag_modo}
        log.info("modo do premio: %s — %s", modo_curva, diag_modo["explicacao"])
    else:
        comp, diag_comp = ANC.compor_curva(s_fun, s_saz, ajuste_now, w,
                                           PREMISSAS.premio_basis_rs_mwh)
    fv, flag = CV.aplicar_limites(pd.Series(comp.fair_value.to_numpy(), index=alvo), alvo)

    cb = pd.DataFrame({"mes_ref": alvo, "horas_mes": [posicao.horas_do_mes(m) for m in alvo],
                       "fundamental": s_fun.to_numpy(), "sazonal": s_saz.to_numpy(),
                       "peso": w, "fair_value": fv.to_numpy(), "limite": flag.to_numpy(),
                       "nowcast_pct": comp.ajuste_nowcast_pct.to_numpy()})

    if bol.get("ok"):
        # Cenarios vem de TRAJETORIAS OFICIAIS INTEIRAS do InfoPLD, nao de um
        # multiplicador estatistico aplicado a curva central. O multiplicador
        # estimado continua calculado e vira challenger.
        cenb = bol["cenarios"]
        razao = cb.fair_value.to_numpy() / np.where(cenb.Esperado.to_numpy() > 0,
                                                    cenb.Esperado.to_numpy(), np.nan)
        cb["umido"] = cenb.Umido.to_numpy() * razao
        if bol["diag_cen"].get("seco_por_estimador"):
            # O leque oficial NAO oferece cenario mais seco que o central: a propria
            # RNA e a trajetoria mais seca das cinco neste horizonte. Um "Seco" igual
            # ao "Esperado" nao serve para risco. Usa-se entao o multiplicador
            # estatistico estimado sobre regimes historicos, com metodo declarado.
            cb["seco"] = cb.fair_value * efeitos["k_seco"]
            efeitos["fonte_seco"] = (
                f"estimador estatistico (k={efeitos['k_seco']:.3f}) — o leque oficial "
                f"do InfoPLD nao tem trajetoria mais seca que a central "
                f"({bol['diag_cen']['trajetoria_esperado']})")
            log.warning("cenario SECO por estimador estatistico: a trajetoria central "
                        "ja e a mais seca do leque oficial")
        else:
            cb["seco"] = cenb.Seco.to_numpy() * razao
            efeitos["fonte_seco"] = f"InfoPLD — {bol['diag_cen']['trajetoria_seco']}"
        efeitos["k_seco_infopld"] = float(np.nanmean(cenb.Seco / cenb.Esperado))
        efeitos["k_umido_infopld"] = float(np.nanmean(cenb.Umido / cenb.Esperado))
        efeitos["fonte_cenarios"] = (
            f"InfoPLD — Esperado={bol['diag_cen']['trajetoria_esperado']}, "
            f"Seco={bol['diag_cen']['trajetoria_seco']}, "
            f"Umido={bol['diag_cen']['trajetoria_umido']}")
        log.info("cenarios do InfoPLD: %s", efeitos["fonte_cenarios"])
        log.info("  k implicito -> seco %.3f | umido %.3f (estatistico: %.3f / %.3f)",
                 efeitos["k_seco_infopld"], efeitos["k_umido_infopld"],
                 efeitos["k_seco"], efeitos["k_umido"])
    else:
        cb["seco"] = cb.fair_value * efeitos["k_seco"]
        cb["umido"] = cb.fair_value * efeitos["k_umido"]

    # --------------------------------------------------------------- cenarios

    # ------------------------------------------------------------------ risco
    # FATOR DE RISCO = preco a termo do proprio strip, reconstruido walk-forward.
    # O PLD spot entra apenas como challenger (limite superior), porque a
    # volatilidade do spot nao e a volatilidade de um contrato a termo.
    fwd = CV.backcast_forward(flat, alvo, hl, PREMISSAS.janela_sazonal_meses,
                              PREMISSAS.kernel_calendario_dias / 30.0, PREMISSAS.winsor,
                              n_origens=PREMISSAS.n_origens_forward,
                              mv_nivel=PREMISSAS.meia_vida_nivel_meses)
    if fwd.empty or fwd.ret.notna().sum() < 12:
        raise SystemExit("FALHA: nao foi possivel reconstruir a serie de forward "
                         "(historico insuficiente). Sem fator de risco, nao ha VaR.")
    pesos_h0 = np.array([posicao.horas_do_mes(m) for m in alvo], float)
    fv_flat0 = float(np.average(cb.fair_value, weights=pesos_h0))
    v_bc = risco.var_forward(fwd.ret, fv_flat0, PREMISSAS.var_confianca,
                             PREMISSAS.lambda_forward, PREMISSAS.var_horizonte_meses)
    # PRINCIPAL: volatilidade do NIVEL dessazonalizado, amortecida ate a entrega.
    # O backcast passa o nivel por uma EWMA de 6 meses; medir a volatilidade dali
    # e medir o suavizador, nao o mercado. Ele fica como PISO declarado.
    fat_saz = fatores.set_index("mes")["fator"]
    precos_v = pd.Series(cb.fair_value.to_numpy(float), index=pd.DatetimeIndex(alvo))
    v = risco.var_nivel(flat, fat_saz, precos_v, DATA_CORTE,
                        PREMISSAS.var_confianca, PREMISSAS.lambda_forward)
    v["vol_ewma_mensal"] = v["vol_nivel_mensal"]
    v["var_preco_hist"] = v_bc["var_preco"]
    v["var_preco_piso_backcast"] = v_bc["var_preco"]
    var_vert = v["tabela"].set_index("mes_ref")["var_rs_mwh"]
    es_vert = v["tabela"].set_index("mes_ref")["es_rs_mwh"]
    log.info("VaR a termo (nivel amortecido): %.2f R$/MWh medio | vol do nivel %.1f%% a.m., "
             "meia-vida %.1f meses | por vertice: %s", v["var_preco"],
             100 * v["vol_nivel_mensal"], v["meia_vida_nivel_meses"],
             ", ".join(f"{m.strftime('%b')}={x:.1f}" for m, x in var_vert.items()))
    log.info("piso declarado (backcast do proprio modelo, suavizado): %.2f R$/MWh -> "
             "o metodo principal e %.1fx maior", v_bc["var_preco"],
             v["var_preco"] / max(v_bc["var_preco"], 1e-9))

    diario = (pld[(pld.submercado == sub)].set_index("ts").pld.resample("D").mean().dropna())
    esc = risco.escolher_representacao(diario, PREMISSAS.var_lambda_ewma)
    rep = esc["escolhida"]
    mv_rev = risco.meia_vida_reversao(diario)
    v_spot = risco.fhs(diario, PREMISSAS.var_confianca, PREMISSAS.var_horizonte_du,
                       PREMISSAS.var_lambda_ewma, rep, agregacao="sobreposta")
    v_spot["var_preco"] = abs(fv_flat0 * (np.exp(v_spot["q_choque"]) - 1.0))
    v_ch = risco.historico(diario, PREMISSAS.var_confianca, PREMISSAS.var_horizonte_du, rep)
    v_iid = v_spot
    log.info("meia-vida de reversao do PLD diario = %.1f dias", mv_rev)
    log.info("challenger sobre SPOT (superestima o termo): %.2f R$/MWh -> razao spot/termo = %.1fx",
             v_spot["var_preco"], v_spot["var_preco"] / max(v["var_preco"], 1e-9))

    # --------------------------------------------------------------- posicao
    mve_f, info_mve = CV.proxy_mve(mve, sub, alvo)
    preco_entrada = info_mve.get("preco_medio_ponderado")
    orcamento = PREMISSAS.limite_var_brl * PREMISSAS.var_orcamento_frac
    # referencia observavel alternativa: PLD flat dos ultimos 3 meses fechados
    ref_alt = float(flat.tail(3).flat.mean())
    # Perda por MWm se a posicao for carregada ate a entrega no cenario adverso.
    # A direcao ainda nao esta fixada; usa-se o pior dos dois lados, que e o
    # conservador correto antes de escolher o lado.
    _h = float(np.sum(pesos_h0))
    _fv = fv_flat0
    _p_ent_hip = _fv - PREMISSAS.edge_minimo_rs_mwh
    _seco = float(np.average(cb.seco, weights=pesos_h0))
    _umido = float(np.average(cb.umido, weights=pesos_h0))
    perda_cen_mwm = max(abs(_umido - _p_ent_hip), abs(_seco - (_fv + PREMISSAS.edge_minimo_rs_mwh))) * _h
    pos = posicao.definir_posicao(cb.fair_value, preco_entrada, PREMISSAS.edge_minimo_rs_mwh,
                                  v["var_preco"], orcamento, alvo,
                                  referencia_alternativa=ref_alt,
                                  fonte_referencia="PLD flat medio dos 3 ultimos meses fechados",
                                  mwm_teto=PREMISSAS.mwm_maximo_operacional,
                                  perda_cenario_por_mwm=perda_cen_mwm,
                                  orcamento_cenario=PREMISSAS.limite_var_brl * PREMISSAS.frac_stress)
    horas_total = pos["horas"]
    mwm = pos.get("mwm", 0.0)
    dirc = pos.get("direcao", 0)
    p_ent = pos.get("preco_entrada", pos.get("comprar_ate"))

    var_brl = risco.var_posicao(v["var_preco"], mwm, horas_total, dirc)
    es_brl = risco.var_posicao(v["es_preco"], mwm, horas_total, dirc)
    consumo = var_brl / PREMISSAS.limite_var_brl

    pesos_h = np.array([posicao.horas_do_mes(m) for m in alvo], float)
    preco_cen = {"base": float(np.average(cb.fair_value, weights=pesos_h)),
                 "seco": float(np.average(cb.seco, weights=pesos_h)),
                 "umido": float(np.average(cb.umido, weights=pesos_h))}
    pnl_cen = {k: risco.pnl(dirc, mwm, horas_total, p_ent or 0.0, x) for k, x in preco_cen.items()}
    prob = PREMISSAS.prob_cenarios
    pnl_esp = sum(prob[k] * pnl_cen[k] for k in pnl_cen)
    preco_esp = sum(prob[k] * preco_cen[k] for k in preco_cen)
    # A amostra do FHS descreve choques em torno do PLD spot (p0). O produto negociado
    # e um flat a termo cujo valor esperado e o fair value. Aplicar os choques em termos
    # RELATIVOS sobre o fair value mantem a escala de incerteza e centra a distribuicao no
    # lugar certo. Somar o choque absoluto ao spot (erro cometido na 1a versao) produzia
    # P5/P95 incoerentes com o PnL esperado.
    choques_rel = np.exp(np.random.default_rng(7).choice(
        v["amostra_ret"], size=20000) * np.sqrt(PREMISSAS.var_horizonte_meses)) - 1.0
    precos_saida = preco_cen["base"] * (1.0 + choques_rel)
    amostra_pnl = dirc * mwm * horas_total * (precos_saida - (p_ent or 0.0)) if mwm else None
    pnl_p5 = float(np.quantile(amostra_pnl, .05)) if amostra_pnl is not None else float("nan")
    pnl_p95 = float(np.quantile(amostra_pnl, .95)) if amostra_pnl is not None else float("nan")
    fluxos = [(pd.Timestamp(m).to_period("M").to_timestamp("M").date(),
               risco.pnl(dirc, mwm, posicao.horas_do_mes(m), p_ent or 0.0, float(x)))
              for m, x in zip(alvo, cb.fair_value)]
    vpl = posicao.vpl(fluxos, PREMISSAS.taxa_desconto_aa, hoje)
    var_cen = {k: var_brl * (efeitos["k_seco"] if k == "seco" else efeitos["k_umido"] if k == "umido" else 1.0)
               for k in ("base", "seco", "umido")}
    checks = qualidade.consolidar(checks, qualidade.checar_risco(
        var_brl, min(pnl_cen.values()) if pnl_cen else 0.0, es_brl, consumo))

    grade = np.linspace(0, max(mwm * 2, 100), 40)
    sens_tam = pd.DataFrame({"mwm": grade,
                             "var_brl": [risco.var_posicao(v["var_preco"], m, horas_total, dirc) for m in grade]})

    # ------------------------------------------------------------------ book
    book_res, sinal_df, pernas, cal_justo = None, None, [], None
    if cal_prem is not None:
        curva_fv = pd.Series(cb.fair_value.to_numpy(), index=alvo)
        # PREMIO JUSTO por mes: proporcional a abertura do leque de cenarios.
        # Sem isso, o premio medio e aplicado ao mes corrente, que quase nao tem
        # risco restante, e o edge dele fica artificialmente enorme.
        cal_justo = cal_prem.copy()
        cal_justo["dispersao"] = disp0.to_numpy()
        cal_justo["k_premio"] = k_prem
        cal_justo["premio_justo"] = premio_justo_s.to_numpy()
        cal_justo["sinal_relativo"] = cal_justo.premio_rs - cal_justo.premio_justo
        cal_justo["fair_value_modelo"] = curva_fv.to_numpy()
        sinal_df = PRM.sinal(cal_justo, PREMISSAS.limiar_sinal_rs, PREMISSAS.modo_sinal,
                             PREMISSAS.auto_limiar, PREMISSAS.k_sigma_limiar,
                             PREMISSAS.custo_execucao_rs)
        log.info("sinal (%s): limiar R$ %.2f (%s, sigma=%.2f) | nivel do edge %.2f | %s",
                 PREMISSAS.modo_sinal, float(sinal_df.limiar.iloc[0]),
                 sinal_df.limiar_vinculante.iloc[0],
                 float(sinal_df.sigma_residuo.iloc[0]),
                 float(sinal_df.edge_nivel.iloc[0]),
                 ", ".join(f"{pd.Timestamp(r.mes_ref):%b}={r.acao}"
                           for _, r in sinal_df.iterrows()))
        if PREMISSAS.dimensionar_pelo_var:
            # RISCO POR VERTICE, dependente do lado, com dados REAIS do InfoPLD.
            # Comprado tem o umido como adverso; vendido tem o seco. O VaR de
            # marcacao entra como PISO quando o cenario adverso e favoravel.
            orc = PREMISSAS.limite_var_brl * PREMISSAS.var_orcamento_frac
            seco_s = pd.Series(cb.seco.to_numpy(), index=alvo)
            umido_s = pd.Series(cb.umido.to_numpy(), index=alvo)
            # VaR POR VERTICE, nao um numero unico: a estrutura a termo de
            # volatilidade e decrescente, entao agosto carrega mais risco de
            # marcacao por MWm do que dezembro.
            risco_v = BK.risco_por_vertice(sinal_df, seco_s, umido_s, ref_mkt,
                                           var_vert)
            pernas, dim_var = BK.dimensionar_por_risco(
                risco_v, orc, mwmed_max=PREMISSAS.mwm_maximo_operacional)
            dim_var.to_csv(DIR_OUT / "book_dimensionamento_risco.csv", index=False)
            log.info("dimensionamento por risco: orcamento R$ %.1f mi | %s",
                     orc / 1e6,
                     " ".join(f"{pd.Timestamp(r.mes_ref):%b}={r.acao[0]}{r.mwmed:.0f}"
                              f"({r.restricao})" for _, r in dim_var.iterrows()))
            log.info("risco por vertice (R$/MWm): %s",
                     " ".join(f"{pd.Timestamp(r.mes_ref):%b}={r.risco_mwm:,.0f}"
                              f"[{r.risco_vinculante[:8]}]" for _, r in dim_var.iterrows()))
            if dim_var.capado_liquidez.any():
                capados = ", ".join(f"{pd.Timestamp(r.mes_ref):%b}"
                                    for _, r in dim_var.iterrows()
                                    if r.capado_liquidez)
                log.warning("VERTICES CAPADOS POR LIQUIDEZ: %s. O VaR permitiria mais, "
                            "mas o teto operacional de %.0f MWm morde antes.",
                            capados, PREMISSAS.mwm_maximo_operacional)
        else:
            dim_var = pd.DataFrame()
            pernas = BK.book_por_sinal(
                sinal_df, PREMISSAS.mwmed_por_perna, ref_mkt,
                neutralizar_nivel=(PREMISSAS.executar_como_spread
                                   and PREMISSAS.modo_sinal == "valor_relativo"))
        if pernas:
            bk = BK.Book(pernas, alvo)
            # ---------------------------------------------------------------
            # DUAS FAMILIAS DE PnL, e confundi-las e o erro classico.
            #
            # 1) CONVERGENCIA DO PREMIO (marcacao a mercado). A tese e que o
            #    premio de cada mes volta ao justo. Saida = ancora + premio
            #    justo. E o PnL que a posicao captura se for desmontada ANTES
            #    da entrega. Por construcao vale exatamente o edge do sinal.
            #
            # 2) CARREGO ATE A ENTREGA. No vencimento o contrato liquida contra
            #    o SPOT e o premio vai a zero. Saida = PLD do cenario, sem
            #    premio nenhum. Consequencia que precisa ficar explicita:
            #    comprar forward e carregar tem valor esperado NEGATIVO igual
            #    ao premio pago; vender tem valor esperado positivo, com a
            #    cauda seca contra. Sao apostas diferentes da de valor relativo.
            # ---------------------------------------------------------------
            anc_s = pd.Series(s_fun.to_numpy(), index=alvo)
            conv = anc_s + premio_justo_s.reindex(alvo)
            cen_pld = bol["cenarios"].set_index("mes_ref") if bol.get("ok") else None
            seco_pld = (pd.Series(cen_pld.Seco.to_numpy(), index=alvo)
                        if cen_pld is not None else pd.Series(cb.seco.to_numpy(), index=alvo))
            # bol["cenarios"].Seco ja e o cenario efetivo (ver substituicao na origem)
            umido_pld = (pd.Series(cen_pld.Umido.to_numpy(), index=alvo)
                         if cen_pld is not None else pd.Series(cb.umido.to_numpy(), index=alvo))
            curvas = {"Convergencia": conv,
                      "Entrega_Esperado": anc_s,
                      "Entrega_Seco": seco_pld,
                      "Entrega_Umido": umido_pld}
            book_res = bk.resumo(curvas, var_vert, es_vert,
                                 PREMISSAS.limite_var_brl, PREMISSAS.taxa_desconto_aa,
                                 hoje)
            log.info("PnL do book — convergencia do premio: R$ %.2f mi | "
                     "carrego ate a entrega: esperado R$ %.2f mi, seco R$ %.2f mi, "
                     "umido R$ %.2f mi",
                     book_res["pnl_Convergencia"] / 1e6,
                     book_res["pnl_Entrega_Esperado"] / 1e6,
                     book_res["pnl_Entrega_Seco"] / 1e6,
                     book_res["pnl_Entrega_Umido"] / 1e6)
            log.info("book: %s pernas | liquido %.0f MWm | VaR R$ %.2f mi "
                     "(%.1f%% do limite)", book_res["n_pernas"],
                     book_res["mwmed_liquido_abs"], book_res["var_total"] / 1e6,
                     book_res["consumo_limite"] * 100)
            bk.resumo_por_perna(curvas).to_csv(DIR_OUT / "book_pernas.csv", index=False)
            bk.posicao_liquida().to_csv(DIR_OUT / "book_posicao_liquida.csv", index=False)
            bk.vpl(curvas, PREMISSAS.taxa_desconto_aa, hoje,
                   cenario="Convergencia").to_csv(DIR_OUT / "book_vpl.csv", index=False)
            sinal_df.to_csv(DIR_OUT / "sinal_vs_mercado.csv", index=False)
            _pnl = bk.pnl(curvas)
            pnl_mes = (_pnl.groupby("mes_ref")[[f"pnl_{k}" for k in curvas]].sum()
                       .reindex(alvo, fill_value=0.0).reset_index()
                       .rename(columns={"index": "mes_ref"}))
            pnl_mes.to_csv(DIR_OUT / "book_pnl_mensal.csv", index=False)
            pos_g = bk.posicao_liquida().set_index("mes_ref").reindex(alvo).reset_index()
            pos_g.columns = ["mes_ref"] + list(pos_g.columns[1:])
            pos_g = pos_g.fillna({"mwmed_liquido": 0.0, "preco_entrada_medio": 0.0})
            try:
                gb = saidas.graficos_book(
                    DIR_OUT / "graficos", cb, sinal_df, pos_g,
                    bk.vpl(curvas, PREMISSAS.taxa_desconto_aa, hoje,
                           cenario="Convergencia"),
                    pnl_mes, ref_mkt, book_res)
                log.info("graficos do book: %s", ", ".join(gb))
            except Exception as e:
                log.warning("graficos do book nao gerados: %s", e)

    # --------------------------------------------------------------- contexto
    man = pd.DataFrame(manifesto.itens())
    if man.empty:
        arqs = [p for k in ("pld_horario", "ena_diario", "ear_diario", "cmo_semanal", "mve")
                for p in _arquivos(base, k)]
        man = pd.DataFrame([{"instituicao": "FIXTURE", "conjunto": p.parent.name + "/" + p.name,
                             "url_origem": "fixture local - NAO e fonte oficial",
                             "url_recurso": str(p), "arquivo": str(p),
                             "baixado_em_utc": "-", "sha256": manifesto.sha256(p),
                             "bytes": p.stat().st_size, "frequencia_atualizacao": "-",
                             "colunas_utilizadas": [], "transformacoes": [],
                             "qualidade_limitacoes": "dado sintetico; nao sustenta tese"}
                            for p in arqs]) if arqs else pd.DataFrame([{
                             "instituicao": "-", "conjunto": "execucao sem sync (fixtures)",
                             "url_origem": "-", "url_recurso": "-", "arquivo": "-",
                             "baixado_em_utc": "-", "sha256": None, "bytes": None,
                             "frequencia_atualizacao": "-", "colunas_utilizadas": [],
                             "transformacoes": [], "qualidade_limitacoes": "fixtures"}])
    resumo = pd.DataFrame([
        {"serie": "PLD horario " + sub, "obs": len(pld), "de": str(pld.ts.min()), "ate": str(pld.ts.max())},
        {"serie": "flat mensal " + sub, "obs": len(flat), "de": str(flat.mes_ref.min().date()),
         "ate": str(flat.mes_ref.max().date())},
        {"serie": "ENA " + sub, "obs": int((ena.submercado == sub).sum()),
         "de": str(ena.data.min()), "ate": str(ena.data.max())},
        {"serie": "EAR " + sub, "obs": int((ear.submercado == sub).sum()),
         "de": str(ear.data.min()), "ate": str(ear.data.max())},
        {"serie": "CMO semanal", "obs": 0 if cmo is None else len(cmo),
         "de": "-" if cmo is None else str(cmo.data.min()), "ate": "-" if cmo is None else str(cmo.data.max())},
        {"serie": "MVE negocios", "obs": len(mve), "de": "-", "ate": "-"},
    ])
    premissas_tab = [
        ("Submercado", sub, "produto principal do case; outros submercados exigem nova curva"),
        ("Produto", PREMISSAS.produto, "energia convencional flat mensal"),
        ("Data de corte", str(DATA_CORTE), "definida pelo case"),
        ("Meia-vida EWMA", f"{hl} dias", f"CALCULADO: escolhida por walk-forward entre {PREMISSAS.meias_vidas_teste}"),
        ("Janela sazonal", f"{PREMISSAS.janela_sazonal_meses} meses", "regime pos-DESSEM e pos-renovavel"),
        ("Kernel de calendario", f"sigma={PREMISSAS.kernel_calendario_dias/30:.2f} meses",
         "amplia amostra por mes-calendario; sem ele, 24 meses dao 2 obs/mes"),
        ("Winsorizacao", str(PREMISSAS.winsor), "robustez a spike sem apagar evento; winsorizados sao listados"),
        ("Peso do fundamental", f"{w:.1f}", "CALCULADO: minimiza RMSE fora da amostra no backtest walk-forward"),
        ("Confianca do VaR", f"{PREMISSAS.var_confianca:.0%}", "escolha declarada"),
        ("Horizonte do VaR", f"{PREMISSAS.var_horizonte_du} dias uteis", "prazo realista de desmontagem em mercado ilíquido"),
        ("Lambda EWMA do forward", PREMISSAS.lambda_forward,
         "serie mensal: lambda menor que o diario de 0,94"),
        ("Representacao de variacao", rep, "CALCULADO: " + esc["criterio"]),
        ("Agregacao temporal do VaR", "sobreposta",
         f"PLD reverte a media (meia-vida {mv_rev:.1f} dias); somar choques iid superestimaria"),
        ("Orcamento de VaR", f"{PREMISSAS.var_orcamento_frac:.0%} do teto",
         "R$ 50 mi e teto, nao meta; buffer para gap e risco de base"),
        ("Taxa de desconto", f"{PREMISSAS.taxa_desconto_aa:.2%} a.a.", "Selic vigente - PREMISSA, revisar"),
        ("Edge minimo", f"{PREMISSAS.edge_minimo_rs_mwh} R$/MWh", "abaixo disso nao ha conviccao para posicao"),
        ("Fracao do limite para stress de cenario", f"{PREMISSAS.frac_stress:.0%}",
         "a perda carregando ate a entrega no cenario adverso tambem tem de caber no limite"),
        ("Teto operacional de tamanho", f"{PREMISSAS.mwm_maximo_operacional:.0f} MWm",
         "limite de LIQUIDEZ, nao de VaR: com consolidacao de contrapartes, desmontar "
         "acima disso move o proprio preco. Vinculante quando o VaR permite mais"),
        ("Meia-vida do nivel", f"{PREMISSAS.meia_vida_nivel_meses:.0f} meses",
         "EWMA do log flat dessazonalizado; media movel de 12m e lisa demais e "
         "subestimava a volatilidade do termo"),
        ("Prob. dos cenarios", str(prob), "premissa; nao sai de modelo probabilistico"),
        ("Quantis de regime", f"{PREMISSAS.quantil_seco}/{PREMISSAS.quantil_umido}", "corte do indice hidro"),
    ]
    var_tab = [
        ("VaR de preco (FHS)", round(v["var_preco"], 4), "R$/MWh", Rotulo.CALCULADO),
        ("ES de preco (FHS)", round(v["es_preco"], 4), "R$/MWh", Rotulo.CALCULADO),
        ("VaR de preco (challenger historico)", round(v_ch["var_preco"], 4), "R$/MWh", Rotulo.CALCULADO),
        ("VaR de preco (sensibilidade iid/raiz-h)", round(v_iid["var_preco"], 4), "R$/MWh", Rotulo.CALCULADO),
        ("Meia-vida de reversao do PLD", round(mv_rev, 1), "dias", Rotulo.CALCULADO),
        ("ES de preco (challenger)", round(v_ch["es_preco"], 4), "R$/MWh", Rotulo.CALCULADO),
        ("Confianca", PREMISSAS.var_confianca, "-", Rotulo.PREMISSA),
        ("Horizonte", PREMISSAS.var_horizonte_du, "dias uteis", Rotulo.PREMISSA),
        ("Lambda", PREMISSAS.var_lambda_ewma, "-", Rotulo.PREMISSA),
        ("Observacoes", v["n_obs"], "dias", Rotulo.OBSERVADO),
        ("MWm", mwm, "MWm", Rotulo.CALCULADO),
    ]
    pos_tab = [(k, (v_ if not isinstance(v_, (list, dict)) else json.dumps(v_)[:200]))
               for k, v_ in pos.items()]
    ctx = {
        "nome_curva": NOME_CURVA, "produto": PREMISSAS.produto, "status": status,
        "status_motivo": motivo, "data_corte": str(DATA_CORTE),
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"), "hoje": hoje,
        "curva": cb, "flat": flat, "fatores": fatores, "sens_meia_vida": sens,
        "efeitos": efeitos, "hidro": reg.rename(columns={"mes_ref": "mes_ref"}),
        "prob": prob, "posicao": pos, "posicao_tab": pos_tab,
        "posicao_rotulo": {"fair_value_flat": Rotulo.FAIR_VALUE, "preco_entrada": Rotulo.PROXY,
                           "mwm": Rotulo.CALCULADO, "direcao": Rotulo.CALCULADO},
        "var_info": v, "var_challenger": v_ch, "var_spot": v_spot["var_preco"],
        "restricao": pos.get("restricao_vinculante", "n/d"),
        "mwm_var": pos.get("mwm_por_VaR", float("nan")),
        "mwm_liq": pos.get("mwm_por_liquidez", float("nan")),
        "mwm_cen": pos.get("mwm_por_cenario", float("nan")), "var_iid": v_iid, "mv_reversao": mv_rev, "repr_criterio": esc["criterio"],
        "var_brl": var_brl, "es_brl": es_brl, "consumo_limite": consumo,
        "var_cen": var_cen, "amostra_pnl": amostra_pnl, "sens_tamanho": sens_tam,
        "orcamento": orcamento, "limite": PREMISSAS.limite_var_brl,
        "frac_orcamento": PREMISSAS.var_orcamento_frac,
        "horas_total": horas_total, "taxa_desconto": PREMISSAS.taxa_desconto_aa,
        "preco_cen": preco_cen, "pnl_cen": pnl_cen, "pnl_esperado": pnl_esp,
        "preco_esperado": preco_esp, "pnl_p5": pnl_p5, "pnl_p95": pnl_p95, "vpl": vpl,
        "ret_var": (pnl_esp / var_brl) if var_brl else float("nan"),
        "ret_es": (pnl_esp / es_brl) if es_brl else float("nan"),
        "manifesto": man, "resumo_dados": resumo, "premissas_tab": premissas_tab,
        "var_tab": var_tab, "checks": checks,
        "backtests": pd.concat([res_wf.assign(tabela="walk_forward_meia_vida"),
                                bt_pesos.assign(tabela="peso_fundamental")], ignore_index=True),
        "linha_mwm": 2 + [k for k, _ in pos_tab].index("mwm") if "mwm" in dict(pos_tab) else 2,
        "linha_var_preco": 2, "fonte_entrada": info_mve.get("status", "n/d"),
        "q_seco": PREMISSAS.quantil_seco, "q_umido": PREMISSAS.quantil_umido,
        "data_reavaliacao": str((pd.Timestamp(hoje) + pd.Timedelta(days=30)).date()),
        "fim_produto": str((pd.Timestamp(alvo.max()) + pd.offsets.MonthEnd(0)).date()),
        "tese": _tese(pos, cb, efeitos, preco_cen, info_mve, sub),
        "gatilhos": _gatilhos(cb, efeitos, v, reg),
        "invalidam": _invalidam(efeitos, info_fun, info_mve),
        "limitacoes": _limitacoes(info_fun, info_mve, diag_sz, status, motivo),
    }

    DIR_OUT.mkdir(parents=True, exist_ok=True)
    cb.to_csv(DIR_OUT / "curva_mensal_base_seco_umido.csv", index=False)
    flat.to_csv(DIR_PROC / "pld_flat_mensal.csv", index=False)
    reg.to_csv(DIR_PROC / "drivers_hidrologicos.csv", index=False)
    fatores.to_csv(DIR_OUT / "fatores_sazonais.csv", index=False)
    ctx["backtests"].to_csv(DIR_OUT / "backtests.csv", index=False)
    checks.to_csv(DIR_OUT / "relatorio_qualidade.csv", index=False)
    (DIR_OUT / "diagnostico_sazonalidade.json").write_text(
        json.dumps(diag_sz, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (DIR_OUT / "resumo_execucao.json").write_text(json.dumps({
        "premio_nivel_rs_mwh": diag_prem.get("nivel_rs_mwh"),
        "premio_formato": diag_prem.get("formato_termo"),
        "premio_modo": PREMISSAS.premio_modo,
        "modo_sinal": PREMISSAS.modo_sinal,
        "k_premio_por_dispersao": (float(cal_justo.k_premio.iloc[0])
                                   if cal_justo is not None else None),
        "book": book_res,
        "status": status, "motivo": motivo, "submercado": sub, "meia_vida_dias": hl,
        "peso_fundamental": w, "k_seco": efeitos["k_seco"], "k_umido": efeitos["k_umido"],
        "var_preco_rs_mwh": v["var_preco"], "var_preco_iid": v_iid["var_preco"],
        "meia_vida_reversao_dias": mv_rev,
        # A posicao unica (mwm/direcao/vpl/pnl_esperado) saiu daqui junto com as
        # abas POSICAO e PNL_VPL: dava um numero agregado para o book inteiro e
        # contradizia o book real, que tem lado e tamanho proprios por vertice.
        # Posicao, PnL, VPL e risco vem exclusivamente de "book".
        "var_unitario_referencia": {
            "obs": "insumo de risco por MWh, nao e posicao",
            "consumo_limite_referencia": consumo, "var_brl_referencia": var_brl},
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # ---------------------------------------------------- MODELO EXCEL (calculo na planilha)
    diario_df = diario.reset_index()
    diario_df.columns = ["data", "pld"]
    hid_m = reg[["mes_ref", "ena_pct", "ear_pct"]].copy()
    lim_ano = LIMITES_PLD.get(int(pd.Timestamp(alvo.max()).year), LIMITES_PLD[2026])
    info_xl = excel_modelo.construir(
        DIR_OUT / "MODELO_Curva_Forward.xlsx",
        {"pld_diario": diario_df, "hidro_mensal": hid_m, "mve": mve_f, "manifesto": man},
        PREMISSAS,
        {"data_corte": DATA_CORTE, "ref_mes": pd.Timestamp(ref).date(), "alvo": alvo,
         "piso": lim_ano["min"], "teto": lim_ano["max_estrutural"], "peso_fund": w,
         "nome_curva": NOME_CURVA, "status": status, "status_motivo": motivo,
         "submercado": sub, "meia_vida": hl, "forward": fwd, "nivel_col": nivel_col,
         "tem_ancora": bool(bol.get("ok")),
         "seco_estatistico": bool(bol.get("ok")
                                  and bol["diag_cen"].get("seco_por_estimador")),
         "peso_ancora": PREMISSAS.peso_ancora_infopld if bol.get("ok") else 0.0,
         "tem_premio": cal_prem is not None,
         "premio_basis": PREMISSAS.premio_basis_rs_mwh,
         "pos": pos, "var_fwd": v,
         "var_spot_challenger": v_spot["var_preco"],
         "crosscheck": [
             ("Fair value flat (R$/MWh)", pos["fair_value_flat"], "=FV_FLAT", 0.001, "determinístico"),
             ("k_seco (estimador residual)", ef_res["k_seco"], "=K_SECO", 0.001, "determinístico"),
             ("k_umido (estimador residual)", ef_res["k_umido"], "=K_UMIDO", 0.001, "determinístico"),
             ("Vol EWMA mensal do nivel", v["vol_nivel_mensal"], "=VOL_NIVEL", 0.01,
              "recursao EWMA replicada celula a celula"),
             ("Meia-vida do nivel (meses)", v["meia_vida_nivel_meses"],
              "=LN(2)/KAPPA_NIVEL", 0.01, "AR(1) do nivel dessazonalizado"),
             ("ES de preco (R$/MWh)", v["es_preco"], "=ES_PRECO", 0.01,
              "z do ES = phi(z)/(1-conf)"),
             ("VaR de preco (R$/MWh)", v["var_preco"], "=VAR_PRECO", 0.01,
              "delta-normal: deterministico dada a vol"),
             ("ES de preco (R$/MWh)", v["es_preco"], "=ES_PRECO", 0.01, "deterministico"),
             # Estas quatro linhas comparavam o Excel contra a posicao unica do
             # Python, que nao existe mais. Agora os dois lados leem o BOOK — que
             # e o unico ponto onde posicao, risco e resultado sao definidos.
             ("Equivalente flat (MWm, comparacao)", book_res["mwmed_equivalente_flat"],
              "=BOOK_MWM_FLAT", 0.02,
              "arredondamento para lote inteiro no dimensionamento por risco"),
             ("Energia do book (MWh)", book_res["energia_liquida_gwh"] * 1000,
              "=BOOK_ENERGIA_MWH", 0.02, "esta e a medida de tamanho, junto do ladder"),
             ("Notional do book (R$)", book_res["notional_brl"],
              "=BOOK_NOTIONAL", 0.02, "soma de MWm x horas x preco de entrada"),
             ("Soma de MWm das pernas (diagnostico)", book_res["soma_mwm_pernas"],
              "=BOOK_SOMA_MWM", 0.02,
              "nao e tamanho de posicao; entra so para fechar a conta com a planilha"),
             ("VaR de marcacao do book (R$)", book_res["var_total"], "=VAR_MTM_BOOK", 0.02,
              "herda a tolerancia do VaR de preco"),
             ("PnL carrego esperado (R$)", book_res["pnl_Entrega_Esperado"],
              "=BOOK_PNL_ESP", 0.02, "herda a tolerancia do tamanho"),
             ("PnL convergencia (R$)", book_res["pnl_Convergencia"],
              "=BOOK_PNL_CONV", 0.02, "herda a tolerancia do tamanho"),
             ("VPL do book (R$)", book_res["vpl"], "=BOOK_VPL", 0.02,
              "desconto mes a mes ate 31/12"),
         ]})
    log.info("modelo Excel: %s abas, %s linhas de PLD diario, horizonte de %s meses",
             len(info_xl["abas"]), info_xl["linhas_pld"], info_xl["horizonte"])
    if bol.get("ok"):
        from openpyxl import load_workbook
        wbx = load_workbook(DIR_OUT / "MODELO_Curva_Forward.xlsx")
        rx = XB.adicionar_abas(wbx, bol, alvo, sub)
        if cal_prem is not None:
            produtos = [BK.rotulo_mes(m) for m in alvo] + ["Q4/26"]
            rb = XBK.adicionar(wbx, alvo, ref_mkt, pernas, produtos,
                               PREMISSAS.premio_modo, PREMISSAS.limiar_sinal_rs,
                               modo_sinal=PREMISSAS.modo_sinal,
                               k_premio=float(cal_justo.k_premio.iloc[0]))
            info_pos = XBK.aba_posicao(wbx, alvo, dim_var, rb, PREMISSAS.limite_var_brl,
                                       PREMISSAS.var_orcamento_frac,
                                       PREMISSAS.mwm_maximo_operacional)
            # O case deu o VaR como unica restricao: o exercicio no limite cheio
            # e a resposta direta a essa restricao.
            XBK.aba_exercicio_var(wbx, alvo, info_pos)
            log.info("abas de book adicionadas: %s", ", ".join(rb["abas"]))
            org = XBK.organizar(wbx, rb["primeira_perna"], rb["ultima_perna"])
            log.info("abas reordenadas — primeiras: %s", ", ".join(org["ordem"]))
        wbx.save(DIR_OUT / "MODELO_Curva_Forward.xlsx")
        log.info("abas de boletins adicionadas: %s (%s observacoes auditadas)",
                 ", ".join(rx["abas"]), rx["n_obs_auditoria"])
    ctx["efeitos_residual"] = ef_res

    saidas.gerar_planilha(DIR_OUT / "entrega_2_curva.xlsx", ctx)
    saidas.gerar_graficos(DIR_OUT / "graficos", ctx)
    relatorio.gerar(DIR_OUT / "entrega_2.md", ctx)
    log.info("artefatos em %s", DIR_OUT)
    print(json.dumps(json.loads((DIR_OUT / "resumo_execucao.json").read_text()), indent=2, ensure_ascii=False))


# ------------------------------------------------------------------- textos
def _tese(pos, cb, ef, preco_cen, info_mve, sub):
    if pos["tipo"] == "DIRECIONAL":
        d = "comprada" if pos["direcao"] > 0 else "vendida"
        return [f"Posição {d} em {pos['mwm']:.0f} MWm de convencional flat {sub} para "
                f"{cb.mes_ref.min():%b/%y}–{cb.mes_ref.max():%b/%y}. O fair value público de "
                f"R$ {pos['fair_value_flat']:.2f}/MWh está {abs(pos['edge']):.2f} R$/MWh "
                f"{'acima' if pos['edge']>0 else 'abaixo'} da referência pública de transação, "
                f"edge maior que o mínimo de convicção adotado."]
    if pos["tipo"] == "SEM_POSICAO":
        return [f"Não há assimetria suficiente para posição direcional: o edge de "
                f"{abs(pos.get('edge',0)):.2f} R$/MWh não supera o mínimo de convicção. "
                f"Recomendação condicional: comprar até R$ {pos['comprar_ate']:.2f}/MWh ou "
                f"vender acima de R$ {pos['vender_acima_de']:.2f}/MWh."]
    return [f"Não existe, na data de corte, preço público de transação comparável em produto, "
            f"vigência e submercado ({info_mve.get('motivo','')}). Portanto a recomendação é "
            f"**condicional**, e não direcional: o fair value calculado sobre dados públicos é "
            f"R$ {pos['fair_value_flat']:.2f}/MWh para {sub} flat no horizonte. "
            f"Comprar até R$ {pos['comprar_ate']:.2f}/MWh; vender acima de "
            f"R$ {pos['vender_acima_de']:.2f}/MWh. Forçar direção sem preço observável seria "
            f"inventar o dado que falta."]


def _gatilhos(cb, ef, v, reg):
    ult = reg.dropna(subset=["ena_pct"]).iloc[-1]
    return [
        f"ENA %MLT do submercado abaixo de {reg.limiar_seco.iloc[-1]:.2f} de índice hidro por "
        f"duas semanas consecutivas — regime seco confirmado, reprecificar em +{(ef['k_seco']-1)*100:.1f}%.",
        f"ENA/EAR acima do limiar úmido ({reg.limiar_umido.iloc[-1]:.2f}) — reprecificar em "
        f"{(ef['k_umido']-1)*100:.1f}%.",
        f"Movimento adverso do preco a termo maior que o VaR de {v['var_preco']:.2f} R$/MWh "
        f"em {v['horizonte_meses']:.0f} mes — revisao obrigatoria do tamanho.",
        "Publicação de nova Função de Custo Futuro do NEWAVE/DECOMP que altere o CMO do horizonte "
        "em mais de 10% — recalcular a âncora fundamental.",
        f"Última leitura de ENA %MLT: {ult.ena_pct:.1f}% (referência de acompanhamento).",
    ]


def _invalidam(ef, info_fun, info_mve):
    inv = [
        "Ordenação Seco > Base > Úmido deixar de valer na reestimação — o mecanismo econômico da "
        "tese estaria quebrado.",
        "Surgir preço público de transação comparável que contradiga o fair value em mais que o "
        "erro médio do backtest.",
        "Mudança de metodologia de formação do PLD que invalide a janela de 24 meses.",
    ]
    if not ef["ordenacao_coerente"]:
        inv.insert(0, "ATENÇÃO: a ordenação de cenários JÁ está invertida nesta estimação — "
                      "investigar antes de operar.")
    if info_fun.get("status") != "ok":
        inv.append(f"Componente fundamental ausente nesta execução ({info_fun.get('motivo','')}).")
    return inv


def _limitacoes(info_fun, info_mve, diag, status, motivo):
    L = [
        "A curva é uma referência pública de fair value, NÃO uma curva de mercado observada. "
        "Não existe curva forward pública e líquida no Brasil equivalente à proprietária das mesas.",
        "Risco de base entre o PLD (preço de curto prazo com piso e teto administrativos) e o preço "
        "bilateral de um contrato a termo. O prêmio de risco a termo não é observável em fonte pública.",
        f"Janela de 24 meses: amostra curta por construção. Tamanho amostral efetivo médio por "
        f"mês-calendário = {diag['n_efetivo_medio']:.1f} observações.",
        f"{diag['spikes_winsorizados']} observação(ões) winsorizada(s) — listadas em "
        f"outputs/diagnostico_sazonalidade.json, nenhuma descartada.",
        "CMO não é preço negociável. Onde entra na curva, entra como âncora de custo, com peso "
        "definido por backtest.",
        "Risco de liquidez: a consolidação de contrapartes citada no case encarece a desmontagem; "
        "o horizonte do VaR já reflete isso.",
    ]
    if info_mve.get("status") != "ok":
        L.append(f"MVE: {info_mve.get('motivo', info_mve.get('status'))}.")
    if status != "DEFINITIVO":
        L.insert(0, motivo)
    return L


def cmd_calibrar(args):
    """Reseleciona janela, meia-vida e kernel da sazonalidade fora da amostra.

    POR QUE UM COMANDO SEPARADO
    ---------------------------
    Estes tres parametros definem a FORMA da curva. Selecionar forma pelo erro
    TOTAL nao funciona: o erro de nivel e varias vezes maior que o de forma e
    domina o criterio, entao o vencedor e sempre o ajuste mais liso — que e o
    que menos erra no nivel, nao o que melhor acerta a forma.

    Aqui o nivel e removido antes de medir: previsto e realizado sao centrados
    na propria media do horizonte, e o que sobra e so a forma relativa.
    """
    import itertools
    from . import sazonalidade as sz
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    flat = pd.read_csv(DIR_PROC / "pld_flat_mensal.csv")
    flat["mes_ref"] = pd.to_datetime(flat.mes_ref)
    d = flat.sort_values("mes_ref").reset_index(drop=True)
    H, n_or = args.horizonte, args.origens
    origens = list(d.mes_ref.iloc[-(n_or + H):-H])
    if len(origens) < 6:
        raise SystemExit(f"FALHA: so {len(origens)} origens disponiveis. "
                         "Historico curto demais para selecionar parametros.")

    def erro_forma(kd, hl, jan):
        errs = []
        for o in origens:
            hist = d[d.mes_ref <= o]
            alvo = d[(d.mes_ref > o) & (d.mes_ref <= o + pd.DateOffset(months=H))]
            if len(hist) < 18 or len(alvo) < H:
                continue
            try:
                tab, _ = sz.fatores_sazonais(hist, o, hl, jan, kd / 30.0)
                p = np.log(sz.prever(hist, tab, o, pd.DatetimeIndex(alvo.mes_ref)).preco.values)
            except Exception:
                continue
            a = np.log(alvo.flat.values)
            errs.append(np.abs((p - p.mean()) - (a - a.mean())))
        return float(np.mean(np.concatenate(errs))) if errs else float("nan")

    janelas = (24, 36, 48, 60)
    hls = PREMISSAS.meias_vidas_teste
    kernels = (5, 10, 15, 21, 30)
    linhas = []
    for jan, hl, kd in itertools.product(janelas, hls, kernels):
        e = erro_forma(kd, hl, jan)
        if np.isfinite(e):
            linhas.append({"janela_meses": jan, "meia_vida_dias": hl,
                           "kernel_dias": kd, "erro_forma": e})
    tab = pd.DataFrame(linhas).sort_values("erro_forma").reset_index(drop=True)
    if tab.empty:
        raise SystemExit("FALHA: nenhuma combinacao pode ser avaliada.")
    saida = DIR_OUT / "calibracao_sazonalidade.csv"
    tab.to_csv(saida, index=False)

    b = tab.iloc[0]
    at = tab[(tab.janela_meses == PREMISSAS.janela_sazonal_meses) &
             (tab.kernel_dias == PREMISSAS.kernel_calendario_dias)]
    log.info("SELECAO FORA DA AMOSTRA sobre a FORMA (nivel removido), "
             "horizonte %d meses, %d origens", H, len(origens))
    log.info("MELHOR: janela=%dm, meia-vida=%dd, kernel=%dd -> erro de forma %.2f%%",
             b.janela_meses, b.meia_vida_dias, b.kernel_dias, 100 * b.erro_forma)
    if len(at):
        a0 = at.sort_values("erro_forma").iloc[0]
        log.info("CONFIG ATUAL: janela=%dm, kernel=%dd -> erro de forma %.2f%% "
                 "(ganho possivel: %.1f%%)", a0.janela_meses, a0.kernel_dias,
                 100 * a0.erro_forma, 100 * (a0.erro_forma - b.erro_forma) / a0.erro_forma)
    print("\n--- 8 melhores combinacoes ---")
    print(tab.head(8).to_string(index=False))
    print(f"\nGrade completa em {saida}")
    print("Para aplicar, editar em src/config.py: janela_sazonal_meses, "
          "kernel_calendario_dias e meias_vidas_teste.")
    print("A meia-vida ja e escolhida automaticamente a cada run; janela e kernel nao.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="curva", description=NOME_CURVA)
    s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("sync", help="baixa e versiona as fontes publicas")
    a.add_argument("-v", "--verbose", action="store_true"); a.set_defaults(func=cmd_sync)
    b = s.add_parser("run", help="executa o pipeline completo")
    b.add_argument("--submercado", default=PREMISSAS.submercado)
    b.add_argument("--raw-dir", default=None)
    b.add_argument("--fixtures", action="store_true", help="usa fixtures (valida codigo, nao sustenta tese)")
    b.add_argument("--ignorar-falhas", action="store_true")
    b.add_argument("-v", "--verbose", action="store_true")
    b.set_defaults(func=cmd_run)
    bl = s.add_parser("boletins", help="ingere e valida InfoPLD/IPDO da pasta, sem recalcular")
    bl.add_argument("--pasta", default=None)
    bl.add_argument("-v", "--verbose", action="store_true")
    bl.set_defaults(func=cmd_boletins)
    cal = s.add_parser("calibrar", help="reseleciona janela/meia-vida/kernel da sazonalidade "
                                          "pelo erro de FORMA fora da amostra")
    cal.add_argument("--horizonte", type=int, default=5, help="meses a frente avaliados")
    cal.add_argument("--origens", type=int, default=24, help="quantas datas passadas")
    cal.add_argument("-v", "--verbose", action="store_true")
    cal.set_defaults(func=cmd_calibrar)
    x = s.add_parser("excel", help="reconstroi apenas o MODELO Excel a partir dos dados ja baixados")
    x.add_argument("--submercado", default=PREMISSAS.submercado)
    x.add_argument("--raw-dir", default=None)
    x.add_argument("--fixtures", action="store_true")
    x.add_argument("--ignorar-falhas", action="store_true")
    x.add_argument("-v", "--verbose", action="store_true")
    x.set_defaults(func=cmd_run)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
