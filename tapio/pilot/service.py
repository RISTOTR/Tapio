"""Private, bounded pilot orchestration around the unchanged accepted engine."""

import asyncio
import calendar
import re
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from types import FunctionType
from uuid import uuid4

from apps.api.app.services.tool_queries import Queries
from scripts.evaluate_phase09d import PREFIX, schema_hash
from tapio.agent.exclusive import ScopedCoordinator, run_scoped_agent
from tapio.agent.mandatory import EvidenceView, coordinated_registry, required_views
from tapio.agent.providers.openai import read_key
from tapio.agent.providers.openai_exclusive import OpenAIExclusiveModel
from tapio.agent.render_bounded import render_answer
from tapio.pilot.config import (
    HISTORY,
    MODEL,
    SETTINGS,
    load_config,
    readonly_engine,
    readonly_session,
    source_fingerprints,
)
from tapio.pilot.contracts import Session
from tapio.pilot.diagnostics import Diagnostics, ObservedModel
from tapio.pilot.failures import (
    classify_failure,
    coverage_summary,
    has_partial_evidence,
    unconstrained_overview,
)
from tapio.pilot.history import History
from tapio.pilot.named_subject import retrieve_subject
from tapio.pilot.presentation import TITLES, present, provenance, unsupported
from tapio.pilot.search_planner import plan_search
from tapio.pilot.transaction_search import (
    requested_dates,
    retrieve_search,
    search_intent,
    search_response,
    validate_search_plan,
)


def period_for(question):
    """Small explicit calendar-period wrapper, never a model-generated filter."""
    years = set(re.findall(r"\b(20\d{2})\b", question))
    if len(years) > 1 or re.search(
        r"\b(last year|last month|quarter|yesterday|since|between)\b", question, re.I
    ):
        raise ValueError("EXPLICIT_SINGLE_PERIOD_REQUIRED")
    year = int(next(iter(years))) if years else date.today().year
    months = [
        i for i in range(1, 13) if re.search(r"\b" + calendar.month_name[i] + r"\b", question, re.I)
    ]
    if len(months) > 1:
        raise ValueError("EXPLICIT_SINGLE_PERIOD_REQUIRED")
    month = months[0] if months else None
    return {
        "date_from": f"{year}-{month:02d}-01" if month else f"{year}-01-01",
        "date_to": f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}"
        if month
        else f"{year}-12-31",
    }


class AcceptedModel(OpenAIExclusiveModel):
    def _post(self, payload):
        if payload["model"] != MODEL or any(
            payload[k] != SETTINGS[k]
            for k in ("max_completion_tokens", "reasoning_effort", "parallel_tool_calls", "store")
        ):
            raise ValueError("PILOT_MODEL_SETTINGS_CHANGED")
        self.request_count = getattr(self, "request_count", 0) + 1
        result = super()._post(payload)
        if result.get("model") != MODEL:
            raise ValueError("PILOT_MODEL_UNAVAILABLE")
        return result


def isolated_engine(observed, diagnostics=None):
    """Reuse the exact accepted function code with a per-call audit destination.

    A private globals mapping avoids process-global monkeypatching and leaves all
    policy, prompt, retrieval, finalization and round-budget code unchanged.
    """

    class PilotCoordinator(ScopedCoordinator):
        def __init__(self, *args, **kwargs):
            # The accepted default writes the full ledger to a historical directory.
            # Keep it in memory; the pilot persists only necessary provenance below.
            kwargs["audit_path"] = None
            if diagnostics:
                diagnostics.enter("COORDINATOR_INITIALIZATION")
                diagnostics.data["coordinator_called"] = True
            try:
                super().__init__(*args, **kwargs)
            except Exception as exc:
                if diagnostics:
                    diagnostics.failed(exc)
                raise
            if diagnostics:
                diagnostics.data["plan_validation"] = "VALID"
            observed.append(self)

        async def execute(self):
            if diagnostics:
                diagnostics.enter("EVIDENCE_RETRIEVAL")
                diagnostics.data["retrieval_attempted"] = True
            try:
                return await super().execute()
            except Exception as exc:
                if diagnostics:
                    diagnostics.failed(exc)
                raise

    runner = FunctionType(
        run_scoped_agent.__code__,
        {**run_scoped_agent.__globals__, "ScopedCoordinator": PilotCoordinator},
        run_scoped_agent.__name__,
        run_scoped_agent.__defaults__,
        run_scoped_agent.__closure__,
    )
    runner.__kwdefaults__ = dict(run_scoped_agent.__kwdefaults__)
    return runner


