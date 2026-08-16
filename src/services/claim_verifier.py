"""Claim Verifier — portao fail-closed entre a saida do LLM e o registro/UI.

Nenhum numero factual pode ser criado pelo LLM. Todo valor quantitativo precisa
de valor, unidade, data-base, fonte e `evidence_id`. Quem nao tiver e bloqueado.

Cinco checagens, nesta ordem:

1. **Numero orfao** — varre o texto e acha numeral que nao veio de placeholder
   resolvido nem consta na lista de claims declarados.
2. **Lastro** — claim numerica/factual sem `evidence_id` e BLOQUEADA.
3. **Existencia** — `evidence_id` precisa existir no banco.
4. **Data-base** — evidencia posterior ao corte oficial e BLOQUEADA.
5. **Recomputacao** — o valor afirmado tem de bater com o da evidencia.

Acertar por acaso nao passa: numero correto sem `evidence_id` e bloqueado igual.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Sequence

from src.database import repositories as R

UNAVAILABLE_MSG = "Não disponível — evidência insuficiente."

#: Numeros que aparecem em texto e nao sao afirmacao de dado.
_IGNORABLE = re.compile(
    r"(?:^|(?<=[\s(]))(?:"
    r"\d{4}-\d{2}-\d{2}"          # datas ISO
    r"|\d{1,2}/\d{1,2}/\d{2,4}"   # datas brasileiras
    r"|A\+\d+|M\+\d+|Q\+\d+"      # tenores
    r"|20\d{2}"                   # anos
    r"|[1-9]\)"                   # enumeracoes "1)"
    r")"
)
_NUMBER = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:\.\d+)?")
_PLACEHOLDER = re.compile(r"\{\{([a-zA-Z0-9_.]+)\}\}")

VERIFIED, UNVERIFIED, CONTRADICTED, BLOCKED = "VERIFIED", "UNVERIFIED", "CONTRADICTED", "BLOCKED"


@dataclass(frozen=True)
class Claim:
    """Afirmacao declarada por um agente."""

    text: str
    kind: str  # NUMERICA | FACTUAL | OPINIAO
    value: Decimal | None = None
    unit: str | None = None
    evidence_id: str | None = None
    tolerance: Decimal = Decimal("0.01")


@dataclass
class ClaimVerdict:
    claim: Claim
    status: str
    reason: str = ""
    evidence_value: Decimal | None = None


@dataclass
class VerificationReport:
    verdicts: list[ClaimVerdict] = field(default_factory=list)
    orphan_numbers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.orphan_numbers) or any(
            v.status in (BLOCKED, CONTRADICTED) for v in self.verdicts
        )

    @property
    def verified_ids(self) -> list[str]:
        return [v.claim.evidence_id for v in self.verdicts
                if v.status == VERIFIED and v.claim.evidence_id]

    def summary(self) -> str:
        if not self.blocked:
            return f"{len(self.verdicts)} afirmacao(oes) verificada(s)."
        partes = []
        if self.orphan_numbers:
            partes.append(f"{len(self.orphan_numbers)} numero(s) sem origem: "
                          + ", ".join(self.orphan_numbers[:5]))
        ruins = [v for v in self.verdicts if v.status in (BLOCKED, CONTRADICTED)]
        if ruins:
            partes.append(f"{len(ruins)} afirmacao(oes) bloqueada(s)")
        return "BLOQUEADO — " + "; ".join(partes)


def _parse(texto: str) -> Decimal | None:
    limpo = texto.strip()
    if "," in limpo and "." in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif "," in limpo:
        limpo = limpo.replace(",", ".")
    try:
        return Decimal(limpo)
    except InvalidOperation:
        return None


def extract_numbers(texto: str) -> list[str]:
    """Numerais candidatos, ja removidos datas, tenores e anos."""
    mascarado = _IGNORABLE.sub(" ", texto or "")
    return [m.group(0) for m in _NUMBER.finditer(mascarado)]


def find_orphans(texto: str, claims: Sequence[Claim]) -> list[str]:
    """Numerais no texto que nao correspondem a nenhuma claim declarada."""
    declarados = set()
    for c in claims:
        if c.value is not None:
            declarados.add(c.value)
            declarados.add(c.value.normalize())
    orfaos = []
    for bruto in extract_numbers(texto):
        valor = _parse(bruto)
        if valor is None:
            continue
        if any(valor == d or valor.normalize() == d for d in declarados):
            continue
        orfaos.append(bruto)
    return orfaos


def verify(
    conn: sqlite3.Connection,
    claims: Iterable[Claim],
    *,
    cut_off: str,
    text: str | None = None,
    check_orphans: bool = True,
) -> VerificationReport:
    """Verifica as claims. Fail-closed: na duvida, bloqueia."""
    lista = list(claims)
    relatorio = VerificationReport()

    for claim in lista:
        if claim.kind == "OPINIAO":
            relatorio.verdicts.append(ClaimVerdict(claim, UNVERIFIED,
                "Opiniao: renderizada como leitura, nunca como dado."))
            continue

        if not claim.evidence_id:
            relatorio.verdicts.append(ClaimVerdict(claim, BLOCKED,
                "Afirmacao factual sem evidence_id. Numero correto por acaso tambem e bloqueado."))
            continue

        linha = R.get_evidence(conn, claim.evidence_id)
        if linha is None:
            relatorio.verdicts.append(ClaimVerdict(claim, BLOCKED,
                f"evidence_id {claim.evidence_id} nao existe no banco."))
            continue

        if linha["as_of"] > cut_off:
            relatorio.verdicts.append(ClaimVerdict(claim, BLOCKED,
                f"Evidencia com data-base {linha['as_of']}, posterior ao corte {cut_off}."))
            continue

        if not linha["source_name"]:
            relatorio.verdicts.append(ClaimVerdict(claim, BLOCKED,
                "Evidencia sem fonte declarada."))
            continue

        if claim.value is not None:
            registrado = R.to_decimal(linha["value_numeric"])
            if registrado is None:
                relatorio.verdicts.append(ClaimVerdict(claim, CONTRADICTED,
                    "Claim numerica apontando para evidencia sem valor numerico."))
                continue
            if abs(registrado - claim.value) > claim.tolerance:
                relatorio.verdicts.append(ClaimVerdict(claim, CONTRADICTED,
                    f"Valor afirmado {claim.value} diverge da evidencia {registrado} "
                    f"(tolerancia {claim.tolerance}).", registrado))
                continue
            if claim.unit and linha["unit"] and claim.unit != linha["unit"]:
                relatorio.verdicts.append(ClaimVerdict(claim, CONTRADICTED,
                    f"Unidade afirmada {claim.unit} diverge da evidencia {linha['unit']}.",
                    registrado))
                continue
            relatorio.verdicts.append(ClaimVerdict(claim, VERIFIED,
                f"Confere com {linha['source_name']} (data-base {linha['as_of']}).", registrado))
        else:
            relatorio.verdicts.append(ClaimVerdict(claim, VERIFIED,
                f"Lastro em {linha['source_name']} (data-base {linha['as_of']})."))

    if check_orphans and text:
        relatorio.orphan_numbers = find_orphans(text, lista)
        if relatorio.orphan_numbers:
            relatorio.notes.append(
                "Numero sem origem no texto do agente. Todo numero deve vir do banco, "
                "de arquivo, de documento ou de funcao Python."
            )
    return relatorio


def render_safe(texto: str, report: VerificationReport) -> str:
    """Substitui numeros bloqueados pela mensagem padrao, em vez de exibi-los."""
    if not report.orphan_numbers:
        return texto
    saida = texto
    for bruto in sorted(set(report.orphan_numbers), key=len, reverse=True):
        saida = saida.replace(bruto, UNAVAILABLE_MSG)
    return saida


def resolve_placeholders(template: str, values: dict[str, str]) -> str:
    """Renderiza `{{chave}}` a partir de valores com lastro.

    Marcador sem valor vira falha visivel — nunca texto plausivel.
    """
    faltando = [m.group(1) for m in _PLACEHOLDER.finditer(template) if m.group(1) not in values]
    if faltando:
        raise ValueError(
            f"Placeholder sem evidencia: {', '.join(sorted(set(faltando)))}. "
            "Renderizacao abortada (fail-closed)."
        )
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def persist_claims(conn: sqlite3.Connection, report: VerificationReport, *,
                   session_id: str | None = None, thesis_id: str | None = None) -> None:
    """Registra o veredito na auditoria — a prova de que o portao rodou."""
    R.audit(
        conn, action="CLAIM_VERIFY", entity="debate" if session_id else "tese",
        entity_id=session_id or thesis_id, agent="ClaimVerifier",
        output_data={
            "blocked": report.blocked, "summary": report.summary(),
            "verdicts": [{"text": v.claim.text[:120], "status": v.status, "reason": v.reason}
                         for v in report.verdicts],
            "orphans": report.orphan_numbers,
        },
        evidence_ids=report.verified_ids,
    )


__all__ = [
    "BLOCKED", "CONTRADICTED", "Claim", "ClaimVerdict", "UNAVAILABLE_MSG", "UNVERIFIED",
    "VERIFIED", "VerificationReport", "extract_numbers", "find_orphans", "persist_claims",
    "render_safe", "resolve_placeholders", "verify",
]
