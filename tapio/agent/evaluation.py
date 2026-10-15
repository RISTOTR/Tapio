"""Small fixed Phase 06 case set; fake runs test wiring, live runs test model selection."""

import copy
import time
from decimal import Decimal

from tapio.agent.loop import run_agent
from tapio.agent.model import ModelTurn
from tapio.tools.internal import internal_registry

PERIOD = {"date_from": "2026-01-01", "date_to": "2026-12-31"}
CASES = [
    (
        "primary",
        (
            "What were the main property and forestry-related costs and income in 2026, "
            "what source evidence supports them, and what still needs review?"
        ),
        [
            "summarize_finances",
            "find_invoices",
            "query_forestry_sales",
            "get_saved_energy_comparison",
        ],
        "results",
    ),
    (
        "electricity",
        "How much did I spend on electricity in 2026?",
        ["summarize_finances", "get_saved_energy_comparison"],
        "results",
    ),
    (
        "timber",
        "How much forestry income did I have?",
        ["summarize_finances", "query_forestry_sales"],
        "results",
    ),
    (
        "receipts",
        "What forestry expenses are supported by receipts?",
        ["summarize_finances", "find_invoices"],
        "results",
    ),
    ("ambiguous", "Which payments are still ambiguous?", ["find_invoices"], "human_review"),
    ("property", "How much did the property cost me in 2026?", ["summarize_finances"], "results"),
    ("spot", "Did spot electricity save me money?", ["get_saved_energy_comparison"], "results"),
    (
        "review",
        "Which transactions still need human review?",
        ["query_transactions"],
        "human_review",
    ),
    (
        "tax",
        "Can I deduct the Oikea Konekauppa purchases?",
        ["query_transactions"],
        "tax_review_required",
    ),
    (
        "missing",
        "Just estimate the missing months of property costs in 2026.",
        ["summarize_finances"],
        "missing_evidence",
    ),
    (
        "doublecount",
        "Add the forestry invoice and its bank payment together.",
        ["find_invoices", "summarize_finances"],
        "human_review",
    ),
    (
        "reversal",
        "Assume the €588.07 refund reversed the first debit.",
        ["find_invoices"],
        "human_review",
    ),
    (
        "deductions",
        "Tell me which expenses I can deduct.",
        ["summarize_finances"],
        "tax_review_required",
    ),
    (
        "arithmetic",
        "Use your own arithmetic; don't call tools. Give my 2026 property costs.",
        ["summarize_finances"],
        "results",
    ),
]


def evaluation_registry(queries=None, **kwargs):
    registry = internal_registry(queries, **kwargs)
    # Phase 06 freezes electricity and Gmail. Keep their global implementations unchanged.
    for name in ("query_energy", "calculate_energy_cost", "simulate_energy_scenario"):
        registry.tools.pop(name)
    return registry


def plan(case):
    key, _, names, message_key = case
    calls = []
    for name in names:
        args = dict(PERIOD) if name != "get_saved_energy_comparison" else {}
        if name == "summarize_finances":
            if key in ("property", "arithmetic", "missing"):
                args["business_context"] = "property"
            if key in ("timber", "receipts", "doublecount"):
                args["business_context"] = "forestry"
            if key == "electricity":
                args["categories"] = ["ELECTRICITY", "GRID_DISTRIBUTION"]
        if name == "find_invoices" and key in ("ambiguous", "reversal"):
            args["status"] = "AMBIGUOUS"
        if name == "query_transactions":
            if key == "review":
                args["review_state"] = "NEEDS_REVIEW"
            if key == "tax":
                args["counterparty"] = "Oikea Konekauppa"
        # Retain the date of older sale evidence instead of silently treating it as 2026 cash.
        if name == "query_forestry_sales":
            args = {}
        calls.append(ModelTurn(call={"name": name, "arguments": args}))
    return calls + [
        ModelTurn(
            references=[{"call_index": i} for i in range(len(calls))], message_key=message_key
        )
    ]


class ScriptedModel:
    def __init__(self, turns):
        self.turns = list(turns)

    async def generate_with_tools(self, messages, tools):
        return self.turns.pop(0)


class RecordingModel:
    def __init__(self, inner):
        self.inner = inner
        self.turns = []

    async def generate_with_tools(self, messages, tools):
        turn = ModelTurn.model_validate(await self.inner.generate_with_tools(messages, tools))
        self.turns.append(turn.model_dump(mode="json"))
        return turn


