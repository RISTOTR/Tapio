"""Version-aware import parsing without changing human labels or source bytes."""

import csv
import io
from collections import Counter

from data_pipeline.labels.contracts import QUEUE_COLUMNS, ReviewError, encode_queue, parse_reviews


def parse_import(raw):
    # Imported lazily because the queue utility also uses workflow read helpers.
    from data_pipeline.labels.upgrade_review_queue import V2_COLUMNS, parse_v2

    try:
        text = raw.decode("utf-8-sig")
        candidates = []
        for delimiter in (",", ";"):
            reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
            if reader.fieldnames in (
                QUEUE_COLUMNS,
                V2_COLUMNS,
                [k for k in V2_COLUMNS if k != "review_group"],
            ):
                candidates.append((reader.fieldnames, list(reader)))
        if len(candidates) != 1:
            raise ReviewError("invalid_review_columns")
        columns, rows = candidates[0]
        if any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ReviewError("malformed_row")
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        normalized = stream.getvalue().encode("utf-8-sig")
        if columns == QUEUE_COLUMNS:
            return parse_reviews(encode_queue(rows)), "human_csv_v1"
        return parse_v2(normalized), "human_csv_v2"
    except (UnicodeError, csv.Error):
        raise ReviewError("invalid_review_csv") from None


def queue_report(rows):
    return {
        "total_queue_rows": len(rows),
        "queue_status_counts": dict(Counter(r["review_status"] for r in rows)),
        "evidence_status_counts": dict(Counter(r.get("evidence_status", "absent") for r in rows)),
        "rows_with_review_group": sum(bool(r.get("review_group")) for r in rows),
    }
