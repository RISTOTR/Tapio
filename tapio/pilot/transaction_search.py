"""Bounded deterministic bank text search, separate from the frozen evidence agent."""

import calendar
import re
import unicodedata
from datetime import date
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import select

from apps.api.app.domain.models import Transaction, TransactionLabelReview
from tapio.pilot.contracts import Coverage, Evidence, PilotResponse
from tapio.pilot.subject_identity import generic_subject
from tapio.tools.schemas import Schema

MAX_SCANNED = 100_000
MAX_MATCHES = 1000
FIELDS = (
    "raw_description",
    "raw_source.Selitys",
    "raw_merchant",
    "normalized_merchant",
    "recipient",
    "processor",
    "confirmed_category",
    "confirmed_context",
    "suggested_category",
    "suggested_context",
)


def normalize_text(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in value).split())


class SearchDates(Schema):
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def ordered(self):
        if self.date_from > self.date_to:
            raise ValueError("INVALID_SEARCH_DATES")
        return self


class SearchPlan(Schema):
    intent: Literal["TRANSACTION_SEARCH"]
    terms: list[str] = Field(min_length=1, max_length=10)
    date_range: SearchDates | None

    @model_validator(mode="after")
    def specific_terms(self):
        for term in self.terms:
            normalized = normalize_text(term)
            if not isinstance(term, str) or not 3 <= len(normalized) <= 80 or len(term) > 120:
                raise ValueError("SEARCH_TERM_TOO_SHORT_OR_LONG")
            if not any(c.isalpha() for c in normalized) or normalized in {
                "the",
                "and",
                "for",
                "from",
                "with",
                "anything",
                "something",
                "related",
                "all",
                "any",
                "everything",
                "transaction",
                "transactions",
                "payment",
                "payments",
                "purchase",
                "purchases",
            }:
                raise ValueError("SEARCH_TERM_NOT_SPECIFIC")
        return self


def search_intent(question):
    """Grammar-level routing; no topic-specific words or synonym dictionary."""
    q = normalize_text(question)
    action = re.search(r"\b(show|find|list|search|look)\b", q)
    objects = re.search(r"\b(transactions?|payments?|purchases?)\b", q)
    relation = re.search(r"\b(related|mentioning|mentions|containing|contains|matching|word)\b", q)
    # Preserve established review/coverage, totals and tax paths.
    if re.search(r"\b(review|unreviewed|unresolved|incomplete|deduct\w*|total|how much)\b", q):
        return False
    if action and ((objects and len(q.split()) >= 3) or relation):
        return True
    # A short standalone phrase is also a search box query, not an overview.
    return bool(
        not action
        and not re.search(
            r"\b(what|where|why|how|can|give|tell|compare|reconcile|review|explain|summarize|overview|important)\b",
            q,
        )
        and 1 <= len(q.split()) <= 8
        and not generic_subject(q)
        and "?" not in question
    )


def requested_dates(question):
    years = set(re.findall(r"\b20\d{2}\b", question))
    months = [
        i for i in range(1, 13) if re.search(r"\b" + calendar.month_name[i] + r"\b", question, re.I)
    ]
    if (
        len(years) > 1
        or len(months) > 1
        or re.search(
            r"\b(last|since|between|before|after|quarter|yesterday|today|this year|this month)\b",
            question,
            re.I,
        )
        or re.search(r"\b\d{4}-\d{2}-\d{2}\b", question)
    ):
        raise ValueError("UNSUPPORTED_QUESTION")
    if not years:
        if months:
            raise ValueError("UNSUPPORTED_QUESTION")
        return None
    year = int(next(iter(years)))
    month = months[0] if months else None
    return SearchDates(
        date_from=date(year, month or 1, 1),
        date_to=date(year, month or 12, calendar.monthrange(year, month)[1] if month else 31),
    )


