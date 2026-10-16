"""Frozen development/holdout evaluation. No expected plans enter model prompts."""

import argparse
import asyncio
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from integrations.gmail.cache import private_write
from tapio.agent.acceptance.planning import (
    PlanningModel,
    evidence_states,
    infer_requirements,
    missing_requirements,
    register_plan,
)
from tapio.agent.acceptance.registry import acceptance_registry
from tapio.agent.evaluation import evaluate_case
from tapio.agent.providers.openai import OpenAIModel, read_key
from tapio.agent.render import render_answer

DATA = Path(__file__).with_name("datasets")
OUTPUT = Path("data/interim/phase07")
CONFIGS = {
    "A": ("gpt-5.4-nano-2026-03-17", ("0.20", "0.02", "1.25")),
    "B": ("gpt-5.4-mini-2026-03-17", ("0.75", "0.075", "4.50")),
    "C": ("gpt-5.4-mini-2026-03-17", ("0.75", "0.075", "4.50")),
}


def load_cases(split):
    manifest = json.loads((DATA / "manifest.json").read_text())
    payload = (DATA / f"{split}.json").read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest[split]:
        raise ValueError("FROZEN_DATASET_CHANGED")
    return json.loads(payload)


def score(result, case, requirements):
    response = result["response"]
    missing = missing_requirements(requirements, response.get("results", []), result["trace"])
    original_pass = result["passed"]
    selected = response.get("results", [])
    names = {r["tool"] for r in selected if r.get("ok")}
    deterministic = response.get("answer", "") == render_answer(
        selected, response.get("message", "")
    )
    expected_tax = case["message_key"] == "tax_review_required"
    tax_ok = not expected_tax or response.get("message", "").startswith("Tax treatment")
    scope_ok = True
    if case["id"] in ("electricity", "electricity_evidence"):
        scope_ok = "GRID_AND_SUPPLIER_SCOPE" not in missing
    if case["id"] == "unresolved_forestry":
        scope_ok = "UNRESOLVED_REVIEW_QUERY" not in missing
    complete = original_pass and not missing and deterministic and tax_ok and scope_ok
    required = set(case["required_tools"])
    calls = [t["tool"] for t in result["trace"] if t["tool"] != "submit_evidence_plan"]
    return dict(
        EVIDENCE_COMPLETE=complete,
        phase06_rubric_pass=original_pass,
        missing_evidence=missing,
        required_tools_called=required <= names,
        additional_calls=[n for n in calls if n not in required],
        repeated_calls=len(calls) - len(set(calls)),
        tool_errors=[
            t["result"]["error"]["code"] for t in result["trace"] if not t["result"]["ok"]
        ],
        unsupported_claims=bool(response.get("answer")) and not deterministic,
        final_factual_correctness=deterministic,
        factual_check_limit=(
            "Exact trusted rendering; completeness assessed separately, "
            "not an independent factual oracle."
        ),
        ambiguity_preserved=result["rubric"]["correct_ambiguity_handling"]
        and (not requirements["direct_reconciliation"] or "DIRECT_RECONCILIATION" not in missing),
        tax_boundary=tax_ok,
        coverage_disclosed="Missing periods are not estimated" in response.get("answer", ""),
        evidence_states=evidence_states(response),
        critical=case["critical"],
    )


def meets_development_gate(results):
    return (
        len(results) == 20
        and sum(r["acceptance"]["EVIDENCE_COMPLETE"] for r in results) >= 18
        and all(
            r["acceptance"]["EVIDENCE_COMPLETE"] for r in results if r["acceptance"]["critical"]
        )
        and all(not r["acceptance"]["unsupported_claims"] for r in results)
    )


def decision(development, holdout):
    if not meets_development_gate(development) or len(holdout) != 8:
        return "NOT_READY"
    if (
        sum(r["acceptance"]["EVIDENCE_COMPLETE"] for r in holdout) / 8 >= 0.85
        and all(
            r["acceptance"]["EVIDENCE_COMPLETE"] for r in holdout if r["acceptance"]["critical"]
        )
        and all(not r["acceptance"]["unsupported_claims"] for r in holdout)
    ):
        return "READY_FOR_HUMAN_SUPERVISED_PILOT"
    return "NOT_READY"


