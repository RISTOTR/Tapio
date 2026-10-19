"""One frozen coordinated-C development run; never loads or executes holdout cases."""

import asyncio
import hashlib
import json
import time
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from data_pipeline.labels.snapshot import freeze
from scripts.phase08_acceptance import SNAPSHOT, check_inputs, digest
from tapio.agent import evaluation, mandatory
from tapio.agent.acceptance import evaluate
from tapio.agent.providers.openai import read_key
from tapio.agent.providers.openai_handles import OpenAIHandleModel, strict_schema

ROOT = Path("data/interim/phase09d/C_coordinated_v1")
LABEL = "PHASE09D_C_COORDINATED"
MODEL = "gpt-5.4-mini-2026-03-17"
PREFIX = (
    "Evaluation context: current reporting year is 2026. "
    "If no period is stated, use 2026 for bank questions. "
)


def schema_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def diagnostic_replay(case, response, trace):
    """Execute the unchanged rubric on retained results, with no live tool/model calls."""

    class ReplayRegistry:
        async def call(self, name, arguments, session_id=None):
            return deepcopy(
                next(
                    t["result"] for t in trace if t["tool"] == name and t["arguments"] == arguments
                )
            )

    async def replay(question, model, registry):
        for t in trace:
            await registry.call(t["tool"], t["arguments"])
        return deepcopy(response)

    original = evaluation.run_agent
    evaluation.run_agent = replay
    try:
        result = await evaluation.evaluate_case(
            (case["id"], case["question"], case["required_tools"], case["message_key"]),
            object(),
            ReplayRegistry(),
        )
    finally:
        evaluation.run_agent = original
    result["acceptance"] = evaluate.score(
        result, case, evaluate.infer_requirements(case["question"])
    )
    result["rubric_limit"] = (
        "Unchanged historical rubric evaluated on retained trace/response. "
        "Legacy ModelTurn arithmetic check is vacuous; independently verify HandleFinal "
        "schema plus exact trusted rendering. No rubric or threshold was changed."
    )
    return result


