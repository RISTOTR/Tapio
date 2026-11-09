"""Explicit local-user rules: deterministic scoped suggestions, never source writes."""

import re
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from apps.api.app.domain.enums import TransactionCategory
from data_pipeline.labels.merchant_policy import ambiguous_merchant
from tapio.knowledge.concepts import identity, matches
from tapio.knowledge.models import Typed, digest
from tapio.pilot.subject_identity import normalize_subject, resolve_subject


class RuleScope(Typed):
    type: Literal[
        "ENTITY_EXACT",
        "ENTITY_FAMILY",
        "VOCABULARY",
        "DATE_RANGE",
        "TRIP",
        "TRANSACTION_PATTERN",
        "USER_GLOBAL_TAXONOMY",
    ]
    owner: Literal["THIS_USER"] = "THIS_USER"
    entity: str | None = None
    aliases: tuple[str, ...] = ()
    concept: str | None = None
    terms: tuple[str, ...] = ()
    start: date | None = None
    end: date | None = None
    date_field: Literal["booking_date"] = "booking_date"
    transport_entities: dict[str, Literal["BUS", "TRAIN", "FLIGHT"]] = Field(default_factory=dict)
    modes: tuple[Literal["BUS", "TRAIN", "FLIGHT"], ...] = ()
    purpose: str | None = None

    @model_validator(mode="after")
    def bounded(self):
        if self.type in {"ENTITY_EXACT", "ENTITY_FAMILY"}:
            if (
                not self.entity
                or self.terms
                or self.concept
                or self.start
                or self.end
                or self.modes
                or self.transport_entities
                or self.purpose
            ):
                raise ValueError("EXCLUSIVE_ENTITY_SCOPE_REQUIRED")
            if self.type == "ENTITY_EXACT" and self.aliases:
                raise ValueError("EXACT_SCOPE_CANNOT_HAVE_ALIASES")
            if ambiguous_merchant(self.entity) or "paytrail" in normalize_subject(self.entity):
                raise ValueError("AMBIGUOUS_MERCHANT_RULE_FORBIDDEN")
        elif self.type in {"VOCABULARY", "USER_GLOBAL_TAXONOMY"}:
            if (
                not self.concept
                or not self.terms
                or len(self.terms) > 10
                or self.entity
                or self.aliases
                or self.start
                or self.end
                or self.modes
                or self.transport_entities
                or self.purpose
            ):
                raise ValueError("EXCLUSIVE_TAXONOMY_SCOPE_REQUIRED")
            if any(not t.strip() or len(t) < 3 for t in self.terms):
                raise ValueError("BOUNDED_VOCABULARY_REQUIRED")
        elif self.type in {"TRIP", "DATE_RANGE"}:
            if (
                not self.start
                or not self.end
                or self.start > self.end
                or (self.end - self.start).days > 62
                or not self.modes
                or not self.transport_entities
                or not self.purpose
            ):
                raise ValueError("BOUNDED_TRANSPORT_SCOPE_REQUIRED")
            if self.entity or self.aliases or self.terms or self.concept:
                raise ValueError("EXCLUSIVE_TRIP_SCOPE_REQUIRED")
        else:
            raise ValueError("TRANSACTION_PATTERN_NOT_ENABLED")
        return self


class UserRule(Typed):
    subject: str = Field(min_length=2, max_length=160)
    kind: Literal[
        "MERCHANT_CLASSIFICATION_RULE",
        "VOCABULARY_CLASSIFICATION_RULE",
        "ENTITY_CLASSIFICATION_RULE",
        "DATE_SCOPED_CONTEXT_RULE",
        "TRIP_SCOPED_RULE",
        "RECIPIENT_CLASSIFICATION_RULE",
    ]
    category: TransactionCategory
    context: Literal["PERSONAL", "PROPERTY", "FORESTRY", "UNKNOWN"]
    scope: RuleScope

    @model_validator(mode="after")
    def consistent(self):
        if self.kind in {"TRIP_SCOPED_RULE", "DATE_SCOPED_CONTEXT_RULE"}:
            if self.scope.type not in {"TRIP", "DATE_RANGE"} or self.category != "TRAVEL":
                raise ValueError("TRIP_REQUIRES_TRAVEL_SCOPE")
        elif self.scope.type in {"TRIP", "DATE_RANGE"}:
            raise ValueError("TRIP_RULE_KIND_REQUIRED")
        return self


