"""Validate once, execute bounded tools, and present scoped evidence without a second planner."""

import asyncio
import re
import time
from datetime import date, timedelta
from decimal import Decimal

from integrations.gmail.models import Search
from tapio.pilot import planned_retrieval as retrieval
from tapio.pilot.attachment_answers import analyze_attachments
from tapio.pilot.config import readonly_engine, readonly_session
from tapio.pilot.conversation import (
    contract_followup,
    exclusion_followup,
    followup_plan,
    is_followup,
    load_previous,
    period_followup_question,
    same_period,
    selection_exclusions,
)
from tapio.pilot.evidence_routing import (
    accepted_answer,
    gmail_lookup,
    local_evidence,
    needs_gmail_auth,
)
from tapio.pilot.invoice_comparison import add_evidence_comparison, compare_invoices, reference_key
from tapio.pilot.query_plan import Period, QueryPlan, interpret, selected_attachment_request
from tapio.pilot.workspace_answers import response, session


def scope_lines(plan):
    lines = [f"Period: {p.date_from} to {p.date_to}" for p in plan.periods]
    if not plan.periods and plan.intent in {"TRANSACTION_SEARCH", "PERIOD_COMPARISON"}:
        lines.append("Period: all imported transaction dates")
    if plan.expense_only:
        lines.append("Expense view: excludes confirmed TAX and TRANSFER categories.")
    for label, values in [
        ("Context", plan.contexts),
        ("Category", plan.categories),
        ("Merchant", plan.merchants),
        ("Concept", plan.concepts),
        ("Destination", plan.locations),
    ]:
        if values:
            lines.append(label + ": " + ", ".join(values))
    for e in plan.exclusions:
        lines.append("Exclude: " + " / ".join(v for v in [e.context, e.category] if v))
    return lines


def failed(message, category):
    result = response(message)
    result = result.model_copy(update={"failure_category": category})
    result = result.model_copy(
        update={
            "evidence_state": "NEEDS_NARROWING"
            if category == "INTERPRETATION_FAILED"
            else "PARTIAL_COVERAGE"
        }
    )
    result = result.model_copy(update={"evidence_states": [result.evidence_state]})
    return result


def load_transactions(plan):
    engine = readonly_engine()
    try:
        with readonly_session(engine) as db:
            return retrieval.transactions(db, plan)
    finally:
        engine.dispose()


def load_energy(plan):
    engine = readonly_engine()
    try:
        return retrieval.energy(plan, lambda: readonly_session(engine))
    finally:
        engine.dispose()


def energy_answer(plan, records, missing):
    lines = []
    for p in plan.periods:
        selected = [
            r
            for r in records
            if str(p.date_from) <= r["date_from"] <= r["date_to"] <= str(p.date_to)
        ]
        if not selected:
            lines.append(f"{p.date_from} to {p.date_to}: no measured coverage available.")
            continue
        total = sum((Decimal(r["total"]) for r in selected), Decimal(0))
        label = "consumption" if plan.metric == "CONSUMPTION" else "solar export"
        lines.append(
            f"{p.date_from} to {p.date_to}: {total:.3f} kWh {label}"
            + (" (available months only)." if missing else ".")
        )
    limits = ["Missing measured coverage: " + "; ".join(missing)] if missing else []
    if plan.metric == "SOLAR_PRODUCTION":
        limits.append(
            "These readings measure export to the grid. Total panel production is not "
            "available from this source."
        )
    result = response(
        "; ".join(lines),
        records=records,
        limits=limits,
        sources=[
            {
                "label": "Local energy readings",
                "status": "used" if records else "checked",
                "detail": "Each requested month checked independently; deterministic totals.",
            }
        ],
    )
    if missing:
        result = result.model_copy(update={"failure_category": "PARTIAL_PERIOD_COVERAGE"})
    return result


