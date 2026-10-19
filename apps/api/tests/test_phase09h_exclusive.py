"""Offline exclusive context and bounded trusted-output regressions."""

import asyncio
from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_phase09f_scoped import PERIOD, Registry
from test_phase09f_scoped import plan as legacy_plan

from scripts.replay_phase09h import alternatives
from tapio.agent.exclusive import ScopedCoordinator, ScopedPlan
from tapio.agent.providers.openai_exclusive import strict_schema
from tapio.agent.render_bounded import render_answer


def plan(selection, **kwargs):
    raw = legacy_plan(**kwargs).model_dump()
    raw.pop("context_scope")
    raw.pop("selected_contexts")
    return ScopedPlan(**raw, context_selection=selection)


@pytest.mark.parametrize(
    "selection",
    [
        {"mode": "ALL"},
        {"mode": "UNSPECIFIED"},
        *[
            {"mode": "SELECTED", "contexts": c}
            for c in [["PROPERTY"], ["FORESTRY"], ["PROPERTY", "FORESTRY"], ["UNKNOWN"]]
        ],
    ],
)
def test_canonical_modes(selection):
    assert plan(selection).context_selection.model_dump() == selection


@pytest.mark.parametrize(
    "selection",
    [
        {"mode": "ALL", "contexts": ["PROPERTY"]},
        {"mode": "ALL", "contexts": []},
        {"mode": "UNSPECIFIED", "contexts": ["UNKNOWN"]},
        {"mode": "SELECTED"},
        {"mode": "SELECTED", "contexts": []},
        {"mode": "SELECTED", "contexts": ["INVALID"]},
        {"mode": "SELECTED", "contexts": ["UNKNOWN", "UNKNOWN"]},
    ],
)
def test_impossible_combinations(selection):
    with pytest.raises(ValidationError):
        plan(selection)


def test_provider_schema_exclusive():
    schema = strict_schema(ScopedPlan)
    branches = schema["properties"]["context_selection"]["anyOf"]
    assert len(branches) == 3
    for branch in branches:
        obj = schema["$defs"][branch["$ref"].split("/")[-1]]
        assert obj["additionalProperties"] is False
        mode = obj["properties"]["mode"]["const"]
        assert ("contexts" in obj["properties"]) == (mode == "SELECTED")
        if mode == "SELECTED":
            assert obj["properties"]["contexts"]["minItems"] == 1
    assert "context_scope" not in schema["properties"]
    assert "selected_contexts" not in schema["properties"]


def test_unknown_not_discovery():
    assert plan({"mode": "SELECTED", "contexts": ["UNKNOWN"]}).required_contexts == ["UNKNOWN"]
    assert plan({"mode": "UNSPECIFIED"}).required_contexts == []


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Which transactions still need human review?", 1),
        ("What did the property cost?", 2),
        ("Can I deduct the Oikea Konekauppa purchases?", 1),
    ],
)
def test_retained_contradiction_not_guessed(question, expected):
    raw = legacy_plan(scope="ALL", contexts=[]).model_dump()
    raw["selected_contexts"] = ["PROPERTY"]
    if "deduct" in question:
        raw["context_scope"] = "UNSPECIFIED"
        raw["selected_contexts"] = ["UNKNOWN"]
    choices, _ = alternatives(raw, question)
    assert len(choices) == expected


def test_general_review_95_and_tax_discovery():
    async def check():
        c = ScopedCoordinator(
            Registry(),
            plan({"mode": "SELECTED", "contexts": ["UNKNOWN"]}, question_type="review"),
            PERIOD,
            question="Which transactions still need human review?",
        )
        await c.execute()
        rows = [
            i
            for e in c.envelopes
            if "REVIEW_COVERAGE" in e["views"]
            for i in e["result"]["data"].get("items", [])
        ]
        assert len(rows) == 95
        assert c.plan.context_selection.mode == "ALL"
        t = ScopedCoordinator(
            Registry(),
            plan({"mode": "UNSPECIFIED"}, question_type="tax", needs_tax_boundary=True),
            PERIOD,
            question="Can I deduct the Oikea Konekauppa purchases?",
        )
        await t.execute()
        assert t.plan.required_contexts == []
        assert t.finalization_contract()["allowed_message_keys"] == ["tax_review_required"]

    asyncio.run(check())


def test_renderer_maximum_and_source_preserved():
    results = [
        {"ok": True, "tool": "query_transactions", "data": {"items": [], "truncated": False}}
    ] * 1000
    before = deepcopy(results)
    answer = render_answer(results, "unbounded message " * 1000)
    assert len(answer.split()) <= 850
    assert "no tax-deductibility decision" in answer
    assert results == before


def test_new_coordinator_keeps_reference_gate_and_bounded_renderer():
    async def check():
        c = ScopedCoordinator(
            Registry(),
            plan({"mode": "UNSPECIFIED"}, question_type="tax", needs_tax_boundary=True),
            PERIOD,
            question="Tell me which expenses I can deduct.",
        )
        await c.execute()
        handles = c.finalization_contract()["required_final_handles"]
        incomplete = c.finalize(
            {
                "references": [{"evidence_handle": h} for h in handles[:-1]],
                "message_key": "tax_review_required",
            }
        )
        assert incomplete["status"] != "COMPLETE"
        complete = c.finalize(
            {
                "references": [{"evidence_handle": h} for h in handles],
                "message_key": "tax_review_required",
            }
        )
        assert complete["status"] == "COMPLETE"
        assert len(complete["answer"].split()) <= 850
        assert len(complete["results"]) == len(handles)

    asyncio.run(check())


@pytest.mark.parametrize(
    "selection",
    [
        {"mode": "ALL"},
        {"mode": "UNSPECIFIED"},
        {"mode": "SELECTED", "contexts": ["PROPERTY"]},
        {"mode": "SELECTED", "contexts": ["FORESTRY"]},
        {"mode": "SELECTED", "contexts": ["PROPERTY", "FORESTRY"]},
        {"mode": "SELECTED", "contexts": ["UNKNOWN"]},
    ],
)
def test_provider_json_schema_validates_one_branch(selection):
    from jsonschema import Draft202012Validator

    schema = strict_schema(ScopedPlan)
    instance = plan(selection).model_dump(mode="json")
    Draft202012Validator(schema).validate(instance)
    matches = 0
    for branch in schema["properties"]["context_selection"]["anyOf"]:
        branch_schema = {**branch, "$defs": schema["$defs"]}
        matches += Draft202012Validator(branch_schema).is_valid(selection)
    assert matches == 1
    for invalid in [
        {"mode": "ALL", "contexts": ["PROPERTY"]},
        {"mode": "UNSPECIFIED", "contexts": ["UNKNOWN"]},
        {"mode": "SELECTED", "contexts": []},
    ]:
        instance["context_selection"] = invalid
        assert not Draft202012Validator(schema).is_valid(instance)
