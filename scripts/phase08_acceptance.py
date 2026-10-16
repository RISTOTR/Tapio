"""Phase 08 evaluation runner: frozen inputs, existing scoring, private native traces."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import select, text

from apps.api.app.core.database import SessionLocal
from apps.api.app.domain.models import Document
from data_pipeline.labels.snapshot import fingerprint, freeze
from tapio.agent.acceptance import evaluate
from tapio.agent.acceptance.registry import acceptance_registry
from tapio.agent.providers.openai import OpenAIModel

SNAPSHOT = Path("data/interim/phase08/human_review_20261016_268cbff95973/snapshot.json")
SNAPSHOT_HASH = "ee55cdd801da98d66acd09dd754222457cdc464f38fabe0471b186456e0b5221"
ROOT = Path("data/interim/phase08/development_rerun_v1")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_inputs(snapshot):
    if digest(SNAPSHOT) != SNAPSHOT_HASH:
        raise ValueError("SNAPSHOT_CHANGED")
    for name, expected in {**snapshot["protected_files"], **snapshot["protocol_hashes"]}.items():
        if digest(name) != expected:
            raise ValueError("PROTECTED_INPUT_CHANGED")
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        actual = {
            name: fingerprint(
                [
                    dict(r)
                    for r in session.execute(select(Document.metadata.tables[name])).mappings()
                ]
            )
            for name in snapshot["source_fingerprints"]
        }
    if actual != snapshot["source_fingerprints"]:
        raise ValueError("SOURCE_SNAPSHOT_CHANGED")
    return actual


async def run(stage, config):
    snapshot = json.loads(SNAPSHOT.read_text())
    fingerprints = check_inputs(snapshot)
    output = ROOT / ("smoke" if stage == "smoke" else "development")
    manifest_path = ROOT / "inputs.json"
    specs = acceptance_registry(coverage=snapshot["bank_coverage"]).specifications()
    inputs = {
        "snapshot_path": str(SNAPSHOT),
        "snapshot_sha256": digest(SNAPSHOT),
        "source_fingerprints": fingerprints,
        "human_review": snapshot["review_coverage"],
        "dataset_hashes": snapshot["dataset_hashes"],
        "protocol_hashes": snapshot["protocol_hashes"],
        "tool_specifications": specs,
        "tool_registry_sha256": digest("tapio/agent/acceptance/registry.py"),
        "system_policy_sha256": digest("tapio/agent/policy.py"),
        "runner_sha256": digest(__file__),
        "configs": evaluate.CONFIGS,
        "max_rounds": 6,
        "holdout_opened": False,
    }
    # JSON round-trip makes tuple serialization identical on subsequent invocations.
    inputs = json.loads(json.dumps(inputs))
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != inputs:
            raise ValueError("FROZEN_RUN_INPUTS_CHANGED")
    else:
        freeze(manifest_path, inputs)
    if stage != "smoke":
        smoke = json.loads((ROOT / "smoke" / "B_development.json").read_text())["results"][0]
        valid = [
            e
            for e in smoke["provider_protocol"]
            if e["validation"] in ("VALID_CANONICAL_FINAL", "PROVIDER_FORMAT_NORMALIZED")
        ]
        if not valid or smoke["response"]["status"] != "COMPLETE":
            raise ValueError("SMOKE_CONTRACT_FAILED_STOP")
    evaluate.OUTPUT = output
    evaluate.acceptance_registry = lambda **kwargs: acceptance_registry(
        coverage=snapshot["bank_coverage"], **kwargs
    )

    class AuditedModel(OpenAIModel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, protocol_dir=output / "provider_protocol")

        def _post(self, payload):
            record = {
                "model": payload["model"],
                "final_function": payload["tools"][-1],
                "success": False,
            }
            try:
                response = super()._post(payload)
                record["success"] = True
                return response
            except ValueError as exc:
                record["error_code"] = str(exc)
                raise
            finally:
                from uuid import uuid4

                freeze(output / "requests" / f"{uuid4().hex}.json", record)

    evaluate.OpenAIModel = AuditedModel
    if stage == "smoke":
        if config != "B":
            raise ValueError("SMOKE_USES_PHASE07_STRONGER_MODEL")
        cases = evaluate.load_cases("development")
        chosen = next(c for c in cases if c["id"] == "primary")
        evaluate.load_cases = lambda split: [chosen]
    await evaluate.run(config, "development")
    check_inputs(snapshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["smoke", "development"], required=True)
    parser.add_argument("--config", choices=["A", "B", "C"], required=True)
    args = parser.parse_args()
    asyncio.run(run(args.stage, args.config))


if __name__ == "__main__":
    main()
