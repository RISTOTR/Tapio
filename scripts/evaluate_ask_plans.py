"""Opt-in, six-call live Ask planner evaluation. Synthetic questions; no DB/Gmail calls."""

import argparse
import asyncio
import json
from datetime import date

from tapio.pilot.query_plan import interpret

TODAY = date(2026, 11, 18)
JUNE = [{"date_from": "2026-06-01", "date_to": "2026-06-30"}]
CASES = [
    {
        "id": "forestry-total",
        "question": "How much did I spend on forestry in June 2026?",
        "expected": {
            "contexts": ["FORESTRY"],
            "categories": [],
            "metric": "OUTFLOW",
            "periods": JUNE,
            "evidence_requirements": [],
            "merchants": [],
            "concepts": [],
            "locations": [],
            "clarification": None,
        },
    },
    {
        "id": "personal-travel",
        "question": "Total personal travel expenses in June 2026",
        "expected": {
            "contexts": ["PERSONAL"],
            "categories": ["TRAVEL"],
            "metric": "OUTFLOW",
            "periods": JUNE,
            "evidence_requirements": [],
            "locations": [],
            "merchants": [],
            "concepts": [],
            "clarification": None,
        },
    },
    {
        "id": "tax-flights",
        "question": "Suggest forestry flight expenses to Finland for tax deductions in June 2026",
        "expected": {
            "contexts": ["FORESTRY"],
            "categories": ["TRAVEL"],
            "concepts": ["flight"],
            "locations": ["Finland"],
            "merchants": [],
            "action": "TAX_SUGGESTION",
            "periods": JUNE,
            "evidence_requirements": [],
            "clarification": None,
        },
    },
    {
        "id": "gmail-receipts",
        "question": "Find Gmail receipts for personal travel expenses in June 2026",
        "expected": {
            "intent": "TRANSACTION_SEARCH",
            "contexts": ["PERSONAL"],
            "categories": ["TRAVEL"],
            "periods": JUNE,
            "evidence_requirements": ["EMAIL", "RECEIPT"],
            "clarification": None,
        },
    },
    {
        "id": "solar-comparison",
        "question": "Compare solar export in July 2025 and July 2026",
        "expected": {
            "intent": "PERIOD_COMPARISON",
            "metric": "SOLAR_EXPORT",
            "contexts": [],
            "categories": [],
            "concepts": [],
            "merchants": [],
            "evidence_requirements": [],
            "clarification": None,
            "periods": [
                {"date_from": "2025-07-01", "date_to": "2025-07-31"},
                {"date_from": "2026-07-01", "date_to": "2026-07-31"},
            ],
        },
    },
    {
        "id": "missing-year",
        "question": "Compare solar export from May through August",
        "expected": {"periods": [], "needs_clarification": True},
    },
]


def mismatches(plan, expected):
    """Exact requested sets, ignoring order; never accept extra scope or missing filters."""
    actual = plan.model_dump(mode="json")
    failures = []
    for field, value in expected.items():
        got = bool(actual["clarification"]) if field == "needs_clarification" else actual[field]
        if isinstance(value, list):
            equal = sorted(json.dumps(v, sort_keys=True) for v in got) == sorted(
                json.dumps(v, sort_keys=True) for v in value
            )
        else:
            equal = got == value
        if not equal:
            failures.append(field)
    return failures


async def evaluate(model, cases=CASES):
    results = []
    for case in cases:
        try:
            plan = await interpret(model, case["question"], today=TODAY)
            failures = mismatches(plan, case["expected"])
            result = {
                "case": case["id"],
                "status": "FAIL" if failures else "PASS",
                "failed_fields": failures,
                "plan": plan.model_dump(mode="json"),
            }
        except Exception as exc:
            # Never print provider exception details, credentials or request contents.
            result = {"case": case["id"], "status": "ERROR", "error_type": type(exc).__name__}
        results.append(result)
        print(json.dumps(result), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make up to six paid provider calls")
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"live_calls": 0, "cases": CASES}, indent=2))
        return 0
    from tapio.agent.providers.openai import read_key
    from tapio.pilot.config import MODEL
    from tapio.pilot.service import AcceptedModel

    try:
        model = AcceptedModel(read_key(), model=MODEL)
    except ValueError:
        print(json.dumps({"error": "LIVE_MODEL_CONFIGURATION_UNAVAILABLE"}))
        return 2
    results = asyncio.run(evaluate(model))
    passed = sum(r["status"] == "PASS" for r in results)
    print(
        json.dumps(
            {
                "model": MODEL,
                "reference_date": str(TODAY),
                "passed": passed,
                "total": len(results),
                "scope": "validated query plans only",
            }
        )
    )
    return int(passed != len(results))


if __name__ == "__main__":
    raise SystemExit(main())
