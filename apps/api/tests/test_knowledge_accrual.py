"""Authority, provenance, replay and safe reuse without external services."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tapio.knowledge.backfill import accrue, reviewed_email_events
from tapio.knowledge.models import Authority, Claim, KnowledgeEvent, Provenance, canonical
from tapio.knowledge.queries import KnowledgeQueries
from tapio.knowledge.store import load_bundle, rebuild, save_bundle

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def claim(value="example", **updates):
    data = dict(
        kind="ENTITY",
        subject="Example",
        predicate="name",
        value=value,
        authority="DETERMINISTIC_SOURCE_FACT",
        single_valued=True,
        provenance=Provenance(
            source_type="synthetic",
            source_id="source-1",
            source_hash="a" * 64,
            originating_field="name",
            observed_at=NOW,
            extraction_method="test-v1",
        ),
    )
    data.update(updates)
    return Claim(**data)


def event(c):
    return KnowledgeEvent(event_type="SOURCE_PARSED", claims=(c,))


def test_provenance_required():
    with pytest.raises(ValidationError):
        Claim(kind="ENTITY", subject="X", predicate="name", value="x", authority="SUGGESTED")


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_hash", "bad"),
        ("source_id", ""),
        ("originating_field", ""),
        ("extraction_method", ""),
    ],
)
def test_invalid_provenance(field, value):
    data = claim().provenance.model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        Provenance(**data)


def test_human_authority_requires_confirmation():
    with pytest.raises(ValidationError, match="HUMAN_CONFIRMATION"):
        claim(authority="HUMAN_CONFIRMED")


@pytest.mark.parametrize("authority", list(Authority))
def test_authority_preserved(authority):
    p = claim().provenance.model_copy(update={"confirmation_id": "review-1"})
    c = claim(authority=authority, provenance=p)
    assert rebuild([event(c)]).items[0].claim.authority == authority


def test_replay_order_idempotent_and_persistent(tmp_path):
    events = [event(claim("first")), event(claim("second"))]
    s = save_bundle(tmp_path, events)
    assert rebuild(events[::-1]) == s == rebuild(events + events)
    assert load_bundle(tmp_path / ("snapshot-" + s.events_hash + ".json")) == s
    assert save_bundle(tmp_path, events) == s


def test_support_not_inflated_but_last_seen_advances():
    a = claim()
    b = a.model_copy(
        update={
            "provenance": a.provenance.model_copy(update={"observed_at": NOW + timedelta(days=1)})
        }
    )
    s = rebuild([event(a), event(b)])
    assert s.items[0].support_count == 1
    assert s.items[0].first_seen == NOW and s.items[0].last_seen == NOW + timedelta(days=1)


def test_contradiction_history_and_human_preference():
    a = claim("candidate", authority="SUGGESTED")
    b = claim(
        "reviewed",
        authority="HUMAN_CONFIRMED",
        provenance=a.provenance.model_copy(
            update={"source_id": "human-review", "confirmation_id": "review-1"}
        ),
    )
    s = rebuild([event(a), event(b)])
    assert len(s.items) == 2 and len(s.contradictions) == 1
    assert all(i.contradiction_count == 1 for i in s.items)
    q = KnowledgeQueries(s)
    assert [i.claim.value for i in s.items if q.accepted(i)] == ["reviewed"]


def test_equal_authority_conflict_not_arbitrarily_selected():
    s = rebuild([event(claim("first")), event(claim("second"))])
    assert s.contradictions[0].status == "UNRESOLVED"
    assert not any(KnowledgeQueries(s).accepted(i) for i in s.items)


@pytest.mark.parametrize("status", ["CONFIRMED", "CANDIDATE", "AMBIGUOUS", "REJECTED"])
def test_relationship_status(status):
    c = claim(kind="RELATIONSHIP", relationship_status=status)
    assert rebuild([event(c)]).items[0].claim.relationship_status == status


def test_suggested_relationship_cannot_confirm():
    with pytest.raises(ValidationError, match="SUGGESTION_CANNOT_CONFIRM"):
        claim(kind="RELATIONSHIP", authority="SUGGESTED", relationship_status="CONFIRMED")


def test_alias_reuse_with_provenance_and_no_suggestion_promotion():
    a = claim("Example Alias", kind="ENTITY_ALIAS", predicate="accepted_alias")
    b = claim(
        "Guessed Alias", kind="ENTITY_ALIAS", predicate="candidate_alias", authority="SUGGESTED"
    )
    q = KnowledgeQueries(rebuild([event(a), event(b)]))
    result = q.prepare_search("Example Alias")
    assert result.plan.terms == ["Example Alias", "Example"]
    assert result.influences[0].knowledge_id
    assert q.prepare_search("Guessed Alias").plan.terms == ["Guessed Alias"]


def test_ambiguous_alias_cannot_mix_entities():
    a = claim("same", kind="ENTITY_ALIAS")
    b = claim("same", kind="ENTITY_ALIAS", subject="Different")
    q = KnowledgeQueries(rebuild([event(a), event(b)]))
    with pytest.raises(ValueError, match="ALIAS_AMBIGUOUS"):
        q.prepare_search("same")


def test_source_field_vocabulary_and_no_source_mutation():
    tables = {
        "transactions": [
            {
                "id": "t1",
                "raw_counterparty": "Example",
                "normalized_counterparty": "Example",
                "raw_source": {"Selitys": "TALLETUSKORKO", "NewUnknownColumn": "private-value"},
            }
        ]
    }
    before = canonical(tables)
    q = KnowledgeQueries(rebuild(accrue(tables, observed_at=NOW)))
    assert canonical(tables) == before
    assert q.get_known_vocabulary("talletuskorko")[0].claim.value["concept"] is None
    assert q.get_known_vocabulary("talletuskorko")[0].claim.value["language"] == "fi"
    assert "raw_source.Selitys" in {i.claim.subject for i in q.get_searchable_fields()}
    unknown = q.get_entity_knowledge("raw_source.NewUnknownColumn")
    assert unknown[0].claim.authority == "UNKNOWN"
    assert "private-value" not in canonical(q.snapshot)
    assert set(q.prepare_search("farmacia").plan.terms) == {"pharmacy", "apteekki", "farmacia"}


def test_merchant_observation_never_becomes_rule():
    sources = []
    for i, context in enumerate(["FORESTRY", "FORESTRY", "PERSONAL"]):
        sources.append(
            event(
                claim(
                    context,
                    kind="MERCHANT_OBSERVATION",
                    predicate="reviewed_context_observation",
                    scope=str(i),
                    authority="HUMAN_CONFIRMED",
                    provenance=claim().provenance.model_copy(
                        update={"source_id": str(i), "confirmation_id": str(i)}
                    ),
                )
            )
        )
    result = KnowledgeQueries(rebuild(sources)).get_merchant_observations("Example")
    assert result["contexts"] == {"FORESTRY": 2, "PERSONAL": 1}
    assert result["status"] == "MULTI_CONTEXT_OBSERVED" and result["classification_rule"] is None
    with pytest.raises(ValidationError, match="NOT_CLASSIFICATION_RULES"):
        claim(kind="MERCHANT_OBSERVATION", predicate="always_forestry")


def test_email_source_fact_without_raw_body(tmp_path):
    p = tmp_path / "email.json"
    p.write_text(
        json.dumps(
            {
                "accepted_at": NOW.isoformat(),
                "import_status": "BODY_EVIDENCE",
                "external_message_id": "synthetic-mail",
                "content_hash": "a" * 64,
                "sender": "Example <mail@example.invalid>",
                "body": "DO_NOT_PERSIST",
                "accepted_fields": {
                    "new_contract.product": "Example Product",
                    "arbitrary_secret": "DO_NOT_PERSIST",
                },
            }
        )
    )
    result = rebuild(reviewed_email_events(p))
    assert "DO_NOT_PERSIST" not in canonical(result)
    assert any(i.claim.value == "example.invalid" for i in result.items)
    assert all(i.claim.authority == "DETERMINISTIC_SOURCE_FACT" for i in result.items)


def test_tampered_bundle_rejected(tmp_path):
    snapshot = save_bundle(tmp_path, [event(claim())])
    p = tmp_path / ("snapshot-" + snapshot.events_hash + ".json")
    data = json.loads(p.read_text())
    data["items"][0]["support_count"] = 99
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="REPLAY_MISMATCH"):
        load_bundle(p)


def test_single_occurrence_is_not_recurring():
    tables = {"transactions": [{"id": "t1", "normalized_counterparty": "Example"}]}
    assert not any(
        i.claim.kind == "RECURRING_PATTERN" for i in rebuild(accrue(tables, observed_at=NOW)).items
    )


def test_unknown_context_does_not_invent_multi_context():
    cs = [
        event(
            claim(
                v,
                kind="MERCHANT_OBSERVATION",
                predicate="reviewed_context_observation",
                scope=str(i),
                authority="HUMAN_CONFIRMED",
                provenance=claim().provenance.model_copy(update={"confirmation_id": "review"}),
            )
        )
        for i, v in enumerate(["PERSONAL", "UNKNOWN"])
    ]
    result = KnowledgeQueries(rebuild(cs)).get_merchant_observations("Example")
    assert result["contexts"] == {"PERSONAL": 1, "UNKNOWN": 1}
    assert result["status"] == "OBSERVATIONS_ONLY"


def test_knowledge_influenced_search_retains_trace(monkeypatch):
    import tapio.pilot.transaction_search as search
    from tapio.knowledge.queries import retrieve_with_knowledge

    q = KnowledgeQueries(rebuild([event(claim("Example Alias", kind="ENTITY_ALIAS"))]))

    def retrieve(plan, session_factory):
        assert "Example" in plan.terms
        return {
            "plan": plan.model_dump(mode="json"),
            "items": [],
            "searched_fields": ["raw_merchant"],
        }

    monkeypatch.setattr(search, "retrieve_search", retrieve)
    evidence = retrieve_with_knowledge("Example Alias", q, None)
    assert evidence["knowledge_influences"][0]["knowledge_id"] == q.snapshot.items[0].id
    assert evidence["knowledge_events_hash"] == q.snapshot.events_hash
