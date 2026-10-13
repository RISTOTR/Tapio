"""Validate and atomically import human labels; no automatic confirmation or replacement."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from apps.api.app.core.database import SessionLocal
from data_pipeline.labels.contracts import ReviewError
from data_pipeline.labels.review_input import parse_import, queue_report
from data_pipeline.labels.review_transactions import PRIVATE_ROOT
from data_pipeline.labels.workflow import import_reviews


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument(
        "--reviewer", required=True, help="Human reviewer name or stable local alias"
    )
    args = parser.parse_args(argv)
    try:
        raw = args.file.read_bytes()
        rows, _ = parse_import(raw)
        archive_dir = PRIVATE_ROOT / "review_imports"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive = archive_dir / f"{sha256(raw).hexdigest()}.csv"
        if archive.exists():
            if archive.read_bytes() != raw:
                raise ReviewError("archive_hash_conflict")
        else:
            with archive.open("xb") as file:
                file.write(raw)
        result = import_reviews(raw, reviewer=args.reviewer, factory=SessionLocal)
        result.update(queue_report(rows))
        result["source_archive"] = str(archive)
        result["review_file_sha256"] = sha256(raw).hexdigest()
    except ReviewError as exc:
        result = {
            "reviewed_rows_inserted": 0,
            "ambiguous_skipped": 0,
            "validation_failures": 1,
            "error_code": str(exc),
        }
        print(json.dumps(result))
        return 1
    except (OSError, SQLAlchemyError):
        print(json.dumps({"status": "failed", "error_code": "file_or_database_failure"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
