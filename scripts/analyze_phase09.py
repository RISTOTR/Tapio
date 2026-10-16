"""Offline trace diagnosis and explicitly counterfactual replay; no live provider or DB calls."""

import asyncio
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from data_pipeline.labels.snapshot import freeze
from tapio.agent.acceptance.evaluate import score
from tapio.agent.acceptance.planning import infer_requirements, missing_requirements, selected_views
from tapio.agent.evaluation import ScriptedModel, evaluate_case
from tapio.agent.model import ModelTurn

ROOT = Path("data/interim/phase08/development_rerun_v1")
OUT = Path("data/interim/phase09")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence(trace):
    return [{"tool": t["tool"], **t["result"]} for t in trace]


def call_key(t):
    # Omitted nullable filters and explicit nulls have the same meaning here.
    args = {k: v for k, v in t["arguments"].items() if v is not None}
    return json.dumps([t["tool"], args], sort_keys=True)


def reference_forensics(refs, trace):
    if refs is None:
        return {"available": False}
    n = len(trace)
    plan = [i for i, t in enumerate(trace) if t["tool"] == "submit_evidence_plan"]
    invalid = [i for i in refs if type(i) is not int or i < 0 or i >= n]
    return {
        "available": True,
        "raw_indexes": refs,
        "total_positions": n,
        "successful_calls": sum(t["result"]["ok"] for t in trace),
        "successful_evidence_calls": sum(
            t["result"]["ok"] and t["tool"] != "submit_evidence_plan" for t in trace
        ),
        "planning_positions": plan,
        "invalid_indexes": invalid,
        "references_planning_operation": bool(set(refs) & set(plan)),
        "failed_call_references": [
            i for i in refs if type(i) is int and 0 <= i < n and not trace[i]["result"]["ok"]
        ],
        "exact_one_based_full_ledger": refs == list(range(1, n + 1)),
        "includes_next_nonexistent_position": n in refs,
        "complete_zero_based_plus_future": set(refs) == set(range(n + 1)),
        "all_fit_zero_based_evidence_only": all(
            type(i) is int and 0 <= i < n - len(plan) for i in refs
        ),
        "interpretation_limit": (
            "Observed numbering patterns only; model intent/mental numbering is not observable."
        ),
    }


