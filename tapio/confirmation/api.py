"""Browser-only preview/commit routes; not exposed as agent tools."""

import hmac
import os
import secrets
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from tapio.confirmation.concept_review import ConceptSelection
from tapio.confirmation.mapping_review import MappingSelection
from tapio.confirmation.rule_review import RuleSelection
from tapio.confirmation.service import Commit, ConfirmationService, Selection

router = APIRouter(prefix="/pilot/confirmation")
SESSIONS = {}


@lru_cache
def service():
    from apps.api.app.core.database import SessionLocal

    if os.getenv("TAPIO_CONFIRMATION_BATCH") == "PERSISTENT_V1":
        return persistent_queue().service()
    return ConfirmationService.local(SessionLocal)


def browser(request):
    sid = request.cookies.get("tapio_confirmation_session", "")
    entry = SESSIONS.get(sid)
    if (
        not entry
        or entry["expires"] < time.time()
        or not hmac.compare_digest(entry["csrf"], request.headers.get("X-Tapio-CSRF", ""))
    ):
        raise HTTPException(403, "Valid local review session required.")
    if request.headers.get("origin") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Same-origin review request required.")
    return sid


@lru_cache
def persistent_queue():
    from apps.api.app.core.database import SessionLocal
    from tapio.confirmation.persistent import PersistentQueue

    return PersistentQueue(SessionLocal)


@router.get("", response_class=HTMLResponse)
def page():
    return Path("tapio/confirmation/page.html").read_text()


@router.get("/cards")
def cards(response: Response, request: Request):
    s = service()
    csrf = create_session(response, request)
    result = {
        "batch_id": s.batch.get("batch_id", "FIXED_FIVE"),
        "batch_version": s.batch.get("version", "CONFIRMATION_PREVIEW_V1"),
        "writes_enabled": s.enabled(),
        "csrf": csrf,
        "cards": [
            {
                k: c[k]
                for k in (
                    "card_id",
                    "transaction",
                    "source_messages",
                    "suggestion",
                    "current_state",
                    "warnings",
                    "reasons",
                )
            }
            for c in s.cards.values()
        ],
    }
    return populate_cards(s, result)


def create_session(response, request=None):
    response.headers["Cache-Control"] = "no-store"
    if request is not None:
        sid = request.cookies.get("tapio_confirmation_session", "")
        entry = SESSIONS.get(sid)
        if entry and entry["expires"] > time.time():
            return entry["csrf"]
    now = time.time()
    for key in list(SESSIONS):
        if SESSIONS[key]["expires"] < now:
            del SESSIONS[key]
    if len(SESSIONS) > 100:
        raise HTTPException(429, "Too many local review sessions.")
    sid = secrets.token_hex(32)
    csrf = secrets.token_hex(32)
    SESSIONS[sid] = {"csrf": csrf, "expires": now + 7200}
    response.set_cookie(
        "tapio_confirmation_session",
        sid,
        httponly=True,
        samesite="strict",
        max_age=7200,
        path="/pilot/confirmation",
    )
    return csrf


def populate_cards(s, result):
    for card in result["cards"]:
        card.update(s.card_status(card["card_id"]))
        original = s.cards[card["card_id"]]
        for key in (
            "evidence",
            "document_evidence",
            "paytrail_purpose",
            "pilot_tags",
            "receipt_evidence",
            "receipt_conflicts",
            "semantic_concepts",
            "user_rules",
            "user_rule_conflicts",
            "frozen_field_states",
            "uncertainty_history",
            "review_signals",
            "abstention_reasons",
            "concept_candidates",
            "blocked_generalizations",
        ):
            card[key] = original.get(key)
        if (
            result["batch_version"]
            in {"GENERAL_CONFIRMATION_V1", "BOUNDED_CONFIRMATION_V1", "PERSISTENT_CONFIRMATION_V1"}
            and card["write_state"] == "READY_TO_CONFIRM"
        ):
            card["write_state"] = "READY"
        card["frozen_field_states"] = original.get("field_states")
        card["authoritative"] = s.current_review(card["card_id"])
        card["field_states"] = {
            f: card["authoritative"][f]["field_status"] for f in ("category", "context")
        }
        card["transaction"] = {k: v for k, v in card["transaction"].items() if k != "id"}
    result["reviewed"] = sum(
        c["write_state"] in {"CONFIRMED", "CHANGED", "SKIPPED"} for c in result["cards"]
    )
    if s.batch.get("version") == "PERSISTENT_CONFIRMATION_V1":
        result["queue"] = persistent_queue().progress()
    return result


