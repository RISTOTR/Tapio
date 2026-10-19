"""Synthetic scope/finalization regressions; no real provider or project source mutation."""

import asyncio
import json
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from tapio.agent.mandatory import EvidenceView as V
from tapio.agent.mandatory import HandleFinal
from tapio.agent.providers.openai_scoped import OpenAIScopedModel, strict_schema
from tapio.agent.render import render_answer
from tapio.agent.scoped import (
    ContextSelection,
    ScopedCoordinator,
    ScopedLedger,
    ScopedPlan,
    ScopedTurn,
    ViewRequirement,
    run_scoped_agent,
    scope_policy,
)

PERIOD = {"date_from": "2026-01-01", "date_to": "2026-12-31"}


def plan(scope="UNSPECIFIED", contexts=None, views=None, **kw):
    return ScopedPlan(
        context_scope=scope,
        selected_contexts=contexts or [],
        required_views=views or ["BANK_CASH_FLOW"],
        question_type=kw.pop("question_type", "overview"),
        needs_coverage_check=False,
        needs_tax_boundary=kw.pop("needs_tax_boundary", False),
        needs_reconciliation=kw.pop("needs_reconciliation", False),
        **kw,
    )


def rec(state):
    return {
        "invoice_id": state,
        "state": state,
        "confirmed_paid_eur": "0.00",
        "confirmed_refund_eur": "0.00",
        "confirmed_net_eur": "0.00",
        "candidate_debit_count": 2 if state == "AMBIGUOUS" else 0,
        "candidate_credit_count": 1 if state == "AMBIGUOUS" else 0,
        "candidate_net_outflow_eur": "588.07",
        "candidate_net_matches_invoice": True,
        "human_review_required": state != "PAID",
    }


class Registry:
    def __init__(self):
        self.calls = []
        self.tools = {
            n: SimpleNamespace(classification="READ_ONLY")
            for n in [
                "summarize_finances",
                "query_transactions",
                "find_invoices",
                "get_invoice_reconciliation",
                "list_documents",
                "query_forestry_sales",
                "get_saved_energy_comparison",
            ]
        }
        self.rows = [
            {
                "id": str(i),
                "booking_date": (date(2026, 1, 1) + timedelta(days=i * 3)).isoformat(),
                "counterparty": "synthetic",
                "currency": "EUR",
                "amount": "0.10",
                "category": None,
                "business_context": None,
                "label_authority": "UNREVIEWED",
            }
            for i in range(95)
        ]

    def specifications(self):
        return []

    async def call(self, name, args, **kwargs):
        self.calls.append((name, deepcopy(args)))
        d = {"items": [], "truncated": False}
        if name == "summarize_finances":
            d = {
                **PERIOD,
                "context_filter": args.get("business_context", "").upper()
                if args.get("business_context")
                else None,
                "categories_filter": args.get("categories"),
                "context_totals": [],
                "groups": [],
                "unresolved_count": 95,
                "excluded_unresolved_context_count": 0,
                "observed_first_date": "2026-01-01",
                "observed_last_date": "2026-10-10",
                "bank_source_coverage": {"status": "PARTIAL"},
            }
        elif name == "query_transactions":
            rows = (
                []
                if args.get("business_context")
                else [
                    r
                    for r in self.rows
                    if args["date_from"] <= r["booking_date"] <= args["date_to"]
                ]
            )
            d = {"items": rows[: args["limit"]], "truncated": len(rows) > args["limit"]}
        elif name == "find_invoices":
            d["items"] = [
                {
                    "id": s,
                    "invoice_date": "2026-01-01",
                    "vendor": "Synthetic",
                    "total_eur": "588.07",
                    "reconciliation": rec(s),
                }
                for s in ["AMBIGUOUS", "PAID", "UNMATCHED"]
            ]
        elif name == "get_invoice_reconciliation":
            d = rec(args["invoice_id"])
        elif name == "get_saved_energy_comparison":
            d = {
                "aggregate": {
                    "net_fixed_household_total": "1",
                    "net_spot_household_total": "1",
                    "fixed_minus_spot_eur": "0",
                    "winner": "tie",
                },
                "months": ["synthetic"],
                "coverage": "Synthetic coverage",
            }
        return {"ok": True, "data": d}


def execute(p=None, question="Show bank evidence", registry=None):
    c = ScopedCoordinator(registry or Registry(), p or plan(), PERIOD, question=question)
    asyncio.run(c.execute())
    return c


def final(c, names=None, key="results"):
    return HandleFinal(
        references=[
            {"evidence_handle": h}
            for h in (
                c.finalization_contract()["required_final_handles"] if names is None else names
            )
        ],
        message_key=key,
    )


@pytest.mark.parametrize("scope", ["ALL", "UNSPECIFIED"])
def test_unfiltered_scopes(scope):
    c = execute(plan(scope))
    assert c.trace[0]["arguments"]["business_context"] is None
    assert c.plan.context_scope == scope