def diagnose(result, case):
    trace = result["trace"]
    req = infer_requirements(case["question"])
    retrieved = evidence(trace)
    missing_retrieved = missing_requirements(req, retrieved, trace)
    selected = result["response"].get("results", [])
    missing_selected = missing_requirements(req, selected, trace)
    missing_tools = sorted(
        set(case["required_tools"]) - {t["tool"] for t in trace if t["result"]["ok"]}
    )
    plan = result.get("evidence_plan")
    missing_plan = (
        sorted(set(req["required_views"]) - set(plan["required_views"])) if plan else None
    )
    finals = []
    for event in result["provider_protocol"]:
        native = json.loads(Path(event["private_artifact"]).read_text())
        for choice in (native.get("original_provider_output") or {}).get("choices", []):
            for call in choice.get("message", {}).get("tool_calls", []):
                if call["function"]["name"] == "finish_evidence_answer":
                    args = json.loads(call["function"]["arguments"])
                    finals.append(
                        {
                            "raw_arguments": call["function"]["arguments"],
                            "arguments": args,
                            "normalized": native["normalized_final"],
                            "validation": native["validation"],
                            "error": native["error_code"],
                            "artifact": event["private_artifact"],
                        }
                    )
    final = finals[-1] if finals else None
    refs = (
        [r["call_index"] if isinstance(r, dict) else r for r in final["arguments"]["references"]]
        if final
        else None
    )
    valid = bool(
        final and final["validation"] in ("VALID_CANONICAL_FINAL", "PROVIDER_FORMAT_NORMALIZED")
    )
    enough = (
        not missing_retrieved and not missing_tools and result["rubric"]["correct_source_scope"]
    )
    seen, repeated, ledger = set(), [], []
    for i, t in enumerate(trace):
        key = call_key(t)
        if key in seen:
            repeated.append(i)
        seen.add(key)
        ledger.append(
            {
                "call_index": i,
                "tool": t["tool"],
                "arguments": t["arguments"],
                "ok": t["result"]["ok"],
                "kind": "planning" if t["tool"] == "submit_evidence_plan" else "evidence",
                "views": sorted(selected_views(evidence([t]))),
                "result_sha256": hashlib.sha256(
                    json.dumps(t["result"], sort_keys=True).encode()
                ).hexdigest(),
            }
        )
    classes, subtypes, notes = set(), set(), []
    failed = not result["acceptance"]["EVIDENCE_COMPLETE"]
    planning_rounds = sum(t["tool"] == "submit_evidence_plan" for t in trace)
    api_rounds = len(result["provider_protocol"])
    budget_hit = api_rounds >= 6
    missing_views = set(req["required_views"]) - selected_views(retrieved)
    if failed:
        if missing_views or missing_tools or "DIRECT_RECONCILIATION" in missing_retrieved:
            classes.add("EVIDENCE_NOT_REQUESTED")
        if missing_plan:
            classes.add("EVIDENCE_PLAN_INCOMPLETE")
            subtypes.add("A_PLAN_OMITTED_REQUIREMENT")
        if plan and set(plan["required_views"]) - selected_views(retrieved):
            classes.add("PLAN_NOT_FOLLOWED")
            subtypes.add("B_PLAN_NOT_EXECUTED")
        names = {t["tool"] for t in trace}
        wrong_scope = (
            "summarize_finances" in names
            and bool(set(missing_retrieved) & {"GRID_AND_SUPPLIER_SCOPE", "REQUIRED_BANK_CONTEXT"})
        ) or ("query_transactions" in names and "UNRESOLVED_REVIEW_QUERY" in missing_retrieved)
        if wrong_scope or (
            not result["rubric"]["correct_source_scope"]
            and (case["id"] != "review" or "query_transactions" in names)
        ):
            classes.add("WRONG_FILTER_OR_SCOPE")
            subtypes.add("C_WRONG_SCOPE_OR_QUERY")
        # Only valid finals establish selection omission; rejected results are a fallback.
        if valid and set(missing_selected) - set(missing_retrieved):
            classes.add("FINAL_REFERENCE_OMITS_VALID_EVIDENCE")
            subtypes.add("D_RETRIEVED_BUT_NOT_SELECTED")
        if final and final["error"] == "FINAL_REFERENCE_OUT_OF_RANGE":
            classes.add("FINAL_REFERENCE_OUT_OF_RANGE")
        if (
            req["needs_tax_boundary"]
            and result["response"].get("message", "").startswith("Tax treatment") is False
            and valid
        ):
            classes.update(["FINAL_MESSAGE_KEY_WRONG", "REQUIRED_POLICY_NOT_TRIGGERED"])
        if repeated:
            classes.add("REPEATED_CALL_WASTE")
            subtypes.add("F_REPEATED_EQUIVALENT_CALL")
        document_detour = "DOCUMENTS" in missing_views and any(
            t["tool"] in ("list_documents", "get_document_summary") for t in trace
        )
        if document_detour:
            classes.update(["WRONG_TOOL_SELECTED", "TOOL_DESCRIPTION_AMBIGUITY"])
            subtypes.add("G_DOCUMENT_VIEW_NAMING_AMBIGUITY")
            notes.append(
                "DOCUMENTS gate accepts invoice views, not generic document catalog/summary; "
                "naming is a plausible contributor, not proven model intent."
            )
        if budget_hit and (missing_retrieved or missing_tools):
            classes.add("ROUND_BUDGET_EXHAUSTED")
            subtypes.add("E_OBSERVED_TRAJECTORY_AT_BUDGET")
        if not classes:
            classes.add("OTHER_EXPLICITLY_DOCUMENTED")
            notes.append("See failed frozen rubric fields; no mental-cause inference.")
    plan_class = None
    if failed and plan:
        if missing_plan:
            plan_class = "PLAN_WRONG"
        elif enough:
            plan_class = "PLAN_AND_EXECUTION_CORRECT_FINAL_WRONG"
        elif (
            missing_tools
            and not missing_retrieved
            and not (set(plan["required_views"]) - selected_views(retrieved))
        ):
            plan_class = "REQUIREMENT_NOT_EXPRESSIBLE_IN_PLAN_SCHEMA"
            classes.add("REQUIRED_POLICY_NOT_TRIGGERED")
            subtypes.add("G_REQUIREMENT_NOT_EXPRESSED_IN_PLAN")
            notes.append(
                "Generic view plan is satisfied but frozen required-tool obligation remains; "
                "plan has no source-specific binding for that obligation."
            )
        else:
            plan_class = "PLAN_CORRECT_EXECUTION_WRONG"
    return {
        "configuration": result["configuration"],
        "question_id": case["id"],
        "question": case["question"],
        "question_class": plan["question_type"]
        if plan
        else "semantic_requirements:" + ",".join(req["required_views"]),
        "expected_evidence": req,
        "frozen_required_tools": case["required_tools"],
        "actual_plan": plan,
        "plan_missing_views": missing_plan,
        "plan_schema_unexpressed_constraints": [
            k
            for k in ("direct_reconciliation", "electricity_categories", "needs_unknown_review")
            if req.get(k)
        ],
        "ledger": ledger,
        "successful_positions": [i for i, t in enumerate(trace) if t["result"]["ok"]],
        "failed_positions": [i for i, t in enumerate(trace) if not t["result"]["ok"]],
        "repeated_equivalent_positions": repeated,
        "same_tool_repeat_count": len(trace) - len({t["tool"] for t in trace}),
        "missing_retrieved_requirements": missing_retrieved,
        "omitted_required_views": sorted(missing_views),
        "missing_required_tools": missing_tools,
        "finals": finals,
        "raw_final_message_key": final["arguments"]["message_key"] if final else None,
        "effective_final_message_key": result["model_turns"][-1]["message_key"] if valid else None,
        "validated_references": refs if valid else None,
        "reference_forensics": reference_forensics(refs, trace),
        "final_rejection_reason": final["error"] if final else "NO_RETAINED_FINAL",
        "evidence_complete": not failed,
        "critical": case["critical"],
        "reported_rounds": result["rounds"],
        "provider_rounds": api_rounds,
        "planning_rounds": planning_rounds,
        "evidence_rounds": len(trace) - planning_rounds,
        "finalization_round": api_rounds if final else None,
        "round_budget_exhausted": budget_hit,
        "enough_evidence_before_finalization": enough,
        "failure_classes": sorted(classes),
        "evidence_failure_subtypes": sorted(subtypes),
        "planning_failure_class": plan_class,
        "failed_rubric": [k for k, v in result["rubric"].items() if not v],
        "notes": notes,
    }