@router.post("/preview")
def preview(body: Selection, request: Request):
    sid = browser(request)
    try:
        if body.review_version is None:
            raise ValueError("UNCONFIRMED_UI_STATE_CHANGE")
        return service().preview(body, sid)
    except ValueError as e:
        if "STALE" in str(e) and getattr(service(), "monitor", None):
            service().monitor.record_stale()
        raise HTTPException(409, str(e)) from None


@router.post("/commit")
def commit(body: Commit, request: Request):
    sid = browser(request)
    try:
        s = service()
        result = s.commit(body, sid)
        card_id = s.verify(body.token, sid)["selection"]["card_id"]
        return {**result, "authoritative": s.current_review(card_id)}
    except ValueError as e:
        raise HTTPException(409, str(e)) from None


@router.get("/concepts", response_class=HTMLResponse)
def concept_page():
    return Path("tapio/confirmation/concepts.html").read_text()


@router.get("/concepts/cards")
def concept_cards(response: Response, request: Request):
    q = persistent_queue()
    return {
        "csrf": create_session(response, request),
        "candidates": q.concepts.candidates(),
        "decisions": q.concepts.decisions(),
        "records": q.concepts.records(),
        "writes_enabled": q.enabled(),
    }


class ConceptCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(max_length=64000)
    explicit_click: Literal["APPLY_CONCEPT_DECISION"]


class NextWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window_id: str
    explicit_click: Literal["OPEN_NEXT_BOUNDED_WINDOW"]
    refresh: bool = False


@router.post("/concepts/preview")
def concept_preview(body: ConceptSelection, request: Request):
    try:
        sid = browser(request)
        review = persistent_queue().concepts
        if body.expected_state is None:
            raise ValueError("EXPECTED_CONCEPT_STATE_REQUIRED")
        record = review.record(body.candidate_id)
        if body.expected_state != record["state_version"]:
            raise ValueError("STALE_CONCEPT_STATE")
        if record["decision"] != "PENDING" and not body.revise:
            raise ValueError("EXPLICIT_REVISION_REQUIRED")
        return review.preview(body, sid)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/concepts/commit")
def concept_commit(body: ConceptCommit, request: Request):
    from tapio.confirmation.persistent import LOCK

    sid = browser(request)
    with LOCK:
        q = persistent_queue()
        if not q.enabled():
            raise HTTPException(409, "CONCEPT_WRITES_DISABLED")
        try:
            return q.concepts.commit_result(body.token, sid)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(409, str(exc)) from None


@router.post("/queue/next")
def queue_next(body: NextWindow, request: Request):
    browser(request)
    try:
        result = persistent_queue().advance(body.window_id, refresh=body.refresh)
        service.cache_clear()
        return result
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/rules", response_class=HTMLResponse)
def rule_page():
    return Path("tapio/confirmation/rules.html").read_text()


@router.get("/rules/cards")
def rule_cards(response: Response, request: Request):
    q = persistent_queue()
    return {
        "csrf": create_session(response, request),
        "records": q.rules.records(),
        "writes_enabled": q.enabled(),
    }


@router.post("/rules/preview")
def rule_preview(body: RuleSelection, request: Request):
    try:
        return persistent_queue().rules.preview(body, browser(request))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


class RuleCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(max_length=64000)
    explicit_click: Literal["APPLY_USER_RULE_DECISION"]


