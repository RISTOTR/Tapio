"""Read-only bank verification: safe aggregates; optional ignored private diagnostics."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.database import SessionLocal
from apps.api.app.domain.models import Transaction
from data_pipeline.ingest.bank_csv import SOURCE_TYPE
from data_pipeline.normalize.bank_analysis import (
    classification_features,
    duplicate_payment_candidates,
    recurring_candidates,
    reversal_candidates,
)


def read_transactions(session: Session, account_key: str) -> pl.DataFrame:
    transactions = session.scalars(
        select(Transaction)
        .where(Transaction.source_namespace == f"{SOURCE_TYPE}:{account_key}")
        .order_by(Transaction.booking_date, Transaction.source_transaction_id)
    ).all()
    if not transactions:
        raise ValueError("No imported transactions for this account namespace")
    fields = [
        "booking_date",
        "value_date",
        "amount",
        "currency",
        "raw_counterparty",
        "normalized_counterparty",
        "payment_intermediary",
        "ultimate_recipient",
        "reference",
        "message",
        "transaction_type_code",
        "source_file",
        "category",
        "source_namespace",
        "source_transaction_id",
    ]
    return pl.DataFrame(
        [
            {
                **{key: getattr(row, key) for key in fields},
                "direction": row.direction.value,
                "business_context": row.business_context.value
                if row.business_context
                else "unknown",
            }
            for row in transactions
        ],
        schema_overrides={
            "amount": pl.Decimal(20, 6),
            **{
                key: pl.String
                for key in [
                    "raw_counterparty",
                    "normalized_counterparty",
                    "payment_intermediary",
                    "ultimate_recipient",
                    "reference",
                    "message",
                    "transaction_type_code",
                    "category",
                ]
            },
        },
    )


def aggregate_checks(frame: pl.DataFrame) -> dict:
    rows = frame.to_dicts()
    by_year = []
    for year in sorted({r["booking_date"].year for r in rows}):
        group = [r for r in rows if r["booking_date"].year == year]
        by_year.append(
            {
                "year": year,
                "count": len(group),
                "first_date": min(r["booking_date"] for r in group),
                "last_date": max(r["booking_date"] for r in group),
                "debits": sum(r["amount"] < 0 for r in group),
                "credits": sum(r["amount"] > 0 for r in group),
            }
        )
    forestry = [r for r in rows if r["business_context"] == "forestry"]
    property_totals = []
    for name in ["Vattenfall Oy", "Elenia Verkko Oyj"]:
        group = [r for r in rows if r["normalized_counterparty"] == name]
        if group:
            property_totals.append(
                {
                    "counterparty": name,
                    "count": len(group),
                    "debit_count": sum(r["amount"] < 0 for r in group),
                    "total_debits_eur": sum(
                        (-r["amount"] for r in group if r["amount"] < 0), Decimal(0)
                    ),
                    "first_date": min(r["booking_date"] for r in group),
                    "last_date": max(r["booking_date"] for r in group),
                }
            )
    recurring = recurring_candidates(frame)
    refunds = reversal_candidates(frame)
    duplicates = duplicate_payment_candidates(frame)
    known = [
        "Vattenfall Oy",
        "Elenia Verkko Oyj",
        "Metsänhoitoyhdistys Keski-Suomi",
        "Stora Enso Oyj",
        "Verohallinto",
        "Paytrail Oyj",
    ]
    return {
        "rows": frame.height,
        "years": by_year,
        "known_counterparty_counts": {
            n: sum(r["normalized_counterparty"] == n for r in rows) for n in known
        },
        "paytrail_count": sum(r["payment_intermediary"] == "Paytrail Oyj" for r in rows),
        "paytrail_with_explicit_recipient": sum(
            r["payment_intermediary"] == "Paytrail Oyj" and r["ultimate_recipient"] is not None
            for r in rows
        ),
        "forestry_suggestions": {
            "count": len(forestry),
            "total_credits_eur": sum(
                (r["amount"] for r in forestry if r["amount"] > 0), Decimal(0)
            ),
            "total_debits_eur": sum(
                (-r["amount"] for r in forestry if r["amount"] < 0), Decimal(0)
            ),
            "counterparties": sorted({r["normalized_counterparty"] for r in forestry}),
            "category_unknown_count": sum(r["category"] == "unknown" for r in forestry),
            "tax_treatment": "not assessed; human review required",
        },
        "unassigned_business_context_count": sum(r["business_context"] == "unknown" for r in rows),
        "property_energy": property_totals,
        "recurring_candidate_groups": len(recurring),
        "recurring_property_counterparties": [
            r["counterparty"] for r in recurring if r["counterparty"] in known[:2]
        ],
        "refund_candidate_pairs": len(refunds),
        "refund_candidate_distinct_credits": len({r["credit_id"] for r in refunds}),
        "refund_credits_with_multiple_possible_debits": len(
            {r["credit_id"] for r in refunds if r["matching_debit_count"] > 1}
        ),
        "duplicate_payment_candidate_pairs": len(duplicates),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-key", required=True)
    parser.add_argument(
        "--private-output",
        action="store_true",
        help="Write only under ignored data/processed/bank/",
    )
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        frame = read_transactions(session, args.account_key)
    summary = aggregate_checks(frame)
    if args.private_output:
        # Fixed ignored root; no arbitrary output path for sensitive diagnostics.
        path = Path(__file__).resolve().parents[1] / "data/processed/bank"
        path.mkdir(parents=True, exist_ok=True)
        for name, data in [
            ("aggregate", summary),
            ("recurring", recurring_candidates(frame)),
            ("refund_candidates", reversal_candidates(frame)),
            ("duplicate_payment_candidates", duplicate_payment_candidates(frame)),
        ]:
            (path / f"{name}.json").write_text(json.dumps(data, default=str, indent=2) + "\n")
        classification_features(frame).write_csv(path / "classification_features.csv")
    print(json.dumps(summary, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
