"""Read-only bank coverage and human review preparation."""

import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import select

from apps.api.app.domain.models import (
    ImportRun,
    Invoice,
    Transaction,
    TransactionInvoiceAllocation,
    TransactionLabelReview,
    TransactionReversalCandidate,
)
from apps.api.app.services.financial_summary import authoritative_label
from apps.api.app.services.tool_queries import Queries
from data_pipeline.ingest.bank_csv import SOURCE_TYPE, parse_bank_csv
from data_pipeline.labels.contracts import review_facts, safe_text
from data_pipeline.labels.merchant_policy import AMBIGUOUS_REASON, ambiguous_merchant
from data_pipeline.labels.workflow import source_identifiers
from integrations.gmail.cache import private_write

ROOT = Path("data/interim/phase07")


def filename_interval(name):
    match = re.fullmatch(r"tapahtumat(\d{8})-(\d{8})\.csv", name)
    if not match:
        return None
    return [date.fromisoformat(x).isoformat() for x in match.groups()]


def coverage_status(interval, verified_statement=False):
    # A filename or first/last booking date is not a statement completeness assertion.
    if not verified_statement:
        return "UNKNOWN_COVERAGE"
    return "COMPLETE_FOR_SOURCE_INTERVAL" if interval else "UNKNOWN_COVERAGE"


def priority(t, linked, reversals):
    context = t.business_context.value.upper() if t.business_context else "UNKNOWN"
    category = (t.category or "UNKNOWN").upper()
    reasons = []
    if abs(t.amount) >= 500:
        reasons.append("large_cash_flow_ge_500_eur")
    if t.amount > 0:
        reasons.append("income_or_refund_requires_review")
    if linked:
        reasons.append("invoice_link")
    if reversals:
        reasons.append("reversal_candidate")
    if context in ("PROPERTY", "FORESTRY"):
        reasons.append("weak_domain_suggestion_not_authority")
    if category in ("TRANSFER", "ELECTRICITY", "GRID_DISTRIBUTION", "TIMBER_INCOME"):
        reasons.append("material_cashflow_category")
    ambiguous = ambiguous_merchant(
        getattr(t, "ultimate_recipient", None) or t.normalized_counterparty
    )
    if reasons:
        return "P1", reasons + ([AMBIGUOUS_REASON] if ambiguous else [])
    if ambiguous:
        return "P2", [AMBIGUOUS_REASON]
    name = (t.normalized_counterparty or "").casefold()
    if any(x in name for x in ("rauta", "tokmanni", "mets", "sähkö", "vattenfall", "elenia")):
        return "P2", ["possible_domain_relevance_receipt_needed"]
    return "P3", ["ordinary_personal_or_low_materiality_review_later"]


