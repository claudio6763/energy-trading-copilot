"""Repositorios de fontes, series, observacoes, curva forward e acervo documental."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import select

from copilot.common.enums import (
    AuditAction,
    Confidence,
    CurvePriceType,
    DocType,
    EvidenceSourceType,
    LicenseClass,
    ProductClass,
    QuantFunction,
    SourceKind,
    Submarket,
    Unit,
)
from copilot.common.errors import MissingEvidenceError
from copilot.db.models import (
    Document,
    DocumentChunk,
    Evidence,
    ForwardCurve,
    ForwardCurvePoint,
    MarketObservation,
    MarketSeries,
    QuantRun,
    Source,
    SqlExecution,
)
from copilot.db.repositories.base import BaseRepository
from copilot.ingest.policy import assert_ingestable, effective_authorization


def content_hash(text: str) -> str:
    """SHA-256 do conteudo citado — detecta mudanca silenciosa da fonte."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SourceRepository(BaseRepository[Source]):
    model = Source
    entity_name = "source"

    def register(
        self,
        *,
        name: str,
        source_kind: SourceKind,
        license_class: LicenseClass,
        publisher: str | None = None,
        url: str | None = None,
        authorized: bool = False,
        authorization_ref: str | None = None,
        update_frequency: str | None = None,
        notes: str | None = None,
    ) -> Source:
        """Cadastra uma fonte. Licenca incompativel e rejeitada aqui (P10)."""
        assert_ingestable(
            license_class, authorized, subject=name, authorization_ref=authorization_ref
        )
        source = Source(
            name=name,
            publisher=publisher,
            url=url,
            source_kind=source_kind,
            license_class=license_class,
            authorized=effective_authorization(license_class, authorized),
            authorization_ref=authorization_ref,
            update_frequency=update_frequency,
            notes=notes,
        )
        return self.add(source, action=AuditAction.INGEST)

    def by_name(self, name: str) -> Source | None:
        return self.session.execute(
            self.scoped().where(Source.name == name)
        ).scalars().first()


class EvidenceRepository(BaseRepository[Evidence]):
    model = Evidence
    entity_name = "evidence"

    def create(
        self,
        *,
        source_type: EvidenceSourceType,
        excerpt: str,
        license_class: LicenseClass,
        source_id: str | None = None,
        locator: str | None = None,
        value_numeric: Decimal | None = None,
        unit: Unit | None = None,
        confidence: Confidence = Confidence.MEDIUM,
        as_of: date | None = None,
        note: str | None = None,
    ) -> Evidence:
        """Cria a evidencia. Todo numero do sistema nasce a partir de uma destas."""
        if not excerpt or not excerpt.strip():
            raise MissingEvidenceError(
                "evidence.excerpt e obrigatorio: sem trecho citado nao ha lastro (P6)."
            )
        assert_ingestable(license_class, True, subject="evidencia")
        evidence = Evidence(
            source_type=source_type,
            source_id=source_id,
            locator=locator,
            excerpt=excerpt,
            value_numeric=value_numeric,
            unit=unit,
            content_hash=content_hash(excerpt),
            license_class=license_class,
            confidence=confidence,
            as_of=as_of,
            note=note,
        )
        return self.add(evidence)

    def require(self, evidence_id: str | None, *, field: str) -> str:
        """Valida que o `evidence_id` existe no escopo. Usado por AC-02."""
        if not evidence_id:
            raise MissingEvidenceError(
                f"{field} exige `evidence_id`: afirmacao factual sem lastro nao e "
                "persistida (P6 / AC-02)."
            )
        if self.get(evidence_id) is None:
            raise MissingEvidenceError(
                f"{field} referencia evidence_id {evidence_id!r} inexistente no escopo "
                f"{self.ctx.dataset_kind.value} / as_of<={self.ctx.as_of.isoformat()}."
            )
        return evidence_id


class MarketSeriesRepository(BaseRepository[MarketSeries]):
    model = MarketSeries
    entity_name = "market_series"

    def register(
        self,
        *,
        metric_key: str,
        description: str,
        unit: Unit,
        frequency: str,
        source: Source,
        submarket: Submarket | None = None,
        model_run: str | None = None,
        ensemble_member: str | None = None,
    ) -> MarketSeries:
        assert_ingestable(source.license_class, source.authorized, subject=source.name)
        series = MarketSeries(
            metric_key=metric_key,
            description=description,
            unit=unit,
            frequency=frequency,
            submarket=submarket,
            source_id=source.id,
            license_class=source.license_class,
            model_run=model_run,
            ensemble_member=ensemble_member,
        )
        return self.add(series, action=AuditAction.INGEST)

    def by_metric_key(self, metric_key: str) -> list[MarketSeries]:
        """Todas as variantes (rodadas/ensembles) de uma metrica.

        Devolve a lista inteira de proposito: divergencia entre modelos nao e
        reduzida a media (DATA_CONTRACT secao 6).
        """
        return list(
            self.session.execute(
                self.scoped().where(MarketSeries.metric_key == metric_key)
            ).scalars()
        )


