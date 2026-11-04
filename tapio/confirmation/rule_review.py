"""Explicit durable rule confirmation; the ledger never writes transaction labels."""

import hashlib
import hmac
import json
import secrets
import time
from datetime import date
from typing import Literal

from pydantic import Field

from tapio.confirmation.concept_review import ConceptReview
from tapio.knowledge.models import Claim, KnowledgeEvent, Provenance, Typed, canonical, digest
from tapio.knowledge.user_rules import UserRule


class RuleSelection(Typed):
    candidate_id: str
    action: Literal["CONFIRM_RULE", "EDIT_RULE", "REJECT_RULE", "DEFER_RULE"]
    rule: UserRule
    expected_state: str
    revise: bool = False
    scope_confirmed: bool = False
    note: str = Field(default="", max_length=500)


class RuleReview(ConceptReview):
    event_directory = "rule_decisions"
    decision_fields = ("action", "rule", "note", "scope_confirmed")
    state_error = "STALE_RULE_STATE"

    def candidates(self):
        p = self.root / "candidates.json"
        base = json.loads(p.read_text()) if p.exists() else []
        return base + [
            c
            for p in sorted((self.root / "candidate_additions").glob("*.json"))
            for c in json.loads(p.read_text())
        ]

    def record(self, candidate_id):
        c = next((c for c in self.candidates() if c["id"] == candidate_id), None)
        if c is None:
            raise ValueError("RULE_NOT_ALLOWLISTED")
        e = self.decisions().get(candidate_id)
        active = bool(e and e["action"] in {"CONFIRM_RULE", "EDIT_RULE"})
        states = {
            "CONFIRM_RULE": "CONFIRMED",
            "EDIT_RULE": "EDITED",
            "REJECT_RULE": "REJECTED",
            "DEFER_RULE": "DEFERRED",
        }
        return {
            **c,
            "rule": e["rule"] if e else c["rule"],
            "active": active,
            "authority": "HUMAN_CONFIRMED" if active else "SUGGESTED",
            "decision": states[e["action"]] if e else "PENDING",
            "state_version": e["id"] if e else "PENDING",
            "event_id": e["id"] if e else None,
            "timestamp": e["timestamp"] if e else None,
        }

    def active(self):
        return [
            {"candidate_id": r["id"], "rule": r["rule"], "event_id": r["event_id"]}
            for r in self.records()
            if r["active"]
        ]

    def preview(self, selection, browser_session):
        selection = RuleSelection.model_validate(selection)
        record = self.record(selection.candidate_id)
        if record["state_version"] != selection.expected_state:
            raise ValueError(self.state_error)
        if record["decision"] != "PENDING" and not selection.revise:
            raise ValueError("EXPLICIT_REVISION_REQUIRED")
        candidate = next(c for c in self.candidates() if c["id"] == selection.candidate_id)
        rule = selection.rule.model_dump(mode="json")
        original = candidate["rule"]
        if selection.action in {"CONFIRM_RULE", "EDIT_RULE"}:
            if selection.action == "CONFIRM_RULE" and rule != original:
                raise ValueError("USE_EDIT_RULE_FOR_CHANGES")
            if rule["subject"] != original["subject"] or rule["kind"] != original["kind"]:
                raise ValueError("RULE_SUBJECT_SCOPE_FROZEN")
            left = {k: v for k, v in rule["scope"].items() if k not in {"start", "end"}}
            right = {k: v for k, v in original["scope"].items() if k not in {"start", "end"}}
            if left != right:
                raise ValueError("RULE_SUBJECT_SCOPE_FROZEN")
            if rule["scope"]["type"] in {"TRIP", "DATE_RANGE"}:
                if not selection.scope_confirmed:
                    raise ValueError("EXPLICIT_TRIP_BOUNDARY_CONFIRMATION_REQUIRED")
                bounds = candidate["date_envelope"]
                if (
                    not date.fromisoformat(bounds["start"])
                    <= selection.rule.scope.start
                    <= selection.rule.scope.end
                    <= date.fromisoformat(bounds["end"])
                ):
                    raise ValueError("TRIP_OUTSIDE_STATED_DATE_ENVELOPE")
        payload = {
            "selection": selection.model_dump(mode="json"),
            "candidate": candidate,
            "expected_state": selection.expected_state,
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
            "selected": selection.model_dump(mode="json"),
            "effect": (
                "Confirm this scoped THIS_USER rule and the separately listed semantic facts. "
                "Future bounded cards receive suggestions only; "
                "no transaction labels or tax status change."
            ),
            "semantic_facts": candidate.get("semantic_facts", []),
            "token": canonical(token),
        }

    def knowledge_events(self):
        events = []
        for e in self.events():
            if e["action"] not in {"CONFIRM_RULE", "EDIT_RULE"}:
                continue
            p = Provenance(
                source_type="user_rule_decisions",
                source_id=e["id"],
                source_hash=digest(e),
                originating_field="rule",
                observed_at=e["timestamp"],
                extraction_method="explicit-scoped-user-rule-review-v1",
                confirmation_id=e["id"],
            )
            claims = [
                Claim(
                    kind="USER_RULE",
                    subject=e["rule"]["subject"],
                    predicate="user_classification_rule",
                    value=e["rule"],
                    scope="THIS_USER:" + e["candidate_id"],
                    authority="HUMAN_CONFIRMED",
                    provenance=p,
                )
            ]
            for fact in e["candidate_snapshot"].get("semantic_facts", []):
                claims.append(
                    Claim(
                        kind=fact["kind"],
                        subject=fact["subject"],
                        predicate="semantic_concept",
                        value=fact["concept"],
                        scope="THIS_USER",
                        authority="HUMAN_CONFIRMED",
                        provenance=p,
                    )
                )
            events.append(KnowledgeEvent(event_type="HUMAN_REVIEW_CONFIRMED", claims=tuple(claims)))
        return events
