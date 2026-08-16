"""Inspecao dos decks DECOMP/NEWAVE publicados pela CCEE.

Nao supoe nomes de arquivo: ABRE o ZIP, lista o conteudo, classifica por
heuristica e extrai o que der. Se o deck exigir binario ou licenca para gerar
saida, NAO simula execucao — reporta o que foi possivel ler e para.

Uso:
    python -m src.decks inspecionar data/raw/decks/*.zip
"""
from __future__ import annotations
import re, sys, zipfile
from pathlib import Path

import pandas as pd

PADROES = {
    "cmo": [r"^cmarg", r"cmo", r"custo.*marginal"],
    "ena": [r"^vazoes", r"^ena", r"afluen"],
    "armazenamento": [r"earm", r"^varm", r"armazen"],
    "termica": [r"^term", r"gt\b", r"geracao.*termica"],
    "intercambio": [r"^interc", r"^exch", r"intercambio"],
    "carga": [r"^carga", r"^sistema", r"demanda"],
    "deficit": [r"deficit", r"custo.*deficit"],
    "config": [r"^dger", r"^caso", r"^arquivos", r"^entdados", r"^dadger"],
    "saida": [r"^relato", r"^sumario", r"^pmo", r"\.rv\d", r"^inviab"],
}


def classificar(nome: str) -> str:
    b = Path(nome).name.lower()
    for cat, pads in PADROES.items():
        if any(re.search(p, b) for p in pads):
            return cat
    return "outro"


def inventario(zip_path: Path) -> pd.DataFrame:
    linhas = []
    with zipfile.ZipFile(zip_path) as z:
        for i in z.infolist():
            if i.is_dir():
                continue
            linhas.append({"deck": Path(zip_path).name, "arquivo": i.filename,
                           "categoria": classificar(i.filename), "bytes": i.file_size,
                           "modificado": "%04d-%02d-%02d" % i.date_time[:3]})
    df = pd.DataFrame(linhas)
    return df.sort_values(["categoria", "arquivo"]).reset_index(drop=True)


def extrair_relato_cmo(zip_path: Path, encoding="latin-1") -> pd.DataFrame:
    """Tenta extrair CMO por estagio/patamar do RELATO do DECOMP.

    O layout do RELATO muda entre versoes. A funcao devolve DataFrame vazio e
    registra o motivo quando nao reconhece o bloco — nunca chuta valor.
    """
    achados = []
    with zipfile.ZipFile(zip_path) as z:
        alvos = [n for n in z.namelist() if re.search(r"relato", Path(n).name, re.I)]
        for nome in alvos:
            texto = z.read(nome).decode(encoding, errors="replace")
            bloco = re.search(r"CUSTO MARGINAL DE OPERACAO.*?(?=\n\s*\n\s*\n)", texto,
                              re.S | re.I)
            if not bloco:
                achados.append({"arquivo": nome, "status": "bloco de CMO nao encontrado",
                                "linhas": 0})
                continue
            linhas = [l for l in bloco.group(0).splitlines()
                      if re.search(r"\d+\s+\d+[.,]\d+", l)]
            achados.append({"arquivo": nome, "status": "bloco localizado",
                            "linhas": len(linhas), "amostra": linhas[:3]})
    return pd.DataFrame(achados)


def inspecionar(caminhos: list[str]) -> pd.DataFrame:
    todos = []
    for c in caminhos:
        p = Path(c)
        if not p.exists():
            print(f"[aviso] nao existe: {p}")
            continue
        inv = inventario(p)
        todos.append(inv)
        print(f"\n=== {p.name} ===")
        print(inv.groupby("categoria").agg(arquivos=("arquivo", "size"),
                                           bytes=("bytes", "sum")).to_string())
        rel = extrair_relato_cmo(p)
        if len(rel):
            print("\nRELATO:")
            print(rel.to_string(index=False))
    return pd.concat(todos, ignore_index=True) if todos else pd.DataFrame()


if __name__ == "__main__":
    df = inspecionar(sys.argv[1:])
    if len(df):
        out = Path("outputs/inventario_decks.csv")
        out.parent.mkdir(exist_ok=True)
        df.to_csv(out, index=False)
        print(f"\ninventario -> {out}")
