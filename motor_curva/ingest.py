"""Leitura tolerante e padronizacao. Falha explicita quando o schema muda."""
from __future__ import annotations
import re, zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .config import MAPA_SUB, DATA_CORTE, LIMITES_PLD


class SchemaDesconhecido(RuntimeError):
    pass


# ------------------------------------------------------------------ leitura
def ler_csv_flex(caminho: Path) -> pd.DataFrame:
    caminho = Path(caminho)
    if caminho.suffix.lower() == ".zip":
        with zipfile.ZipFile(caminho) as z:
            nomes = [n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))]
            if not nomes:
                raise SchemaDesconhecido(f"{caminho.name}: zip sem csv")
            with z.open(nomes[0]) as fh:
                return _tenta_ler(fh, caminho.name)
    with open(caminho, "rb") as fh:
        return _tenta_ler(fh, caminho.name)


def _tenta_ler(buf, nome: str) -> pd.DataFrame:
    """Escolhe a combinacao sep/decimal/encoding que produz mais colunas.

    Aceita arquivo apenas com cabecalho (0 linhas) - e um estado valido, p.ex.
    quando nao houve negocio no MVE. Nao inventa dado para preencher.
    """
    import io
    bruto = buf.read()
    melhor, melhor_score = None, (-1, -1)
    for enc in ("utf-8-sig", "latin-1"):
        for sep in (";", ",", "\t"):
            for dec in (",", "."):
                try:
                    df = pd.read_csv(io.BytesIO(bruto), sep=sep, decimal=dec,
                                     encoding=enc, low_memory=False)
                except Exception:
                    continue
                if df.shape[1] < 2:
                    continue
                numericas = sum(pd.api.types.is_numeric_dtype(df[c]) for c in df.columns)
                score = (df.shape[1], numericas)
                if score > melhor_score:
                    melhor, melhor_score = df, score
                    df.attrs["arquivo"] = nome
                    df.attrs["sep"], df.attrs["decimal"], df.attrs["encoding"] = sep, dec, enc
    if melhor is None:
        raise SchemaDesconhecido(f"{nome}: nao consegui inferir separador/encoding")
    return melhor


def _col(df: pd.DataFrame, exatos: list[str], padroes: list[str], rotulo: str) -> str:
    baixo = {c.lower().strip(): c for c in df.columns}
    for e in exatos:
        if e in baixo:
            return baixo[e]
    for p in padroes:
        for lc, orig in baixo.items():
            if re.search(p, lc):
                return orig
    raise SchemaDesconhecido(
        f"nao localizei a coluna de '{rotulo}' em {df.attrs.get('arquivo','?')}. "
        f"Colunas disponiveis: {list(df.columns)}. "
        f"Ajuste as listas em src/ingest.py e rode de novo — nao ha substituicao silenciosa.")


def _sub(serie: pd.Series) -> pd.Series:
    s = serie.astype(str).str.strip().str.lower()
    s = s.str.replace(r"\s+", " ", regex=True)
    return s.map(MAPA_SUB)


