"""Offline Phase 09E diagnostics. No model calls or live orchestration changes."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

from data_pipeline.labels.snapshot import freeze
from scripts.evaluate_phase09d import diagnostic_replay
from scripts.phase08_acceptance import SNAPSHOT, check_inputs, digest
from tapio.agent.mandatory import (
    HandleFinal,
    MandatoryCoordinator,
    MandatoryPlan,
    coordinated_registry,
    enforce_policy,
)
from tapio.agent.render import render_answer

SOURCE = Path("data/interim/phase09d/C_coordinated_v1")
ROOT = Path("data/interim/phase09e")


def reference_analysis(record):
    validation = record.get("final_validation")
    if not validation:
        return {"replayable": False, "reason": "NO_RETAINED_FINAL"}
    final = HandleFinal.model_validate(validation["requested_final"])
    names = [r.evidence_handle for r in final.references]
    handles = record["handles"]
    unknown = sorted(set(names) - set(handles))
    duplicate = len(names) != len(set(names))
    failed = [
        name
        for name in names
        if name in handles and not record["trace"][handles[name]["call_index"]]["result"].get("ok")
    ]
    omitted = [h for h in handles if h in record["mandatory_handles"] and h not in names]
    return {
        "replayable": not (unknown or duplicate or failed),
        "referenced": names,
        "omitted": omitted,
        "unknown": unknown,
        "duplicate": duplicate,
        "failed_result_handles": failed,
        "message_key": final.message_key,
        "omitted_results": [
            {
                "handle": h,
                "views": handles[h]["views"],
                "tool": record["trace"][handles[h]["call_index"]]["tool"],
                "arguments": record["trace"][handles[h]["call_index"]]["arguments"],
                "result": record["trace"][handles[h]["call_index"]]["result"],
            }
            for h in omitted
        ],
    }


def final_reference_counterfactual(record):
    """Add only omitted existing mandatory handles; preserve order, key and source results."""
    analysis = reference_analysis(record)
    if not analysis["replayable"]:
        return {"classification": "NOT_REPLAYABLE", "analysis": analysis}
    coordinator = MandatoryCoordinator(
        None,
        record["effective_plan"],
        {
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
        },
    )
    coordinator.trace = deepcopy(record["trace"])
    coordinator.ledger.results = [
        {"tool": t["tool"], **deepcopy(t["result"])} for t in record["trace"]
    ]
    coordinator.ledger.handles = deepcopy(record["handles"])
    coordinator.ledger.mandatory_handles = set(record["mandatory_handles"])
    coordinator.completed = set(record["retrieved_views"])
    coordinator.errors = deepcopy(record["state"]["errors"])
    final = deepcopy(record["final_validation"]["requested_final"])
    final["references"] += [{"evidence_handle": h} for h in analysis["omitted"]]
    response = coordinator.finalize(final)
    return {
        "analysis": analysis,
        "counterfactual_final": final,
        "response": response,
        "source_results_unchanged": True,
        "message_key_unchanged": True,
        "manual_answer_edits": False,
    }


def context_analysis(record):
    raw = record["raw_plan"]
    effective = record.get("effective_plan")
    actual = [
        t["arguments"].get("business_context")
        for t in record["trace"]
        if t["tool"] == "summarize_finances"
    ]
    return {
        "model_contexts": raw["required_contexts"],
        "policy_added_contexts": sorted(
            set(effective["required_contexts"]) - set(raw["required_contexts"])
        )
        if effective
        else None,
        "actual_bank_context_filters": actual,
        "has_unfiltered_aggregate": None in actual,
        "omitted_named_contexts": sorted(
            {"PROPERTY", "FORESTRY", "PERSONAL", "UNKNOWN"} - {c.upper() for c in actual if c}
        )
        if None not in actual
        else [],
        "policy_errors": [e["error"] for e in record["policy_events"] if "error" in e],
    }


def merchant_discovery_analysis(transactions):
    """Bounded textual candidates only; never assign merchant identity, context or tax status."""
    exact = [
        i for i in transactions if "oikea konekauppa" in (i.get("counterparty") or "").casefold()
    ]
    candidates = [
        i for i in transactions if "oikea konekaupp" in (i.get("counterparty") or "").casefold()
    ]
    return {
        "literal_matches": exact,
        "truncated_name_candidates": candidates,
        "matching_is_non_authoritative": True,
    }


def tax_scope_variant(record, *, unknown_only=False):
    """Explicit hypothetical scope change; all recorded semantic intent remains untouched."""
    raw = MandatoryPlan.model_validate(record["raw_plan"])
    discovery = raw.model_copy(update={"required_contexts": []})
    effective = enforce_policy(record["case"]["question"], discovery)
    if unknown_only:
        # Hypothesis: permit UNKNOWN as a filter. This is NOT the recommended discovery scope.
        effective = effective.model_copy(update={"required_contexts": ["UNKNOWN"]})
    return effective


def replace_bank_scope(record, aggregate):
    """Replace only bank summaries with one existing all-context aggregate result."""
    if not aggregate.get("ok") or aggregate["data"].get("context_filter") is not None:
        raise ValueError("SUCCESSFUL_ALL_CONTEXT_AGGREGATE_REQUIRED")
    trace = []
    inserted = False
    for t in record["trace"]:
        if t["tool"] == "summarize_finances":
            if not inserted:
                trace.append(
                    {
                        "tool": "summarize_finances",
                        "arguments": {
                            "date_from": "2026-01-01",
                            "date_to": "2026-12-31",
                            "business_context": None,
                            "categories": None,
                        },
                        "result": deepcopy(aggregate),
                        "mandatory": True,
                    }
                )
                inserted = True
        else:
            trace.append(deepcopy(t))
    if not inserted:
        raise ValueError("NO_RECORDED_BANK_SCOPE")
    selected = []
    inserted = False
    for result in record["response"]["results"]:
        if result["tool"] == "summarize_finances":
            if not inserted:
                selected.append({"tool": "summarize_finances", **deepcopy(aggregate)})
                inserted = True
        else:
            selected.append(deepcopy(result))
    response = {**deepcopy(record["response"]), "results": selected}
    response["answer"] = render_answer(selected, response["message"])
    return response, trace


async def main():
    target = ROOT / "finalization_policy_analysis.json"
    if target.exists():
        raise ValueError("ANALYSIS_ALREADY_EXISTS")
    snapshot = json.loads(SNAPSHOT.read_text())
    before = check_inputs(snapshot)
    protected = {
        str(p): digest(p)
        for base in ["data/interim/phase09d", "tapio"]
        for p in Path(base).rglob("*")
        if p.is_file() and "__pycache__" not in str(p)
    }
    frozen = json.loads((SOURCE / "frozen.json").read_text())
    protected.update(frozen["protected_hashes"])
    holdout = Path("tapio/agent/acceptance/datasets/holdout.json")
    assert digest(holdout) == frozen["holdout_hash"]
    records = {
        name: json.loads((SOURCE / "cases" / name / "result.json").read_text())
        for name in ["receipts", "ambiguous", "review", "tax", "primary"]
    }
    references = {}
    for name in ["receipts", "ambiguous", "review"]:
        record = records[name]
        replay = final_reference_counterfactual(record)
        if "response" in replay:
            replay["diagnostics"] = await diagnostic_replay(
                record["case"], replay["response"], record["trace"]
            )
            replay["classification"] = (
                "REFERENCE_OMISSION_ONLY"
                if replay["diagnostics"]["acceptance"]["EVIDENCE_COMPLETE"]
                else "CONTENT_STILL_FAILS"
            )
        requests = [
            json.loads(p.read_text())
            for p in sorted((SOURCE / "cases" / name / "requests").glob("*.json"))
        ]
        final_request = requests[-1]
        references[name] = {
            "raw_plan": record["raw_plan"],
            "effective_plan": record["effective_plan"],
            "handles": record["handles"],
            "historical_response": record["response"],
            "historical_diagnostics": record["diagnostics"],
            "raw_provider_final": json.loads(
                (SOURCE / "cases" / name / "responses" / "01.json").read_text()
            ),
            "final_request": final_request,
            "counterfactual": replay,
        }
    tax = records["tax"]
    tax_variants = {}
    for label, unknown_only in [("UNSPECIFIED_DISCOVERY", False), ("UNKNOWN_FILTER", True)]:
        plan = tax_scope_variant(tax, unknown_only=unknown_only)
        coordinator = MandatoryCoordinator(
            coordinated_registry(
                coverage=snapshot["bank_coverage"], audit_path=ROOT / "local_read_audit.jsonl"
            ),
            plan,
            {"date_from": "2026-01-01", "date_to": "2026-12-31"},
        )
        state = await coordinator.execute()
        transactions = [
            item
            for t in coordinator.trace
            if t["tool"] == "query_transactions"
            and t["result"].get("ok")
            and not t["result"]["data"].get("truncated")
            for item in t["result"]["data"]["items"]
        ]
        matches = merchant_discovery_analysis(transactions)
        tax_variants[label] = {
            "explicit_hypothesis": (
                "Replace recorded context restriction only; no new model plan/final"
            ),
            "effective_plan": plan.model_dump(mode="json"),
            "state": state,
            "trace": coordinator.trace,
            "handles": coordinator.ledger.handles,
            "merchant_discovery": matches,
            "returned_transaction_count": len(transactions),
            "classification": "POLICY_REJECTION_ONLY"
            if state["status"] == "MANDATORY_EVIDENCE_COMPLETE"
            and matches["truncated_name_candidates"]
            else "ADDITIONAL_FAILURE_REMAINS",
            "finalization_tested": False,
        }
    primary = records["primary"]
    registry = coordinated_registry(
        coverage=snapshot["bank_coverage"], audit_path=ROOT / "local_read_audit.jsonl"
    )
    aggregate = await registry.call(
        "summarize_finances",
        {
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
            "business_context": None,
            "categories": None,
        },
        session_id="phase09e-offline-all-context",
    )
    response, trace = replace_bank_scope(primary, aggregate)
    diagnostic = await diagnostic_replay(primary["case"], response, trace)
    result = {
        "phase": "09E",
        "models_called": 0,
        "api_tokens": 0,
        "historical_scores_unchanged": True,
        "source_fingerprints": before,
        "protected_hashes": protected,
        "snapshot_hash": digest(SNAPSHOT),
        "holdout_hash": frozen["holdout_hash"],
        "holdout_contents_inspected": False,
        "references": references,
        "tax": {
            "recorded_plan": tax["raw_plan"],
            "question": tax["case"]["question"],
            "context_analysis": context_analysis(tax),
            "variants": tax_variants,
        },
        "primary": {
            "context_analysis": context_analysis(primary),
            "aggregate": aggregate,
            "response": response,
            "trace": trace,
            "diagnostics": diagnostic,
            "classification": "SCOPE_REPRESENTATION_ONLY"
            if diagnostic["acceptance"]["EVIDENCE_COMPLETE"]
            else "ADDITIONAL_FAILURE_REMAINS",
            "scope_change_only": True,
            "model_final_replayed": False,
        },
    }
    assert check_inputs(snapshot) == before
    assert all(digest(p) == h for p, h in protected.items())
    freeze(target, result)
    print(
        json.dumps(
            {
                "references": {
                    k: v["counterfactual"]["classification"] for k, v in references.items()
                },
                "tax": {
                    k: {
                        "classification": v["classification"],
                        "merchant_candidates": len(
                            v["merchant_discovery"]["truncated_name_candidates"]
                        ),
                        "calls": len(v["trace"]),
                    }
                    for k, v in tax_variants.items()
                },
                "primary": result["primary"]["classification"],
                "models_called": 0,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