def test_selected_exact_and_unknown_real_label():
    c = execute(plan("SELECTED", ["UNKNOWN"]))
    assert c.trace[0]["arguments"]["business_context"] == "unknown"
    assert c.plan.context_scope == "SELECTED"


@pytest.mark.parametrize(
    "scope,contexts",
    [
        ("ALL", ["PROPERTY"]),
        ("UNSPECIFIED", ["UNKNOWN"]),
        ("SELECTED", []),
        ("SELECTED", ["ALL"]),
        ("SELECTED", ["PROPERTY", "PROPERTY"]),
    ],
)
def test_reject_scope_contradictions(scope, contexts):
    with pytest.raises(ValueError):
        ContextSelection(context_scope=scope, selected_contexts=contexts)


def test_new_schema_has_no_ambiguous_context_list():
    schema = strict_schema(ScopedPlan)
    assert "required_contexts" not in schema["properties"]
    assert set(["context_scope", "selected_contexts"]) <= set(schema["required"])
    assert schema["additionalProperties"] is False


def test_tax_unspecified_discovers_without_context_assumption():
    c = execute(
        plan(question_type="tax", needs_tax_boundary=True),
        "Can I deduct the Oikea Konekauppa purchases?",
    )
    assert c.plan.context_scope == "UNSPECIFIED"
    assert all(a.get("business_context") is None for n, a in c.registry.calls)
    assert (
        len(
            [
                i
                for e in c.envelopes
                if e["result"]["tool"] == "query_transactions"
                for i in e["result"]["data"]["items"]
            ]
        )
        == 95
    )
    assert c.finalize(final(c))["message"].startswith("Tax treatment")
    assert c.finalization_contract()["allowed_message_keys"] == ["tax_review_required"]


@pytest.mark.parametrize("context", ["FORESTRY", "UNKNOWN", "PROPERTY"])
def test_merchant_context_guess_still_rejects(context):
    with pytest.raises(ValueError, match="AMBIGUOUS_MERCHANT"):
        scope_policy("Can I deduct the Oikea Konekauppa purchases?", plan("SELECTED", [context]))


def test_explicit_user_context_is_allowed():
    p, _, _ = scope_policy("Show PERSONAL Tokmanni purchases", plan("SELECTED", ["PERSONAL"]))
    assert p.selected_contexts == ["PERSONAL"]


def test_primary_policy_uses_one_all_context_aggregate():
    c = execute(
        plan("SELECTED", ["PROPERTY", "FORESTRY"]),
        "Show property and forestry costs and what still needs review",
    )
    calls = [t for t in c.trace if t["tool"] == "summarize_finances"]
    assert len(calls) == 1 and calls[0]["arguments"]["business_context"] is None
    assert c.plan.context_scope == "ALL"
    assert c.model_plan.context_scope == "SELECTED"
    assert c.policy_additions["scope_before"] == "SELECTED"


def test_general_review_includes_unreviewed_null_rows():
    c = execute(
        plan("SELECTED", ["PERSONAL", "PROPERTY", "FORESTRY", "UNKNOWN"], question_type="review"),
        "Which transactions still need human review?",
    )
    assert c.plan.context_scope == "ALL"
    rows = [
        i
        for e in c.envelopes
        if e["result"]["tool"] == "query_transactions"
        for i in e["result"]["data"]["items"]
    ]
    assert len(rows) == 95 and len({i["id"] for i in rows}) == 95
    assert all(i["business_context"] is None for i in rows)
    assert c.state()["status"] == "MANDATORY_EVIDENCE_COMPLETE"


def test_general_review_guard_rejects_restrictive_query_even_if_called_directly():
    c = execute(plan(), "What remains unresolved?")
    result = asyncio.run(
        c.retrieve(
            "query_transactions", {**PERIOD, "business_context": "unknown"}, {V.REVIEW_COVERAGE}
        )
    )
    assert result is None
    assert c.state()["status"] == "EVIDENCE_INCOMPLETE"


def test_explicit_context_review_stays_selected():
    c = execute(plan("SELECTED", ["FORESTRY"]), "Which forestry transactions need review?")
    queries = [t for t in c.trace if t["tool"] == "query_transactions"]
    assert queries and all(t["arguments"]["business_context"] == "forestry" for t in queries)


def test_retrieval_and_reference_flags_independent():
    ledger = ScopedLedger(
        [ViewRequirement(view=V.DOCUMENTS, retrieval_required=True, final_reference_required=False)]
    )
    e = ledger.add("list_documents", {"ok": True, "data": {}}, {V.DOCUMENTS}, mandatory=True)
    assert e["retrieval_required"] and not e["final_reference_required"]
    assert ledger.required_final_handles == set()


