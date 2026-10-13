"""Synthetic many-to-many, duplicate-payment and ambiguous-refund acceptance tests."""

import copy
import os
import subprocess
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.domain.enums import DocumentType, ImportStatus, TransactionDirection
from apps.api.app.domain.models import (
    Document,
    ImportRun,
    Invoice,
    Transaction,
    TransactionInvoiceAllocation,
    TransactionReversalCandidate,
)
from apps.api.tests.test_energy_load import factory as factory
from data_pipeline.ingest.bank_csv import SOURCE_TYPE
from data_pipeline.reconcile.invoices import candidates, reconcile, state


def invoice(id="invoice", total="100", reference="9001"):
    return {
        "id": id,
        "vendor": "Vattenfall Oy",
        "total": Decimal(total),
        "due": date(2026, 2, 15),
        "reference": reference,
    }


def transaction(
    id="debit", amount="-100", reference="9001", days=0, vendor="Vattenfall Oy", namespace="test"
):
    return {
        "id": id,
        "vendor": vendor,
        "amount": Decimal(amount),
        "date": date(2026, 2, 15) + timedelta(days=days),
        "reference": reference,
        "currency": "EUR",
        "namespace": namespace,
    }


def test_exact_reference_supported_match():
    rows, _ = candidates([invoice()], [transaction()])
    assert len(rows) == 1 and rows[0]["auto_confirm_eligible"]
    assert rows[0]["evidence"]["score_components"] == {
        "vendor": 40,
        "amount": 30,
        "reference": 50,
        "date": 10,
    }


def test_exact_vendor_amount_without_invoice_reference():
    rows, _ = candidates([invoice(reference=None)], [transaction(reference=None)])
    assert rows[0]["auto_confirm_eligible"]


@pytest.mark.parametrize(
    "change",
    [
        {"vendor": "Unrelated Vendor"},
        {"currency": "USD"},
        {"date": date(2020, 1, 1)},
        {"amount": Decimal("100")},
    ],
)
def test_amount_alone_wrong_direction_currency_or_date_insufficient(change):
    rows, _ = candidates([invoice()], [{**transaction(), **change}])
    assert rows == []


@pytest.mark.parametrize("ref", [None, "different"])
def test_missing_or_conflicting_reference_blocks_confirmation(ref):
    rows, _ = candidates([invoice()], [transaction(reference=ref)])
    assert len(rows) == 1 and not rows[0]["auto_confirm_eligible"]


def test_competing_invoice_retains_both_candidates():
    rows, _ = candidates([invoice("a"), invoice("b")], [transaction()])
    assert len(rows) == 2 and not any(r["auto_confirm_eligible"] for r in rows)


def test_one_invoice_multiple_partial_payments():
    rows, _ = candidates([invoice()], [transaction("a", "-40"), transaction("b", "-60")])
    assert [r["amount"] for r in rows] == [Decimal(40), Decimal(60)]
    assert not any(r["auto_confirm_eligible"] for r in rows)
    assert (
        state(Decimal(100), [{"amount": r["amount"], "status": "CONFIRMED"} for r in rows])["state"]
        == "PAID"
    )


def test_bulk_payment_multiple_invoices_candidate_only():
    rows, _ = candidates([invoice("a", "40"), invoice("b", "60")], [transaction()])
    assert sum(r["amount"] for r in rows) == 100
    assert not any(r["auto_confirm_eligible"] for r in rows)


def test_duplicate_refund_keeps_both_reversal_possibilities():
    invoices = [invoice(total="588.07")]
    txs = [
        transaction("a", "-588.07"),
        transaction("b", "-588.07", days=2),
        transaction("refund", "588.07", days=14, reference=None),
    ]
    before = copy.deepcopy(txs)
    rows, reversals = candidates(invoices, txs)
    assert len(rows) == 3 and len(reversals) == 2
    assert {r["debit_id"] for r in reversals} == {"a", "b"}
    assert {r["credit_id"] for r in reversals} == {"refund"}
    assert rows[-1]["evidence"]["refund_link_ambiguous"]
    assert sum(r["amount"] for r in rows) == Decimal("588.07")
    assert not any(r["auto_confirm_eligible"] for r in rows)
    assert txs == before
    assert (
        state(Decimal("588.07"), [{"amount": r["amount"], "status": "CANDIDATE"} for r in rows])[
            "state"
        ]
        == "AMBIGUOUS"
    )


def test_refund_cannot_cross_account_or_precede_payment():
    for refund in [
        transaction("r", "100", days=2, namespace="other"),
        transaction("r", "100", days=-2),
    ]:
        rows, pairs = candidates([invoice()], [transaction(), refund])
        assert len(rows) == 1 and pairs == []


@pytest.mark.parametrize(
    "amounts,status",
    [
        ([], "UNMATCHED"),
        (["40"], "PARTIALLY_PAID"),
        (["100"], "PAID"),
        (["100", "100"], "OVERPAID"),
        (["100", "-100"], "REFUNDED"),
        (["100", "100", "-100"], "PAID"),
    ],
)
def test_computed_states(amounts, status):
    assert (
        state(Decimal(100), [{"amount": Decimal(a), "status": "CONFIRMED"} for a in amounts])[
            "state"
        ]
        == status
    )


