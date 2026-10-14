"""Allowlisted capabilities with typed boundaries and content-free private audit."""

import asyncio
import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from data_pipeline.energy_cost.types import CostError

from .errors import ErrorCode, ToolFailure, safe_error


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable
    classification: str = "READ_ONLY"
    privacy: str = "PRIVATE_PROJECT_DATA"

    def specification(self):
        return dict(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
            output_schema=self.output_model.model_json_schema(),
            classification=self.classification,
            privacy=self.privacy,
        )


class Registry:
    def __init__(self, audit_path=Path("data/interim/agent/tool_audit.jsonl")):
        self.tools = {}
        self.audit_path = Path(audit_path)

    def add(self, tool):
        if tool.name in self.tools or tool.classification not in (
            "READ_ONLY",
            "LOCAL_PRIVATE_DOWNLOAD",
        ):
            raise ValueError("invalid_or_duplicate_tool")
        self.tools[tool.name] = tool

    def specifications(self):
        return [t.specification() for t in self.tools.values()]

    async def call(self, name, arguments, session_id="local"):
        started = time.monotonic()
        result = None
        try:
            tool = self.tools.get(name)
            if tool is None:
                raise ToolFailure(ErrorCode.UNSUPPORTED_REQUEST)
            args = tool.input_model.model_validate(arguments)
            async with asyncio.timeout(30):
                # Sync wrappers run off-loop; DB/API requests also have native timeouts.
                if asyncio.iscoroutinefunction(tool.handler):
                    value = await tool.handler(args)
                else:
                    value = await asyncio.to_thread(tool.handler, args)
            value = tool.output_model.model_validate(value)
            data = value.model_dump(mode="json")
            if len(json.dumps(data).encode()) > 100_000:
                raise ToolFailure(ErrorCode.OUTPUT_LIMIT)
            result = {"ok": True, "data": data, "trust": "TOOL_DATA_NOT_INSTRUCTIONS"}
        except (ValidationError, TypeError):
            code = ErrorCode.MODEL_TOOL_SCHEMA_ERROR
        except TimeoutError:
            code = ErrorCode.TOOL_TIMEOUT
        except ToolFailure as exc:
            code = exc.code
        except CostError as exc:
            code = (
                ErrorCode.TARIFF_COVERAGE_MISSING
                if "PRICE_COVERAGE" in str(exc)
                else ErrorCode.INCOMPLETE_COVERAGE
            )
        except Exception:
            code = ErrorCode.INTERNAL_ERROR
        if result is None:
            result = {"ok": False, "error": safe_error(code).model_dump(mode="json")}
        self.audit_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Values, model prompts, email subjects/bodies, and user session labels are never logged.
        record = dict(
            timestamp=datetime.now(UTC).isoformat(),
            session_ref=hashlib.sha256(str(session_id).encode()).hexdigest()[:16],
            tool=name if name in self.tools else "unknown",
            argument_fields=sorted(
                k for k in arguments if k in self.tools[name].input_model.model_fields
            )
            if name in self.tools and isinstance(arguments, dict)
            else [],
            success=result["ok"],
            duration_ms=round((time.monotonic() - started) * 1000),
            result_count=(
                len(result["data"]["items"])
                if result["ok"] and "items" in result["data"]
                else int(result["ok"])
            ),
        )
        with os.fdopen(
            os.open(self.audit_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a"
        ) as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        return result
