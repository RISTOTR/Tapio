"""Read-only typed knowledge queries and opt-in, traceable search preparation."""

from collections import Counter
from typing import TypedDict

from data_pipeline.labels.merchant_policy import AMBIGUOUS_REASON, ambiguous_merchant
from tapio.knowledge.fields import SOURCE_FIELDS
from tapio.knowledge.models import Authority, Kind, KnowledgeItem, Snapshot, Typed
from tapio.pilot.transaction_search import SearchPlan, normalize_text


class SearchUse(Typed):
    term: str
    knowledge_id: str
    authority: Authority


class KnowledgeSearch(Typed):
    plan: SearchPlan
    influences: tuple[SearchUse, ...]


class MerchantObservations(TypedDict):
    contexts: dict[str, int]
    status: str
    knowledge_ids: list[str]
    classification_rule: None
    review_reason: str | None


class KnowledgeQueries:
    def __init__(self, snapshot: Snapshot):
        self.snapshot = snapshot

    def _find(self, subject: str, kinds: set[Kind]) -> tuple[KnowledgeItem, ...]:
        matches = {
            i.claim.subject
            for i in self.snapshot.items
            if i.claim.kind == Kind.ENTITY_ALIAS
            and self.accepted(i)
            and isinstance(i.claim.value, str)
            and normalize_text(i.claim.value) == normalize_text(subject)
        }
        if len(matches) > 1:
            raise ValueError("KNOWLEDGE_ALIAS_AMBIGUOUS")
        subject = next(iter(matches)) if matches else subject
        return tuple(
            i
            for i in self.snapshot.items
            if i.claim.kind in kinds and normalize_text(i.claim.subject) == normalize_text(subject)
        )

    def accepted(self, item: KnowledgeItem) -> bool:
        if item.claim.authority not in {
            Authority.HUMAN_CONFIRMED,
            Authority.DETERMINISTIC_SOURCE_FACT,
        }:
            return False
        if item.claim.relationship_status and item.claim.relationship_status != "CONFIRMED":
            return False
        for c in self.snapshot.contradictions:
            if item.id in c.claim_ids and item.id not in c.preferred_claim_ids:
                return False
        return True

    def get_entity_knowledge(self, subject: str) -> tuple[KnowledgeItem, ...]:
        return self._find(subject, set(Kind))

    def get_known_aliases(self, subject: str) -> tuple[KnowledgeItem, ...]:
        return self._find(subject, {Kind.ENTITY_ALIAS})

    def get_known_vocabulary(self, concept: str) -> tuple[KnowledgeItem, ...]:
        return self._find(concept, {Kind.VOCABULARY, Kind.SEARCH_TERM_MAPPING})

    def get_merchant_observations(self, subject: str) -> MerchantObservations:
        items = self._find(subject, {Kind.MERCHANT_OBSERVATION})
        counts = Counter(str(i.claim.value) for i in items if self.accepted(i))
        return {
            "contexts": dict(sorted(counts.items())),
            "status": "MULTI_CONTEXT_OBSERVED"
            if len(set(counts) - {"UNKNOWN"}) > 1
            else "OBSERVATIONS_ONLY",
            "knowledge_ids": [i.id for i in items],
            "classification_rule": None,
            "review_reason": AMBIGUOUS_REASON if ambiguous_merchant(subject) else None,
        }

    def get_related_documents(self, subject: str) -> tuple[KnowledgeItem, ...]:
        return tuple(
            i
            for i in self.get_known_relationships(subject)
            if i.claim.predicate in {"has_document", "has_invoice", "has_contract"}
        )

    def get_known_relationships(self, subject: str) -> tuple[KnowledgeItem, ...]:
        return self._find(subject, {Kind.RELATIONSHIP})

    def get_searchable_fields(self) -> tuple[KnowledgeItem, ...]:
        # A discovered unknown field cannot activate itself via a stored suggestion.
        return tuple(
            i
            for i in self.snapshot.items
            if i.claim.kind == Kind.SOURCE_FIELD_MEANING
            and i.claim.subject in SOURCE_FIELDS
            and self.accepted(i)
            and isinstance(i.claim.value, dict)
            and i.claim.value.get("searchable") is True
        )

    def prepare_search(self, literal: str) -> KnowledgeSearch:
        terms, influences = [literal], []
        targets = {
            normalize_text(i.claim.subject)
            for i in self.snapshot.items
            if i.claim.kind == Kind.ENTITY_ALIAS
            and self.accepted(i)
            and isinstance(i.claim.value, str)
            and normalize_text(i.claim.value) == normalize_text(literal)
        }
        if len(targets) > 1:
            raise ValueError("KNOWLEDGE_ALIAS_AMBIGUOUS")
        for item in self.snapshot.items:
            c = item.claim
            if not self.accepted(item):
                continue
            additions = []
            if c.kind == Kind.ENTITY_ALIAS and isinstance(c.value, str):
                if normalize_text(literal) in {normalize_text(c.subject), normalize_text(c.value)}:
                    additions = [c.subject, c.value]
            elif c.kind == Kind.SEARCH_TERM_MAPPING and isinstance(c.value, dict):
                vocabulary = c.value.get("terms", [])
                if normalize_text(literal) in {
                    normalize_text(c.subject),
                    *(normalize_text(t) for t in vocabulary),
                }:
                    additions = vocabulary
            for term in additions:
                if normalize_text(term) not in {normalize_text(t) for t in terms}:
                    terms.append(term)
                influences.append(SearchUse(term=term, knowledge_id=item.id, authority=c.authority))
        if len(terms) > 10:
            raise ValueError("KNOWLEDGE_SEARCH_TERM_LIMIT")
        return KnowledgeSearch(
            plan=SearchPlan(intent="TRANSACTION_SEARCH", terms=terms, date_range=None),
            influences=tuple(influences),
        )


def retrieve_with_knowledge(literal: str, queries: KnowledgeQueries, session_factory) -> dict:
    """Explicit opt-in offline use. Evidence records every knowledge item influencing search."""
    from tapio.pilot.search_display import prepare
    from tapio.pilot.transaction_search import retrieve_search

    planned = queries.prepare_search(literal)
    evidence = prepare(retrieve_search(planned.plan, session_factory))
    evidence["knowledge_influences"] = [i.model_dump(mode="json") for i in planned.influences]
    evidence["source_field_knowledge_ids"] = [i.id for i in queries.get_searchable_fields()]
    evidence["knowledge_events_hash"] = queries.snapshot.events_hash
    return evidence
