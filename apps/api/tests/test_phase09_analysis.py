"""Offline diagnostics must distinguish observation, inference and hypothetical replay."""

import asyncio
from copy import deepcopy

import pytest

from scripts.analyze_phase09 import RecordedRegistry, call_key, reference_forensics, replay


def call(name="summarize_finances", ok=True):
    return {"tool": name, "arguments": {}, "result": {"ok": ok, "data": {}}}


def test_reference_units_include_plan_and_failed_calls():
    trace = [call("submit_evidence_plan"), call(ok=False), call()]
    result = reference_forensics([0, 1, 3], trace)
    assert result["total_positions"] == 3
    assert result["successful_calls"] == 2
    assert result["successful_evidence_calls"] == 1
    assert result["failed_call_references"] == [1]
    assert result["references_planning_operation"]
    assert result["invalid_indexes"] == [3]


@pytest.mark.parametrize("count", [3, 4, 5])
def test_one_based_pattern_is_observed_not_repaired(count):
    refs = list(range(1, count + 1))
    original = refs.copy()
    report = reference_forensics(refs, [call() for _ in range(count)])
    assert report["exact_one_based_full_ledger"]
    assert report["invalid_indexes"] == [count]
    assert refs == original


def test_no_raw_references_means_unavailable_not_empty():
    assert reference_forensics(None, [call()]) == {"available": False}
    assert reference_forensics([], [call()])["available"]


def test_repeat_equivalence_only_ignores_null_optional_arguments():
    a = call()
    b = deepcopy(a)
    b["arguments"] = {"categories": None}
    assert call_key(a) == call_key(b)
    b["arguments"] = {"categories": ["ELECTRICITY"]}
    assert call_key(a) != call_key(b)


def test_recorded_registry_never_queries_or_accepts_unrecorded_arguments():
    registry = RecordedRegistry([call()])
    with pytest.raises(ValueError, match="ARGUMENT_MISMATCH"):
        asyncio.run(registry.call("summarize_finances", {"limit": 1}))
    result = asyncio.run(registry.call("summarize_finances", {}))
    result["data"]["mutated"] = True
    assert "mutated" not in registry.trace[0]["result"]["data"]


def test_counterfactual_does_not_increase_live_round_budget():
    result = asyncio.run(replay({}, [call() for _ in range(6)], "results"))
    assert not result["available"]
    assert result["reason"] == "EXCEEDS_UNCHANGED_SIX_ROUND_REPLAY"


def synthetic_result(tmp_path, *, invalid=False, planned=False):
    import json

    from scripts.analyze_phase09 import evidence

    data = {
        "context_filter": "PROPERTY",
        "categories_filter": None,
        "bank_source_coverage": {"status": "UNKNOWN_COVERAGE"},
    }
    trace = [{"tool": "summarize_finances", "arguments": {}, "result": {"ok": True, "data": data}}]
    args = {"references": [{"call_index": 1 if invalid else 0}], "message_key": "results"}
    path = tmp_path / "native.json"
    path.write_text(
        json.dumps(
            {
                "original_provider_output": {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "finish_evidence_answer",
                                            "arguments": json.dumps(args),
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
                "normalized_final": args,
                "validation": "INVALID_FINAL_CONTENT" if invalid else "VALID_CANONICAL_FINAL",
                "error_code": "FINAL_REFERENCE_OUT_OF_RANGE" if invalid else None,
            }
        )
    )
    return {
        "configuration": "C" if planned else "A",
        "trace": trace,
        "response": {"results": evidence(trace)},
        "rubric": {"correct_source_scope": True},
        "acceptance": {"EVIDENCE_COMPLETE": False},
        "rounds": 1,
        "provider_protocol": [{"private_artifact": str(path)}],
        "model_turns": [{"message_key": "results"}],
        "evidence_plan": {
            "question_type": "domain_cost",
            "required_views": ["BANK_CASH_FLOW", "COVERAGE", "ENERGY"],
        }
        if planned
        else None,
    }


def test_rejected_final_does_not_manufacture_valid_reference_selection(tmp_path):
    from scripts.analyze_phase09 import diagnose

    r = synthetic_result(tmp_path, invalid=True)
    case = {
        "id": "synthetic",
        "question": "property costs",
        "required_tools": ["summarize_finances"],
        "critical": True,
    }
    row = diagnose(r, case)
    assert row["enough_evidence_before_finalization"]
    assert row["validated_references"] is None
    assert row["failure_classes"] == ["FINAL_REFERENCE_OUT_OF_RANGE"]


def test_correct_plan_missing_retrieval_is_execution_failure(tmp_path):
    from scripts.analyze_phase09 import diagnose

    r = synthetic_result(tmp_path, planned=True)
    case = {
        "id": "synthetic",
        "question": "property electricity costs",
        "required_tools": ["summarize_finances", "get_saved_energy_comparison"],
        "critical": False,
    }
    row = diagnose(r, case)
    assert row["plan_missing_views"] == []
    assert row["planning_failure_class"] == "PLAN_CORRECT_EXECUTION_WRONG"
    assert "PLAN_NOT_FOLLOWED" in row["failure_classes"]
    assert "WRONG_FILTER_OR_SCOPE" not in row["failure_classes"]
