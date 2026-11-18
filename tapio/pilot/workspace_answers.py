"""Bounded follow-up context and energy evidence routing around existing tools."""

import asyncio
import calendar
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from apps.api.app.domain.models import Transaction
from apps.api.app.services.tool_queries import Queries
from tapio.pilot.config import load_config, readonly_engine, readonly_session, source_fingerprints
from tapio.pilot.contracts import Coverage, PilotResponse, Session
from tapio.pilot.evidence_routing import answer_question
from tapio.pilot.period_comparison import comparison_plan
from tapio.pilot.transaction_search import requested_dates
from tapio.tools.finance_schemas import FinanceQuery
from tapio.tools.schemas import EnergyQuery, InvoiceQuery


def session():
    return Session(
        id=str(uuid4()),
        timestamp=datetime.now(UTC).isoformat(),
        model_calls=0,
        rounds=0,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        latency_seconds=0,
        estimated_cost_usd="0",
    )


def response(answer, *, records=(), sources=(), limits=(), suggestions=(), breakdown=()):
    return PilotResponse(
        answer=answer,
        direct_answer=answer,
        evidence_state="PARTIAL_COVERAGE",
        evidence_states=["PARTIAL_COVERAGE"],
        coverage=Coverage(status="DETERMINED" if records else "UNAVAILABLE"),
        evidence=[],
        human_review=[],
        limitations=list(limits),
        sources=list(sources),
        supporting_records=list(records),
        suggestions=list(suggestions),
        relevant_breakdown=list(breakdown),
        session=session(),
    )


def followup_question(question, previous):
    if not re.search(r"\b(those|these|that|previous|them)\b", question, re.I):
        return question
    domains = re.findall(r"\b(property|forestry|personal)\b", previous, re.I)
    years = set(re.findall(r"\b20\d{2}\b", previous))
    if (
        re.search(r"\btax payments?\b", question, re.I)
        and len(set(d.lower() for d in domains)) == 1
        and len(years) == 1
    ):
        return f"Show {domains[0].lower()} tax payments in {next(iter(years))}"
    return None


def energy_periods(question):
    span = re.search(
        r"\b("
        + "|".join(calendar.month_name[1:])
        + r")\s*[-–]\s*("
        + "|".join(calendar.month_name[1:])
        + r")\s+(20\d{2})\s+(?:vs|versus)\s+(20\d{2})\b",
        question,
        re.I,
    )
    if span:
        from datetime import date

        from tapio.pilot.transaction_search import SearchDates

        months = {name.lower(): n for n, name in enumerate(calendar.month_name) if name}
        first, last = months[span[1].lower()], months[span[2].lower()]
        if first > last:
            raise ValueError("UNSUPPORTED_PERIOD")
        return [
            SearchDates(
                date_from=date(int(y), first, 1),
                date_to=date(int(y), last, calendar.monthrange(int(y), last)[1]),
            )
            for y in (span[3], span[4])
        ]
    if re.search(r"\b(since|before|after|last|quarter|between)\b", question, re.I):
        raise ValueError("UNSUPPORTED_PERIOD")
    if re.search(r"\b(vs|versus|compare|comparison)\b", question, re.I):
        # Use the existing validated date grammar, without a fabricated merchant subject.
        dates = re.findall(
            r"(?:" + "|".join(calendar.month_name[1:]) + r")\s+20\d{2}|\b20\d{2}\b", question, re.I
        )
        plan = comparison_plan("compare meter " + " vs ".join(dates))
        if not plan:
            raise ValueError("UNSUPPORTED_PERIOD")
        return [plan.period_a, plan.period_b]
    bounds = requested_dates(question)
    if not bounds:
        raise ValueError("MISSING_PERIOD")
    return [bounds]


def local_energy(question, periods):
    config, _ = load_config()
    engine = readonly_engine()
    try:
        before = source_fingerprints(engine, config)
        queries = Queries(session_factory=lambda: readonly_session(engine))
        solar = bool(re.search(r"solar|panel|aurinko", question, re.I))
        records, lines, missing = [], [], []
        for bounds in periods:
            label = f"{bounds.date_from} to {bounds.date_to}"
            if solar:
                try:
                    value = queries.energy(
                        EnergyQuery(**bounds.model_dump(), metric="solar_export_kwh")
                    )
                    records.append(
                        {"source": "Local energy readings", **value.model_dump(mode="json")}
                    )
                    lines.append(f"{label}: measured solar export {value.total} kWh.")
                except Exception:
                    missing.append((bounds, "Vattenfall"))
            else:
                for provider in ("Vattenfall", "Elenia"):
                    value = queries.invoices(
                        InvoiceQuery(**bounds.model_dump(), vendor=provider, limit=50)
                    )
                    records.extend(
                        {"source": "Imported invoices", **r.model_dump(mode="json")}
                        for r in value.items
                    )
                    if (
                        value.items
                        and not value.truncated
                        and all(r.total_eur is not None for r in value.items)
                    ):
                        total = sum((r.total_eur for r in value.items), Decimal(0))
                        lines.append(
                            f"{label} · {provider}: {total:.2f} EUR across "
                            f"{len(value.items)} imported invoices (invoice dates)."
                        )
                    else:
                        missing.append((bounds, provider))
        if source_fingerprints(engine, config) != before:
            raise ValueError("SOURCE_CHANGED_DURING_QUESTION")
        return records, lines, missing
    finally:
        engine.dispose()


