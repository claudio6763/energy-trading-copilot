# -*- coding: utf-8 -*-
"""Parser do InfoPLD Diario (CCEE) — visao PROSPECTIVA.

Extrai duas familias de informacao, com precisoes diferentes:

  1. PAGINA "resumo"  — PLD diario, projecao dos 3 meses proximos, ENA, EARM,
     GSF/MRE e ESS. Precisao de DUAS CASAS (ex.: R$ 127,05/MWh).
  2. TABELAS "resumo da projecao de ..." — as 5 trajetorias oficiais por
     submercado e mes, horizonte longo. Precisao INTEIRA (ex.: 127).

Onde as duas se sobrepoem, vale a do resumo, que tem mais precisao. A regra
esta implementada em `projecao_pld_consolidada` e e declarada no resultado.

NUNCA montar trajetoria "Frankenstein": cada uma das cinco (RNA, SMAP 2023,
SMAP 2018, SMAP CFS VE, SMAP CFS LI) e um cenario coerente e e preservada
inteira. Combinar o maior preco de cada mes entre modelos diferentes produziria
uma trajetoria que nenhum modelo gerou.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from .boletins import Natureza, Obs, SUBS, _num, mes_ref

TRAJETORIAS = ["RNA", "SMAP 2023", "SMAP 2018", "SMAP CFS VE", "SMAP CFS LI"]

TITULOS = {
    "PLD": r"resumo da proje[çc][ãa]o do PLD",
    "ENA": r"resumo da proje[çc][ãa]o de energia natural afluente",
    "EARM": r"resumo da proje[çc][ãa]o de energia armazenada",
}
UNIDADES = {"PLD": "R$/MWh", "ENA": "%MLT", "EARM": "%EARMmax"}


def _abrir(caminho):
    import pdfplumber
    return pdfplumber.open(caminho)


def _paginas_texto(caminho) -> list[str]:
    with _abrir(caminho) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


# ------------------------------------------------------------------- resumo
def _linha_valores(linha: str, n_esperado: int) -> list[float | None]:
    brutos = re.findall(r"-?[\d.]+,\d+|-?\d+(?:\.\d{3})*(?![\d,])|-", linha)
    vals = [_num(b) for b in brutos]
    return vals[-n_esperado:] if len(vals) >= n_esperado else vals


def resumo(caminho, paginas: list[str] | None = None) -> tuple[list[Obs], dict]:
    """Le a pagina 'resumo'. Devolve (observacoes, diagnostico)."""
    pgs = paginas or _paginas_texto(caminho)
    doc = Path(caminho).name
    idx = next((i for i, t in enumerate(pgs)
                if t.strip().lower().startswith("resumo")
                and re.search(r"Proje[çc][ãa]o\s+\w{3}/\d{2}", t)), None)
    if idx is None:
        return [], {"status": "pagina de resumo nao encontrada", "pagina": None}
    pag, txt = idx + 1, pgs[idx]
    obs: list[Obs] = []
    diag = {"pagina": pag, "linhas_ignoradas": []}

    ordem4 = ["SE", "S", "NE", "N"]              # blocos de PLD
    ordem5 = ["SE", "S", "NE", "N", "SIN"]       # blocos de ENA e Armazenamento
    bloco = None
    for linha in txt.splitlines():
        l = linha.strip()
        if re.match(r"^PLD\s+SE/CO", l):
            bloco = "PLD"; continue
        if re.match(r"^ENA\s+SE/CO", l):
            bloco = "ENA"; continue
        if re.match(r"^Armazenamento\s+SE/CO", l):
            bloco = "EARM"; continue
        if re.match(r"^Fator de ajuste do MRE", l):
            bloco = "MRE"; continue
        if re.match(r"^Encargos ESS", l):
            bloco = "ESS"; continue

        # --- PLD diario e projecoes mensais
        if bloco == "PLD":
            m = re.match(r"^(\d{2})/(\w{3})/(\d{2})\s", l)
            if m:
                d = f"20{m.group(3)}-{mes_ref(m.group(2)+'/'+m.group(3))[-2:]}-{m.group(1)}"
                for s, v in zip(ordem4, _linha_valores(l, 4)):
                    if v is not None:
                        obs.append(Obs("PLD_DIARIO", s, d, v, "R$/MWh", Natureza.REALIZADO,
                                       documento=doc, pagina=pag,
                                       regra_validacao="0 < v < 2000"))
                continue
            m = re.match(r"^Proje[çc][ãa]o\s+(\w{3}/\d{2})", l)
            if m:
                mr = mes_ref(m.group(1))
                for s, v in zip(ordem4, _linha_valores(l, 4)):
                    if v is not None:
                        obs.append(Obs("PLD_PROJ_MES", s, mr, v, "R$/MWh", Natureza.PROJETADO,
                                       cenario="resumo (alta precisao)", documento=doc,
                                       pagina=pag, regra_validacao="0 < v < 2000"))
                continue

        # --- ENA
        if bloco == "ENA":
            m = re.match(r"^Acumulado at[eé]\s+(\d{2})/(\w{3})/(\d{2})", l)
            if m:
                mr = mes_ref(m.group(2) + "/" + m.group(3))
                for s, v in zip(ordem5, _linha_valores(l, 5)):
                    if v is not None:
                        obs.append(Obs("ENA_ACUM_MES", s, mr, v, "%MLT", Natureza.REALIZADO,
                                       documento=doc, pagina=pag,
                                       regra_validacao="0 < v < 500"))
                continue
            m = re.match(r"^Expectativa\s+(\w{3}/\d{2})", l)
            if m:
                mr = mes_ref(m.group(1))
                for s, v in zip(ordem5, _linha_valores(l, 5)):
                    if v is not None:
                        obs.append(Obs("ENA_EXPECT_MES", s, mr, v, "%MLT", Natureza.PROJETADO,
                                       documento=doc, pagina=pag,
                                       regra_validacao="0 < v < 500"))
                continue

        # --- Armazenamento
        if bloco == "EARM":
            m = re.match(r"^Em\s+(\d{2})/(\w{3})/(\d{2})", l)
            if m:
                mr = mes_ref(m.group(2) + "/" + m.group(3))
                d = f"{mr}-{m.group(1)}"
                for s, v in zip(ordem5, _linha_valores(l, 5)):
                    if v is not None:
                        obs.append(Obs("EARM_DIA", s, d, v, "%EARMmax", Natureza.REALIZADO,
                                       documento=doc, pagina=pag,
                                       regra_validacao="0 <= v <= 100"))
                continue
            m = re.match(r"^Expectativa final de\s+(\w{3}/\d{2})", l)
            if m:
                mr = mes_ref(m.group(1))
                for s, v in zip(ordem5, _linha_valores(l, 5)):
                    if v is not None:
                        obs.append(Obs("EARM_FIM_MES", s, mr, v, "%EARMmax", Natureza.PROJETADO,
                                       documento=doc, pagina=pag,
                                       regra_validacao="0 <= v <= 100"))
                continue

        # --- MRE / GSF
        if bloco == "MRE":
            m = re.match(r"^(Acumulado at[eé]|Expectativa|Proje[çc][ãa]o)\s+(\S+)", l)
            if m:
                vals = _linha_valores(l, 2)
                per = mes_ref(m.group(2)) or m.group(2).strip()
                nat = Natureza.REALIZADO if "Acumulado" in m.group(1) else Natureza.PROJETADO
                for nome, v in zip(["GSF_MRE", "GSF_REPACTUADO"], vals):
                    if v is not None:
                        obs.append(Obs(nome, "SIN", per, v, "%", nat, documento=doc,
                                       pagina=pag, regra_validacao="0 < v <= 200"))
                continue

        # --- ESS e custo de descolamento
        if bloco == "ESS":
            m = re.match(r"^(Expectativa|Proje[çc][ãa]o)\s+(\S+)", l)
            if m:
                vals = _linha_valores(l, 2)
                per = mes_ref(m.group(2)) or m.group(2).strip()
                for nome, v in zip(["ESS", "CUSTO_DESCOLAMENTO_CMO_PLD"], vals):
                    if v is not None:
                        obs.append(Obs(nome, "SIN", per, v, "R$ MM", Natureza.PROJETADO,
                                       documento=doc, pagina=pag,
                                       regra_validacao="v >= 0"))
                continue

    diag["n_obs"] = len(obs)
    diag["status"] = "ok" if obs else "resumo encontrado, nada extraido"
    return obs, diag


# --------------------------------------------------- tabelas de trajetorias
def tabela_trajetorias(caminho, tipo: str, paginas: list[str] | None = None
                       ) -> tuple[list[Obs], dict]:
    """Extrai a tabela das 5 trajetorias oficiais para PLD, ENA ou EARM.

    Layout do PDF (validado contra as edicoes de 08/2026):
        <SUBMERCADO> ago/26 set/26 out/26 ...
        proj. PLD, RNA          91 92 80 ...
        proj. PLD, SMAP 2023    91 97 106 ...
        ...
    O rotulo da linha diz "proj. PLD" mesmo nas tabelas de ENA e EARM — e uma
    reutilizacao de rotulo do proprio boletim. O tipo vem do TITULO da pagina,
    nunca do rotulo da linha.
    """
    if tipo not in TITULOS:
        raise ValueError(f"tipo deve ser um de {list(TITULOS)}")
    pgs = paginas or _paginas_texto(caminho)
    doc = Path(caminho).name
    idx = next((i for i, t in enumerate(pgs) if re.search(TITULOS[tipo], t, re.I)), None)
    if idx is None:
        return [], {"status": f"tabela de {tipo} nao encontrada", "pagina": None}
    pag, txt = idx + 1, pgs[idx]

    obs: list[Obs] = []
    revisar: list[str] = []
    sub_atual, meses = None, []
    for linha in txt.splitlines():
        l = linha.strip()
        if not l:
            continue
        m = re.match(r"^(SE/CO|SIN|NE|S|N)\s+((?:\w{3}/\d{2}\s*)+)$", l)
        if m:
            sub_atual = SUBS[m.group(1)]
            meses = [mes_ref(x) for x in m.group(2).split()]
            continue
        # Alternativas EXPLICITAS e da mais longa para a mais curta. Um padrao
        # generico como SMAP[^\d]* parava antes do ano e devolvia "SMAP",
        # descartando silenciosamente as trajetorias SMAP 2023 e SMAP 2018.
        m = re.match(r"^proj\.\s*PLD,\s*(SMAP CFS VE|SMAP CFS LI|SMAP 2023|SMAP 2018|RNA)"
                     r"\s+(.*)$", l)
        if not m:
            if l.lower().startswith("proj. pld"):
                revisar.append(l[:80])
            continue
        traj, resto = m.group(1), m.group(2)
        traj = re.sub(r"\s+", " ", traj).strip()
        if traj not in TRAJETORIAS:
            revisar.append(l[:80]); continue
        if not sub_atual or not meses:
            revisar.append(f"linha sem cabecalho de submercado: {l[:60]}"); continue

        brutos = resto.split()
        if len(brutos) != len(meses):
            # tolera colunas vazias no fim do horizonte da trajetoria
            if len(brutos) < len(meses):
                brutos = brutos + ["-"] * (len(meses) - len(brutos))
            else:
                revisar.append(f"{sub_atual}/{traj}: {len(brutos)} valores para "
                               f"{len(meses)} meses"); continue
        for mr, b in zip(meses, brutos):
            v = _num(b)
            if v is None:
                continue     # '-' = fora do horizonte publicado daquela trajetoria
            obs.append(Obs(f"{tipo}_PROJ_TRAJ", sub_atual, mr, v, UNIDADES[tipo],
                           Natureza.PROJETADO, cenario=traj, documento=doc, pagina=pag,
                           metodo="pdfplumber/text+regex",
                           confianca=0.98,
                           regra_validacao={"PLD": "0 < v < 2000",
                                            "ENA": "0 < v < 1000",
                                            "EARM": "0 <= v <= 100"}[tipo]))
    diag = {"pagina": pag, "n_obs": len(obs), "revisar": revisar,
            "status": "ok" if obs else "nada extraido",
            "trajetorias": sorted({o.cenario for o in obs}),
            "submercados": sorted({o.submercado for o in obs})}
    return obs, diag


# ------------------------------------------------------------- orquestracao
def extrair(caminho) -> tuple[pd.DataFrame, dict]:
    """Extrai tudo do InfoPLD. Devolve (DataFrame de observacoes, diagnostico)."""
    pgs = _paginas_texto(caminho)
    todas, diag = [], {}
    o, d = resumo(caminho, pgs); todas += o; diag["resumo"] = d
    for tipo in ("PLD", "ENA", "EARM"):
        o, d = tabela_trajetorias(caminho, tipo, pgs)
        todas += o
        diag[f"traj_{tipo}"] = d
    df = pd.DataFrame([o.dict() for o in todas])
    diag["total_obs"] = len(df)
    return df, diag


def projecao_pld_consolidada(df: pd.DataFrame, submercado: str = "SE") -> pd.DataFrame:
    """Projecao mensal de PLD por trajetoria, com a precisao do resumo onde existe.

    O resumo traz ago, set e out com duas casas. A tabela de trajetorias traz de
    set em diante, inteiro. Para a trajetoria RNA — que a CCEE usa como
    referencia — os meses cobertos pelo resumo assumem o valor de alta precisao.
    Os demais meses e as demais trajetorias ficam com o inteiro da tabela.
    """
    t = df[(df.variavel == "PLD_PROJ_TRAJ") & (df.submercado == submercado)].copy()
    r = df[(df.variavel == "PLD_PROJ_MES") & (df.submercado == submercado)].copy()
    t["precisao"] = "inteiro (tabela de trajetorias)"
    if not r.empty:
        mapa = dict(zip(r.periodo, r.valor))
        alvo = t.cenario == "RNA"
        for i in t[alvo].index:
            per = t.at[i, "periodo"]
            if per in mapa:
                t.at[i, "valor"] = mapa[per]
                t.at[i, "precisao"] = "2 casas (pagina de resumo)"
        # meses do resumo que a tabela nao cobre (tipicamente o mes corrente)
        faltando = set(mapa) - set(t[alvo].periodo)
        for per in sorted(faltando):
            t = pd.concat([t, pd.DataFrame([{
                "variavel": "PLD_PROJ_TRAJ", "submercado": submercado, "periodo": per,
                "valor": mapa[per], "unidade": "R$/MWh", "natureza": Natureza.PROJETADO,
                "cenario": "RNA", "documento": r.documento.iloc[0],
                "pagina": int(r.pagina.iloc[0]), "metodo": "pdfplumber/text",
                "confianca": 1.0, "regra_validacao": "0 < v < 2000",
                "precisao": "2 casas (pagina de resumo)"}])], ignore_index=True)
    return t.sort_values(["cenario", "periodo"]).reset_index(drop=True)
