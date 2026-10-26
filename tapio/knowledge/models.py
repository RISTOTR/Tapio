"""Provider-neutral evidence and event contracts."""

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class Authority(StrEnum):
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    DETERMINISTIC_SOURCE_FACT = "DETERMINISTIC_SOURCE_FACT"
    SUGGESTED = "SUGGESTED"
    UNKNOWN = "UNKNOWN"


class Kind(StrEnum):
    ENTITY = "ENTITY"
    ENTITY_ALIAS = "ENTITY_ALIAS"
    VOCABULARY = "VOCABULARY"
    SOURCE_FIELD_MEANING = "SOURCE_FIELD_MEANING"
    MERCHANT_OBSERVATION = "MERCHANT_OBSERVATION"
    DOCUMENT_FACT = "DOCUMENT_FACT"
    CONTRACT_FACT = "CONTRACT_FACT"
    RELATIONSHIP = "RELATIONSHIP"
    RECURRING_PATTERN = "RECURRING_PATTERN"
    SEARCH_TERM_MAPPING = "SEARCH_TERM_MAPPING"


class RelationshipStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANDIDATE = "CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    REJECTED = "REJECTED"


class EventType(StrEnum):
    SOURCE_PARSED = "SOURCE_PARSED"
    HUMAN_REVIEW_CONFIRMED = "HUMAN_REVIEW_CONFIRMED"
    DOCUMENT_REVIEWED = "DOCUMENT_REVIEWED"
    ALIAS_DISCOVERED = "ALIAS_DISCOVERED"
    RELATIONSHIP_CONFIRMED = "RELATIONSHIP_CONFIRMED"
    VOCABULARY_CONFIRMED = "VOCABULARY_CONFIRMED"


class Typed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provenance(Typed):
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    originating_field: str = Field(min_length=1)
    observed_at: datetime
    extraction_method: str = Field(min_length=1)
    confirmation_id: str | None = None


class Claim(Typed):
    kind: Kind
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    value: JsonValue
    scope: str = ""
    authority: Authority
    provenance: Provenance
    relationship_status: RelationshipStatus | None = None
    # Multi-valued observations never become single-valued merchant rules.
    single_valued: bool = False

    @model_validator(mode="after")
    def authority_boundary(self):
        if self.authority == Authority.HUMAN_CONFIRMED and not self.provenance.confirmation_id:
            raise ValueError("HUMAN_CONFIRMATION_PROVENANCE_REQUIRED")
        if self.kind == Kind.RELATIONSHIP and self.relationship_status is None:
            raise ValueError("RELATIONSHIP_STATUS_REQUIRED")
        if self.authority in (Authority.SUGGESTED, Authority.UNKNOWN):
            if self.relationship_status == RelationshipStatus.CONFIRMED:
                raise ValueError("SUGGESTION_CANNOT_CONFIRM_RELATIONSHIP")
        if (
            self.kind == Kind.MERCHANT_OBSERVATION
            and self.predicate != "reviewed_context_observation"
        ):
            raise ValueError("MERCHANT_OBSERVATIONS_ARE_NOT_CLASSIFICATION_RULES")
        return self


class KnowledgeEvent(Typed):
    event_type: EventType
    claims: tuple[Claim, ...] = Field(min_length=1)


class KnowledgeItem(Typed):
    id: str
    claim: Claim
    provenance: tuple[Provenance, ...]
    first_seen: datetime
    last_seen: datetime
    support_count: int = Field(ge=1)
    contradiction_count: int = Field(ge=0)
    human_confirmation_status: str


class Contradiction(Typed):
    claim_ids: tuple[str, ...]
    status: str = "UNRESOLVED"
    preferred_claim_ids: tuple[str, ...] = ()


class Snapshot(Typed):
    version: str = "KNOWLEDGE_V1"
    events_hash: str
    items: tuple[KnowledgeItem, ...]
    contradictions: tuple[Contradiction, ...]


def canonical(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()