def entity_match(value, entity, aliases=()):
    if not value:
        return False
    # The existing resolver permits only explicit aliases and unique legal-name variants.
    resolution = resolve_subject(value, {entity})
    return resolution["status"] == "MATCH_FOUND" or normalize_subject(value) in {
        normalize_subject(a) for a in aliases
    }


def rule_match(rule, tx, reuse=None):
    scope = rule.scope
    value = identity(tx)  # Processor identity never replaces the underlying recipient.
    if not value:
        return None
    if scope.type == "ENTITY_EXACT":
        matched = (
            reuse.key(value) == reuse.key(scope.entity)
            if reuse
            else normalize_subject(value) == normalize_subject(scope.entity)
        )
    elif scope.type == "ENTITY_FAMILY":
        matched = entity_match(value, scope.entity, scope.aliases)
        if reuse:
            matched = matched or any(
                reuse.key(value) == reuse.key(n) for n in (scope.entity, *scope.aliases)
            )
    elif scope.type in {"VOCABULARY", "USER_GLOBAL_TAXONOMY"}:
        if ambiguous_merchant(value):
            return None
        terms = [t for t in scope.terms if matches(t, "TOKEN", value)]
        links = reuse.vocabulary(scope.concept, scope.terms, value) if reuse else []
        return (
            {
                "identity": value,
                "matched_terms": terms,
                "concept": scope.concept,
                "vocabulary_links": links,
            }
            if terms or links
            else None
        )
    else:
        try:
            day = date.fromisoformat(str(tx.get("booking_date", ""))[:10])
        except ValueError:
            return None
        if not scope.start <= day <= scope.end:
            return None
        modes = {m for name, m in scope.transport_entities.items() if entity_match(value, name)}
        if len(modes) != 1 or not modes <= set(scope.modes):
            return None
        return {
            "identity": value,
            "date": str(day),
            "date_field": scope.date_field,
            "transport_mode": next(iter(modes)),
            "purpose": scope.purpose,
        }
    return {"identity": value, "resolution": scope.type} if matched else None


def apply_user_rules(card, tx, active, reuse=None):
    result = deepcopy(card)
    matched = []
    for item in active:
        rule = UserRule.model_validate(item["rule"])
        evidence = rule_match(rule, tx, reuse)
        if evidence:
            matched.append(
                {
                    "rule_id": item["candidate_id"],
                    "event_id": item["event_id"],
                    "authority": "HUMAN_CONFIRMED",
                    "rule": rule.model_dump(mode="json"),
                    "evidence": evidence,
                }
            )
    result["user_rules"] = matched
    result["user_rule_conflicts"] = []
    for field in ("category", "context"):
        if result["current_state"].get("authority", {}).get(field) == "HUMAN_CONFIRMED":
            continue
        values = {m["rule"][field] for m in matched}
        if len(values) > 1:
            result["suggestion"][field] = None
            result["user_rule_conflicts"].append(field)
        elif values:
            result["suggestion"][field] = next(iter(values))
    if result["user_rule_conflicts"]:
        result["reasons"].append(
            {
                "code": "USER_RULE_CONFLICT",
                "explanation": "Conflicting confirmed user rules require review; no majority vote.",
                "evidence_refs": [m["event_id"] for m in matched],
            }
        )
    if matched:
        result["reasons"].append(
            {
                "code": "USER_RULE_MATCH",
                "explanation": (
                    "Explicit THIS_USER rule matched its frozen scope; labels remain "
                    "suggestions for this transaction. No tax decision."
                ),
                "evidence_refs": [m["event_id"] for m in matched],
            }
        )
        if result.get("paytrail_purpose") == "STILL_OPAQUE" and result["suggestion"].get(
            "category"
        ):
            result["paytrail_purpose"] = "PARTIAL_PURPOSE"
        if "pilot_tags" in result:
            tags = [
                t
                for t in result["pilot_tags"]
                if t
                not in {"BOTH", "CATEGORY_ONLY", "CONTEXT_ONLY", "ABSTENTION", "USER_RULE_MATCH"}
                and not t.startswith("PAYTRAIL_")
            ]
            c, x = (result["suggestion"].get(k) for k in ("category", "context"))
            tags += [
                "BOTH"
                if c and x
                else "CATEGORY_ONLY"
                if c
                else "CONTEXT_ONLY"
                if x
                else "ABSTENTION",
                "USER_RULE_MATCH",
            ]
            if result.get("paytrail_purpose"):
                tags.append("PAYTRAIL_" + result["paytrail_purpose"])
            result["pilot_tags"] = tags
            if c or x:
                result["warnings"] = [
                    w
                    for w in result.get("warnings", [])
                    if w != "No supported suggestion is available. Use CHANGE or SKIP."
                ]
    result["card_id"] = digest(result)[:32]
    return result


