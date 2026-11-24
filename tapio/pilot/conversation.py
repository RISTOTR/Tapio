"""Server-owned conversation focus. Failed follow-ups never replace the selection."""

import json
import re

from tapio.pilot.query_plan import MONTH, QueryPlan, validate_plan


def exclusion_followup(question):
    return bool(re.match(r"\s*(?:exclude|excluding|leave out|remove)\b", question, re.I))


def contract_followup(question):
    return bool(re.search(r"\b(?:it|that contract|this contract)\b", question, re.I))


def selection_exclusions(question, focus):
    """Resolve exclusions only against explicit labels or the saved selection."""
    text = re.sub(r"^\s*(?:exclude|excluding|leave out|remove)\s+", "", question, flags=re.I)
    text = re.sub(r"\s+from\s+(?:those|these|the).*", "", text, flags=re.I).strip(" .")
    classifications, merchants = [], []
    names = {r.get("counterparty") for r in focus.get("records", []) if r.get("counterparty")}

    def key(value):
        # Permit a repeated-letter typo only when it resolves to one selected merchant.
        return re.sub(r"(.)\1+", r"\1", value.casefold().strip())

    for clause in re.split(r",|\band\b|\bor\b", text, flags=re.I):
        clause = clause.strip()
        matches = [name for name in names if key(name) == key(clause)]
        if len(matches) == 1:
            merchants.extend(matches)
            continue
        try:
            parsed = validate_plan("Exclude " + clause, QueryPlan(intent="TRANSACTION_SEARCH"))
            remainder = clause.casefold()
            for item in parsed.exclusions:
                for label in (item.category, item.context):
                    if label:
                        remainder = re.sub(
                            r"\b" + label.lower().replace("_", " ") + r"\b", "", remainder
                        )
            if re.sub(r"\b(?:costs?|expenses?|transactions?|payments?)\b|\s+", "", remainder):
                raise ValueError("Unresolved exclusion")
            classifications.extend(parsed.exclusions)
        except ValueError:
            raise ValueError("Name the category, context, or exact merchant to exclude.") from None
    return classifications, merchants


def omitted_year(question):
    return bool(
        re.search(r"\b" + MONTH + r"\b", question, re.I) and not re.search(r"\b20\d{2}\b", question)
    )


def same_period(question):
    return bool(
        re.search(r"\bsame period\b", question, re.I) and not re.search(r"\b20\d{2}\b", question)
    )


def period_followup_question(question, previous):
    focus = (previous or {}).get("focus") or {}
    plan = focus.get("plan") or {}
    periods = plan.get("periods", [])
    if len(periods) != 1:
        raise ValueError("Specify the date range; the previous period is not unambiguous.")
    p = periods[0]
    return re.sub(
        r"\bsame period\b", f"period {p['date_from']} to {p['date_to']}", question, flags=re.I
    )


def is_followup(question):
    return (
        same_period(question)
        or exclusion_followup(question)
        or contract_followup(question)
        or omitted_year(question)
        or bool(
            re.search(
                r"\b(these|those|them|which ones|their|that payment|this payment|"
                r"each (?:invoice|document)(?! of| from| for))\b",
                question,
                re.I,
            )
        )
    )


def load_previous(history, session_id):
    if not session_id:
        return None
    path = history.directory(session_id) / "question.json"
    if not path.exists():
        return None
    saved = json.loads(path.read_text())
    previous = dict(
        question=saved["question"],
        plan=saved.get("query_plan"),
        records=saved.get("response", {}).get("supporting_records", []),
    )
    focus = saved.get("conversation_focus")
    # Compatibility with earlier histories: recover the root selection, not a failed turn.
    visited = set()
    cursor = saved
    for _ in range(20):
        if focus is not None:
            break
        if not is_followup(cursor["question"]):
            if not cursor.get("response", {}).get("failure_category"):
                focus = dict(
                    question=cursor["question"],
                    plan=cursor.get("query_plan"),
                    records=cursor.get("response", {}).get("supporting_records", []),
                )
            break
        parent = cursor.get("previous_session")
        if not parent or parent in visited:
            break
        visited.add(parent)
        path = history.directory(parent) / "question.json"
        if not path.exists():
            break
        cursor = json.loads(path.read_text())
        focus = cursor.get("conversation_focus")
    previous["focus"] = focus
    return previous


def followup_plan(question, previous):
    if not is_followup(question) or same_period(question):
        return None
    focus = (previous or {}).get("focus")
    if not focus or not focus.get("plan"):
        return QueryPlan(
            intent="UNSUPPORTED",
            clarification=(
                "There is no saved selection for this follow-up. "
                "First find the intended transactions or documents."
            ),
        )
    plan = QueryPlan.model_validate(focus["plan"]).model_copy(deep=True)
    if exclusion_followup(question):
        try:
            classifications, _ = selection_exclusions(question, focus)
        except ValueError as exc:
            return QueryPlan(intent="UNSUPPORTED", clarification=str(exc))
        plan.exclusions.extend(classifications)
        plan.clarification = None
        return plan
    if contract_followup(question) and plan.intent == "DOCUMENT_LOOKUP":
        return plan
    plan.constraints = []
    plan.clarification = None
    plan.evidence_requirements = []
    plan.evidence_mode = "REQUIRE"
    q = question.lower()
    if omitted_year(question):
        years = {p.date_from.year for p in plan.periods} | {p.date_to.year for p in plan.periods}
        if len(years) != 1 or not plan.merchants or not any(m.lower() in q for m in plan.merchants):
            return QueryPlan(
                intent="UNSUPPORTED",
                clarification="Which year should I use? "
                "I cannot tie this month unambiguously to the previous selection.",
            )
        scoped_question = re.sub(
            r"\b(" + MONTH + r")\b",
            lambda m: m[0] + " " + str(next(iter(years))),
            question,
            flags=re.I,
        )
        scoped = validate_plan(scoped_question, plan)
        if re.search(r"why|inspect", q):
            scoped.evidence_mode = "INSPECT"
            scoped.action = "FIND_EVIDENCE"
        return scoped
    if re.search(r"customer|account.holder", q):
        plan.intent = "DOCUMENT_LOOKUP"
        return plan
    if re.search(r"non.finnish|spanish|foreign.*(?:card|account)", q):
        plan.action = "LIST"
        plan.intent = "TRANSACTION_SEARCH"
        return plan
    if re.search(r"missing|weak|receipts?|invoices?", q):
        plan.intent = "TRANSACTION_SEARCH"
        plan.action = "FIND_EVIDENCE"
        plan.evidence_mode = "GAPS" if re.search(r"missing|weak", q) else "REQUIRE"
        plan.evidence_requirements = ["RECEIPT", "INVOICE"]
        return plan
    return QueryPlan(
        intent="UNSUPPORTED",
        clarification=(
            "The previous selection is retained. Specify what to check about those records."
        ),
    )
