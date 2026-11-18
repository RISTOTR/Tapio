"""Focused current-review retrieval checks in the existing isolated SQL fixture."""

from decimal import Decimal
from uuid import uuid4

from apps.api.app.domain.models import Document, Invoice, Transaction, TransactionInvoiceAllocation
from apps.api.app.services.tool_queries import Queries
from apps.api.tests.test_confirmation_workflow import apply
from apps.api.tests.test_confirmation_workflow import setup as setup
from apps.api.tests.test_energy_load import factory as factory
from tapio.confirmation.projection import current_classified_transactions
from tapio.pilot.planned_retrieval import transactions
from tapio.pilot.query_plan import QueryPlan, period
from tapio.tools.schemas import InvoiceID


def test_latest_correction_reaches_transaction_and_invoice_views(setup, factory):
    service, card, _ = setup
    txid = card["transaction"]["id"]
    apply(
        service,
        card,
        action="CHANGE",
        fields={"context": "PERSONAL", "category": "TRAVEL"},
        reason="Synthetic initial classification",
    )
    with factory() as db:
        tx = db.get(Transaction, txid)
        doc = Document(
            id=uuid4(),
            document_type="invoice",
            source_filename="synthetic.pdf",
            sha256="a" * 64,
            import_run_id=tx.import_run_id,
            document_metadata={},
        )
        inv = Invoice(
            id=uuid4(),
            document_id=doc.id,
            vendor="Synthetic vendor",
            invoice_number="test",
            invoice_date=tx.booking_date,
            total_eur=Decimal("123.45"),
        )
        db.add(doc)
        db.flush()
        db.add(inv)
        db.flush()
        db.add(
            TransactionInvoiceAllocation(
                transaction_id=tx.id,
                invoice_id=inv.id,
                status="CONFIRMED",
                allocated_amount_eur=Decimal("123.45"),
                match_method="synthetic",
            )
        )
        db.commit()
        iid = inv.id
        year = tx.booking_date.year
    q = Queries(session_factory=factory)
    assert q.invoice(InvoiceID(invoice_id=iid)).confirmed_payment_human_contexts == ["PERSONAL"]
    apply(
        service,
        card,
        action="CHANGE",
        fields={"context": "FORESTRY"},
        reason="Synthetic correction",
    )
    assert q.invoice(InvoiceID(invoice_id=iid)).confirmed_payment_human_contexts == ["FORESTRY"]
    p = QueryPlan(
        intent="TRANSACTION_SEARCH",
        contexts=["FORESTRY"],
        categories=["TRAVEL"],
        periods=[period(year)],
        action="TAX_SUGGESTION",
    )
    with factory() as db:
        rows, _ = transactions(db, p)
        selected = next(r for r in rows if r["transaction_id"] == txid)
        assert selected["business_context"] == "FORESTRY"
        assert selected["supporting_evidence"][0]["link_status"] == "CONFIRMED"
        pairs = current_classified_transactions(db, [], transaction_ids=[txid])
        assert pairs[0][1].confirmed_category == "TRAVEL"