def _dt(serie: pd.Series) -> pd.Series:
    """Converte para datetime decidindo dayfirst por EVIDENCIA, nao por chute.

    Bug real encontrado no desenvolvimento: com `format='mixed', dayfirst=False`,
    a string brasileira '01/02/2026 00:00' era lida como 1 de fevereiro em vez de
    2 de janeiro. Datas com dia <= 12 eram silenciosamente trocadas de mes e, ao
    colidirem no drop_duplicates, sumiam — derrubando a cobertura mensal para 87%
    sem nenhum erro. O check de cobertura pegou o sintoma; a causa estava aqui.

    Regra: olha os dois primeiros campos numericos. Se algum primeiro campo > 12,
    e dayfirst. Se algum segundo campo > 12, nao e. Em caso de ambiguidade total,
    tenta as duas e fica com a que produz menos NaT; empatando, assume dayfirst
    (fontes brasileiras) e registra a decisao em serie.attrs.
    """
    if pd.api.types.is_datetime64_any_dtype(serie):
        return serie

    amostra = serie.dropna().astype(str).head(5000)
    pri = amostra.str.extract(r"^\s*(\d{1,4})\D(\d{1,2})", expand=True)
    a = pd.to_numeric(pri[0], errors="coerce")
    b = pd.to_numeric(pri[1], errors="coerce")

    if (a > 31).any():                       # comeca com ano: ISO, sem ambiguidade
        dayfirst, motivo = False, "formato ISO (ano primeiro)"
    elif (a > 12).any():
        dayfirst, motivo = True, "primeiro campo > 12 -> dia primeiro"
    elif (b > 12).any():
        dayfirst, motivo = False, "segundo campo > 12 -> mes primeiro"
    else:
        d1 = pd.to_datetime(serie, errors="coerce", dayfirst=True)
        d0 = pd.to_datetime(serie, errors="coerce", dayfirst=False)
        dayfirst = d1.isna().sum() <= d0.isna().sum()
        motivo = "ambiguo; escolhido por menor numero de NaT (empate -> dayfirst)"

    d = pd.to_datetime(serie, errors="coerce", dayfirst=dayfirst)
    d.attrs["dayfirst"] = dayfirst
    d.attrs["motivo_dayfirst"] = motivo
    return d


# -------------------------------------------------------------- normalizacao
def normalizar_pld(arquivos: list[Path]) -> pd.DataFrame:
    """-> [ts, submercado, pld, granularidade]. Aceita horario (2021+) e semanal (2001-2020)."""
    partes = []
    for a in arquivos:
        df = ler_csv_flex(a)

        # ---- SCHEMA REAL DA CCEE: a data vem QUEBRADA em tres colunas.
        #   MES_REFERENCIA;SUBMERCADO;PERIODO_COMERCIALIZACAO;DIA;HORA;PLD_HORA
        #   202608;NORDESTE;337;15;0;140.11
        # Sem tratar isso, o localizador tolerante casava PERIODO_COMERCIALIZACAO
        # com o padrao "periodo" e usava 1..744 como se fosse data — o pandas lia
        # como nanossegundos desde 1970 e a serie inteira virava 01/01/1970.
        # O erro era visivel no log; o perigo e que um leitor tolerante demais
        # aceite silenciosamente a coluna errada.
        low = {str(c).strip().lower(): c for c in df.columns}
        if {"mes_referencia", "dia", "hora"} <= set(low):
            mes = pd.to_numeric(df[low["mes_referencia"]], errors="coerce")
            dia = pd.to_numeric(df[low["dia"]], errors="coerce")
            hora = pd.to_numeric(df[low["hora"]], errors="coerce")
            base = pd.to_datetime(mes.astype("Int64").astype(str),
                                  format="%Y%m", errors="coerce")
            ts = (base + pd.to_timedelta(dia.fillna(1) - 1, unit="D")
                       + pd.to_timedelta(hora.fillna(0), unit="h"))
            c_sub = _col(df, ["submercado", "cod_submercado", "id_subsistema",
                              "nom_submercado", "nom_subsistema"],
                         [r"submerc", r"subsist"], "submercado")
            c_pld = _col(df, ["pld_hora", "val_pld", "pld", "preco", "val_preco"],
                         [r"pld", r"pre[cç]o"], "PLD")
            p = pd.DataFrame({"ts": ts, "submercado": _sub(df[c_sub]),
                              "pld": pd.to_numeric(df[c_pld], errors="coerce")})
            p["origem"] = Path(a).name
            partes.append(p.dropna(subset=["ts", "submercado", "pld"]))
            continue

        c_ts = _col(df, ["din_instante", "data", "data_hora", "din_referencia", "dat_referencia",
                         "periodo_referencia", "din_periodocomercializacao"],
                    [r"^din", r"data", r"instante", r"periodo"], "data/hora")
        c_sub = _col(df, ["cod_submercado", "id_subsistema", "submercado", "nom_submercado",
                          "sigla_submercado", "nom_subsistema"],
                     [r"submerc", r"subsist"], "submercado")
        c_pld = _col(df, ["val_pld", "pld", "preco", "val_preco", "vlr_pld",
                          "val_precoenergiamercado", "val_cmo"],
                     [r"pld", r"pre[cç]o", r"valor"], "PLD")
        p = pd.DataFrame({"ts": _dt(df[c_ts]), "submercado": _sub(df[c_sub]),
                          "pld": pd.to_numeric(df[c_pld], errors="coerce")})
        p["origem"] = Path(a).name
        partes.append(p.dropna(subset=["ts", "submercado", "pld"]))
    if not partes:
        raise SchemaDesconhecido("nenhum arquivo de PLD lido")
    d = pd.concat(partes, ignore_index=True).sort_values("ts")
    d = d[d.ts.dt.date <= DATA_CORTE]                       # nunca dado apos o corte
    d = d.drop_duplicates(subset=["ts", "submercado"], keep="last")
    passo = d.groupby("submercado").ts.diff().dt.total_seconds().median()
    d["granularidade"] = "horaria" if (passo and passo <= 3700) else "semanal"
    return d.reset_index(drop=True)