def build_audit(queries=None, source_dir=Path("/Users/tyokone/Downloads")):
    q = queries or Queries()
    with q.session() as s:
        runs = list(
            s.scalars(
                select(ImportRun)
                .where(ImportRun.source_type == SOURCE_TYPE)
                .order_by(
                    ImportRun.source_filename, ImportRun.sha256, ImportRun.started_at, ImportRun.id
                )
            )
        )
        transactions = list(
            s.scalars(select(Transaction).order_by(Transaction.booking_date, Transaction.id))
        )
        reviews = {r.transaction_id: r for r in s.scalars(select(TransactionLabelReview))}
        allocations = list(
            s.scalars(
                select(TransactionInvoiceAllocation).order_by(
                    TransactionInvoiceAllocation.invoice_id, TransactionInvoiceAllocation.id
                )
            )
        )
        invoices = {i.id: i for i in s.scalars(select(Invoice))}
        reversals = list(
            s.scalars(
                select(TransactionReversalCandidate).order_by(
                    TransactionReversalCandidate.debit_id, TransactionReversalCandidate.credit_id
                )
            )
        )
        secrets = source_identifiers(s)
        records = {}
        for run in runs:
            records.setdefault(
                run.sha256,
                dict(
                    source_filename=run.source_filename,
                    sha256=run.sha256,
                    filename_claimed_interval=filename_interval(run.source_filename),
                    interval_authority="FILENAME_ONLY_NOT_STATEMENT",
                    import_runs=[],
                    rows_parsed=run.source_metadata.get("rows_parsed"),
                ),
            )["import_runs"].append(
                dict(
                    id=str(run.id),
                    outcome=run.source_metadata.get("outcome"),
                    loaded=run.row_count,
                    skipped=run.source_metadata.get("rows_skipped_duplicates"),
                )
            )
        # Only known bank export naming convention; no unrelated Downloads content is read.
        paths = sorted(source_dir.glob("tapahtumat*.csv"))
        paths += sorted(Path("data/raw").rglob("*.csv"))
        source_ids = {}
        for path in paths:
            if not filename_interval(path.name):
                continue
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            frame = parse_bank_csv(raw)
            dates = sorted(
                date.fromisoformat(x)
                if "-" in x
                else date(int(x.split(".")[2]), int(x.split(".")[1]), int(x.split(".")[0]))
                for x in frame["Kirjauspäivä"]
            )
            record = records.setdefault(
                digest,
                dict(
                    source_filename=path.name,
                    sha256=digest,
                    filename_claimed_interval=filename_interval(path.name),
                    import_runs=[],
                    interval_authority="FILENAME_ONLY_NOT_STATEMENT",
                    rows_parsed=len(frame),
                ),
            )
            record.update(
                local_file_found=True,
                file_sha256_matches_import=bool(record["import_runs"]),
                booking_first=str(dates[0]),
                booking_last=str(dates[-1]),
                source_rows=len(frame),
            )
            source_ids[digest] = set(frame["Arkistointitunnus"])
        overlaps = [
            dict(
                left=a, right=b, identical_source_identity_count=len(source_ids[a] & source_ids[b])
            )
            for a in sorted(source_ids)
            for b in sorted(source_ids)
            if a < b and source_ids[a] & source_ids[b]
        ]
        yr = [t for t in transactions if t.booking_date.year == 2026]
        intervals = [
            r["filename_claimed_interval"]
            for r in records.values()
            if r["filename_claimed_interval"] and r["filename_claimed_interval"][0][:4] == "2026"
        ]
        coverage = dict(
            year=2026,
            status="UNKNOWN_COVERAGE",
            year_status="PARTIAL_YEAR",
            claimed_source_start=min(i[0] for i in intervals) if intervals else None,
            claimed_source_end=max(i[1] for i in intervals) if intervals else None,
            booking_start=str(min(t.booking_date for t in yr)),
            booking_end=str(max(t.booking_date for t in yr)),
            transaction_count=len(yr),
            known_gaps=[],
            gaps_assessment="NOT_ESTABLISHED_NO_STATEMENT_MANIFEST",
            statement_boundary_verified=False,
            sources=list(records.values()),
            overlaps=overlaps,
            later_local_export_found=any(
                r["filename_claimed_interval"] and r["filename_claimed_interval"][1] > "2026-10-07"
                for r in records.values()
            ),
            scan_scope=(
                "Known bank exports in documented Downloads directory and data/raw; import metadata"
            ),
            limitations=[
                "Filename intervals are not verified bank statement intervals.",
                "Booking dates do not prove complete coverage, even within the export interval.",
                "No missing transactions or zero-activity months inferred.",
            ],
        )
        counts = Counter(t.normalized_counterparty for t in yr)
        queue = []
        for t in yr:
            context, category, human = authoritative_label(reviews.get(t.id))
            if human and context != "UNKNOWN" and category != "UNKNOWN":
                continue
            links = [
                dict(
                    invoice_id=str(a.invoice_id),
                    document_id=str(invoices[a.invoice_id].document_id),
                    status=a.status,
                    amount_eur=str(a.allocated_amount_eur),
                )
                for a in allocations
                if a.transaction_id == t.id
            ]
            pairs = [
                dict(debit_id=str(r.debit_id), credit_id=str(r.credit_id), status="CANDIDATE")
                for r in reversals
                if t.id in (r.debit_id, r.credit_id)
            ]
            p, reasons = priority(t, links, pairs)
            queue.append(
                dict(
                    **review_facts(t, secrets),
                    reference=safe_text(t.reference, secrets),
                    weak_category=t.category,
                    weak_context=t.business_context.value if t.business_context else None,
                    linked_evidence=links,
                    recurrence_count_same_counterparty=counts[t.normalized_counterparty],
                    recurrence_dates=[
                        str(x.booking_date)
                        for x in yr
                        if x.normalized_counterparty == t.normalized_counterparty
                    ],
                    reversal_evidence=pairs,
                    priority=p,
                    reasons=reasons,
                    confirmed_category="",
                    confirmed_context="",
                    human_decision="",
                    policy="Broad personal labels allowed; DNA prepaid OTHER/PERSONAL; "
                    "fuel FUEL/PERSONAL; "
                    "K-Rauta/Tokmanni need receipts for domain attribution; no tax decision.",
                )
            )
        queue.sort(
            key=lambda r: (
                r["priority"],
                -abs(float(r["amount"])),
                r["booking_date"],
                r["transaction_id"],
            )
        )
    coverage["review_coverage"] = dict(
        unresolved=len(queue),
        reviewed=len(yr) - len(queue),
        priorities=dict(Counter(r["priority"] for r in queue)),
    )
    return coverage, queue


def main():
    coverage, queue = build_audit()
    for name, obj in [("bank_coverage.json", coverage), ("review_queue.json", queue)]:
        private_write(ROOT / name, json.dumps(obj, indent=2, ensure_ascii=False).encode())
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(queue[0]))
    writer.writeheader()
    writer.writerows(
        {
            k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
            for k, v in row.items()
        }
        for row in queue
    )
    private_write(ROOT / "review_queue.csv", buf.getvalue().encode("utf-8-sig"))
    print(
        json.dumps(
            {
                k: coverage[k]
                for k in (
                    "status",
                    "claimed_source_start",
                    "claimed_source_end",
                    "booking_end",
                    "later_local_export_found",
                    "review_coverage",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
