"""Seed do dataset DEMO — dados **sintéticos**, gerados deterministicamente.

Tres regras que este modulo respeita a risca:

1. **Nada aqui e dado de mercado.** Todos os valores saem de um gerador com seed
   fixa. Cada `evidence.excerpt` diz isso em letras maiusculas. Dado sintetico
   nunca e derivado de dado real, para nao confundir proveniencia (P9).
2. **Grava exclusivamente em `dataset_kind=DEMO`.** A tese da Entrega 2 vive em
   `REAL` e nunca e tocada por este script.
3. **Toda observacao carrega `evidence_id`.** O seed exercita o mesmo caminho de
   escrita da aplicacao — inclusive a rejeicao de fonte licenciada (AC-56).

Uso::

    make seed-demo            # popula (idempotente: nao duplica)
    make seed-demo-reset      # apaga tudo de DEMO e repopula
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete

from copilot.audit import trail
from copilot.common.context import run_context
from copilot.common.enums import (
    ActorType,
    AgentName,
    AlertKind,
    AssumptionKind,
    AuditAction,
    ClaimStatus,
    ClaimType,
    Confidence,
    Criticality,
    CurvePriceType,
    DatasetKind,
    DebateVerdict,
    DocType,
    EvidenceSourceType,
    Instrument,
    LicenseClass,
    Likelihood,
    ProductClass,
    QuantFunction,
    RiskCategory,
    RuleOperator,
    RuleType,
    ScenarioKind,
    Severity,
    Side,
    SourceKind,
    Submarket,
    ThesisDirection,
    ThesisStatus,
    TurnRole,
    Unit,
)
from copilot.common.errors import LicenseViolation
from copilot.common.logging import get_logger, setup_logging
from copilot.config.settings import get_settings
from copilot.db.models import (
    Alert,
    Assumption,
    Claim,
    DebateSession,
    DebateTurn,
    Document,
    DocumentChunk,
    Evidence,
    ForwardCurve,
    ForwardCurvePoint,
    MarketObservation,
    MarketSeries,
    Position,
    QuantRun,
    RiskItem,
    Scenario,
    ScenarioResult,
    Source,
    SqlExecution,
    Thesis,
    TriggerRule,
    WatchdogRun,
)
from copilot.db.repositories import Repositories
from copilot.db.session import session_scope

log = get_logger(__name__)

SEED_SOURCE_NAME = "SINTÉTICO — Gerador de demonstração"
SYNTHETIC_NOTE = (
    "VALOR SINTÉTICO GERADO PARA DEMONSTRAÇÃO. Não representa dado de mercado, "
    "não provém de ONS, CCEE, ANEEL ou de qualquer provedor. Uso restrito ao "
    "dataset DEMO."
)
HISTORY_DAYS = 45

#: Ordem de remocao respeitando as chaves estrangeiras. `audit_log` fica de fora:
#: a trilha e append-only e permanente, inclusive para o dataset DEMO (C7).
_DELETE_ORDER = (
    Claim,
    Alert,
    WatchdogRun,
    DebateTurn,
    DebateSession,
    ScenarioResult,
    Scenario,
    RiskItem,
    TriggerRule,
    Position,
    Assumption,
    Thesis,
    DocumentChunk,
    Document,
    ForwardCurvePoint,
    ForwardCurve,
    MarketObservation,
    MarketSeries,
    Evidence,
    QuantRun,
    SqlExecution,
    Source,
)


# --------------------------------------------------------------------- gerador
def _wave(day_index: int, *, base: float, amplitude: float, period: float, phase: float) -> float:
    """Serie deterministica e suave. Sem `random`: mesmo seed, mesmo resultado."""
    return base + amplitude * math.sin((day_index + phase) * 2 * math.pi / period)


def _dec(value: float, places: str = "0.01") -> Decimal:
    return Decimal(str(round(value, 6))).quantize(Decimal(places))


# ----------------------------------------------------------------------- limpeza
def purge_demo(session) -> int:  # type: ignore[no-untyped-def]
    """Remove todas as linhas DEMO. Nunca toca em REAL nem em `audit_log`."""
    removed = 0
    for model in _DELETE_ORDER:
        result = session.execute(
            delete(model).where(model.dataset_kind == DatasetKind.DEMO)
        )
        removed += result.rowcount or 0
    trail.append(
        session,
        action=AuditAction.SEED,
        entity="dataset",
        entity_id=None,
        note=f"purge do dataset DEMO: {removed} linhas removidas",
    )
    return removed


def already_seeded(session) -> bool:  # type: ignore[no-untyped-def]
    from sqlalchemy import func, select

    count = session.execute(
        select(func.count())
        .select_from(Source)
        .where(Source.dataset_kind == DatasetKind.DEMO, Source.name == SEED_SOURCE_NAME)
    ).scalar_one()
    return bool(count)


# -------------------------------------------------------------------- populacao
def seed(session, as_of: date) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Popula o dataset DEMO. Devolve a contagem por entidade."""
    repos = Repositories(session)
    counts: dict[str, int] = {}

    # 1. Fonte sintetica -----------------------------------------------------
    source = repos.sources.register(
        name=SEED_SOURCE_NAME,
        source_kind=SourceKind.MANUAL,
        license_class=LicenseClass.PUBLIC_OPEN,
        publisher="Energy Trading Copilot (seed)",
        authorized=True,
        update_frequency="sob demanda",
        notes=SYNTHETIC_NOTE,
    )
    counts["source"] = 1

    # 2. Prova do bloqueio de licenca na ingestao (P10 / AC-56) --------------
    try:
        repos.sources.register(
            name="Provedor comercial de curva (exemplo bloqueado)",
            source_kind=SourceKind.PROVEDOR_COMERCIAL,
            license_class=LicenseClass.LICENSED_BLOCKED,
            authorized=False,
        )
    except LicenseViolation as exc:
        trail.append(
            session,
            action=AuditAction.INGEST_REJECTED,
            entity="source",
            note=f"tentativa de ingestao rejeitada pela politica de licenca: {exc}",
        )
        counts["source_rejeitada"] = 1
    else:  # pragma: no cover - so ocorre se a politica regredir
        raise AssertionError(
            "Fonte LICENSED_BLOCKED foi aceita: a politica de licenciamento regrediu (P10)."
        )

    # 3. Series de mercado ---------------------------------------------------
    series_specs = [
        ("ear_sudeste_pct", "SINTÉTICO — Energia armazenada SE/CO, % da capacidade",
         Unit.PERCENT, "diaria", Submarket.SE_CO, None, None, 0.52, 0.10, 60.0, 0.0),
        ("ena_sin_mlt_pct", "SINTÉTICO — ENA do SIN, % da MLT",
         Unit.PERCENT, "diaria", None, None, None, 0.88, 0.22, 45.0, 12.0),
        ("pld_se_semanal", "SINTÉTICO — PLD SE/CO, R$/MWh",
         Unit.BRL_PER_MWH, "semanal", Submarket.SE_CO, None, None, 180.0, 60.0, 30.0, 5.0),
        ("carga_sin_mwmed", "SINTÉTICO — Carga do SIN, MWmed",
         Unit.MWMED, "diaria", None, None, None, 71000.0, 2500.0, 21.0, 3.0),
        # Duas rodadas divergentes da mesma metrica: a divergencia entre modelos
        # e preservada, nunca reduzida a media na ingestao.
        ("precip_prev_7d", "SINTÉTICO — Precipitação prevista 7d, rodada A",
         Unit.MM, "por_rodada", Submarket.SE_CO, "RODADA_A", "membro_01", 42.0, 18.0, 14.0, 0.0),
        ("precip_prev_7d", "SINTÉTICO — Precipitação prevista 7d, rodada B",
         Unit.MM, "por_rodada", Submarket.SE_CO, "RODADA_B", "membro_01", 61.0, 25.0, 14.0, 6.0),
    ]

    series_by_key: dict[str, MarketSeries] = {}
    observations = 0
    for (
        metric_key, description, unit, frequency, submarket, model_run, member,
        base, amplitude, period, phase,
    ) in series_specs:
        series = repos.series.register(
            metric_key=metric_key,
            description=description,
            unit=unit,
            frequency=frequency,
            source=source,
            submarket=submarket,
            model_run=model_run,
            ensemble_member=member,
        )
        series_by_key.setdefault(metric_key, series)

        for offset in range(HISTORY_DAYS, 0, -1):
            ref = as_of - timedelta(days=offset)
            raw = _wave(offset, base=base, amplitude=amplitude, period=period, phase=phase)
            value = _dec(raw, "0.000001" if unit is Unit.PERCENT else "0.01")
            evidence = repos.evidence.create(
                source_type=EvidenceSourceType.HUMAN_INPUT,
                source_id=source.id,
                locator=f"seed://{metric_key}/{ref.isoformat()}",
                excerpt=f"{SYNTHETIC_NOTE} {metric_key}={value} {unit.value} em {ref.isoformat()}.",
                license_class=LicenseClass.PUBLIC_OPEN,
                value_numeric=value,
                unit=unit,
                confidence=Confidence.LOW,
                as_of=ref,
            )
            repos.observations.record(
                series=series,
                ref_date=ref,
                value=value,
                evidence_id=evidence.id,
                as_of=ref,
            )
            observations += 1
    counts["market_series"] = len(series_specs)
    counts["market_observation"] = observations

    # 4. Curva forward -------------------------------------------------------
    curve_evidence = repos.evidence.create(
        source_type=EvidenceSourceType.HUMAN_INPUT,
        source_id=source.id,
        locator="seed://forward_curve/SE_CO",
        excerpt=f"{SYNTHETIC_NOTE} Curva forward sintética SE/CO, convencional.",
        license_class=LicenseClass.PUBLIC_OPEN,
        confidence=Confidence.LOW,
        as_of=as_of,
    )
    curve = repos.curves.create(
        curve_name="SINTÉTICA SE/CO convencional",
        submarket=Submarket.SE_CO,
        product_class=ProductClass.CONVENCIONAL,
        source=source,
        evidence_id=curve_evidence.id,
        price_type=CurvePriceType.PROXY_PUBLICO,
        as_of=as_of,
        notes=SYNTHETIC_NOTE,
    )
    tenors = [
        ("A+1", date(as_of.year + 1, 1, 1), date(as_of.year + 1, 12, 31), 195.00),
        ("A+2", date(as_of.year + 2, 1, 1), date(as_of.year + 2, 12, 31), 188.50),
        ("A+3", date(as_of.year + 3, 1, 1), date(as_of.year + 3, 12, 31), 182.00),
    ]
    for label, start, end, price in tenors:
        point_evidence = repos.evidence.create(
            source_type=EvidenceSourceType.HUMAN_INPUT,
            source_id=source.id,
            locator=f"seed://forward_curve/SE_CO/{label}",
            excerpt=f"{SYNTHETIC_NOTE} Tenor {label} = {price} R$/MWh.",
            license_class=LicenseClass.PUBLIC_OPEN,
            value_numeric=_dec(price),
            unit=Unit.BRL_PER_MWH,
            confidence=Confidence.LOW,
            as_of=as_of,
        )
        repos.curves.add_point(
            curve,
            tenor_label=label,
            delivery_start=start,
            delivery_end=end,
            price=_dec(price),
            evidence_id=point_evidence.id,
        )
    counts["forward_curve"] = 1
    counts["forward_curve_point"] = len(tenors)

    # 5. Acervo documental (schema; a ingestao real e do Sprint 4) -----------
    document = repos.documents.ingest(
        source=source,
        title="SINTÉTICO — Nota de demonstração sobre regras de comercialização",
        doc_type=DocType.NOTA_MERCADO,
        published_at=as_of - timedelta(days=30),
        effective_from=as_of - timedelta(days=30),
        as_of=as_of,
    )
    for index, text in enumerate(
        [
            f"{SYNTHETIC_NOTE} Trecho 1: texto de demonstração do acervo documental.",
            f"{SYNTHETIC_NOTE} Trecho 2: usado apenas para exercitar o schema de RAG.",
        ]
    ):
        repos.documents.add_chunk(document, chunk_index=index, text=text, page=index + 1)
    counts["document"] = 1
    counts["document_chunk"] = 2

    # 6. Cenarios hidrologicos distintos (RF-53) -----------------------------
    scenarios = {}
    for name, shocks, weight, description in [
        ("Base", {"ena_mlt_pct": 0.0, "pld_shift": 0.0}, "0.60",
         "SINTÉTICO — cenário central de demonstração."),
        ("Seco", {"ena_mlt_pct": -0.25, "pld_shift": 90.0}, "0.40",
         "SINTÉTICO — cenário de hidrologia adversa."),
    ]:
        scenarios[name] = repos.scenarios.create(
            name=name,
            kind=ScenarioKind.HIDROLOGICO,
            definition=shocks,
            description=description,
            probability_weight=Decimal(weight),
        )
    counts["scenario"] = len(scenarios)

    # 7. Tese de demonstracao ------------------------------------------------
    thesis = repos.theses.create_draft(
        title="DEMO — Venda de forward convencional SE/CO A+1",
        summary=(
            "Tese de demonstração, com números sintéticos.\n"
            "Existe para exercitar registro, debate e vigilância ponta a ponta.\n"
            "Não é recomendação e não reflete leitura de mercado."
        ),
        direction=ThesisDirection.VENDA,
        product="Forward convencional SE/CO A+1",
        submarket=Submarket.SE_CO,
        author="seed",
        delivery_start=date(as_of.year + 1, 1, 1),
        delivery_end=date(as_of.year + 1, 12, 31),
        horizon_days=120,
        review_date=as_of + timedelta(days=30),
        expected_pnl_p5=Decimal("-8500000.00"),
        expected_pnl_p50=Decimal("4200000.00"),
        expected_pnl_p95=Decimal("15800000.00"),
        var_consumed=Decimal("18500000.00"),
        as_of=as_of,
    )

    assumption_specs = [
        (AssumptionKind.HIDROLOGICA, "SINTÉTICA — EAR SE/CO permanece acima de 45%.",
         "ear_sudeste_pct", "0.520000", "0.450000", "0.750000", Unit.PERCENT, Criticality.ALTA),
        (AssumptionKind.PRECO, "SINTÉTICA — PLD SE/CO abaixo de 260 R$/MWh.",
         "pld_se_semanal", "180.00", "0.00", "260.00", Unit.BRL_PER_MWH, Criticality.ALTA),
        (AssumptionKind.CARGA, "SINTÉTICA — carga do SIN estável na faixa observada.",
         "carga_sin_mwmed", "71000.00", "66000.00", "76000.00", Unit.MWMED, Criticality.MEDIA),
    ]
    assumptions = []
    for kind, statement, metric_key, expected, low, high, unit, criticality in assumption_specs:
        evidence = repos.evidence.create(
            source_type=EvidenceSourceType.HUMAN_INPUT,
            source_id=source.id,
            locator=f"seed://assumption/{metric_key}",
            excerpt=f"{SYNTHETIC_NOTE} Premissa ancorada em {metric_key}.",
            license_class=LicenseClass.PUBLIC_OPEN,
            value_numeric=Decimal(expected),
            unit=unit,
            confidence=Confidence.LOW,
            as_of=as_of,
        )
        assumptions.append(
            repos.theses.add_assumption(
                thesis,
                kind=kind,
                statement=statement,
                evidence_id=evidence.id,
                metric_key=metric_key,
                expected_value=Decimal(expected),
                tolerance_low=Decimal(low),
                tolerance_high=Decimal(high),
                unit=unit,
                criticality=criticality,
            )
        )
    counts["assumption"] = len(assumptions)

    position_evidence = repos.evidence.create(
        source_type=EvidenceSourceType.HUMAN_INPUT,
        source_id=source.id,
        locator="seed://position/forward_a1",
        excerpt=f"{SYNTHETIC_NOTE} Preço de referência sintético de 195,00 R$/MWh.",
        license_class=LicenseClass.PUBLIC_OPEN,
        value_numeric=Decimal("195.00"),
        unit=Unit.BRL_PER_MWH,
        confidence=Confidence.LOW,
        as_of=as_of,
    )
    repos.theses.add_position(
        thesis,
        instrument=Instrument.FORWARD_CONV,
        submarket=Submarket.SE_CO,
        side=Side.SHORT,
        volume_mwh=Decimal("438000.000"),
        price_ref=Decimal("195.00"),
        delivery_start=date(as_of.year + 1, 1, 1),
        delivery_end=date(as_of.year + 1, 12, 31),
        evidence_id=position_evidence.id,
        var_contribution=Decimal("18500000.00"),
    )
    counts["position"] = 1

    rule_specs = [
        (RuleType.SAIDA, "pld_se_semanal", RuleOperator.GTE, "260.00", Unit.BRL_PER_MWH,
         "7d", Severity.CRITICO, "SINTÉTICA — sair se o PLD romper 260 R$/MWh."),
        (RuleType.INVALIDACAO, "ear_sudeste_pct", RuleOperator.LT, "0.450000", Unit.PERCENT,
         "spot", Severity.CRITICO, "SINTÉTICA — tese invalidada se a EAR cair abaixo de 45%."),
        (RuleType.ALERTA, "ena_sin_mlt_pct", RuleOperator.LT, "0.700000", Unit.PERCENT,
         "7d", Severity.ATENCAO, "SINTÉTICA — atenção se a ENA ficar abaixo de 70% da MLT."),
    ]
    for rule_type, metric_key, operator, threshold, unit, window, severity, description in rule_specs:
        repos.theses.add_trigger_rule(
            thesis,
            rule_type=rule_type,
            metric_key=metric_key,
            operator=operator,
            threshold=Decimal(threshold),
            unit=unit,
            eval_window=window,
            severity=severity,
            description=description,
        )
    counts["trigger_rule"] = len(rule_specs)

    for category, description, severity, likelihood, mitigation in [
        (RiskCategory.HIDROLOGICO, "SINTÉTICO — hidrologia adversa prolongada.",
         Severity.CRITICO, Likelihood.MEDIA, "Gatilho de invalidação em EAR < 45%."),
        (RiskCategory.LIQUIDEZ, "SINTÉTICO — consolidação de contrapartes reduz liquidez.",
         Severity.ATENCAO, Likelihood.ALTA, "Desmontagem faseada."),
    ]:
        repos.theses.add_risk(
            thesis,
            category=category,
            description=description,
            severity=severity,
            likelihood=likelihood,
            mitigation=mitigation,
        )
    counts["risk_item"] = 2

    # 8. Cenarios aplicados a tese, sempre via quant_run --------------------
    for name, p5, p50, p95, var_impact, delta in [
        ("Base", "-3200000.00", "5100000.00", "13400000.00", "18500000.00",
         "SINTÉTICO — tese mantida; reavaliação na data prevista."),
        ("Seco", "-21800000.00", "-9400000.00", "1200000.00", "34200000.00",
         "SINTÉTICO — gatilho de invalidação provavelmente acionado."),
    ]:
        run = repos.quant_runs.record(
            function=QuantFunction.SCENARIO,
            inputs={"scenario": name, "thesis_id": thesis.id, "seed_demo": True},
            outputs={"pnl_p50": p50, "var_impact": var_impact, "synthetic": True},
            seed=20260814,
        )
        repos.scenario_results.record(
            thesis=thesis,
            scenario=scenarios[name],
            quant_run_id=run.id,
            pnl_p5=Decimal(p5),
            pnl_p50=Decimal(p50),
            pnl_p95=Decimal(p95),
            var_impact=Decimal(var_impact),
            thesis_delta=delta,
        )
    counts["scenario_result"] = 2

    # 9. Debate de demonstracao ---------------------------------------------
    repos.theses.set_status(thesis, ThesisStatus.EM_DEBATE, note="seed")
    debate = repos.debates.open_session(thesis)
    turns = [
        (AgentName.ORQUESTRADOR, TurnRole.CONSULTA,
         "SINTÉTICO — rodada aberta; contexto montado com as_of e dataset DEMO."),
        (AgentName.TRADER, TurnRole.DEFESA,
         "SINTÉTICO — defesa da tese, ancorada nas três premissas registradas."),
        (AgentName.RISCO, TurnRole.ATAQUE,
         "SINTÉTICO — premissa hidrológica é a mais frágil; cenário Seco quebra a posição."),
        (AgentName.INTELIGENCIA_MERCADO, TurnRole.CONSULTA,
         "SINTÉTICO — leitura contrária registrada; divergência entre rodadas preservada."),
    ]
    for agent, role, content in turns:
        repos.debates.add_turn(
            debate,
            agent=agent,
            role=role,
            content=content,
            verifier_status=ClaimStatus.VERIFIED,
            prompt_version="seed",
            context_hash=None if agent is not AgentName.RISCO else "isolado",
        )
    repos.debates.close_session(
        debate,
        verdict=DebateVerdict.APROVAVEL,
        counter_argument=(
            "SINTÉTICO — no cenário Seco o VaR sobe para além do limite e a posição "
            "vira perda relevante; o dimensionamento assume hidrologia benigna."
        ),
        weakest_assumption_id=assumptions[0].id,
        breaking_scenario_id=scenarios["Seco"].id,
        confirmation_bias_score=Decimal("0.666667"),
        bias_rationale="SINTÉTICO — 2 de 3 fontes citadas concordam com a direção da tese.",
    )
    counts["debate_session"] = 1
    counts["debate_turn"] = len(turns)

    repos.claims.record(
        claim_text="SINTÉTICO — VaR consumido de R$ 18.500.000,00.",
        claim_type=ClaimType.NUMERICA,
        status=ClaimStatus.VERIFIED,
        thesis_id=thesis.id,
        value_numeric=Decimal("18500000.00"),
        unit=Unit.BRL,
        evidence_id=position_evidence.id,
    )
    repos.theses.set_status(thesis, ThesisStatus.APROVADA, note="seed")
    repos.theses.set_status(thesis, ThesisStatus.ATIVA, note="seed")

    # 10. Segunda tese: demonstra o bloqueio por claim sem lastro (RF-51) ----
    blocked_thesis = repos.theses.create_draft(
        title="DEMO — Tese bloqueada pelo Claim Verifier",
        summary=(
            "Tese de demonstração usada para provar o bloqueio.\n"
            "Contém uma afirmação numérica sem lastro."
        ),
        direction=ThesisDirection.COMPRA,
        product="Forward convencional SE/CO A+2",
        submarket=Submarket.SE_CO,
        author="seed",
        as_of=as_of,
    )
    repos.claims.record(
        claim_text="SINTÉTICO — número afirmado sem evidence_id (deve bloquear).",
        claim_type=ClaimType.NUMERICA,
        status=ClaimStatus.BLOCKED,
        thesis_id=blocked_thesis.id,
        value_numeric=Decimal("999999.99"),
        unit=Unit.BRL,
        reason="Número órfão: não originado de placeholder resolvido (RF-51).",
    )
    repos.theses.set_status(blocked_thesis, ThesisStatus.EM_DEBATE, note="seed")
    counts["thesis"] = 2
    counts["claim"] = 2

    # 11. Execucao de Watchdog e alertas ------------------------------------
    watchdog_run = repos.watchdog.start(trigger_source="agendado", as_of=as_of)
    alert_evidence = repos.evidence.create(
        source_type=EvidenceSourceType.HUMAN_INPUT,
        source_id=source.id,
        locator="seed://watchdog/ena_sin_mlt_pct",
        excerpt=f"{SYNTHETIC_NOTE} ENA sintética abaixo da faixa declarada na premissa.",
        license_class=LicenseClass.PUBLIC_OPEN,
        value_numeric=Decimal("0.680000"),
        unit=Unit.PERCENT,
        confidence=Confidence.LOW,
        as_of=as_of,
    )
    repos.alerts.raise_alert(
        thesis_id=thesis.id,
        severity=Severity.ATENCAO,
        alert_kind=AlertKind.PREMISSA_VIOLADA,
        message="SINTÉTICO — ENA abaixo de 70% da MLT: premissa hidrológica sob tensão.",
        evidence_id=alert_evidence.id,
        watchdog_run_id=watchdog_run.id,
        assumption_id=assumptions[0].id,
        observed_value=Decimal("0.680000"),
        expected_value=Decimal("0.880000"),
        delta=Decimal("-0.200000"),
        unit=Unit.PERCENT,
        dedup_key=f"{thesis.id}:ena_sin_mlt_pct:7d",
        as_of=as_of,
    )
    coverage_evidence = repos.evidence.create(
        source_type=EvidenceSourceType.HUMAN_INPUT,
        source_id=source.id,
        locator="seed://watchdog/cobertura",
        excerpt=f"{SYNTHETIC_NOTE} Fonte sintética indisponível no ciclo.",
        license_class=LicenseClass.PUBLIC_OPEN,
        confidence=Confidence.LOW,
        as_of=as_of,
    )
    repos.alerts.raise_alert(
        thesis_id=thesis.id,
        severity=Severity.ATENCAO,
        alert_kind=AlertKind.COBERTURA_DADOS,
        message=(
            "SINTÉTICO — série indisponível neste ciclo. Ausência de dado não é "
            "premissa válida (RF-36)."
        ),
        evidence_id=coverage_evidence.id,
        watchdog_run_id=watchdog_run.id,
        as_of=as_of,
    )
    repos.watchdog.finish(
        watchdog_run,
        theses_checked=2,
        assumptions_checked=len(assumptions),
        rules_evaluated=len(rule_specs),
        sources_ok=[SEED_SOURCE_NAME],
        sources_failed=["SINTÉTICA — série de demonstração indisponível"],
        notes="Execução de demonstração.",
    )
    counts["watchdog_run"] = 1
    counts["alert"] = 2

    trail.append(
        session,
        action=AuditAction.SEED,
        entity="dataset",
        note=f"seed DEMO concluido: {counts}",
    )
    return counts


# --------------------------------------------------------------------------- cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Popula o dataset DEMO com dados sintéticos.")
    parser.add_argument(
        "--reset", action="store_true", help="apaga todas as linhas DEMO antes de popular"
    )
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="data-base (padrão: DEFAULT_AS_OF)"
    )
    args = parser.parse_args(argv)

    setup_logging()
    settings = get_settings()
    as_of = args.as_of or settings.default_as_of

    with run_context(
        as_of=as_of,
        dataset_kind=DatasetKind.DEMO,
        actor="seed",
        actor_type=ActorType.SISTEMA,
    ):
        with session_scope() as session:
            if args.reset:
                removed = purge_demo(session)
                log.info("seed_purge", extra={"linhas_removidas": removed})
            elif already_seeded(session):
                log.info("seed_ignorado", extra={"motivo": "dataset DEMO ja populado"})
                print("Dataset DEMO ja populado. Use --reset para repopular.")
                return 0
            counts = seed(session, as_of)

    log.info("seed_concluido", extra=counts)
    print("Seed DEMO concluido:")
    for key in sorted(counts):
        print(f"  {key:>24}: {counts[key]}")
    print(f"  {'as_of':>24}: {as_of.isoformat()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
