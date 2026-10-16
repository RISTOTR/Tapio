"""Offline native reference-contract tests: never invoke a provider or the database."""

import asyncio
import copy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.api.tests.test_phase06 import PERIOD, response, row, synthetic_queries
from tapio.agent.acceptance.evaluate import score
from tapio.agent.acceptance.planning import infer_requirements
from tapio.agent.evaluation import CASES, evaluate_case, evaluation_registry
from tapio.agent.model import ModelTurn, ResultReference
from tapio.agent.providers.final_contract import FinalAnswer, executed_call_outcomes
from tapio.agent.providers.openai import OpenAIModel


def history(outcomes=(True, True)):
    messages = [{"role": "system", "content": "trusted"}]
    for ok in outcomes:
        messages.extend(
            [
                {"role": "assistant", "tool_call": {"name": "query_transactions", "arguments": {}}},
                {"role": "tool", "name": "query_transactions", "content": {"ok": ok}},
            ]
        )
    return messages


def parse(tmp_path, references, outcomes=(True, True)):
    model = OpenAIModel("synthetic-secret", protocol_dir=tmp_path)
    native = response(
        "finish_evidence_answer", {"references": references, "message_key": "results"}
    )
    turn = model.parse_response(native, history(outcomes), set())
    event = model.protocol_events[-1]
    artifact = json.loads(Path(event["private_artifact"]).read_text())
    return turn, event, artifact, native


@pytest.mark.parametrize(
    "references,expected,classification",
    [
        ([{"call_index": 0}, {"call_index": 1}], [0, 1], "VALID_CANONICAL_FINAL"),
        ([0, 1], [0, 1], "PROVIDER_FORMAT_NORMALIZED"),
        (0, [0], "PROVIDER_FORMAT_NORMALIZED"),
        ([1, {"call_index": 0}], [1, 0], "PROVIDER_FORMAT_NORMALIZED"),
    ],
)
def test_valid_reference_forms(tmp_path, references, expected, classification):
    original = copy.deepcopy(references)
    turn, event, _, _ = parse(tmp_path, references)
    assert all(isinstance(r, ResultReference) for r in turn.references)
    assert [r.call_index for r in turn.references] == expected
    assert event["validation"] == classification
    assert references == original


@pytest.mark.parametrize(
    "references",
    [
        [-1],
        -1,
        [2],
        ["0"],
        "0",
        [True],
        [1.0],
        [None],
        None,
        [{"call_index": "0"}],
        [{"call_index": True}],
        [{"call_index": 1.0}],
        [{"call_index": 0, "extra": "unknown"}],
        [0, {"other": 1}],
        [0, 0],
        [0, {"call_index": 0}],
        [[0]],
        {},
    ],
)
def test_invalid_references_fail_without_salvage(tmp_path, references):
    model = OpenAIModel("secret", protocol_dir=tmp_path)
    native = response(
        "finish_evidence_answer", {"references": references, "message_key": "results"}
    )
    with pytest.raises(ValueError, match="INVALID_FINAL_CONTENT"):
        model.parse_response(native, history(), set())
    event = model.protocol_events[-1]
    assert event["validation"] == "INVALID_FINAL_CONTENT"
    assert (
        json.loads(Path(event["private_artifact"]).read_text())["original_provider_output"]
        == native
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"message_key": "results"},
        {"references": [0]},
        {"references": [0], "message_key": "results", "call": None},
        {"references": [0], "message_key": "made_up"},
    ],
)
def test_missing_or_unknown_final_fields(tmp_path, arguments):
    model = OpenAIModel("secret", protocol_dir=tmp_path)
    with pytest.raises(ValueError, match="INVALID_FINAL_CONTENT"):
        model.parse_response(response("finish_evidence_answer", arguments), history(), set())


def test_failed_call_not_referenceable_and_indexes_not_renumbered(tmp_path):
    with pytest.raises(ValueError, match="FAILED_CALL"):
        parse(tmp_path, [0], outcomes=(False, True))
    turn, _, _, _ = parse(tmp_path, [1], outcomes=(False, True))
    assert turn.references[0].call_index == 1