def transaction_answer(plan, records, unresolved):
    lines, missing_periods = [], []
    for p in plan.periods:
        rows = [r for r in records if str(p.date_from) <= r["booking_date"] <= str(p.date_to)]
        if not rows:
            missing_periods.append(f"{p.date_from} to {p.date_to}")
        for currency in sorted({r["currency"] for r in rows}):
            amounts = [Decimal(r["amount"]) for r in rows if r["currency"] == currency]
            total = sum(amounts, Decimal(0))
            if plan.metric == "OUTFLOW" or plan.action == "TAX_SUGGESTION":
                total = -sum((v for v in amounts if v < 0), Decimal(0))
            lines.append(
                f"{p.date_from} to {p.date_to}: {len(amounts)} transactions, "
                f"{total:.2f} {currency}."
            )
    # Group arithmetic uses the same scoped rows as the displayed evidence.
    scopes = [
        (
            f"{p.date_from} to {p.date_to}",
            [r for r in records if str(p.date_from) <= r["booking_date"] <= str(p.date_to)],
        )
        for p in plan.periods
    ] or [("All imported dates", records)]
    for label, rows in scopes:
        for currency in sorted({r["currency"] for r in rows}):
            selected = [r for r in rows if r["currency"] == currency]

            def amount(items):
                return sum(
                    (
                        max(-Decimal(r["amount"]), Decimal(0))
                        if plan.metric == "OUTFLOW"
                        else Decimal(r["amount"])
                        for r in items
                    ),
                    Decimal(0),
                )

            total = amount(selected)
            if not plan.periods:
                lines.append(f"{label}: {len(selected)} transactions, {total:.2f} {currency}.")
            if {"ELECTRICITY", "GRID_DISTRIBUTION"}.issubset(set(plan.categories)):
                for category, title in [
                    ("ELECTRICITY", "Energy supplier"),
                    ("GRID_DISTRIBUTION", "Grid distribution"),
                ]:
                    subtotal = amount([r for r in selected if r["category"] == category])
                    lines.append(f"{label} — {title}: {subtotal:.2f} {currency}.")
            for merchant in plan.share_merchants:
                subset = [
                    r
                    for r in selected
                    if retrieval.matching_terms(
                        {"counterparty": r["counterparty"]}, retrieval.aliases(merchant)
                    )
                ]
                subtotal = amount(subset)
                share = f"{subtotal / total * 100:.1f}%" if total else "undefined (zero total)"
                lines.append(
                    f"{label} — {merchant}: {subtotal:.2f} of {total:.2f} {currency}, {share}."
                )
    noun = "tax review candidates" if plan.action == "TAX_SUGGESTION" else "matching transactions"
    limits = []
    if "TRAVEL" in plan.categories and plan.periods:
        lines.append(
            "Dates refer to payments, not travel dates. Tickets paid earlier are outside "
            "this period. Search forestry flights, trains and buses across the full year "
            "to check earlier ticket payments (for example Finnair)."
        )
    for p in plan.periods:
        months = [(a.strftime("%Y-%m"), a, b) for a, b in retrieval.monthly_periods(p)]
        matched = [
            label
            for label, a, b in months
            if any(str(a) <= r["booking_date"] <= str(b) for r in records)
        ]
        absent = [label for label, _, _ in months if label not in matched]
        if matched and absent and (p.date_to - p.date_from).days < 365:
            lines.append(
                "Matching booking months: "
                + ", ".join(matched)
                + ". No matching transactions in: "
                + ", ".join(absent)
                + "."
            )
    if unresolved:
        reasons = sorted({r["missing"] for r in unresolved})
        limits.append(
            f"{len(unresolved)} otherwise matching transactions lack required evidence: "
            + " ".join(reasons)
        )
    if len(plan.periods) > 1 and missing_periods:
        limits.append("No matching transactions for: " + "; ".join(missing_periods))
    result = response(
        f"{len(records)} {noun}." if records else "No transactions satisfy all requested filters.",
        records=records,
        breakdown=lines,
        limits=limits,
        sources=[
            {
                "label": "Local bank records and current reviews",
                "status": "used" if records else "checked",
                "detail": "Current category/context; linked local invoices checked.",
            }
        ],
    )
    if not records:
        result = result.model_copy(
            update={
                "failure_category": "MATCHING_RECORDS_INSUFFICIENT_EVIDENCE"
                if unresolved
                else "NO_MATCHING_RECORDS"
            }
        )
    elif missing_periods:
        result = result.model_copy(update={"failure_category": "PARTIAL_PERIOD_COVERAGE"})
    return result