def test_rejected_candidates_do_not_count():
    assert (
        state(Decimal(100), [{"amount": Decimal(100), "status": "REJECTED"}])["state"]
        == "UNMATCHED"
    )


def test_decimal_partial_sum_exact():
    result = state(
        Decimal(".30"), [{"amount": Decimal(v), "status": "CONFIRMED"} for v in (".1", ".2")]
    )
    assert result["state"] == "PAID" and Decimal(result["confirmed_net_eur"]) == Decimal(".30")


def seed(factory, duplicate=False):
    account = uuid4().hex
    with factory() as session, session.begin():
        run = ImportRun(
            source_type="synthetic",
            source_filename="synthetic.pdf",
            sha256=account.ljust(64, "0"),
            parser_version="synthetic",
            status=ImportStatus.COMPLETED,
        )
        session.add(run)
        session.flush()
        doc = Document(
            document_type=DocumentType.INVOICE,
            source_filename="synthetic.pdf",
            sha256=account.ljust(64, "0"),
            import_run_id=run.id,
            document_metadata={"bill": {"reference": account}},
        )
        session.add(doc)
        session.flush()
        inv = Invoice(
            document_id=doc.id,
            vendor="Synthetic " + account,
            invoice_number=account,
            invoice_date=date(2026, 2, 1),
            due_date=date(2026, 2, 15),
            total_eur=Decimal("588.07"),
        )
        session.add(inv)
        txs = []
        for i, amount in enumerate(["-588.07", "-588.07", "588.07"] if duplicate else ["-588.07"]):
            tx = Transaction(
                booking_date=date(2026, 2, 15) + timedelta(days=i),
                amount=Decimal(amount),
                currency="EUR",
                direction=TransactionDirection.INCOMING
                if Decimal(amount) > 0
                else TransactionDirection.OUTGOING,
                normalized_counterparty=inv.vendor,
                reference=account,
                source_namespace=f"{SOURCE_TYPE}:{account}",
                source_transaction_id=str(i),
                source_file="synthetic.csv",
                import_run_id=run.id,
            )
            session.add(tx)
            txs.append(tx)
        session.flush()
        return account, inv.id, [t.id for t in txs]


def test_persistent_duplicate_refund_idempotency_immutable(factory):
    account, inv, ids = seed(factory, duplicate=True)
    aggregate, details = reconcile(account, session_factory=factory, confirm_exact=True)
    assert aggregate["candidate_links"] == 3 and aggregate["confirmed_links"] == 0
    assert aggregate["reversal_candidate_pairs"] == 2
    detail = next(r for r in details if r["invoice_id"] == str(inv))
    assert detail["state"] == "AMBIGUOUS" and detail["candidate_net_consistent_with_single_payment"]
    with factory() as session:
        before = [session.get(Transaction, id).amount for id in ids]
        n = session.scalar(select(func.count()).select_from(TransactionInvoiceAllocation))
        r = session.scalar(select(func.count()).select_from(TransactionReversalCandidate))
    assert reconcile(account, session_factory=factory, confirm_exact=True) == (aggregate, details)
    with factory() as session:
        assert n == session.scalar(select(func.count()).select_from(TransactionInvoiceAllocation))
        assert r == session.scalar(select(func.count()).select_from(TransactionReversalCandidate))
        assert before == [session.get(Transaction, id).amount for id in ids]


def test_unique_match_confirmed_and_existing_decision_preserved(factory):
    account, inv, ids = seed(factory)
    aggregate, details = reconcile(account, session_factory=factory, confirm_exact=True)
    assert aggregate["confirmed_links"] == 1
    assert next(r for r in details if r["invoice_id"] == str(inv))["state"] == "PAID"
    with factory() as session, session.begin():
        a = session.scalar(
            select(TransactionInvoiceAllocation).where(
                TransactionInvoiceAllocation.invoice_id == inv
            )
        )
        a.status = "REJECTED"
    aggregate, _ = reconcile(account, session_factory=factory, confirm_exact=True)
    assert aggregate["confirmed_links"] == 0 and aggregate["candidate_links"] == 0


def test_0005_up_down_up_and_schema_check(factory):
    url = factory.kw["bind"].url
    assert "energy_test_" in url.query["options"]
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    for args in [("downgrade", "0004"), ("upgrade", "head"), ("check",)]:
        subprocess.run([".venv/bin/alembic", *args], env=env, check=True, capture_output=True)


def test_domestic_reference_padding_requires_valid_checksum():
    from data_pipeline.reconcile.invoices import reference_key

    assert reference_key("1 232") == reference_key("00000000000000001232")
    assert reference_key("1233") != reference_key("00000000000000001233")
    assert reference_key("RF01ABC") != reference_key("ABC")


def test_explicit_candidate_promotion_retains_evidence(factory):
    account, inv, ids = seed(factory)
    aggregate, _ = reconcile(account, session_factory=factory)
    assert aggregate["candidate_links"] == 1
    aggregate, _ = reconcile(account, session_factory=factory, confirm_exact=True)
    assert aggregate["confirmed_links"] == 1
    with factory() as session:
        a = session.scalar(
            select(TransactionInvoiceAllocation).where(
                TransactionInvoiceAllocation.invoice_id == inv
            )
        )
        assert a.evidence["previous_evaluations"][0]["status"] == "CANDIDATE"
