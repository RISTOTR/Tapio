"""Explicit Ask corrections; one transaction, signed preview, existing append-only writer."""

import re
import secrets
import time
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from apps.api.app.domain.models import Transaction
from data_pipeline.labels.contracts import CATEGORIES, CONTEXTS
from tapio.confirmation.api import browser, create_session, persistent_queue
from tapio.confirmation.groups import GroupReview
from tapio.confirmation.persistent import LOCK
from tapio.confirmation.service import (
    Commit,
    ConfirmationService,
    Selection,
    review_state,
    row_data,
)
from tapio.knowledge.fields import source_text_fields
from tapio.knowledge.models import digest
from tapio.pilot.planned_retrieval import aliases
from tapio.pilot.query_plan import explicit_periods
from tapio.pilot.transaction_search import matching_terms

HELP = (
    "Use: Change Example Shop transaction 22/05/2026 to category OTHER "
    "and business context FORESTRY. Specify one date and at least one field."
)
router = APIRouter(prefix="/pilot/corrections")


def parse_correction(question):
    if not re.match(r"^\s*(change|correct|update|set)\b", question, re.I):
        return None
    match = re.search(r"\b(category|business\s+context|context)\b", question, re.I)
    if not match:
        raise ValueError(HELP)
    target, changes = question[: match.start()], question[match.start() :]
    fields = {}
    pattern = r"(category|business\s+context|context)\s*(?:to\s+|[:=]\s*)?([A-Za-z_]+)"
    for m in re.finditer(pattern, changes, re.I):
        field = "category" if m[1].lower() == "category" else "context"
        value = m[2].upper()
        if field in fields or value not in (CATEGORIES if field == "category" else CONTEXTS):
            raise ValueError("Use one valid category/context value per field. " + HELP)
        fields[field] = value
    remaining = re.sub(pattern, "", changes, flags=re.I)
    if not fields or re.sub(r"\b(and|to|be)\b|[\s,.;]", "", remaining, flags=re.I):
        raise ValueError(HELP)
    from datetime import date

    periods = explicit_periods(target, date.today())
    if len(periods) != 1 or periods[0].date_from != periods[0].date_to:
        raise ValueError(HELP)
    target = re.sub(r"^\s*(change|correct|update|set)\s+", "", target, flags=re.I)
    target = re.sub(r"\b(?:\d{1,2}[/.]\d{1,2}[/.]20\d{2}|20\d{2}-\d{2}-\d{2})\b", "", target)
    target = re.sub(
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[A-Za-z]+\s+20\d{2}\b", "", target, flags=re.I
    )
    merchant = re.sub(r"\b(transaction|on|dated|to|be)\b", "", target, flags=re.I).strip(" .,;:")
    if len(merchant) < 2:
        raise ValueError(HELP)
    return {"merchant": merchant, "date": periods[0].date_from, "fields": fields}


