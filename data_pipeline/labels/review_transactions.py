"""Generate a private blank human-review CSV; refuse to replace existing files."""

import argparse
import json
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from apps.api.app.core.database import SessionLocal
from data_pipeline.labels.workflow import prepare_queue

PRIVATE_ROOT = Path(__file__).resolve().parents[2] / "data/processed/bank"


def output_path(name: str) -> Path:
    if Path(name).name != name or not name.endswith(".csv"):
        raise ValueError("Output must be a CSV basename inside data/processed/bank")
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
    return PRIVATE_ROOT / name


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-key", required=True)
    parser.add_argument("--output-name", default="review_queue.csv")
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    try:
        path = output_path(args.output_name)
        if path.exists():
            raise FileExistsError
        raw, report = prepare_queue(
            SessionLocal, args.account_key, target=args.size, seed=args.seed
        )
        with path.open("xb") as file:
            file.write(raw)
    except FileExistsError:
        print(json.dumps({"status": "failed", "error_code": "output_exists_choose_new_name"}))
        return 1
    except (ValueError, OSError, SQLAlchemyError):
        print(json.dumps({"status": "failed", "error_code": "queue_generation_failed"}))
        return 1
    print(json.dumps({"status": "awaiting_human_review", "path": str(path), **report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
