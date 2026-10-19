"""Synthetic analysis-tool checks; no live provider, database or production-policy mutation."""

from copy import deepcopy

import pytest

from scripts.analyze_phase09e import (
    context_analysis,
    final_reference_counterfactual,
    reference_analysis,
    replace_bank_scope,
    tax_scope_variant,
)
from tapio.agent.mandatory import MandatoryPlan, enforce_policy


def record():
    plan = {
        "question_type": "overview",
        "required_views": ["DOCUMENTS"],
        "required_contexts": [],
        "needs_coverage_check": False,
        "needs_tax_boundary": False,
        "needs_reconciliation": False,
    }
    return {
        "raw_plan": deepcopy(plan),
        "effective_plan": plan,
        "policy_events": [],
        "trace": [
            {
                "tool": "list_documents",
                "arguments": {"page": i},
                "result": {"ok": True, "data": {"items": [{"id": f"synthetic-{i}"}]}},
                "mandatory": True,
            }
            for i in range(2)
        ],
        "handles": {f"E{i}": {"call_index": i, "views": ["DOCUMENTS"]} for i in range(2)},
        "mandatory_handles": ["E0", "E1"],
        "retrieved_views": ["DOCUMENTS"],
        "state": {"errors": []},
        "final_validation": {
            "requested_final": {
                "references": [{"evidence_handle": "E1"}],
                "message_key": "human_review",
            }
        },
    }


def test_analyzer_identifies_exact_omission_and_provenance():
    r = record()
    a = reference_analysis(r)
    assert a["omitted"] == ["E0"]
    assert a["omitted_results"][0]["result"] == r["trace"][0]["result"]
    assert a["referenced"] == ["E1"]


def test_counterfactual_preserves_order_key_results_and_input():
    r = record()
    before = deepcopy(r)
    cf = final_reference_counterfactual(r)
    assert cf["response"]["status"] == "COMPLETE"
    assert cf["counterfactual_final"]["references"] == [
        {"evidence_handle": "E1"},
        {"evidence_handle": "E0"},
    ]
    assert cf["counterfactual_final"]["message_key"] == "human_review"
    assert cf["response"]["results"][0]["data"] == r["trace"][1]["result"]["data"]
    assert r == before


@pytest.mark.parametrize("problem", ["unknown", "duplicate", "failed", "absent"])
def test_counterfactual_refuses_to_repair_other_reference_defects(problem):
    r = record()
    if problem == "unknown":
        r["final_validation"]["requested_final"]["references"] = [{"evidence_handle": "E99"}]
    elif problem == "duplicate":
        r["final_validation"]["requested_final"]["references"] *= 2
    elif problem == "failed":
        r["trace"][1]["result"] = {"ok": False, "error": {"code": "FAIL"}}
    else:
        r["final_validation"] = None
    assert final_reference_counterfactual(r)["classification"] == "NOT_REPLAYABLE"


def test_reference_completion_does_not_hide_retrieval_error():
    r = record()
    r["state"]["errors"] = [{"code": "TRUNCATED_REQUIRED_EVIDENCE"}]
    cf = final_reference_counterfactual(r)
    assert cf["response"]["status"] == "EVIDENCE_INCOMPLETE"
    assert cf["response"]["answer"] == ""


def test_context_analyzer_distinguishes_unknown_from_unfiltered():
    r = record()
    r["trace"] = [{"tool": "summarize_finances", "arguments": {"business_context": "unknown"}}]
    a = context_analysis(r)
    assert not a["has_unfiltered_aggregate"]
    assert a["omitted_named_contexts"] == ["FORESTRY", "PERSONAL", "PROPERTY"]
    r["trace"][0]["arguments"]["business_context"] = None
    assert context_analysis(r)["has_unfiltered_aggregate"]


def tax_record():
    r = record()
    r["case"] = {"question": "Can I deduct the Oikea Konekauppa purchases?"}
    r["raw_plan"].update(
        question_type="tax",
        required_contexts=["UNKNOWN"],
        required_views=["TAX_BOUNDARY_CONTEXT"],
        needs_tax_boundary=True,
    )
    return r


def test_tax_discovery_preserves_intent_and_does_not_modify_live_guard():
    r = tax_record()
    before = deepcopy(r)
    p = tax_scope_variant(r)
    assert p.required_contexts == [] and p.needs_tax_boundary and p.question_type == "tax"
    assert "TAX_BOUNDARY_CONTEXT" in p.required_views
    assert r == before
    with pytest.raises(ValueError, match="AMBIGUOUS_MERCHANT_CONTEXT"):
        enforce_policy(r["case"]["question"], MandatoryPlan.model_validate(r["raw_plan"]))


def test_unknown_hypothesis_remains_restrictive_filter():
    assert tax_scope_variant(tax_record(), unknown_only=True).required_contexts == ["UNKNOWN"]


def bank(context):
    return {
        "ok": True,
        "data": {
            "context_filter": context,
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
            "context_totals": [],
            "groups": [],
            "unresolved_count": 0,
            "excluded_unresolved_context_count": 0,
            "observed_first_date": None,
            "observed_last_date": None,
        },
    }


def primary_record():
    r = record()
    r["trace"] = [
        {"tool": "summarize_finances", "arguments": {"business_context": c}, "result": bank(c)}
        for c in ["property", "forestry"]
    ] + r["trace"]
    r["response"] = {
        "status": "COMPLETE",
        "message": "Unchanged message",
        "results": [{"tool": t["tool"], **t["result"]} for t in r["trace"]],
    }
    return r


def test_all_scope_changes_only_bank_results_and_preserves_message():
    r = primary_record()
    before = deepcopy(r)
    response, trace = replace_bank_scope(r, bank(None))
    assert len(trace) == len(r["trace"]) - 1
    assert trace[0]["arguments"]["business_context"] is None
    assert trace[1:] == r["trace"][2:]
    assert response["message"] == r["response"]["message"]
    assert response["results"][1:] == r["response"]["results"][2:]
    assert r == before


def test_primary_counterfactual_refuses_filtered_aggregate():
    with pytest.raises(ValueError, match="ALL_CONTEXT"):
        replace_bank_scope(primary_record(), bank("PROPERTY"))


def test_truncated_merchant_candidate_does_not_assign_context_or_tax():
    from scripts.analyze_phase09e import merchant_discovery_analysis

    items = [
        {
            "counterparty": "oikea konekaupp synthetic",
            "business_context": "PERSONAL",
            "label_authority": "HUMAN_REVIEWED",
        }
    ]
    before = deepcopy(items)
    result = merchant_discovery_analysis(items)
    assert result["literal_matches"] == []
    assert result["truncated_name_candidates"] == items
    assert result["matching_is_non_authoritative"]
    assert items == before


def test_empty_discovery_does_not_invent_merchant_evidence():
    from scripts.analyze_phase09e import merchant_discovery_analysis

    result = merchant_discovery_analysis([{"counterparty": "another merchant"}])
    assert not result["literal_matches"] and not result["truncated_name_candidates"]
