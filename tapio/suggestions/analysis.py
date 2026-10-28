"""Offline feedback analysis. No source, knowledge or feedback writes."""

import json
from collections import Counter
from datetime import datetime

from data_pipeline.labels.merchant_policy import ambiguous_merchant
from tapio.knowledge.models import digest
from tapio.knowledge.queries import KnowledgeQueries
from tapio.suggestions.models import FeedbackInput

CHOICES = ("CORRECT", "PARTIALLY_USEFUL", "WRONG", "INSUFFICIENT_EVIDENCE", "SKIP")
CONTENTS = ("CATEGORY_ONLY", "CONTEXT_ONLY", "CATEGORY_AND_CONTEXT", "ABSTENTION")
PRIORITIES = ("HIGH_REVIEW_VALUE", "MEDIUM_REVIEW_VALUE", "LOW_REVIEW_VALUE", "AMBIGUOUS_REVIEW")
REASONS = (
    "MERCHANT_PREVIOUSLY_REVIEWED",
    "EXACT_MERCHANT_IDENTITY",
    "EXACT_ALIAS_MATCH",
    "RELATED_DOCUMENT_FOUND",
    "RECURRING_PATTERN",
    "SOURCE_TEXT_MATCH",
    "MULTI_CONTEXT_MERCHANT",
    "CONFLICTING_OBSERVATIONS",
)


def content(card):
    a, b = card.suggestion.category is not None, card.suggestion.context is not None
    return (
        "CATEGORY_AND_CONTEXT"
        if a and b
        else ("CATEGORY_ONLY" if a else "CONTEXT_ONLY" if b else "ABSTENTION")
    )


def load_feedback(store):
    """Validate saved snapshots, ignore other batches, never invent unanswered feedback."""
    batch, cards = store.batch()
    by_id = {c.card_id: c for c in cards}
    latest, ignored, count = {}, 0, 0
    for path in sorted((store.root / "feedback").glob("*.json")):
        r = json.loads(path.read_text())
        if r["batch_hash"] != batch["cards_hash"]:
            ignored += 1
            continue
        c = by_id.get(r["card_id"])
        if (
            c is None
            or r["card_hash"] != digest(c)
            or r["transaction_reference"] != c.transaction.id
            or r["suggestion_snapshot"] != c.suggestion.model_dump(mode="json")
        ):
            raise ValueError("FEEDBACK_SNAPSHOT_MISMATCH")
        FeedbackInput(choice=r["choice"], note=r["note"])
        timestamp = datetime.fromisoformat(r["timestamp"])
        if timestamp.tzinfo is None:
            raise ValueError("FEEDBACK_TIMEZONE_REQUIRED")
        old = latest.get(c.card_id)
        if old:
            previous = datetime.fromisoformat(old["timestamp"])
            if timestamp == previous and (r["choice"], r["note"]) != (old["choice"], old["note"]):
                raise ValueError("AMBIGUOUS_LATEST_FEEDBACK")
            if timestamp < previous:
                count += 1
                continue
        latest[c.card_id] = r
        count += 1
    return cards, latest, {"saved_records": count, "other_batch_records": ignored}


def distribution(cards, feedback):
    counts = Counter(feedback[c.card_id]["choice"] for c in cards if c.card_id in feedback)
    return {
        "total": len(cards),
        "reviewed": sum(counts.values()),
        "unanswered": len(cards) - sum(counts.values()),
        **{k: counts[k] for k in CHOICES},
    }


def note_themes(note):
    """Conservative tags only; no raw text or inferred confirmations in summary."""
    value = note.casefold()
    themes = []
    for tag, terms in {
        "MERCHANT_TYPE_INSURANCE": ("insurance", "vakuutus"),
        "SERVICE_TYPE_REPAIR": ("repair", "korjaus", "huolto"),
        "MERCHANT_TYPE_CAFE": ("café", "cafe"),
        "CATEGORY_GROCERIES": ("groceries", "ruokakauppa"),
        "TRANSACTION_CONTEXT_PERSONAL": ("personal", "henkilökohtainen"),
        "NEEDS_DOCUMENT": ("receipt", "document", "kuitti", "lasku"),
    }.items():
        if any(term in value for term in terms):
            themes.append(tag)
    return themes or (["OTHER_NOTE_REQUIRES_MANUAL_READING"] if note.strip() else [])


