"""Import one local PDF; prints only aggregate counts and safe error codes."""

import argparse
import json
import logging
from pathlib import Path

from apps.api.app.core.database import SessionLocal

from .loader import import_document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        raw = args.file.read_bytes()
    except OSError:
        print(json.dumps({"status": "failed", "error_code": "source_unreadable"}))
        return 1
    result = import_document(raw, filename=args.file.name, session_factory=SessionLocal)
    print(json.dumps(result))
    return int(result["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
