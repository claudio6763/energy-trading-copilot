"""Schema inicial: catalogo, evidencia, tese, debate, watchdog e auditoria.

Revision ID: 0001_initial
Revises:
Create Date: Sprint 1

Notas de projeto:

* Os tipos customizados (`DecimalText`, `EnumText`, `UTCDateTime`) sao importados
  de `copilot.db.types` de proposito: e o que garante DDL correto nos dois
  dialetos a partir de uma unica definicao, sem duplicar a logica de Decimal.
  O teste `tests/integration/test_migrations.py::test_migration_matches_models`
  protege contra divergencia entre migration e models.
* `audit_log` recebe triggers de banco que abortam UPDATE e DELETE. A garantia
  vale mesmo se alguem escrever fora da aplicacao (C7 / AC-61).
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

from copilot.common import enums as E
from copilot.db.types import DecimalText, EnumText, UTCDateTime, enum_check

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ULID = sa.String(26)


# --------------------------------------------------------------------------- helpers
def _id() -> sa.Column:
    return sa.Column("id", sa.String(26), primary_key=True)


def _created() -> sa.Column:
    return sa.Column("created_at", UTCDateTime(), nullable=False, index=True)


def _dataset_kind() -> sa.Column:
    return sa.Column("dataset_kind", EnumText(E.DatasetKind), nullable=False, index=True)


def _as_of() -> sa.Column:
    return sa.Column("as_of", sa.Date(), nullable=False, index=True)


def _money() -> DecimalText:
    return DecimalText(18, 2)


def _energy() -> DecimalText:
    return DecimalText(18, 3)


def _price() -> DecimalText:
    return DecimalText(12, 2)


def _percent() -> DecimalText:
    return DecimalText(9, 6)


def _obs() -> DecimalText:
    return DecimalText(28, 8)


def _fk(target: str, ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete=ondelete)


# --------------------------------------------------------------------------- upgrade
def upgrade() -> None:
    # ---------------------------------------------------------------- source
    op.create_table(
        "source",
        _id(),
        _created(),
        _dataset_kind(),
        sa.Column("name", sa.String(120), nullable=False, index=True),
        sa.Column("publisher", sa.String(160), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("source_kind", EnumText(E.SourceKind), nullable=False),
        sa.Column("license_class", EnumText(E.LicenseClass), nullable=False),
        sa.Column("authorized", sa.Boolean(), nullable=False),
        sa.Column("authorization_ref", sa.Text(), nullable=True),
        sa.Column("update_frequency", sa.String(60), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("name", "dataset_kind", name="uq_source_name_kind"),
        enum_check("source_kind", E.SourceKind),
        enum_check("license_class", E.LicenseClass),
        enum_check("dataset_kind", E.DatasetKind),
    )

    # -------------------------------------------------------- sql_execution
    op.create_table(
        "sql_execution",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("template_name", sa.String(120), nullable=True, index=True),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("sql_hash", sa.String(64), nullable=False, index=True),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("as_of_applied", sa.Boolean(), nullable=False),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_sql_execution_scope", "dataset_kind", "as_of"),
    )

    # ------------------------------------------------------------ quant_run
    op.create_table(
        "quant_run",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("function", EnumText(E.QuantFunction), nullable=False, index=True),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("inputs_hash", sa.String(64), nullable=False, index=True),
        sa.Column("outputs_json", sa.JSON(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("code_version", sa.String(32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        enum_check("function", E.QuantFunction),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_quant_run_repro", "inputs_hash", "code_version", "seed"),
        sa.Index("ix_quant_run_scope", "dataset_kind", "as_of"),
    )

    # ------------------------------------------------------------- evidence
    op.create_table(
        "evidence",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("source_type", EnumText(E.EvidenceSourceType), nullable=False, index=True),
        sa.Column("source_id", sa.String(64), nullable=True, index=True),
        sa.Column("locator", sa.Text(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("value_numeric", _obs(), nullable=True),
        sa.Column("unit", EnumText(E.Unit), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True, index=True),
        sa.Column("retrieved_at", UTCDateTime(), nullable=False),
        sa.Column("license_class", EnumText(E.LicenseClass), nullable=False),
        sa.Column("confidence", EnumText(E.Confidence), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        enum_check("source_type", E.EvidenceSourceType),
        enum_check("license_class", E.LicenseClass),
        enum_check("confidence", E.Confidence),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_evidence_scope", "dataset_kind", "as_of"),
    )

    # -------------------------------------------------------- market_series
    op.create_table(
        "market_series",
        _id(),
        _created(),
        _dataset_kind(),
        sa.Column("metric_key", sa.String(80), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", EnumText(E.Unit), nullable=False),
        sa.Column("frequency", sa.String(40), nullable=False),
        sa.Column("submarket", EnumText(E.Submarket), nullable=True),
        sa.Column("source_id", ULID, _fk("source.id", "RESTRICT"), nullable=False),
        sa.Column("license_class", EnumText(E.LicenseClass), nullable=False),
        sa.Column("model_run", sa.String(60), nullable=True),
        sa.Column("ensemble_member", sa.String(60), nullable=True),
        sa.UniqueConstraint(
            "metric_key", "dataset_kind", "model_run", "ensemble_member",
            name="uq_market_series_key",
        ),
        enum_check("unit", E.Unit),
        enum_check("license_class", E.LicenseClass),
        enum_check("submarket", E.Submarket),
        enum_check("dataset_kind", E.DatasetKind),
    )

    # --------------------------------------------------- market_observation
    op.create_table(
        "market_observation",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("series_id", ULID, _fk("market_series.id", "CASCADE"), nullable=False),
        sa.Column("ref_date", sa.Date(), nullable=False, index=True),
        sa.Column("value", _obs(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("evidence_id", ULID, _fk("evidence.id", "RESTRICT"), nullable=False),
        sa.UniqueConstraint(
            "series_id", "ref_date", "as_of", "revision", name="uq_market_observation_point"
        ),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_market_observation_scope", "dataset_kind", "as_of"),
        sa.Index("ix_market_observation_lookup", "series_id", "ref_date", "as_of"),
    )

    # -------------------------------------------------------- forward_curve
    op.create_table(
        "forward_curve",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("curve_name", sa.String(120), nullable=False, index=True),
        sa.Column("submarket", EnumText(E.Submarket), nullable=False),
        sa.Column("product_class", EnumText(E.ProductClass), nullable=False),
        sa.Column("price_type", EnumText(E.CurvePriceType), nullable=False),
        sa.Column("source_id", ULID, _fk("source.id", "RESTRICT"), nullable=False),
        sa.Column("license_class", EnumText(E.LicenseClass), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("evidence_id", ULID, _fk("evidence.id", "RESTRICT"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "curve_name", "submarket", "product_class", "price_type", "as_of", "dataset_kind",
            name="uq_forward_curve_key",
        ),
        enum_check("submarket", E.Submarket),
        enum_check("product_class", E.ProductClass),
        enum_check("price_type", E.CurvePriceType),
        enum_check("license_class", E.LicenseClass),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_forward_curve_scope", "dataset_kind", "as_of"),
    )

    op.create_table(
        "forward_curve_point",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("curve_id", ULID, _fk("forward_curve.id", "CASCADE"), nullable=False),
        sa.Column("tenor_label", sa.String(40), nullable=False),
        sa.Column("delivery_start", sa.Date(), nullable=False),
        sa.Column("delivery_end", sa.Date(), nullable=False),
        sa.Column("price", _price(), nullable=False),
        sa.Column("evidence_id", ULID, _fk("evidence.id", "RESTRICT"), nullable=False),
        sa.UniqueConstraint("curve_id", "tenor_label", name="uq_forward_curve_point_tenor"),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_forward_curve_point_scope", "dataset_kind", "as_of"),
    )

    # ------------------------------------------------------------- document
    op.create_table(
        "document",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("source_id", ULID, _fk("source.id", "RESTRICT"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("doc_type", EnumText(E.DocType), nullable=False, index=True),
        sa.Column("publisher", sa.String(160), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True, index=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True, index=True),
        sa.Column("license_class", EnumText(E.LicenseClass), nullable=False),
        sa.Column("authorized", sa.Boolean(), nullable=False),
        enum_check("doc_type", E.DocType),
        enum_check("license_class", E.LicenseClass),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_document_scope", "dataset_kind", "as_of"),
    )

    op.create_table(
        "document_chunk",
        _id(),
        _created(),
        _dataset_kind(),
        sa.Column("document_id", ULID, _fk("document.id", "CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(200), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        # Sprint 4: no PostgreSQL vira `vector(1536)` via migration condicional.
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_model", sa.String(80), nullable=True),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
        enum_check("dataset_kind", E.DatasetKind),
    )

    # --------------------------------------------------------------- thesis
    op.create_table(
        "thesis",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_id", ULID, _fk("thesis.id", "SET NULL"), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("direction", EnumText(E.ThesisDirection), nullable=False),
        sa.Column("product", sa.String(120), nullable=False),
        sa.Column("submarket", EnumText(E.Submarket), nullable=False),
        sa.Column("delivery_start", sa.Date(), nullable=True),
        sa.Column("delivery_end", sa.Date(), nullable=True),
        sa.Column("horizon_days", sa.Integer(), nullable=True),
        sa.Column("review_date", sa.Date(), nullable=True),
        sa.Column("status", EnumText(E.ThesisStatus), nullable=False, index=True),
        sa.Column("expected_pnl_p5", _money(), nullable=True),
        sa.Column("expected_pnl_p50", _money(), nullable=True),
        sa.Column("expected_pnl_p95", _money(), nullable=True),
        sa.Column("var_consumed", _money(), nullable=True),
        sa.Column("var_limit", _money(), nullable=False),
        sa.Column("author", sa.String(120), nullable=False),
        sa.Column("trader_response", sa.Text(), nullable=True),
        sa.Column("approved_at", UTCDateTime(), nullable=True),
        sa.Column("closed_at", UTCDateTime(), nullable=True),
        enum_check("direction", E.ThesisDirection),
        enum_check("submarket", E.Submarket),
        enum_check("status", E.ThesisStatus),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_thesis_scope", "dataset_kind", "as_of"),
        sa.Index("ix_thesis_lineage", "parent_id", "version"),
    )

    # ----------------------------------------------------------- assumption
    op.create_table(
        "assumption",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("thesis_id", ULID, _fk("thesis.id", "CASCADE"), nullable=False),
        sa.Column("kind", EnumText(E.AssumptionKind), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("metric_key", sa.String(80), nullable=True, index=True),
        sa.Column("expected_value", _obs(), nullable=True),
        sa.Column("tolerance_low", _obs(), nullable=True),
        sa.Column("tolerance_high", _obs(), nullable=True),
        sa.Column("unit", EnumText(E.Unit), nullable=True),
        # C3 / AC-02: premissa sem lastro nao entra.
        sa.Column("evidence_id", ULID, _fk("evidence.id", "RESTRICT"), nullable=False),
        sa.Column("criticality", EnumText(E.Criticality), nullable=False),
        sa.Column("status", EnumText(E.AssumptionStatus), nullable=False, index=True),
        sa.Column("last_checked_at", UTCDateTime(), nullable=True),
        enum_check("kind", E.AssumptionKind),
        enum_check("criticality", E.Criticality),
        enum_check("status", E.AssumptionStatus),
        enum_check("unit", E.Unit),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_assumption_scope", "dataset_kind", "as_of"),
    )

    # ------------------------------------------------------------- position
    op.create_table(
        "position",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("thesis_id", ULID, _fk("thesis.id", "CASCADE"), nullable=False),
        sa.Column("instrument", EnumText(E.Instrument), nullable=False),
        sa.Column("submarket", EnumText(E.Submarket), nullable=False),
        sa.Column("side", EnumText(E.Side), nullable=False),
        sa.Column("volume_mwh", _energy(), nullable=False),
        sa.Column("price_ref", _price(), nullable=False),
        sa.Column("delivery_start", sa.Date(), nullable=False),
        sa.Column("delivery_end", sa.Date(), nullable=False),
        sa.Column("notional", _money(), nullable=True),
        sa.Column("counterparty", sa.String(120), nullable=True),
        sa.Column("var_contribution", _money(), nullable=True),
        sa.Column("evidence_id", ULID, _fk("evidence.id", "RESTRICT"), nullable=False),
        enum_check("instrument", E.Instrument),
        enum_check("submarket", E.Submarket),
        enum_check("side", E.Side),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_position_scope", "dataset_kind", "as_of"),
    )

    # --------------------------------------------------------- trigger_rule
    op.create_table(
        "trigger_rule",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("thesis_id", ULID, _fk("thesis.id", "CASCADE"), nullable=False),
        sa.Column("rule_type", EnumText(E.RuleType), nullable=False, index=True),
        sa.Column("metric_key", sa.String(80), nullable=False, index=True),
        sa.Column("operator", EnumText(E.RuleOperator), nullable=False),
        sa.Column("threshold", _obs(), nullable=False),
        sa.Column("unit", EnumText(E.Unit), nullable=False),
        sa.Column("eval_window", sa.String(20), nullable=False),
        sa.Column("severity", EnumText(E.Severity), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        enum_check("rule_type", E.RuleType),
        enum_check("operator", E.RuleOperator),
        enum_check("severity", E.Severity),
        enum_check("unit", E.Unit),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_trigger_rule_scope", "dataset_kind", "as_of"),
        sa.Index("ix_trigger_rule_watch", "active", "metric_key"),
    )

    # ------------------------------------------------------------ risk_item
    op.create_table(
        "risk_item",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("thesis_id", ULID, _fk("thesis.id", "CASCADE"), nullable=False),
        sa.Column("category", EnumText(E.RiskCategory), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", EnumText(E.Severity), nullable=False),
        sa.Column("likelihood", EnumText(E.Likelihood), nullable=False),
        sa.Column("mitigation", sa.Text(), nullable=True),
        sa.Column("evidence_id", ULID, _fk("evidence.id", "SET NULL"), nullable=True),
        enum_check("category", E.RiskCategory),
        enum_check("severity", E.Severity),
        enum_check("likelihood", E.Likelihood),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_risk_item_scope", "dataset_kind", "as_of"),
    )

    # ------------------------------------------------------------- scenario
    op.create_table(
        "scenario",
        _id(),
        _created(),
        _dataset_kind(),
        sa.Column("name", sa.String(80), nullable=False, index=True),
        sa.Column("kind", EnumText(E.ScenarioKind), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("probability_weight", _percent(), nullable=True),
        sa.Column("source_evidence_id", ULID, _fk("evidence.id", "SET NULL"), nullable=True),
        sa.UniqueConstraint("name", "dataset_kind", name="uq_scenario_name_kind"),
        enum_check("kind", E.ScenarioKind),
        enum_check("dataset_kind", E.DatasetKind),
    )

    op.create_table(
        "scenario_result",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("thesis_id", ULID, _fk("thesis.id", "CASCADE"), nullable=False),
        sa.Column("scenario_id", ULID, _fk("scenario.id", "RESTRICT"), nullable=False),
        sa.Column("quant_run_id", ULID, _fk("quant_run.id", "RESTRICT"), nullable=False),
        sa.Column("pnl_p5", _money(), nullable=True),
        sa.Column("pnl_p50", _money(), nullable=True),
        sa.Column("pnl_p95", _money(), nullable=True),
        sa.Column("var_impact", _money(), nullable=True),
        sa.Column("thesis_delta", sa.Text(), nullable=True),
        sa.UniqueConstraint("thesis_id", "scenario_id", "as_of", name="uq_scenario_result_thesis"),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_scenario_result_scope", "dataset_kind", "as_of"),
    )

    # -------------------------------------------------------- debate_session
    op.create_table(
        "debate_session",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("thesis_id", ULID, _fk("thesis.id", "CASCADE"), nullable=False),
        sa.Column("thesis_version", sa.Integer(), nullable=False),
        sa.Column("run_id", ULID, nullable=False, index=True),
        sa.Column("verdict", EnumText(E.DebateVerdict), nullable=True, index=True),
        sa.Column(
            "weakest_assumption_id", ULID, _fk("assumption.id", "SET NULL"), nullable=True
        ),
        sa.Column(
            "breaking_scenario_id", ULID, _fk("scenario.id", "SET NULL"), nullable=True
        ),
        sa.Column("counter_argument", sa.Text(), nullable=True),
        sa.Column("confirmation_bias_score", _percent(), nullable=True),
        sa.Column("bias_rationale", sa.Text(), nullable=True),
        sa.Column("trader_response", sa.Text(), nullable=True),
        sa.Column("cost_usd", _money(), nullable=True),
        sa.Column("started_at", UTCDateTime(), nullable=True),
        sa.Column("ended_at", UTCDateTime(), nullable=True),
        enum_check("verdict", E.DebateVerdict),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_debate_session_scope", "dataset_kind", "as_of"),
        sa.Index("ix_debate_session_thesis", "thesis_id", "thesis_version"),
    )

    op.create_table(
        "debate_turn",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("session_id", ULID, _fk("debate_session.id", "CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("agent", EnumText(E.AgentName), nullable=False),
        sa.Column("role", EnumText(E.TurnRole), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tools_called_json", sa.JSON(), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=True),
        sa.Column("verifier_status", EnumText(E.ClaimStatus), nullable=True),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("prompt_version", sa.String(40), nullable=True),
        sa.Column("context_hash", sa.String(64), nullable=True),
        sa.UniqueConstraint("session_id", "seq", name="uq_debate_turn_seq"),
        enum_check("agent", E.AgentName),
        enum_check("role", E.TurnRole),
        enum_check("verifier_status", E.ClaimStatus),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_debate_turn_scope", "dataset_kind", "as_of"),
    )

    # --------------------------------------------------------- watchdog_run
    op.create_table(
        "watchdog_run",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column("started_at", UTCDateTime(), nullable=False),
        sa.Column("ended_at", UTCDateTime(), nullable=True),
        sa.Column("status", EnumText(E.WatchdogStatus), nullable=False, index=True),
        sa.Column("theses_checked", sa.Integer(), nullable=False),
        sa.Column("assumptions_checked", sa.Integer(), nullable=False),
        sa.Column("rules_evaluated", sa.Integer(), nullable=False),
        sa.Column("sources_ok", sa.JSON(), nullable=True),
        sa.Column("sources_failed", sa.JSON(), nullable=True),
        sa.Column("trigger_source", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        enum_check("status", E.WatchdogStatus),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_watchdog_run_scope", "dataset_kind", "as_of"),
    )

    # ---------------------------------------------------------------- alert
    op.create_table(
        "alert",
        _id(),
        _created(),
        _dataset_kind(),
        _as_of(),
        sa.Column(
            "watchdog_run_id", ULID, _fk("watchdog_run.id", "CASCADE"), nullable=True
        ),
        sa.Column("thesis_id", ULID, _fk("thesis.id", "CASCADE"), nullable=False),
        sa.Column("assumption_id", ULID, _fk("assumption.id", "SET NULL"), nullable=True),
        sa.Column(
            "trigger_rule_id", ULID, _fk("trigger_rule.id", "SET NULL"), nullable=True
        ),
        sa.Column("severity", EnumText(E.Severity), nullable=False, index=True),
        sa.Column("alert_kind", EnumText(E.AlertKind), nullable=False, index=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("observed_value", _obs(), nullable=True),
        sa.Column("expected_value", _obs(), nullable=True),
        sa.Column("delta", _obs(), nullable=True),
        sa.Column("unit", EnumText(E.Unit), nullable=True),
        # RF-33: todo alerta aponta o dado que o disparou.
        sa.Column("evidence_id", ULID, _fk("evidence.id", "RESTRICT"), nullable=False),
        sa.Column("dedup_key", sa.String(120), nullable=True, index=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("acknowledged_by", sa.String(120), nullable=True),
        sa.Column("acknowledged_at", UTCDateTime(), nullable=True),
        sa.Column("decision", EnumText(E.AlertDecision), nullable=True),
        sa.Column("decision_rationale", sa.Text(), nullable=True),
        enum_check("severity", E.Severity),
        enum_check("alert_kind", E.AlertKind),
        enum_check("decision", E.AlertDecision),
        enum_check("unit", E.Unit),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_alert_scope", "dataset_kind", "as_of"),
        sa.Index("ix_alert_open", "thesis_id", "severity", "acknowledged_at"),
    )

    # ---------------------------------------------------------------- claim
    op.create_table(
        "claim",
        _id(),
        _created(),
        _dataset_kind(),
        sa.Column("turn_id", ULID, _fk("debate_turn.id", "CASCADE"), nullable=True),
        sa.Column("alert_id", ULID, _fk("alert.id", "CASCADE"), nullable=True),
        sa.Column("thesis_id", ULID, _fk("thesis.id", "CASCADE"), nullable=True, index=True),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", EnumText(E.ClaimType), nullable=False),
        sa.Column("value_numeric", _obs(), nullable=True),
        sa.Column("unit", EnumText(E.Unit), nullable=True),
        sa.Column("evidence_id", ULID, _fk("evidence.id", "SET NULL"), nullable=True),
        sa.Column("status", EnumText(E.ClaimStatus), nullable=False, index=True),
        sa.Column("tolerance_applied", _obs(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        enum_check("claim_type", E.ClaimType),
        enum_check("status", E.ClaimStatus),
        enum_check("unit", E.Unit),
        enum_check("dataset_kind", E.DatasetKind),
        sa.Index("ix_claim_blocking", "thesis_id", "status"),
    )

    # ------------------------------------------------------------ audit_log
    op.create_table(
        "audit_log",
        _id(),
        _created(),
        sa.Column("actor_type", EnumText(E.ActorType), nullable=False),
        sa.Column("actor", sa.String(160), nullable=False),
        sa.Column("agent_version", sa.String(40), nullable=True),
        sa.Column("action", EnumText(E.AuditAction), nullable=False, index=True),
        sa.Column("entity", sa.String(80), nullable=False, index=True),
        sa.Column("entity_id", ULID, nullable=True, index=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("run_id", ULID, nullable=True, index=True),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("prompt_version", sa.String(40), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=True, index=True),
        sa.Column("note", sa.Text(), nullable=True),
        enum_check("actor_type", E.ActorType),
        enum_check("action", E.AuditAction),
        sa.Index("ix_audit_log_entity_pair", "entity", "entity_id"),
    )

    _create_audit_guards()


def _create_audit_guards() -> None:
    """Triggers append-only na trilha de auditoria (C7 / AC-61)."""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log "
            "BEGIN SELECT RAISE(ABORT, 'audit_log e append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log "
            "BEGIN SELECT RAISE(ABORT, 'audit_log e append-only'); END"
        )
    elif dialect == "postgresql":
        op.execute(
            "CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'audit_log e append-only'; END; "
            "$$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log "
            "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()"
        )
        op.execute(
            "CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log "
            "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()"
        )


def _drop_audit_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log")
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log")
        op.execute("DROP FUNCTION IF EXISTS audit_log_append_only()")


# ------------------------------------------------------------------- downgrade
def downgrade() -> None:
    _drop_audit_guards()
    for table in (
        "audit_log",
        "claim",
        "alert",
        "watchdog_run",
        "debate_turn",
        "debate_session",
        "scenario_result",
        "scenario",
        "risk_item",
        "trigger_rule",
        "position",
        "assumption",
        "thesis",
        "document_chunk",
        "document",
        "forward_curve_point",
        "forward_curve",
        "market_observation",
        "market_series",
        "evidence",
        "quant_run",
        "sql_execution",
        "source",
    ):
        op.drop_table(table)
