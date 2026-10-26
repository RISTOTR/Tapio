"""Pilot-only failure classification and deterministic guidance; no answer synthesis."""

import re

VIEW_LABELS = {
    "BANK_CASH_FLOW": "bank cash flow",
    "DOCUMENTS": "documents",
    "INVOICES": "invoices",
    "RECONCILIATION": "invoice/payment reconciliation",
    "FORESTRY_SALE": "forestry sales",
    "REVIEW_COVERAGE": "transaction review",
    "ELECTRICITY_SAVED_COMPARISON": "saved electricity comparison",
    "GRID_SCOPE": "grid charges",
    "TAX_BOUNDARY_CONTEXT": "tax-review context",
    "COVERAGE": "source coverage",
}


def unconstrained_overview(question):
    """Only explicit unbounded multi-domain requests; not ordinary yearly summaries."""
    q = question.casefold()
    domains = sum(
        bool(re.search(pattern, q))
        for pattern in (
            r"\b(finances|financial|bank)\b",
            r"\b(forestry)\b",
            r"\b(property)\b",
            r"\b(electricity)\b",
            r"\b(taxes|tax)\b",
            r"\b(documents)\b",
        )
    )
    return (
        domains >= 2
        and bool(re.search(r"\b(everything|complete overview|all my finances)\b", q))
        and not re.search(r"\b20\d{2}\b", q)
    )


def classify_failure(detail, diagnostics, coordinator, response):
    """Refine only a failed release, using execution facts, never guessing missing evidence."""
    category = detail["category"]
    if category in {
        "INFRASTRUCTURE_UNAVAILABLE",
        "AGENT_EXECUTION_ERROR",
        "CONFIGURATION_ERROR",
        "SAFETY_REJECTION",
        "QUESTION_TOO_BROAD",
        "UNSUPPORTED_SCOPE",
        "PLAN_INVALID",
    }:
        return category
    if (
        diagnostics["planner_called"]
        and coordinator is None
        and (
            response.get("status") == "INVALID_FINAL_CONTENT"
            or detail["stage"] == "COORDINATOR_INITIALIZATION"
        )
    ):
        return "PLAN_INVALID"
    if coordinator:
        state = coordinator.state()
        if state["status"] != "MANDATORY_EVIDENCE_COMPLETE":
            # A validated multi-view plan exceeded the existing bounded executor.
            # Retain incompleteness facts even when narrowing is the primary remedy.
            codes = {e.get("code") for e in coordinator.errors}
            domains = set()
            groups = {
                "bank": {"BANK_CASH_FLOW", "REVIEW_COVERAGE"},
                "documents": {"DOCUMENTS", "INVOICES", "RECONCILIATION"},
                "forestry": {"FORESTRY_SALE"},
                "electricity": {"ELECTRICITY_SAVED_COMPARISON", "GRID_SCOPE"},
            }
            requested = {r.view.value for r in coordinator.requirements}
            for domain, views in groups.items():
                if requested & views:
                    domains.add(domain)
            if "MANDATORY_SOURCE_CALL_LIMIT" in codes and len(domains) >= 2:
                return "QUESTION_TOO_BROAD"
            return "EVIDENCE_INCOMPLETE"
        if category == "EVIDENCE_INCOMPLETE":
            return "VALIDATION_ERROR"
    if category == "EVIDENCE_INCOMPLETE" and diagnostics.get("transaction_search"):
        return category
    # Absent a valid plan/retrieval, incomplete evidence cannot be claimed.
    if category == "EVIDENCE_INCOMPLETE":
        return "AGENT_EXECUTION_ERROR"
    return category


def suggestions(question, plan=None):
    """Fixed supported question shapes; user supplies years, otherwise examples label scope."""
    years = sorted(set(re.findall(r"\b20\d{2}\b", question)))
    year = years[-1] if years else "2026"
    views = set((plan or {}).get("required_views", []))
    q = question.casefold()
    choices = []
    if "forestry" in q or "FORESTRY_SALE" in views:
        choices.append(f"What forestry income reached my bank account in {year}?")
    if "property" in q:
        choices.append(f"What were my main property expenses in {year}?")
    if "electricity" in q or "ELECTRICITY_SAVED_COMPARISON" in views:
        choices.append("Was fixed or spot electricity cheaper in the saved comparison?")
    if "document" in q or "DOCUMENTS" in views:
        choices.append(f"What documents are available in {year}?")
    choices.extend(
        [
            f"What were my main property expenses in {year}?",
            f"What forestry income reached my bank account in {year}?",
            f"What parts of my {year} bank data are still incomplete?",
        ]
    )
    return list(dict.fromkeys(choices))[:3]


def coverage_summary(coordinator):
    """Release only structural coverage, never unvalidated totals, raw errors or model prose."""
    if coordinator is None:
        return ""
    state = coordinator.state()
    completed = sorted(str(v) for v in coordinator.completed)
    missing = sorted(str(v) for v in state["missing_views"])
    parts = []
    if completed:
        parts.append(
            "Completed evidence areas: "
            + ", ".join(VIEW_LABELS[v] for v in completed if v in VIEW_LABELS)
            + "."
        )
    if missing:
        parts.append(
            "Incomplete evidence areas: "
            + ", ".join(VIEW_LABELS[v] for v in missing if v in VIEW_LABELS)
            + "."
        )
    if any(e.get("code") == "TRUNCATED_REQUIRED_EVIDENCE" for e in coordinator.errors):
        parts.append("Required retrieved rows were truncated; full coverage is not established.")
    if state["errors"] and not missing:
        parts.append("Retrieval errors prevent complete coverage from being established.")
    return " ".join(parts)


def has_partial_evidence(coordinator):
    if coordinator is None:
        return False
    for result in coordinator.ledger.results:
        if not result.get("ok"):
            continue
        data = result.get("data", {})
        if data.get("items") or data.get("transaction_count", 0) > 0 or data.get("invoice_id"):
            return True
    return False
