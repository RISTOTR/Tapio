"""Synthetic-only checks for mandatory retrieval, explicit handles and trusted finalization."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from data_pipeline.labels.merchant_policy import ambiguous_merchant
from tapio.agent.mandatory import (
    CoordinatedTurn,
    EvidenceLedger,
    HandleFinal,
    MandatoryCoordinator,
    MandatoryPlan,
    enforce_policy,
    legacy_plan,
    required_views,
    run_coordinated_agent,
)
from tapio.agent.mandatory import (
    EvidenceView as V,
)
from tapio.agent.providers.openai_handles import OpenAIHandleModel

PERIOD = {"date_from": "2026-01-01", "date_to": "2026-12-31"}


def plan(views, **kwargs):
    return MandatoryPlan(
        question_type="overview",
        required_views=views,
        required_contexts=[],
        needs_coverage_check=False,
        needs_tax_boundary=False,
        **kwargs,
    )


class Registry:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail
        self.tools = {
            name: SimpleNamespace(classification="READ_ONLY")
            for name in [
                "summarize_finances",
                "find_invoices",
                "get_invoice_reconciliation",
                "list_documents",
                "query_forestry_sales",
                "query_transactions",
                "get_saved_energy_comparison",
            ]
        }

    def specifications(self):
        return []

    async def call(self, name, args, **kwargs):
        self.calls.append((name, deepcopy(args)))
        if name == self.fail:
            return {"ok": False, "error": {"code": "SYNTHETIC_FAILURE"}}
        data = {"items": [], "truncated": False}
        if name == "summarize_finances":
            data = {
                **PERIOD,
                "context_filter": args.get("business_context", "").upper()
                if args.get("business_context")
                else None,
                "categories_filter": args.get("categories"),
                "bank_source_coverage": {"status": "UNKNOWN_COVERAGE"},
            }
        elif name == "find_invoices":
            data["items"] = [{"id": "synthetic-invoice"}]
        elif name == "get_invoice_reconciliation":
            data = {"invoice_id": args["invoice_id"], "state": "AMBIGUOUS"}
        return {"ok": True, "data": data}


def execute(p, registry=None):
    c = MandatoryCoordinator(registry or Registry(), p, PERIOD)
    asyncio.run(c.execute())
    return c


def test_views_are_distinct_and_all_mandatory_tools_execute():
    c = execute(plan(list(V)))
    assert c.state()["status"] == "MANDATORY_EVIDENCE_COMPLETE"
    names = [t["tool"] for t in c.trace]
    assert {
        "list_documents",
        "find_invoices",
        "get_invoice_reconciliation",
        "query_forestry_sales",
        "get_saved_energy_comparison",
        "query_transactions",
    } <= set(names)
    assert c.completed == set(V)


@pytest.mark.parametrize("contexts", [["FORESTRY"], ["PROPERTY"], ["PROPERTY", "FORESTRY"]])
def test_contexts_never_fall_back_to_all(contexts):
    p = plan([V.BANK_CASH_FLOW, V.REVIEW_COVERAGE]).model_copy(
        update={"required_contexts": contexts}
    )
    c = execute(p)
    assert {t["arguments"]["business_context"] for t in c.trace} == {x.lower() for x in contexts}
    assert all(t["arguments"]["business_context"] is not None for t in c.trace)


def test_reconciliation_requires_direct_lookup_not_invoice_list():
    c = execute(
        plan([V.INVOICES], needs_reconciliation=True), Registry(fail="get_invoice_reconciliation")
    )
    assert V.INVOICES in c.completed and V.RECONCILIATION not in c.completed
    assert c.state()["status"] == "EVIDENCE_INCOMPLETE"
    assert len(c.ledger.handles) == 1
    assert c.ledger.results[-1]["ok"] is False


def test_document_plan_does_not_become_invoice_evidence():
    c = execute(plan([V.DOCUMENTS]))
    assert [t["tool"] for t in c.trace] == ["list_documents"]
    assert V.INVOICES not in c.completed


def test_forestry_sale_never_becomes_bank_cash():
    c = execute(plan([V.FORESTRY_SALE]))
    assert c.completed == {V.FORESTRY_SALE}
    assert c.trace[0]["tool"] == "query_forestry_sales"


def test_electricity_cash_grid_and_model_are_separate():
    c = execute(plan([V.GRID_SCOPE, V.ELECTRICITY_SAVED_COMPARISON]))
    assert c.trace[0]["arguments"]["categories"] == ["ELECTRICITY", "GRID_DISTRIBUTION"]
    assert [t["tool"] for t in c.trace] == ["summarize_finances", "get_saved_energy_comparison"]


@pytest.mark.parametrize(
    "question", ["What still needs review?", "Unresolved transactions?", "What should I not trust?"]
)
def test_review_policy_cannot_be_satisfied_by_aggregate_only(question):
    p = enforce_policy(question, plan([V.BANK_CASH_FLOW]))
    assert V.REVIEW_COVERAGE in required_views(p)
    c = execute(p)
    assert any(t["arguments"].get("review_state") == "NEEDS_REVIEW" for t in c.trace)


def test_handles_stable_across_failed_calls_no_planning_index():
    ledger = EvidenceLedger()
    assert ledger.add("x", {"ok": False}, set(), mandatory=True) is None
    e = ledger.add("y", {"ok": True, "data": {}}, {V.DOCUMENTS}, mandatory=True)
    assert e["evidence_handle"] == "E0" and "call_index" not in e
    refs = ledger.resolve(
        HandleFinal(references=[{"evidence_handle": "E0"}], message_key="results")
    )
    assert refs[0].call_index == 1


@pytest.mark.parametrize("refs,error", [(["E1"], "UNKNOWN"), (["E0", "E0"], "DUPLICATE")])
def test_unknown_and_duplicate_handles_rejected(refs, error):
    c = execute(plan([V.DOCUMENTS]))
    with pytest.raises(ValueError, match=error):
        c.finalize({"references": [{"evidence_handle": x} for x in refs], "message_key": "results"})


def test_missing_mandatory_and_optional_cannot_replace_it():
    c = execute(plan([V.INVOICES]), Registry(fail="find_invoices"))
    asyncio.run(c.retrieve("list_documents", PERIOD, set(), mandatory=False))
    result = c.finalize({"references": [{"evidence_handle": "E0"}], "message_key": "results"})
    assert result["status"] == "EVIDENCE_INCOMPLETE" and result["answer"] == ""


def test_omitted_mandatory_reference_blocks_rendering():
    c = execute(plan([V.DOCUMENTS]))
    assert (
        c.finalize({"references": [], "message_key": "results"})["status"] == "EVIDENCE_INCOMPLETE"
    )


def test_tax_forces_boundary_and_retrieves_purpose_evidence(monkeypatch):
    import tapio.agent.mandatory as module

    p = plan([V.DOCUMENTS]).model_copy(update={"needs_tax_boundary": True})
    c = execute(p)
    captured = []
    monkeypatch.setattr(
        module, "render_answer", lambda results, message: captured.append(message) or message
    )
    result = c.finalize(
        {"references": [{"evidence_handle": x} for x in c.ledger.handles], "message_key": "results"}
    )
    assert result["message"].startswith("Tax treatment")
    assert any(t["tool"] == "query_transactions" for t in c.trace)


@pytest.mark.parametrize("merchant", ["Tokmanni", "K-Rauta", "Oikea Konekauppa"])
def test_merchant_alone_cannot_supply_context(merchant):
    assert ambiguous_merchant(merchant)
    p = plan([V.BANK_CASH_FLOW]).model_copy(update={"required_contexts": ["FORESTRY"]})
    with pytest.raises(ValueError, match="EXPLICIT_SCOPE"):
        enforce_policy(f"Can I deduct purchases at {merchant}?", p)


def test_legacy_plan_migration_is_explicit_only():
    raw = {
        "question_type": "receipts",
        "required_views": ["DOCUMENTS"],
        "required_contexts": [],
        "needs_coverage_check": False,
        "needs_tax_boundary": False,
    }
    assert legacy_plan(raw).required_views == [V.INVOICES]
    assert MandatoryPlan.model_validate(raw).required_views == [V.DOCUMENTS]


def test_handle_adapter_retains_raw_without_ledger_arithmetic(tmp_path):
    native = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "finish_evidence_answer",
                                "arguments": json.dumps(
                                    {
                                        "references": [{"evidence_handle": "E99"}],
                                        "message_key": "results",
                                    }
                                ),
                            }
                        }
                    ]
                },
            }
        ]
    }
    m = OpenAIHandleModel("synthetic", protocol_dir=tmp_path)
    turn = m.parse_coordinated(native, {"finish_evidence_answer"}, False)
    assert turn.final.references[0].evidence_handle == "E99"
    raw = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert raw["original_provider_output"] == native
    assert raw["validation"] == "VALID_HANDLE_SCHEMA_PENDING_LEDGER_VALIDATION"
    with pytest.raises(ValueError, match="UNKNOWN"):
        EvidenceLedger().resolve(turn.final)


def test_raw_integer_indexes_not_accepted_in_handle_protocol():
    with pytest.raises(ValueError):
        HandleFinal.model_validate({"references": [{"call_index": 0}], "message_key": "results"})


def test_mandatory_work_does_not_consume_model_decisions(monkeypatch):
    import tapio.agent.mandatory as module

    monkeypatch.setattr(module, "render_answer", lambda *_: "synthetic-render")

    class Model:
        count = 0

        async def generate_coordinated(self, messages, tools, **kwargs):
            self.count += 1
            assert "call_index" not in json.dumps(messages)
            if kwargs["planning"]:
                return CoordinatedTurn(plan=plan([V.DOCUMENTS, V.FORESTRY_SALE, V.RECONCILIATION]))
            envelopes = messages[-1]["content"]["evidence"]
            return CoordinatedTurn(
                final=HandleFinal(
                    references=[{"evidence_handle": e["evidence_handle"]} for e in envelopes],
                    message_key="results",
                )
            )

    m = Model()
    result = asyncio.run(run_coordinated_agent("source evidence", m, Registry(), period=PERIOD))
    assert result["status"] == "COMPLETE" and result["model_rounds"] == m.count == 2


@pytest.mark.parametrize("count", [3, 4, 5])
def test_phase08_out_of_range_patterns_never_resolve(count):
    ledger = EvidenceLedger()
    for _ in range(count):
        ledger.add("source", {"ok": True, "data": {}}, {V.DOCUMENTS}, mandatory=True)
    with pytest.raises(ValueError, match="UNKNOWN"):
        ledger.resolve(
            HandleFinal(references=[{"evidence_handle": f"E{count}"}], message_key="results")
        )
    assert list(ledger.handles) == [f"E{i}" for i in range(count)]


def test_wrong_returned_context_blocks_success():
    class WrongContext(Registry):
        async def call(self, name, args, **kwargs):
            result = await super().call(name, args, **kwargs)
            result["data"]["context_filter"] = None
            return result

    c = execute(
        plan([V.BANK_CASH_FLOW]).model_copy(update={"required_contexts": ["FORESTRY"]}),
        WrongContext(),
    )
    assert c.state()["status"] == "EVIDENCE_INCOMPLETE"


def test_no_invoice_cannot_satisfy_direct_reconciliation():
    class Empty(Registry):
        async def call(self, name, args, **kwargs):
            result = await super().call(name, args, **kwargs)
            result["data"]["items"] = []
            return result

    c = execute(plan([V.RECONCILIATION]), Empty())
    assert V.RECONCILIATION not in c.completed
    assert any(e["code"] == "NO_INVOICE_FOR_DIRECT_RECONCILIATION" for e in c.errors)


def test_pagination_preserves_original_leaf_results_and_handles():
    class Paged(Registry):
        async def call(self, name, args, **kwargs):
            self.calls.append((name, args))
            return {
                "ok": True,
                "data": {
                    "items": [],
                    "truncated": args["date_from"] == PERIOD["date_from"]
                    and args["date_to"] == PERIOD["date_to"],
                },
            }

    c = execute(plan([V.DOCUMENTS]), Paged())
    assert len(c.trace) == 3
    assert len(c.ledger.handles) == 2
    assert all(not e["result"]["data"]["truncated"] for e in c.envelopes)
    assert c.state()["status"] == "MANDATORY_EVIDENCE_COMPLETE"


def test_mutating_capability_is_never_executed():
    registry = Registry()
    registry.tools["list_documents"].classification = "LOCAL_PRIVATE_DOWNLOAD"
    c = execute(plan([V.DOCUMENTS]), registry)
    assert registry.calls == []
    assert c.state()["status"] == "EVIDENCE_INCOMPLETE"


def test_exact_renderer_and_source_values_preserved():
    from apps.api.app.services.financial_summary import summarize_rows
    from apps.api.tests.test_phase06 import row
    from tapio.agent.loop import TEMPLATES
    from tapio.agent.render import render_answer
    from tapio.tools.finance_schemas import FinanceQuery

    data = summarize_rows([row("-.10"), row("-.20")], FinanceQuery(**PERIOD)).model_dump(
        mode="json"
    )
    original = deepcopy(data)
    c = MandatoryCoordinator(Registry(), plan([V.BANK_CASH_FLOW]), PERIOD)
    c.ledger.add(
        "summarize_finances", {"ok": True, "data": data}, {V.BANK_CASH_FLOW}, mandatory=True
    )
    c.completed.add(V.BANK_CASH_FLOW)
    result = c.finalize({"references": [{"evidence_handle": "E0"}], "message_key": "results"})
    assert result["answer"] == render_answer(result["results"], TEMPLATES["results"])
    assert "0.30" in result["answer"]
    assert data == original


def test_provider_payload_exposes_handles_not_indexes(tmp_path):
    captured = []

    def send(payload):
        captured.append(payload)
        return {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "finish_evidence_answer",
                                    "arguments": json.dumps(
                                        {
                                            "references": [{"evidence_handle": "E0"}],
                                            "message_key": "results",
                                        }
                                    ),
                                }
                            }
                        ]
                    },
                }
            ]
        }

    model = OpenAIHandleModel("synthetic", transport=send, protocol_dir=tmp_path)
    asyncio.run(
        model.generate_coordinated([{"role": "system", "content": "synthetic"}], [], planning=False)
    )
    assert "call_index" not in json.dumps(captured)
    assert "evidence_handle" in json.dumps(captured)
    assert captured[0]["tools"][0]["function"]["strict"] is True


@pytest.mark.parametrize(
    "missing,state,expected",
    [
        ([], None, "NOT_REPLAYABLE"),
        (["REVIEW_COVERAGE"], {"status": "MANDATORY_EVIDENCE_COMPLETE"}, "PLAN_ITSELF_INCOMPLETE"),
        ([], {"status": "EVIDENCE_INCOMPLETE"}, "MANDATORY_EVIDENCE_RETRIEVAL_FAILED"),
        ([], {"status": "MANDATORY_EVIDENCE_COMPLETE"}, "MANDATORY_EVIDENCE_COMPLETE"),
    ],
)
def test_replay_classification_never_invents_missing_plan(missing, state, expected):
    from scripts.replay_phase09b import classify_replay

    assert classify_replay(missing, state) == expected


@pytest.mark.parametrize("context", ["PERSONAL", "PROPERTY", "FORESTRY"])
def test_explicit_user_merchant_scope_is_preserved(context):
    p = plan([V.BANK_CASH_FLOW]).model_copy(update={"required_contexts": [context]})
    effective = enforce_policy(f"Show my {context.lower()} purchases at Tokmanni", p)
    assert context in effective.required_contexts
