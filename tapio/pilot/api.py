"""Loopback-only pilot app; no imports of mutation or Gmail routers."""

import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tapio.confirmation.api import router as confirmation_router
from tapio.pilot.config import require_mode
from tapio.pilot.contracts import Ask, Feedback, PilotResponse
from tapio.pilot.diagnostics import exception_detail
from tapio.pilot.health import DATABASE_HELP, database_available
from tapio.pilot.service import Pilot
from tapio.suggestions.models import FeedbackInput

app = FastAPI(title="Tapio read-only pilot", docs_url=None, redoc_url=None)
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse({"detail": "Invalid pilot request fields."}, status_code=422)


@lru_cache
def get_pilot():
    return Pilot()


@app.middleware("http")
async def local_only(request: Request, call_next):
    if not request.client or request.client.host not in ("127.0.0.1", "::1", "testclient"):
        return JSONResponse({"detail": "Local pilot access only."}, status_code=403)
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        return JSONResponse({"detail": "Same-origin access required."}, status_code=403)
    try:
        require_mode()
    except ValueError:
        return JSONResponse({"detail": "Pilot mode is disabled."}, status_code=503)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "frame-ancestors 'none'; connect-src 'self'"
    )
    return response


@app.get("/pilot", response_class=HTMLResponse)
def page():
    return Path(__file__).with_name("page.html").read_text()


@app.post("/pilot/ask", response_model=PilotResponse)
async def ask(body: Ask):
    if not body.question.strip():
        raise HTTPException(422, "Please enter a question.")
    try:
        return await get_pilot().ask(body.question.strip(), route="POST /pilot/ask")
    except Exception as exc:
        # Storage/bootstrap failures cannot always be written to private history.
        # Emit only safe structured metadata, never str(exc), SQL or traceback text.
        logging.getLogger(__name__).error(
            "Pilot request unavailable: %s", exception_detail(exc, "PRIVATE_HISTORY", debug=True)
        )
        raise HTTPException(
            503,
            "Pilot configuration, source verification or private audit storage is unavailable. "
            "No unvalidated answer is returned.",
        ) from None


@app.post("/pilot/feedback/{session_id}")
def feedback(session_id: UUID, body: Feedback):
    try:
        get_pilot().history.feedback(str(session_id), body)
    except FileNotFoundError:
        raise HTTPException(404, "Unknown pilot session.") from None
    except Exception:
        raise HTTPException(503, "Private feedback storage unavailable.") from None
    return {"saved": True, "source_data_changed": False}


@app.get("/pilot/metrics")
def metrics():
    return get_pilot().history.metrics()


@app.get("/pilot/health")
def health():
    try:
        database_available()
    except Exception:
        return JSONResponse(
            {"status": "DATABASE_UNAVAILABLE", "detail": DATABASE_HELP}, status_code=503
        )
    return {"status": "READY", "detail": "Local database is available."}


# Fixed-batch evaluation only: no source mutation or knowledge-promotion router.
def get_suggestion_store():
    from tapio.pilot.config import load_config, readonly_engine, source_fingerprints
    from tapio.suggestions.store import Store

    store = Store(Path("data/interim/suggestion_pilot"))
    batch, _ = store.batch()
    config, _ = load_config()
    engine = readonly_engine()
    try:
        if source_fingerprints(engine, config) != batch["provenance"]["source_fingerprints"]:
            raise ValueError("SUGGESTION_SOURCE_SNAPSHOT_CHANGED")
    finally:
        engine.dispose()
    return store


@app.get("/pilot/suggestions", response_class=HTMLResponse)
def suggestion_page():
    return Path("tapio/suggestions/page.html").read_text()


@app.get("/pilot/suggestions/cards")
def suggestion_cards():
    try:
        return get_suggestion_store().public_batch()
    except Exception:
        raise HTTPException(503, "Verified suggestion batch unavailable.") from None


@app.get("/pilot/suggestions/metrics")
def suggestion_metrics():
    try:
        return get_suggestion_store().metrics()
    except Exception:
        raise HTTPException(503, "Suggestion metrics unavailable.") from None


@app.post("/pilot/suggestions/cards/{card_id}/feedback")
def suggestion_feedback(card_id: str, body: FeedbackInput):
    try:
        get_suggestion_store().feedback(card_id, body)
    except KeyError:
        raise HTTPException(404, "Unknown suggestion card.") from None
    except Exception:
        raise HTTPException(503, "Suggestion feedback store unavailable.") from None
    return {
        "saved": True,
        "source_data_changed": False,
        "labels_changed": False,
        "knowledge_authority_changed": False,
    }


# Narrow, separately gated human confirmation; no generic mutation router.

app.include_router(confirmation_router)
