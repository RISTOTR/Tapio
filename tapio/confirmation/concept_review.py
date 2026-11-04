"""Append-only explicit human review of allowlisted concept candidates."""

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from tapio.knowledge.category_mappings import derive_mappings
from tapio.knowledge.concepts import ConceptName
from tapio.knowledge.models import Claim, KnowledgeEvent, Provenance, Typed, canonical, digest


class ConceptSelection(Typed):
    candidate_id: str
    action: Literal["CONFIRM_CONCEPT", "EDIT_CONCEPT", "REJECT_CONCEPT", "DEFER"]
    concept: ConceptName
    note: str = Field(default="", max_length=500)
    expected_state: str | None = None
    revise: bool = False


class ConceptReview:
    event_directory = "concept_decisions"
    decision_fields = ("action", "concept", "note")
    state_error = "STALE_CONCEPT_STATE"

    def __init__(self, root, key=None):
        self.root = Path(root)
        self.key = key or secrets.token_bytes(32)

    def candidates(self):
        base = json.loads((self.root / "candidates.json").read_text())
        candidates = base + [
            c
            for p in sorted((self.root / "candidate_additions").glob("*.json"))
            for c in json.loads(p.read_text())
        ]

        from tapio.confirmation.candidate_evidence import refreshed

        return refreshed(self.root, candidates, self.decisions())

    def events(self):
        events = [
            json.loads(p.read_text())
            for p in sorted((self.root / self.event_directory).glob("*.json"))
        ]
        previous = None
        for event in events:
            if (
                event["previous"] != previous
                or digest({k: v for k, v in event.items() if k != "id"}) != event["id"]
            ):
                raise ValueError("CONCEPT_AUDIT_INTEGRITY")
            previous = event["id"]
        return events

    def decisions(self):
        return {e["candidate_id"]: e for e in self.events()}

    def version(self):
        return digest({"candidates": self.candidates(), "events": self.events()})

    def record(self, candidate_id):
        candidate = next((c for c in self.candidates() if c["id"] == candidate_id), None)
        if candidate is None:
            raise ValueError("CONCEPT_NOT_ALLOWLISTED")
        event = self.decisions().get(candidate_id)
        statuses = {
            "CONFIRM_CONCEPT": "CONFIRMED",
            "EDIT_CONCEPT": "EDITED",
            "REJECT_CONCEPT": "REJECTED",
            "DEFER": "DEFERRED",
        }
        active = bool(event and event["action"] in {"CONFIRM_CONCEPT", "EDIT_CONCEPT"})
        return {
            **candidate,
            "decision": statuses[event["action"]] if event else "PENDING",
            "concept": event["concept"] if event else candidate["concept"],
            "proposed_concept": candidate["concept"],
            "authority": "HUMAN_CONFIRMED" if active else "SUGGESTED",
            "active": active,
            "active_for_suggestions": active
            and event["concept"] == candidate["concept"]
            and derive_mappings([candidate])[0]["eligible"],
            "timestamp": event["timestamp"] if event else None,
            "event_id": event["id"] if event else None,
            "state_version": event["id"] if event else "PENDING",
        }

    def records(self):
        return [self.record(c["id"]) for c in self.candidates()]

    def commit_result(self, token, browser_session):
        before = len(self.events())
        event = self.commit(token, browser_session)
        return {
            "status": "SAVED" if len(self.events()) > before else "ALREADY_APPLIED",
            "record": self.record(event["candidate_id"]),
            "event_id": event["id"],
        }

    def preview(self, selection, browser_session):
        selection = ConceptSelection.model_validate(selection)
        candidate = next((c for c in self.candidates() if c["id"] == selection.candidate_id), None)
        if candidate is None:
            raise ValueError("CONCEPT_NOT_ALLOWLISTED")
        if selection.action == "CONFIRM_CONCEPT" and selection.concept != candidate["concept"]:
            raise ValueError("USE_EDIT_FOR_CHANGED_CONCEPT")
        state = self.record(selection.candidate_id)["state_version"]
        if selection.expected_state is not None and selection.expected_state != state:
            raise ValueError(self.state_error)
        payload = {
            "selection": selection.model_dump(),
            "candidate": candidate,
            "version": self.version(),
            "expected_state": state,
            "session": browser_session,
            "expires": time.time() + 900,
            "nonce": secrets.token_hex(20),
        }
        token = {
            "payload": payload,
            "signature": hmac.new(
                self.key, canonical(payload).encode(), hashlib.sha256
            ).hexdigest(),
        }
        return {
            "candidate": candidate,
            "selected": selection.model_dump(),
            "effect": "Concept authority only; no transaction classification or context rule.",
            "token": canonical(token),
        }

    def commit(self, token, browser_session):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".concept.lock").open("a") as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._commit_locked(token, browser_session)

    def _commit_locked(self, token, browser_session):
        value = json.loads(token)
        p = value["payload"]
        expected = hmac.new(self.key, canonical(p).encode(), hashlib.sha256).hexdigest()
        if (
            not hmac.compare_digest(expected, value["signature"])
            or p["session"] != browser_session
            or p["expires"] < time.time()
        ):
            raise ValueError("INVALID_CONCEPT_PREVIEW")
        events = self.events()
        existing = next((e for e in events if e["nonce"] == p["nonce"]), None)
        if existing:
            return existing
        current = self.decisions().get(p["selection"]["candidate_id"])
        state = current["id"] if current else "PENDING"
        if (
            state != p["expected_state"]
            or next(c for c in self.candidates() if c["id"] == p["selection"]["candidate_id"])
            != p["candidate"]
        ):
            raise ValueError(self.state_error)
        if current and all(
            current.get(k, "") == p["selection"].get(k, "") for k in self.decision_fields
        ):
            return current
        event = {
            **p["selection"],
            "candidate_snapshot": p["candidate"],
            "nonce": p["nonce"],
            "previous": events[-1]["id"] if events else None,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        event["id"] = digest(event)
        path = self.root / self.event_directory / f"{len(events) + 1:06d}.json"
        path.parent.mkdir(mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(canonical(event))
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)  # Atomic publication; never overwrite an event.
        finally:
            os.unlink(temporary)
        return event

    def knowledge_events(self):
        output = []
        # Retain contrary historical confirmations. Consumption uses latest decisions
        # and blocks conflicting scopes, rather than erasing prior assertions.
        for e in self.events():
            if e["action"] not in {"CONFIRM_CONCEPT", "EDIT_CONCEPT"}:
                continue
            c = e["candidate_snapshot"]
            output.append(
                KnowledgeEvent(
                    event_type="HUMAN_REVIEW_CONFIRMED",
                    claims=(
                        Claim(
                            kind=c["kind"],
                            subject=c["term"],
                            predicate="semantic_concept",
                            value=e["concept"],
                            scope=c["match_mode"],
                            authority="HUMAN_CONFIRMED",
                            single_valued=True,
                            provenance=Provenance(
                                source_type="concept_decisions",
                                source_id=e["id"],
                                source_hash=digest(e),
                                originating_field="concept",
                                observed_at=e["timestamp"],
                                extraction_method="explicit-concept-review-v1",
                                confirmation_id=e["id"],
                            ),
                        ),
                    ),
                )
            )
        return output
