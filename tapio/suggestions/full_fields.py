"""Versioned, source-message-backed suggestions; processor identity never supplies context."""

from data_pipeline.normalize.bank import counterparty_fields
from tapio.knowledge.models import digest
from tapio.suggestions.generate import Generator
from tapio.suggestions.models import EvidenceInput, Reason, Suggestion


def message_recipient(tx):
    raw = tx.get("raw_source") or {}
    return counterparty_fields(tx.get("raw_counterparty"), raw.get("Viesti"))["ultimate_recipient"]


class FullFieldGenerator(Generator):
    def card(self, tx, signals):
        base = super().card(tx, signals)
        evidence = {e.id: e for e in base.evidence}
        used = set(base.knowledge_used)
        reasons = list(base.reasons)
        suggestion = base.suggestion
        facts = [
            i
            for i in self.snapshot.items
            if i.claim.subject == tx["id"]
            and i.claim.predicate == "observed_source_text"
            and isinstance(i.claim.value, dict)
            and i.claim.value.get("field") == "raw_source.Viesti"
            and self.q.accepted(i)
        ]
        for i in facts:
            evidence[i.id] = EvidenceInput(
                id=i.id,
                authority=i.claim.authority,
                summary="Exact source message (Viesti), distinct from Selitys.",
                provenance=i.provenance,
            )
            used.add(i.id)
        if facts:
            reasons.append(
                Reason(
                    code="SOURCE_MESSAGE_MATCH",
                    explanation=(
                        "Viesti is available as explicit message evidence; "
                        "it does not confirm labels."
                    ),
                    evidence_refs=tuple(i.id for i in facts),
                )
            )
        if signals["merchant"] == "Paytrail Oyj":
            recipient = message_recipient(tx)
            prior_ids = {
                t["id"]
                for t in self.txs.values()
                if recipient and t["id"] != tx["id"] and message_recipient(t) == recipient
            }
            history = [
                i
                for i in self.snapshot.items
                if i.claim.subject in prior_ids
                and i.claim.predicate == "confirmed_category"
                and i.claim.authority == "HUMAN_CONFIRMED"
                and self.q.accepted(i)
                and i.claim.value != "UNKNOWN"
            ]
            values = {i.claim.value for i in history}
            category = next(iter(values)) if len(values) == 1 and facts else None
            if base.current_state.category not in (None, "UNKNOWN") or signals["ambiguous_links"]:
                category = None
            suggestion = Suggestion(category=category, context=None)
            if category:
                refs = []
                for i in history:
                    evidence[i.id] = EvidenceInput(
                        id=i.id,
                        authority=i.claim.authority,
                        summary="Category observation for the same explicitly named recipient.",
                        provenance=i.provenance,
                    )
                    used.add(i.id)
                    refs.append(i.id)
                # Include the exact other messages proving recipient scope, not just label history.
                for i in self.snapshot.items:
                    if (
                        i.claim.subject in prior_ids
                        and i.claim.predicate == "observed_source_text"
                        and i.claim.value.get("field") == "raw_source.Viesti"
                    ):
                        evidence[i.id] = EvidenceInput(
                            id=i.id,
                            authority=i.claim.authority,
                            summary="Prior transaction message naming the same recipient.",
                            provenance=i.provenance,
                        )
                        used.add(i.id)
                        refs.append(i.id)
                reasons.append(
                    Reason(
                        code="SOURCE_MESSAGE_MATCH",
                        evidence_refs=tuple(refs),
                        explanation="Category suggestion uses agreeing human observations for "
                        "the exact recipient named in Viesti. Paytrail identity supplies no "
                        "category or context rule.",
                    )
                )
        return base.model_copy(
            update={
                "card_id": digest(
                    {
                        "transaction": tx,
                        "knowledge": self.snapshot.events_hash,
                        "rule": "FULL_CSV_CARDS_V2",
                    }
                )[:32],
                "rule_version": "FULL_CSV_CARDS_V2",
                "suggestion": suggestion,
                "reasons": tuple(reasons),
                "evidence": tuple(evidence.values()),
                "knowledge_used": tuple(sorted(used)),
                "warnings": tuple(
                    w
                    for w in base.warnings
                    if not (suggestion.category and w.startswith("No supported label suggestion"))
                ),
            }
        )
