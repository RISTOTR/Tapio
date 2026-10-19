"""One frozen Phase 09F configuration development run; no holdout evaluation or retries."""

import asyncio
import json
import time
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from data_pipeline.labels.snapshot import freeze
from scripts.evaluate_phase09d import PREFIX, diagnostic_replay, schema_hash
from scripts.phase08_acceptance import SNAPSHOT, check_inputs, digest
from tapio.agent import evaluation, mandatory, scoped
from tapio.agent.acceptance import evaluate
from tapio.agent.providers.openai import read_key
from tapio.agent.providers.openai_scoped import OpenAIScopedModel, strict_schema

ROOT = Path("data/interim/phase09g/C_scoped_v1")
LABEL = "PHASE09G_SCOPED_C_DEVELOPMENT"
MODEL = "gpt-5.4-mini-2026-03-17"
CONFIG = Path("data/interim/phase09f/next_live_configuration.json")
CONFIG_HASH = "239e45f619acfeda49588a034bfa3f6a208112235b49da48a53a068cda049b09"


def verify_configuration(snapshot):
    if digest(CONFIG) != CONFIG_HASH:
        raise ValueError("FROZEN_CONFIGURATION_HASH_MISMATCH")
    config = json.loads(CONFIG.read_text())
    assert config["identifier"] == "PHASE09F_SCOPED_C_V1"
    assert config["model"] == MODEL == evaluate.CONFIGS["C"][0]
    assert config["settings"] == {
        "max_rounds": 6,
        "max_completion_tokens": 3000,
        "reasoning_effort": "none",
        "parallel_tool_calls": False,
        "store": False,
    }
    assert all(digest(p) == h for p, h in config["implementation_hashes"].items())
    assert digest(SNAPSHOT) == config["data_snapshot_hash"]
    assert check_inputs(snapshot) == config["source_fingerprints"]
    assert digest(evaluate.DATA / "development.json") == config["development_dataset_hash"]
    assert schema_hash(strict_schema(scoped.ScopedPlan)) == config["evidence_plan_schema_hash"]
    assert (
        schema_hash(strict_schema(scoped.ContextSelection)) == config["context_scope_schema_hash"]
    )
    assert schema_hash(strict_schema(mandatory.HandleFinal)) == config["finalization_schema_hash"]
    assert (
        schema_hash(config["evidence_handle_contract"]) == config["evidence_handle_contract_hash"]
    )
    assert (
        schema_hash(
            mandatory.coordinated_registry(coverage=snapshot["bank_coverage"]).specifications()
        )
        == config["tool_registry_hash"]
    )
    assert (
        digest("tapio/agent/scoped.py")
        == config["evidence_policy_hash"]
        == config["coordinator_hash"]
    )
    assert digest("tapio/agent/mandatory.py") == config["inherited_coordinator_hash"]
    # Byte hashing only, no holdout deserialization or execution.
    assert digest(evaluate.DATA / "holdout.json") == config["holdout_hash"]
    return config


async def run_case(case, snapshot, key):
    target = ROOT / "cases" / case["id"]
    observed = []
    turns = []
    policy_events = []
    transport_errors = []
    original_coordinator = scoped.ScopedCoordinator
    original_policy = scoped.scope_policy

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
            event["effective_plan"] = result[0].model_dump(mode="json")
            event["policy_additions"] = result[1]
            return result
        except ValueError as exc:
            event["error"] = str(exc)
            raise

    class ObservedModel(OpenAIScopedModel):
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
    scoped.ScopedCoordinator = ObservedCoordinator
    scoped.scope_policy = observe_policy
    freeze(target / "started.json", {"case": case, "run": LABEL})
    started = time.monotonic()
    exception = None
    try:
        response = await scoped.run_scoped_agent(
            PREFIX + case["question"], model, registry, period=evaluation.PERIOD, max_rounds=6
        )
    except Exception as exc:
        exception = type(exc).__name__
        response = {"status": "INFRASTRUCTURE_EXCEPTION", "results": [], "answer": ""}
    finally:
        scoped.ScopedCoordinator = original_coordinator
        scoped.scope_policy = original_policy
    elapsed = time.monotonic() - started
    c = observed[0] if observed else None
    trace = deepcopy(c.trace) if c else []
    diagnostics = await diagnostic_replay(case, response, trace)
    raw = next((t["plan"] for t in turns if t["plan"]), None)
    raw_views = (
        sorted(mandatory.required_views(scoped.ScopedPlan.model_validate(raw))) if raw else []
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
        "policy_additions": c.policy_additions if c else None,
        "view_requirements": [v.model_dump(mode="json") for v in c.requirements] if c else [],
        "finalization_contract": c.finalization_contract() if c else None,
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
        or any(
            not t["result"].get("ok")
            and t["result"].get("error", {}).get("code") in ("INTERNAL_ERROR", "TOOL_TIMEOUT")
            for t in trace
        )
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
    config = verify_configuration(snapshot)
    cases = evaluate.load_cases("development")
    assert len(cases) == 20 and sum(c["critical"] for c in cases) == 8
    protected = {
        str(p): digest(p)
        for base in [
            "data/interim/phase06",
            "data/interim/phase07",
            "data/interim/phase08",
            "data/interim/phase09",
            "data/interim/phase09b",
            "data/interim/phase09c",
            "data/interim/phase09d",
            "data/interim/phase09e",
            "data/interim/phase09f",
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
    frozen = {
        "run": LABEL,
        "configuration_id": config["identifier"],
        "configuration_sha256": CONFIG_HASH,
        "source_fingerprints": config["source_fingerprints"],
        "snapshot_hash": digest(SNAPSHOT),
        "protected_hashes": protected,
        "model": MODEL,
        "settings": config["settings"],
        "development_hash": config["development_dataset_hash"],
        "holdout_hash": config["holdout_hash"],
        "manifest_hash": digest(evaluate.DATA / "manifest.json"),
        "case_ids": [c["id"] for c in cases],
        "question_prefix": PREFIX,
        "period": evaluation.PERIOD,
        "rates": evaluate.CONFIGS["C"][1],
        "cost_basis": "Frozen historical USD rates; estimate, not bill",
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
        "source_tables_unchanged": check_inputs(snapshot) == config["source_fingerprints"],
        "human_review_unchanged": True,
        "protected_artifacts_unchanged": all(digest(p) == h for p, h in protected.items()),
        "configuration_hash_unchanged": digest(CONFIG) == CONFIG_HASH,
        "snapshot_hash_unchanged": digest(SNAPSHOT) == config["data_snapshot_hash"],
        "holdout_hash_unchanged": digest(evaluate.DATA / "holdout.json") == config["holdout_hash"],
        "holdout_manifest_unchanged": digest(evaluate.DATA / "manifest.json")
        == frozen["manifest_hash"],
    }
    freeze(ROOT / "integrity.json", integrity)
    summary = {
        "run": LABEL,
        "cases_executed": len(results),
        "evidence_complete": sum(
            r["diagnostics"]["acceptance"]["EVIDENCE_COMPLETE"] for r in results
        ),
        "critical_passed": sum(
            r["case"]["critical"] and r["diagnostics"]["acceptance"]["EVIDENCE_COMPLETE"]
            for r in results
        ),
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