async def supporting_mail(pilot, plan, records, unresolved, directory):
    """Positive sender + period only; never infer authoritative labels from messages."""
    selected = records + unresolved
    names = plan.merchants or list(
        dict.fromkeys(r["counterparty"] for r in selected if r.get("counterparty"))
    )
    if not names or not plan.periods:
        missing = (
            "Name the merchant or email sender to check receipts for this date."
            if plan.periods
            else "Name an email sender and date range to check Gmail evidence."
        )
        return [], [missing], []
    evidence, limits, sources = [], [], []
    checks = 0
    for name in names:
        # Only a source/user-derived sender term, never model-generated Gmail operators.
        # Official sender domains: vr.fi/asiakaspalvelu and OnniBus developer contact.
        sender_domains = {
            "vr": "vr.fi",
            "vr oy": "vr.fi",
            "onnibuscom oy": "onnibus.com",
            "onnibus.com oy": "onnibus.com",
            "onnibus": "onnibus.com",
        }
        sender = sender_domains.get(name.casefold(), re.sub(r"[^\w@.-]", "", name.split()[0]))
        if len(sender) < 3:
            limits.append(f"A more specific email sender is needed for {name}.")
            continue
        periods = plan.periods
        dates = sorted(
            {
                date.fromisoformat(r["booking_date"])
                for r in selected
                if r.get("booking_date") and r.get("counterparty") == name
            }
        )
        if dates:
            windows = []
            for day in dates:
                start, end = day - timedelta(days=7), day + timedelta(days=7)
                if windows and start <= windows[-1][1]:
                    windows[-1] = (windows[-1][0], max(end, windows[-1][1]))
                else:
                    windows.append((start, end))
            periods = [Period(date_from=start, date_to=end) for start, end in windows]
        for p in periods:
            if checks >= 3:
                limits.append(
                    "Checked three sender/period combinations; narrow the scope to "
                    "check remaining evidence."
                )
                return evidence, limits, sources
            checks += 1
            search = Search(
                query=(
                    f"from:{sender} after:{p.date_from:%Y/%m/%d} "
                    f"before:{p.date_to + timedelta(days=1):%Y/%m/%d}"
                ),
                max_results=5,
            )
            try:
                found, limited = await gmail_lookup(search, directory)
            except Exception as exc:
                reason = (
                    "Gmail authorization needs reconnecting; renew the existing read-only "
                    "authorization and retry."
                    if needs_gmail_auth(exc)
                    else "The Gmail lookup could not complete; check the connection and retry."
                )
                limits.append(
                    f"Gmail evidence for {name} is unavailable. {reason} "
                    "This is not a no-match result."
                )
                sources.append(
                    {
                        "label": "Gmail read-only",
                        "status": "authentication required"
                        if needs_gmail_auth(exc)
                        else "unavailable",
                        "detail": reason,
                    }
                )
                continue
            for record in found:
                record["evidence_status"] = (
                    "Candidate message; transaction association not confirmed"
                )
                record["requested_sender"] = name
            evidence.extend(found)
            sources.append(
                {
                    "label": "Gmail read-only",
                    "status": "used" if found else "checked",
                    "detail": f"{name}, {p.date_from}–{p.date_to}: {len(found)} candidates.",
                }
            )
            if limited:
                limits.append(
                    f"More messages exist for {name}; only the bounded selected messages were read."
                )
    return evidence, limits, sources