class MarketObservationRepository(BaseRepository[MarketObservation]):
    model = MarketObservation
    entity_name = "market_observation"

    def record(
        self,
        *,
        series: MarketSeries,
        ref_date: date,
        value: Decimal,
        evidence_id: str,
        as_of: date | None = None,
        revision: int = 0,
    ) -> MarketObservation:
        if not evidence_id:
            raise MissingEvidenceError(
                "market_observation exige `evidence_id` (C3 / P6)."
            )
        observation = MarketObservation(
            series_id=series.id,
            ref_date=ref_date,
            value=value,
            revision=revision,
            evidence_id=evidence_id,
            as_of=as_of,
        )
        return self.add(observation, action=AuditAction.INGEST, evidence_ids=[evidence_id])

    def latest(self, metric_key: str, *, ref_date: date | None = None) -> MarketObservation | None:
        """Ultima observacao conhecida ate o `as_of` do contexto (RF-58 / AC-55)."""
        stmt = (
            self.scoped()
            .join(MarketSeries, MarketSeries.id == MarketObservation.series_id)
            .where(MarketSeries.metric_key == metric_key)
        )
        if ref_date is not None:
            stmt = stmt.where(MarketObservation.ref_date == ref_date)
        stmt = stmt.order_by(
            MarketObservation.ref_date.desc(),
            MarketObservation.as_of.desc(),
            MarketObservation.revision.desc(),
        ).limit(1)
        return self.session.execute(stmt).scalars().first()

    def series_history(self, metric_key: str, *, limit: int = 500) -> list[MarketObservation]:
        stmt = (
            self.scoped()
            .join(MarketSeries, MarketSeries.id == MarketObservation.series_id)
            .where(MarketSeries.metric_key == metric_key)
            .order_by(MarketObservation.ref_date.asc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())


class ForwardCurveRepository(BaseRepository[ForwardCurve]):
    model = ForwardCurve
    entity_name = "forward_curve"

    def create(
        self,
        *,
        curve_name: str,
        submarket: Submarket,
        product_class: ProductClass,
        source: Source,
        evidence_id: str,
        price_type: CurvePriceType = CurvePriceType.MID,
        as_of: date | None = None,
        currency: str = "BRL",
        notes: str | None = None,
    ) -> ForwardCurve:
        assert_ingestable(source.license_class, source.authorized, subject=source.name)
        if not evidence_id:
            raise MissingEvidenceError("forward_curve exige `evidence_id` (C3).")
        curve = ForwardCurve(
            curve_name=curve_name,
            submarket=submarket,
            product_class=product_class,
            price_type=price_type,
            source_id=source.id,
            license_class=source.license_class,
            currency=currency,
            evidence_id=evidence_id,
            as_of=as_of,
            notes=notes,
        )
        return self.add(curve, action=AuditAction.INGEST, evidence_ids=[evidence_id])

    def add_point(
        self,
        curve: ForwardCurve,
        *,
        tenor_label: str,
        delivery_start: date,
        delivery_end: date,
        price: Decimal,
        evidence_id: str,
    ) -> ForwardCurvePoint:
        if not evidence_id:
            raise MissingEvidenceError("forward_curve_point exige `evidence_id` (C3).")
        point = ForwardCurvePoint(
            curve_id=curve.id,
            tenor_label=tenor_label,
            delivery_start=delivery_start,
            delivery_end=delivery_end,
            price=price,
            evidence_id=evidence_id,
            as_of=curve.as_of,
        )
        repo = ForwardCurvePointRepository(self.session)
        return repo.add(point, action=AuditAction.INGEST, evidence_ids=[evidence_id])

    def latest(
        self,
        *,
        curve_name: str | None = None,
        submarket: Submarket | None = None,
        product_class: ProductClass | None = None,
    ) -> ForwardCurve | None:
        stmt = self.scoped()
        if curve_name is not None:
            stmt = stmt.where(ForwardCurve.curve_name == curve_name)
        if submarket is not None:
            stmt = stmt.where(ForwardCurve.submarket == submarket)
        if product_class is not None:
            stmt = stmt.where(ForwardCurve.product_class == product_class)
        stmt = stmt.order_by(ForwardCurve.as_of.desc()).limit(1)
        return self.session.execute(stmt).scalars().first()


class ForwardCurvePointRepository(BaseRepository[ForwardCurvePoint]):
    model = ForwardCurvePoint
    entity_name = "forward_curve_point"


class DocumentRepository(BaseRepository[Document]):
    model = Document
    entity_name = "document"

    def ingest(
        self,
        *,
        source: Source,
        title: str,
        doc_type: DocType,
        license_class: LicenseClass | None = None,
        publisher: str | None = None,
        published_at: date | None = None,
        effective_from: date | None = None,
        effective_to: date | None = None,
        url: str | None = None,
        file_hash: str | None = None,
        authorized: bool = True,
        as_of: date | None = None,
    ) -> Document:
        """Grava o documento. Licenca incompativel e rejeitada antes da gravacao."""
        license_class = license_class or source.license_class
        assert_ingestable(license_class, authorized, subject=title)
        document = Document(
            source_id=source.id,
            title=title,
            doc_type=doc_type,
            publisher=publisher,
            published_at=published_at,
            effective_from=effective_from,
            effective_to=effective_to,
            url=url,
            file_hash=file_hash,
            license_class=license_class,
            authorized=effective_authorization(license_class, authorized),
            as_of=as_of,
        )
        return self.add(document, action=AuditAction.INGEST)

    def add_chunk(
        self,
        document: Document,
        *,
        chunk_index: int,
        text: str,
        page: int | None = None,
        section: str | None = None,
        token_count: int | None = None,
    ) -> DocumentChunk:
        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=chunk_index,
            text=text,
            page=page,
            section=section,
            token_count=token_count,
        )
        return DocumentChunkRepository(self.session).add(chunk, audit=False)

    def effective_at(self, reference: date | None = None) -> list[Document]:
        """Documentos vigentes na data-base (filtro de vigencia da recuperacao RAG)."""
        reference = reference or self.ctx.as_of
        stmt = self.scoped().where(
            (Document.effective_from.is_(None)) | (Document.effective_from <= reference)
        )
        return list(self.session.execute(stmt).scalars())


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    model = DocumentChunk
    entity_name = "document_chunk"


