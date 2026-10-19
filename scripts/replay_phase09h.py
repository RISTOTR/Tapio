"""Offline context alternatives and deterministic rendering; no model finals invented."""

import asyncio
import json
from pathlib import Path

from data_pipeline.labels.snapshot import freeze
from scripts.phase08_acceptance import SNAPSHOT, check_inputs, digest
from tapio.agent.exclusive import ScopedCoordinator, ScopedPlan, scope_policy
from tapio.agent.mandatory import coordinated_registry
from tapio.agent.render_bounded import render_answer

ROOT = Path("data/interim/phase09h")
SOURCE = Path("data/interim/phase09g/C_scoped_v1")


def alternatives(raw, question):
    base = {k: v for k, v in raw.items() if k not in ("context_scope", "selected_contexts")}
    modes = []
    if raw["context_scope"] != "SELECTED":
        modes.append({"mode": raw["context_scope"]})
    if raw["selected_contexts"]:
        modes.append({"mode": "SELECTED", "contexts": raw["selected_contexts"]})
    accepted, rejected = {}, []
    for selection in modes:
        plan = ScopedPlan.model_validate({**base, "context_selection": selection})
        try:
            effective, _, _ = scope_policy(question, plan)
        except ValueError as exc:
            rejected.append({"selection": selection, "reason": str(exc)})
            continue
        key = json.dumps(effective.context_selection.model_dump(), sort_keys=True)
        accepted[key] = plan
    return list(accepted.values()), rejected


async def main():
    assert not (ROOT / "replay.json").exists()
    snapshot = json.loads(SNAPSHOT.read_text())
    before = check_inputs(snapshot)
    prior = json.loads((SOURCE / "frozen.json").read_text())
    protected = dict(prior["protected_hashes"])
    for folder in ("phase09f", "phase09g"):
        for path in Path("data/interim", folder).rglob("*"):
            if path.is_file() and "__pycache__" not in str(path):
                protected[str(path)] = digest(path)
    assert digest("tapio/agent/acceptance/datasets/holdout.json") == prior["holdout_hash"]
    runs = []
    for name in prior["case_ids"]:
        old = json.loads((SOURCE / "cases" / name / "result.json").read_text())
        native = json.loads((SOURCE / "cases" / name / "responses/00.json").read_text())
        raw = json.loads(native["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        plans, rejected = alternatives(raw, old["case"]["question"])
        branches = []
        for plan in plans:
            c = ScopedCoordinator(
                coordinated_registry(
                    coverage=snapshot["bank_coverage"], audit_path=ROOT / "read_audit.jsonl"
                ),
                plan,
                prior["period"],
                question=old["case"]["question"],
            )
            state = await c.execute()
            contract = c.finalization_contract()
            assert set(contract["required_final_handles"]) == set(c.ledger.handles)
            results = [e["result"] for e in c.envelopes]
            # Renderer-only probe: never a fabricated model final or benchmark score.
            answer = render_answer(
                results, "Evidence retrieved for offline structural verification."
            )
            review = [
                i
                for e in c.envelopes
                if "REVIEW_COVERAGE" in e["views"]
                for i in e["result"]["data"].get("items", [])
            ]
            tax = [
                i
                for e in c.envelopes
                if "TAX_BOUNDARY_CONTEXT" in e["views"]
                for i in e["result"]["data"].get("items", [])
                if "oikea konekaupp" in (i.get("counterparty") or "").lower()
            ]
            assert len(answer.split()) <= 850
            assert "no tax-deductibility decision" in answer
            if name == "review":
                assert len({i["id"] for i in review}) == 95
            if name == "tax":
                assert c.plan.context_scope == "UNSPECIFIED"
                assert tax and all(i["label_authority"] == "HUMAN_REVIEWED" for i in tax)
                assert contract["allowed_message_keys"] == ["tax_review_required"]
            branches.append(
                {
                    "provenance": c.provenance(),
                    "state": state,
                    "trace": c.trace,
                    "contract": contract,
                    "review_rows": len(review),
                    "tax_candidates": tax,
                    "renderer_words": len(answer.split()),
                }
            )
        failed = not branches or any(
            b["state"]["status"] != "MANDATORY_EVIDENCE_COMPLETE" for b in branches
        )
        classification = (
            "STRUCTURAL_FAILURE"
            if failed
            else "STRUCTURALLY_READY"
            if len(plans) == 1
            else "STILL_MODEL_DEPENDENT"
        )
        rendered = None
        if old["response"].get("status") == "COMPLETE":
            rendered = len(
                render_answer(old["response"]["results"], old["response"]["message"]).split()
            )
        runs.append(
            {
                "case": name,
                "raw_plan": raw,
                "scope_failed_before": old["raw_plan"] is None,
                "scope_replay": "STRUCTURALLY_PREVENTED"
                if len(plans) == 1
                else "STILL_MODEL_DEPENDENT",
                "classification": classification,
                "rejected_interpretations": rejected,
                "branches": branches,
                "retained_final_renderer_words": rendered,
            }
        )
        print(name, classification, rendered, flush=True)
    assert check_inputs(snapshot) == before
    assert all(digest(p) == h for p, h in protected.items())
    freeze(
        ROOT / "replay.json",
        {
            "runs": runs,
            "protected_hashes": protected,
            "source_fingerprints": before,
            "holdout_hash": prior["holdout_hash"],
            "model_calls": 0,
            "historical_scores_changed": False,
            "new_model_finals": 0,
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
