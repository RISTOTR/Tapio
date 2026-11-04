"""Separate explicit category-mapping review; no context or transaction writes."""

import hashlib
import hmac
import json
import secrets
import time
from typing import Literal

from pydantic import Field

from tapio.confirmation.concept_review import ConceptReview
from tapio.knowledge.models import Typed, canonical


class MappingSelection(Typed):
    candidate_id: str
    action: Literal["CONFIRM_MAPPING", "REJECT_MAPPING", "DEFER_MAPPING"]
    expected_state: str
    revise: bool = False
    note: str = Field(default="", max_length=500)


class MappingReview(ConceptReview):
    event_directory = "mapping_decisions"
    decision_fields = ("action", "note")
    state_error = "STALE_MAPPING_STATE"

    def candidates(self):
        p = self.root / "candidates.json"
        from tapio.confirmation.candidate_evidence import refreshed

        candidates = json.loads(p.read_text()) if p.exists() else []
        return refreshed(self.root, candidates, self.decisions())

    def record(self, candidate_id):
        c = next((c for c in self.candidates() if c["id"] == candidate_id), None)
        if c is None:
            raise ValueError("MAPPING_NOT_ALLOWLISTED")
        e = self.decisions().get(candidate_id)
        active = bool(e and e["action"] == "CONFIRM_MAPPING")
        return {
            **c,
            "decision": {
                "CONFIRM_MAPPING": "CONFIRMED",
                "REJECT_MAPPING": "REJECTED",
                "DEFER_MAPPING": "DEFERRED",
            }.get(e["action"] if e else "", "PENDING"),
            "active": active,
            "authority": "HUMAN_CONFIRMED" if active else "SUGGESTED",
            "state_version": e["id"] if e else "PENDING",
        }

    def preview(self, selection, browser_session):
        s = MappingSelection.model_validate(selection)
        record = self.record(s.candidate_id)
        if s.expected_state != record["state_version"]:
            raise ValueError(self.state_error)
        if record["decision"] != "PENDING" and not s.revise:
            raise ValueError("EXPLICIT_REVISION_REQUIRED")
        c = next(c for c in self.candidates() if c["id"] == s.candidate_id)
        if s.action == "CONFIRM_MAPPING" and (
            c["concept"] == "GOVERNMENT_AGENCY"
            or c["category"] in {None, "UNKNOWN"}
            or c.get("conflicts")
        ):
            raise ValueError("UNSAFE_MAPPING")
        payload = {
            "selection": s.model_dump(),
            "candidate": c,
            "version": self.version(),
            "expected_state": s.expected_state,
            "session": browser_session,
            "expires": time.time() + 900,
            "nonce": secrets.token_hex(20),
        }
        token = canonical(
            {
                "payload": payload,
                "signature": hmac.new(
                    self.key, canonical(payload).encode(), hashlib.sha256
                ).hexdigest(),
            }
        )
        return {
            "selected": s.model_dump(),
            "candidate": c,
            "effect": (
                "Approve only this scoped category mapping. Requires separately "
                "confirmed semantic identity and sufficient current evidence. No "
                "context, tax-deductibility or transaction write."
            ),
            "token": token,
        }

    def apply(self, mappings):
        records = {c["concept_candidate_id"]: c for c in self.records()}
        output = []
        for original in mappings:
            m = {**original}
            r = records.get(m["candidate_id"])
            if (
                r
                and r["active"]
                and r["concept"] == m["concept"]
                and r["category"] == m["category"]
            ):
                m["blocked"] = [b for b in m["blocked"] if b != "EXPLICIT_MAPPING_REVIEW_REQUIRED"]
                m["eligible"] = not m["blocked"]
                m["mapping_confirmation_id"] = r["state_version"]
            output.append(m)
        return output

    def knowledge_events(self):
        # Mapping snapshots with their decision IDs are frozen by mapping_events.
        return []