def test_unexecuted_call_not_referenceable(tmp_path):
    model = OpenAIModel("secret", protocol_dir=tmp_path)
    messages = history() + [{"role": "assistant", "tool_call": {"name": "query_transactions"}}]
    with pytest.raises(ValueError, match="UNEXECUTED_TOOL_CALL"):
        model.parse_response(
            response("finish_evidence_answer", {"references": [2], "message_key": "results"}),
            messages,
            set(),
        )


def test_orphan_and_reused_tool_results_rejected():
    with pytest.raises(ValueError):
        executed_call_outcomes([{"role": "tool", "content": {"ok": True}}])
    with pytest.raises(ValueError):
        executed_call_outcomes(history() + [{"role": "tool", "content": {"ok": True}}])


def test_raw_and_normalized_output_are_private_and_separate(tmp_path):
    turn, event, artifact, native = parse(tmp_path, [0, 1])
    assert artifact["original_provider_output"] == native
    assert artifact["normalized_final"] == {
        "references": [{"call_index": 0}, {"call_index": 1}],
        "message_key": "results",
    }
    assert artifact["validation"] == "PROVIDER_FORMAT_NORMALIZED"
    assert artifact["executed_call_outcomes"] == [True, True]
    assert Path(event["private_artifact"]).stat().st_mode & 0o777 == 0o600
    assert "synthetic-secret" not in json.dumps(artifact)
    assert "original_provider_output" not in turn.model_dump()


def test_invalid_content_preserves_normalization_attempt(tmp_path):
    model = OpenAIModel("secret", protocol_dir=tmp_path)
    with pytest.raises(ValueError):
        model.parse_response(
            response("finish_evidence_answer", {"references": [99], "message_key": "results"}),
            history(),
            set(),
        )
    artifact = json.loads(Path(model.protocol_events[-1]["private_artifact"]).read_text())
    assert artifact["normalized_final"]["references"] == [{"call_index": 99}]
    assert artifact["validation"] == "INVALID_FINAL_CONTENT"


def test_duplicate_json_fields_rejected(tmp_path):
    native = response("finish_evidence_answer", {})
    native["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
        '{"references":[0],"references":[1],"message_key":"results"}'
    )
    with pytest.raises(ValueError, match="DUPLICATE_JSON_FIELD"):
        OpenAIModel("secret", protocol_dir=tmp_path).parse_response(native, history(), set())


def test_internal_reference_dto_does_not_normalize():
    for invalid in ("0", True, 0.0, -1):
        with pytest.raises(ValidationError):
            ResultReference(call_index=invalid)
    with pytest.raises(ValidationError):
        ModelTurn(references=[0])


def test_strict_finish_schema_and_unchanged_source_tool_schema(tmp_path):
    payloads = []
    source = {"name": "example", "description": "unchanged", "input_schema": {"type": "object"}}
    model = OpenAIModel(
        "secret",
        protocol_dir=tmp_path,
        transport=lambda p: (
            payloads.append(p)
            or response("finish_evidence_answer", {"references": [], "message_key": "unsupported"})
        ),
    )
    asyncio.run(model.generate_with_tools(history(()), [source]))
    source_function, finish = [t["function"] for t in payloads[0]["tools"]]
    assert source_function["parameters"] == source["input_schema"]
    assert source_function["description"] == source["description"]
    assert source_function["strict"] is False and finish["strict"] is True
    assert finish["parameters"] == FinalAnswer.model_json_schema()
    assert set(finish["parameters"]["required"]) == {"references", "message_key"}
    assert "ToolCall" not in finish["parameters"].get("$defs", {})
    for obj in [finish["parameters"], *finish["parameters"].get("$defs", {}).values()]:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


