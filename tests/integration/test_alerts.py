"""Alertas: lastro obrigatorio, deduplicacao e decisao registrada."""

from __future__ import annotations

from decimal import Decimal

import pytest

from copilot.common.enums import AlertDecision, AlertKind, Severity, Unit
from copilot.common.errors import MissingEvidenceError
from copilot.db.repositories import Repositories
from tests.conftest import AS_OF
from tests.fixtures.builders import make_evidence, make_thesis


def test_alerta_sem_lastro_e_recusado(session, demo_ctx: None) -> None:
    """RF-33: o dado que disparou precisa ser rastreavel."""
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    with pytest.raises(MissingEvidenceError, match="evidence_id"):
        repos.alerts.raise_alert(
            thesis_id=thesis.id,
            severity=Severity.CRITICO,
            alert_kind=AlertKind.PREMISSA_VIOLADA,
            message="sem lastro",
            evidence_id="",
        )


def test_deduplicacao_incrementa_em_vez_de_repetir(session, demo_ctx: None) -> None:
    """RF-37 / AC-24: um alerta com contador, nao N alertas identicos."""
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    evidence = make_evidence(repos, value=Decimal("0.44"), unit=Unit.PERCENT, as_of=AS_OF)
    chave = f"{thesis.id}:ear_sudeste_pct:7d"

    for _ in range(3):
        repos.alerts.raise_alert(
            thesis_id=thesis.id,
            severity=Severity.ATENCAO,
            alert_kind=AlertKind.PREMISSA_VIOLADA,
            message="EAR abaixo da faixa.",
            evidence_id=evidence.id,
            dedup_key=chave,
            as_of=AS_OF,
        )
    session.flush()

    abertos = repos.alerts.open_alerts(thesis_id=thesis.id)
    assert len(abertos) == 1
    assert abertos[0].occurrence_count == 3


def test_alerta_reconhecido_libera_novo_alerta(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    evidence = make_evidence(repos, as_of=AS_OF)
    chave = "k"

    primeiro = repos.alerts.raise_alert(
        thesis_id=thesis.id,
        severity=Severity.ATENCAO,
        alert_kind=AlertKind.GATILHO_DISPARADO,
        message="primeiro",
        evidence_id=evidence.id,
        dedup_key=chave,
        as_of=AS_OF,
    )
    repos.alerts.acknowledge(
        primeiro, decision=AlertDecision.MANTER, rationale="Monitorando de perto."
    )
    repos.alerts.raise_alert(
        thesis_id=thesis.id,
        severity=Severity.ATENCAO,
        alert_kind=AlertKind.GATILHO_DISPARADO,
        message="segundo",
        evidence_id=evidence.id,
        dedup_key=chave,
        as_of=AS_OF,
    )
    session.flush()
    assert repos.alerts.count(thesis_id=thesis.id) == 2
    assert len(repos.alerts.open_alerts(thesis_id=thesis.id)) == 1


def test_reconhecimento_exige_justificativa(session, demo_ctx: None) -> None:
    """RF-34 / AC-25: decidir sem justificar nao e decidir."""
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    evidence = make_evidence(repos, as_of=AS_OF)
    alerta = repos.alerts.raise_alert(
        thesis_id=thesis.id,
        severity=Severity.CRITICO,
        alert_kind=AlertKind.VAR_LIMITE,
        message="VaR no limite.",
        evidence_id=evidence.id,
        as_of=AS_OF,
    )
    with pytest.raises(ValueError, match="justificativa"):
        repos.alerts.acknowledge(alerta, decision=AlertDecision.ENCERRAR, rationale="  ")

    repos.alerts.acknowledge(
        alerta, decision=AlertDecision.AJUSTAR, rationale="Reduzir volume em 20%."
    )
    assert alerta.decision is AlertDecision.AJUSTAR
    assert alerta.acknowledged_at is not None
    assert alerta.is_open is False


def test_run_parcial_quando_uma_fonte_falha(session, demo_ctx: None) -> None:
    """RF-36 / AC-23."""
    from copilot.common.enums import WatchdogStatus

    repos = Repositories(session)
    run = repos.watchdog.start(trigger_source="manual", as_of=AS_OF)
    repos.watchdog.finish(
        run,
        theses_checked=1,
        sources_ok=["fonte A"],
        sources_failed=["fonte B"],
    )
    assert run.status is WatchdogStatus.PARCIAL
    assert run.sources_failed == ["fonte B"]


def test_run_ok_quando_nada_falha(session, demo_ctx: None) -> None:
    from copilot.common.enums import WatchdogStatus

    repos = Repositories(session)
    run = repos.watchdog.start(as_of=AS_OF)
    repos.watchdog.finish(run, theses_checked=1, sources_ok=["fonte A"])
    assert run.status is WatchdogStatus.OK


def test_run_falha_quando_nenhuma_fonte_responde(session, demo_ctx: None) -> None:
    from copilot.common.enums import WatchdogStatus

    repos = Repositories(session)
    run = repos.watchdog.start(as_of=AS_OF)
    repos.watchdog.finish(run, sources_failed=["fonte A", "fonte B"])
    assert run.status is WatchdogStatus.FALHA
