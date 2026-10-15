"""Pure Decimal aggregation of imported cash rows using human labels exclusively."""

from collections import defaultdict
from decimal import Decimal

from tapio.tools.finance_schemas import CashGroup, FinanceSummary

ZERO = Decimal(0)


def authoritative_label(review):
    if review is None or review.review_status != "REVIEWED":
        return "UNKNOWN", "UNKNOWN", False
    return (
        review.confirmed_business_context or "UNKNOWN",
        review.confirmed_category or "UNKNOWN",
        True,
    )


def summarize_rows(rows, args):
    groups = defaultdict(list)
    contexts = defaultdict(list)
    selected = []
    excluded = 0
    context_filter = args.business_context.value.upper() if args.business_context else None
    categories = [c.value for c in args.categories] if args.categories is not None else None
    for transaction, review in rows:
        context, category, human = authoritative_label(review)
        if context_filter and context != context_filter:
            excluded += context == "UNKNOWN"
            continue
        if categories is not None and category not in categories:
            continue
        item = (
            transaction,
            review,
            human,
            context == "UNKNOWN" or category == "UNKNOWN" or not human,
        )
        selected.append(item)
        groups[context, category, transaction.currency].append(item)
        contexts[context, "ALL_CATEGORIES", transaction.currency].append(item)

    def aggregate(key, items):
        debit = sum((-t.amount for t, _, _, _ in items if t.amount < 0), ZERO)
        credit = sum((t.amount for t, _, _, _ in items if t.amount > 0), ZERO)
        confirmed = sum(h for _, _, h, _ in items)
        unresolved = sum(u for _, _, _, u in items)
        return CashGroup(
            business_context=key[0],
            category=key[1],
            currency=key[2],
            debit_total=debit,
            credit_total=credit,
            net_cash_flow=credit - debit,
            transaction_count=len(items),
            confirmed_count=confirmed,
            unresolved_count=unresolved,
            transaction_ids=[t.id for t, _, _, _ in items],
            human_review_ids=[r.id for _, r, h, _ in items if h],
            evidence=(["CONFIRMED_HUMAN_LABEL"] if confirmed else [])
            + (["AMBIGUOUS"] if unresolved else []),
        )

    dates = [t.booking_date for t, _ in rows]
    return FinanceSummary(
        date_from=args.date_from,
        date_to=args.date_to,
        context_filter=context_filter,
        categories_filter=categories,
        groups=[aggregate(k, v) for k, v in sorted(groups.items())],
        context_totals=[aggregate(k, v) for k, v in sorted(contexts.items())],
        transaction_count=len(selected),
        confirmed_count=sum(h for _, _, h, _ in selected),
        unresolved_count=sum(u for _, _, _, u in selected),
        observed_first_date=min(dates) if dates else None,
        observed_last_date=max(dates) if dates else None,
        coverage="IMPORTED_ROWS_ONLY_NOT_COMPLETE_BANK_STATEMENT",
        excluded_unresolved_context_count=excluded,
        limitations=[
            "Cash flows only; never add invoice values or forestry-sale values to these totals.",
            (
                "Only REVIEWED human labels are authoritative. Weak labels are ignored; "
                "unknown context is not assigned to property or forestry."
            ),
            (
                "Observed booking dates do not prove continuous statement coverage. "
                "Missing months are not zero or estimated."
            ),
            "Refunds remain credits; this summary does not identify which debit was reversed.",
            "Classification is not tax treatment; no deductibility decision.",
            (
                "Currencies are separate; confirmed_count can overlap unresolved_count "
                "for human UNKNOWN labels."
            ),
        ],
    )