def validate_answer(response, coordinator, model):
    if response["status"] != "COMPLETE" or coordinator is None:
        raise ValueError("PILOT_EVIDENCE_INCOMPLETE")
    if (
        coordinator.state()["status"] != "MANDATORY_EVIDENCE_COMPLETE"
        or coordinator.final_validation["validation"] != "COMPLETE"
    ):
        raise ValueError("PILOT_EVIDENCE_INCOMPLETE")
    requested = coordinator.final_validation["requested_final"]["references"]
    names = [item["evidence_handle"] for item in requested]
    if len(names) != len(set(names)) or not coordinator.ledger.required_final_handles <= set(names):
        raise ValueError("PILOT_REFERENCE_FAILURE")
    if any(name not in coordinator.ledger.handles for name in names):
        raise ValueError("PILOT_REFERENCE_FAILURE")
    selected = [
        coordinator.ledger.results[coordinator.ledger.handles[name]["call_index"]] for name in names
    ]
    if selected != response["results"] or not all(r["ok"] for r in selected):
        raise ValueError("PILOT_REFERENCE_FAILURE")
    if (
        response["answer"] != render_answer(selected, response["message"])
        or len(response["answer"].split()) > 850
    ):
        raise ValueError("PILOT_RENDER_FAILURE")
    if EvidenceView.TAX_BOUNDARY_CONTEXT in required_views(coordinator.plan) and not response[
        "message"
    ].startswith("Tax treatment"):
        raise ValueError("PILOT_TAX_BOUNDARY_FAILURE")
    if "no tax-deductibility decision" not in response["answer"]:
        raise ValueError("PILOT_TAX_BOUNDARY_FAILURE")
    if any(e["validation"] == "INVALID_PROVIDER_RESPONSE" for e in model.protocol_events):
        raise ValueError("PILOT_PROVIDER_PROTOCOL_FAILURE")