async def run(config, split):
    if split == "holdout":
        dev = json.loads((OUTPUT / f"{config}_development.json").read_text())["results"]
        if not meets_development_gate(dev):
            raise ValueError("HOLDOUT_GATE_NOT_MET_DO_NOT_OPEN_HOLDOUT")
    target = OUTPUT / f"{config}_{split}.json"
    if target.exists():
        raise ValueError("EVALUATION_ALREADY_EXISTS_NO_OVERWRITE")
    cases = load_cases(split)
    model_id, rates = CONFIGS[config]
    preflight = acceptance_registry(audit_path=OUTPUT / "tool_audit.jsonl")
    for name, arguments in [
        ("summarize_finances", {"date_from": "2026-01-01", "date_to": "2026-12-31"}),
        ("find_invoices", {"limit": 1}),
        ("get_saved_energy_comparison", {}),
    ]:
        check = await preflight.call(name, arguments, session_id="phase07-preflight")
        if not check["ok"]:
            raise ValueError("INFRASTRUCTURE_PREFLIGHT_FAILED_NO_LIVE_REQUEST")
    key = read_key()
    results = []
    for case in cases:
        case_path = OUTPUT / f"{config}_{split}_{case['id']}.json"
        if case_path.exists():
            raise ValueError("CASE_TRACE_ALREADY_EXISTS_NO_OVERWRITE")
        model = OpenAIModel(key, model=model_id)
        registry = acceptance_registry(audit_path=OUTPUT / "tool_audit.jsonl")
        if config == "C":
            register_plan(registry)
            model = PlanningModel(model, case["question"])
        case_tuple = (case["id"], case["question"], case["required_tools"], case["message_key"])
        result = await evaluate_case(case_tuple, model, registry)
        result["provider_protocol"] = list(getattr(model, "protocol_events", []))
        requirements = infer_requirements(case["question"])
        # Score the same fixed requirements for every configuration before C's fail-closed gate.
        result["acceptance"] = score(result, case, requirements)
        if config == "C":
            result["evidence_plan"] = model.plan.model_dump() if model.plan else None
            missing = missing_requirements(
                model.requirements, result["response"].get("results", []), result["trace"]
            )
            if missing or not model.plan:
                result["response"]["status"] = "EVIDENCE_INCOMPLETE"
                result["response"]["missing_evidence"] = missing
                result["acceptance"]["EVIDENCE_COMPLETE"] = False
                result["acceptance"]["evidence_states"] = ["HUMAN_REVIEW_REQUIRED", "UNSUPPORTED"]
        coverage = [
            r["data"].get("bank_source_coverage")
            for r in result["response"].get("results", [])
            if r.get("ok") and r["tool"] == "summarize_finances"
        ]
        result["coverage_summary"] = coverage
        result["configuration"] = config
        result["model_id"] = model_id
        t = result["tokens"]
        result["estimated_cost_usd"] = str(
            (
                (t["input"] - t["cached_input"]) * Decimal(rates[0])
                + t["cached_input"] * Decimal(rates[1])
                + t["output"] * Decimal(rates[2])
            )
            / 1_000_000
        )
        result["cost_basis"] = dict(model=model_id, usd_per_million=list(rates), billed=False)
        private_write(case_path, json.dumps(result, indent=2, ensure_ascii=False).encode())
        results.append(result)
        print(
            json.dumps(
                dict(
                    config=config,
                    case=case["id"],
                    rounds=result["rounds"],
                    complete=result["acceptance"]["EVIDENCE_COMPLETE"],
                    status=result["response"]["status"],
                )
            ),
            flush=True,
        )
    summary = dict(
        configuration=config,
        split=split,
        model_id=model_id,
        case_count=len(results),
        evidence_complete=sum(r["acceptance"]["EVIDENCE_COMPLETE"] for r in results),
        critical_failures=[
            r["case"]
            for r in results
            if r["acceptance"]["critical"] and not r["acceptance"]["EVIDENCE_COMPLETE"]
        ],
        latency_seconds=sum(r["latency_seconds"] for r in results),
        estimated_cost_usd=str(sum(Decimal(r["estimated_cost_usd"]) for r in results)),
        results=results,
    )
    private_write(target, json.dumps(summary, indent=2).encode())
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=list(CONFIGS), required=True)
    parser.add_argument("--split", choices=["development", "holdout"], default="development")
    args = parser.parse_args()
    asyncio.run(run(args.config, args.split))


if __name__ == "__main__":
    main()