@router.post("/rules/commit")
def rule_commit(body: RuleCommit, request: Request):
    from tapio.confirmation.persistent import LOCK

    sid = browser(request)
    with LOCK:
        q = persistent_queue()
        if not q.enabled():
            raise HTTPException(409, "RULE_WRITES_DISABLED")
        try:
            return q.rules.commit_result(body.token, sid)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(409, str(exc)) from None


@router.get("/mappings", response_class=HTMLResponse)
def mapping_page():
    return Path("tapio/confirmation/mappings.html").read_text()


@router.get("/mappings/cards")
def mapping_cards(response: Response, request: Request):
    q = persistent_queue()
    return {
        "csrf": create_session(response, request),
        "records": q.mappings.records(),
        "writes_enabled": q.enabled(),
    }


@router.post("/mappings/preview")
def mapping_preview(body: MappingSelection, request: Request):
    try:
        return persistent_queue().mappings.preview(body, browser(request))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


class MappingCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(max_length=64000)
    explicit_click: Literal["APPLY_MAPPING_DECISION"]


@router.post("/mappings/commit")
def mapping_commit(body: MappingCommit, request: Request):
    from tapio.confirmation.persistent import LOCK

    sid = browser(request)
    with LOCK:
        q = persistent_queue()
        if not q.enabled():
            raise HTTPException(409, "MAPPING_WRITES_DISABLED")
        try:
            return q.mappings.commit_result(body.token, sid)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(409, str(exc)) from None


@router.get("/current")
def current_reviews(response: Response):
    response.headers["Cache-Control"] = "no-store"
    s = service()
    return {
        "batch_id": s.batch.get("batch_id", "FIXED_FIVE"),
        "reviews": {cid: s.current_review(cid) for cid in s.cards},
    }


@lru_cache
def group_review():
    from tapio.confirmation.groups import GroupReview

    return GroupReview(persistent_queue())


@router.get("/groups", response_class=HTMLResponse)
def groups_page():
    return Path("tapio/confirmation/groups.html").read_text()


@router.get("/groups/cards")
def groups_cards(response: Response, request: Request, budget: int = 10):
    if not 1 <= budget <= 1000:
        raise HTTPException(422, "Review budget must be between 1 and 1000")
    try:
        plan = group_review().build(budget)
        return {**plan, "csrf": create_session(response, request)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


class GroupSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    group_id: str


class GroupCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    token: str = Field(max_length=2000000)
    explicit_click: Literal["APPLY_DISPLAYED_GROUP"]


class IndividualSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    selection: Selection


class IndividualCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    commit: Commit


@router.post("/groups/preview")
def group_preview(body: GroupSelection, request: Request):
    try:
        return group_review().preview(body.plan_id, body.group_id, browser(request))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/groups/commit")
def group_commit(body: GroupCommit, request: Request):
    try:
        return group_review().commit(body.plan_id, body.token, browser(request))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/groups/skip")
def group_skip(body: GroupSelection, request: Request):
    browser(request)
    try:
        return group_review().skip(body.plan_id, body.group_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/groups/individual/preview")
def group_individual_preview(body: IndividualSelection, request: Request):
    try:
        sid = browser(request)
        if body.selection.review_version is None:
            raise ValueError("UNCONFIRMED_UI_STATE_CHANGE")
        _, s = group_review().get(body.plan_id)
        return s.preview(body.selection, sid)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/groups/individual/commit")
def group_individual_commit(body: IndividualCommit, request: Request):
    try:
        sid = browser(request)
        review = group_review()
        result = review.individual_commit(body.plan_id, body.commit, sid)
        _, s = review.get(body.plan_id)
        cid = s.verify(body.commit.token, sid)["selection"]["card_id"]
        return {**result, "authoritative": s.current_review(cid)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/groups/current")
def group_current(plan_id: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        _, s = group_review().get(plan_id)
        return {cid: s.current_review(cid) for cid in s.cards} if s else {}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
