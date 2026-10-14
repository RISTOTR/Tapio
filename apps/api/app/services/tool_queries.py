"""Read-only projections and existing deterministic-service composition for typed tools."""

import re
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text

from apps.api.app.core.database import SessionLocal
from apps.api.app.domain.models import (
    Document,
    EnergyReading,
    ForestrySale,
    Invoice,
    Transaction,
    TransactionInvoiceAllocation,
    TransactionLabelReview,
)
from data_pipeline.energy_cost.engine import calculate
from data_pipeline.energy_cost.scenarios import SupplierScenario, compare
from data_pipeline.energy_cost.sources import load
from data_pipeline.energy_cost.spot import read_spot
from data_pipeline.energy_cost.types import Reading, boundaries, validate_readings
from data_pipeline.reconcile.invoices import state
from tapio.tools import schemas as S
from tapio.tools.errors import ErrorCode, ToolFailure


def project(model, values):
    return model.model_validate({k: values[k] for k in model.model_fields if k in values})


def safe_name(value):
    if value is None:
        return None
    return re.sub(r"\b[A-Z]{2}\d{2}(?:\s?\d){10,30}\b", "[bank identifier removed]", value)[:200]


class Queries:
    def __init__(
        self,
        session_factory=SessionLocal,
        spot_path=Path("data/processed/energy_cost/spot/fi_hourly.csv"),
    ):
        self.session_factory = session_factory
        self.spot_path = Path(spot_path)

    @contextmanager
    def session(self):
        with self.session_factory() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout = '20000ms'"))
            yield session

    @staticmethod
    def dated(query, column, args):
        if args.date_from:
            query = query.where(column >= args.date_from)
        if args.date_to:
            query = query.where(column <= args.date_to)
        return query

    def transactions(self, args):
        t, r = Transaction, TransactionLabelReview
        q = select(t, r).outerjoin(r, (r.transaction_id == t.id) & (r.review_status == "REVIEWED"))
        q = self.dated(q, t.booking_date, args)
        for value, column in [
            (args.category, r.confirmed_category),
            (args.business_context, r.confirmed_business_context),
            (args.direction, t.direction),
        ]:
            if value is not None:
                q = q.where(column == value)
        if args.counterparty:
            q = q.where(t.normalized_counterparty.icontains(args.counterparty, autoescape=True))
        with self.session() as session:
            rows = session.execute(q.order_by(t.booking_date, t.id).limit(args.limit + 1)).all()
            items = [
                S.TransactionSummary(
                    id=t.id,
                    booking_date=t.booking_date,
                    amount=t.amount,
                    currency=t.currency,
                    direction=t.direction,
                    counterparty=safe_name(t.normalized_counterparty),
                    category=r.confirmed_category if r else None,
                    business_context=r.confirmed_business_context if r else None,
                    label_authority="HUMAN_REVIEWED" if r else "UNREVIEWED",
                )
                for t, r in rows[: args.limit]
            ]
            return S.Page[S.TransactionSummary](items=items, truncated=len(rows) > args.limit)

    def energy(self, args):
        with self.session() as session:
            ids = list(session.scalars(select(EnergyReading.metering_point_id).distinct()))
            if len(ids) != 1:
                raise ToolFailure(ErrorCode.INCOMPLETE_COVERAGE)
            start, end = boundaries(args.date_from, args.date_to)
            stored = session.scalars(
                select(EnergyReading).where(
                    EnergyReading.metering_point_id == ids[0],
                    EnergyReading.source_grain == "hourly",
                    EnergyReading.timestamp >= start,
                    EnergyReading.timestamp < end,
                )
            )
            rows = [
                Reading(
                    timestamp=r.timestamp,
                    consumption_kwh=r.consumption_kwh,
                    solar_export_kwh=r.solar_export_kwh,
                )
                for r in stored
            ]
            validate_readings(rows, args.date_from, args.date_to)
            return S.EnergySummary(
                date_from=args.date_from,
                date_to=args.date_to,
                metric=args.metric,
                total=sum((getattr(r, args.metric) for r in rows), Decimal(0)),
                hours=len(rows),
                coverage="COMPLETE",
            )

    @staticmethod
    def cost_summary(result):
        values = {
            **result,
            "monthly": [project(S.MonthlyCost, m) for m in result["monthly"]],
            "provenance": [project(S.PriceProvenance, p) for p in result["provenance"]],
        }
        return project(S.CostSummary, values)

    def cost(self, args):
        with self.session() as session:
            rows, tariffs, _ = load(session, args.date_from, args.date_to)
            return self.cost_summary(
                calculate(rows, tariffs, args.date_from, args.date_to, args.scope)
            )

    def scenario(self, args):
        with self.session() as session:
            rows, tariffs, _ = load(session, args.date_from, args.date_to)
            spot = read_spot(self.spot_path) if args.use_cached_spot else None
            export = read_spot(self.spot_path) if args.use_cached_export_spot else None
            supplier = SupplierScenario(args.scenario, spot, export)
            if args.compare_fixed:
                fixed = SupplierScenario(args.compare_fixed, export_spot=export)
                result = compare(
                    rows, tariffs, args.date_from, args.date_to, fixed, supplier, args.scope
                )
                return S.ScenarioSummary(
                    mode="SCENARIO_COMPARISON",
                    result=self.cost_summary(result["spot"]),
                    fixed=self.cost_summary(result["fixed"]),
                    fixed_minus_spot_eur=result["fixed_minus_spot_eur"],
                    difference_percent_of_fixed=result["difference_percent_of_fixed"],
                    break_even_fixed_price_cents_per_kwh=result[
                        "break_even_fixed_price_cents_per_kwh"
                    ],
                    winner=result["winner"],
                    assumptions=args.scenario,
                )
            result = calculate(rows, tariffs, args.date_from, args.date_to, args.scope, supplier)
            return S.ScenarioSummary(
                mode="SCENARIO", result=self.cost_summary(result), assumptions=args.scenario
            )

    @staticmethod
    def document(row):
        m = row.document_metadata
        return S.DocumentSummary(
            id=row.id,
            document_type=row.document_type,
            document_date=row.document_date,
            vendor=safe_name(m.get("vendor")),
            kind=m.get("kind"),
            parser_version=m.get("parser_version"),
            sha256=row.sha256,
        )

    def documents(self, args):
        q = self.dated(select(Document), Document.document_date, args)
        if args.document_type:
            q = q.where(Document.document_type == args.document_type)
        if args.vendor:
            q = q.where(
                Document.document_metadata["vendor"].astext.icontains(args.vendor, autoescape=True)
            )
        with self.session() as s:
            rows = list(
                s.scalars(q.order_by(Document.document_date, Document.id).limit(args.limit + 1))
            )
            return S.Page[S.DocumentSummary](
                items=[self.document(d) for d in rows[: args.limit]],
                truncated=len(rows) > args.limit,
            )

    def document_summary(self, args):
        with self.session() as s:
            row = s.get(Document, args.document_id)
            if row is None:
                raise ToolFailure(ErrorCode.NOT_FOUND)
            return self.document(row)

    @staticmethod
    def reconciliation(s, invoice):
        if invoice.total_eur is None:
            raise ToolFailure(ErrorCode.INCOMPLETE_COVERAGE)
        rows = s.scalars(
            select(TransactionInvoiceAllocation).where(
                TransactionInvoiceAllocation.invoice_id == invoice.id
            )
        )
        result = state(
            invoice.total_eur, [dict(amount=a.allocated_amount_eur, status=a.status) for a in rows]
        )
        return S.ReconciliationSummary(
            invoice_id=invoice.id, **result, human_review_required=result["state"] == "AMBIGUOUS"
        )

    def invoice_summary(self, s, row):
        doc = s.get(Document, row.document_id)
        return S.InvoiceSummary(
            id=row.id,
            source_document_id=row.document_id,
            parser_version=doc.document_metadata.get("parser_version"),
            vendor=safe_name(row.vendor),
            invoice_number=row.invoice_number,
            invoice_date=row.invoice_date,
            total_eur=row.total_eur,
            subtotal_eur=row.subtotal_eur,
            vat_eur=row.vat_eur,
            reconciliation=self.reconciliation(s, row),
        )

    def invoice(self, args):
        with self.session() as s:
            row = s.get(Invoice, args.invoice_id)
            if row is None:
                raise ToolFailure(ErrorCode.NOT_FOUND)
            return self.invoice_summary(s, row)

    def invoice_reconciliation(self, args):
        return self.invoice(args).reconciliation

    def invoices(self, args):
        q = self.dated(select(Invoice), Invoice.invoice_date, args)
        if args.vendor:
            q = q.where(Invoice.vendor.icontains(args.vendor, autoescape=True))
        if args.invoice_number:
            q = q.where(Invoice.invoice_number == args.invoice_number)
        with self.session() as s:
            rows = list(s.scalars(q.order_by(Invoice.invoice_date, Invoice.id).limit(201)))
            items = [self.invoice_summary(s, r) for r in rows[:200]]
            if args.status:
                items = [r for r in items if r.reconciliation.state == args.status]
            return S.Page[S.InvoiceSummary](
                items=items[: args.limit], truncated=len(rows) > 200 or len(items) > args.limit
            )

    @staticmethod
    def sale(s, row):
        doc = s.get(Document, row.document_id)
        return S.ForestrySummary(
            id=row.id,
            source_document_id=row.document_id,
            parser_version=doc.document_metadata.get("parser_version"),
            buyer=safe_name(row.buyer),
            sale_date=row.sale_date,
            actual_volume_m3=row.actual_volume_m3,
            actual_value_eur=row.actual_value_eur,
            estimated_volume_m3=row.estimated_volume_m3,
            estimated_value_eur=row.estimated_value_eur,
        )

    def forestry_sale(self, args):
        with self.session() as s:
            row = s.get(ForestrySale, args.sale_id)
            if row is None:
                raise ToolFailure(ErrorCode.NOT_FOUND)
            return self.sale(s, row)

    def forestry_sales(self, args):
        q = self.dated(select(ForestrySale), ForestrySale.sale_date, args)
        if args.buyer:
            q = q.where(ForestrySale.buyer.icontains(args.buyer, autoescape=True))
        with self.session() as s:
            rows = list(
                s.scalars(q.order_by(ForestrySale.sale_date, ForestrySale.id).limit(args.limit + 1))
            )
            return S.Page[S.ForestrySummary](
                items=[self.sale(s, r) for r in rows[: args.limit]],
                truncated=len(rows) > args.limit,
            )
