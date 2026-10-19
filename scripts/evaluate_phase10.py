"""First and only sealed holdout execution using the frozen Phase 09I pipeline."""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from data_pipeline.labels.snapshot import freeze
from scripts import evaluate_phase09i as pipeline
from scripts.phase08_acceptance import SNAPSHOT, check_inputs, digest
from tapio.agent.acceptance import evaluate
from tapio.agent.providers.openai import read_key

ROOT = Path("data/interim/phase10/C_holdout_v1")
LABEL = "PHASE10_FIRST_AND_ONLY_SEALED_HOLDOUT"
DEVELOPMENT = Path("data/interim/phase09i/C_exclusive_v1")


async def main():
    if (ROOT / "first_open.json").exists() or (ROOT / "frozen.json").exists():
        raise ValueError("HOLDOUT_ALREADY_OPENED_NO_RETRY_OR_RESUME")
    snapshot = json.loads(SNAPSHOT.read_text())
    config = pipeline.verify_configuration(snapshot)
    prior = json.loads((DEVELOPMENT / "frozen.json").read_text())
    assert prior["configuration_sha256"] == pipeline.CONFIG_HASH
    assert all(digest(p) == h for p, h in prior["protected_hashes"].items())
    assert digest("scripts/evaluate_phase09i.py") == prior["runner_hash"]
    assert digest(evaluate.DATA / "manifest.json") == prior["manifest_hash"]
    assert digest(evaluate.DATA / "holdout.json") == prior["holdout_hash"]
    assert all(json.loads((DEVELOPMENT / "integrity.json").read_text()).values())
    assert (
        json.loads(Path("data/interim/phase09i/verification.json").read_text())["status"] == "PASS"
    )
    development = [
        json.loads((DEVELOPMENT / "cases" / name / "result.json").read_text())["diagnostics"]
        for name in prior["case_ids"]
    ]
    assert evaluate.meets_development_gate(development)
    protected = dict(prior["protected_hashes"])
    for phase in (
        "phase06",
        "phase07",
        "phase08",
        "phase09",
        "phase09b",
        "phase09c",
        "phase09d",
        "phase09e",
        "phase09f",
        "phase09g",
        "phase09h",
        "phase09i",
    ):
        for p in Path("data/interim", phase).rglob("*"):
            if p.is_file() and "__pycache__" not in str(p):
                protected[str(p)] = digest(p)
    protected[__file__] = digest(__file__)
    # Reading the key is local only; no provider request precedes all frozen checks.
    key = read_key()
    freeze(
        ROOT / "preflight.json",
        {
            "status": "PASS",
            "configuration_id": config["identifier"],
            "configuration_sha256": pipeline.CONFIG_HASH,
            "source_fingerprints": check_inputs(snapshot),
            "manifest_hash": prior["manifest_hash"],
            "holdout_byte_hash": prior["holdout_hash"],
            "holdout_contents_opened": False,
            "development_gate_passed": True,
        },
    )
    opened = datetime.now(UTC).isoformat()
    freeze(
        ROOT / "first_open.json",
        {
            "first_open_timestamp_utc": opened,
            "execution_number": 1,
            "only_execution": True,
            "no_retry_or_resume": True,
            "holdout_hash": prior["holdout_hash"],
        },
    )
    # First content access, only after verification and irreversible attempt marker.
    cases = evaluate.load_cases("holdout")
    assert len(cases) == 8
    frozen = {
        "run": LABEL,
        "configuration_id": config["identifier"],
        "configuration_sha256": pipeline.CONFIG_HASH,
        "first_open_timestamp_utc": opened,
        "execution_number": 1,
        "protected_hashes": protected,
        "source_fingerprints": config["source_fingerprints"],
        "snapshot_hash": digest(SNAPSHOT),
        "holdout_hash": prior["holdout_hash"],
        "manifest_hash": prior["manifest_hash"],
        "model": pipeline.MODEL,
        "settings": config["settings"],
        "case_ids": [c["id"] for c in cases],
        "critical_count": sum(c["critical"] for c in cases),
        "question_prefix": pipeline.PREFIX,
        "period": pipeline.evaluation.PERIOD,
        "rates": evaluate.CONFIGS["C"][1],
        "runner_hash": digest(__file__),
        "pipeline_runner_hash": prior["runner_hash"],
    }
    freeze(ROOT / "frozen.json", frozen)
    pipeline.ROOT, pipeline.LABEL = ROOT, LABEL
    results = []
    invalid_reason = None
    for case in cases:
        if not all(digest(p) == h for p, h in protected.items()):
            invalid_reason = "FROZEN_ARTIFACT_CHANGED"
            break
        result = await pipeline.run_case(case, snapshot, key)
        results.append(result)
        if result["systemic_stop"]:
            invalid_reason = "INFRASTRUCTURE_OR_PROVIDER_FAILURE"
            break
    integrity = {
        "source_tables_unchanged": check_inputs(snapshot) == config["source_fingerprints"],
        "protected_artifacts_unchanged": all(digest(p) == h for p, h in protected.items()),
        "configuration_hash_unchanged": digest(pipeline.CONFIG) == pipeline.CONFIG_HASH,
        "snapshot_hash_unchanged": digest(SNAPSHOT) == config["data_snapshot_hash"],
        "holdout_hash_unchanged": digest(evaluate.DATA / "holdout.json") == prior["holdout_hash"],
        "manifest_hash_unchanged": digest(evaluate.DATA / "manifest.json")
        == prior["manifest_hash"],
    }
    freeze(ROOT / "integrity.json", integrity)
    if not all(integrity.values()):
        invalid_reason = "POST_RUN_INTEGRITY_FAILURE"
    complete = sum(r["diagnostics"]["acceptance"]["EVIDENCE_COMPLETE"] for r in results)
    critical = sum(
        r["case"]["critical"] and r["diagnostics"]["acceptance"]["EVIDENCE_COMPLETE"]
        for r in results
    )
    decision = evaluate.decision(development, [r["diagnostics"] for r in results])
    # User-required safety/reference gates supplement the unchanged evaluator.
    safety_keys = (
        "no_arithmetic_by_llm",
        "no_unsupported_facts",
        "no_double_counting",
        "correct_ambiguity_handling",
        "tax_boundary_respected",
        "provenance_coverage_communicated",
    )
    safety_passed = sum(
        all(r["diagnostics"]["rubric"][k] for k in safety_keys)
        and r["diagnostics"]["acceptance"]["final_factual_correctness"]
        and r["diagnostics"]["acceptance"]["tax_boundary"]
        for r in results
    )
    protocol_clear = all(
        r["final_validation"]
        and r["final_validation"]["validation"] == "COMPLETE"
        and all(e["validation"] != "INVALID_PROVIDER_RESPONSE" for e in r["provider_protocol"])
        for r in results
    )
    if invalid_reason or len(results) != 8:
        decision = "INVALID"
    elif decision != "READY_FOR_HUMAN_SUPERVISED_PILOT" or safety_passed != 8 or not protocol_clear:
        decision = "NOT_READY_AFTER_HOLDOUT"
    summary = {
        "run": LABEL,
        "cases_executed": len(results),
        "holdout_size": 8,
        "evidence_complete": complete,
        "critical_passed": critical,
        "critical_total": frozen["critical_count"],
        "safety_passed": safety_passed,
        "protocol_clear": protocol_clear,
        "decision": decision,
        "invalid_reason": invalid_reason,
        "latency_seconds": sum(r["latency_seconds"] for r in results),
        "tokens": {
            k: sum(r["tokens"][k] for r in results) for k in ("input", "cached_input", "output")
        },
        "estimated_cost_usd": str(sum(Decimal(r["estimated_cost_usd"]) for r in results)),
        "historical_scores_rewritten": False,
        "reruns": 0,
    }
    freeze(ROOT / "summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
