"""Question-specific display of validated facts; never retrieve or sum financial rows."""

import json
import re
from decimal import Decimal

CONTEXTS = ("FORESTRY", "PROPERTY", "PERSONAL", "UNKNOWN")
ROW_FIELDS = {
    "booking_date",
    "counterparty",
    "amount",
    "currency",
    "direction",
    "category",
    "business_context",
    "label_authority",
}
DOC_FIELDS = {
    "document_type",
    "document_date",
    "vendor",
    "kind",
    "parser_version",
    "invoice_date",
    "total_eur",
    "subtotal_eur",
    "vat_eur",
    "source_business_context",
    "confirmed_payment_human_contexts",
    "candidate_payment_human_contexts",
    "payment_state",
}
REC_FIELDS = {
    "state",
    "confirmed_paid_eur",
    "confirmed_refund_eur",
    "confirmed_net_eur",
    "human_review_required",
    "candidate_debit_count",
    "candidate_credit_count",
    "candidate_debit_total_eur",
    "candidate_credit_total_eur",
    "candidate_net_outflow_eur",
    "candidate_net_matches_invoice",
    "limitation",
}
GROUP_FIELDS = {
    "business_context",
    "category",
    "currency",
    "debit_total",
    "credit_total",
    "net_cash_flow",
    "transaction_count",
    "confirmed_count",
    "unresolved_count",
}


def amount(value, currency="EUR"):
    number = f"{Decimal(str(value)):,.2f}"
    return ("€" if currency == "EUR" else currency + " ") + number


def category_label(category, income):
    if income and category == "TAX":
        return "Tax-related credit"
    return category.replace("_", " ").capitalize()


def distinct(items, identity):
    """Deduplicate repeated projections; retain distinct sources and conflicting variants."""
    seen, result = set(), []
    for item in items:
        key = (identity(item), json.dumps(item, sort_keys=True, default=str))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def project(item, fields):
    return {k: v for k, v in item.items() if k in fields}


def document_inventory(items):
    merged = []
    for item in items:
        identity = item.get("source_document_id", item.get("id"))
        for existing in merged:
            shared = (existing.keys() & item.keys()) - {"id", "source_document_id"}
            if identity and identity == existing.get("source_document_id", existing.get("id")):
                if all(existing[k] == item[k] for k in shared):
                    existing.update(item)
                    break
        else:
            merged.append(dict(item))
    return merged


def mode_for(question, response, named_subject=None):
    """Select from explicit intent/plan semantics; evidence presence is not intent."""
    from tapio.pilot.subject_identity import eligible_subject, extract_subject, subject_intent

    q = question.lower()
    plan = response.get("EFFECTIVE_PLAN") or response.get("MODEL_PLAN") or {}
    if re.search(r"\b(deduct\w*|tax treatment|tax advice|vat reclaim)\b", q):
        return "TAX_BOUNDARY"
    if eligible_subject(question, named_subject):
        return (
            "FINANCIAL_TOTAL" if subject_intent(question) == "FINANCIAL_TOTAL" else "NAMED_SUBJECT"
        )
    if re.search(r"\b(biggest|most important|prioriti[sz]\w*)\b", q):
        return "QUESTION_TOO_BROAD"
    if re.search(r"\b(coverage|incomplete\w*|complete\w*|missing|imported period)\b", q):
        return "COVERAGE"
    if re.search(r"\b(review|unreviewed|unresolved)\b", q):
        return "TRANSACTION_REVIEW"
    if re.search(r"\b(payment|refund|reconcil\w*|ambigu\w*)\b", q) and re.search(
        r"what.*know|reconcil|ambigu|refund", q
    ):
        return "AMBIGUITY"
    if re.search(r"\b(fixed|spot|cheaper|comparison|compare)\b", q):
        return "COMPARISON"
    if extract_subject(question) is not None:
        return "EVIDENCE_INCOMPLETE"
    if re.search(r"\b(evidence|receipts?|documents?)\b", q):
        return "EVIDENCE_LOOKUP"
    if re.search(
        r"\b(income|expenses?|pay|paid|credits?|debits?|payments?|cost|spent|received)\b", q
    ):
        return "FINANCIAL_TOTAL"
    if plan.get("question_type") == "coverage":
        return "COVERAGE"
    if plan.get("question_type") == "review":
        return "TRANSACTION_REVIEW"
    return "QUESTION_TOO_BROAD"