def validate_search_plan(question, value):
    plan = SearchPlan.model_validate(value)
    if plan.date_range != requested_dates(question):
        raise ValueError("SEARCH_DATE_SCOPE_MISMATCH")
    return plan


def matching_terms(fields, terms):
    """Whole normalized token/phrase matches, no wildcard, stemming or fuzzy expansion."""
    matches = []
    for term in terms:
        needle = " " + normalize_text(term) + " "
        matched = [
            name for name, value in fields.items() if needle in " " + normalize_text(value) + " "
        ]
        if matched:
            matches.append({"term": term, "fields": matched})
    return matches


def retrieve_search(plan, session_factory, *, hide_labels=False):
    """hide_labels is an offline ablation projection; production defaults stay unchanged."""
    plan = SearchPlan.model_validate(plan)
    t, r = Transaction, TransactionLabelReview
    query = select(t, r).outerjoin(r, r.transaction_id == t.id).order_by(t.booking_date, t.id)
    if plan.date_range:
        query = query.where(
            t.booking_date >= plan.date_range.date_from, t.booking_date <= plan.date_range.date_to
        )
    items, scanned = [], 0
    first = last = None
    with session_factory() as db:
        for tx, review in db.execute(query.execution_options(yield_per=500)):
            scanned += 1
            if scanned > MAX_SCANNED:
                raise ValueError("TRANSACTION_SEARCH_LIMIT")
            first = first or tx.booking_date
            last = tx.booking_date
            confirmed = (
                not hide_labels and review is not None and review.review_status == "REVIEWED"
            )
            fields = {
                "raw_description": tx.message,
                "raw_source.Selitys": (tx.raw_source or {}).get("Selitys")
                if isinstance(tx.raw_source, dict)
                else None,
                "raw_merchant": tx.raw_counterparty,
                "normalized_merchant": tx.normalized_counterparty,
                "recipient": tx.ultimate_recipient,
                "processor": tx.payment_intermediary,
                "confirmed_category": review.confirmed_category if confirmed else None,
                "confirmed_context": review.confirmed_business_context if confirmed else None,
                "suggested_category": tx.category if not confirmed and not hide_labels else None,
                "suggested_context": tx.business_context
                if not confirmed and not hide_labels
                else None,
            }
            matches = matching_terms(fields, plan.terms)
            if not matches:
                continue
            if len(items) >= MAX_MATCHES:
                raise ValueError("TRANSACTION_SEARCH_LIMIT")
            items.append(
                {
                    "id": str(tx.id),
                    "booking_date": tx.booking_date.isoformat(),
                    "counterparty": tx.normalized_counterparty or tx.raw_counterparty or "Unnamed",
                    "amount": str(tx.amount),
                    "currency": tx.currency,
                    "direction": tx.direction.value,
                    "label_authority": "HUMAN_REVIEWED" if confirmed else "UNREVIEWED",
                    "review_status": review.review_status
                    if review and not hide_labels
                    else "UNREVIEWED",
                    "category": review.confirmed_category if confirmed else None,
                    "business_context": review.confirmed_business_context if confirmed else None,
                    "matched_terms": matches,
                }
            )
    return {
        "plan": plan.model_dump(mode="json"),
        "items": items,
        "complete": True,
        "scanned_rows": scanned,
        "observed_from": first.isoformat() if first else None,
        "observed_to": last.isoformat() if last else None,
        "searched_fields": list(FIELDS[:6] if hide_labels else FIELDS),
        "matching": "NORMALIZED_TOKEN_PHRASE_V1",
        "labels_hidden": hide_labels,
    }


