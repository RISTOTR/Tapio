"""Private operational diagnostics: no exception messages, SQL, prompts or credentials."""

import os
import re
import traceback
from pathlib import Path

from sqlalchemy.exc import OperationalError


def exception_detail(exc, stage, *, debug=False):
    message = str(exc)
    code = message if re.fullmatch(r"[A-Z][A-Z0-9_]{0,80}", message) else type(exc).__name__
    category = "AGENT_EXECUTION_ERROR"
    if isinstance(exc, OperationalError):
        code = "DATABASE_OPERATIONAL_ERROR"
        original = str(exc.orig).lower()
        if "connection refused" in original:
            code = "DATABASE_CONNECTION_REFUSED"
        elif "operation not permitted" in original or "permission denied" in original:
            code = "DATABASE_ACCESS_DENIED"
        elif "password authentication failed" in original:
            code = "DATABASE_AUTHENTICATION_FAILED"
        sqlstate = getattr(exc.orig, "sqlstate", "") or ""
        connection_failure = code != "DATABASE_OPERATIONAL_ERROR" or sqlstate.startswith(
            ("08", "28")
        )
        category = "INFRASTRUCTURE_UNAVAILABLE" if connection_failure else "AGENT_EXECUTION_ERROR"
    elif code in {"EXPLICIT_SINGLE_PERIOD_REQUIRED", "UNSUPPORTED_QUESTION"}:
        category = (
            "QUESTION_TOO_BROAD"
            if code == "EXPLICIT_SINGLE_PERIOD_REQUIRED"
            else "UNSUPPORTED_SCOPE"
        )
    elif code.startswith(("SOURCE_", "PILOT_REFERENCE", "PILOT_RENDER", "PILOT_TAX", "PILOT_NON_")):
        category = "SAFETY_REJECTION"
    elif stage == "CONFIGURATION" or code in {
        "PILOT_REGISTRY_CHANGED",
        "PILOT_MODEL_SETTINGS_CHANGED",
    }:
        category = "CONFIGURATION_ERROR"
    elif code.startswith(("LIVE_", "PILOT_MODEL_UNAVAILABLE", "INVALID_PRIVATE_KEY")):
        category = "INFRASTRUCTURE_UNAVAILABLE"
    elif code in {
        "PILOT_EVIDENCE_INCOMPLETE",
        "MANDATORY_EVIDENCE_FAILED",
        "TRANSACTION_SEARCH_LIMIT",
    }:
        category = "EVIDENCE_INCOMPLETE"
    elif code == "QUESTION_TOO_BROAD":
        category = "QUESTION_TOO_BROAD"
    elif stage in {"MODEL_PLANNER", "COORDINATOR_INITIALIZATION"} and isinstance(
        exc, (ValueError, TypeError)
    ):
        category = "PLAN_INVALID"
    elif code in {"INVALID_FINAL_CONTENT", "PILOT_PROVIDER_PROTOCOL_FAILURE"} or stage in {
        "FINAL_VALIDATION",
        "PRESENTATION",
    }:
        category = "VALIDATION_ERROR"
    elif isinstance(exc, TimeoutError):
        category = (
            "INFRASTRUCTURE_UNAVAILABLE"
            if stage in {"MODEL_PLANNER", "MODEL_FINAL"}
            else "AGENT_EXECUTION_ERROR"
        )
    result = {
        "category": category,
        "code": code,
        "stage": stage,
        "exception_type": type(exc).__name__,
    }
    if isinstance(exc, OperationalError):
        result["sqlstate"] = getattr(exc.orig, "sqlstate", None)
    if debug:
        result["frames"] = [
            {"file": Path(f.filename).name, "function": f.name, "line": f.lineno}
            for f in traceback.extract_tb(exc.__traceback__)
        ]
    return result


class Diagnostics:
    def __init__(self, request_id, route):
        self.debug = os.getenv("TAPIO_PILOT_DIAGNOSTICS", "").lower() == "true"
        self.data = {
            "request_id": request_id,
            "pilot_mode": os.getenv("TAPIO_PILOT_MODE", "").lower() == "true",
            "diagnostic_mode": self.debug,
            "route_reached": route,
            "accepted_config_id": None,
            "database_available": None,
            "provider_available": None,
            "plan_validation": "NOT_ATTEMPTED",
            "retrieval_attempted": False,
            "completeness_result": "NOT_ATTEMPTED",
            "planner_called": False,
            "coordinator_called": False,
            "model_calls": 0,
            "evidence_views_requested": [],
            "evidence_views_returned": [],
            "failure": None,
            "stages": [],
        }
        self.stage = "REQUEST"

    def enter(self, stage):
        self.stage = stage
        self.data["stages"].append(stage)

    def failed(self, exc):
        if self.data["failure"] is None:
            self.data["failure"] = exception_detail(exc, self.stage, debug=self.debug)


class ObservedModel:
    """Transparent observer; forwards identical arguments and returned provider objects."""

    def __init__(self, model, diagnostics):
        self.model = model
        self.diagnostics = diagnostics

    def __getattr__(self, name):
        return getattr(self.model, name)

    async def generate_coordinated(self, *args, **kwargs):
        self.diagnostics.enter("MODEL_PLANNER" if kwargs["planning"] else "MODEL_FINAL")
        if kwargs["planning"]:
            self.diagnostics.data["planner_called"] = True
        try:
            turn = await self.model.generate_coordinated(*args, **kwargs)
            self.diagnostics.data["provider_available"] = True
            return turn
        except Exception as exc:
            # The accepted engine deliberately converts some exceptions to status DTOs.
            # Preserve their reason here before that conversion, without changing behavior.
            self.diagnostics.failed(exc)
            if self.diagnostics.data["failure"]["category"] == "INFRASTRUCTURE_UNAVAILABLE":
                self.diagnostics.data["provider_available"] = False
            raise
