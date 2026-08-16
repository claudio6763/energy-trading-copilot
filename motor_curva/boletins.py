# -*- coding: utf-8 -*-
"""Identificacao, versionamento e proveniencia de boletins (InfoPLD e IPDO).

REGRA CENTRAL: um numero extraido de PDF so entra no modelo acompanhado de
documento, pagina, natureza e confianca. Sem proveniencia, nao entra.

NATUREZA DO DADO — nunca misturar na mesma variavel:
    REALIZADO   ja aconteceu e foi medido (IPDO: carga verificada, EAR do dia)
    PROGRAMADO  o ONS programou, ainda nao verificou (IPDO: carga programada)
    PROJETADO   saida de modelo para o futuro (InfoPLD: projecao de PLD/ENA/EARM)
    PREMISSA    escolha do analista
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path

MESES_PT = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
            "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}
SUBS = {"SE/CO": "SE", "SE": "SE", "SUDESTE": "SE", "SUDESTE/CENTRO-OESTE": "SE",
        "S": "S", "SUL": "S", "NE": "NE", "NORDESTE": "NE",
        "N": "N", "NORTE": "N", "SIN": "SIN"}


class Natureza:
    REALIZADO = "REALIZADO"
    PROGRAMADO = "PROGRAMADO"
    PROJETADO = "PROJETADO"
    PREMISSA = "PREMISSA"
    MANUAL = "MANUAL_REVIEWED"


@dataclass
class Obs:
    """Uma observacao extraida, com proveniencia completa."""
    variavel: str
    submercado: str
    periodo: str                 # 'YYYY-MM-DD' ou 'YYYY-MM'
    valor: float
    unidade: str
    natureza: str
    cenario: str = ""            # RNA, SMAP 2023, ... quando aplicavel
    documento: str = ""
    pagina: int = 0
    metodo: str = "pdfplumber/text"
    confianca: float = 1.0
    regra_validacao: str = ""
    def dict(self):
        return asdict(self)


def sha256(p: Path, bloco: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(bloco), b""):
            h.update(c)
    return h.hexdigest()


def mes_ref(token: str, ano_base: int | None = None) -> str | None:
    """'set/26' -> '2026-09'.  Aceita 'ago/26', 'set/2026', 'set-26'."""
    m = re.match(r"([a-zç]{3})[/\-\s]?(\d{2,4})", token.strip().lower())
    if not m:
        return None
    mm = MESES_PT.get(m.group(1))
    if not mm:
        return None
    a = int(m.group(2))
    if a < 100:
        a += 2000
    return f"{a:04d}-{mm:02d}"


def _num(txt: str) -> float | None:
    """Converte numero em formato BR. Devolve None para '-' e vazio."""
    if txt is None:
        return None
    t = str(txt).strip().replace("R$", "").replace("/MWh", "").replace("%", "")
    t = t.replace("MWmês", "").replace("MWmes", "").replace("MWmed", "").strip()
    if t in ("", "-", "--", "---", "n/d", "nd"):
        return None
    t = t.replace(".", "").replace(",", ".") if re.search(r",\d", t) else t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


# ------------------------------------------------------------- identificacao
@dataclass
class Documento:
    caminho: str
    tipo: str                    # INFOPLD | IPDO | DESCONHECIDO
    data_documento: str          # data de publicacao/referencia do boletim
    data_referencia: str         # dado a que o boletim se refere
    paginas: int
    sha256: str
    bytes: int
    identificado_por: str
    preliminar: bool = False
    avisos: list = field(default_factory=list)
    def dict(self):
        return asdict(self)


def identificar(caminho: str | Path, texto_p1: str | None = None,
                texto_p2: str | None = None) -> Documento:
    """Identifica pelo CONTEUDO, nunca pelo nome do arquivo.

    O nome e usado apenas como desempate quando o conteudo e ambiguo.
    """
    p = Path(caminho)
    import pdfplumber
    with pdfplumber.open(p) as pdf:
        n = len(pdf.pages)
        t1 = texto_p1 if texto_p1 is not None else (pdf.pages[0].extract_text() or "")
        t2 = texto_p2 if texto_p2 is not None else (
            pdf.pages[1].extract_text() or "" if n > 1 else "")
    cabeca = (t1 + "\n" + t2)

    tipo, por, prelim, avisos = "DESCONHECIDO", "", False, []
    if re.search(r"IPDO|Informativo Preliminar Di[aá]rio|Balan[çc]o de Energia", cabeca, re.I) \
            and re.search(r"SISTEMA INTERLIGADO NACIONAL", cabeca, re.I):
        tipo, por = "IPDO", "conteudo: cabecalho de Balanco de Energia do SIN"
        prelim = True
    elif re.search(r"pre[çc]os,\s*modelos e estudos energ|comportamento do PLD|InfoPLD",
                   cabeca, re.I):
        tipo, por = "INFOPLD", "conteudo: gerencia de precos/modelos da CCEE"
    if tipo == "DESCONHECIDO":
        nome = p.name.lower()
        if "ipdo" in nome:
            tipo, por = "IPDO", "nome do arquivo (conteudo inconclusivo)"
            avisos.append("identificado pelo nome; revisar")
        elif "infopld" in nome:
            tipo, por = "INFOPLD", "nome do arquivo (conteudo inconclusivo)"
            avisos.append("identificado pelo nome; revisar")

    # --- data interna do documento
    # A busca e feita SOMENTE na primeira pagina. Bug real: concatenar a pagina 2
    # fazia o IPDO ser datado por "62.456 em 18/02/2025", que e a data de um
    # RECORDE HISTORICO de carga, nao a data do boletim.
    MESES_LONGOS = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
                    "agosto", "setembro", "outubro", "novembro", "dezembro"]

    def _sem_acento(x: str) -> str:
        import unicodedata
        return "".join(c for c in unicodedata.normalize("NFD", x)
                       if unicodedata.category(c) != "Mn")

    d = None
    t1_sa = _sem_acento(t1)
    # (1) data por extenso: "11 Agosto de 2026"
    m = re.search(r"(\d{1,2})\s+(" + "|".join(MESES_LONGOS) + r")\s+de\s+(\d{4})",
                  t1_sa, re.I)
    if m:
        d = date(int(m.group(3)), MESES_LONGOS.index(m.group(2).lower()) + 1,
                 int(m.group(1)))
    # (2) data numerica na primeira pagina
    if d is None:
        m = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", t1)
        if m:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    # (3) ultimo recurso: nome do arquivo
    if d is None:
        m = re.search(r"(\d{2})[-_](\d{2})[-_](\d{4})|(\d{8})", p.name)
        if m:
            if m.group(4):
                x = m.group(4)
                d = date(int(x[4:]), int(x[2:4]), int(x[:2]))
            else:
                d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            avisos.append("data obtida do nome do arquivo; conteudo nao trazia data legivel")

    if d is None:
        raise ValueError(f"nao consegui determinar a data de {p.name}. "
                         f"Arquivo marcado para revisao manual; nao sera ingerido.")

    # O IPDO publicado no dia D reporta a operacao do dia D (titulo traz a data do dado).
    # O InfoPLD publicado no dia D traz o PLD de D e projecoes a partir de D.
    return Documento(caminho=str(p), tipo=tipo, data_documento=d.isoformat(),
                     data_referencia=d.isoformat(), paginas=n, sha256=sha256(p),
                     bytes=p.stat().st_size, identificado_por=por, preliminar=prelim,
                     avisos=avisos)


# --------------------------------------------------------------- repositorio
class Repositorio:
    """Registro imutavel de boletins. Nunca sobrescreve edicao anterior."""

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.indice = self.raiz / "indice_boletins.json"

    def _ler(self) -> list[dict]:
        if self.indice.exists():
            return json.loads(self.indice.read_text(encoding="utf-8"))
        return []

    def registrar(self, doc: Documento) -> tuple[bool, str]:
        itens = self._ler()
        if any(i["sha256"] == doc.sha256 for i in itens):
            return False, "duplicado (hash ja registrado) — nada a fazer"
        itens.append({**doc.dict(), "registrado_em": datetime.now().isoformat(timespec="seconds")})
        self.indice.write_text(json.dumps(itens, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, "registrado"

    def listar(self, tipo: str | None = None, ate: date | None = None) -> list[dict]:
        itens = self._ler()
        if tipo:
            itens = [i for i in itens if i["tipo"] == tipo]
        if ate:
            itens = [i for i in itens if date.fromisoformat(i["data_referencia"]) <= ate]
        return sorted(itens, key=lambda i: i["data_referencia"])

    def mais_recente(self, tipo: str, ate: date | None = None) -> dict | None:
        """Edicao mais recente do tipo, respeitando a data de corte.

        E aqui que o Modo Case se protege: com `ate` = 14/08/2026, um boletim
        publicado depois simplesmente nao existe para o modelo.
        """
        l = self.listar(tipo, ate)
        return l[-1] if l else None
