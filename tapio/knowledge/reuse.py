"""Explicit, source-backed identity and vocabulary links; never label authority."""

import hashlib
import hmac
import json

from integrations.gmail.receipts import norm
from tapio.knowledge.concepts import matches
from tapio.knowledge.models import digest
from tapio.pilot.subject_identity import REGISTRY, normalize_subject


class Reuse:
    def __init__(self, data=None):
        self.data = data or {"entities": [], "vocabulary": []}
        self.entities = {}
        if any(not e.get("evidence") or not e.get("anchors") for e in self.data["vocabulary"]):
            raise ValueError("VOCABULARY_REQUIRES_EXISTING_CONCEPT_AND_EVIDENCE")
        for entry in self.data["entities"]:
            if not entry.get("evidence"):
                raise ValueError("ALIAS_REQUIRES_SOURCE_EVIDENCE")
            for name in [entry["canonical_name"], *entry["aliases"]]:
                key = normalize_subject(name)
                if not key or key in self.entities:
                    raise ValueError("CANONICAL_ALIAS_COLLISION")
                self.entities[key] = entry

    @classmethod
    def load(cls, root, tables=None):
        path = root / "reuse.json"
        if not path.exists():
            return cls()
        envelope = json.loads(path.read_text())
        data = envelope["data"]
        signature = hmac.new(
            (root / "queue.key").read_bytes(), digest(data).encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, envelope["signature"]):
            raise ValueError("REUSE_INTEGRITY")
        if tables is not None:
            indexed = {n: {r["id"]: r for r in rows} for n, rows in tables.items()}
            for entry in data["entities"] + data["vocabulary"]:
                for ref in entry["evidence"]:
                    if digest(indexed.get(ref["table"], {}).get(ref["id"])) != ref["hash"]:
                        raise ValueError("STALE_REUSE_EVIDENCE")
        return cls(data)

    def resolve(self, value):
        key = normalize_subject(value)
        entry = self.entities.get(key)
        if entry:
            return {
                "canonical_id": entry["id"],
                "canonical_name": entry["canonical_name"],
                "matched_identity": value,
                "method": "EXPLICIT_ALIAS",
                "evidence": entry["evidence"],
                "limitations": entry.get("limitations", []),
            }
        # Reuse the existing explicit registry, never fuzzy/legal-prefix matching.
        known = [
            name
            for name, item in REGISTRY.items()
            if key in {normalize_subject(a) for a in (name, *item.aliases, *item.bank_descriptors)}
        ]
        if len(known) > 1:
            raise ValueError("CANONICAL_ALIAS_COLLISION")
        canonical = known[0] if known else norm(value)
        return {
            "canonical_id": "entity:" + digest(normalize_subject(canonical))[:24],
            "canonical_name": canonical,
            "matched_identity": value,
            "method": "REGISTERED_ALIAS" if known else "NORMALIZED_EXACT",
            "evidence": [],
            "limitations": [],
        }

    def key(self, value):
        return normalize_subject(self.resolve(value)["canonical_name"])

    def vocabulary(self, concept, terms, value):
        return [
            entry
            for entry in self.data["vocabulary"]
            if entry["concept"] == concept
            and set(map(normalize_subject, terms)) & set(map(normalize_subject, entry["anchors"]))
            and matches(entry["term"], "TOKEN", value)
        ]

    def history(self, rows):
        return [
            {**r, "raw_identity_key": r["identity_key"], "identity_key": self.key(r["identity"])}
            for r in rows
        ]