def test_normalization_does_not_make_missing_evidence_pass(tmp_path):
    outputs = iter(
        [
            response("summarize_finances", PERIOD),
            response("finish_evidence_answer", {"references": [0], "message_key": "results"}),
        ]
    )
    model = OpenAIModel(
        "secret", transport=lambda _: next(outputs), protocol_dir=tmp_path / "native"
    )
    registry = evaluation_registry(synthetic_queries([row("-1")]), audit_path=tmp_path / "audit")
    case = CASES[0]
    result = asyncio.run(evaluate_case(case, model, registry))
    assert result["response"]["status"] == "COMPLETE"
    assert not result["passed"] and not result["rubric"]["correct_tool_selection"]
    case_data = dict(id=case[0], required_tools=case[2], message_key=case[3], critical=False)
    assert not score(result, case_data, infer_requirements(case[1]))["EVIDENCE_COMPLETE"]
    assert model.protocol_events[-1]["validation"] == "PROVIDER_FORMAT_NORMALIZED"
    assert len(result["response"]["results"]) == 1


def test_normalization_does_not_manufacture_references(tmp_path):
    turn, _, _, _ = parse(tmp_path, [1])
    assert [r.call_index for r in turn.references] == [1]
    turn, _, _, _ = parse(tmp_path, [])
    assert turn.references == []


def test_renderer_and_phase06_scoring_unchanged():
    # Baseline hashes frozen before this repair; independent of provider representation.
    expected = {
        "tapio/agent/render.py": "bbc92cd05451aceaa87536a65d82efcb5ebf1dfc00dd7a85f4b4b7f61aecd791",
        "tapio/agent/evaluation.py": (
            "817f6ce1b5138ccf470dc9928d77fb4037af07890c6275809800e09084ad4c05"
        ),
        "tapio/agent/loop.py": "e4d099c77af58ef154f37c23ac169ed14d015a1b7f06ac21135111c6020c885e",
    }
    for name, digest in expected.items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest


def test_equivalent_formats_have_identical_rendering_and_scores(tmp_path):
    source_rows = [row("-1")]
    results = []
    for index, references in enumerate(([{"call_index": 0}], [0])):
        native_turns = iter(
            [
                response("summarize_finances", {**PERIOD, "business_context": "property"}),
                response(
                    "finish_evidence_answer", {"references": references, "message_key": "results"}
                ),
            ]
        )
        model = OpenAIModel(
            "secret",
            protocol_dir=tmp_path / str(index),
            transport=lambda _, turns=native_turns: next(turns),
        )
        registry = evaluation_registry(
            synthetic_queries(source_rows), audit_path=tmp_path / "audit"
        )
        case = next(c for c in CASES if c[0] == "property")
        results.append(asyncio.run(evaluate_case(case, model, registry)))
    assert results[0]["passed"] is True and results[1]["passed"] is True
    assert results[0]["response"] == results[1]["response"]
    assert results[0]["rubric"] == results[1]["rubric"]


def test_empty_and_overlong_reference_lists_do_not_gain_evidence(tmp_path):
    model = OpenAIModel("secret", protocol_dir=tmp_path)
    with pytest.raises(ValueError, match="INVALID_FINAL_SCHEMA"):
        model.parse_response(
            response(
                "finish_evidence_answer", {"references": list(range(9)), "message_key": "results"}
            ),
            history((True,) * 9),
            set(),
        )
    empty = model.parse_response(
        response("finish_evidence_answer", {"references": [], "message_key": "results"}),
        history(),
        set(),
    )
    assert empty.references == []


def test_malformed_native_envelope_is_retained_before_rejection(tmp_path):
    model = OpenAIModel("secret", protocol_dir=tmp_path, transport=lambda _: None)
    with pytest.raises(ValueError, match="INVALID_PROVIDER_RESPONSE"):
        asyncio.run(model.generate_with_tools(history(()), []))
    record = json.loads(Path(model.protocol_events[-1]["private_artifact"]).read_text())
    assert record["original_provider_output"] is None
    assert record["normalized_final"] is None
    assert record["validation"] == "INVALID_PROVIDER_RESPONSE"