class RecordedRegistry:
    """Exact recorded argument/result pairs; no fallback to source tools."""

    def __init__(self, trace):
        self.trace = copy.deepcopy(trace)
        self.position = 0

    def specifications(self):
        return []

    async def call(self, name, arguments, session_id=None):
        t = self.trace[self.position]
        if name != t["tool"] or arguments != t["arguments"]:
            raise ValueError("RECORDED_REPLAY_ARGUMENT_MISMATCH")
        self.position += 1
        return copy.deepcopy(t["result"])


async def replay(case, trace, message_key):
    if len(trace) > 5:
        return {"available": False, "reason": "EXCEEDS_UNCHANGED_SIX_ROUND_REPLAY"}
    turns = [ModelTurn(call={"name": t["tool"], "arguments": t["arguments"]}) for t in trace]
    turns.append(
        ModelTurn(
            references=[{"call_index": i} for i in range(len(trace))], message_key=message_key
        )
    )
    r = await evaluate_case(
        (case["id"], case["question"], case["required_tools"], case["message_key"]),
        ScriptedModel(turns),
        RecordedRegistry(trace),
    )
    a = score(r, case, infer_requirements(case["question"]))
    return {
        "available": True,
        "counterfactual_only": True,
        "evidence_complete": a["EVIDENCE_COMPLETE"],
        "missing": a["missing_evidence"],
        "failed_rubric": [k for k, v in r["rubric"].items() if not v],
        "trace": trace,
        "message_key": message_key,
        "financial_outputs": (
            "Unmodified recorded results; references are explicit hypothetical "
            "oracle selection, not repaired live output."
        ),
    }


def deficits(case, trace):
    req = infer_requirements(case["question"])
    missing = set(missing_requirements(req, evidence(trace), trace))
    missing.update("TOOL:" + n for n in set(case["required_tools"]) - {t["tool"] for t in trace})
    finance = [t for t in trace if t["tool"] == "summarize_finances"]
    if case["id"] in ("property", "arithmetic", "missing") and not any(
        t["arguments"].get("business_context") == "property" for t in finance
    ):
        missing.add("FROZEN_PROPERTY_SCOPE")
    if case["id"] == "primary" and not any(
        t["arguments"].get("business_context") is None and t["arguments"].get("categories") is None
        for t in finance
    ):
        missing.add("FROZEN_ALL_CONTEXT_SCOPE")
    return missing


def choose_recorded(case, pool):
    chosen = []
    while deficits(case, chosen) and len(chosen) < 5:
        options = [t for t in pool if t not in chosen]
        best = min(options, key=lambda t: len(deficits(case, chosen + [t])))
        if len(deficits(case, chosen + [best])) >= len(deficits(case, chosen)):
            break
        chosen.append(best)
    return chosen


