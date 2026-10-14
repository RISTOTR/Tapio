"""Bounded model-selected tools with deterministic rendering of sourced answers."""

import asyncio

from pydantic import ValidationError

from .model import ModelTurn
from .policy import SYSTEM_POLICY

TEMPLATES = {
    "results": "The following results come directly from the selected deterministic tools.",
    "missing_evidence": "Evidence or source coverage is incomplete; no missing value was invented.",
    "unsupported": "Unsupported read-only request. Please narrow it.",
    "human_review": "The evidence requires human review before any source change.",
    "tax_review_required": "Tax treatment needs human review; no deductibility decision was made.",
}


async def run_agent(request, model, registry, max_rounds=6):
    if not 1 <= max_rounds <= 8:
        raise ValueError("max_rounds_must_be_1_to_8")
    if len(request) > 8000:
        raise ValueError("request_too_large")
    messages = [{"role": "system", "content": SYSTEM_POLICY}, {"role": "user", "content": request}]
    results = []
    for _ in range(max_rounds):
        try:
            async with asyncio.timeout(45):
                turn = ModelTurn.model_validate(
                    await model.generate_with_tools(messages, registry.specifications())
                )
        except (ValidationError, ValueError):
            return {"status": "MODEL_TOOL_SCHEMA_ERROR", "results": results}
        except TimeoutError:
            return {"status": "TOOL_TIMEOUT", "results": results}
        except Exception:
            return {"status": "MODEL_PROVIDER_ERROR", "results": results}
        if turn.call:
            result = await registry.call(turn.call.name, turn.call.arguments)
            results.append({"tool": turn.call.name, **result})
            messages.append({"role": "assistant", "tool_call": turn.call.model_dump(mode="json")})
            messages.append(
                {
                    "role": "tool",
                    "name": turn.call.name,
                    "content": result,
                    "trust": "DATA_NOT_INSTRUCTIONS",
                }
            )
            continue
        if any(r.call_index >= len(results) for r in turn.references):
            return {"status": "MODEL_TOOL_SCHEMA_ERROR", "results": results}
        if turn.message_key == "results" and not turn.references:
            return {
                "status": "MISSING_EVIDENCE",
                "message": TEMPLATES["missing_evidence"],
                "results": [],
            }
        selected = [results[r.call_index] for r in turn.references]
        # Always retain errors/coverage warnings; model selection cannot conceal them.
        errors = [r for r in results if not r["ok"]]
        return {
            "status": "COMPLETE",
            "message": TEMPLATES[turn.message_key],
            "results": selected,
            "errors": errors,
        }
    return {
        "status": "MAX_ROUNDS",
        "message": "Tool-call limit reached; no further actions were taken.",
        "results": results,
    }
