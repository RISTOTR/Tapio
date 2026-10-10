"""Read-only deterministic candidates and future weak-label feature preparation."""

from calendar import monthrange
from collections import defaultdict
from decimal import Decimal
from statistics import mean

import polars as pl


def effective_counterparty(row: dict) -> str | None:
    return (
        row.get("ultimate_recipient")
        if row.get("payment_intermediary")
        else row.get("normalized_counterparty")
    )


def groups(frame: pl.DataFrame) -> dict:
    result = defaultdict(list)
    for row in frame.iter_rows(named=True):
        name = effective_counterparty(row)
        if name:
            result[(row.get("source_namespace"), name, row["currency"])].append(row)
    return result


def recurring_candidates(frame: pl.DataFrame) -> list[dict]:
    """At least three consecutive months, one debit/month, 24–38-day gaps.

    Amount variability is reported, not used to reject variable utility bills.
    Multiple monthly payments break a run; one longest qualifying run is returned.
    """
    results = []
    for (namespace, name, currency), rows in sorted(groups(frame).items(), key=lambda x: str(x[0])):
        debits = sorted((r for r in rows if r["amount"] < 0), key=lambda r: r["booking_date"])
        if len(debits) < 3:
            continue
        # Report the longest contiguous qualifying run, rather than declaring that
        # the merchant recurs over the entire history. An irregular payment breaks a run.
        best = []
        for start in range(len(debits)):
            run = [debits[start]]
            for following in debits[start + 1 :]:
                previous_date = run[-1]["booking_date"]
                current_date = following["booking_date"]
                month_gap = (
                    (current_date.year - previous_date.year) * 12
                    + current_date.month
                    - previous_date.month
                )
                if month_gap != 1 or not 24 <= (current_date - previous_date).days <= 38:
                    break
                candidate = run + [following]
                days = [r["booking_date"].day for r in candidate]
                ends = [
                    monthrange(r["booking_date"].year, r["booking_date"].month)[1]
                    - r["booking_date"].day
                    for r in candidate
                ]
                if min(max(days) - min(days), max(ends) - min(ends)) > 7:
                    break
                run = candidate
            if len(run) > len(best):
                best = run
        if len(best) < 3:
            continue
        debits = best
        dates = [r["booking_date"] for r in debits]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
        amounts = [-r["amount"] for r in debits]
        average = sum(amounts) / Decimal(len(amounts))
        variance = sum((a - average) ** 2 for a in amounts) / Decimal(len(amounts))
        results.append(
            {
                "source_namespace": namespace,
                "counterparty": name,
                "currency": currency,
                "status": "monthly_candidate",
                "count": len(debits),
                "first_date": dates[0],
                "last_date": dates[-1],
                "mean_interval_days": mean(gaps),
                "mean_amount": average,
                "amount_variance": variance,
                "amount_range_relative_to_mean": (max(amounts) - min(amounts)) / average,
            }
        )
    return results


def reversal_candidates(frame: pl.DataFrame, max_days: int = 365) -> list[dict]:
    """Exact-amount later credit candidates, never allocation/reconciliation decisions."""
    result = []
    for (namespace, name, currency), rows in groups(frame).items():
        for credit in rows:
            if credit["amount"] <= 0:
                continue
            matches = [
                debit
                for debit in rows
                if debit["amount"] == -credit["amount"]
                and 0 < (credit["booking_date"] - debit["booking_date"]).days <= max_days
            ]
            for debit in matches:
                result.append(
                    {
                        "source_namespace": namespace,
                        "counterparty": name,
                        "currency": currency,
                        "debit_id": debit["source_transaction_id"],
                        "credit_id": credit["source_transaction_id"],
                        "amount": credit["amount"],
                        "status": "refund_or_reversal_candidate",
                        "matching_debit_count": len(matches),
                    }
                )
    return sorted(result, key=lambda r: (str(r["source_namespace"]), r["credit_id"], r["debit_id"]))


def duplicate_payment_candidates(frame: pl.DataFrame) -> list[dict]:
    result = []
    for (namespace, name, currency), rows in groups(frame).items():
        debits = sorted(
            (r for r in rows if r["amount"] < 0),
            key=lambda r: (r["booking_date"], r["source_transaction_id"]),
        )
        for i, first in enumerate(debits):
            for second in debits[i + 1 :]:
                if (
                    first["source_transaction_id"] != second["source_transaction_id"]
                    and first.get("reference")
                    and first["reference"] == second.get("reference")
                    and first["amount"] == second["amount"]
                    and 0 <= (second["booking_date"] - first["booking_date"]).days <= 31
                ):
                    result.append(
                        {
                            "counterparty": name,
                            "currency": currency,
                            "source_namespace": namespace,
                            "first_id": first["source_transaction_id"],
                            "second_id": second["source_transaction_id"],
                            "status": "duplicate_payment_candidate",
                        }
                    )
    return result


def classification_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Private in-memory export. Rule labels are weak labels, never human ground truth.

    Label/provenance columns must not be model inputs in a later experiment.
    """
    return frame.select(
        "normalized_counterparty",
        "ultimate_recipient",
        "message",
        "transaction_type_code",
        "amount",
        "direction",
        pl.col("booking_date").dt.month().alias("month"),
        (pl.col("booking_date").dt.weekday() - 1).alias("day_of_week"),
        pl.when(pl.col("category") == "tax")
        .then(pl.lit("tax"))
        .when(pl.col("amount") < 0)
        .then(pl.lit("expense"))
        .when(pl.col("amount") > 0)
        .then(pl.lit("income"))
        .otherwise(pl.lit("unknown"))
        .alias("suggested_transaction_role"),
        pl.col("category").alias("suggested_category"),
        pl.col("business_context").alias("suggested_business_context"),
        pl.lit("deterministic_weak_label_not_ground_truth").alias("label_provenance"),
    )