async def run_case(case, snapshot, key):
    target = ROOT / "cases" / case["id"]
    observed = []
    turns = []
    policy_events = []
    transport_errors = []
    original_coordinator = mandatory.MandatoryCoordinator
    original_policy = mandatory.enforce_policy

    class ObservedCoordinator(original_coordinator):
        def __init__(self, *args, **kwargs):
            kwargs["audit_path"] = target / "final_validation.json"
            super().__init__(*args, **kwargs)
            observed.append(self)

    def observe_policy(question, plan):
        event = {"raw_plan": plan.model_dump(mode="json")}
        policy_events.append(event)
        try:
            result = original_policy(question, plan)
            event["effective_plan"] = result.model_dump(mode="json")
            return result
        except ValueError as exc:
            event["error"] = str(exc)
            raise

    class ObservedModel(OpenAIHandleModel):
        def _post(self, payload):
            n = len(list((target / "requests").glob("*.json")))
            freeze(target / "requests" / f"{n:02}.json", payload)
            try:
                response = super()._post(payload)
                freeze(target / "responses" / f"{n:02}.json", response)
                if response.get("model") != MODEL:
                    transport_errors.append("UNEXPECTED_RETURNED_MODEL")
                    raise ValueError("UNEXPECTED_RETURNED_MODEL")
                return response
            except ValueError as exc:
                transport_errors.append(str(exc))
                freeze(target / "responses" / f"{n:02}_error.json", {"error": str(exc)})
                raise

        async def generate_coordinated(self, *args, **kwargs):
            turn = await super().generate_coordinated(*args, **kwargs)
            turns.append(turn.model_dump(mode="json"))
            return turn

    model = ObservedModel(key, model=MODEL, protocol_dir=target / "provider_protocol")
    registry = mandatory.coordinated_registry(
        coverage=snapshot["bank_coverage"], audit_path=target / "tool_audit.jsonl"
    )
    mandatory.MandatoryCoordinator = ObservedCoordinator
    mandatory.enforce_policy = observe_policy
    freeze(target / "started.json", {"case": case, "run": LABEL})
    started = time.monotonic()
    exception = None
    try:
        response = await mandatory.run_coordinated_agent(
            PREFIX + case["question"], model, registry, period=evaluation.PERIOD, max_rounds=6
        )
    except Exception as exc:
        exception = type(exc).__name__
        response = {"status": "INFRASTRUCTURE_EXCEPTION", "results": [], "answer": ""}
    finally:
        mandatory.MandatoryCoordinator = original_coordinator
        mandatory.enforce_policy = original_policy
    elapsed = time.monotonic() - started
    c = observed[0] if observed else None
    trace = deepcopy(c.trace) if c else []
    diagnostics = await diagnostic_replay(case, response, trace)
    raw = next((t["plan"] for t in turns if t["plan"]), None)
    raw_views = (
        sorted(mandatory.required_views(mandatory.MandatoryPlan.model_validate(raw))) if raw else []
    )
    effective = sorted(mandatory.required_views(c.plan)) if c else []
    tokens = {"input": 0, "cached_input": 0, "output": 0}
    for item in model.usage:
        usage = item["usage"]
        tokens["input"] += usage.get("prompt_tokens", 0)
        tokens["output"] += usage.get("completion_tokens", 0)
        tokens["cached_input"] += usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    rates = evaluate.CONFIGS["C"][1]
    cost = (
        (tokens["input"] - tokens["cached_input"]) * Decimal(rates[0])
        + tokens["cached_input"] * Decimal(rates[1])
        + tokens["output"] * Decimal(rates[2])
    ) / 1_000_000
    result = {
        "case": case,
        "run": LABEL,
        "model": MODEL,
        "response": response,
        "raw_plan": raw,
        "model_planned_views": raw["required_views"] if raw else [],
        "model_plan_implied_views": raw_views,
        "policy_added_mandatory_views": sorted(set(effective) - set(raw_views)),
        "effective_mandatory_views": effective,
        "retrieved_views": sorted(c.completed) if c else [],
        "effective_plan": c.plan.model_dump(mode="json") if c else None,
        "policy_events": policy_events,
        "state": c.state() if c else None,
        "trace": trace,
        "handles": c.ledger.handles if c else {},
        "mandatory_handles": sorted(c.ledger.mandatory_handles) if c else [],
        "optional_calls": [t for t in trace if not t["mandatory"]],
        "final_validation": getattr(c, "final_validation", None),
        "parsed_turns": turns,
        "provider_protocol": model.protocol_events,
        "usage": model.usage,
        "tokens": tokens,
        "estimated_cost_usd": str(cost),
        "latency_seconds": elapsed,
        "diagnostics": diagnostics,
        "transport_errors": transport_errors,
        "infrastructure_exception_type": exception,
    }
    # Provider/timeout or actual source execution errors invalidate the run; no retries.
    result["systemic_stop"] = bool(
        transport_errors
        or exception
        or response["status"] == "TOOL_TIMEOUT"
        or any(not t["result"].get("ok") for t in trace)
    )
    freeze(target / "result.json", result)
    print(
        json.dumps(
            {
                "case": case["id"],
                "status": response["status"],
                "complete": diagnostics["acceptance"]["EVIDENCE_COMPLETE"],
                "rounds": response.get("model_rounds"),
                "systemic_stop": result["systemic_stop"],
            }
        ),
        flush=True,
    )
    return result