def safety_findings(cards, snapshot):
    """Check authority and exact provenance support; findings require human review."""
    q = KnowledgeQueries(snapshot)
    by_id = {i.id: i for i in snapshot.items}
    findings = []
    for c in cards:
        flags = set()
        reasons = {r.code for r in c.reasons}
        inputs = {e.id: e for e in c.evidence}
        for key in c.knowledge_used:
            item, evidence = by_id.get(key), inputs.get(key)
            if (
                item is None
                or evidence is None
                or evidence.authority != item.claim.authority
                or evidence.provenance != item.provenance
            ):
                flags.add("PROVENANCE_OR_AUTHORITY_MISMATCH")
        if (
            ambiguous_merchant(c.transaction.merchant) or "MULTI_CONTEXT_MERCHANT" in reasons
        ) and c.suggestion.context is not None:
            flags.add("MULTI_CONTEXT_IDENTITY_SUGGESTION")
        for field, predicate in [
            ("category", "confirmed_category"),
            ("context", "confirmed_business_context"),
        ]:
            value = getattr(c.suggestion, field)
            if value is None:
                continue
            if getattr(c.current_state, field) not in (None, "UNKNOWN"):
                flags.add("STRONGER_HUMAN_FACT_IGNORED")
            history = [
                by_id[k]
                for k in c.knowledge_used
                if k in by_id
                and by_id[k].claim.predicate == predicate
                and q.accepted(by_id[k])
                and by_id[k].claim.subject != c.transaction.id
            ]
            values = {i.claim.value for i in history if i.claim.value != "UNKNOWN"}
            if values != {value} or not all(
                i.claim.authority == "HUMAN_CONFIRMED" for i in history
            ):
                flags.add("UNSUPPORTED_OR_CONFLICTING_LABEL")
        if content(c) != "ABSTENTION" and any(
            by_id[k].claim.relationship_status in {"AMBIGUOUS", "CANDIDATE"}
            for k in c.knowledge_used
            if k in by_id
        ):
            flags.add("AMBIGUOUS_RELATIONSHIP_USED_WITH_LABEL")
        presentation = " ".join(r.explanation for r in c.reasons).casefold()
        if any(
            term in presentation for term in ("deductible", "tax deduction", "always classified")
        ):
            flags.add("TAX_OR_MERCHANT_RULE_LANGUAGE_REQUIRES_REVIEW")
        if c.suggestion.authority != "SUGGESTED":
            flags.add("SUGGESTION_AUTHORITY_PROMOTED")
        findings.extend({"card_id": c.card_id, "code": flag} for flag in sorted(flags))
    return findings


def analyze(cards, feedback, snapshot):
    totals = distribution(cards, feedback)
    by_content = {
        k: distribution([c for c in cards if content(c) == k], feedback) for k in CONTENTS
    }
    priorities = {
        k: distribution([c for c in cards if c.priority == k], feedback) for k in PRIORITIES
    }
    reasons = sorted(set(REASONS) | {r.code for c in cards for r in c.reasons})
    by_reason = {
        k: distribution([c for c in cards if k in {r.code for r in c.reasons}], feedback)
        for k in reasons
    }
    themes = Counter(t for r in feedback.values() for t in note_themes(r["note"]))
    positive = distribution([c for c in cards if content(c) != "ABSTENTION"], feedback)
    abstention = by_content["ABSTENTION"]
    unsafe = safety_findings(cards, snapshot)
    # Conservative gate for recommending a design, never an authorization for writes.
    ready = (
        not unsafe
        and not totals["unanswered"]
        and not totals["WRONG"]
        and positive["CORRECT"] > 0
        and priorities["HIGH_REVIEW_VALUE"]["CORRECT"] > 0
    )
    return {
        "totals": totals,
        "by_content": by_content,
        "by_priority": priorities,
        "by_reason": by_reason,
        "positive_suggestions": positive,
        "abstentions": abstention,
        "notes_saved": sum(bool(r["note"].strip()) for r in feedback.values()),
        "note_themes": dict(themes),
        "unsafe_findings": unsafe,
        "decision": (
            "READY_FOR_CONTROLLED_CONFIRMATION_WORKFLOW"
            if ready
            else "SUGGESTION_RULES_NEED_REVIEW"
        ),
        "decision_scope": "Design recommendation only; no write authorization.",
        "limitations": [
            "Small selected sample; overlapping reasons are associations, not causal effects.",
            "Card-level feedback cannot establish separate category/context accuracy.",
            "INSUFFICIENT_EVIDENCE on abstention is not failure "
            "or explicit proof of appropriateness.",
            "Note themes are lexical review aids, not accepted knowledge or confirmed labels.",
            "Any WRONG response requires a separate bounded-error review before a ready decision.",
        ],
    }
