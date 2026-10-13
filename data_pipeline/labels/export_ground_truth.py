"""Export human-reviewed records only and report rule agreement, never model accuracy."""

import argparse
import json

from apps.api.app.core.database import SessionLocal
from data_pipeline.labels.review_transactions import output_path
from data_pipeline.labels.workflow import ground_truth, quality_report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-key", required=True)
    parser.add_argument("--output-name", default="ground_truth.csv")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        report = quality_report(session, args.account_key)
        frame = ground_truth(session, args.account_key)
    if not args.report_only:
        try:
            with output_path(args.output_name).open("x", encoding="utf-8", newline="") as file:
                frame.write_csv(file)
        except FileExistsError:
            print(json.dumps({"error_code": "output_exists_choose_new_name"}))
            return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