class Pilot:
    def __init__(
        self,
        *,
        history=None,
        model_factory=None,
        config_loader=load_config,
        engine=None,
        fingerprint_check=source_fingerprints,
        registry_factory=None,
        subject_loader=retrieve_subject,
        search_planner=plan_search,
        search_loader=retrieve_search,
    ):
        self.history = history or History(HISTORY)
        self.model_factory = model_factory or (
            lambda path: AcceptedModel(read_key(), model=MODEL, protocol_dir=path)
        )
        self.config_loader = config_loader
        self.engine = engine
        self.fingerprint_check = fingerprint_check
        self.registry_factory = registry_factory
        self.subject_loader = subject_loader
        self.search_planner = search_planner
        self.search_loader = search_loader
        self.lock = asyncio.Lock()

    async def ask(self, question, *, route="SERVICE"):
        async with self.lock:
            return await self._ask(question, route)

    async def _ask(self, question, route):
        started = time.monotonic()
        session_id, timestamp = str(uuid4()), datetime.now(UTC).isoformat()
        diagnostics = Diagnostics(session_id, route)
        directory = self.history.directory(session_id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        config = {}
        observed, failure, model, before = [], None, None, None
        response = {"status": "UNSUPPORTED", "results": [], "answer": ""}
        public = None
        named_subject = None
        search_evidence = None
        try:
            diagnostics.enter("CONFIGURATION")
            config, snapshot = self.config_loader()
            diagnostics.data["accepted_config_id"] = config["identifier"]
            if self.engine is None:
                self.engine = readonly_engine()
            diagnostics.enter("SOURCE_PREFLIGHT")
            before = await asyncio.to_thread(self.fingerprint_check, self.engine, config)
            diagnostics.data["database_available"] = True
            if search_intent(question):
                diagnostics.enter("QUESTION_PERIOD")
                dates = requested_dates(question)
                diagnostics.data["period"] = dates.model_dump(mode="json") if dates else None
                diagnostics.enter("MODEL_INITIALIZATION")
                model = ObservedModel(
                    self.model_factory(directory / "provider_protocol"), diagnostics
                )
                diagnostics.enter("MODEL_PLANNER")
                diagnostics.data["planner_called"] = True
                async with asyncio.timeout(45):
                    search_plan = validate_search_plan(
                        question, await self.search_planner(model, question)
                    )
                diagnostics.data["provider_available"] = True
                diagnostics.data["plan_validation"] = "VALID"
                diagnostics.data["transaction_search"] = search_plan.model_dump(mode="json")
                diagnostics.enter("EVIDENCE_RETRIEVAL")
                diagnostics.data["retrieval_attempted"] = True
                search_evidence = await asyncio.to_thread(
                    self.search_loader, search_plan, lambda: readonly_session(self.engine)
                )
                diagnostics.data["completeness_result"] = "SEARCH_COMPLETE"
                diagnostics.data["evidence_views_requested"] = ["TRANSACTION_SEARCH"]
                diagnostics.data["evidence_views_returned"] = ["TRANSACTION_SEARCH"]
                response = {"status": "COMPLETE", "results": [], "answer": "", "model_rounds": 1}
            else:
                diagnostics.enter("QUESTION_PERIOD")
                period = period_for(question)
                diagnostics.data["period"] = period
                if unconstrained_overview(question):
                    raise ValueError("QUESTION_TOO_BROAD")
                diagnostics.enter("READ_ONLY_REGISTRY")
                registry = (
                    self.registry_factory(directory)
                    if self.registry_factory
                    else coordinated_registry(
                        coverage=snapshot["bank_coverage"],
                        queries=Queries(session_factory=lambda: readonly_session(self.engine)),
                        audit_path=directory / "tool_audit.jsonl",
                    )
                )
                if set(registry.tools) - set(TITLES) or any(
                    t.classification != "READ_ONLY" for t in registry.tools.values()
                ):
                    raise ValueError("PILOT_NON_READONLY_CAPABILITY")
                if schema_hash(registry.specifications()) != config["tool_registry_hash"]:
                    raise ValueError("PILOT_REGISTRY_CHANGED")
                diagnostics.enter("MODEL_INITIALIZATION")
                model = ObservedModel(
                    self.model_factory(directory / "provider_protocol"), diagnostics
                )
                diagnostics.enter("ACCEPTED_AGENT")
                response = await isolated_engine(observed, diagnostics)(
                    PREFIX + question, model, registry, period=period, max_rounds=6
                )
                diagnostics.data["agent_status"] = response["status"]
                diagnostics.enter("FINAL_VALIDATION")
                if response["status"] == "INVALID_FINAL_CONTENT":
                    raise ValueError("INVALID_FINAL_CONTENT")
                validate_answer(response, observed[0] if observed else None, model)
                diagnostics.enter("NAMED_SUBJECT_RETRIEVAL")
                named_subject = await asyncio.to_thread(
                    self.subject_loader, question, lambda: readonly_session(self.engine)
                )
            diagnostics.enter("SOURCE_POSTFLIGHT")
            after = await asyncio.to_thread(self.fingerprint_check, self.engine, config)
            if before != after:
                raise ValueError("SOURCE_CHANGED_DURING_QUESTION")
        except Exception as exc:
            diagnostics.failed(exc)
            failure = diagnostics.data["failure"]["code"]
        usage = getattr(model, "usage", [])
        input_tokens = sum(u["usage"].get("prompt_tokens", 0) for u in usage)
        cached = sum(
            u["usage"].get("prompt_tokens_details", {}).get("cached_tokens", 0) for u in usage
        )
        output = sum(u["usage"].get("completion_tokens", 0) for u in usage)
        cost = (
            Decimal(input_tokens - cached) * Decimal(".75")
            + Decimal(cached) * Decimal(".075")
            + Decimal(output) * Decimal("4.50")
        ) / 1_000_000
        session = Session(
            id=session_id,
            timestamp=timestamp,
            model_calls=getattr(model, "request_count", len(usage)),
            usage_complete=getattr(model, "request_count", len(usage)) == len(usage),
            rounds=response.get("model_rounds", 0),
            input_tokens=input_tokens,
            cached_input_tokens=cached,
            output_tokens=output,
            latency_seconds=round(time.monotonic() - started, 6),
            estimated_cost_usd=str(cost),
        )
        if failure is None:
            try:
                diagnostics.enter("PRESENTATION")
                if search_evidence is not None:
                    public = search_response(search_evidence, session)
                else:
                    public = present(
                        response,
                        session,
                        config["human_review_counts"],
                        question=question,
                        named_subject=named_subject,
                    )
            except (ValueError, KeyError, TypeError) as exc:
                diagnostics.failed(exc)
                failure = "PRESENTATION_VALIDATION_FAILED"
        coordinator = observed[0] if observed else None
        if coordinator:
            diagnostics.data["completeness_result"] = coordinator.state()["status"]
            diagnostics.data["retrieval_calls"] = [
                {
                    "tool": t["tool"],
                    "ok": t["result"].get("ok", False),
                    "truncated": t["result"].get("data", {}).get("truncated", False),
                }
                for t in coordinator.trace
            ]
        if failure:
            detail = diagnostics.data["failure"]
            if detail["category"] == "INFRASTRUCTURE_UNAVAILABLE" and detail["code"].startswith(
                "DATABASE_"
            ):
                diagnostics.data["database_available"] = False
            detail["category"] = classify_failure(detail, diagnostics.data, coordinator, response)
            if detail["category"] == "PLAN_INVALID":
                diagnostics.data["plan_validation"] = "INVALID"
            public = unsupported(
                session,
                diagnostics.data["failure"]["category"],
                failure_code=diagnostics.data["failure"]["code"],
                question=question,
                plan=coordinator.plan.model_dump(mode="json") if coordinator else None,
                coverage_note=coverage_summary(coordinator),
                partial_found=has_partial_evidence(coordinator),
            )
        coordinator = observed[0] if observed else None
        diagnostics.data["model_calls"] = session.model_calls
        if coordinator:
            diagnostics.data["evidence_views_requested"] = [
                r.view.value for r in coordinator.requirements
            ]
            diagnostics.data["evidence_views_returned"] = sorted(
                {view for meta in coordinator.ledger.handles.values() for view in meta["views"]}
            )
            diagnostics.data["evidence_errors"] = [
                {"code": e.get("code"), "tool": e.get("tool")} for e in coordinator.errors
            ]
        diagnostics.data["presentation_mode"] = public.presentation_mode
        diagnostics.data["presentation_failure_category"] = public.failure_category
        from tapio.pilot.subject_identity import extract_subject

        diagnostics.data["extracted_subject"] = extract_subject(question)
        diagnostics.data["resolved_subject"] = (
            named_subject.get("canonical_subject") if named_subject else None
        )
        diagnostics.enter("PRIVATE_HISTORY")
        record = {
            "timestamp": timestamp,
            "question": question,
            "response": public.model_dump(mode="json"),
            "failure": failure,
            "source_fingerprints_verified": failure is None,
            "configuration_id": config.get("identifier"),
            "diagnostics": diagnostics.data,
            "model": MODEL,
            "provenance": coordinator.provenance() if coordinator else None,
            "named_subject": named_subject,
            "transaction_search": search_evidence,
            "final_references": coordinator.final_validation.get("requested_final")
            if coordinator and hasattr(coordinator, "final_validation")
            else None,
            "evidence_sources": {
                h: {
                    "views": meta["views"],
                    "sources": provenance(coordinator.ledger.results[meta["call_index"]]["data"]),
                }
                for h, meta in coordinator.ledger.handles.items()
            }
            if coordinator
            else {},
        }
        self.history.save(session_id, record)
        return public
