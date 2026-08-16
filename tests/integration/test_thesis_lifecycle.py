"""Ciclo de vida da tese: versoes, transicoes, limite de VaR e bloqueio por claim."""

from __future__ import annotations

from decimal import Decimal

import pytest

from copilot.common.enums import (
    ClaimStatus,
    ClaimType,
    DebateVerdict,
    AgentName,
    ThesisStatus,
    TurnRole,
    Unit,
)
from copilot.common.errors import (
    ImmutableThesisError,
    InvalidStatusTransition,
    MissingEvidenceError,
    VarLimitExceeded,
)
from copilot.db.repositories import Repositories
from tests.conftest import AS_OF
from tests.fixtures.builders import make_evidence, make_full_thesis, make_thesis


# ----------------------------------------------------------------- transicoes
def test_transicao_invalida_e_recusada(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    with pytest.raises(InvalidStatusTransition, match="nao permitida"):
        repos.theses.set_status(thesis, ThesisStatus.ATIVA)


def test_estados_terminais_nao_reabrem(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    repos.theses.set_status(thesis, ThesisStatus.ENCERRADA)
    assert thesis.closed_at is not None
    with pytest.raises(InvalidStatusTransition):
        repos.theses.set_status(thesis, ThesisStatus.ATIVA)


def test_aprovacao_carimba_o_horario(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    repos.theses.set_status(thesis, ThesisStatus.EM_DEBATE)
    repos.theses.set_status(thesis, ThesisStatus.APROVADA)
    assert thesis.approved_at is not None


# ------------------------------------------------------------ limite de VaR
@pytest.mark.parametrize(
    ("var", "aprova"),
    [
        (Decimal("49900000.00"), True),
        (Decimal("50000000.00"), True),
        (Decimal("50100000.00"), False),
    ],
)
def test_fronteira_do_limite_de_var(session, demo_ctx: None, var: Decimal, aprova: bool) -> None:
    """AC-43 / P8: verificacao em codigo, testada exatamente na fronteira."""
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF, title=f"Tese {var}", var_consumed=var)
    repos.theses.set_status(thesis, ThesisStatus.EM_DEBATE)

    if aprova:
        repos.theses.set_status(thesis, ThesisStatus.APROVADA)
        assert thesis.status is ThesisStatus.APROVADA
        assert thesis.var_within_limit is True
    else:
        with pytest.raises(VarLimitExceeded, match="excede o limite"):
            repos.theses.set_status(thesis, ThesisStatus.APROVADA)
        assert thesis.status is ThesisStatus.EM_DEBATE
        assert thesis.var_within_limit is False


def test_var_nao_calculado_nao_bloqueia(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF, var_consumed=None)
    repos.theses.set_status(thesis, ThesisStatus.EM_DEBATE)
    repos.theses.set_status(thesis, ThesisStatus.APROVADA)
    assert thesis.status is ThesisStatus.APROVADA


# ------------------------------------------------- bloqueio pelo Claim Verifier
@pytest.mark.parametrize("status", [ClaimStatus.BLOCKED, ClaimStatus.CONTRADICTED])
def test_claim_sem_lastro_bloqueia_aprovacao(
    session, demo_ctx: None, status: ClaimStatus
) -> None:
    """RF-51: numero orfao trava a tese, nao so a mensagem."""
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    repos.theses.set_status(thesis, ThesisStatus.EM_DEBATE)
    repos.claims.record(
        claim_text="Numero afirmado sem lastro.",
        claim_type=ClaimType.NUMERICA,
        status=status,
        thesis_id=thesis.id,
        value_numeric=Decimal("123.45"),
        unit=Unit.BRL,
        reason="teste",
    )
    session.flush()

    assert len(repos.theses.blocking_claims(thesis.id)) == 1
    with pytest.raises(MissingEvidenceError, match="Aprovacao bloqueada"):
        repos.theses.set_status(thesis, ThesisStatus.APROVADA)


def test_claim_verificada_nao_bloqueia(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    evidence = make_evidence(repos, value=Decimal("123.45"), unit=Unit.BRL, as_of=AS_OF)
    repos.theses.set_status(thesis, ThesisStatus.EM_DEBATE)
    repos.claims.record(
        claim_text="Numero com lastro.",
        claim_type=ClaimType.NUMERICA,
        status=ClaimStatus.VERIFIED,
        thesis_id=thesis.id,
        value_numeric=Decimal("123.45"),
        unit=Unit.BRL,
        evidence_id=evidence.id,
    )
    session.flush()
    repos.theses.set_status(thesis, ThesisStatus.APROVADA)
    assert thesis.status is ThesisStatus.APROVADA


def test_claim_verificada_sem_evidencia_e_incoerente(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    with pytest.raises(MissingEvidenceError, match="exige"):
        repos.claims.record(
            claim_text="Numero verificado sem lastro.",
            claim_type=ClaimType.NUMERICA,
            status=ClaimStatus.VERIFIED,
        )


# ------------------------------------------------------------------- versoes
def test_tese_aprovada_e_imutavel(session, demo_ctx: None) -> None:
    """AC-05."""
    from copilot.common.enums import AssumptionKind

    repos = Repositories(session)
    thesis = make_full_thesis(repos, as_of=AS_OF)
    repos.theses.set_status(thesis, ThesisStatus.EM_DEBATE)
    repos.theses.set_status(thesis, ThesisStatus.APROVADA)
    evidence = make_evidence(repos, as_of=AS_OF)

    with pytest.raises(ImmutableThesisError, match="nova versao"):
        repos.theses.add_assumption(
            thesis,
            kind=AssumptionKind.PRECO,
            statement="Premissa tardia.",
            evidence_id=evidence.id,
        )


def test_nova_versao_copia_componentes_e_preserva_a_anterior(
    session, demo_ctx: None
) -> None:
    repos = Repositories(session)
    original = make_full_thesis(repos, as_of=AS_OF)
    repos.theses.set_status(original, ThesisStatus.EM_DEBATE)
    repos.theses.set_status(original, ThesisStatus.APROVADA)
    session.flush()
    original_id = original.id

    nova = repos.theses.new_version(original, change_reason="Redimensionamento apos debate.")
    session.flush()

    assert nova.version == 2
    assert nova.parent_id == original_id
    assert nova.status is ThesisStatus.RASCUNHO
    assert nova.change_reason == "Redimensionamento apos debate."

    completa = repos.theses.get_full(nova.id)
    assert completa is not None
    assert len(completa.assumptions) == 1
    assert len(completa.positions) == 1
    assert len(completa.trigger_rules) == 1
    assert len(completa.risk_items) == 1

    anterior = repos.theses.get_full(original_id)
    assert anterior is not None
    assert anterior.status is ThesisStatus.APROVADA  # intacta
    assert anterior.version == 1


def test_nova_versao_exige_motivo(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    with pytest.raises(ValueError, match="motivo"):
        repos.theses.new_version(thesis, change_reason="   ")


def test_linhagem_de_versoes(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    v1 = make_thesis(repos, as_of=AS_OF)
    v2 = repos.theses.new_version(v1, change_reason="ajuste 1")
    v3 = repos.theses.new_version(v2, change_reason="ajuste 2")
    session.flush()

    linhagem = repos.theses.lineage(v3.id)
    assert [t.version for t in linhagem] == [1, 2, 3]


# -------------------------------------------------------------------- debate
def test_debate_sem_contra_argumento_fica_inconclusivo(session, demo_ctx: None) -> None:
    """RF-27 / AC-15: concordar nao e resultado aceitavel."""
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    debate = repos.debates.open_session(thesis)
    repos.debates.add_turn(
        debate, agent=AgentName.TRADER, role=TurnRole.DEFESA, content="Defesa."
    )
    repos.debates.close_session(debate, verdict=DebateVerdict.APROVAVEL)
    assert debate.verdict is DebateVerdict.INCONCLUSIVA
    assert "INCONCLUSIVA" in (debate.bias_rationale or "")


def test_debate_com_contra_argumento_e_aprovavel(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    debate = repos.debates.open_session(thesis)
    repos.debates.add_turn(
        debate, agent=AgentName.RISCO, role=TurnRole.ATAQUE, content="Ataque."
    )
    repos.debates.close_session(
        debate,
        verdict=DebateVerdict.APROVAVEL,
        counter_argument="No cenario Seco a posicao vira perda relevante.",
        confirmation_bias_score=Decimal("0.750000"),
    )
    assert debate.verdict is DebateVerdict.APROVAVEL
    assert debate.confirmation_bias_score == Decimal("0.750000")
    assert debate.ended_at is not None


def test_sequencia_de_turnos_e_automatica(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    debate = repos.debates.open_session(thesis)
    for agent in (AgentName.TRADER, AgentName.RISCO, AgentName.REGULATORIO):
        repos.debates.add_turn(debate, agent=agent, role=TurnRole.CONSULTA, content="x")
    session.flush()
    turnos = repos.debate_turns.list(session_id=debate.id)
    assert sorted(t.seq for t in turnos) == [1, 2, 3]
    assert repos.debate_turns.count(session_id=debate.id) == 3