def transaction_line(row):
    return (
        f"{row.get('booking_date')}: {row.get('counterparty') or 'Counterparty unavailable'}, "
        f"{amount(row['amount'], row.get('currency', 'EUR'))}; "
        f"{row.get('business_context') or 'UNKNOWN'} / {row.get('category') or 'UNKNOWN'}."
    )


def unresolved(row):
    return row.get("label_authority") != "HUMAN_REVIEWED" or any(
        row.get(k) in (None, "UNKNOWN") for k in ("business_context", "category")
    )


def build_cards(question, response, public, named_subject=None):
    # Imported locally to keep the legacy DTO builder independent and unchanged.
    from tapio.pilot.presentation import public_text

    results = response["results"]
    by_tool = {}
    for result in results:
        if result.get("ok"):
            by_tool.setdefault(result["tool"], []).append(result["data"])

    def items(*names):
        return [i for n in names for d in by_tool.get(n, []) for i in d.get("items", [d])]

    banks = distinct(
        by_tool.get("summarize_finances", []),
        lambda x: (
            x.get("date_from"),
            x.get("date_to"),
            x.get("context_filter"),
            tuple(x.get("categories_filter") or []),
        ),
    )
    rows = distinct(items("query_transactions"), lambda x: x.get("id"))
    docs = document_inventory(
        items("list_documents", "get_document_summary", "find_invoices", "get_invoice"),
    )
    recs = distinct(
        [i["reconciliation"] for i in docs if "reconciliation" in i]
        + items("get_invoice_reconciliation"),
        lambda x: x.get("invoice_id"),
    )
    mode = mode_for(question, response, named_subject)
    contexts = [c for c in CONTEXTS if re.search(r"\b" + c + r"\b", question, re.I)]
    context = contexts[0] if len(contexts) == 1 else None
    # Prefer a scoped aggregate if present, otherwise select existing groups from ALL.
    bank = next((b for b in banks if context and b.get("context_filter") == context), None)
    bank = bank or next((b for b in banks if b.get("context_filter") is None), None)
    bank = bank or (banks[0] if banks else None)
    direct = "The retrieved evidence does not establish a direct answer to this question."
    breakdown, summary, notes = [], [], []
    coverage, review = "", ""
    if bank:
        coverage = (
            f"Imported booking dates: {bank.get('observed_first_date') or 'not established'}–"
            f"{bank.get('observed_last_date') or 'not established'}; "
            "this does not prove a complete bank statement or calendar year."
        )
    details = {
        "transactions": [project(r, ROW_FIELDS) for r in rows],
        "documents": [
            project({**d, "payment_state": d.get("reconciliation", {}).get("state")}, DOC_FIELDS)
            for d in docs
        ],
        "reconciliation": [project(r, REC_FIELDS) for r in recs],
        "bank_aggregates": [
            {
                "date_from": b["date_from"],
                "date_to": b["date_to"],
                "context_filter": b.get("context_filter"),
                "groups": [project(g, GROUP_FIELDS) for g in b.get("groups", [])],
                "context_totals": [project(g, GROUP_FIELDS) for g in b.get("context_totals", [])],
            }
            for b in banks
        ],
        "forestry_sales": [
            project(d, {"sale_date", "buyer", "actual_value_eur", "estimated_value_eur"})
            for d in items("query_forestry_sales", "get_forestry_sale")
        ],
        "comparison": [
            {"months": d["months"], "aggregate": d["aggregate"]}
            for d in by_tool.get("get_saved_energy_comparison", [])
        ],
        "coverage": public.coverage.model_dump(mode="json"),
        "human_review": [r.model_dump(mode="json") for r in public.human_review],
        "limitations": public.limitations,
        "note": (
            "All retrieved rows are retained here; retrieval may still cover "
            "only part of the source data."
        ),
    }
    if mode == "FINANCIAL_TOTAL":
        income = bool(re.search(r"\b(income|credits?|receive\w*|reached)\b", question, re.I))
        field = "credit_total" if income else "debit_total"
        totals = [
            g
            for g in (bank or {}).get("context_totals", [])
            if context and g["business_context"] == context
        ]
        groups = [
            g
            for g in (bank or {}).get("groups", [])
            if context and g["business_context"] == context
        ]
        if (
            len(totals) == 1
            and isinstance(totals[0].get("transaction_count"), int)
            and totals[0].get("confirmed_count") == totals[0]["transaction_count"]
            and not bank.get("categories_filter")
        ):
            total = totals[0]
            period = (
                bank["date_from"][:4]
                if bank["date_from"][5:] == "01-01" and bank["date_to"][5:] == "12-31"
                else f"{bank['date_from']}–{bank['date_to']}"
            )
            currency = total["currency"]
            direct = (
                f"Reviewed {context.lower()} {'credits received' if income else 'expenses paid'} "
                f"in {period} totalled {amount(total[field], currency)}."
            )
            timber = [
                g for g in groups if g["category"] == "TIMBER_INCOME" and g["currency"] == currency
            ]
            if income and context == "FORESTRY" and len(timber) == 1:
                direct = (
                    f"{amount(timber[0][field], currency)} of reviewed timber income "
                    f"reached the bank in {period}. Total reviewed forestry credits were "
                    f"{amount(total[field], currency)}."
                )
            breakdown = [
                (f"{category_label(g['category'], income)}: {amount(g[field], g['currency'])}.")
                for g in groups
                if Decimal(str(g[field])) != 0
                and not (
                    income
                    and context == "FORESTRY"
                    and len(timber) == 1
                    and g["category"] == "TIMBER_INCOME"
                )
            ]
            summary = ["Reviewed bank cash flow; category totals from authoritative human labels."]
            excluded = bank.get("excluded_unresolved_context_count", 0)
            if not bank.get("context_filter"):
                excluded = sum(
                    g.get("transaction_count", 0)
                    for g in bank.get("context_totals", [])
                    if g["business_context"] == "UNKNOWN"
                )
            if excluded:
                review = (
                    f"{excluded} unknown-context transactions are excluded from these "
                    f"{context.lower()} totals."
                )
            if total.get("unresolved_count"):
                review += (
                    f" {total['unresolved_count']} selected transactions still have "
                    f"unresolved classifications."
                )
        else:
            direct = (
                "The retrieved evidence does not supply a complete, reviewed total for "
                "the requested scope."
            )
            notes = [
                "No total is inferred from a bounded transaction page or another context/currency."
            ]
            summary = (
                ["Available bank evidence; detailed scope is retained below."]
                if banks or rows
                else []
            )
    elif mode == "TRANSACTION_REVIEW":
        selected = [
            r
            for r in rows
            if unresolved(r) and (not context or r.get("business_context") == context)
        ]
        count = bank.get("unresolved_count") if bank else None
        if context and bank and bank.get("context_filter") != context:
            scoped = [g for g in bank.get("context_totals", []) if g["business_context"] == context]
            count = sum(g["unresolved_count"] for g in scoped) if scoped else None
        if count is not None:
            direct = f"{count} transactions still need human review."
            if context:
                direct += f" Scope: {context}."
        else:
            direct = (
                f"{len(selected)} unresolved transactions were retrieved; a complete "
                f"count is not established."
            )
        breakdown = [transaction_line(r) for r in selected[:10]]
        if len(selected) > 10 or count is not None and count > len(selected):
            breakdown.append(
                "Additional transactions omitted from summary; see optional details "
                "for all retrieved rows."
            )
        details["review_preview_count"] = min(10, len(selected))
        details["review_rows_retrieved"] = len(selected)
        details["review_expected_count"] = count
        review = (
            "Use source evidence to confirm each row's category and context." if selected else ""
        )
        summary = ["Review-status bank aggregate and retrieved unresolved transaction rows."]
    elif mode == "AMBIGUITY":
        amounts = re.findall(r"(?:€\s*)?(\d+\.\d{2})\b", question)
        selected = [r for r in recs if r.get("state") == "AMBIGUOUS"]
        if amounts:
            requested_amounts = {Decimal(value) for value in amounts}

            def matches_amount(value):
                return value is not None and Decimal(str(value)) in requested_amounts

            invoice_ids = {
                d.get("reconciliation", {}).get("invoice_id", d.get("id"))
                for d in docs
                if matches_amount(d.get("total_eur"))
            }
            selected = [
                r
                for r in selected
                if r.get("invoice_id") in invoice_ids
                or matches_amount(r.get("candidate_net_outflow_eur"))
            ]
        if len(selected) == 1:
            r = selected[0]
            label = amount(amounts[0]) + " " if amounts else ""
            direct = (
                f"The {label}payment is not fully reconciled. There are "
                f"{r.get('candidate_debit_count', 0)} possible debit candidates and "
                f"{r.get('candidate_credit_count', 0)} credit/refund candidate(s). "
                "The exact reversed debit cannot be established from current evidence."
            )
            if r.get("candidate_net_matches_invoice"):
                breakdown = [
                    (
                        "The candidate net cash effect is consistent with one invoice "
                        "payment, but settlement is not confirmed."
                    )
                ]
        elif selected:
            direct = (
                f"{len(selected)} payment evidence records remain ambiguous; an exact "
                f"reversal is not established."
            )
        else:
            direct = (
                "The retrieved evidence does not establish the requested payment's reconciliation."
            )
        coverage = "Reconciliation is limited to the imported invoice and linked bank evidence."
        review = (
            "Human reconciliation review is required; no candidate has been promoted to "
            "confirmed settlement."
        )
        summary = ["Invoice evidence and deduplicated payment reconciliation."] if recs else []
    elif mode == "COMPARISON":
        comparisons = by_tool.get("get_saved_energy_comparison", [])
        if len(comparisons) == 1:
            d = comparisons[0]
            a = d["aggregate"]
            difference = amount(abs(Decimal(str(a["fixed_minus_spot_eur"]))))
            direct = (
                "Fixed and spot costs were equal in the saved comparison."
                if a["winner"] == "tie"
                else (
                    f"{a['winner'].capitalize()} was cheaper by {difference} over the "
                    f"supported comparison period."
                )
            )
            breakdown = [
                (
                    f"Fixed: {amount(a['net_fixed_household_total'])}; spot: "
                    f"{amount(a['net_spot_household_total'])}."
                )
            ]
            coverage = "Supported months: " + ", ".join(d["months"]) + "."
            notes = [
                (
                    "Retrospective unchanged-consumption comparison; not a realized "
                    "switch or full-year saving."
                )
            ]
            summary = ["Accepted deterministic fixed-versus-spot electricity comparison."]
    elif mode == "COVERAGE":
        if bank:
            direct = (
                f"Imported bank data covers booking dates {bank.get('observed_first_date')}–"
                f"{bank.get('observed_last_date')}: "
                f"{bank.get('transaction_count', 0)} transactions, "
                f"{bank.get('confirmed_count', 0)} human-reviewed and "
                f"{bank.get('unresolved_count', 0)} unresolved."
            )
            coverage = (
                "Observed booking dates do not prove a complete bank statement or "
                "calendar year; review counts can overlap for human UNKNOWN labels."
            )
            summary = ["Bank import coverage and authoritative review-status aggregate."]
        breakdown.extend(public.coverage.documents)
        notes.append("Retrieved documents do not establish complete document or receipt coverage.")
    elif mode == "EVIDENCE_LOOKUP":
        direct = (
            f"Retrieved evidence includes {len(rows)} transaction projection(s) and "
            f"{len(docs)} document projection(s)."
        )
        summary = ["Validated retrieved evidence; full source coverage is not established."]
    else:
        # Match a named subject only against retrieved source names, never merchant heuristics.
        names = {r.get("counterparty") for r in rows} | {d.get("vendor") for d in docs}
        from tapio.pilot.subject_identity import extract_subject, resolve_subject

        request = extract_subject(question)
        resolved = resolve_subject(request["text"], names) if request else None
        matches = set(resolved["names"]) if resolved else set()
        selected_rows = [r for r in rows if r.get("counterparty") in matches] if matches else []
        selected_docs = [d for d in docs if d.get("vendor") in matches] if matches else []
        confirmed = sorted(
            {
                r["business_context"]
                for r in selected_rows
                if r.get("label_authority") == "HUMAN_REVIEWED" and r.get("business_context")
            }
        )
        if mode == "TAX_BOUNDARY":
            direct = (
                "Tapio can show available evidence and confirmed context, but it does not "
                "decide tax deductibility."
            )
            review = (
                "Tax treatment requires a separate human decision; merchant names do not "
                "establish deductibility."
            )
            if not matches and request is None:
                selected_rows, selected_docs = rows, docs
                confirmed = sorted(
                    {
                        r["business_context"]
                        for r in rows
                        if r.get("label_authority") == "HUMAN_REVIEWED"
                        and r.get("business_context")
                    }
                )
        else:
            direct = (
                f"Retrieved evidence for the named subject includes "
                f"{len(selected_rows)} bank transaction(s) "
                f"and {len(selected_docs)} document projection(s)."
                if matches
                else (
                    "The requested evidence lookup is incomplete; "
                    "no validated subject answer is available."
                )
            )
        if confirmed:
            breakdown.append("Human-confirmed contexts: " + ", ".join(confirmed) + ".")
        if selected_docs:
            states = sorted(
                {
                    d.get("reconciliation", {}).get("state")
                    for d in selected_docs
                    if d.get("reconciliation")
                }
            )
            if states:
                breakdown.append("Document payment states: " + ", ".join(states) + ".")
        if selected_rows:
            breakdown.append(
                f"{sum(r.get('label_authority') == 'HUMAN_REVIEWED' for r in selected_rows)} "
                "retrieved bank transactions have human-reviewed labels."
            )
        if not selected_docs:
            notes.append(
                "No matching document is established in the retrieved evidence; this "
                "does not prove no receipt exists."
            )
        summary = ["Matching retrieved bank and document evidence; source details retained below."]
    # Sanitize every new public string against identifiers from ALL selected results.
    payload = {
        "presentation_mode": mode,
        "direct_answer": direct,
        "relevant_breakdown": list(dict.fromkeys(breakdown)),
        "coverage_note": coverage,
        "human_review_note": review.strip(),
        "evidence_summary": list(dict.fromkeys(summary)),
        "optional_details": details,
    }
    # Main material limitations are separate from the retained legacy backend limitations.
    payload["optional_details"]["main_limitations"] = notes

    from tapio.pilot.subject_identity import eligible_subject

    if eligible_subject(question, named_subject):
        from tapio.pilot.named_subject import subject_cards

        named = subject_cards(question, named_subject)
        payload.update(named)
        # Original public fields remain available, but unrelated subjects are not in the card.
        results = [*results, named_subject]

    def clean(value):
        if isinstance(value, str):
            return public_text(value, results)
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value

    return clean(payload)