def tax_details(question):
    config, _ = load_config()
    engine = readonly_engine()
    try:
        before = source_fingerprints(engine, config)
        bounds = requested_dates(question)
        context = re.search(r"\b(property|forestry|personal)\b", question, re.I)[0].lower()
        value = Queries(session_factory=lambda: readonly_session(engine)).summarize_finances(
            FinanceQuery(**bounds.model_dump(), business_context=context, categories=["TAX"])
        )
        ids = {tid for group in value.groups for tid in group.transaction_ids}
        with readonly_session(engine) as db:
            transactions = [
                {
                    "source": "Local bank transaction",
                    "transaction_id": str(t.id),
                    "booking_date": str(t.booking_date),
                    "amount": str(t.amount),
                    "currency": t.currency,
                    "counterparty": t.normalized_counterparty,
                    "message": t.message,
                    "source_file": t.source_file,
                    "category": "TAX",
                    "business_context": context.upper(),
                    "authority": "Current human-confirmed review",
                }
                for t in db.scalars(
                    select(Transaction)
                    .where(Transaction.id.in_(ids))
                    .order_by(Transaction.booking_date, Transaction.id)
                )
            ]
        if before != source_fingerprints(engine, config):
            raise ValueError("SOURCE_CHANGED_DURING_QUESTION")
        return response(
            f"{value.transaction_count} imported {context} transactions have a current "
            f"human-confirmed tax category in {bounds.date_from.year}.",
            records=transactions,
            breakdown=[
                f"{g.currency}: {g.debit_total} paid, {g.credit_total} received."
                for g in value.context_totals
            ],
            sources=[
                {
                    "label": "Local structured data",
                    "status": "used",
                    "detail": (
                        "Current authoritative review state; deterministic totals. Gmail "
                        "was not searched."
                    ),
                }
            ],
            limits=[
                "A tax category does not establish deductibility or complete statement coverage."
            ],
        )
    finally:
        engine.dispose()


