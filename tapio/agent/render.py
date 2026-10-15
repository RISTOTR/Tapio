"""Trusted prose from typed tool fields. No free-form model claims or financial sums."""

from decimal import Decimal


def money(value):
    return f"{Decimal(value):.2f}" if value is not None else "not established"


def render_answer(results, message):
    lines = [message]
    for result in results:
        if not result.get("ok"):
            lines.append("Tool evidence unavailable: " + result["error"]["code"])
            continue
        name, d = result["tool"], result["data"]
        if name == "summarize_finances":
            lines.append(f"Bank cash-flow view: {d['date_from']} to {d['date_to']}.")
            for group in d["context_totals"]:
                lines.append(
                    f"{group['business_context']} ({group['currency']}): "
                    f"debits {money(group['debit_total'])}; "
                    f"credits {money(group['credit_total'])}; "
                    f"net cash flow {money(group['net_cash_flow'])}. "
                    f"Human-reviewed {group['confirmed_count']}; "
                    f"unresolved {group['unresolved_count']}."
                )
            for group in d["groups"]:
                if group["business_context"] in ("PROPERTY", "FORESTRY"):
                    lines.append(
                        f"  {group['business_context']} / {group['category']}: "
                        f"debits {money(group['debit_total'])}, "
                        f"credits {money(group['credit_total'])} "
                        f"{group['currency']}."
                    )
            lines.append(
                f"Needs review: {d['unresolved_count']} selected transactions; "
                f"{d['excluded_unresolved_context_count']} unknown-context rows "
                "excluded by context filter."
            )
            lines.append(
                f"Coverage: imported booking dates {d['observed_first_date']} to "
                f"{d['observed_last_date']}; not proof of a complete bank statement or year."
            )
        elif name in ("find_invoices", "get_invoice"):
            items = d.get("items", [d])
            lines.append("Source-document/invoice view (not additional cash expenses):")
            if not items:
                lines.append(
                    "No matching imported invoice evidence; this does not establish zero expense."
                )
            for item in items:
                contexts = item.get("confirmed_payment_human_contexts", [])
                candidate_contexts = item.get("candidate_payment_human_contexts", [])
                lines.append(
                    f"{item['invoice_date']}: {item['vendor']}, source invoice value "
                    f"EUR {money(item['total_eur'])}; payment {item['reconciliation']['state']}; "
                    f"human context on confirmed links {contexts or 'not established'}, "
                    f"on candidate links {candidate_contexts or 'not established'}."
                )
                lines.extend(reconciliation_lines(item["reconciliation"]))
            if d.get("truncated"):
                lines.append("Invoice list truncated; not a complete total.")
        elif name == "get_invoice_reconciliation":
            lines.extend(reconciliation_lines(d))
        elif name in ("query_forestry_sales", "get_forestry_sale"):
            lines.append("Forestry-sale source values (not bank timber income):")
            items = d.get("items", [d])
            if not items:
                lines.append(
                    "No matching imported sale evidence; "
                    "this does not establish zero timber income."
                )
            for item in items:
                lines.append(
                    f"{item['sale_date']}: documented actual value "
                    f"EUR {money(item['actual_value_eur'])}; "
                    f"estimated value EUR {money(item['estimated_value_eur'])}. "
                    "Payment not implied."
                )
            if d.get("truncated"):
                lines.append("Sale list truncated; no complete sale total supplied.")
        elif name == "get_saved_energy_comparison":
            a = d["aggregate"]
            lines.append(
                f"Frozen deterministic energy comparison, {', '.join(d['months'])}: "
                f"net fixed EUR {money(a['net_fixed_household_total'])}, "
                f"net spot EUR {money(a['net_spot_household_total'])}; "
                f"fixed minus spot EUR {money(a['fixed_minus_spot_eur'])}; winner {a['winner']}. "
                "Retrospective unchanged-load scenario, not a realized switch or full-year result."
            )
            lines.append(d["coverage"])
        elif name == "query_transactions":
            lines.append("Transaction review evidence (do not sum this bounded page):")
            for item in d["items"][:10]:
                lines.append(
                    f"{item['booking_date']}: "
                    f"{item['counterparty'] or 'counterparty unavailable'}, "
                    f"{item['currency']} {money(item['amount'])}, "
                    f"{item['business_context'] or 'UNKNOWN'} / {item['category'] or 'UNKNOWN'}, "
                    f"{item['label_authority']}."
                )
            if d["truncated"] or len(d["items"]) > 10:
                lines.append("Additional rows omitted from prose; bounded page is not a total.")
        else:
            lines.append(f"{name}: structured source evidence retained in results.")
    lines.append(
        "Limits: no tax-deductibility decision. Human business context is not tax treatment. "
        "Do not add invoice, forestry-sale and bank-payment values together. "
        "Missing periods are not estimated; unknown classifications remain unresolved."
    )
    return "\n".join(lines)


def reconciliation_lines(d):
    lines = [
        f"Reconciled-event view: {d['state']}; "
        f"confirmed paid EUR {money(d['confirmed_paid_eur'])}, "
        f"confirmed refund EUR {money(d['confirmed_refund_eur'])}, "
        f"confirmed net EUR {money(d['confirmed_net_eur'])}."
    ]
    if d.get("candidate_debit_count") or d.get("candidate_credit_count"):
        lines.append(
            f"Ambiguous candidate cash flows: {d['candidate_debit_count']} debit(s), "
            f"{d['candidate_credit_count']} credit(s); candidate net outflow "
            f"EUR {money(d['candidate_net_outflow_eur'])}. "
            + (
                "Net is consistent with one invoice payment, but not confirmed. "
                if d["candidate_net_matches_invoice"]
                else ""
            )
            + "Exact reversed debit is not established; all reversal candidates remain preserved."
        )
    return lines