class SqlExecutionRepository(BaseRepository[SqlExecution]):
    model = SqlExecution
    entity_name = "sql_execution"

    def record(
        self,
        *,
        sql_text: str,
        params: dict[str, Any] | None = None,
        template_name: str | None = None,
        row_count: int | None = None,
        duration_ms: int | None = None,
        as_of_applied: bool = True,
    ) -> SqlExecution:
        execution = SqlExecution(
            sql_text=sql_text,
            sql_hash=content_hash(sql_text),
            params_json=params,
            template_name=template_name,
            row_count=row_count,
            duration_ms=duration_ms,
            as_of_applied=as_of_applied,
        )
        return self.add(execution, audit=False)


class QuantRunRepository(BaseRepository[QuantRun]):
    model = QuantRun
    entity_name = "quant_run"

    def record(
        self,
        *,
        function: QuantFunction,
        inputs: dict[str, Any],
        outputs: dict[str, Any] | None = None,
        seed: int | None = None,
        code_version: str | None = None,
        duration_ms: int | None = None,
    ) -> QuantRun:
        from copilot import CODE_VERSION

        payload = repr(sorted(inputs.items()))
        run = QuantRun(
            function=function,
            inputs_json=inputs,
            inputs_hash=content_hash(payload),
            outputs_json=outputs,
            seed=seed,
            code_version=code_version or CODE_VERSION,
            duration_ms=duration_ms,
        )
        return self.add(run, action=AuditAction.QUANT_RUN)

    def find_reproducible(
        self, *, inputs_hash: str, code_version: str, seed: int | None
    ) -> QuantRun | None:
        """Execucao anterior com as mesmas entradas — base do teste AC-40."""
        stmt = self.scoped().where(
            QuantRun.inputs_hash == inputs_hash,
            QuantRun.code_version == code_version,
            QuantRun.seed.is_(seed) if seed is None else QuantRun.seed == seed,
        )
        return self.session.execute(stmt).scalars().first()


__all__ = [
    "DocumentChunkRepository",
    "DocumentRepository",
    "EvidenceRepository",
    "ForwardCurvePointRepository",
    "ForwardCurveRepository",
    "MarketObservationRepository",
    "MarketSeriesRepository",
    "QuantRunRepository",
    "SourceRepository",
    "SqlExecutionRepository",
    "content_hash",
]
