"""Deterministic purposefully stratified review proposals, never confirmed labels."""

import hashlib
import re
from collections import Counter, defaultdict

import polars as pl

from data_pipeline.normalize.bank_analysis import (
    duplicate_payment_candidates,
    effective_counterparty,
    recurring_candidates,
    reversal_candidates,
)

SEED = 42
TARGET = 100
MERCHANT_CAP = 6
PATTERNS = {
    "grocery_like": r"\b(prisma|lidl|k-market|s-market|sale|alepa|k-supermarket|k-citymarket)\b",
    "fuel_like": r"\b(neste|st1|shell|teboil|abc)\b",
    "maintenance_like": r"(puuilo|motonet|tokmanni|rauta|biltema|stark|bauhaus|katsastus)",
    "insurance_like": r"(vakuutus|tapiola|fennia)",
    "subscription_like": r"\b(dna|elisa|telia|netflix|spotify)\b",
    "transfer_like": r"\b(tilisiirto|siirto|transfer)\b",
}
QUOTAS = {
    "forestry_rule": 10,
    "property_rule": 10,
    "paytrail": 12,
    "tax": 6,
    "grocery_like": 8,
    "fuel_like": 6,
    "maintenance_like": 6,
    "insurance_like": 5,
    "subscription_like": 4,
    "transfer_like": 10,
    "credit": 12,
    "recurring": 10,
    "unknown_context": 35,
    "unknown_merchant": 10,
    "debit": 50,
}


def sample_transactions(
    frame: pl.DataFrame, *, target: int = TARGET, seed: int = SEED
) -> tuple[list, dict]:
    if target < 1 or frame["transaction_id"].n_unique() != frame.height:
        raise ValueError("Positive target and unique transaction IDs required")
    rows = frame.to_dicts()
    by_archive = {r["source_transaction_id"]: r["transaction_id"] for r in rows}
    hints = defaultdict(list)
    mandatory = set()
    for pair in reversal_candidates(frame):
        credit, debit = by_archive[pair["credit_id"]], by_archive[pair["debit_id"]]
        mandatory.update([credit, debit])
        hints[credit].append(f"Unresolved refund candidate with debit {debit}")
        hints[debit].append(f"Unresolved refund candidate with credit {credit}")
    for pair in duplicate_payment_candidates(frame):
        a, b = by_archive[pair["first_id"]], by_archive[pair["second_id"]]
        mandatory.update([a, b])
        hints[a].append(f"Possible duplicate payment with {b}; not confirmed")
        hints[b].append(f"Possible duplicate payment with {a}; not confirmed")
    recurring = {r["counterparty"] for r in recurring_candidates(frame)}
    for row in rows:
        merchant = effective_counterparty(row)
        row["merchant_group"] = merchant or row.get("normalized_counterparty") or "(missing)"
        text = " ".join(
            [merchant or "", row.get("message") or "", row.get("source_description") or ""]
        )
        tags = {name for name, pattern in PATTERNS.items() if re.search(pattern, text, re.I)}
        if row["business_context"] == "forestry":
            tags.add("forestry_rule")
        if row["business_context"] == "property":
            tags.add("property_rule")
        if row["business_context"] == "unknown":
            tags.add("unknown_context")
        if not merchant or row["category"] == "unknown":
            tags.add("unknown_merchant")
        if row.get("payment_intermediary"):
            tags.add("paytrail")
        if row["category"] == "tax":
            tags.add("tax")
        if merchant in recurring:
            tags.add("recurring")
        tags.add("credit" if row["amount"] > 0 else "debit")
        if row["transaction_id"] in mandatory:
            tags.add("relationship_candidate")
        row["tags"] = tags
        row["review_hint"] = "; ".join(sorted(hints[row["transaction_id"]]))

    def rank(row):
        return hashlib.sha256(f"{seed}:{row['transaction_id']}".encode()).hexdigest()

    ordered = sorted(rows, key=rank)
    selected, counts = {}, Counter()

    def add(row, *, required=False):
        identity, merchant = row["transaction_id"], row["merchant_group"]
        if identity in selected:
            return
        # Mandatory relationship rows are never silently omitted because of a cap.
        if required or (len(selected) < target and counts[merchant] < MERCHANT_CAP):
            selected[identity] = row
            counts[merchant] += 1

    for row in ordered:
        if row["transaction_id"] in mandatory:
            add(row, required=True)
    for tag, quota in QUOTAS.items():
        for row in ordered:
            if sum(tag in r["tags"] for r in selected.values()) >= quota:
                break
            if tag in row["tags"]:
                add(row)
    # Fill underrepresented merchant groups first, then deterministic rank.
    while len(selected) < min(target, len(rows)):
        remaining = [
            r
            for r in ordered
            if r["transaction_id"] not in selected and counts[r["merchant_group"]] < MERCHANT_CAP
        ]
        if not remaining:
            break
        add(min(remaining, key=lambda r: (counts[r["merchant_group"]], rank(r))))
    result = sorted(selected.values(), key=rank)
    report = {
        "seed": seed,
        "target": target,
        "sample_size": len(result),
        "source_rows": len(rows),
        "merchant_cap": MERCHANT_CAP,
        "maximum_merchant_count": max(counts.values(), default=0),
        "distinct_effective_merchants": len(counts),
        "mandatory_relationship_rows": len(mandatory),
        "strata_available": {tag: sum(tag in r["tags"] for r in rows) for tag in QUOTAS},
        "strata_selected": {tag: sum(tag in r["tags"] for r in result) for tag in QUOTAS},
        "year_counts": dict(sorted(Counter(str(r["booking_date"].year) for r in result).items())),
        "quota_shortfalls": {
            tag: quota - sum(tag in r["tags"] for r in result)
            for tag, quota in QUOTAS.items()
            if sum(tag in r["tags"] for r in result) < quota
        },
    }
    return result, report
