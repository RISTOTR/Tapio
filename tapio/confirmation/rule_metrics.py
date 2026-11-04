"""Read-only repeated-teaching audit over the bounded queue's frozen windows."""

import json

from tapio.knowledge.models import digest
from tapio.knowledge.user_rules import explanations, friction_metrics


def metrics(queue, revisions, transactions):
    sources = {t["id"]: t for t in transactions}
    cards = {}
    for window, metadata in queue.manifest()["windows"].items():
        batch = json.loads((queue.root / "windows" / window / "preview.json").read_text())
        if digest(batch) != metadata["batch_digest"]:
            raise ValueError("WINDOW_INTEGRITY")
        for c in batch["cards"]:
            txid = c["transaction"]["id"]
            cards[txid] = {
                **c,
                "created_at": batch["created_at"],
                "rule_version": batch.get("rule_version"),
                "source_transaction": sources[txid],
            }
    return friction_metrics(explanations(revisions, transactions), queue.rules.events(), cards)
