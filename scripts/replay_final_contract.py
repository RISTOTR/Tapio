"""Offline counterfactual parser replay. No credentials, provider or database calls."""

import asyncio
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from integrations.gmail.cache import private_write
from tapio.agent.acceptance.evaluate import load_cases, score
from tapio.agent.acceptance.planning import infer_requirements, missing_requirements
from tapio.agent.evaluation import ScriptedModel, evaluate_case
from tapio.agent.model import ModelTurn
from tapio.agent.providers.openai import OpenAIModel

ROOT = Path("data/interim/phase07")
OUTPUT = Path("data/interim/protocol_repair")


class RecordedRegistry:
    """Returns only the exact already-executed calls; never executes a tool."""

    def __init__(self, trace):
        self.trace = copy.deepcopy(trace)
        self.position = 0

    def specifications(self):
        return []

    async def call(self, name, arguments, session_id="offline-replay"):
        original = self.trace[self.position]
        assert (name, arguments) == (original["tool"], original["arguments"])
        self.position += 1
        return copy.deepcopy(original["result"])


def messages_from_trace(trace):
    messages = [{"role": "system", "content": "Offline recorded execution history"}]
    for item in trace:
        messages += [
            {
                "role": "assistant",
                "tool_call": {"name": item["tool"], "arguments": item["arguments"]},
            },
            {"role": "tool", "name": item["tool"], "content": item["result"]},
        ]
    return messages


async def replay(native, historical, case, output=OUTPUT):
    def no_network(_):
        raise AssertionError("REPLAY_MUST_NOT_CALL_PROVIDER")

    model = OpenAIModel(
        "offline-no-credential", transport=no_network, protocol_dir=output / "native_protocol"
    )
    final = model.parse_response(native, messages_from_trace(historical["trace"]), set())
    turns = [
        ModelTurn(call={"name": t["tool"], "arguments": t["arguments"]})
        for t in historical["trace"]
    ] + [final]
    result = await evaluate_case(
        (case["id"], case["question"], case["required_tools"], case["message_key"]),
        ScriptedModel(turns),
        RecordedRegistry(historical["trace"]),
    )
    result["acceptance"] = score(result, case, infer_requirements(case["question"]))
    result["provider_protocol"] = model.protocol_events
    result["mode"] = "COUNTERFACTUAL_PARSER_REPLAY_ONLY"
    return result


def inventory(cases):
    findings = []
    for config in "ABC":
        summary = json.loads((ROOT / f"{config}_development.json").read_text())
        for result in summary["results"]:
            case = cases[result["case"]]
            available = [{"tool": t["tool"], **t["result"]} for t in result["trace"]]
            names = {r["tool"] for r in available if r.get("ok")}
            missing = missing_requirements(
                infer_requirements(case["question"]), available, result["trace"]
            )
            missing_tools = sorted(set(case["required_tools"]) - names)
            if result["acceptance"]["EVIDENCE_COMPLETE"]:
                classification = "PASSED_HISTORICALLY"
            elif missing or missing_tools or not result["rubric"]["correct_source_scope"]:
                classification = "EVIDENCE_RETRIEVAL_INCOMPLETE"
            elif result["response"].get("answer"):
                classification = "VALID_FINAL_BUT_FAILED_ACCEPTANCE"
            else:
                classification = "RAW_FINAL_UNAVAILABLE"
            findings.append(
                dict(
                    configuration=config,
                    case=case["id"],
                    classification=classification,
                    missing_views=missing,
                    missing_tools=missing_tools,
                    historical_status=result["response"]["status"],
                )
            )
    return findings


async def main():
    target = OUTPUT / "counterfactual_replay.json"
    if target.exists():
        raise ValueError("REPLAY_REPORT_EXISTS_NO_OVERWRITE")
    cases = {c["id"]: c for c in load_cases("development")}
    # This association is explicitly recorded by phase07/diagnose_finish.py, not inferred.
    native_path = ROOT / "finish_diagnostic_native.json"
    trace_path = ROOT / "B_development_primary.json"
    native = json.loads(native_path.read_text())
    historical = json.loads(trace_path.read_text())
    arguments = json.loads(
        native["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    )
    try:
        ModelTurn.model_validate(arguments)
        before_valid = True
    except ValidationError:
        before_valid = False
    result = await replay(native, historical, cases[historical["case"]])
    findings = inventory(cases)
    report = dict(
        mode="COUNTERFACTUAL_PARSER_REPLAY_ONLY",
        paid_calls=0,
        database_calls=0,
        raw_capture_count=1,
        repaired_raw_rejections=int(not before_valid),
        still_invalid_raw=0,
        replay_evidence_complete=result["acceptance"]["EVIDENCE_COMPLETE"],
        replay_evidence_failures=int(not result["acceptance"]["EVIDENCE_COMPLETE"]),
        provenance=(
            "Diagnostic replay of B primary final turn; not the original benchmark response."
        ),
        historical_explicit_schema_rejections=sum(
            x["historical_status"] == "MODEL_TOOL_SCHEMA_ERROR" for x in findings
        ),
        historical_rejected_native_outputs_retained=0,
        limitation=(
            "The other native rejections were not retained. "
            "Their exact representation cannot be reconstructed."
        ),
        classification_counts=dict(Counter(x["classification"] for x in findings)),
        native_sha256=hashlib.sha256(native_path.read_bytes()).hexdigest(),
        trace_sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        findings=findings,
        replay=result,
    )
    private_write(target, json.dumps(report, indent=2).encode())
    print(json.dumps({k: v for k, v in report.items() if k not in ("findings", "replay")}))


if __name__ == "__main__":
    asyncio.run(main())
