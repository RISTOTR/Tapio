"""Same-origin, CSRF-protected explicit browser import boundary."""

from functools import lru_cache
from typing import Literal
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from tapio.confirmation.api import browser, create_session, persistent_queue
from tapio.importing.service import MAX_BYTES, ImportWorkflow

router = APIRouter(prefix="/app/import")


@lru_cache
def workflow():
    return ImportWorkflow(persistent_queue())


def failure(exc):
    messages = {
        "IMPORT_PREVIEW_STALE": (
            "Records changed after this preview. Inspect the file again before importing."
        ),
        "IMPORT_PREVIEW_EXPIRED": "This preview expired. Inspect the file again.",
        "IMPORT_WRITES_DISABLED": (
            "Imports are disabled until the local integrity checks are verified."
        ),
        "IMPORT_RECOVERY_REQUIRED": (
            "Finish the pending import analysis before starting another import."
        ),
        "SELECT_EXISTING_ACCOUNT": "Choose the existing account used for this bank export.",
    }
    return HTTPException(
        409,
        messages.get(
            str(exc),
            (
                "Import could not finish safely. If transactions were saved, "
                "resume analysis below; do not import them under another account."
            ),
        ),
    )


@router.get("/status")
def status(response: Response, request: Request):
    w = workflow()
    try:
        return {
            "csrf": create_session(response, request, path="/app/import"),
            "accounts": w.accounts(),
            "writes_enabled": w.queue.enabled(),
            **w.history(),
        }
    except (ValueError, OSError, KeyError):
        raise HTTPException(503, "Import history or integrity state is unavailable.") from None


@router.post("/preview")
async def preview(request: Request, account: str = "", source: Literal["bank", "sampo"] = "bank"):
    sid = browser(request)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "Choose a CSV no larger than 10 MB.")
    filename = unquote(request.headers.get("X-Filename", ""))
    try:
        from data_pipeline.ingest.bank_csv import SOURCE_TYPE
        from data_pipeline.normalize.sampo import SOURCE_TYPE as SAMPO_TYPE

        return await run_in_threadpool(
            workflow().preview,
            bytes(raw),
            filename,
            account,
            sid,
            SAMPO_TYPE if source == "sampo" else SOURCE_TYPE,
        )
    except (ValueError, OSError, KeyError) as exc:
        raise failure(exc) from None


class ApplyImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation: Literal["IMPORT_AND_ANALYZE"]


@router.post("/commit")
def commit(body: ApplyImport, request: Request):
    sid = browser(request)
    try:
        return workflow().commit(body.token, sid)
    except (ValueError, OSError, KeyError) as exc:
        raise failure(exc) from None