def test_required_handles_derive_from_final_policy_not_optional_calls():
    c = execute()
    required = list(c.finalization_contract()["required_final_handles"])
    asyncio.run(c.retrieve("list_documents", {}, set(), mandatory=False))
    assert c.finalization_contract()["required_final_handles"] == required
    assert len(c.ledger.handles) == len(required) + 1
    assert c.finalize(final(c, list(c.ledger.handles)))["status"] == "COMPLETE"


def test_missing_reference_rejected_without_attachment():
    c = execute()
    f = final(c, [])
    before = f.model_dump()
    response = c.finalize(f)
    assert response["status"] == "EVIDENCE_INCOMPLETE" and not response["answer"]
    assert f.model_dump() == before
    assert c.final_validation["requested_final"]["references"] == []


@pytest.mark.parametrize("names,match", [(["E0", "E0"], "DUPLICATE"), (["E99"], "UNKNOWN")])
def test_invalid_final_handles(names, match):
    c = execute()
    with pytest.raises(ValueError, match=match):
        c.finalize(final(c, names))


def test_failed_handle_rejected():
    c = execute()
    c.ledger.results[0]["ok"] = False
    with pytest.raises(ValueError, match="FAILED_EVIDENCE"):
        c.finalize(final(c))


@pytest.mark.parametrize(
    "question,omitted_tools",
    [
        (
            "What forestry expenses are supported by receipts?",
            ["summarize_finances", "query_forestry_sales"],
        ),
        ("Which payments are still ambiguous?", ["get_invoice_reconciliation"]),
        ("Which transactions still need human review?", ["get_invoice_reconciliation"]),
    ],
)
def test_three_omission_regressions_explicitly_required(question, omitted_tools):
    c = execute(
        plan(views=["BANK_CASH_FLOW", "RECONCILIATION"], needs_reconciliation=True), question
    )
    contract = c.finalization_contract()
    for h, d in c.ledger.handles.items():
        if c.ledger.results[d["call_index"]]["tool"] in omitted_tools:
            assert h in contract["required_final_handles"]
    assert "call_index" not in json.dumps(contract) and "result" not in contract
    assert (
        c.finalize(final(c, contract["required_final_handles"][:-1]))["status"]
        == "EVIDENCE_INCOMPLETE"
    )


def test_ambiguity_and_renderer_unchanged():
    c = execute(plan(views=["RECONCILIATION"]), "Assume the refund reversed the first debit")
    before = deepcopy(c.ledger.results)
    response = c.finalize(final(c))
    assert response["answer"] == render_answer(response["results"], response["message"])
    assert "Exact reversed debit is not established" in response["answer"]
    assert c.ledger.results == before
    assert any(r["data"].get("state") == "AMBIGUOUS" for r in response["results"])


def test_runtime_payload_explicit_and_no_source_mutation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = Registry()
    before = deepcopy(registry.rows)

    class Model:
        def __init__(self):
            self.messages = []

        async def generate_coordinated(self, messages, tools, **kwargs):
            self.messages = deepcopy(messages)
            if kwargs["planning"]:
                return ScopedTurn(plan=plan())
            contract = messages[-1]["content"]["finalization_contract"]
            return ScopedTurn(
                final=HandleFinal(
                    references=[{"evidence_handle": h} for h in contract["required_final_handles"]],
                    message_key="results",
                )
            )

    model = Model()
    result = asyncio.run(run_scoped_agent("Show bank evidence", model, registry, period=PERIOD))
    assert result["status"] == "COMPLETE" and result["model_rounds"] == 2
    assert registry.rows == before
    assert set(
        ["MODEL_PLAN", "POLICY_ADDITIONS", "EFFECTIVE_PLAN", "REQUIRED_FINAL_HANDLES"]
    ) <= set(result)
    assert "call_index" not in json.dumps(model.messages)


def test_provider_uses_new_schema_without_live_transport(tmp_path):
    payloads = []

    def transport(payload):
        payloads.append(payload)
        return {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "submit_evidence_plan",
                                    "arguments": json.dumps(plan().model_dump(mode="json")),
                                }
                            }
                        ]
                    },
                }
            ]
        }

    model = OpenAIScopedModel("synthetic", transport=transport, protocol_dir=tmp_path)
    turn = asyncio.run(
        model.generate_coordinated([{"role": "user", "content": "synthetic"}], [], planning=True)
    )
    assert turn.plan.context_scope == "UNSPECIFIED"
    schema = payloads[0]["tools"][0]["function"]["parameters"]
    assert (
        "context_scope" in schema["properties"] and "required_contexts" not in schema["properties"]
    )
    assert payloads[0]["reasoning_effort"] == "none"


def test_round_budget_not_increased():
    with pytest.raises(ValueError, match="LIMIT"):
        asyncio.run(run_scoped_agent("x", None, None, period=PERIOD, max_rounds=7))
