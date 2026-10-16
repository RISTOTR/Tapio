"""General evidence requirements, typed planning and deterministic acceptance gates."""

import json
import re
from typing import Literal

from pydantic import Field

from tapio.tools.registry import Tool
from tapio.tools.schemas import Schema

View = Literal[
    "BANK_CASH_FLOW", "DOCUMENTS", "RECONCILIATION", "FORESTRY_SALE", "ENERGY", "REVIEW", "COVERAGE"
]


class EvidencePlan(Schema):
    question_type: Literal[
        "overview",
        "domain_cost",
        "income",
        "receipts",
        "reconciliation",
        "tax",
        "coverage",
        "review",
        "comparison",
    ]
    required_views: list[View] = Field(min_length=1, max_length=7)
    required_contexts: list[Literal["PROPERTY", "FORESTRY", "PERSONAL", "UNKNOWN"]] = Field(
        max_length=4
    )
    needs_coverage_check: bool
    needs_tax_boundary: bool


def infer_requirements(question):
    """Conservative domain rules, not a question-to-tool lookup or answer database."""
    text = question.casefold()

    def has(terms):
        return any(re.search(r"\b" + term + r"\b", text) for term in terms)

    forestry = has(["forestry", "timber", "forest"])
    property_ = has(["property"])
    tax = has(["tax", "deduct", "deduction", "deductible"])
    ambiguous = has(["ambiguous", "refund", "reversed", "reversal", "cancelled", "settled"])
    review = has(["unresolved", "awaiting", "classification"]) or "transactions still need" in text
    energy = has(["electricity", "power", "grid", "network", "spot", "tariff"])
    overview = has(["overview", "financial summary"]) or forestry and property_
    missing = has(["missing", "absent", "incomplete", "coverage"])
    views = set()
    if not (energy and has(["spot", "tariff"]) and not property_) or overview:
        views.update(["BANK_CASH_FLOW", "COVERAGE"])
    if forestry and not review or overview:
        views.update(["BANK_CASH_FLOW", "DOCUMENTS", "RECONCILIATION", "FORESTRY_SALE", "COVERAGE"])
    if ambiguous:
        views.update(["DOCUMENTS", "RECONCILIATION"])
    if review:
        views.add("REVIEW")
    if energy or overview:
        views.add("ENERGY")
    if tax:
        views.update(["BANK_CASH_FLOW", "COVERAGE"])
    if missing:
        views.add("COVERAGE")
    return dict(
        required_views=sorted(views),
        required_contexts=[c for c, b in [("PROPERTY", property_), ("FORESTRY", forestry)] if b],
        needs_coverage_check="COVERAGE" in views,
        needs_tax_boundary=tax,
        direct_reconciliation=ambiguous,
        electricity_categories=energy and not has(["spot"]) and not overview,
        needs_unknown_review=review,
    )


def selected_views(results):
    views = set()
    for r in results:
        if not r.get("ok"):
            continue
        name, data = r["tool"], r["data"]
        if name == "summarize_finances":
            views.add("BANK_CASH_FLOW")
            if data.get("bank_source_coverage"):
                views.add("COVERAGE")
        if name in ("find_invoices", "get_invoice"):
            views.add("DOCUMENTS")
            items = data.get("items", [data])
            if not items or all("reconciliation" in i for i in items):
                views.add("RECONCILIATION")
        if name == "get_invoice_reconciliation":
            views.add("RECONCILIATION")
        if name in ("query_forestry_sales", "get_forestry_sale"):
            views.add("FORESTRY_SALE")
        if name == "get_saved_energy_comparison":
            views.add("ENERGY")
        if name == "query_transactions":
            views.add("REVIEW")
    return views


