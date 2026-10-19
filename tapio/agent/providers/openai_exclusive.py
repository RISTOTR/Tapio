"""Versioned provider adapter for semantic plans and explicit evidence handles."""

import asyncio
import json
import time
from copy import deepcopy
from pathlib import Path

from tapio.agent.exclusive import ScopedPlan, ScopedTurn
from tapio.agent.mandatory import HandleFinal
from tapio.agent.providers.final_contract import unique_json_object
from tapio.agent.providers.openai import OpenAIModel


def strict_schema(model):
    schema = model.model_json_schema()

    def visit(value):
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object" and "properties" in value:
                value["required"] = list(value["properties"])
                value["additionalProperties"] = False
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(schema)
    return schema


class OpenAIExclusiveModel(OpenAIModel):
    def __init__(
        self, *args, protocol_dir=Path("data/interim/phase09h/provider_protocol"), **kwargs
    ):
        super().__init__(*args, protocol_dir=protocol_dir, **kwargs)

    async def generate_with_tools(self, messages, tools):
        raise ValueError("USE_RUN_SCOPED_AGENT_FOR_HANDLE_PROTOCOL")

    async def generate_coordinated(self, messages, tools, *, planning, final_only=False):
        name = "submit_evidence_plan" if planning else "finish_evidence_answer"
        schema = strict_schema(ScopedPlan if planning else HandleFinal)
        functions = (
            []
            if planning or final_only
            else [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                        "strict": False,
                    },
                }
                for t in tools
            ]
        )
        functions.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": "Declare semantic evidence requirements; no facts."
                    if planning
                    else (
                        "Finish using existing evidence_handle values. "
                        "Include every supplied required_final_handle. "
                        "No prose or arithmetic."
                    ),
                    "parameters": schema,
                    "strict": True,
                },
            }
        )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": m["role"],
                    "content": m["content"]
                    if isinstance(m["content"], str)
                    else json.dumps(m["content"]),
                }
                for m in messages
            ],
            "tools": functions,
            "tool_choice": {"type": "function", "function": {"name": name}}
            if planning or final_only
            else "required",
            "parallel_tool_calls": False,
            "store": False,
            "max_completion_tokens": 3000,
            "reasoning_effort": "none",
        }
        start = time.monotonic()
        response = await asyncio.to_thread(self.transport, payload)
        metadata = response if isinstance(response, dict) else {}
        self.usage.append(
            {
                "latency_seconds": time.monotonic() - start,
                "usage": metadata.get("usage", {}),
                "model": metadata.get("model"),
            }
        )
        return self.parse_coordinated(
            response, {f["function"]["name"] for f in functions}, planning
        )

    def parse_coordinated(self, response, names, planning):
        record = {
            "original_provider_output": deepcopy(response),
            "normalized_final": None,
            "representation_changed": False,
            "validation": "INVALID_PROVIDER_RESPONSE",
            "error_code": None,
        }
        try:
            choices = response["choices"]
            if len(choices) != 1 or choices[0]["finish_reason"] != "tool_calls":
                raise ValueError("ONE_NATIVE_TOOL_CALL_REQUIRED")
            calls = choices[0]["message"]["tool_calls"]
            if len(calls) != 1:
                raise ValueError("ONE_NATIVE_TOOL_CALL_REQUIRED")
            f = calls[0]["function"]
            if f["name"] not in names:
                raise ValueError("UNEXPECTED_COORDINATED_FUNCTION")
            args = json.loads(f["arguments"], object_pairs_hook=unique_json_object)
            if planning:
                turn = ScopedTurn(plan=ScopedPlan.model_validate(args))
                record["validation"] = "VALID_EVIDENCE_PLAN"
            elif f["name"] == "finish_evidence_answer":
                final = HandleFinal.model_validate(args)
                record["normalized_final"] = final.model_dump(mode="json")
                record["validation"] = "VALID_HANDLE_SCHEMA_PENDING_LEDGER_VALIDATION"
                turn = ScopedTurn(final=final)
            else:
                turn = ScopedTurn(call={"name": f["name"], "arguments": args})
                record["validation"] = "VALID_OPTIONAL_TOOL_CALL"
            return turn
        except (ValueError, TypeError, KeyError, IndexError):
            record["error_code"] = "INVALID_COORDINATED_PROVIDER_OUTPUT"
            raise ValueError("INVALID_COORDINATED_PROVIDER_OUTPUT") from None
        finally:
            self._record_protocol(record)
