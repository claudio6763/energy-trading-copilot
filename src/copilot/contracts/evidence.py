"""Referencia de evidencia — o tipo que atravessa todas as fronteiras.

Regra estrutural do projeto: um numero factual nunca trafega como `float` ou
`str` solto. Trafega como `NumericFact`, que **obriga** um `evidence_id`. E o
mecanismo de tipo que sustenta P5 e P6.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from copilot.common.enums import Confidence, EvidenceSourceType, LicenseClass, Unit


class EvidenceRef(BaseModel):
    """Ponteiro para uma linha de `evidence`, com o suficiente para exibir a fonte."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(min_length=26, max_length=26)
    source_type: EvidenceSourceType
    locator: str | None = None
    excerpt: str
    as_of: date
    license_class: LicenseClass
    confidence: Confidence = Confidence.MEDIUM


class NumericFact(BaseModel):
    """Um numero com lastro. Sem `evidence_id` o objeto nao pode ser construido."""

    model_config = ConfigDict(frozen=True)

    value: Decimal
    unit: Unit
    evidence_id: str = Field(min_length=26, max_length=26)
    as_of: date
    label: str | None = None

    def render(self) -> str:
        """Representacao para UI. Sempre acompanhada da data-base."""
        return f"{self.value} {self.unit.value} (as_of {self.as_of.isoformat()})"


__all__ = ["EvidenceRef", "NumericFact"]
