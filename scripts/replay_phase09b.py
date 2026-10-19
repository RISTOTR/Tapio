"""Fresh local read-only mandatory-retrieval replay; never creates model decisions."""

import asyncio
import json
from collections import Counter
from pathlib import Path

from data_pipeline.labels.snapshot import freeze
from scripts.phase08_acceptance import SNAPSHOT, check_inputs, digest
from tapio.agent.mandatory import (
    MandatoryCoordinator,
    coordinated_registry,
    enforce_policy,
    legacy_plan,
    required_views,
)

ROOT = Path("data/interim/phase09b")


def classify_replay(missing_plan, state):
    if state is None:
        return "NOT_REPLAYABLE"
    if missing_plan:
        return "PLAN_ITSELF_INCOMPLETE"
    return (
        "MANDATORY_EVIDENCE_COMPLETE"
        if state["status"] == "MANDATORY_EVIDENCE_COMPLETE"
        else "MANDATORY_EVIDENCE_RETRIEVAL_FAILED"
    )


async def main():
    target = ROOT / "mandatory_replay.json"
    if target.exists():
        raise ValueError("REPLAY_EXISTS_NO_OVERWRITE")
    snapshot = json.loads(SNAPSHOT.read_text())
    before = check_inputs(snapshot)
    roots = [Path("data/interim/phase08/development_rerun_v1"), Path("data/interim/phase09")]
    protected = {
        str(p): digest(p)
        for root in roots
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in str(p)
    }
    inventory = json.loads(Path("data/interim/phase09/failure_inventory.json").read_text())
    runs = []
    for old in inventory["runs"]:
        base = {
            "configuration": old["configuration"],
            "question_id": old["question_id"],
            "historical_pass": old["evidence_complete"],
        }
        if old["actual_plan"] is None:
            runs.append(
                {
                    **base,
                    "classification": "NOT_REPLAYABLE",
                    "reason": "NO_RETAINED_MODEL_PLAN_NO_SYNTHETIC_PLAN_INVENTED",
                }
            )
            continue
        plan = legacy_plan(old["actual_plan"])
        policy = enforce_policy(old["question"], plan)
        missing_plan = sorted(required_views(policy) - required_views(plan))
        registry = coordinated_registry(
            coverage=snapshot["bank_coverage"], audit_path=ROOT / "local_tool_audit.jsonl"
        )
        coordinator = MandatoryCoordinator(
            registry, plan, {"date_from": "2026-01-01", "date_to": "2026-12-31"}
        )
        state = await coordinator.execute()
        classification = classify_replay(missing_plan, state)
        runs.append(
            {
                **base,
                "classification": classification,
                "missing_plan_views": missing_plan,
                "declared_plan": plan.model_dump(mode="json"),
                "policy_plan": policy.model_dump(mode="json"),
                "state": state,
                "trace": coordinator.trace,
                "execution_mode": "FRESH_LOCAL_DETERMINISTIC_READ_ONLY_TOOLS",
                "model_final_replayed": False,
                "structurally_prevented_failure": not old["evidence_complete"]
                and classification == "MANDATORY_EVIDENCE_COMPLETE"
                and "EVIDENCE_NOT_REQUESTED" in old["failure_classes"],
            }
        )
        print(
            json.dumps(
                {
                    **base,
                    "classification": classification,
                    "calls": len(coordinator.trace),
                    "missing": state["missing_views"],
                    "errors": state["errors"],
                }
            ),
            flush=True,
        )
    after = check_inputs(snapshot)
    assert before == after and all(digest(p) == h for p, h in protected.items())
    summary = {
        "counts": dict(Counter(r["classification"] for r in runs)),
        "prior_failures_now_have_complete_mandatory_evidence": sum(
            not r["historical_pass"] and r["classification"] == "MANDATORY_EVIDENCE_COMPLETE"
            for r in runs
        ),
        "structurally_prevented_phase08_failures": sum(
            r.get("structurally_prevented_failure", False) for r in runs
        ),
        "plan_missing_cases": [
            r["question_id"] for r in runs if r["classification"] == "PLAN_ITSELF_INCOMPLETE"
        ],
        "source_tables_unchanged": len(after),
        "model_calls": 0,
        "historical_scores_unchanged": True,
        "holdout_contents_opened": False,
    }
    freeze(
        target,
        {
            "snapshot_sha256": digest(SNAPSHOT),
            "source_fingerprints": after,
            "protected_artifact_hashes": protected,
            "summary": summary,
            "runs": runs,
        },
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