def search_response(evidence, session):
    from tapio.pilot.answer_cards import amount, unresolved
    from tapio.pilot.presentation import public_text

    if evidence.get("complete") is not True:
        raise ValueError("TRANSACTION_SEARCH_LIMIT")
    from tapio.pilot.search_display import prepare, summary

    catalog = bool(evidence.get("catalog_concept") or evidence.get("literal_search"))
    if catalog:
        evidence = prepare(evidence)
    rows = evidence["items"]
    terms = evidence["plan"]["terms"]
    direct = (
        f"I found {len(rows)} matching transaction(s)."
        if rows
        else "I found no imported bank transactions matching the search terms: "
        + ", ".join(terms)
        + "."
    )
    if catalog:
        text, search_notes = summary(rows, evidence.get("language", "en"))
        direct = text["found"].format(n=len(rows)) if rows else text["none"]
    elif not rows:
        direct += " This does not establish zero spending."
    lines = []
    for row in rows[:30]:
        status = (
            "human-reviewed: " + row["category"] + " / " + row["business_context"]
            if row["label_authority"] == "HUMAN_REVIEWED"
            else "unresolved"
        )
        if row["label_authority"] == "HUMAN_REVIEWED" and unresolved(row):
            status += "; unresolved"
        if catalog:
            status = (
                "HUMAN_CONFIRMED: " + row["category"] + " / " + row["business_context"]
                if row["label_authority"] == "HUMAN_REVIEWED"
                else text["unresolved"]
            )
        lines.append(
            f"{row['booking_date']} — {row['counterparty']} — "
            f"{amount(row['amount'], row['currency'])}; {status}. "
            + (text["matched"] if catalog else "Matched: ")
            + ", ".join(m["term"] for m in row["matched_terms"])
            + "."
        )
    public_rows = [{k: v for k, v in row.items() if k != "id"} for row in rows]

    def clean(value):
        if isinstance(value, str):
            return public_text(value, [evidence])
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value

    period = evidence["plan"]["date_range"]
    scope = f"{period['date_from']}–{period['date_to']}" if period else "all imported dates"
    note = (
        f"Search scope: {scope}; {evidence['scanned_rows']} imported rows searched. "
        "Text matching does not establish purpose or tax deductibility. "
        "Imported rows do not prove complete bank-statement coverage."
    )
    if evidence.get("labels_hidden"):
        note += (
            " Offline label ablation: confirmed and suggested labels were hidden before search. "
            "No text match does not establish absence of purchases in that category or context."
        )
    if any(
        field.startswith("suggested_")
        for row in rows
        for match in row["matched_terms"]
        for field in match["fields"]
    ):
        note += " Suggested-label matches are non-authoritative; they are not confirmed labels."
    if len(rows) > 30:
        note += " First 30 matches shown; all matches are retained in transaction details."
    if catalog:
        note = " ".join(
            [
                *search_notes,
                text["availability"].format(n=sum(unresolved(r) for r in rows)),
                text["coverage"],
            ]
        )
    states = ["SUPPORTED", "NO_MATCH"] if not rows else ["SUPPORTED"]
    if any(unresolved(r) for r in rows):
        states.append("HUMAN_REVIEW_REQUIRED")
    return PilotResponse(
        presentation_mode="TRANSACTION_SEARCH",
        failure_category="NO_MATCH" if not rows else None,
        direct_answer=clean(direct),
        answer=clean("\n".join([direct, *lines, note])),
        relevant_breakdown=clean(lines),
        coverage_note=clean(note),
        evidence_state="SUPPORTED",
        evidence_states=states,
        coverage=Coverage(status="DETERMINED"),
        evidence=[
            Evidence(
                kind="transaction_search",
                summary="Deterministic bank text matches",
                records=len(rows),
            )
        ],
        evidence_summary=clean(
            [(text["terms"] if catalog else "Search terms: ") + ", ".join(terms) + "."]
        ),
        optional_details=clean(
            {
                "transactions": public_rows,
                "search": {
                    "terms": terms,
                    "date_range": period,
                    "matching": evidence["matching"],
                    "searched_fields": evidence["searched_fields"],
                    "scanned_rows": evidence["scanned_rows"],
                },
            }
        ),
        human_review=[],
        limitations=[],
        session=session,
    )
