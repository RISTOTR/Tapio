"""Shared read-only CLI plumbing; detailed output stays in ignored private storage."""

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from apps.api.app.core.database import SessionLocal

from .types import CostError


def parser(description):
    result = argparse.ArgumentParser(description=description)
    result.add_argument("--start", type=date.fromisoformat, required=True)
    result.add_argument("--end", type=date.fromisoformat, required=True)
    result.add_argument("--meter-id", type=UUID)
    result.add_argument("--output", type=Path)
    return result


def output(result, path=None):
    payload = json.dumps(result, default=str, sort_keys=True, indent=2) + "\n"
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
        if "monthly" in result:
            with path.with_suffix(".csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(result["monthly"][0]))
                writer.writeheader()
                writer.writerows(result["monthly"])
    summary = {
        k: v
        for k, v in result.items()
        if k not in ("hourly", "daily", "provenance", "tariff_provenance")
    }
    if "fixed" in summary:
        summary = {k: v for k, v in summary.items() if k not in ("fixed", "spot")}
    print(json.dumps(summary, default=str, sort_keys=True, indent=2))


def run(action):
    try:
        with SessionLocal() as session:
            # This transaction is explicitly read-only, including future accidental writes.
            from sqlalchemy import text

            session.execute(text("SET TRANSACTION READ ONLY"))
            action(session)
    except (CostError, ValidationError, ValueError, OSError) as exc:
        code = str(exc) if isinstance(exc, CostError) else "INVALID_INPUT"
        print(json.dumps({"status": "ERROR", "error_code": code}))
        raise SystemExit(2) from None
