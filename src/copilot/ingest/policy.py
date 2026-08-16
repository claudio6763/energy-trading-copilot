"""Politica de licenciamento na ingestao — P10 / RNF-08 / AC-56.

A regra e "bloqueia na entrada, nao filtra na saida": fonte sem licenca
compativel nunca chega a existir no banco. Este modulo e o unico ponto de
decisao; o Sprint 2 (ingestores) e os repositorios chamam `assert_ingestable`.
"""

from __future__ import annotations

from copilot.common.enums import BLOCKED_LICENSE_CLASSES, LicenseClass
from copilot.common.errors import LicenseViolation
from copilot.common.logging import get_logger

log = get_logger(__name__)

#: Classes publicas: autorizacao implicita, atribuicao obrigatoria em PUBLIC_ATTRIB.
_IMPLICITLY_AUTHORIZED = frozenset({LicenseClass.PUBLIC_OPEN, LicenseClass.PUBLIC_ATTRIB})

#: Classes que exigem autorizacao registrada em `source.authorization_ref`.
_REQUIRES_AUTHORIZATION = frozenset(
    {LicenseClass.LICENSED_AUTHORIZED, LicenseClass.CONFIDENTIAL_INTERNAL}
)


def is_ingestable(license_class: LicenseClass, authorized: bool) -> bool:
    """True se a fonte pode ser ingerida."""
    if license_class in BLOCKED_LICENSE_CLASSES:
        return False
    if license_class in _REQUIRES_AUTHORIZATION and not authorized:
        return False
    return True


def assert_ingestable(
    license_class: LicenseClass,
    authorized: bool,
    *,
    subject: str = "fonte",
    authorization_ref: str | None = None,
) -> None:
    """Levanta `LicenseViolation` se a ingestao nao for permitida.

    :param subject: descricao usada na mensagem e no log (nome da fonte ou do documento).
    """
    if license_class in BLOCKED_LICENSE_CLASSES:
        log.warning(
            "ingestao_rejeitada",
            extra={"subject": subject, "license_class": license_class.value, "reason": "classe_bloqueada"},
        )
        raise LicenseViolation(
            f"Ingestao rejeitada para {subject!r}: licenca {license_class.value} e "
            "bloqueada sem autorizacao escrita (P10). Nada foi gravado."
        )
    if license_class in _REQUIRES_AUTHORIZATION and not authorized:
        log.warning(
            "ingestao_rejeitada",
            extra={"subject": subject, "license_class": license_class.value, "reason": "sem_autorizacao"},
        )
        raise LicenseViolation(
            f"Ingestao rejeitada para {subject!r}: licenca {license_class.value} exige "
            "autorizacao registrada em `authorization_ref` (P10)."
        )
    if license_class in _REQUIRES_AUTHORIZATION and not authorization_ref:
        log.warning(
            "autorizacao_sem_referencia",
            extra={"subject": subject, "license_class": license_class.value},
        )


def effective_authorization(license_class: LicenseClass, authorized: bool) -> bool:
    """Autorizacao efetiva: classes publicas sao implicitamente autorizadas."""
    return True if license_class in _IMPLICITLY_AUTHORIZED else authorized


__all__ = ["assert_ingestable", "effective_authorization", "is_ingestable"]
