"""Explicit correction-aware projection; original events/history are never rewritten."""

from tapio.knowledge.models import Claim, KnowledgeEvent
from tapio.knowledge.store import rebuild


def replay_confirmations(base_events, revisions, merchant_by_tx):
    active = {}
    chains = {}
    for row in sorted(revisions, key=lambda r: (str(r["transaction_id"]), r["sequence"])):
        tx = str(row["transaction_id"])
        previous = chains.get(tx)
        if row["sequence"] != (previous["sequence"] + 1 if previous else 1):
            raise ValueError("REVISION_SEQUENCE_GAP")
        if str(row["previous_id"] or "") != str(previous["id"] if previous else ""):
            raise ValueError("REVISION_CHAIN_MISMATCH")
        event = KnowledgeEvent.model_validate(row["knowledge_event"])
        if event.event_type != "HUMAN_REVIEW_CONFIRMED":
            raise ValueError("NOT_A_CONFIRMATION_EVENT")
        for claim in event.claims:
            if (
                claim.subject != tx
                or claim.provenance.confirmation_id != str(row["id"])
                or claim.authority != "HUMAN_CONFIRMED"
            ):
                raise ValueError("INVALID_CONFIRMATION_PROVENANCE")
            active[(tx, claim.predicate)] = claim
        chains[tx] = row
    events = []
    context_txs = {tx for tx, p in active if p == "confirmed_business_context"}
    for event in base_events:
        claims = tuple(
            c
            for c in event.claims
            if (c.subject, c.predicate) not in active
            and not (c.kind == "MERCHANT_OBSERVATION" and c.scope in context_txs)
        )
        if claims:
            events.append(event.model_copy(update={"claims": claims}))
    for (tx, predicate), claim in sorted(active.items()):
        claims = [claim]
        if predicate == "confirmed_business_context" and merchant_by_tx.get(tx):
            claims.append(
                Claim(
                    kind="MERCHANT_OBSERVATION",
                    subject=merchant_by_tx[tx],
                    predicate="reviewed_context_observation",
                    value=claim.value,
                    scope=tx,
                    authority="HUMAN_CONFIRMED",
                    provenance=claim.provenance,
                    single_valued=True,
                )
            )
        events.append(KnowledgeEvent(event_type="HUMAN_REVIEW_CONFIRMED", claims=tuple(claims)))
    return rebuild(events), events
