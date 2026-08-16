# -*- coding: utf-8 -*-
"""Parser do IPDO (ONS) — visao OBSERVADA, estado diario do sistema.

O IPDO responde "o que aconteceu ontem". O InfoPLD responde "o que se espera
daqui pra frente". As duas nunca entram na mesma variavel.

No balanco de energia do IPDO, cada fonte traz DUAS colunas:
    PROGRAMADO   o que o ONS havia despachado
    VERIFICADO   o que de fato ocorreu
A diferenca entre elas e o insumo do nowcast: surpresa de carga, surpresa de
renovavel, surpresa de termica. Guardamos as duas separadas, com natureza
propria, e a surpresa e CALCULADA — nunca extraida como se fosse um dado.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .boletins import Natureza, Obs, _num

# Fontes do balanco do SIN, na ordem em que aparecem na pagina 1
FONTES_SIN = ["Hidro Nacional", "Itaipu Binacional", "Termo Nuclear",
              "Termo Convencional", "Eólica", "Solar"]
# Ordem das colunas da tabela de armazenamento (pagina 3)
ORDEM_EARM = ["SIN", "S", "SE", "N", "NE"]


def _paginas_texto(caminho) -> list[str]:
    import pdfplumber
    with pdfplumber.open(caminho) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def _nums(linha: str) -> list[float]:
    out = []
    for b in re.findall(r"-?\d{1,3}(?:\.\d{3})+|-?\d+,\d+|-?\d+", linha):
        v = _num(b)
        if v is not None:
            out.append(v)
    return out


# ------------------------------------------------------- 1. balanco do SIN
def balanco_sin(caminho, paginas=None, data_ref: str = "") -> tuple[list[Obs], dict]:
    """Producao por fonte e carga do SIN: programado x verificado."""
    pgs = paginas or _paginas_texto(caminho)
    doc = Path(caminho).name
    idx = next((i for i, t in enumerate(pgs)
                if re.search(r"Balan[çc]o de Energia", t, re.I)
                and re.search(r"SISTEMA INTERLIGADO NACIONAL", t, re.I)), None)
    if idx is None:
        return [], {"status": "pagina de balanco nao encontrada", "pagina": None}
    pag, txt = idx + 1, pgs[idx]
    obs, revisar = [], []

    for linha in txt.splitlines():
        l = linha.strip()
        for fonte in FONTES_SIN:
            if l.startswith(fonte):
                v = _nums(l)
                # padrao: programado, verificado, participacao(%)
                if len(v) >= 2:
                    import unicodedata
                    limpo = "".join(c for c in unicodedata.normalize("NFD", fonte.upper())
                                    if unicodedata.category(c) != "Mn")
                    nome = "GER_" + re.sub(r"[^A-Z]", "", limpo)[:14]
                    obs.append(Obs(nome, "SIN", data_ref, v[0], "MWmed",
                                   Natureza.PROGRAMADO, documento=doc, pagina=pag,
                                   regra_validacao="v >= 0"))
                    obs.append(Obs(nome, "SIN", data_ref, v[1], "MWmed",
                                   Natureza.REALIZADO, documento=doc, pagina=pag,
                                   regra_validacao="v >= 0"))
                else:
                    revisar.append(l[:70])
                break
        if l.startswith("Total SIN"):
            v = _nums(l)
            if len(v) >= 2:
                obs.append(Obs("GER_TOTAL", "SIN", data_ref, v[0], "MWmed",
                               Natureza.PROGRAMADO, documento=doc, pagina=pag))
                obs.append(Obs("GER_TOTAL", "SIN", data_ref, v[1], "MWmed",
                               Natureza.REALIZADO, documento=doc, pagina=pag))
        if l.startswith("Carga (*)") and "Total" not in l:
            v = _nums(l)
            if len(v) >= 2:
                obs.append(Obs("CARGA", "SIN", data_ref, v[0], "MWmed",
                               Natureza.PROGRAMADO, documento=doc, pagina=pag,
                               regra_validacao="10000 < v < 200000"))
                obs.append(Obs("CARGA", "SIN", data_ref, v[1], "MWmed",
                               Natureza.REALIZADO, documento=doc, pagina=pag,
                               regra_validacao="10000 < v < 200000"))
                break   # a primeira ocorrencia e a do SIN; as demais sao submercados
    return obs, {"pagina": pag, "n_obs": len(obs), "revisar": revisar,
                 "status": "ok" if obs else "nada extraido"}


# ------------------------------------------------- 2. energia armazenada
def armazenamento(caminho, paginas=None, data_ref: str = "") -> tuple[list[Obs], dict]:
    """Tabela 'Variacao de Energia Armazenada' (SIN, Sul, SE/CO, Norte, NE).

    ATENCAO a ordem das colunas: SIN, Sul, SE/CO, Norte, NE. Nao e a ordem
    usual SE/S/NE/N. Trocar a ordem aqui inverte SE/CO com Sul e passa
    despercebido, porque os dois numeros sao plausiveis.
    """
    pgs = paginas or _paginas_texto(caminho)
    doc = Path(caminho).name
    idx = next((i for i, t in enumerate(pgs)
                if re.search(r"Varia[çc][ãa]o de Energia Armazenada", t, re.I)), None)
    if idx is None:
        return [], {"status": "tabela de armazenamento nao encontrada", "pagina": None}
    pag, txt = idx + 1, pgs[idx]
    linhas = [l.strip() for l in txt.splitlines()]
    obs, revisar = [], []

    def _capturar(padrao_rotulo, variavel, unidade, natureza, valida, antes=True):
        for i, l in enumerate(linhas):
            if re.search(padrao_rotulo, l, re.I):
                # o rotulo pode vir DEPOIS da linha de numeros (layout do IPDO)
                cand = _nums(l)
                if len(cand) < 5 and antes and i > 0:
                    cand = _nums(linhas[i - 1])
                if len(cand) >= 5:
                    for s, v in zip(ORDEM_EARM, cand[:5]):
                        obs.append(Obs(variavel, s, data_ref, v, unidade, natureza,
                                       documento=doc, pagina=pag,
                                       regra_validacao=valida))
                    return True
                revisar.append(f"{variavel}: {l[:60]}")
                return False
        return False

    _capturar(r"Capacidade M[aá]xima", "EARM_CAPACIDADE", "MWmes",
              Natureza.REALIZADO, "v > 0")
    _capturar(r"Armazenamento ao final do dia \(MWm", "EARM_MWMES", "MWmes",
              Natureza.REALIZADO, "v >= 0")
    _capturar(r"Armazenamento ao final do dia \(%\)", "EARM_PCT", "%EARMmax",
              Natureza.REALIZADO, "0 <= v <= 100")
    _capturar(r"Varia[çc][ãa]o em rela[çc][ãa]o dia anterior", "EARM_VAR_DIA", "p.p.",
              Natureza.REALIZADO, "-20 < v < 20", antes=False)
    _capturar(r"Varia[çc][ãa]o acumulada\s*mensal", "EARM_VAR_MES", "p.p.",
              Natureza.REALIZADO, "-50 < v < 50", antes=False)

    return obs, {"pagina": pag, "n_obs": len(obs), "revisar": revisar,
                 "status": "ok" if obs else "nada extraido",
                 "ordem_colunas": ORDEM_EARM}


# --------------------------------------------------------- 3. ENA por bacia
def ena_submercados(caminho, paginas=None, data_ref: str = "") -> tuple[list[Obs], dict]:
    """ENA por submercado a partir dos paineis da pagina 2.

    O layout e de dois paineis lado a lado e o texto sai intercalado, o que
    torna a associacao valor-submercado fragil. Extraimos com CONFIANCA
    REDUZIDA (0,6) e marcamos para revisao. A fonte preferencial de ENA por
    submercado e a pagina de resumo do InfoPLD, que traz a mesma informacao em
    tabela limpa.
    """
    pgs = paginas or _paginas_texto(caminho)
    doc = Path(caminho).name
    idx = next((i for i, t in enumerate(pgs)
                if re.search(r"Energia Afluente\s*ENA", t, re.I)), None)
    if idx is None:
        return [], {"status": "painel de ENA nao localizado", "pagina": None,
                    "nota": "usar ENA do resumo do InfoPLD"}
    pag, txt = idx + 1, pgs[idx]
    valores = []
    for l in txt.splitlines():
        m = re.search(r"Energia Afluente\s*ENA\s*([\d\s.,]+)MWmed", l)
        if m:
            v = _num(re.sub(r"\s+", "", m.group(1)))
            if v:
                valores.append(v)
    obs = [Obs("ENA_MWMED", "?", data_ref, v, "MWmed", Natureza.REALIZADO,
               documento=doc, pagina=pag, metodo="pdfplumber/text (painel duplo)",
               confianca=0.6,
               regra_validacao="v > 0; submercado exige revisao manual")
           for v in valores]
    return obs, {"pagina": pag, "n_obs": len(obs), "confianca": 0.6,
                 "status": "extraido com baixa confianca",
                 "revisar": ["associacao valor-submercado no painel duplo"],
                 "nota": "preferir ENA_ACUM_MES do resumo do InfoPLD"}


# ------------------------------------------------------------ orquestracao
def extrair(caminho, data_ref: str = "") -> tuple[pd.DataFrame, dict]:
    pgs = _paginas_texto(caminho)
    if not data_ref:
        from .boletins import identificar
        data_ref = identificar(caminho).data_referencia
    todas, diag = [], {"data_referencia": data_ref}
    for nome, fn in (("balanco", balanco_sin), ("armazenamento", armazenamento),
                     ("ena", ena_submercados)):
        o, d = fn(caminho, pgs, data_ref)
        todas += o
        diag[nome] = d
    df = pd.DataFrame([o.dict() for o in todas])
    diag["total_obs"] = len(df)
    return df, diag


def surpresas(df: pd.DataFrame) -> pd.DataFrame:
    """Programado x verificado. A surpresa e CALCULADA, nunca extraida.

    Sinal positivo = veio MAIS do que o programado.
    """
    p = df[df.natureza == Natureza.PROGRAMADO][["variavel", "submercado", "valor"]]
    r = df[df.natureza == Natureza.REALIZADO][["variavel", "submercado", "valor"]]
    j = p.merge(r, on=["variavel", "submercado"], suffixes=("_prog", "_real"))
    j = j[j.valor_prog != 0].copy()
    j["surpresa_abs"] = j.valor_real - j.valor_prog
    j["surpresa_pct"] = j.surpresa_abs / j.valor_prog
    j["natureza"] = "CALCULADO"
    return j.sort_values("surpresa_pct", key=abs, ascending=False).reset_index(drop=True)