def normalizar_ons_diario(arquivos: list[Path], conceito: str) -> pd.DataFrame:
    """conceito in {'ena','ear'} -> [data, submercado, valor, pct]."""
    exatos_val = {
        "ena": ["ena_bruta_regiao_mwmed", "ena_armazenavel_regiao_mwmed", "val_enaarmazenavel"],
        "ear": ["ear_verif_subsistema_mwmes", "ear_verif_subsistema", "val_earverificada"],
    }[conceito]
    exatos_pct = {
        "ena": ["ena_armazenavel_regiao_percentualmlt", "ena_bruta_regiao_percentualmlt"],
        "ear": ["ear_verif_subsistema_percentual", "val_earverificadapercentual"],
    }[conceito]
    pad_val = {"ena": [r"ena.*mwmed", r"ena.*valor"], "ear": [r"ear.*mwmes", r"ear.*verif"]}[conceito]
    pad_pct = {"ena": [r"ena.*percentual", r"percentualmlt"], "ear": [r"ear.*percentual"]}[conceito]

    partes = []
    for a in arquivos:
        df = ler_csv_flex(a)
        c_dt = _col(df, [f"{conceito}_data", "din_instante", "data"], [r"data", r"^din"], "data")
        c_sub = _col(df, ["id_subsistema", "nom_subsistema", "cod_subsistema"],
                     [r"subsist", r"submerc"], "subsistema")
        c_val = _col(df, exatos_val, pad_val, f"{conceito} valor")
        try:
            c_pct = _col(df, exatos_pct, pad_pct, f"{conceito} percentual")
            pct = pd.to_numeric(df[c_pct], errors="coerce")
        except SchemaDesconhecido:
            pct = np.nan
        partes.append(pd.DataFrame({
            "data": _dt(df[c_dt]).dt.date, "submercado": _sub(df[c_sub]),
            "valor": pd.to_numeric(df[c_val], errors="coerce"), "pct": pct,
        }).dropna(subset=["data", "submercado"]))
    d = pd.concat(partes, ignore_index=True)
    d = d[d.data <= DATA_CORTE].drop_duplicates(["data", "submercado"], keep="last")
    return d.sort_values("data").reset_index(drop=True)