async def answer_workspace(pilot, question, previous_session=None):
    original = question
    context = None
    if re.search(r"\b(attachment|attachments|attached files)\b", question, re.I) and re.search(
        r"\b(open|read|analy[sz]e|inspect|extract)\b", question, re.I
    ):
        from tapio.pilot.attachment_answers import analyze_attachments

        selected = []
        if previous_session:
            saved = json.loads(
                (pilot.history.directory(previous_session) / "question.json").read_text()
            )
            selected = [
                r
                for r in saved.get("response", {}).get("supporting_records", [])
                if r.get("source")
                in {"Gmail read-only", "Stored email evidence", "Email PDF attachment"}
            ]
        result = await analyze_attachments(pilot, question, selected)
        pilot.history.save(
            result.session.id,
            {
                "question": original,
                "previous_session": previous_session,
                "response": result.model_dump(mode="json"),
            },
        )
        return result
    if previous_session:
        path = pilot.history.directory(previous_session) / "question.json"
        if not path.exists():
            raise ValueError("UNKNOWN_PREVIOUS_QUESTION")
        saved = json.loads(path.read_text())
        previous = saved.get("question", "")
        resolved = followup_question(question, previous)
        if resolved is None:
            result = response(
                "Please name the subject and period for this follow-up.",
                limits=[
                    "The earlier question does not provide an unambiguous scope for this request."
                ],
                suggestions=["Include the supplier or context and a year."],
            )
            pilot.history.save(
                result.session.id,
                {"question": original, "response": result.model_dump(mode="json")},
            )
            return result
        if resolved != question:
            context = resolved
            question = resolved
    energy = bool(
        re.search(
            r"\b(solar\w*|solar panel|electricity bills?|electricity invoices?|aurinko\w*)\b",
            question,
            re.I,
        )
    )
    if re.search(r"\bforestry\b", question, re.I) and re.search(
        r"\b(deduct\w*|vat|iva)\b", question, re.I
    ):
        from tapio.pilot.tax_suggestions import GUIDANCE, VAT_GUIDANCE, forestry_candidates

        records, totals = await asyncio.to_thread(forestry_candidates, question)
        result = response(
            f"{len(records)} confirmed forestry expenses to review for possible deductions.",
            records=records,
            breakdown=totals,
            sources=[
                {
                    "label": "Local bank records",
                    "status": "used",
                    "detail": (
                        "Current confirmed forestry context only; "
                        "personal, property and unresolved contexts excluded."
                    ),
                },
                {"label": "Vero forestry deductions", "status": "guidance", "detail": GUIDANCE},
                {"label": "Vero VAT deductions", "status": "guidance", "detail": VAT_GUIDANCE},
            ],
            limits=[
                "Suggestions are not tax decisions. No labels or tax records were changed.",
                "VAT cannot be inferred from a bank payment. Verify the invoice and eligibility.",
                "Scope: imported transactions only; all imported dates if no year was specified.",
            ],
        )
    elif re.fullmatch(r"Show (property|forestry|personal) tax payments in 20\d{2}", question, re.I):
        result = await asyncio.to_thread(tax_details, question)
    elif energy:
        try:
            periods = energy_periods(question)
        except ValueError:
            result = response(
                "Specify a calendar year or month for the energy evidence.",
                suggestions=["Compare electricity bills October 2025 vs October 2026."],
            )
        else:
            records, lines, missing = await asyncio.to_thread(local_energy, question, periods)
            lines.append(
                "Each energy result summarizes its requested period; "
                "it is not a single bank transaction."
            )
            sources = [
                {
                    "label": "Local energy/document data",
                    "status": "used" if records else "checked",
                    "detail": (
                        "Physical energy and invoice evidence; not a bank merchant comparison."
                    ),
                }
            ]
            limits = (
                ["Solar export is electricity sold to the grid, not total panel production."]
                if re.search(r"solar|panel|aurinko", question, re.I)
                else [
                    (
                        "Invoice values are separate from bank payments; imported "
                        "invoices do not establish full period coverage."
                    )
                ]
            )
            for bounds, provider in missing:
                if bounds.date_from.month != bounds.date_to.month and (
                    bounds.date_from.month,
                    bounds.date_to.month,
                ) != (1, 12):
                    limits.append(
                        f"Local {provider} evidence is incomplete for {bounds.date_from} to "
                        f"{bounds.date_to}. Ask for a missing month to search its email evidence; "
                        "the search was not broadened to the whole year."
                    )
                    continue
                period = (
                    f"{calendar.month_name[bounds.date_from.month]} {bounds.date_from.year}"
                    if bounds.date_from.month == bounds.date_to.month
                    else str(bounds.date_from.year)
                )
                # The owner explicitly identified Vattenfall receipts as the missing energy source.
                lookup = await answer_question(
                    pilot, f"Find email receipts from {provider} in {period}"
                )
                records.extend(lookup.supporting_records)
                sources.extend(lookup.sources)
                limits.extend(lookup.limitations)
            result = response(
                (
                    "Available energy evidence is shown below. A complete comparison "
                    "is not established."
                )
                if missing
                else "The available local energy evidence is shown below.",
                records=records,
                sources=sources,
                limits=list(dict.fromkeys(limits)),
                breakdown=lines,
                suggestions=[
                    "For bank cash flow, ask how much you paid a named supplier in one year."
                ],
            )
    elif (
        re.search(r"\belenia\b", question, re.I)
        and re.search(r"\bvattenfall\b", question, re.I)
        and re.search(r"\b(transactions|payments|paid)\b", question, re.I)
        and not re.search(r"\b(email|receipt|invoice|contract|document)\b", question, re.I)
    ):
        try:
            periods = energy_periods(question)
            if len(periods) != 1:
                raise ValueError("ONE_PERIOD_REQUIRED")
        except ValueError:
            result = response("Specify one calendar year or month for the two suppliers.")
        else:
            bounds = periods[0]
            period = (
                f"{calendar.month_name[bounds.date_from.month]} {bounds.date_from.year}"
                if bounds.date_from.month == bounds.date_to.month
                else str(bounds.date_from.year)
            )
            parts = [
                await answer_question(pilot, f"Find {supplier} transactions in {period}")
                for supplier in ("Elenia", "Vattenfall")
            ]
            result = response(
                "Local bank results are shown separately. "
                "These do not establish whether new bills arrived by email.",
                breakdown=[
                    supplier + ": " + (p.direct_answer or p.answer)
                    for supplier, p in zip(("Elenia", "Vattenfall"), parts, strict=True)
                ],
                suggestions=[f"Find Elenia and Vattenfall invoices in email in {period}"],
                records=[
                    r
                    for p in parts
                    for r in (p.supporting_records or p.optional_details.get("transactions", []))
                ],
                sources=[s for p in parts for s in p.sources],
                limits=list(dict.fromkeys(v for p in parts for v in p.limitations)),
            )
    else:
        result = await answer_question(pilot, question)
        if context:
            result = result.model_copy(
                update={
                    "relevant_breakdown": [
                        "Follow-up scope: " + context,
                        *result.relevant_breakdown,
                    ]
                }
            )
        return result
    if context:
        result = result.model_copy(
            update={
                "relevant_breakdown": ["Follow-up scope: " + context, *result.relevant_breakdown]
            }
        )
    pilot.history.save(
        result.session.id,
        {
            "question": question,
            "original_question": original,
            "previous_session": previous_session,
            "response": result.model_dump(mode="json"),
        },
    )
    return result
