"""Bounded read-only bank comparisons; shared identity resolution and Decimal arithmetic."""

import calendar
import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field
from sqlalchemy import select

from apps.api.app.domain.enums import TransactionCategory
from apps.api.app.domain.models import Transaction, TransactionLabelReview
from tapio.pilot.contracts import Coverage, Evidence, PilotResponse
from tapio.pilot.subject_identity import resolve_subject
from tapio.pilot.transaction_search import MAX_SCANNED, SearchDates, normalize_text
from tapio.tools.schemas import Schema

MONTHS = {
    name.casefold(): i
    for i in range(1, 13)
    for name in (calendar.month_name[i], calendar.month_abbr[i])
}
MONTH_PATTERN = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"


class ComparisonPlan(Schema):
    subject: str = Field(min_length=1, max_length=120)
    metric: Literal["BANK_OUTFLOW", "BANK_INFLOW", "NET_CASH_FLOW", "TRANSACTION_COUNT"]
    filter_kind: Literal["SUBJECT", "CONFIRMED_CONTEXT", "CONFIRMED_CATEGORY"] = "SUBJECT"
    period_a: SearchDates
    period_b: SearchDates


def period(year, month=None):
    return SearchDates(
        date_from=date(year, month or 1, 1),
        date_to=date(year, month or 12, calendar.monthrange(year, month)[1] if month else 31),
    )


def comparison_intent(question):
    return bool(re.search(r"\b(compare|comparison|versus|vs|than)\b", normalize_text(question)))


def comparison_plan(question, *, today=None):
    if not comparison_intent(question):
        return None
    q = normalize_text(question)
    if re.search(r"\b(invoice|invoices|tax|deduct\w*|vat|receipt|receipts)\b", q):
        raise ValueError("UNSUPPORTED_QUESTION")
    today = today or date.today()
    relative = re.search(r"last (" + MONTH_PATTERN + r") than the \1 before", q)
    pairs = list(re.finditer(r"\b(" + MONTH_PATTERN + r") (20\d{2})\b", q))
    years = re.findall(r"\b20\d{2}\b", q)
    months = re.findall(r"\b" + MONTH_PATTERN + r"\b", q)
    if relative and not years:
        month = MONTHS[relative[1]]
        year = today.year if today.month > month else today.year - 1
        a, b = period(year, month), period(year - 1, month)
        q = q[: relative.start()] + q[relative.end() :]
    elif len(pairs) == 2 and len(years) == 2 and len(months) == 2:
        a, b = (period(int(p[2]), MONTHS[p[1]]) for p in pairs)
        q = re.sub(r"\b(" + MONTH_PATTERN + r") 20\d{2}\b", " ", q)
    elif len(years) == 2 and len(months) <= 1:
        month = MONTHS[months[0]] if months else None
        a, b = (period(int(y), month) for y in years)
        q = re.sub(r"\b20\d{2}\b|\b" + MONTH_PATTERN + r"\b", " ", q)
    else:
        return None
    if re.search(r"\b(count|number)\b", q):
        metric = "TRANSACTION_COUNT"
    elif re.search(r"\b(net|cash flow)\b", q):
        metric = "NET_CASH_FLOW"
    elif re.search(r"\b(inflow|income|received)\b", q):
        metric = "BANK_INFLOW"
    else:
        metric = "BANK_OUTFLOW"
    # Only structural query words are removed; names are never hardcoded here.
    grammar = {
        "compare",
        "comparison",
        "my",
        "the",
        "in",
        "with",
        "and",
        "vs",
        "versus",
        "for",
        "transactions",
        "transaction",
        "payments",
        "payment",
        "how",
        "much",
        "more",
        "less",
        "did",
        "i",
        "pay",
        "paid",
        "than",
        "cost",
        "me",
        "bank",
        "outflow",
        "inflow",
        "income",
        "received",
        "net",
        "cash",
        "flow",
        "count",
        "number",
        "of",
        "spending",
    }
    subject = " ".join(w for w in q.split() if w not in grammar)
    if not subject or subject in {"between", "before", "after", "since"}:
        return None
    if re.search(r"\b(before|after|last|since|between|only)\b", subject):
        raise ValueError("UNSUPPORTED_QUESTION")
    kind = "SUBJECT"
    if subject.upper() in {"FORESTRY", "PROPERTY", "PERSONAL", "UNKNOWN"}:
        kind, subject = "CONFIRMED_CONTEXT", subject.upper()
    elif subject.upper() in {c.value.upper() for c in TransactionCategory}:
        kind, subject = "CONFIRMED_CATEGORY", subject.upper()
    a, b = sorted((a, b), key=lambda p: p.date_from)
    return ComparisonPlan(subject=subject, metric=metric, filter_kind=kind, period_a=a, period_b=b)