def normalizar_mve(arquivos: list[Path]) -> pd.DataFrame:
    """MVE: proxy publica de transacao. Schema instavel -> devolve o que achar."""
    partes = []
    for a in arquivos:
        df = ler_csv_flex(a)
        cols = {c.lower(): c for c in df.columns}
        def ache(*pads):
            for p in pads:
                for lc, o in cols.items():
                    if re.search(p, lc):
                        return o
            return None
        c_pre = ache(r"pre[cç]o.*m[ée]dio", r"pre[cç]o.*negocia", r"pre[cç]o", r"val_preco")
        c_dt = ache(r"data.*negocia", r"^data", r"^din", r"vigencia.*inicio")
        c_vol = ache(r"montante", r"quantidade", r"volume", r"mwm")
        c_sub = ache(r"submerc", r"subsist")
        c_tipo = ache(r"tipo.*energia", r"fonte")
        c_vig_i = ache(r"vig[eê]ncia.*in[ií]cio", r"inicio.*suprimento", r"data.*inicio")
        c_vig_f = ache(r"vig[eê]ncia.*fim", r"fim.*suprimento", r"data.*fim")
        if not c_pre:
            continue
        partes.append(pd.DataFrame({
            "data_negociacao": _dt(df[c_dt]) if c_dt else pd.NaT,
            "preco": pd.to_numeric(df[c_pre], errors="coerce"),
            "montante": pd.to_numeric(df[c_vol], errors="coerce") if c_vol else np.nan,
            "submercado": _sub(df[c_sub]) if c_sub else None,
            "tipo_energia": df[c_tipo].astype(str) if c_tipo else None,
            "vigencia_ini": _dt(df[c_vig_i]) if c_vig_i else pd.NaT,
            "vigencia_fim": _dt(df[c_vig_f]) if c_vig_f else pd.NaT,
            "arquivo": Path(a).name,
        }))
    if not partes:
        return pd.DataFrame(columns=["data_negociacao", "preco", "montante", "submercado",
                                     "tipo_energia", "vigencia_ini", "vigencia_fim", "arquivo"])
    d = pd.concat(partes, ignore_index=True).dropna(subset=["preco"])
    return d[d.data_negociacao.dt.date <= DATA_CORTE] if d.data_negociacao.notna().any() else d


# ------------------------------------------------------------- agregacao flat
def flat_mensal(pld: pd.DataFrame, submercado: str) -> pd.DataFrame:
    """Preco flat mensal = media aritmetica sobre TODAS as horas do mes.

    Trata ano bissexto naturalmente (conta horas efetivas) e reporta cobertura,
    para que mes incompleto nao seja confundido com mes barato.
    """
    import calendar
    d = pld[(pld.submercado == submercado) & (pld.granularidade == "horaria")].copy()
    if d.empty:
        d = pld[pld.submercado == submercado].copy()
    d["ano"] = d.ts.dt.year
    d["mes"] = d.ts.dt.month
    g = d.groupby(["ano", "mes"]).agg(flat=("pld", "mean"), n_obs=("pld", "size"),
                                      minimo=("pld", "min"), maximo=("pld", "max"),
                                      desvio=("pld", "std")).reset_index()
    g["horas_calendario"] = [calendar.monthrange(int(a), int(m))[1] * 24 for a, m in zip(g.ano, g.mes)]
    g["cobertura"] = g.n_obs / g.horas_calendario
    g["mes_ref"] = pd.to_datetime(dict(year=g.ano, month=g.mes, day=1))
    piso = g.ano.map(lambda a: LIMITES_PLD.get(int(a), {}).get("min", np.nan))
    g["no_piso_pct"] = np.nan
    for i, r in g.iterrows():
        p = LIMITES_PLD.get(int(r.ano), {}).get("min")
        if p:
            sub = d[(d.ano == r.ano) & (d.mes == r.mes)]
            g.loc[i, "no_piso_pct"] = float((sub.pld <= p * 1.001).mean())
    return g.sort_values("mes_ref").reset_index(drop=True)


def flat_semanal(pld: pd.DataFrame, submercado: str) -> pd.DataFrame:
    d = pld[pld.submercado == submercado].copy()
    d = d.set_index("ts").sort_index()
    s = d.pld.resample("W-SAT").agg(["mean", "size"]).reset_index()
    s.columns = ["semana", "flat", "n_obs"]
    return s.dropna()
