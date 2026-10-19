"""Offline retained-plan structural replay. Never invokes a provider or fabricates a final."""

import asyncio
import json
from pathlib import Path

from data_pipeline.labels.snapshot import freeze
from scripts.phase08_acceptance import SNAPSHOT, check_inputs, digest
from tapio.agent.mandatory import coordinated_registry
from tapio.agent.scoped import ScopedCoordinator, ScopedPlan

ROOT = Path("data/interim/phase09f")
SOURCE = Path("data/interim/phase09d/C_coordinated_v1")


def migrate_recorded_plan(record):
    raw = record["raw_plan"]
    contexts = raw["required_contexts"]
    scope = "SELECTED" if contexts else "UNSPECIFIED"
    interpretation = "Explicit legacy scope mapping; not a new model output."
    if record["case"]["id"] == "tax":
        # The requested regression is an explicit discovery hypothesis, NOT UNKNOWN coercion.
        scope, contexts = "UNSPECIFIED", []
        interpretation = (
            "Requested UNSPECIFIED tax-discovery hypothesis from recorded tax intent. "
            "Original UNKNOWN plan retained; literal SELECTED UNKNOWN still rejects."
        )
    plan = ScopedPlan.model_validate(
        {
            **{k: v for k, v in raw.items() if k != "required_contexts"},
            "context_scope": scope,
            "selected_contexts": contexts,
        }
    )
    return plan, interpretation


async def main():
    target = ROOT / "structural_replay.json"
    if target.exists():
        raise ValueError("REPLAY_EXISTS_NO_OVERWRITE")
    snapshot = json.loads(SNAPSHOT.read_text())
    before = check_inputs(snapshot)
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
        ]
        for p in Path(base).rglob("*")
        if p.is_file() and "__pycache__" not in str(p)
    }
    prior = json.loads((SOURCE / "frozen.json").read_text())
    protected.update(prior["protected_hashes"])
    assert digest("tapio/agent/acceptance/datasets/holdout.json") == prior["holdout_hash"]
    runs = []
    for name in prior["case_ids"]:
        old = json.loads((SOURCE / "cases" / name / "result.json").read_text())
        plan, interpretation = migrate_recorded_plan(old)
        c = ScopedCoordinator(
            coordinated_registry(
                coverage=snapshot["bank_coverage"], audit_path=ROOT / "local_read_audit.jsonl"
            ),
            plan,
            {"date_from": "2026-01-01", "date_to": "2026-12-31"},
            question=old["case"]["question"],
        )
        state = await c.execute()
        contract = c.finalization_contract()
        assert "call_index" not in json.dumps(contract)
        assert all(
            d["final_reference_required"] and d["retrieval_required"]
            for d in c.ledger.handles.values()
        )
        assert set(contract["required_final_handles"]) == set(c.ledger.handles)
        old_queries = [(t["tool"], t["arguments"]) for t in old["trace"]]
        new_queries = [(t["tool"], t["arguments"]) for t in c.trace]
        prior_omissions = []
        if name in ["receipts", "ambiguous", "review"]:
            selected = {
                x["evidence_handle"]
                for x in old["final_validation"]["requested_final"]["references"]
            }
            for old_h in old["mandatory_handles"]:
                if old_h in selected:
                    continue
                old_t = old["trace"][old["handles"][old_h]["call_index"]]
                matching = [
                    h
                    for h, meta in c.ledger.handles.items()
                    if c.trace[meta["call_index"]]["tool"] == old_t["tool"]
                    and c.trace[meta["call_index"]]["arguments"] == old_t["arguments"]
                ]
                assert matching and all(h in contract["required_final_handles"] for h in matching)
                prior_omissions.append(
                    {"old_handle": old_h, "new_required_handles": matching, "tool": old_t["tool"]}
                )
        review_rows = [
            i
            for e in c.envelopes
            if "REVIEW_COVERAGE" in e["views"]
            for i in e["result"]["data"].get("items", [])
        ]
        if name == "review":
            assert len(review_rows) == snapshot["review_coverage"]["unresolved"] == 95
            assert len({i["id"] for i in review_rows}) == 95
            assert all(i["label_authority"] == "UNREVIEWED" for i in review_rows)
        if name == "primary":
            bank = [t for t in c.trace if t["tool"] == "summarize_finances"]
            assert len(bank) == 1 and bank[0]["arguments"]["business_context"] is None
        target_ambiguity = [
            t["result"]["data"]
            for t in c.trace
            if t["tool"] == "get_invoice_reconciliation"
            and t["result"].get("ok")
            and t["result"]["data"]["state"] == "AMBIGUOUS"
        ]
        if name in ["ambiguous", "review", "receipts", "primary"]:
            assert target_ambiguity and all(d["human_review_required"] for d in target_ambiguity)
        tax_candidates = [
            i
            for e in c.envelopes
            if "TAX_BOUNDARY_CONTEXT" in e["views"]
            for i in e["result"]["data"].get("items", [])
            if "oikea konekaupp" in (i.get("counterparty") or "").casefold()
        ]
        if name == "tax":
            assert tax_candidates and all(
                i["label_authority"] == "HUMAN_REVIEWED" for i in tax_candidates
            )
            assert contract["allowed_message_keys"] == ["tax_review_required"]
        structural = (
            "STRUCTURALLY_PREVENTED" if name in ["tax", "primary"] else "STILL_MODEL_DEPENDENT"
        )
        run = {
            "case": name,
            "recorded_raw_plan": old["raw_plan"],
            "scope_interpretation": interpretation,
            **c.provenance(),
            "state": state,
            "finalization_contract": contract,
            "trace": c.trace,
            "handles": c.ledger.handles,
            "context_changes_effective_retrieval": (
                sorted(json.dumps(q, sort_keys=True) for q in old_queries)
                != sorted(json.dumps(q, sort_keys=True) for q in new_queries)
            ),
            "prior_omissions_explicitly_required": prior_omissions,
            "reference_regression": "REFERENCE_OMISSION_PREVENTABLE" if prior_omissions else None,
            "review_rows": len(review_rows),
            "tax_candidate_evidence": tax_candidates,
            "target_ambiguity": target_ambiguity,
            "classification": structural,
            "new_model_final_observed": False,
            "historical_score_changed": False,
        }
        runs.append(run)
        print(
            json.dumps(
                {
                    "case": name,
                    "status": state["status"],
                    "calls": len(c.trace),
                    "required_handles": len(contract["required_final_handles"]),
                    "review_rows": len(review_rows),
                    "classification": structural,
                }
            ),
            flush=True,
        )
    assert check_inputs(snapshot) == before
    assert all(digest(p) == h for p, h in protected.items())
    summary = {
        "cases": len(runs),
        "mandatory_complete": sum(
            r["state"]["status"] == "MANDATORY_EVIDENCE_COMPLETE" for r in runs
        ),
        "explicit_final_handle_contracts": len(runs),
        "scope_changed_cases": [
            r["case"] for r in runs if r["context_changes_effective_retrieval"]
        ],
        "structural_failure_preventions": ["tax: UNSPECIFIED hypothesis", "primary: ALL"],
        "reference_omission_preventable": ["receipts", "ambiguous", "review"],
        "review_semantic_coverage_rows": 95,
        "all_final_selection_still_model_dependent": True,
        "model_calls": 0,
        "api_tokens": 0,
        "benchmark_passes_claimed": False,
    }
    freeze(
        target,
        {
            "summary": summary,
            "runs": runs,
            "source_fingerprints": before,
            "snapshot_hash": digest(SNAPSHOT),
            "protected_hashes": protected,
            "holdout_hash": prior["holdout_hash"],
        },
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
