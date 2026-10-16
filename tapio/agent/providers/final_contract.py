"""Provider-boundary representation repair; no evidence selection or financial logic."""

from copy import deepcopy

from pydantic import Field

from tapio.agent.model import MessageKey, ModelTurn, ResultReference
from tapio.tools.schemas import Schema


class FinalAnswer(Schema):
    # Required here: the general ModelTurn defaults also serve intermediate tool calls.
    references: list[ResultReference] = Field(max_length=8)
    message_key: MessageKey


def executed_call_outcomes(messages):
    """Preserve original zero-based positions, including failed calls; never renumber."""
    outcomes = []
    pending = None
    for message in messages:
        if "tool_call" in message:
            if message.get("role") != "assistant" or pending is not None:
                raise ValueError("INVALID_EXECUTION_HISTORY")
            pending = message["tool_call"]["name"]
        elif message.get("role") == "tool":
            if pending is None or message.get("name", pending) != pending:
                raise ValueError("INVALID_EXECUTION_HISTORY")
            content = message.get("content")
            if not isinstance(content, dict) or type(content.get("ok")) is not bool:
                raise ValueError("INVALID_EXECUTION_HISTORY")
            outcomes.append(content["ok"])
            pending = None
    if pending is not None:
        raise ValueError("UNEXECUTED_TOOL_CALL")
    return outcomes


def normalize_final(arguments):
    """Wrap only exact integers; do not coerce, infer, drop, deduplicate or reorder."""
    if not isinstance(arguments, dict) or set(arguments) != {"references", "message_key"}:
        raise ValueError("INVALID_FINAL_FIELDS")
    references = arguments["references"]
    if type(references) is int:
        references = [references]
    if not isinstance(references, list):
        raise ValueError("INVALID_REFERENCE_CONTAINER")
    normalized = []
    for reference in references:
        if type(reference) is int:
            normalized.append({"call_index": reference})
        elif isinstance(reference, dict) and set(reference) == {"call_index"}:
            if type(reference["call_index"]) is not int:
                raise ValueError("INVALID_REFERENCE_INDEX_TYPE")
            normalized.append(deepcopy(reference))
        else:
            raise ValueError("INVALID_REFERENCE_SHAPE")
    return {"references": normalized, "message_key": deepcopy(arguments["message_key"])}


def validate_final(normalized, outcomes):
    final = FinalAnswer.model_validate(normalized)
    seen = set()
    for reference in final.references:
        index = reference.call_index
        if index in seen:
            raise ValueError("DUPLICATE_FINAL_REFERENCE")
        seen.add(index)
        if index >= len(outcomes):
            raise ValueError("FINAL_REFERENCE_OUT_OF_RANGE")
        if outcomes[index] is not True:
            raise ValueError("FINAL_REFERENCE_TO_FAILED_CALL")
    return ModelTurn(**final.model_dump())


def unique_json_object(pairs):
    """Reject ambiguous duplicate JSON keys instead of accepting last-value-wins."""
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("DUPLICATE_JSON_FIELD")
        obj[key] = value
    return obj