SUBJECT_PATTERNS = {
    "DNA Oyj": r"\bdna\b",
    "RESTAURANT": r"\b(ravintola|restaurant)\b",
    "CAFE": r"\b(cafe|café|kahvila)\b",
    "BAR": r"\b(bar|baari)\b",
    "Lepolan yksityistie": r"\blepolan\s+yksityistie\b",
    "Pyöreisen yksityistie": r"\bpyöreisen\s+yksityistie\b",
    "2026_MAY_JUNE_FORESTRY_TRIP": r"(plant trees|tree planting|istut)",
}


def explanations(revisions, transactions):
    """Bounded candidate extraction, not unrestricted free-text rule execution."""
    txs = {t["id"]: t for t in transactions}
    found = defaultdict(list)
    for row in revisions:
        note = row["audit"].get("correction_reason", "").strip()
        if not note:
            continue
        for subject, pattern in SUBJECT_PATTERNS.items():
            if re.search(pattern, normalize_subject(note)):
                found[subject].append(
                    {
                        "review_id": row["id"],
                        "review_hash": digest(row),
                        "transaction_id": row["transaction_id"],
                        "timestamp": row.get("created_at"),
                        "booking_date": txs[row["transaction_id"]]["booking_date"],
                        "statement": note,
                        "labels": row["fields"],
                    }
                )
    return dict(found)


def friction_metrics(observations, decisions, cards):
    repeated = {subject: max(0, len(rows) - 1) for subject, rows in observations.items()}
    missed = []
    after = 0
    for subject, rows in observations.items():
        for row in rows:
            card = cards.get(row["transaction_id"])
            if not card or not card.get("created_at"):
                continue
            created = datetime.fromisoformat(card["created_at"])
            if not row.get("timestamp") or datetime.fromisoformat(row["timestamp"]) < created:
                continue
            latest = {}
            for event in sorted(decisions, key=lambda e: e["timestamp"]):
                if datetime.fromisoformat(event["timestamp"]) <= created:
                    latest[event["candidate_id"]] = event
            for event in latest.values():
                if event["rule"]["subject"] != subject or event["action"] not in {
                    "CONFIRM_RULE",
                    "EDIT_RULE",
                }:
                    continue
                if not rule_match(
                    UserRule.model_validate(event["rule"]), card["source_transaction"]
                ):
                    continue
                after += 1
                if any(
                    card["suggestion"].get(f) is None
                    and card.get("current_state", {}).get("authority", {}).get(f)
                    != "HUMAN_CONFIRMED"
                    for f in ("category", "context")
                ):
                    missed.append(
                        {
                            "code": "MISSED_KNOWLEDGE_REUSE",
                            "review_id": row["review_id"],
                            "rule_event_id": event["id"],
                        }
                    )
    return {
        "code": "REPEATED_EXPLANATION",
        "repeat_counts": repeated,
        "total_repeats": sum(repeated.values()),
        "missed_reuse": missed,
        "later_explanations_in_matching_active_scope": after,
        "after_activation": "NOT_OBSERVED" if not after else "OBSERVED",
    }


def explicit_user_context(card):
    """Only a frozen, matched user rule can override weak context abstention."""
    context = card["suggestion"].get("context")
    return bool(
        context
        and not card.get("user_rule_conflicts")
        and any(
            m["authority"] == "HUMAN_CONFIRMED"
            and m.get("event_id")
            and m["rule"]["context"] == context
            and m["evidence"].get("identity")
            and not ambiguous_merchant(m["evidence"]["identity"])
            for m in card.get("user_rules", [])
        )
    )