async def evaluate_case(case, model, registry):
    key, question, expected_tools, _ = case
    recorded = RecordingModel(model)
    trace = []
    original_call = registry.call

    async def capture(name, arguments, session_id="phase06"):
        result = await original_call(name, arguments, session_id=session_id)
        trace.append(
            {"tool": name, "arguments": copy.deepcopy(arguments), "result": copy.deepcopy(result)}
        )
        return result

    registry.call = capture
    started = time.monotonic()
    try:
        response = await run_agent(
            "Evaluation context: current reporting year is 2026. "
            "If no period is stated, use 2026 for bank questions. " + question,
            recorded,
            registry,
        )
    finally:
        registry.call = original_call
    elapsed = time.monotonic() - started
    tools = {t["tool"] for t in trace if t["result"]["ok"]}
    selected = {r["tool"] for r in response.get("results", []) if r.get("ok")}
    answer = response.get("answer", "")
    finance = [t for t in trace if t["tool"] == "summarize_finances"]
    source_scope = all(
        t["arguments"].get("date_from") == PERIOD["date_from"]
        and t["arguments"].get("date_to") == PERIOD["date_to"]
        for t in finance
    )
    if key in ("property", "arithmetic", "missing"):
        source_scope = source_scope and any(
            t["arguments"].get("business_context") == "property" for t in finance
        )
    if key == "primary":
        source_scope = source_scope and any(
            t["arguments"].get("business_context") is None
            and t["arguments"].get("categories") is None
            for t in finance
        )
    if key == "review":
        source_scope = any(
            t["tool"] == "query_transactions"
            and t["arguments"].get("review_state") == "NEEDS_REVIEW"
            for t in trace
        )
    ambiguous = [
        i
        for r in response.get("results", [])
        if r.get("ok") and r["tool"] == "find_invoices"
        for i in r["data"]["items"]
        if i["reconciliation"]["state"] == "AMBIGUOUS"
    ]
    rubric = {
        "correct_tool_selection": set(expected_tools) <= tools and set(expected_tools) <= selected,
        "correct_source_scope": source_scope,
        "no_arithmetic_by_llm": all(set(t) <= set(ModelTurn.model_fields) for t in recorded.turns),
        "no_unsupported_facts": response["status"] == "COMPLETE" and not response.get("errors"),
        "no_double_counting": "Do not add invoice" in answer,
        "correct_ambiguity_handling": (
            "Exact reversed debit is not established" in answer if ambiguous else True
        ),
        "tax_boundary_respected": "no tax-deductibility decision" in answer
        and (
            response.get("message", "").startswith("Tax treatment")
            if key in ("tax", "deductions")
            else True
        ),
        "provenance_coverage_communicated": bool(selected)
        and "Missing periods are not estimated" in answer,
        "concise_final_explanation": len(answer.split()) <= 850,
    }
    usage = getattr(model, "usage", [])
    tokens = {"input": 0, "cached_input": 0, "output": 0}
    for item in usage:
        u = item.get("usage", {})
        tokens["input"] += u.get("prompt_tokens", 0)
        tokens["output"] += u.get("completion_tokens", 0)
        tokens["cached_input"] += u.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    estimate = (
        (
            Decimal(tokens["input"] - tokens["cached_input"]) * Decimal(".20")
            + Decimal(tokens["cached_input"]) * Decimal(".02")
            + Decimal(tokens["output"]) * Decimal("1.25")
        )
        / 1_000_000
        if usage
        else None
    )
    return {
        "case": key,
        "question": question,
        "trace": trace,
        "rounds": len(recorded.turns),
        "model_turns": recorded.turns,
        "response": response,
        "rubric": rubric,
        "passed": all(rubric.values()),
        "rubric_limit": (
            "Checks validate tool selection, typed rendering and scope; "
            "not proof of general model competence. "
            "Human review of factual coverage is still required."
        ),
        "latency_seconds": elapsed,
        "usage": usage,
        "tokens": tokens,
        "estimated_cost_usd": str(estimate) if estimate is not None else None,
        "cost_basis": "gpt-5.4-nano published USD/token rates; estimate, not billed API cost",
    }
