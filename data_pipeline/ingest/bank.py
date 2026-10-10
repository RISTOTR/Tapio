"""Import a Finnish bank CSV using an explicit non-sensitive account namespace."""

import argparse
import json
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from apps.api.app.core.database import SessionLocal
from data_pipeline.ingest.bank_csv import BankInputError
from data_pipeline.load.bank import import_bank_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument(
        "--account-key", required=True, help="Stable local alias, e.g. primary; no IBAN"
    )
    args = parser.parse_args(argv)
    try:
        result = import_bank_bytes(
            args.file.read_bytes(),
            source_filename=args.file.name,
            account_key=args.account_key,
            session_factory=SessionLocal,
        )
    except OSError:
        print(json.dumps({"status": "failed", "error_code": "source_file_unreadable"}))
        return 1
    except BankInputError as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc)}))
        return 1
    except SQLAlchemyError:
        print(
            json.dumps({"status": "failed", "error_code": "database_unavailable_or_commit_failed"})
        )
        return 1
    print(result.model_dump_json())
    return int(result.status == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
