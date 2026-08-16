"""Trilha de auditoria append-only e rastreabilidade (RF-55 / AC-60 / AC-61)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DatabaseError

from copilot.audit import trail
from copilot.common.enums import AuditAction, ThesisStatus
from copilot.common.errors import AppendOnlyViolation
from copilot.db.models import AuditLog
from copilot.db.repositories import Repositories
from tests.conftest import AS_OF
from tests.fixtures.builders import make_full_thesis, make_thesis


def test_toda_gravacao_deixa_rastro(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_full_thesis(repos, as_of=AS_OF)
    session.flush()

    entidades = {e.entity for e in trail.history(session, limit=500)}
    assert {"thesis", "assumption", "position", "trigger_rule", "risk_item"} <= entidades

    registros = trail.history(session, entity="thesis", entity_id=thesis.id)
    assert registros and registros[0].action is AuditAction.CREATE
    assert registros[0].actor == "pytest"
    assert registros[0].as_of == AS_OF
    assert registros[0].after_json["title"] == "Tese de teste"


def test_mudanca_de_estado_guarda_antes_e_depois(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    thesis = make_thesis(repos, as_of=AS_OF)
    repos.theses.set_status(thesis, ThesisStatus.EM_DEBATE, note="pronto para debate")
    session.flush()

    registros = [
        e for e in trail.history(session, entity="thesis", entity_id=thesis.id)
        if e.action is AuditAction.STATUS_CHANGE
    ]
    assert len(registros) == 1
    assert registros[0].before_json["status"] == "RASCUNHO"
    assert registros[0].after_json["status"] == "EM_DEBATE"


def test_update_na_trilha_e_bloqueado_pela_orm(session, demo_ctx: None) -> None:
    """AC-61, camada de aplicacao."""
    trail.append(session, action=AuditAction.CREATE, entity="teste", entity_id=None)
    session.flush()

    registro = session.query(AuditLog).first()
    registro.note = "adulterado"
    with pytest.raises(AppendOnlyViolation):
        session.flush()
    session.rollback()


def test_delete_na_trilha_e_bloqueado_pela_orm(session, demo_ctx: None) -> None:
    trail.append(session, action=AuditAction.CREATE, entity="teste", entity_id=None)
    session.flush()

    session.delete(session.query(AuditLog).first())
    with pytest.raises(AppendOnlyViolation):
        session.flush()
    session.rollback()


def test_update_na_trilha_e_bloqueado_pelo_banco(session, demo_ctx: None) -> None:
    """AC-61, camada que importa: a garantia nao depende do codigo da aplicacao."""
    trail.append(session, action=AuditAction.CREATE, entity="teste", entity_id=None)
    session.commit()

    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("UPDATE audit_log SET note = 'adulterado'"))
    session.rollback()


def test_delete_na_trilha_e_bloqueado_pelo_banco(session, demo_ctx: None) -> None:
    trail.append(session, action=AuditAction.CREATE, entity="teste", entity_id=None)
    session.commit()

    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("DELETE FROM audit_log"))
    session.rollback()


def test_linha_do_tempo_reconstroi_a_decisao(session, demo_ctx: None) -> None:
    """AC-60: por que a posicao existia, o que a sustentava, o que mudou."""
    repos = Repositories(session)
    thesis = make_full_thesis(repos, as_of=AS_OF)
    repos.theses.set_status(thesis, ThesisStatus.EM_DEBATE)
    repos.theses.set_status(thesis, ThesisStatus.APROVADA)
    repos.theses.set_status(thesis, ThesisStatus.ATIVA)
    session.flush()

    linha = trail.thesis_timeline(session, thesis.id)
    acoes = [e.action for e in linha]
    assert acoes[0] is AuditAction.CREATE
    assert AuditAction.APPROVE in acoes
    assert acoes[-1] is AuditAction.STATUS_CHANGE  # ATIVA e a ultima transicao
    chaves = [(e.created_at, e.id) for e in linha]
    assert chaves == sorted(chaves)  # ordem cronologica preservada
    assert [e.after_json["status"] for e in linha[1:]] == [
        "EM_DEBATE",
        "APROVADA",
        "ATIVA",
    ]


def test_evidence_ids_ficam_no_registro(session, demo_ctx: None) -> None:
    repos = Repositories(session)
    make_full_thesis(repos, as_of=AS_OF)
    session.flush()

    registros = trail.history(session, entity="assumption")
    assert registros
    assert registros[0].evidence_ids
    assert len(registros[0].evidence_ids[0]) == 26
