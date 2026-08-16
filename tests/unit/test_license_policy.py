"""Politica de licenciamento na ingestao — P10 / RNF-08 / AC-56."""

from __future__ import annotations

import pytest

from copilot.common.enums import LicenseClass
from copilot.common.errors import LicenseViolation
from copilot.ingest.policy import assert_ingestable, effective_authorization, is_ingestable


@pytest.mark.parametrize(
    "classe", [LicenseClass.PUBLIC_OPEN, LicenseClass.PUBLIC_ATTRIB]
)
def test_publico_e_sempre_ingerivel(classe: LicenseClass) -> None:
    assert is_ingestable(classe, authorized=False)
    assert effective_authorization(classe, authorized=False) is True
    assert_ingestable(classe, False, subject="fonte publica")


@pytest.mark.parametrize(
    "classe", [LicenseClass.LICENSED_BLOCKED, LicenseClass.CONFIDENTIAL_EXTERNAL]
)
def test_classes_bloqueadas_sao_rejeitadas_mesmo_com_flag(classe: LicenseClass) -> None:
    """Nao existe caminho para ingerir estas classes. Nem com authorized=True."""
    assert not is_ingestable(classe, authorized=True)
    with pytest.raises(LicenseViolation, match="rejeitada"):
        assert_ingestable(classe, True, subject="curva de provedor comercial")


def test_licenciada_exige_autorizacao_registrada() -> None:
    assert not is_ingestable(LicenseClass.LICENSED_AUTHORIZED, authorized=False)
    with pytest.raises(LicenseViolation, match="autorizacao"):
        assert_ingestable(LicenseClass.LICENSED_AUTHORIZED, False, subject="provedor X")

    assert is_ingestable(LicenseClass.LICENSED_AUTHORIZED, authorized=True)
    assert_ingestable(
        LicenseClass.LICENSED_AUTHORIZED,
        True,
        subject="provedor X",
        authorization_ref="contrato-2026-001",
    )


def test_interno_confidencial_segue_a_mesma_regra() -> None:
    assert not is_ingestable(LicenseClass.CONFIDENTIAL_INTERNAL, authorized=False)
    assert is_ingestable(LicenseClass.CONFIDENTIAL_INTERNAL, authorized=True)


def test_mensagem_deixa_claro_que_nada_foi_gravado() -> None:
    with pytest.raises(LicenseViolation) as exc:
        assert_ingestable(LicenseClass.LICENSED_BLOCKED, False, subject="curva DCIDE")
    assert "Nada foi gravado" in str(exc.value)