class Corrections:
    def __init__(self, queue):
        self.queue = queue
        self.pending = {}

    def resolve(self, question, sid):
        parsed = parse_correction(question)
        if parsed is None:
            return {"handled": False}
        with LOCK:
            now = time.time()
            self.pending = {k: v for k, v in self.pending.items() if v["expires"] > now}
            if len(self.pending) >= 32:
                raise ValueError("Too many pending corrections. Wait for previews to expire.")
            with self.queue.factory() as db:
                transactions = db.scalars(
                    select(Transaction)
                    .where(Transaction.booking_date == parsed["date"])
                    .order_by(Transaction.id)
                    .limit(501)
                ).all()
                if len(transactions) > 500:
                    raise ValueError(
                        "Too many transactions on that date; use Review to narrow the selection."
                    )
                matches = [
                    tx
                    for tx in transactions
                    if matching_terms(source_text_fields(tx), aliases(parsed["merchant"]))
                ]
                candidates = []
                for tx in matches:
                    state, version, _ = review_state(db, tx)
                    candidates.append(
                        {
                            "id": str(tx.id),
                            "date": str(tx.booking_date),
                            "merchant": tx.ultimate_recipient or tx.raw_counterparty,
                            "amount": str(tx.amount),
                            "currency": tx.currency,
                            "source_file": tx.source_file,
                            "source_id": tx.source_transaction_id,
                            "current": state,
                            "review_version": version,
                        }
                    )
            ticket = secrets.token_hex(32)
            self.pending[ticket] = {
                "sid": sid,
                "expires": now + 900,
                "parsed": parsed,
                "candidates": candidates,
                "services": {},
                "question": question,
            }
            return {
                "handled": True,
                "ticket": ticket,
                "candidates": candidates,
                "fields": parsed["fields"],
                "writes_enabled": self.queue.enabled(),
            }

    def entry(self, ticket, sid):
        item = self.pending.get(ticket)
        if not item or item["sid"] != sid or item["expires"] < time.time():
            raise ValueError("Correction expired. Submit your correction again.")
        return item

    def preview(self, ticket, transaction_id, sid):
        with LOCK:
            item = self.entry(ticket, sid)
            selected = next((c for c in item["candidates"] if c["id"] == transaction_id), None)
            if selected is None:
                raise ValueError("Choose a transaction from this correction request.")
            GroupReview(self.queue).verify_sources()
            with self.queue.factory() as db:
                from uuid import UUID

                tx = db.get(Transaction, UUID(transaction_id))
                state, version, _ = review_state(db, tx)
                if version != selected["review_version"]:
                    raise ValueError("Classification changed. Submit your correction again.")
                card = {
                    "card_id": transaction_id,
                    "transaction": {
                        "id": transaction_id,
                        "date": str(tx.booking_date),
                        "merchant": tx.ultimate_recipient or tx.raw_counterparty,
                        "amount": str(tx.amount),
                        "currency": tx.currency,
                        "source_file": tx.source_file,
                    },
                    "source_stable_id": tx.source_transaction_id,
                    "source_hash": digest(row_data(tx)),
                    "initial_state_hash": version,
                    "current_state": state,
                    "suggestion": {"category": None, "context": None},
                    "source_messages": {"message": tx.message, "reference": tx.reference},
                    "rule_version": "ASK_CORRECTION_V1",
                    "evidence": [],
                    "knowledge_used": [],
                    "reasons": ["EXPLICIT_USER_CORRECTION"],
                }
            batch = {
                "version": "CORRECTION_REVIEW_V1",
                "batch_id": "ASK-" + ticket,
                "cards": [card],
                "cards_hash": digest([card]),
            }
            service = ConfirmationService(
                self.queue.factory,
                batch,
                enabled=self.queue.enabled,
                signing_key=(self.queue.root / "queue.key").read_bytes(),
            )
            fields = item["parsed"]["fields"]
            selection = Selection(
                card_id=transaction_id,
                action="CHANGE",
                fields=fields,
                correction_reason=item["question"][:500],
                review_version=version,
                touched_fields=tuple(fields),
                explicit_unknown_fields=tuple(f for f, v in fields.items() if v == "UNKNOWN"),
            )
            preview = service.preview(selection, sid)
            item["services"][transaction_id] = service
            return preview

    def commit(self, ticket, transaction_id, commit, sid):
        with LOCK:
            item = self.entry(ticket, sid)
            service = item["services"].get(transaction_id)
            if service is None:
                raise ValueError("Preview this correction before applying it.")
            GroupReview(self.queue).verify_sources()
            return service.commit(commit, sid)


@lru_cache
def corrections():
    return Corrections(persistent_queue())


class Resolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=7600)


class Preview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str = Field(pattern=r"^[0-9a-f]{64}$")
    transaction_id: str = Field(max_length=36)


class Apply(Preview):
    commit: Commit


def fail(exc):
    known = str(exc)
    if known.isupper():
        known = (
            "Correction could not be applied safely. Refresh and preview again; "
            "check that review writes are enabled."
        )
    return HTTPException(409, known)


@router.get("/session")
def correction_session(response: Response, request: Request):
    return {"csrf": create_session(response, request, path="/pilot/corrections")}


@router.post("/resolve")
def resolve(body: Resolve, request: Request):
    try:
        return corrections().resolve(body.question, browser(request))
    except ValueError as exc:
        raise fail(exc) from None


@router.post("/preview")
def preview(body: Preview, request: Request):
    try:
        return corrections().preview(body.ticket, body.transaction_id, browser(request))
    except ValueError as exc:
        raise fail(exc) from None


@router.post("/commit")
def commit(body: Apply, request: Request):
    try:
        return corrections().commit(body.ticket, body.transaction_id, body.commit, browser(request))
    except ValueError as exc:
        raise fail(exc) from None
