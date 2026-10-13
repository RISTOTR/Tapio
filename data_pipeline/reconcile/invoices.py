"""Auditable bank/invoice candidates; confirmation requires mutual uniqueness."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text

from apps.api.app.core.database import SessionLocal
from apps.api.app.domain.models import (
    Document,
    Invoice,
    Transaction,
    TransactionInvoiceAllocation,
    TransactionReversalCandidate,
)
from data_pipeline.ingest.bank_csv import SOURCE_TYPE
from data_pipeline.ingest.documents.loader import LOCK
from data_pipeline.normalize.bank import name_key, normalize_name

VERSION = "invoice-match-2"
ZERO = Decimal(0)


def vendor_key(value):
    return name_key(normalize_name(value) or "")


def reference_key(value):
    # Finance Finland: domestic references omit padding zeroes in print. Only
    # checksum-valid 4–20 digit domestic references get this equivalence.
    compact = re.sub(r"\s+", "", value or "").upper()
    domestic = compact.lstrip("0")
    if compact.isascii() and compact.isdigit() and len(compact) <= 20 and 4 <= len(domestic):
        weights = (7, 3, 1)
        checksum = (
            -sum(int(digit) * weights[i % 3] for i, digit in enumerate(reversed(domestic[:-1])))
        ) % 10
        if checksum == int(domestic[-1]):
            return "FI:" + domestic
    return compact


def candidates(invoices, transactions):
    """Inputs are fact dictionaries. Outputs carry UUIDs privately, no source text."""
    result = []
    for inv in invoices:
        if inv["total"] <= 0:
            continue
        for tx in transactions:
            if tx["amount"] >= 0 or tx["currency"] != "EUR":
                continue
            if not vendor_key(inv["vendor"]) or vendor_key(inv["vendor"]) != vendor_key(
                tx["vendor"]
            ):
                continue
            days = (tx["date"] - inv["due"]).days
            ref = bool(inv.get("reference")) and reference_key(inv["reference"]) == reference_key(
                tx.get("reference")
            )
            exact = -tx["amount"] == inv["total"]
            near = abs(-tx["amount"] - inv["total"]) <= Decimal(".01")
            # A reference can support partial/bulk amounts; amount-only is never enough.
            if not (-31 <= days <= 90 and (near or ref)):
                continue
            evidence = {
                "version": VERSION,
                "vendor_exact": True,
                "amount_exact": exact,
                "amount_delta_eur": str(-tx["amount"] - inv["total"]),
                "reference_exact": ref,
                "reference_present": bool(inv.get("reference")),
                "days_from_due": days,
                "date_window": [-31, 90],
                "score_components": {
                    "vendor": 40,
                    "amount": 30 if exact else 10 if near else 0,
                    "reference": 50 if ref else 0,
                    "date": 10,
                },
            }
            result.append(
                {
                    "transaction_id": tx["id"],
                    "invoice_id": inv["id"],
                    "amount": min(-tx["amount"], inv["total"]),
                    "kind": "payment",
                    "evidence": evidence,
                }
            )
    # Preserve every possible debit/credit reversal. Link refunds to invoice candidates
    # only through an eligible payment and count the credit just once per invoice.
    reversals = []
    by_tx = {t["id"]: t for t in transactions}
    matched_debits = {r["transaction_id"] for r in result}
    for credit in transactions:
        if credit["amount"] <= 0 or credit["currency"] != "EUR":
            continue
        for debit_id in sorted(matched_debits, key=str):
            debit = by_tx[debit_id]
            gap = (credit["date"] - debit["date"]).days
            if credit["namespace"] != debit["namespace"] or vendor_key(
                credit["vendor"]
            ) != vendor_key(debit["vendor"]):
                continue
            if credit["amount"] != -debit["amount"] or not 0 < gap <= 365:
                continue
            reversals.append(
                {
                    "debit_id": debit_id,
                    "credit_id": credit["id"],
                    "evidence": {
                        "version": VERSION,
                        "amount_exact": True,
                        "vendor_exact": True,
                        "days_after_debit": gap,
                        "status": "CANDIDATE",
                    },
                }
            )
    payment_rows = list(result)
    refund_pairs = defaultdict(list)
    for reversal in reversals:
        for payment in payment_rows:
            if payment["transaction_id"] == reversal["debit_id"]:
                refund_pairs[(payment["invoice_id"], reversal["credit_id"])].append(
                    str(reversal["debit_id"])
                )
    for (invoice_id, credit_id), debits in refund_pairs.items():
        result.append(
            {
                "transaction_id": credit_id,
                "invoice_id": invoice_id,
                "amount": -by_tx[credit_id]["amount"],
                "kind": "refund",
                "evidence": {
                    "version": VERSION,
                    "possible_debit_ids": sorted(debits),
                    "refund_link_ambiguous": len(debits) > 1,
                },
            }
        )
    inv_counts = Counter(r["invoice_id"] for r in result)
    tx_counts = Counter(r["transaction_id"] for r in result)
    for row in result:
        e = row["evidence"]
        row["auto_confirm_eligible"] = (
            row["kind"] == "payment"
            and e["amount_exact"]
            and inv_counts[row["invoice_id"]] == 1
            and tx_counts[row["transaction_id"]] == 1
            and (not e["reference_present"] or e["reference_exact"])
        )
    return result, reversals


def state(total, allocations):
    active = [a for a in allocations if a["status"] != "REJECTED"]
    confirmed = [a for a in active if a["status"] == "CONFIRMED"]
    paid = sum((a["amount"] for a in confirmed if a["amount"] > 0), ZERO)
    refunded = -sum((a["amount"] for a in confirmed if a["amount"] < 0), ZERO)
    net = paid - refunded
    if any(a["status"] == "CANDIDATE" for a in active):
        status = "AMBIGUOUS"
    elif paid and net <= 0:
        status = "REFUNDED"
    elif net > total:
        status = "OVERPAID"
    elif net == total:
        status = "PAID"
    elif net > 0:
        status = "PARTIALLY_PAID"
    else:
        status = "UNMATCHED"
    return {
        "state": status,
        "confirmed_paid_eur": str(paid),
        "confirmed_refund_eur": str(refunded),
        "confirmed_net_eur": str(net),
    }


def reconcile(account_key, *, session_factory=SessionLocal, confirm_exact=False):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", account_key):
        raise ValueError("invalid_account_key")
    with session_factory() as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
        pairs = session.execute(
            select(Invoice, Document).join(Document, Invoice.document_id == Document.id)
        ).all()
        invs = [
            {
                "id": i.id,
                "vendor": i.vendor,
                "total": i.total_eur,
                "due": i.due_date,
                "reference": d.document_metadata.get("bill", {}).get("reference"),
            }
            for i, d in pairs
            if i.total_eur is not None and i.due_date
        ]
        transactions = list(
            session.scalars(
                select(Transaction).where(
                    Transaction.source_namespace == f"{SOURCE_TYPE}:{account_key}"
                )
            )
        )
        txs = [
            {
                "id": t.id,
                "vendor": t.ultimate_recipient
                if t.payment_intermediary
                else t.normalized_counterparty,
                "amount": t.amount,
                "date": t.booking_date,
                "currency": t.currency,
                "reference": t.reference,
                "namespace": t.source_namespace,
            }
            for t in transactions
        ]
        proposed, reversals = candidates(invs, txs)
        # Existing allocations across ALL accounts constrain confirmation too.
        existing = list(session.scalars(select(TransactionInvoiceAllocation)))
        by_pair = {(a.invoice_id, a.transaction_id): a for a in existing}
        for row in proposed:
            key = (row["invoice_id"], row["transaction_id"])
            prior = by_pair.get(key)
            competing = any(
                a.status != "REJECTED"
                and (a.invoice_id == row["invoice_id"] or a.transaction_id == row["transaction_id"])
                and (a.invoice_id, a.transaction_id) != key
                for a in existing
            )
            status = (
                "CONFIRMED"
                if confirm_exact and row["auto_confirm_eligible"] and not competing
                else "CANDIDATE"
            )
            if prior is None:
                prior = TransactionInvoiceAllocation(
                    invoice_id=row["invoice_id"],
                    transaction_id=row["transaction_id"],
                    allocated_amount_eur=row["amount"],
                    match_method=VERSION + ":" + row["kind"],
                    status=status,
                    evidence=row["evidence"],
                )
                session.add(prior)
                existing.append(prior)
                by_pair[key] = prior
            elif (
                prior.status == "CANDIDATE"
                and confirm_exact
                and prior.match_method.startswith("invoice-match-")
                and prior.allocated_amount_eur == row["amount"]
            ):
                # Explicit re-evaluation preserves previous evidence. Final human
                # decisions and confirmed allocations are never overwritten.
                changed = any(prior.evidence.get(k) != v for k, v in row["evidence"].items())
                if changed or status == "CONFIRMED":
                    history = list(prior.evidence.get("previous_evaluations", []))
                    history.append(
                        {
                            "reevaluated_at": datetime.now(UTC).isoformat(),
                            "action": "explicit_confirm_exact",
                            "status": prior.status,
                            "evidence": {
                                k: v
                                for k, v in prior.evidence.items()
                                if k != "previous_evaluations"
                            },
                        }
                    )
                    prior.evidence = {**row["evidence"], "previous_evaluations": history}
                    prior.status = status
        for pair in reversals:
            found = session.scalar(
                select(TransactionReversalCandidate.id).where(
                    TransactionReversalCandidate.debit_id == pair["debit_id"],
                    TransactionReversalCandidate.credit_id == pair["credit_id"],
                )
            )
            if not found:
                session.add(TransactionReversalCandidate(**pair))
        session.flush()
        report = []
        for inv in invs:
            allocations = [
                {"amount": a.allocated_amount_eur, "status": a.status}
                for a in existing
                if a.invoice_id == inv["id"] and a.transaction_id in {t["id"] for t in txs}
            ]
            rows = [
                r
                for r in proposed
                if r["invoice_id"] == inv["id"]
                and by_pair[(r["invoice_id"], r["transaction_id"])].status != "REJECTED"
            ]
            debit = [r for r in rows if r["kind"] == "payment" and r["evidence"]["amount_exact"]]
            credits = [r for r in rows if r["kind"] == "refund"]
            observed = sum((r["amount"] for r in debit + credits), ZERO)
            competing = any(
                sum(other["transaction_id"] == r["transaction_id"] for other in proposed) > 1
                for r in rows
            )
            report.append(
                {
                    "invoice_id": str(inv["id"]),
                    **state(inv["total"], allocations),
                    "payment_candidates": len(debit),
                    "refund_candidates": len(credits),
                    "possible_reversal_pairs": sum(
                        len(r["evidence"]["possible_debit_ids"]) for r in credits
                    ),
                    "duplicate_payment_candidate": len(debit) > 1,
                    "candidate_net_eur": str(observed),
                    "candidate_net_consistent_with_single_payment": len(debit) > 1
                    and bool(credits)
                    and observed == inv["total"]
                    and not competing,
                    "competing_invoice_candidates": competing,
                }
            )
        account_ids = {t.id for t in transactions}
        relevant = [a for a in existing if a.transaction_id in account_ids]
        aggregate = {
            "invoices": len(invs),
            "candidate_links": sum(a.status == "CANDIDATE" for a in relevant),
            "confirmed_links": sum(a.status == "CONFIRMED" for a in relevant),
            "exact_payment_candidates": sum(
                r["kind"] == "payment" and r["evidence"]["amount_exact"] for r in proposed
            ),
            "reversal_candidate_pairs": len(reversals),
            "refund_credits": len({r["credit_id"] for r in reversals}),
            "duplicate_payment_invoices": sum(r["duplicate_payment_candidate"] for r in report),
            "net_single_payment_consistent": sum(
                r["candidate_net_consistent_with_single_payment"] for r in report
            ),
            "states": dict(Counter(r["state"] for r in report)),
        }
        return aggregate, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-key", required=True)
    parser.add_argument(
        "--confirm-exact",
        action="store_true",
        help="Confirm newly discovered mutually unique exact matches only",
    )
    args = parser.parse_args(argv)
    aggregate, _ = reconcile(args.account_key, confirm_exact=args.confirm_exact)
    print(json.dumps(aggregate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
