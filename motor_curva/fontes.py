"""Conectores CKAN (CCEE e ONS) com descoberta dinamica, cache e falha explicita.

Regra do case: nao usar links anuais codificados. Os recursos da CCEE ficam em
pda-download.ccee.org.br/<token>/content, com token opaco -> package_show e
obrigatorio. Os do ONS ficam em S3. Ambos sao descobertos aqui.
"""
from __future__ import annotations
import json, re, time
from pathlib import Path
from typing import Iterable

from .config import DIR_RAW, Fonte, FONTES
from . import manifesto


class FonteIndisponivel(RuntimeError):
    """Falha explicita: nunca substituir silenciosamente nem sintetizar."""


def _requests():
    try:
        import requests
        return requests
    except ImportError as e:                                    # pragma: no cover
        raise FonteIndisponivel("pacote 'requests' ausente: pip install -r requirements.txt") from e


def package_show(portal: str, dataset: str, timeout: int = 60) -> dict:
    req = _requests()
    url = f"{portal}/api/3/action/package_show"
    try:
        r = req.get(url, params={"id": dataset}, timeout=timeout,
                    headers={"User-Agent": "curva-publica/1.0"})
        r.raise_for_status()
        js = r.json()
    except Exception as e:
        raise FonteIndisponivel(f"CKAN {portal} dataset={dataset}: {e}") from e
    if not js.get("success"):
        raise FonteIndisponivel(f"CKAN {portal} dataset={dataset} respondeu success=false")
    return js["result"]


def recursos(pacote: dict, formatos: Iterable[str] = ("csv", "zip", "parquet", "xlsx")) -> list[dict]:
    fmts = {f.lower() for f in formatos}
    out = []
    for r in pacote.get("resources", []):
        if (r.get("format") or "").lower() in fmts:
            out.append({"id": r.get("id"), "nome": r.get("name") or r.get("id"),
                        "url": r.get("url"), "formato": (r.get("format") or "").lower(),
                        "ultima_mod": r.get("last_modified") or r.get("created")})
    return out


def _anos_do_nome(nome: str) -> set[int]:
    return {int(a) for a in re.findall(r"(?:19|20)\d{2}", nome or "")}


def baixar_recurso(rec: dict, destino_dir: Path, tentativas: int = 3) -> Path:
    req = _requests()
    destino_dir.mkdir(parents=True, exist_ok=True)
    nome = re.sub(r"[^\w.\-]+", "_", rec["nome"]).strip("_") or rec["id"]
    destino = destino_dir / f"{nome}.{rec['formato']}"
    if destino.exists() and destino.stat().st_size > 0:
        return destino                                          # cache
    ultimo = None
    for i in range(tentativas):
        try:
            with req.get(rec["url"], stream=True, timeout=600,
                         headers={"User-Agent": "curva-publica/1.0"}) as resp:
                resp.raise_for_status()
                tmp = destino.with_suffix(destino.suffix + ".part")
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_content(1 << 20):
                        fh.write(chunk)
                tmp.rename(destino)
            return destino
        except Exception as e:                                  # pragma: no cover
            ultimo = e
            time.sleep(2 * (i + 1))
    raise FonteIndisponivel(f"download falhou para {rec['nome']} ({rec['url']}): {ultimo}")


def sincronizar(fonte: Fonte, anos: set[int] | None = None, log=print) -> list[Path]:
    """Descobre, baixa e registra no manifesto. Levanta FonteIndisponivel se obrigatoria."""
    destino = DIR_RAW / fonte.chave
    try:
        pacote = package_show(fonte.portal, fonte.dataset)
    except FonteIndisponivel as e:
        if fonte.obrigatoria:
            raise
        log(f"  [opcional] {fonte.chave}: {e}")
        return []

    recs = recursos(pacote)
    if fonte.filtro_recurso:
        recs = [r for r in recs if fonte.filtro_recurso.lower() in r["nome"].lower()]
    if anos:
        recs = [r for r in recs if (not _anos_do_nome(r["nome"])) or (_anos_do_nome(r["nome"]) & anos)]
    if not recs:
        msg = f"{fonte.chave}: nenhum recurso encontrado apos filtro"
        if fonte.obrigatoria:
            raise FonteIndisponivel(msg)
        log(f"  [opcional] {msg}")
        return []

    caminhos = []
    for r in recs:
        log(f"  {fonte.chave} <- {r['nome']}")
        p = baixar_recurso(r, destino)
        manifesto.registrar(
            instituicao=fonte.instituicao, conjunto=f"{fonte.dataset}/{r['nome']}",
            url_origem=f"{fonte.portal}/dataset/{fonte.dataset}", url_recurso=r["url"],
            caminho=p, frequencia=fonte.frequencia,
            limitacoes=fonte.descricao)
        caminhos.append(p)
    return caminhos


def sincronizar_tudo(anos: set[int] | None = None, log=print) -> dict[str, list[Path]]:
    out = {}
    for f in FONTES:
        log(f"[{f.instituicao}] {f.chave} - {f.descricao}")
        out[f.chave] = sincronizar(f, anos=anos, log=log)
    return out
