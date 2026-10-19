"""Private append-only question/feedback files; never source-data writes."""

import json
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean, median
from uuid import UUID, uuid4

from data_pipeline.labels.snapshot import freeze
from tapio.pilot.contracts import Feedback


def private_text(value):
    value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[credential removed]", value)
    value = re.sub(r"\bya29\.[A-Za-z0-9._-]+", "[credential removed]", value)
    return re.sub(r"\b1//[A-Za-z0-9_-]+", "[credential removed]", value)


class History:
    def __init__(self, root):
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("PRIVATE_HISTORY_SYMLINK")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def directory(self, session_id):
        if str(UUID(session_id)) != session_id:
            raise ValueError("INVALID_SESSION")
        directory = self.root / session_id
        if directory.is_symlink():
            raise ValueError("PRIVATE_HISTORY_SYMLINK")
        return directory

    def save(self, session_id, payload):
        # No model prompts, full documents, API keys or OAuth credentials belong here.
        freeze(
            self.directory(session_id) / "question.json",
            json.loads(private_text(json.dumps(payload))),
        )

    def feedback(self, session_id, feedback):
        feedback = Feedback.model_validate(feedback)
        directory = self.directory(session_id)
        if not (directory / "question.json").is_file():
            raise FileNotFoundError("UNKNOWN_SESSION")
        freeze(
            directory / "feedback" / f"{uuid4()}.json",
            {
                "timestamp": datetime.now(UTC).isoformat(),
                **feedback.model_dump(),
                "note": private_text(feedback.note),
            },
        )

    def metrics(self):
        records = [json.loads(p.read_text()) for p in self.root.glob("*/question.json")]
        sessions = [r["response"]["session"] for r in records]
        latencies = [s["latency_seconds"] for s in sessions]
        feedback = Counter()
        for r in records:
            paths = sorted(
                (self.directory(r["response"]["session"]["id"]) / "feedback").glob("*.json")
            )
            items = [json.loads(p.read_text()) for p in paths]
            if items:
                feedback[max(items, key=lambda x: x["timestamp"])["rating"]] += 1
        return {
            "questions_asked": len(records),
            "mean_latency_seconds": mean(latencies) if latencies else None,
            "median_latency_seconds": median(latencies) if latencies else None,
            "tokens": {
                k: sum(s[k] for s in sessions)
                for k in ("input_tokens", "cached_input_tokens", "output_tokens")
            },
            "model_calls": sum(s["model_calls"] for s in sessions),
            "questions_with_incomplete_usage": sum(
                not s.get("usage_complete", True) for s in sessions
            ),
            "total_estimated_cost_usd": str(
                sum((Decimal(s["estimated_cost_usd"]) for s in sessions), Decimal(0))
            ),
            "feedback_distribution": dict(feedback),
            "evidence_state_distribution": dict(
                Counter(r["response"]["evidence_state"] for r in records)
            ),
        }