def retrieve_comparison(plan, session_factory):
    plan = ComparisonPlan.model_validate(plan)
    with session_factory() as db:
        pairs = db.execute(
            select(Transaction, TransactionLabelReview)
            .outerjoin(
                TransactionLabelReview, TransactionLabelReview.transaction_id == Transaction.id
            )
            .order_by(Transaction.booking_date, Transaction.id)
            .limit(MAX_SCANNED + 1)
        ).all()
        # Preserve loaded scalar evidence across the read-only session rollback.
        db.expunge_all()
    if len(pairs) > MAX_SCANNED:
        raise ValueError("TRANSACTION_SEARCH_LIMIT")
    names = {
        v
        for tx, _ in pairs
        for v in (tx.normalized_counterparty, tx.ultimate_recipient, tx.payment_intermediary)
        if v
    }
    resolution = resolve_subject(plan.subject, names) if plan.filter_kind == "SUBJECT" else None
    if resolution and resolution["status"] == "AMBIGUOUS_IDENTITY":
        raise ValueError("UNSUPPORTED_QUESTION")

    def matches(tx, review):
        if resolution:
            return any(
                v in resolution["names"]
                for v in (
                    tx.normalized_counterparty,
                    tx.ultimate_recipient,
                    tx.payment_intermediary,
                )
            )
        if review is None or review.review_status != "REVIEWED":
            return False
        field = (
            "confirmed_business_context"
            if plan.filter_kind == "CONFIRMED_CONTEXT"
            else "confirmed_category"
        )
        return getattr(review, field) == plan.subject

    sides = []
    for bounds in (plan.period_a, plan.period_b):
        all_rows = [
            (t, r) for t, r in pairs if bounds.date_from <= t.booking_date <= bounds.date_to
        ]
        selected = [(t, r) for t, r in all_rows if matches(t, r)]
        rows = []
        for t, r in selected:
            confirmed = r is not None and r.review_status == "REVIEWED"
            rows.append(
                {
                    "booking_date": t.booking_date.isoformat(),
                    "counterparty": t.normalized_counterparty,
                    "amount": str(t.amount),
                    "currency": t.currency,
                    "category": r.confirmed_category if confirmed else None,
                    "business_context": r.confirmed_business_context if confirmed else None,
                    "label_authority": "HUMAN_CONFIRMED" if confirmed else "UNRESOLVED",
                }
            )
        totals = {}
        for currency in sorted({t.currency for t, _ in selected}):
            values = [t.amount for t, _ in selected if t.currency == currency]
            totals[currency] = {
                "BANK_OUTFLOW": str(-sum((v for v in values if v < 0), Decimal(0))),
                "BANK_INFLOW": str(sum((v for v in values if v > 0), Decimal(0))),
                "NET_CASH_FLOW": str(sum(values, Decimal(0))),
            }
        sides.append(
            {
                "period": bounds.model_dump(mode="json"),
                "rows": rows,
                "totals": totals,
                "transaction_count": len(rows),
                "imported_rows_in_period": len(all_rows),
                "payment_count": sum(t.amount < 0 for t, _ in selected),
                "observed_from": all_rows[0][0].booking_date.isoformat() if all_rows else None,
                "observed_to": all_rows[-1][0].booking_date.isoformat() if all_rows else None,
            }
        )
    a, b = sides
    differences = {}
    if plan.metric == "TRANSACTION_COUNT":
        differences["count"] = str(b["transaction_count"] - a["transaction_count"])
    else:
        for currency in sorted(set(a["totals"]) | set(b["totals"])):
            av = Decimal(a["totals"].get(currency, {}).get(plan.metric, "0"))
            bv = Decimal(b["totals"].get(currency, {}).get(plan.metric, "0"))
            differences[currency] = str(bv - av)
    return {
        "plan": plan.model_dump(mode="json"),
        "resolution": resolution,
        "sides": sides,
        "difference_b_minus_a": differences,
        "complete": True,
    }


def comparison_response(evidence, session):
    plan = evidence["plan"]
    metric = plan["metric"]
    direct = f"Imported bank comparison for {plan['subject']} — {metric}. "
    diff = ", ".join(f"{Decimal(v):.2f} {c}" for c, v in evidence["difference_b_minus_a"].items())
    direct += (
        "Difference (period B minus period A): "
        + (diff or "no matching rows in either period")
        + "."
    )
    lines = []
    for label, side in zip(("A", "B"), evidence["sides"], strict=True):
        p = side["period"]
        values = (
            str(side["transaction_count"])
            if metric == "TRANSACTION_COUNT"
            else ", ".join(f"{Decimal(v[metric]):.2f} {c}" for c, v in side["totals"].items())
        )
        lines.append(
            f"{label}: {p['date_from']}–{p['date_to']}: {side['transaction_count']} transactions; "
            f"{side['payment_count']} payments; {metric}: {values or 'no matching imported rows'}."
        )
        if not side["rows"]:
            lines.append(
                f"No matching imported {plan['subject']} transactions were found for "
                f"{p['date_from']}–{p['date_to']}. This does not establish zero spending."
            )
    coverage = " ".join(
        f"Period {label}: {s['imported_rows_in_period']} imported bank rows across all subjects; "
        f"observed {s['observed_from'] or 'none'} to {s['observed_to'] or 'none'}."
        for label, s in zip(("A", "B"), evidence["sides"], strict=True)
    ) + (
        " Imported rows do not establish complete bank-statement coverage. "
        "Differences compare only retrieved rows, not proven changes in actual spending; "
        "missing or partial periods may mislead. "
        "Bank amounts are not invoice values and do not establish tax treatment."
    )
    return PilotResponse(
        presentation_mode="COMPARISON",
        direct_answer=direct,
        answer="\n".join([direct, *lines, coverage]),
        relevant_breakdown=lines,
        coverage_note=coverage,
        evidence_state="SUPPORTED",
        evidence_states=["SUPPORTED", "PARTIAL_COVERAGE"]
        + (["NO_MATCH"] if not any(s["rows"] for s in evidence["sides"]) else []),
        coverage=Coverage(status="DETERMINED"),
        evidence=[
            Evidence(
                kind="filtered_bank_comparison",
                summary="Deterministic bank rows",
                records=sum(len(s["rows"]) for s in evidence["sides"]),
            )
        ],
        optional_details={
            "comparison": evidence,
            "transactions": [r for s in evidence["sides"] for r in s["rows"]],
        },
        human_review=[],
        limitations=[],
        session=session,
    )