def missing_requirements(requirements, results, trace):
    missing = set(requirements["required_views"]) - selected_views(results)
    names = {r["tool"] for r in results if r.get("ok")}
    contexts = set()
    for r in results:
        if r.get("ok") and r["tool"] == "summarize_finances":
            context = r["data"]["context_filter"]
            contexts.update(
                [context] if context else ["PROPERTY", "FORESTRY", "PERSONAL", "UNKNOWN"]
            )
    if "BANK_CASH_FLOW" in requirements["required_views"]:
        if set(requirements["required_contexts"]) - contexts:
            missing.add("REQUIRED_BANK_CONTEXT")
    if requirements.get("direct_reconciliation") and "get_invoice_reconciliation" not in names:
        missing.add("DIRECT_RECONCILIATION")
    if requirements.get("needs_unknown_review") and not any(
        t["tool"] == "query_transactions"
        and t["arguments"].get("review_state") == "NEEDS_REVIEW"
        and t["result"]["ok"]
        for t in trace
    ):
        missing.add("UNRESOLVED_REVIEW_QUERY")
    if requirements.get("electricity_categories") and not any(
        r.get("ok")
        and r["tool"] == "summarize_finances"
        and (
            r["data"]["categories_filter"] is None
            or {"ELECTRICITY", "GRID_DISTRIBUTION"} <= set(r["data"]["categories_filter"])
        )
        for r in results
    ):
        missing.add("GRID_AND_SUPPLIER_SCOPE")
    return sorted(missing)


def evidence_states(response):
    if response["status"] != "COMPLETE" or not any(
        r.get("ok") for r in response.get("results", [])
    ):
        return ["UNSUPPORTED", "HUMAN_REVIEW_REQUIRED"]
    states = {"SUPPORTED"}
    for r in response.get("results", []):
        if not r.get("ok"):
            states.add("UNSUPPORTED")
            continue
        d = r["data"]
        if r["tool"] == "summarize_finances":
            states.add("PARTIAL_COVERAGE")
            if d["unresolved_count"] or d["excluded_unresolved_context_count"]:
                states.add("HUMAN_REVIEW_REQUIRED")
        if r["tool"] == "get_saved_energy_comparison":
            states.add("PARTIAL_COVERAGE")
        if r["tool"] in ("find_invoices", "get_invoice", "get_invoice_reconciliation"):
            for i in d.get("items", [d]):
                rec = i.get("reconciliation", i)
                if rec.get("state") == "AMBIGUOUS":
                    states.update(["AMBIGUOUS", "HUMAN_REVIEW_REQUIRED"])
    if response.get("message", "").startswith("Tax treatment"):
        states.add("HUMAN_REVIEW_REQUIRED")
    return sorted(states)


class PlanningModel:
    """One plan turn counts against the same six-round budget; never supplies facts."""

    def __init__(self, inner, question):
        self.inner = inner
        self.requirements = infer_requirements(question)
        self.plan = None

    @property
    def protocol_events(self):
        return getattr(self.inner, "protocol_events", [])

    @property
    def usage(self):
        return self.inner.usage

    async def generate_with_tools(self, messages, tools):
        messages = [dict(m) for m in messages]
        messages[0]["content"] += (
            "\nFirst submit a typed evidence plan. No facts, calculations or prose in the plan. "
            "Then retrieve evidence satisfying these general requirements: "
            + json.dumps(self.requirements)
            + ". Invoice searches include reconciliation states; ambiguous payments additionally "
            "require direct reconciliation. Electricity bank costs include supplier AND grid. "
            "Select empty source results too: absence is evidence of limitations. "
            "A plan consumes one of six rounds, leaving at most four evidence calls and a finish. "
            "Do not repeat equivalent calls. If evidence is missing, explicitly finish for review."
        )
        if self.plan is None:
            turn = await self.inner.generate_with_tools(
                messages, [t for t in tools if t["name"] == "submit_evidence_plan"]
            )
            if not turn.call or turn.call.name != "submit_evidence_plan":
                raise ValueError("EVIDENCE_PLAN_REQUIRED")
            self.plan = EvidencePlan.model_validate(turn.call.arguments)
            self.requirements["required_views"] = sorted(
                set(self.requirements["required_views"]) | set(self.plan.required_views)
            )
            self.requirements["needs_tax_boundary"] |= self.plan.needs_tax_boundary
            return turn
        turn = await self.inner.generate_with_tools(
            messages, [t for t in tools if t["name"] != "submit_evidence_plan"]
        )
        if not turn.call and self.requirements["needs_tax_boundary"]:
            turn = turn.model_copy(update={"message_key": "tax_review_required"})
        return turn


def register_plan(registry):
    registry.add(
        Tool(
            "submit_evidence_plan",
            "Declare evidence needs only; no financial facts.",
            EvidencePlan,
            EvidencePlan,
            lambda args: args,
        )
    )
