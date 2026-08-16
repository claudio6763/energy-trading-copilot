"""Enumeracoes do dominio (DATA_CONTRACT.md).

Regra C8: enums sao persistidos como TEXTO com CHECK constraint, nunca como enum
nativo do banco. Isso mantem SQLite e PostgreSQL sob o mesmo grafo de migrations.

Convencao: identificador Python em ASCII, valor persistido em portugues (CLAUDE.md
secao 5 — nomes de dominio em portugues).
"""

from __future__ import annotations

from enum import Enum


class DomainEnum(str, Enum):
    """Base: serializa como string e compara com string."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)


# ---------------------------------------------------------------------------
# Transversais
# ---------------------------------------------------------------------------


class DatasetKind(DomainEnum):
    """P9 — separacao entre dado demonstrativo e dado real."""

    DEMO = "DEMO"
    REAL = "REAL"


class LicenseClass(DomainEnum):
    """DATA_CONTRACT secao 4. P10 — bloqueio na ingestao, nao na saida."""

    PUBLIC_OPEN = "PUBLIC_OPEN"
    PUBLIC_ATTRIB = "PUBLIC_ATTRIB"
    LICENSED_AUTHORIZED = "LICENSED_AUTHORIZED"
    LICENSED_BLOCKED = "LICENSED_BLOCKED"
    CONFIDENTIAL_INTERNAL = "CONFIDENTIAL_INTERNAL"
    CONFIDENTIAL_EXTERNAL = "CONFIDENTIAL_EXTERNAL"


#: Classes cuja ingestao e sempre rejeitada (DATA_CONTRACT secao 2.2 e 4).
BLOCKED_LICENSE_CLASSES: frozenset[LicenseClass] = frozenset(
    {LicenseClass.LICENSED_BLOCKED, LicenseClass.CONFIDENTIAL_EXTERNAL}
)


class Confidence(DomainEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DataQuality(DomainEnum):
    """Qualidade declarada do dado. Nunca inferida — sempre carimbada na ingestao."""

    #: Valor oficial publicado, sem tratamento.
    OK = "OK"
    #: Preliminar / sujeito a revisao pela fonte.
    PRELIMINAR = "PRELIMINAR"
    #: Interpolado ou completado por nos. Aparece na UI como estimado.
    ESTIMADO = "ESTIMADO"
    #: Serie com buracos conhecidos no periodo.
    INCOMPLETO = "INCOMPLETO"
    #: Fora de faixa esperada ou reprovado em checagem de sanidade.
    SUSPEITO = "SUSPEITO"
    #: Nao mede o que se quer medir; e substituto declarado (ex.: PLD por forward).
    PROXY = "PROXY"


#: Qualidades que exigem penalizacao explicita quando usadas em precificacao/risco.
PENALIZED_QUALITIES: frozenset[DataQuality] = frozenset(
    {DataQuality.ESTIMADO, DataQuality.INCOMPLETO, DataQuality.SUSPEITO, DataQuality.PROXY}
)


class Severity(DomainEnum):
    INFO = "INFO"
    ATENCAO = "ATENÇÃO"
    CRITICO = "CRÍTICO"


class Criticality(DomainEnum):
    ALTA = "ALTA"
    MEDIA = "MÉDIA"
    BAIXA = "BAIXA"


class Likelihood(DomainEnum):
    ALTA = "ALTA"
    MEDIA = "MÉDIA"
    BAIXA = "BAIXA"


class Submarket(DomainEnum):
    SE_CO = "SE/CO"
    S = "S"
    NE = "NE"
    N = "N"


# ---------------------------------------------------------------------------
# Fontes, evidencia e proveniencia
# ---------------------------------------------------------------------------


class SourceKind(DomainEnum):
    OFICIAL = "OFICIAL"
    BOLETIM = "BOLETIM"
    MODELO_METEO = "MODELO_METEO"
    PROVEDOR_COMERCIAL = "PROVEDOR_COMERCIAL"
    INTERNO = "INTERNO"
    MANUAL = "MANUAL"


class EvidenceSourceType(DomainEnum):
    RAG_DOC = "RAG_DOC"
    SQL_QUERY = "SQL_QUERY"
    QUANT_RUN = "QUANT_RUN"
    HUMAN_INPUT = "HUMAN_INPUT"
    EXTERNAL_FILE = "EXTERNAL_FILE"


class Unit(DomainEnum):
    """Unidades aceitas. Numero sem unidade nao e dado."""

    BRL = "R$"
    MWH = "MWh"
    MWMED = "MWmed"
    BRL_PER_MWH = "R$/MWh"
    PERCENT = "%"
    M3_S = "m³/s"
    MM = "mm"
    ADIMENSIONAL = "adimensional"


# ---------------------------------------------------------------------------
# Tese e componentes
# ---------------------------------------------------------------------------


class ThesisDirection(DomainEnum):
    COMPRA = "COMPRA"
    VENDA = "VENDA"
    SPREAD = "SPREAD"
    ESTRUTURADO = "ESTRUTURADO"


class ThesisStatus(DomainEnum):
    RASCUNHO = "RASCUNHO"
    EM_DEBATE = "EM_DEBATE"
    APROVADA = "APROVADA"
    ATIVA = "ATIVA"
    EM_REVISAO = "EM_REVISÃO"
    ENCERRADA = "ENCERRADA"
    INVALIDADA = "INVALIDADA"


#: Transicoes permitidas (RF-10). Aplicadas em codigo pelo ThesisRepository.
THESIS_TRANSITIONS: dict[ThesisStatus, frozenset[ThesisStatus]] = {
    ThesisStatus.RASCUNHO: frozenset({ThesisStatus.EM_DEBATE, ThesisStatus.ENCERRADA}),
    ThesisStatus.EM_DEBATE: frozenset(
        {ThesisStatus.RASCUNHO, ThesisStatus.APROVADA, ThesisStatus.ENCERRADA}
    ),
    ThesisStatus.APROVADA: frozenset({ThesisStatus.ATIVA, ThesisStatus.ENCERRADA}),
    ThesisStatus.ATIVA: frozenset(
        {ThesisStatus.EM_REVISAO, ThesisStatus.ENCERRADA, ThesisStatus.INVALIDADA}
    ),
    ThesisStatus.EM_REVISAO: frozenset(
        {ThesisStatus.ATIVA, ThesisStatus.ENCERRADA, ThesisStatus.INVALIDADA}
    ),
    ThesisStatus.ENCERRADA: frozenset(),
    ThesisStatus.INVALIDADA: frozenset(),
}

#: A partir daqui a tese e imutavel: editar exige nova versao (RF-09).
IMMUTABLE_THESIS_STATUSES: frozenset[ThesisStatus] = frozenset(
    {
        ThesisStatus.APROVADA,
        ThesisStatus.ATIVA,
        ThesisStatus.EM_REVISAO,
        ThesisStatus.ENCERRADA,
        ThesisStatus.INVALIDADA,
    }
)


class AssumptionKind(DomainEnum):
    HIDROLOGICA = "HIDROLÓGICA"
    PRECO = "PREÇO"
    CARGA = "CARGA"
    OFERTA = "OFERTA"
    REGULATORIA = "REGULATÓRIA"
    LIQUIDEZ = "LIQUIDEZ"
    OUTRA = "OUTRA"


class AssumptionStatus(DomainEnum):
    VALIDA = "VÁLIDA"
    SOB_TENSAO = "SOB_TENSÃO"
    VIOLADA = "VIOLADA"
    #: Premissa sem `metric_key`: aceita, porem nao vigiavel. Aparece na UI (RF-32).
    NAO_MONITORAVEL = "NÃO_MONITORÁVEL"


class Instrument(DomainEnum):
    PPA = "PPA"
    FORWARD_CONV = "FORWARD_CONV"
    FORWARD_I5 = "FORWARD_I5"
    OPCAO = "OPÇÃO"
    SWAP = "SWAP"
    ESTRUTURADO = "ESTRUTURADO"


class Side(DomainEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class RuleType(DomainEnum):
    SAIDA = "SAÍDA"
    INVALIDACAO = "INVALIDAÇÃO"
    ALERTA = "ALERTA"


class RuleOperator(DomainEnum):
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    CROSS_UP = "cross_up"
    CROSS_DOWN = "cross_down"
    DELTA_PCT = "delta_pct"


class RiskCategory(DomainEnum):
    MERCADO = "MERCADO"
    HIDROLOGICO = "HIDROLÓGICO"
    REGULATORIO = "REGULATÓRIO"
    CREDITO = "CRÉDITO"
    LIQUIDEZ = "LIQUIDEZ"
    OPERACIONAL = "OPERACIONAL"
    BASE = "BASE"


# ---------------------------------------------------------------------------
# Motor quantitativo e cenarios
# ---------------------------------------------------------------------------


class QuantFunction(DomainEnum):
    VAR_HISTORICAL = "var_historical"
    VAR_PARAMETRIC = "var_parametric"
    VAR_EWMA = "var_ewma"
    VAR_PORTFOLIO = "var_portfolio"
    VAR_MC = "var_mc"
    PNL = "pnl"
    SCENARIO = "scenario"
    ADDONS = "addons"
    LIMIT_CHECK = "limit_check"
    OPTIMIZE = "optimize"
    PRICING = "pricing"


class ScenarioKind(DomainEnum):
    HIDROLOGICO = "HIDROLÓGICO"
    PRECO = "PREÇO"
    CARGA = "CARGA"
    COMBINADO = "COMBINADO"


# ---------------------------------------------------------------------------
# Debate e verificacao
# ---------------------------------------------------------------------------


class AgentName(DomainEnum):
    TRADER = "TRADER"
    RISCO = "RISCO"
    REGULATORIO = "REGULATÓRIO"
    DADOS_SQL = "DADOS_SQL"
    INTELIGENCIA_MERCADO = "INTELIGÊNCIA_MERCADO"
    ORQUESTRADOR = "ORQUESTRADOR"


class TurnRole(DomainEnum):
    DEFESA = "DEFESA"
    ATAQUE = "ATAQUE"
    CONSULTA = "CONSULTA"


class DebateVerdict(DomainEnum):
    APROVAVEL = "APROVÁVEL"
    BLOQUEADA = "BLOQUEADA"
    INCONCLUSIVA = "INCONCLUSIVA"


class ClaimType(DomainEnum):
    NUMERICA = "NUMÉRICA"
    FACTUAL = "FACTUAL"
    OPINIAO = "OPINIÃO"


class ClaimStatus(DomainEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTED = "CONTRADICTED"
    BLOCKED = "BLOCKED"


#: Presenca de qualquer um destes bloqueia a transicao para APROVADA (RF-51).
BLOCKING_CLAIM_STATUSES: frozenset[ClaimStatus] = frozenset(
    {ClaimStatus.CONTRADICTED, ClaimStatus.BLOCKED}
)


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------


class WatchdogStatus(DomainEnum):
    OK = "OK"
    PARCIAL = "PARCIAL"
    FALHA = "FALHA"


class AlertKind(DomainEnum):
    PREMISSA_VIOLADA = "PREMISSA_VIOLADA"
    GATILHO_DISPARADO = "GATILHO_DISPARADO"
    INVALIDACAO = "INVALIDAÇÃO"
    VAR_LIMITE = "VAR_LIMITE"
    MUDANCA_REGULATORIA = "MUDANÇA_REGULATÓRIA"
    #: Fonte indisponivel nunca vira silencio (RF-36).
    COBERTURA_DADOS = "COBERTURA_DADOS"


class AlertDecision(DomainEnum):
    MANTER = "MANTER"
    AJUSTAR = "AJUSTAR"
    ENCERRAR = "ENCERRAR"


# ---------------------------------------------------------------------------
# Acervo documental (RAG) — apenas o schema no Sprint 1
# ---------------------------------------------------------------------------


class DocType(DomainEnum):
    RESOLUCAO = "RESOLUÇÃO"
    REGRA_COMERCIALIZACAO = "REGRA_COMERCIALIZAÇÃO"
    PROCEDIMENTO_REDE = "PROCEDIMENTO_REDE"
    BOLETIM = "BOLETIM"
    RELATORIO = "RELATÓRIO"
    NOTA_MERCADO = "NOTA_MERCADO"


# ---------------------------------------------------------------------------
# Curva forward
# ---------------------------------------------------------------------------


class ProductClass(DomainEnum):
    """Classe de produto da curva forward no mercado livre brasileiro."""

    CONVENCIONAL = "CONVENCIONAL"
    I0 = "I0"
    I5 = "I5"
    I100 = "I100"


class CurvePriceType(DomainEnum):
    MID = "MID"
    BID = "BID"
    ASK = "ASK"
    #: Referencia publica declarada usada como proxy enquanto D-02 nao e respondida.
    PROXY_PUBLICO = "PROXY_PÚBLICO"


class CurveOrigin(DomainEnum):
    """De onde a curva veio. Separa preco negociado de substituto.

    Regra dura do projeto: **PLD e CMO nao sao curva forward negociada.** Sao
    precos de curto prazo formados por modelo de despacho, nao por transacao
    entre contrapartes. Quando usados como referencia de longo prazo, entram
    como `PROXY_SPOT`, ficam marcados `DataQuality.PROXY` e recebem add-on de
    proxy no calculo de risco.
    """

    #: Preco observado em transacao ou cotacao firme de contraparte.
    NEGOCIADA = "NEGOCIADA"
    #: Derivada de PLD/CMO. Sempre penalizada.
    PROXY_SPOT = "PROXY_SPOT"
    #: Saida de modelo proprio ou de terceiro (nao transacionada).
    PROXY_MODELO = "PROXY_MODELO"
    #: Curva interna da companhia.
    INTERNA = "INTERNA"


#: Origens que NAO representam preco negociado. Exigem add-on de proxy (RF-52).
PROXY_CURVE_ORIGINS: frozenset[CurveOrigin] = frozenset(
    {CurveOrigin.PROXY_SPOT, CurveOrigin.PROXY_MODELO}
)

#: Metricas de curto prazo que jamais podem ser registradas como curva negociada.
SPOT_ONLY_METRICS: frozenset[str] = frozenset(
    {"pld", "cmo", "pld_se_semanal", "pld_s_semanal", "pld_ne_semanal", "pld_n_semanal",
     "cmo_se", "cmo_s", "cmo_ne", "cmo_n"}
)


class AddOnKind(DomainEnum):
    """Add-ons de risco somados ao VaR de mercado."""

    LIQUIDEZ = "LIQUIDEZ"
    BASIS = "BASIS"
    PROXY = "PROXY"
    RISCO_MODELO = "RISCO_MODELO"


class HydroScenario(DomainEnum):
    """Cenarios hidrologicos padrao. `EXTREMO` e estresse, nao previsao."""

    SECO = "SECO"
    BASE = "BASE"
    UMIDO = "ÚMIDO"
    EXTREMO = "EXTREMO"


class AdapterStatus(DomainEnum):
    """Resultado de uma execucao de adapter de ingestao."""

    OK = "OK"
    PARCIAL = "PARCIAL"
    #: Endpoint fora do ar, sem rede, ou interface ainda nao implementada.
    INDISPONIVEL = "INDISPONÍVEL"
    #: Bloqueado pela politica de licenciamento (P10).
    REJEITADO = "REJEITADO"


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------


class ActorType(DomainEnum):
    HUMANO = "HUMANO"
    AGENTE = "AGENTE"
    SISTEMA = "SISTEMA"


class AuditAction(DomainEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    VERSION = "VERSION"
    STATUS_CHANGE = "STATUS_CHANGE"
    APPROVE = "APPROVE"
    VETO = "VETO"
    INGEST = "INGEST"
    INGEST_REJECTED = "INGEST_REJECTED"
    SEED = "SEED"
    QUANT_RUN = "QUANT_RUN"
    WATCHDOG_RUN = "WATCHDOG_RUN"
    ALERT_RAISED = "ALERT_RAISED"
    DECISION = "DECISION"
    DELETE = "DELETE"


__all__ = [name for name in dir() if not name.startswith("_")]
