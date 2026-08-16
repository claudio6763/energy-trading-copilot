"""Contratos Pydantic das proximas sprints.

Testados agora porque carregam invariantes de projeto — nao sao meros DTOs.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from copilot.common.enums import (
    AgentName,
    ClaimStatus,
    ClaimType,
    Confidence,
    DatasetKind,
    DebateVerdict,
    EvidenceSourceType,
    LicenseClass,
    Unit,
)
from copilot.contracts import (
    AgentRequest,
    DebateOutcome,
    EvidenceRef,
    ExtractedClaim,
    NumericFact,
    RagAnswer,
    SqlRequest,
    VerificationReport,
)
from copilot.contracts.verifier import VerifiedClaim
from copilot.contracts.watchdog import WatchdogReport

AS_OF = date(2026, 8, 14)
ULID = "01J000000000000000000000AA"


def test_numeric_fact_exige_evidence_id() -> None:
    """P5/P6: numero so trafega com lastro."""
    with pytest.raises(ValidationError):
        NumericFact(value=Decimal("1"), unit=Unit.BRL, as_of=AS_OF)  # type: ignore[call-arg]


def test_numeric_fact_rejeita_id_malformado() -> None:
    with pytest.raises(ValidationError):
        NumericFact(value=Decimal("1"), unit=Unit.BRL, evidence_id="curto", as_of=AS_OF)


def test_numeric_fact_renderiza_com_data_base() -> None:
    fato = NumericFact(
        value=Decimal("195.00"), unit=Unit.BRL_PER_MWH, evidence_id=ULID, as_of=AS_OF
    )
    assert "2026-08-14" in fato.render()


def test_evidence_ref_e_imutavel() -> None:
    ref = EvidenceRef(
        evidence_id=ULID,
        source_type=EvidenceSourceType.SQL_QUERY,
        excerpt="trecho",
        as_of=AS_OF,
        license_class=LicenseClass.PUBLIC_OPEN,
        confidence=Confidence.HIGH,
    )
    with pytest.raises(ValidationError):
        ref.excerpt = "outro"  # type: ignore[misc]


def test_relatorio_de_verificacao_bloqueia_com_numero_orfao() -> None:
    """AC-50: numero sem origem bloqueia, mesmo sem claim marcada."""
    relatorio = VerificationReport(orphan_numbers=["47%"])
    assert relatorio.blocked is True


def test_relatorio_de_verificacao_bloqueia_claim_contraditada() -> None:
    claim = ExtractedClaim(claim_text="x", claim_type=ClaimType.NUMERICA)
    relatorio = VerificationReport(
        claims=[VerifiedClaim(claim=claim, status=ClaimStatus.CONTRADICTED)]
    )
    assert relatorio.blocked is True


def test_relatorio_limpo_nao_bloqueia() -> None:
    claim = ExtractedClaim(
        claim_text="x", claim_type=ClaimType.NUMERICA, evidence_id=ULID, placeholder="{{v}}"
    )
    relatorio = VerificationReport(
        claims=[VerifiedClaim(claim=claim, status=ClaimStatus.VERIFIED)]
    )
    assert relatorio.blocked is False


def test_resposta_rag_sem_trecho_nao_e_fundamentada() -> None:
    """AC-54: sem recuperacao, nao ha resposta ancorada."""
    assert RagAnswer(answer="qualquer coisa").grounded is False


def test_sql_request_exige_template_ou_sql_cru_mas_nao_ambos() -> None:
    with pytest.raises(ValidationError):
        SqlRequest(as_of=AS_OF, dataset_kind=DatasetKind.DEMO)
    with pytest.raises(ValidationError):
        SqlRequest(
            as_of=AS_OF,
            dataset_kind=DatasetKind.DEMO,
            template="t",
            raw_sql="SELECT 1",
        )
    assert SqlRequest(as_of=AS_OF, dataset_kind=DatasetKind.DEMO, template="t").template == "t"


def test_debate_sem_contra_argumento_nao_aprova() -> None:
    """RF-27 / AC-15: concordancia nao libera aprovacao."""
    sem = DebateOutcome(verdict=DebateVerdict.APROVAVEL)
    assert sem.approvable is False

    com = DebateOutcome(
        verdict=DebateVerdict.APROVAVEL,
        counter_argument="No cenario Seco a posicao vira perda relevante.",
    )
    assert com.approvable is True


def test_debate_com_bloqueio_nao_aprova() -> None:
    outcome = DebateOutcome(
        verdict=DebateVerdict.APROVAVEL,
        counter_argument="existe",
        blocking_reasons=["VaR acima do limite"],
    )
    assert outcome.approvable is False


def test_contexto_do_agente_nao_carrega_fala_de_outro_agente() -> None:
    """AC-13: o isolamento do Agente de Risco e estrutural."""
    campos = set(AgentRequest.model_fields)
    assert not campos & {"history", "turns", "trader_argument", "debate_history"}
    assert "thesis_snapshot" in campos


def test_watchdog_report_expoe_lacuna_de_cobertura() -> None:
    """RF-36 / AC-23: fonte que falhou nunca vira silencio."""
    from copilot.common.enums import WatchdogStatus

    relatorio = WatchdogReport(
        run_id=ULID,
        as_of=AS_OF,
        status=WatchdogStatus.PARCIAL,
        sources_failed=["ONS indisponivel"],
    )
    assert relatorio.has_coverage_gap is True
