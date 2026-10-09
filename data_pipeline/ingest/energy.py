"""Import an inspected Finnish electricity CSV with explicit meter identity."""

import argparse
import json
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from apps.api.app.core.database import SessionLocal
from data_pipeline.ingest.energy_csv import PARSER_VERSION, SOURCE_TYPE, canonical_energy
from data_pipeline.load.energy import import_energy_bytes
from data_pipeline.normalize.energy import EnergyInputError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--metering-point", required=True)
    args = parser.parse_args(argv)
    try:
        raw = args.file.read_bytes()
        result = import_energy_bytes(
            raw,
            source_filename=args.file.name,
            metering_point=args.metering_point,
            source_type=SOURCE_TYPE,
            parser_version=PARSER_VERSION,
            normalize=canonical_energy,
            session_factory=SessionLocal,
        )
    except OSError:
        print(json.dumps({"status": "failed", "error_code": "source_file_unreadable"}))
        return 1
    except EnergyInputError as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc)}))
        return 1
    except SQLAlchemyError:
        print(
            json.dumps({"status": "failed", "error_code": "database_unavailable_or_commit_failed"})
        )
        return 1
    print(result.model_dump_json())
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
