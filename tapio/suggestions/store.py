"""Immutable batches and append-only feedback, independent of source/knowledge stores."""

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tapio.knowledge.models import canonical, digest
from tapio.pilot.history import private_text
from tapio.suggestions.models import Card, FeedbackInput


class Store:
    def __init__(self, root: Path):
        self.root = root

    def batch(self):
        data = json.loads((self.root / "batch.json").read_text())
        cards = [Card.model_validate(c) for c in data["cards"]]
        if digest(data["cards"]) != data["cards_hash"]:
            raise ValueError("BATCH_HASH_MISMATCH")
        if not 10 <= len(cards) <= 20:
            raise ValueError("INVALID_BATCH_SIZE")
        return data, cards

    def save_batch(self, cards, provenance):
        if not 10 <= len(cards) <= 20:
            raise ValueError("INVALID_BATCH_SIZE")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        rows = [c.model_dump(mode="json") for c in cards]
        data = {"cards": rows, "cards_hash": digest(rows), "provenance": provenance}
        path = self.root / "batch.json"
        content = canonical(data)
        if path.exists():
            if path.read_text() != content:
                raise ValueError("EXISTING_BATCH_CANNOT_BE_REPLACED")
        else:
            with path.open("x") as f:
                path.chmod(0o600)
                f.write(content)

    def feedback(self, card_id: str, feedback: FeedbackInput):
        data, cards = self.batch()
        card = next((c for c in cards if c.card_id == card_id), None)
        if card is None:
            raise KeyError("UNKNOWN_CARD")
        directory = self.root / "feedback"
        directory.mkdir(mode=0o700, exist_ok=True)
        record = {
            "card_id": card_id,
            "transaction_reference": card.transaction.id,
            "suggestion_snapshot": card.suggestion.model_dump(mode="json"),
            "card_hash": digest(card),
            "batch_hash": data["cards_hash"],
            **feedback.model_dump(),
            "note": private_text(feedback.note),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        path = directory / (str(uuid4()) + ".json")
        with path.open("x") as f:
            path.chmod(0o600)
            f.write(canonical(record))

    def latest(self):
        data, cards = self.batch()
        valid = {c.card_id for c in cards}
        latest = {}
        for path in sorted((self.root / "feedback").glob("*.json")):
            r = json.loads(path.read_text())
            if r["batch_hash"] != data["cards_hash"] or r["card_id"] not in valid:
                continue
            if r["card_id"] not in latest or r["timestamp"] > latest[r["card_id"]]["timestamp"]:
                latest[r["card_id"]] = r
        return latest

    def public_batch(self):
        _, cards = self.batch()
        latest = self.latest()
        result = []
        for card in cards:
            result.append(
                {
                    "card_id": card.card_id,
                    "transaction": card.transaction.model_dump(exclude={"id"}),
                    "current_state": card.current_state.model_dump(),
                    "suggestion": card.suggestion.model_dump(),
                    "reasons": [
                        {"code": r.code, "explanation": r.explanation} for r in card.reasons
                    ],
                    "evidence": [
                        {"summary": e.summary, "authority": e.authority} for e in card.evidence
                    ],
                    "warnings": card.warnings,
                    "priority": card.priority,
                    "suggestion_status": card.suggestion_status,
                    "feedback": latest.get(card.card_id, {}).get("choice"),
                }
            )
        return result

    def metrics(self):
        _, cards = self.batch()
        latest = self.latest()
        groups = {
            k: defaultdict(Counter)
            for k in ("priority", "reason", "merchant", "evidence_authority", "availability")
        }
        counts = Counter()
        for c in cards:
            if c.card_id not in latest:
                continue
            choice = latest[c.card_id]["choice"]
            counts[choice] += 1
            keys = {
                "priority": [c.priority],
                "reason": sorted({r.code for r in c.reasons}),
                "merchant": [c.transaction.merchant],
                "evidence_authority": sorted({e.authority for e in c.evidence}),
                "availability": [
                    f"category={'yes' if c.suggestion.category else 'no'},"
                    f"context={'yes' if c.suggestion.context else 'no'}"
                ],
            }
            for dimension, values in keys.items():
                for value in values:
                    groups[dimension][value][choice] += 1
        return {
            "cards_available": len(cards),
            "cards_reviewed": len(latest),
            "feedback_counts": {
                k: counts[k]
                for k in ("CORRECT", "PARTIALLY_USEFUL", "WRONG", "INSUFFICIENT_EVIDENCE", "SKIP")
            },
            "by_dimension": {
                k: {v: dict(n) for v, n in values.items()} for k, values in groups.items()
            },
            "basis": "Latest explicit feedback per card; overlapping reason/authority "
            "groups. Usefulness feedback, not accuracy.",
        }