async def execute(pilot, plan, question, previous, directory):
    if plan.clarification:
        return failed(plan.clarification, "INTERPRETATION_FAILED")
    if is_followup(question) and re.search(r"customer|account.holder", question, re.I):
        saved = (previous or {}).get("records", [])
        docs = [r for r in saved if r.get("source") == "Email PDF attachment"]
        if not docs:
            docs = [
                r
                for r in ((previous or {}).get("focus") or {}).get("records", [])
                if r.get("source") == "Email PDF attachment"
            ]
        if not docs:
            return failed(
                "The selected invoices have no extracted customer fields yet. "
                "Analyze their PDF attachments first.",
                "INTERPRETATION_FAILED",
            )
        lines = [
            f"{r.get('filename', 'PDF')}: {r.get('customer') or 'Customer not extracted'}."
            for r in docs
        ]
        return response(
            " ".join(lines),
            records=docs,
            sources=[
                {
                    "label": "Previously selected PDFs",
                    "status": "used",
                    "detail": "Customer named in each saved document; no new search.",
                }
            ],
        )
    if plan.intent == "UNSUPPORTED":
        return failed(
            "I could not represent this request with the available evidence tools. "
            "Please specify the records or metric you need.",
            "INTERPRETATION_FAILED",
        )
    if plan.intent == "ATTACHMENT_ANALYSIS":
        selected = (
            [r for r in (previous or {}).get("records", []) if r.get("source") == "Gmail read-only"]
            if selected_attachment_request(question)
            else []
        )
        if selected_attachment_request(question) and not selected:
            return failed(
                "There are no saved emails selected for this follow-up. "
                "Find the intended merchant's emails first, then ask to check their PDFs.",
                "INTERPRETATION_FAILED",
            )
        if not selected:
            selected, limits, sources = await supporting_mail(pilot, plan, [], [], directory)
            if not selected:
                return failed(
                    " ".join(limits) or "No email attachments matched the requested scope.",
                    "GMAIL_EVIDENCE_NOT_FOUND",
                )
        result = await analyze_attachments(pilot, question, selected)
        # Full text remains in the private attachment cache, not normal answers.
        for record in result.supporting_records:
            if "excerpt" in record:
                record.pop("excerpt")
                record["missing"] = "Invoice fields could not be validated for this PDF layout."
                result = result.model_copy(
                    update={"failure_category": "ATTACHMENT_EVIDENCE_INSUFFICIENT"}
                )
        result = result.model_copy(
            update={
                "limitations": [
                    s
                    for s in result.limitations
                    if not s.startswith(("Printed VAT", "Solar export"))
                ]
            }
        )
        # Retain the exact message selection for another attachment follow-up.
        result.supporting_records.extend(selected)
        return add_evidence_comparison(result)
    if plan.metric in {"SOLAR_EXPORT", "SOLAR_PRODUCTION", "CONSUMPTION"}:
        if plan.contexts or plan.categories or plan.merchants or plan.locations or plan.concepts:
            return failed(
                "The energy meter cannot be filtered by transaction context, merchant, "
                "or travel constraints.",
                "INTERPRETATION_FAILED",
            )
        records, missing = await asyncio.to_thread(load_energy, plan)
        result = energy_answer(plan, records, missing)
        if (
            plan.metric in {"SOLAR_EXPORT", "SOLAR_PRODUCTION"}
            and "consumption" in question.lower()
        ):
            consumption_plan = plan.model_copy(update={"metric": "CONSUMPTION"})
            consumption, consumption_missing = await asyncio.to_thread(
                load_energy, consumption_plan
            )
            result.supporting_records.extend(consumption)
            result.limitations.extend(
                ["Missing consumption coverage: " + "; ".join(consumption_missing)]
                if consumption_missing
                else []
            )
            for p in plan.periods:

                def scoped(items, p=p):
                    return [
                        r
                        for r in items
                        if str(p.date_from) <= r["date_from"] <= r["date_to"] <= str(p.date_to)
                    ]

                exports, usage = scoped(records), scoped(consumption)

                # Ratios require identical measured coverage; never mix partial periods.
                def dates(items):
                    return {(r["date_from"], r["date_to"]) for r in items}

                if not exports or dates(exports) != dates(usage) or missing or consumption_missing:
                    result.limitations.append(
                        f"{p.date_from} to {p.date_to}: ratio unavailable "
                        "without complete matching coverage."
                    )
                    continue
                numerator = sum((Decimal(r["total"]) for r in exports), Decimal(0))
                denominator = sum((Decimal(r["total"]) for r in usage), Decimal(0))
                ratio = (
                    f"{numerator / denominator * 100:.1f}%"
                    if denominator
                    else "undefined (zero consumption)"
                )
                result.relevant_breakdown.append(
                    f"{p.date_from} to {p.date_to}: consumption {denominator:.3f} kWh; "
                    f"export / consumption {ratio}. "
                    "This is not total solar production or self-sufficiency."
                )
        return result
    if plan.intent == "DOCUMENT_LOOKUP":
        if contract_followup(question):
            saved = ((previous or {}).get("focus") or {}).get("records", [])
            direct = accepted_answer(question, saved)
            return response(
                direct
                or "The selected contract evidence does not establish a single answer "
                "to that question. Specify the contract or the field to check.",
                records=saved,
                sources=[
                    {
                        "label": "Previously selected contract evidence",
                        "status": "used",
                        "detail": "Saved contract scope; no new Gmail search.",
                    }
                ],
                limits=[]
                if direct
                else ["A single accepted contract date could not be established."],
            )
        if plan.contexts or plan.categories or plan.locations or plan.concepts:
            return failed(
                "Please identify a transaction to associate these document constraints "
                "with its confirmed classification.",
                "INTERPRETATION_FAILED",
            )
        # Use existing accepted knowledge/document readers, with typed scope serialized by code.
        canonical = " ".join([question, *plan.merchants, *plan.evidence_requirements]).lower()
        if len(plan.periods) == 1:
            p = plan.periods[0]
            if p.date_from.month == p.date_to.month:
                canonical += f" {p.date_from:%B %Y}"
            elif p.date_from.month == 1 and p.date_to.month == 12:
                canonical += f" {p.date_from.year}"
            else:
                return failed(
                    "Please request one month or calendar year for document lookup.",
                    "INTERPRETATION_FAILED",
                )
        elif len(plan.periods) > 1:
            return failed("Please request one document period at a time.", "INTERPRETATION_FAILED")
        records, sources = await asyncio.to_thread(local_evidence, canonical)
        direct = accepted_answer(question, records)
        limits = []
        if not records or "EMAIL" in plan.evidence_requirements:
            mail, limits, more = await supporting_mail(pilot, plan, [], [], directory)
            records.extend(mail)
            sources.extend(more)
        result = response(
            direct
            or (
                f"Found {len(records)} evidence records."
                if records
                else "No matching evidence records found."
            ),
            records=records,
            sources=sources,
            limits=limits,
        )
        if not records:
            result = result.model_copy(
                update={
                    "failure_category": "GMAIL_EVIDENCE_NOT_FOUND"
                    if any(s["label"] == "Gmail read-only" for s in sources)
                    else "NO_MATCHING_RECORDS"
                }
            )
        return result
    if plan.intent == "PAYMENT_PURPOSE" and not plan.periods:
        return failed("Which payment date or period should I inspect?", "INTERPRETATION_FAILED")
    records, unresolved = await asyncio.to_thread(load_transactions, plan)
    if is_followup(question) and not same_period(question):
        focus = (previous or {}).get("focus") or {}
        ids = {r["transaction_id"] for r in focus.get("records", []) if r.get("transaction_id")}
        records = [r for r in records if r["transaction_id"] in ids]
        unresolved = [r for r in unresolved if r["transaction_id"] in ids]
        if exclusion_followup(question):
            _, merchants = selection_exclusions(question, focus)
            records = [r for r in records if r.get("counterparty") not in merchants]
            unresolved = [r for r in unresolved if r.get("counterparty") not in merchants]
    if is_followup(question) and re.search(
        r"non.finnish|spanish|foreign.*(?:card|account)", question, re.I
    ):
        candidates = [r for r in records if r.get("source_system") == "SAMPO"]
        return response(
            f"{len(candidates)} of the selected transactions came through the Sampo import.",
            records=candidates,
            limits=[
                "Sampo identifies the import source, not the bank's country. "
                "Check the displayed source account; "
                "non-Finnish origin is not independently verified."
            ],
            sources=[
                {
                    "label": "Imported transaction provenance",
                    "status": "used",
                    "detail": "Source system and account from the original import.",
                }
            ],
        )
    result = transaction_answer(plan, records, unresolved)
    needs_mail = (
        "EMAIL" in plan.evidence_requirements
        or (
            bool(plan.evidence_requirements)
            and any(not r.get("supporting_evidence") for r in records)
        )
        or (plan.intent == "PAYMENT_PURPOSE" and bool(records))
        or bool(unresolved)
        or (plan.evidence_mode == "INSPECT" and bool(records))
    )
    if plan.evidence_mode == "GAPS" and "EMAIL" not in plan.evidence_requirements:
        needs_mail = False
    if plan.intent == "PAYMENT_PURPOSE" and records:
        for record in records:
            if record.get("message"):
                result.evidence_summary.append(
                    record["booking_date"] + " bank message: " + record["message"]
                )
        if plan.merchants:
            knowledge, sources = await asyncio.to_thread(
                local_evidence, " ".join(plan.merchants) + " payment purpose"
            )
            result.supporting_records.extend(knowledge)
            result.sources.extend(sources)
            if knowledge:
                result.evidence_summary.append(
                    "Stored knowledge is shown as supporting evidence; it does not "
                    "change classification."
                )
    mail = []
    attachment_lines = []
    if needs_mail:
        mail, limits, sources = await supporting_mail(pilot, plan, records, unresolved, directory)
        result.supporting_records.extend(mail)
        result.sources.extend(sources)
        result.limitations.extend(limits)
        if mail and ("ATTACHMENT" in plan.evidence_requirements or plan.evidence_mode == "INSPECT"):
            attachments = await analyze_attachments(pilot, question, mail)
            for item in attachments.supporting_records:
                if "excerpt" in item:
                    item.pop("excerpt")
                    item["missing"] = "Structured fields could not be validated for this PDF."
                if item.get("reference"):
                    item["message_link"] = (
                        "https://mail.google.com/mail/u/0/#all/" + item["reference"]
                    )
            result.supporting_records.extend(attachments.supporting_records)
            result.sources.extend(attachments.sources)
            result.limitations.extend(
                s
                for s in attachments.limitations
                if not s.startswith(("Printed VAT", "Solar export"))
            )
            attachment_lines = attachments.relevant_breakdown
            result.relevant_breakdown.extend(attachment_lines)

        if mail:
            result.evidence_summary.append(
                f"Gmail added {len(mail)} candidate messages. "
                "Their association with the payments needs confirmation."
            )
        elif not limits:
            result = result.model_copy(update={"failure_category": "GMAIL_EVIDENCE_NOT_FOUND"})
            result.limitations.append("No Gmail evidence matched the checked sender/period scope.")
    if plan.action == "FIND_EVIDENCE" and plan.intent != "PAYMENT_PURPOSE" and records:
        matched, unknown = [], []
        for row in records:
            reference = row.get("payment_reference") or ""
            linked_mail = [
                m
                for m in mail
                if len(reference) >= 6
                and re.search(
                    r"(?<!\w)" + re.escape(reference_key(reference)) + r"(?!\w)",
                    m.get("excerpt", ""),
                )
            ]
            local_links = [
                e for e in row.get("supporting_evidence", []) if e.get("link_status") == "CONFIRMED"
            ]
            if linked_mail or (
                local_links
                and (plan.evidence_mode != "REQUIRE" or "EMAIL" not in plan.evidence_requirements)
            ):
                row["supporting_evidence"] = [*row.get("supporting_evidence", []), *linked_mail]
                if linked_mail:
                    row["evidence_match"] = "Exact bank reference found in email text"
                matched.append(row)
            else:
                unknown.append(
                    {
                        **row,
                        "missing": "No linked evidence establishes document coverage.",
                    }
                )
        displayed = [*matched, *unknown] if plan.evidence_mode == "REQUIRE" else matched
        for row in unknown:
            row["check_next"] = "No confirmed receipt link; candidate emails are shown separately."
        if plan.evidence_mode in {"INSPECT", "GAPS"}:
            for row in unknown:
                row["check_next"] = (
                    "No confirmed invoice or exact-reference email link; "
                    "check the receipt and purpose."
                )
            displayed = unknown if plan.evidence_mode == "GAPS" else [*matched, *unknown]
        scoped = transaction_answer(
            plan,
            displayed,
            unresolved if plan.evidence_mode != "REQUIRE" else [*unresolved, *unknown],
        )
        if plan.evidence_mode == "REQUIRE" and unknown:
            text = (
                f"{len(records)} payments found; {len(matched)} have linked evidence. "
                f"{len(mail)} candidate emails retrieved; unlinked messages do not yet "
                "establish receipt coverage for the remaining payments."
            )
            scoped = scoped.model_copy(
                update={
                    "answer": text,
                    "direct_answer": text,
                    "failure_category": "MATCHING_RECORDS_INSUFFICIENT_EVIDENCE"
                    if not matched
                    else scoped.failure_category,
                }
            )
        if plan.evidence_mode == "GAPS":
            text = f"{len(unknown)} candidate transactions have weak or missing linked evidence."
            scoped = scoped.model_copy(update={"answer": text, "direct_answer": text})
            scoped.limitations.append(
                "These are classification-based candidates. A specific planting trip "
                "is not established without trip dates or linked trip evidence."
                if "planting" in question.lower()
                else "Missing linked evidence does not prove that a receipt does not exist."
            )
        elif plan.evidence_mode == "INSPECT" and unknown:
            scoped.limitations.append(
                "The bank payments exist, but the available links do not yet explain "
                "their separate purposes. Check invoice numbers and billing periods."
            )
        result = scoped.model_copy(
            update={
                "sources": result.sources,
                "supporting_records": [
                    *displayed,
                    *[r for r in result.supporting_records if not r.get("transaction_id")],
                ],
                "relevant_breakdown": [*scoped.relevant_breakdown, *attachment_lines],
                "limitations": [*scoped.limitations, *result.limitations],
                "evidence_summary": result.evidence_summary,
            }
        )
    if plan.evidence_mode == "INSPECT" and records:
        comparison, matched_ids = compare_invoices(records, result.supporting_records)
        if comparison:
            result.relevant_breakdown.extend(comparison)
            if len(matched_ids) == len(records) and len(records) > 1:
                text = "The payments match separate invoices by reference and amount. " + " ".join(
                    comparison
                )
                result = result.model_copy(update={"answer": text, "direct_answer": text})
                result = result.model_copy(
                    update={
                        "limitations": [
                            s
                            for s in result.limitations
                            if not s.startswith("The bank payments exist")
                        ]
                    }
                )
    if plan.intent == "PAYMENT_PURPOSE" and records:
        result = result.model_copy(
            update={
                "answer": "Matching payments and purpose evidence are shown below.",
                "direct_answer": "Matching payments and purpose evidence are shown below.",
            }
        )
    return add_evidence_comparison(result)


