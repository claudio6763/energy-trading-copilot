"""Excecoes do dominio.

Cada excecao corresponde a um principio inviolavel de CLAUDE.md secao 2.
Falhar alto e proposital: violacao de principio nunca degrada em silencio.
"""

from __future__ import annotations


class CopilotError(Exception):
    """Base de todas as excecoes do projeto."""


class ConfigError(CopilotError):
    """Configuracao ausente ou inconsistente."""


class MissingContextError(CopilotError):
    """Operacao de dados sem `as_of` e `dataset_kind` no contexto (P7, P9)."""


class DatasetKindViolation(CopilotError):
    """Tentativa de misturar DEMO e REAL na mesma operacao (P9 / RF-57)."""


class AsOfViolation(CopilotError):
    """Tentativa de usar dado posterior ao `as_of` do contexto (P7 / RF-58)."""


class MissingEvidenceError(CopilotError):
    """Afirmacao factual sem `evidence_id` (P6 / RF-51 / AC-02)."""


class LicenseViolation(CopilotError):
    """Ingestao de fonte licenciada ou confidencial sem autorizacao (P10 / RNF-08)."""


class AppendOnlyViolation(CopilotError):
    """Tentativa de alterar ou apagar a trilha de auditoria (C7 / AC-61)."""


class ImmutableThesisError(CopilotError):
    """Edicao direta de tese ja aprovada. Use nova versao (RF-09)."""


class InvalidStatusTransition(CopilotError):
    """Transicao de estado nao permitida (RF-10)."""


class VarLimitExceeded(CopilotError):
    """VaR acima do limite de R$ 50 milhoes (P8 / RF-54)."""


# ---------------------------------------------------------------------------
# Sprint 2 — ingestao e motor quantitativo
# ---------------------------------------------------------------------------


class IngestError(CopilotError):
    """Base das falhas de ingestao."""


class SchemaValidationError(IngestError):
    """Arquivo com colunas ausentes, tipos invalidos ou linhas inconsistentes."""

    def __init__(self, message: str, issues: list[str] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


class UnsupportedFormatError(IngestError):
    """Extensao nao suportada pelo leitor de arquivos."""


class AdapterUnavailable(IngestError):
    """Fonte externa indisponivel. Nunca degrada em dado vazio (RF-36)."""


class ProxyNotDeclaredError(IngestError):
    """PLD/CMO usado como curva forward sem declarar origem de proxy.

    Preco de curto prazo formado por modelo de despacho nao e preco negociado.
    Usar sem declarar seria esconder a premissa mais cara da precificacao.
    """


class QuantError(CopilotError):
    """Base das falhas do motor quantitativo."""


class InsufficientSampleError(QuantError):
    """Serie curta demais para a estimativa pedida. Nunca devolve numero fraco."""

    def __init__(self, message: str, *, observed: int = 0, required: int = 0) -> None:
        super().__init__(message)
        self.observed = observed
        self.required = required


class MissingDataError(QuantError):
    """Buraco na serie ou data sem cobertura. Falha alto, nunca preenche com zero."""


class InvalidPeriodError(QuantError):
    """Periodo de entrega invalido (fim antes do inicio, datas ausentes)."""


__all__ = [
    "AdapterUnavailable",
    "AppendOnlyViolation",
    "AsOfViolation",
    "ConfigError",
    "CopilotError",
    "DatasetKindViolation",
    "ImmutableThesisError",
    "IngestError",
    "InsufficientSampleError",
    "InvalidPeriodError",
    "InvalidStatusTransition",
    "LicenseViolation",
    "MissingContextError",
    "MissingDataError",
    "MissingEvidenceError",
    "ProxyNotDeclaredError",
    "QuantError",
    "SchemaValidationError",
    "UnsupportedFormatError",
    "VarLimitExceeded",
]
