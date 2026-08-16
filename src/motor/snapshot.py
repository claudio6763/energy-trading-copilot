"""Modelo do snapshot congelado do motor de curva.

O snapshot guarda exatamente os ingredientes que `avaliar()` precisa para
reproduzir premio -> sinal -> risco por vertice -> book em milissegundos, sem
tocar em `data/raw`. Tudo que entra aqui ja foi produzido pela parte CARA do
pipeline (ingestao, sazonalidade walk-forward, ancora, classificacao de
regime) — `avaliar()` nunca recalcula nada disto, so combina.

Dataclass simples, nao Pydantic: o nucleo deste projeto e stdlib-first (ADR-011
do copiloto) e `pydantic` nao esta entre as dependencias instaladas. Ver
DECISOES.md.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MotorSnapshot:
    """Ingredientes congelados de uma execucao do motor ate a ancora+cenarios.

    Series mensais (`s_fun`, `s_saz`, `ajuste_now`, `var_vert`, `es_vert`, cada
    trajetoria de `cenarios_oficiais`) sao dicts `{"YYYY-MM-01": valor}`,
    alinhados a `alvo`. `cenarios_oficiais` guarda as tres trajetorias OFICIAIS
    da CCEE (Seco/Esperado/Umido) tal como ficaram ao final do pipeline — ja
    com a eventual substituicao do cenario Seco pelo estimador estatistico
    aplicada na ORIGEM (`seco_por_estimador=True`), exatamente como o motor
    faz. Nunca recombine meses de trajetorias diferentes.
    """

    schema_version: int
    gerado_em: str
    as_of: str                    # data de corte, "2026-08-14"
    submercado: str
    status_motor: str             # DEFINITIVO | PROVISORIO | MISTO | FIXTURE_...
    alvo: list[str]               # meses do horizonte, "YYYY-MM-01"

    s_fun: dict[str, float]        # ancora fundamental (InfoPLD), R$/MWh
    s_saz: dict[str, float]        # estatistico EWMA sazonal, R$/MWh
    w: float                       # peso do fundamental na combinacao
    ajuste_now: dict[str, float]   # ajuste de nowcast (fracao, ex 0.0034)

    cenarios_oficiais: dict[str, dict[str, float]]   # {"Seco"|"Esperado"|"Umido": {mes: preco}}
    seco_por_estimador: bool
    k_seco: float
    k_umido: float

    var_vert: dict[str, float]     # VaR de preco por vertice, R$/MWh
    es_vert: dict[str, float]      # ES de preco por vertice, R$/MWh
    hl_dias: int                   # meia-vida escolhida por walk-forward

    manifesto: list[dict[str, Any]] = field(default_factory=list)
    notas: dict[str, Any] = field(default_factory=dict)

    def content_for_hash(self) -> dict[str, Any]:
        """Tudo, exceto o proprio hash e o timestamp de geracao (nao afetam o conteudo)."""
        d = self.to_dict()
        d.pop("snapshot_hash", None)
        d.pop("gerado_em", None)
        return d

    def compute_hash(self) -> str:
        canonico = json.dumps(self.content_for_hash(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonico.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "gerado_em": self.gerado_em,
            "as_of": self.as_of,
            "submercado": self.submercado,
            "status_motor": self.status_motor,
            "alvo": list(self.alvo),
            "s_fun": dict(self.s_fun),
            "s_saz": dict(self.s_saz),
            "w": self.w,
            "ajuste_now": dict(self.ajuste_now),
            "cenarios_oficiais": {k: dict(v) for k, v in self.cenarios_oficiais.items()},
            "seco_por_estimador": self.seco_por_estimador,
            "k_seco": self.k_seco,
            "k_umido": self.k_umido,
            "var_vert": dict(self.var_vert),
            "es_vert": dict(self.es_vert),
            "hl_dias": self.hl_dias,
            "manifesto": list(self.manifesto),
            "notas": dict(self.notas),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MotorSnapshot":
        campos = {k: v for k, v in d.items() if k != "snapshot_hash"}
        return cls(**campos)

    def save(self, path: Path) -> str:
        """Grava o JSON com `snapshot_hash` incluido. Devolve o hash."""
        h = self.compute_hash()
        payload = self.to_dict()
        payload["snapshot_hash"] = h
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return h

    @classmethod
    def load(cls, path: Path) -> "MotorSnapshot":
        payload = json.loads(path.read_text(encoding="utf-8"))
        snap = cls.from_dict(payload)
        gravado = payload.get("snapshot_hash")
        recalculado = snap.compute_hash()
        if gravado and gravado != recalculado:
            raise ValueError(
                f"Snapshot {path} corrompido ou editado a mao: hash gravado "
                f"{gravado[:12]}... nao bate com o conteudo ({recalculado[:12]}...)."
            )
        return snap


__all__ = ["MotorSnapshot"]