async def answer_planned(pilot, question, previous_session=None, *, planner=interpret):
    current = session()
    start = time.monotonic()
    previous = None
    plan = None
    model = None
    previous = load_previous(pilot.history, previous_session)
    try:
        model = pilot.model_factory(pilot.history.directory(current.id) / "protocol")
        # Only previous scope goes to the interpreter; private evidence stays local.
        plan = None if selected_attachment_request(question) else followup_plan(question, previous)
        if plan is None:
            plan = await planner(
                model,
                period_followup_question(question, previous) if same_period(question) else question,
                previous={k: previous[k] for k in ("question", "plan")} if previous else None,
            )
        plan = QueryPlan.model_validate(plan)
    except Exception:
        result = failed(
            "I could not interpret the requested scope. Please specify the subject, "
            "context and period.",
            "INTERPRETATION_FAILED",
        )
    else:
        try:
            result = await execute(
                pilot, plan, question, previous, pilot.history.directory(current.id)
            )
        except ValueError as exc:
            if "LEGACY_REVIEW_CHANGED" in str(exc):
                result = failed(
                    "Stored review history conflicts with its source review. These "
                    "classifications need reconciliation before I can use them.",
                    "CONFLICTING_REVIEW_STATE",
                )
            else:
                result = failed(
                    "I could not execute all requested constraints. Please narrow the "
                    "subject or period.",
                    "INTERPRETATION_FAILED",
                )
        result = result.model_copy(
            update={"relevant_breakdown": [*scope_lines(plan), *result.relevant_breakdown]}
        )
        result.optional_details["query_plan"] = plan.model_dump(mode="json")
    if not result.failure_category and not result.limitations:
        result = result.model_copy(
            update={"evidence_state": "SUPPORTED", "evidence_states": ["SUPPORTED"]}
        )
    usage = getattr(model, "usage", [])
    current = current.model_copy(
        update={"model_calls": getattr(model, "request_count", len(usage))}
    )
    current = current.model_copy(
        update={"input_tokens": sum(u.get("usage", {}).get("prompt_tokens", 0) for u in usage)}
    )
    current = current.model_copy(
        update={"output_tokens": sum(u.get("usage", {}).get("completion_tokens", 0) for u in usage)}
    )
    current = current.model_copy(
        update={
            "cached_input_tokens": sum(
                u.get("usage", {}).get("prompt_tokens_details", {}).get("cached_tokens", 0)
                for u in usage
            )
        }
    )
    current = current.model_copy(
        update={
            "estimated_cost_usd": str(
                (
                    Decimal(current.input_tokens - current.cached_input_tokens) * Decimal("0.75")
                    + Decimal(current.cached_input_tokens) * Decimal("0.075")
                    + Decimal(current.output_tokens) * Decimal("4.5")
                )
                / Decimal(1000000)
            )
        }
    )
    current = current.model_copy(update={"usage_complete": current.model_calls == len(usage)})
    current = current.model_copy(update={"latency_seconds": time.monotonic() - start})
    result = result.model_copy(update={"session": current})
    pilot.history.save(
        current.id,
        {
            "question": question,
            "previous_session": previous_session,
            "conversation_focus": (
                previous.get("focus")
                if previous
                and is_followup(question)
                and (
                    (not same_period(question) and not exclusion_followup(question))
                    or result.failure_category not in (None, "NO_MATCHING_RECORDS")
                )
                else {
                    "question": question,
                    "plan": plan.model_dump(mode="json"),
                    "records": result.supporting_records,
                }
                if plan and result.failure_category in (None, "NO_MATCHING_RECORDS")
                else None
            ),
            "query_plan": plan.model_dump(mode="json") if plan else None,
            "response": result.model_dump(mode="json"),
        },
    )
    return result