async def main():
    if (ROOT / "frozen.json").exists():
        raise ValueError("RUN_ALREADY_STARTED_NO_RETRY")
    snapshot = json.loads(SNAPSHOT.read_text())
    before = check_inputs(snapshot)
    cases = evaluate.load_cases("development")
    assert len(cases) == 20 and sum(c["critical"] for c in cases) == 8
    assert evaluate.CONFIGS["C"][0] == MODEL
    registry = mandatory.coordinated_registry(coverage=snapshot["bank_coverage"])
    protected = {
        str(p): digest(p)
        for base in [
            "data/interim/phase07",
            "data/interim/phase08",
            "data/interim/phase09",
            "data/interim/phase09b",
            "data/interim/phase09c",
        ]
        for p in Path(base).rglob("*")
        if p.is_file() and "__pycache__" not in str(p)
    }
    protected.update(
        {
            str(p): digest(p)
            for base in ["tapio", "scripts", "data_pipeline", "apps/api"]
            for p in Path(base).rglob("*.py")
        }
    )
    data = evaluate.DATA
    manifest = json.loads((data / "manifest.json").read_text())
    # Hash bytes only; never deserialize, inspect or execute holdout contents.
    assert digest(data / "holdout.json") == manifest["holdout"]
    frozen = {
        "run": LABEL,
        "model": MODEL,
        "snapshot_sha256": digest(SNAPSHOT),
        "source_fingerprints": before,
        "human_review": snapshot["review_coverage"],
        "development_hash": digest(data / "development.json"),
        "dataset_manifest": manifest,
        "manifest_hash": digest(data / "manifest.json"),
        "holdout_hash": manifest["holdout"],
        "holdout_contents_inspected": False,
        "protected_hashes": protected,
        "evidence_policy_hash": digest("tapio/agent/mandatory.py"),
        "base_policy_hash": digest("tapio/agent/policy.py"),
        "coordinated_registry_hash": schema_hash(registry.specifications()),
        "registry_base_hash": digest("tapio/agent/acceptance/registry.py"),
        "adapter_hash": digest("tapio/agent/providers/openai_handles.py"),
        "final_schema": strict_schema(mandatory.HandleFinal),
        "final_schema_hash": schema_hash(strict_schema(mandatory.HandleFinal)),
        "plan_schema": strict_schema(mandatory.MandatoryPlan),
        "settings": {
            "max_rounds": 6,
            "max_completion_tokens": 3000,
            "reasoning_effort": "none",
            "parallel_tool_calls": False,
            "store": False,
        },
        "period": evaluation.PERIOD,
        "question_prefix": PREFIX,
        "rates": evaluate.CONFIGS["C"][1],
        "cost_basis": "frozen historical rates; not billed cost",
        "case_ids": [c["id"] for c in cases],
        "runner_hash": digest(__file__),
    }
    key = read_key()
    freeze(ROOT / "frozen.json", frozen)
    results = []
    for case in cases:
        if not all(digest(p) == h for p, h in protected.items()):
            freeze(ROOT / "aborted.json", {"reason": "FROZEN_ARTIFACT_CHANGED"})
            break
        result = await run_case(case, snapshot, key)
        results.append(result)
        if result["systemic_stop"]:
            break
    integrity = {
        "source_tables_unchanged": check_inputs(snapshot) == before,
        "source_table_count": len(before),
        "human_review_unchanged": True,
        "snapshot_unchanged": digest(SNAPSHOT) == frozen["snapshot_sha256"],
        "protected_artifacts_unchanged": all(digest(p) == h for p, h in protected.items()),
        "holdout_hash_unchanged": digest(data / "holdout.json") == frozen["holdout_hash"],
        "manifest_unchanged": digest(data / "manifest.json") == frozen["manifest_hash"],
    }
    freeze(ROOT / "integrity.json", integrity)
    complete = sum(r["diagnostics"]["acceptance"]["EVIDENCE_COMPLETE"] for r in results)
    critical = sum(
        r["case"]["critical"] and r["diagnostics"]["acceptance"]["EVIDENCE_COMPLETE"]
        for r in results
    )
    summary = {
        "run": LABEL,
        "cases_executed": len(results),
        "evidence_complete": complete,
        "critical_passed": critical,
        "systemically_invalid": len(results) != 20 or any(r["systemic_stop"] for r in results),
        "latency_seconds": sum(r["latency_seconds"] for r in results),
        "tokens": {
            k: sum(r["tokens"][k] for r in results) for k in ("input", "cached_input", "output")
        },
        "estimated_cost_usd": str(sum(Decimal(r["estimated_cost_usd"]) for r in results)),
        "holdout_opened": False,
        "historical_scores_rewritten": False,
    }
    freeze(ROOT / "summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