async def main():
    development = Path("tapio/agent/acceptance/datasets/development.json")
    manifest = json.loads(development.with_name("manifest.json").read_text())
    assert sha(development) == manifest["development"]
    cases = {c["id"]: c for c in json.loads(development.read_text())}
    source_paths = [p for p in ROOT.rglob("*") if p.is_file()]
    source_paths += [development, development.with_name("manifest.json")]
    hashes = {str(p): sha(p) for p in source_paths}
    all_results = [
        r
        for c in "ABC"
        for r in json.loads((ROOT / "development" / f"{c}_development.json").read_text())["results"]
    ]
    assert len(all_results) == 60
    pool, seen = [], set()
    for r in all_results:
        for t in r["trace"]:
            key = json.dumps(t, sort_keys=True)
            if t["result"]["ok"] and t["tool"] != "submit_evidence_plan" and key not in seen:
                seen.add(key)
                pool.append(t)
    inventory = []
    for result in all_results:
        case = cases[result["case"]]
        row = diagnose(result, case)
        own = [t for t in result["trace"] if t["tool"] != "submit_evidence_plan"]
        message = row["effective_final_message_key"] or row["raw_final_message_key"]
        row["counterfactual_own_retrieval_all_references"] = (
            await replay(case, own, message) if message else {"available": False}
        )
        row["counterfactual_own_retrieval_expected_message"] = await replay(
            case, own, case["message_key"]
        )
        same_question = [
            t
            for r in all_results
            if r["case"] == case["id"]
            for t in r["trace"]
            if t["result"]["ok"] and t["tool"] != "submit_evidence_plan"
        ]
        chosen = choose_recorded(case, same_question + pool)
        row["recorded_pool_provenance"] = [
            {"configuration": r["configuration"], "question_id": r["case"], "call_index": i}
            for t in chosen
            for r in all_results
            for i, original in enumerate(r["trace"])
            if original == t
        ]
        row["counterfactual_recorded_pool"] = await replay(case, chosen, case["message_key"])
        row["recorded_pool_replay_limitations"] = (
            "Oracle chooses recorded results using frozen development requirements; "
            "not a model score or deployed orchestration. No source query. "
            "May replace wrong retrievals rather than only append. No causal claim."
        )
        needed = len(chosen)
        capacity = 5 - row["planning_rounds"]
        row["observed_required_evidence_call_count_from_recorded_pool"] = (
            needed if not deficits(case, chosen) else None
        )
        row["budget_classification"] = (
            "FAILURE_DUE_TO_BUDGET"
            if not row["evidence_complete"] and not deficits(case, chosen) and needed > capacity
            else "FAILURE_NOT_DUE_TO_BUDGET"
            if not row["evidence_complete"]
            else "NOT_A_FAILURE"
        )
        row["budget_limit_note"] = (
            "Existence of a fitting recorded witness disproves structural budget necessity, "
            "not the role of wasted calls in the observed trajectory."
        )
        row["one_extra_recorded_call_satisfies_retrieval"] = (
            any(not deficits(case, own + [t]) for t in pool) if deficits(case, own) else False
        )
        row["useful_evidence_rounds"] = sum(
            bool(selected_views(evidence([t])) & set(row["expected_evidence"]["required_views"]))
            or t["tool"] in case["required_tools"]
            for t in own
        )
        row["noncontributing_evidence_rounds"] = len(own) - row["useful_evidence_rounds"]
        inventory.append(row)
    summary = {}
    for c in "ABC":
        group = [r for r in inventory if r["configuration"] == c]
        summary[c] = {
            "passes": sum(r["evidence_complete"] for r in group),
            "failure_classes": dict(Counter(x for r in group for x in r["failure_classes"])),
            "subtypes": dict(Counter(x for r in group for x in r["evidence_failure_subtypes"])),
            "planning_failure_classes": dict(
                Counter(r["planning_failure_class"] for r in group if r["planning_failure_class"])
            ),
            "budget": dict(Counter(r["budget_classification"] for r in group)),
            "counterfactual_own_selection_passes": sum(
                r["counterfactual_own_retrieval_all_references"].get("evidence_complete", False)
                for r in group
            ),
            "counterfactual_own_expected_message_passes": sum(
                r["counterfactual_own_retrieval_expected_message"].get("evidence_complete", False)
                for r in group
            ),
            "counterfactual_recorded_pool_passes": sum(
                r["counterfactual_recorded_pool"].get("evidence_complete", False) for r in group
            ),
        }
    assert all(sha(p) == h for p, h in hashes.items())
    freeze(
        OUT / "failure_inventory.json",
        {
            "analysis_version": 3,
            "mode": "OFFLINE_DIAGNOSIS_ONLY",
            "model_calls": 0,
            "fresh_tool_executions": 0,
            "holdout_opened": False,
            "input_hashes": hashes,
            "summary": summary,
            "runs": inventory,
        },
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
