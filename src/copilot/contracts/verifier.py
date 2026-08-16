"""Contratos do Claim Verifier (Sprint 4).

O portao obrigatorio entre qualquer saida de LLM e o registro ou a UI
(ARCHITECTURE secao 6). Nenhuma implementacao nesta sprint.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from copilot.common.enums import ClaimStatus, ClaimType, Unit


class ExtractedClaim(BaseModel):
    """Afirmacao extraida de uma saida de agente, antes da verificacao."""

    model_config = ConfigDict(frozen=True)

    claim_text: str
    claim_type: ClaimType
    value_numeric: Decimal | None = None
    unit: Unit | None = None
    evidence_id: str | None = None
    #: Marcador de origem: `{{placeholder}}` resolvido, ou None se numero orfao.
    placeholder: str | None = None


class VerifiedClaim(BaseModel):
    """Afirmacao apos o veredito."""

    model_config = ConfigDict(frozen=True)

    claim: ExtractedClaim
    status: ClaimStatus
    reason: str | None = None
    tolerance_applied: Decimal | None = None
    evidence_value: Decimal | None = None


class VerificationReport(BaseModel):
    """Resultado da passagem pelo portao.

    `blocked` True impede persistencia e aprovacao (RF-51 / AC-16).
    """

    model_config = ConfigDict(frozen=True)

    claims: list[VerifiedClaim] = Field(default_factory=list)
    orphan_numbers: list[str] = Field(default_factory=list)
    rendered_text: str | None = None

    @property
    def blocked(self) -> bool:
        return bool(self.orphan_numbers) or any(
            claim.status in {ClaimStatus.BLOCKED, ClaimStatus.CONTRADICTED}
            for claim in self.claims
        )


__all__ = ["ExtractedClaim", "VerificationReport", "VerifiedClaim"]
