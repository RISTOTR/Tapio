"""Bounded card generation from exact identities and explicit source observations."""

from collections import Counter
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from data_pipeline.labels.merchant_policy import ambiguous_merchant
from tapio.knowledge.fields import source_text_fields
from tapio.knowledge.models import Provenance, Snapshot, digest
from tapio.knowledge.queries import KnowledgeQueries
from tapio.pilot.subject_identity import resolve_subject
from tapio.pilot.transaction_search import matching_terms
from tapio.suggestions.models import (
    Card,
    CurrentState,
    EvidenceInput,
    Reason,
    Suggestion,
    TransactionView,
)


def eligible(tx, reviews):
    r = reviews.get(tx["id"])
    return (
        not r
        or r["review_status"] != "REVIEWED"
        or any(
            r.get(k) in (None, "UNKNOWN")
            for k in ("confirmed_category", "confirmed_business_context")
        )
    )


class Generator:
    def __init__(
        self,
        snapshot: Snapshot,
        transactions: list[dict],
        reviews: list[dict],
        observed_at: datetime,
    ):
        self.snapshot = snapshot
        self.q = KnowledgeQueries(snapshot)
        self.txs = {t["id"]: t for t in transactions}
        self.reviews = {r["transaction_id"]: r for r in reviews}
        self.when = observed_at
        self.names = {
            t["normalized_counterparty"] for t in transactions if t.get("normalized_counterparty")
        }
        self.by_id = {i.id: i for i in snapshot.items}

    def signals(self, tx):
        raw_name = tx.get("normalized_counterparty") or tx.get("raw_counterparty") or ""
        resolution = resolve_subject(raw_name, self.names)
        merchant = resolution["canonical_subject"] or raw_name or "Unnamed"
        items = self.q.get_entity_knowledge(merchant)
        observations = [
            i
            for i in items
            if i.claim.kind == "MERCHANT_OBSERVATION"
            and i.claim.scope != tx["id"]
            and self.q.accepted(i)
        ]
        ids = {i.claim.scope for i in observations}
        history = [
            i
            for i in self.snapshot.items
            if i.claim.kind == "RELATIONSHIP"
            and i.claim.subject in ids
            and i.claim.predicate in {"confirmed_category", "confirmed_business_context"}
            and self.q.accepted(i)
        ]
        categories = Counter(
            str(i.claim.value)
            for i in history
            if i.claim.predicate == "confirmed_category" and i.claim.value != "UNKNOWN"
        )
        contexts = Counter(
            str(i.claim.value)
            for i in history
            if i.claim.predicate == "confirmed_business_context" and i.claim.value != "UNKNOWN"
        )
        links = []
        for i in self.snapshot.items:
            c = i.claim
            if c.kind != "RELATIONSHIP":
                continue
            if (
                c.predicate == "bank_allocation"
                and isinstance(c.value, dict)
                and c.value.get("transaction_id") == tx["id"]
            ):
                links.append(i)
            if c.predicate == "possible_reversal" and tx["id"] in (c.subject, c.value):
                links.append(i)
        ambiguous_links = any(
            i.claim.relationship_status in {"CANDIDATE", "AMBIGUOUS"} for i in links
        )
        recurring = [i for i in items if i.claim.kind == "RECURRING_PATTERN" and self.q.accepted(i)]
        aliases = [i for i in items if i.claim.kind == "ENTITY_ALIAS" and self.q.accepted(i)]
        text_fields = source_text_fields(tx)
        vocab = []
        for i in self.snapshot.items:
            if i.claim.kind == "SEARCH_TERM_MAPPING" and self.q.accepted(i):
                matches = matching_terms(text_fields, i.claim.value["terms"])
                if matches:
                    vocab.append((i, matches))
            elif (
                i.claim.kind == "VOCABULARY"
                and self.q.accepted(i)
                and isinstance(i.claim.value, dict)
            ):
                if any(p.originating_field.startswith("raw_source.") for p in i.provenance):
                    matches = matching_terms(text_fields, [i.claim.value["term"]])
                    if matches:
                        vocab.append((i, matches))
        conflict = (
            len(categories) > 1 or len(contexts) > 1 or any(i.contradiction_count for i in items)
        )
        multi = ambiguous_merchant(merchant) or len(contexts) > 1
        tags = []
        if ambiguous_merchant(merchant):
            tags.append("EXPLICIT_MULTI_CONTEXT_POLICY")
        if any(i.claim.predicate == "possible_reversal" for i in links):
            tags.append("AMBIGUOUS_REVERSAL")
        if conflict:
            tags.append("CONFLICTING_OBSERVATIONS")
        if multi:
            tags.append("MULTI_CONTEXT_MERCHANT")
        if links:
            tags.append("RELATED_DOCUMENT_OR_RECONCILIATION")
        if recurring:
            tags.append("RECURRING_PATTERN")
        if vocab:
            tags.append("SOURCE_TEXT_MATCH")
        if history and not conflict and not multi:
            tags.append("CONSISTENT_REVIEWED_HISTORY")
        if not history and not links and not recurring:
            tags.append("UNKNOWN_PURPOSE")
        return dict(
            merchant=merchant,
            resolution=resolution,
            history=history,
            observations=observations,
            categories=categories,
            contexts=contexts,
            links=links,
            ambiguous_links=ambiguous_links,
            recurring=recurring,
            aliases=aliases,
            vocab=vocab,
            conflict=conflict,
            multi=multi,
            tags=tags,
        )

    def card(self, tx, s):
        if not eligible(tx, self.reviews):
            raise ValueError("INELIGIBLE_TRANSACTION")
        review = self.reviews.get(tx["id"])
        confirmed = review and review["review_status"] == "REVIEWED"
        current = CurrentState(
            category=review["confirmed_category"] if confirmed else None,
            context=review["confirmed_business_context"] if confirmed else None,
            review_status=review["review_status"] if review else "UNREVIEWED",
        )
        source_id = "transaction:" + tx["id"]
        source = EvidenceInput(
            id=source_id,
            authority="DETERMINISTIC_SOURCE_FACT",
            summary="Imported date, amount, description and merchant identity.",
            provenance=(
                Provenance(
                    source_type="transactions",
                    source_id=tx["id"],
                    source_hash=digest(tx),
                    originating_field="booking_date/amount/merchant/message/Selitys",
                    observed_at=self.when,
                    extraction_method="suggestion-source-v1",
                ),
            ),
        )
        evidence = {source.id: source}
        reasons = [
            Reason(
                code="EXACT_MERCHANT_IDENTITY",
                explanation=(
                    f"Imported merchant: {s['merchant']}. No purpose is inferred "
                    f"from identity alone."
                ),
                evidence_refs=(source.id,),
            )
        ]
        used = set()

        def include(item, summary):
            used.add(item.id)
            evidence[item.id] = EvidenceInput(
                id=item.id,
                authority=item.claim.authority,
                summary=summary,
                provenance=item.provenance,
            )
            return item.id

        warnings = [
            "Suggestions are not confirmed labels. Tax treatment remains a separate human decision."
        ]
        if confirmed:
            rp = Provenance(
                source_type="transaction_label_reviews",
                source_id=review["id"],
                source_hash=digest(review),
                originating_field="confirmed_category/confirmed_business_context",
                observed_at=self.when,
                extraction_method="suggestion-current-review-v1",
                confirmation_id=review["review_file_sha256"],
            )
            evidence["current_review"] = EvidenceInput(
                id="current_review",
                authority="HUMAN_CONFIRMED",
                summary="Existing confirmed fields remain authoritative.",
                provenance=(rp,),
            )
        if s["history"]:
            merchant_refs = tuple(
                include(i, "Exact merchant association for another reviewed transaction.")
                for i in s["observations"]
            )
            refs = merchant_refs + tuple(
                include(i, f"Other reviewed transaction: {i.claim.predicate} = {i.claim.value}.")
                for i in s["history"]
            )
            reasons.append(
                Reason(
                    code="MERCHANT_PREVIOUSLY_REVIEWED",
                    explanation=(
                        f"Other human-reviewed transactions: categories "
                        f"{dict(s['categories'])}; contexts {dict(s['contexts'])}."
                    ),
                    evidence_refs=refs,
                )
            )
        if s["aliases"] and s["resolution"]["method"] in {
            "ALIAS_EXACT",
            "BANK_DESCRIPTOR_ALIAS",
            "LEGAL_SUFFIX_NORMALIZED",
        }:
            refs = tuple(
                include(i, f"Known identity alias: {i.claim.value}.") for i in s["aliases"]
            )
            reasons.append(
                Reason(
                    code="EXACT_ALIAS_MATCH",
                    explanation=(
                        "Identity resolved through the shared exact alias/legal-name resolver."
                    ),
                    evidence_refs=refs,
                )
            )
        if s["recurring"]:
            refs = tuple(
                include(
                    i,
                    f"Merchant observed in {i.support_count} imported transactions; "
                    f"cadence not established.",
                )
                for i in s["recurring"]
            )
            reasons.append(
                Reason(
                    code="RECURRING_PATTERN",
                    explanation=(
                        "Repeated merchant occurrence may make review easier; it "
                        "does not establish purpose."
                    ),
                    evidence_refs=refs,
                )
            )
        for item, matches in s["vocab"]:
            ref = include(item, "Explicit source-term vocabulary or catalog mapping.")
            reasons.append(
                Reason(
                    code="SOURCE_TEXT_MATCH",
                    explanation="Source matches: "
                    + "; ".join(f"{m['term']} in {', '.join(m['fields'])}" for m in matches)
                    + ". No label is assigned from translation.",
                    evidence_refs=(source.id, ref),
                )
            )
        if s["links"]:
            for i in s["links"]:
                ref = include(i, f"{i.claim.predicate}: {i.claim.relationship_status}.")
                reasons.append(
                    Reason(
                        code="RELATED_DOCUMENT_FOUND"
                        if i.claim.predicate == "bank_allocation"
                        else "RECONCILIATION_LINK",
                        explanation=(
                            f"Existing evidence relationship: "
                            f"{i.claim.relationship_status}. "
                            "It does not establish category/context."
                        ),
                        evidence_refs=(ref,),
                    )
                )
            if s["ambiguous_links"]:
                warnings.append(
                    "Candidate or ambiguous reconciliation evidence: no category/context "
                    "recommendation is made from this card."
                )
        else:
            warnings.append(
                "No transaction-specific document or reconciliation link was found in the "
                "retained knowledge."
            )
        if s["multi"]:
            policy_refs = ()
            if ambiguous_merchant(s["merchant"]):
                path = Path("data_pipeline/labels/merchant_policy.py")
                policy = EvidenceInput(
                    id="multi_context_policy",
                    authority="DETERMINISTIC_SOURCE_FACT",
                    summary="Explicit human-review policy for ambiguous retailers.",
                    provenance=(
                        Provenance(
                            source_type="policy",
                            source_id=str(path),
                            source_hash=sha256(path.read_bytes()).hexdigest(),
                            originating_field="ambiguous_merchant",
                            observed_at=self.when,
                            extraction_method="policy-reference-v1",
                        ),
                    ),
                )
                evidence[policy.id] = policy
                policy_refs = (policy.id,)
            refs = tuple(
                include(i, "Merchant context observation for a different reviewed transaction.")
                for i in s["observations"]
            ) + policy_refs or (source.id,)
            reasons.append(
                Reason(
                    code="MULTI_CONTEXT_MERCHANT",
                    explanation=(
                        "Explicit multi-context review policy applies."
                        if ambiguous_merchant(s["merchant"])
                        else "Multiple human-confirmed contexts were observed."
                    )
                    + " Review PERSONAL, PROPERTY or FORESTRY; none is selected from "
                    "merchant identity.",
                    evidence_refs=refs,
                )
            )
            warnings.append("SUGGEST_REVIEW_CONTEXT: merchant-wide context must not be inherited.")
        if s["conflict"]:
            refs = tuple(i.id for i in s["history"]) or (source.id,)
            reasons.append(
                Reason(
                    code="CONFLICTING_OBSERVATIONS",
                    explanation=(
                        "Other observations disagree; conflicting fields are left "
                        "without a recommendation."
                    ),
                    evidence_refs=refs,
                )
            )
            warnings.append(
                "Conflicting observations are retained; no majority vote or confidence "
                "percentage is used."
            )
        category = next(iter(s["categories"])) if len(s["categories"]) == 1 else None
        context = next(iter(s["contexts"])) if len(s["contexts"]) == 1 and not s["multi"] else None
        if current.category not in (None, "UNKNOWN"):
            category = None
        if current.context not in (None, "UNKNOWN"):
            context = None
        if s["ambiguous_links"]:
            category = context = None
        if s["conflict"] or s["multi"] or s["ambiguous_links"]:
            priority = "AMBIGUOUS_REVIEW"
        elif len(s["observations"]) >= 2 or s["links"]:
            priority = "HIGH_REVIEW_VALUE"
        elif s["history"] or s["vocab"] or s["recurring"]:
            priority = "MEDIUM_REVIEW_VALUE"
        else:
            priority = "LOW_REVIEW_VALUE"
        if category is None and context is None:
            warnings.append(
                "No supported label suggestion is available; reviewing evidence or "
                "skipping is appropriate."
            )
        card_id = digest(
            {
                "transaction": tx,
                "knowledge": self.snapshot.events_hash,
                "rule": "DETERMINISTIC_CARDS_V1",
            }
        )[:32]
        return Card(
            card_id=card_id,
            transaction=TransactionView(
                id=tx["id"],
                date=tx["booking_date"],
                amount=tx["amount"],
                currency=tx["currency"],
                merchant=s["merchant"],
                description=(tx.get("raw_source") or {}).get("Selitys") or tx.get("message"),
            ),
            current_state=current,
            suggestion=Suggestion(category=category, context=context),
            reasons=tuple(reasons),
            evidence=tuple(evidence.values()),
            knowledge_used=tuple(sorted(used)),
            warnings=tuple(warnings),
            priority=priority,
            conflicting_knowledge=s["conflict"],
            selection_tags=tuple(s["tags"]),
        )

    def sample(self, size=16):
        if not 10 <= size <= 20:
            raise ValueError("SAMPLE_SIZE_MUST_BE_10_TO_20")
        candidates = [
            (t, self.signals(t))
            for t in sorted(self.txs.values(), key=lambda t: (t["booking_date"], t["id"]))
            if eligible(t, self.reviews)
        ]
        chosen = []
        tags = (
            "EXPLICIT_MULTI_CONTEXT_POLICY",
            "AMBIGUOUS_REVERSAL",
            "MULTI_CONTEXT_MERCHANT",
            "CONFLICTING_OBSERVATIONS",
            "RELATED_DOCUMENT_OR_RECONCILIATION",
            "CONSISTENT_REVIEWED_HISTORY",
            "SOURCE_TEXT_MATCH",
            "RECURRING_PATTERN",
            "UNKNOWN_PURPOSE",
        )
        for tag in tags:
            match = next(
                (pair for pair in candidates if tag in pair[1]["tags"] and pair not in chosen), None
            )
            if match:
                chosen.append(match)
        for pair in candidates:
            if len(chosen) >= size:
                break
            if pair not in chosen and pair[1]["merchant"] not in {s["merchant"] for _, s in chosen}:
                chosen.append(pair)
        for pair in candidates:
            if len(chosen) >= size:
                break
            if pair not in chosen:
                chosen.append(pair)
        return [self.card(t, s) for t, s in chosen[:size]]
