"""Browser-only preview/commit routes; not exposed as agent tools."""

import hmac
import secrets
import time
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from tapio.confirmation.service import Commit, ConfirmationService, Selection

router = APIRouter(prefix="/pilot/confirmation")
SESSIONS = {}


@lru_cache
def service():
    from apps.api.app.core.database import SessionLocal

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


@router.get("", response_class=HTMLResponse)
def page():
    return Path("tapio/confirmation/page.html").read_text()


@router.get("/cards")
def cards(response: Response):
    s = service()
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
    result = {
        "batch_id": s.batch.get("batch_id", "FIXED_FIVE"),
        "batch_version": s.batch.get("version", "CONFIRMATION_PREVIEW_V1"),
        "writes_enabled": s.enabled(),
        "csrf": csrf,
        "cards": [
            {
                k: c[k]
                for k in [
                    "card_id",
                    "transaction",
                    "source_messages",
                    "suggestion",
                    "current_state",
                    "warnings",
                    "reasons",
                ]
            }
            for c in s.cards.values()
        ],
    }

    for card in result["cards"]:
        card.update(s.card_status(card["card_id"]))
        original = s.cards[card["card_id"]]
        for key in ("evidence", "document_evidence", "paytrail_purpose", "pilot_tags"):
            card[key] = original.get(key)
        if (
            result["batch_version"] == "GENERAL_CONFIRMATION_V1"
            and card["write_state"] == "READY_TO_CONFIRM"
        ):
            card["write_state"] = "READY"
        card["transaction"] = {k: v for k, v in card["transaction"].items() if k != "id"}
    result["reviewed"] = sum(
        c["write_state"] in {"CONFIRMED", "CHANGED", "SKIPPED"} for c in result["cards"]
    )
    return result


@router.post("/preview")
def preview(body: Selection, request: Request):
    sid = browser(request)
    try:
        return service().preview(body, sid)
    except ValueError as e:
        if "STALE" in str(e) and getattr(service(), "monitor", None):
            service().monitor.record_stale()
        raise HTTPException(409, str(e)) from None


@router.post("/commit")
def commit(body: Commit, request: Request):
    sid = browser(request)
    try:
        return service().commit(body, sid)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
