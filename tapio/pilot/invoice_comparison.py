"""Read-only invoice facts and payment comparisons; never import or confirm links."""

import re
from decimal import Decimal

from data_pipeline.documents.base import DATE, NUM, day, dec, flat


def final_bill_facts(pages):
    """Older Elenia final-bill layout. Validate printed headline arithmetic only."""
    head = flat(pages[0])
    text = flat("\n".join(pages))
    if "Elenia Verkko Oyj" not in text or "LOPPULASKU" not in head:
        return None
    number = re.search(r"Laskun numero (\d{8,})", head)
    issued = re.search(r"LOPPULASKU (" + DATE + ")", head)
    total = re.search(r"LASKUN LOPPUSUMMA YHTEENSÄ (" + NUM + r") [€¤]", head)
    tax = re.search(
        r"veroton summa (" + NUM + r") [€¤], ALV " + NUM + r" % (" + NUM + r") [€¤]", head
    )
    reference = re.search(r"Ref\. nr\s+([\d ]+)", head)
    if not all((number, issued, total, tax, reference)):
        return None
    if dec(tax[1]) + dec(tax[2]) != dec(total[1]):
        return None
    periods, credits = [], []
    for page, raw in enumerate(pages, 1):
        body = flat(raw)
        for match in re.finditer(r"(" + DATE + r") - (" + DATE + r")", body):
            periods.append(
                dict(period_start=str(day(match[1])), period_end=str(day(match[2])), page=page)
            )
        for line in body.splitlines():
            credit = re.search(r"Vapaaehtoinen hyvitys.*?(-" + NUM + r") [€¤]", line)
            if credit:
                credits.append(
                    dict(description="Voluntary credit", amount_eur=str(dec(credit[1])), page=page)
                )
    return dict(
        vendor="Elenia Verkko Oyj",
        invoice_number=number[1],
        date=str(day(issued[1])),
        payment_reference=re.sub(r"\s", "", reference[1]),
        total_eur=str(dec(total[1])),
        subtotal_eur=str(dec(tax[1])),
        vat_eur=str(dec(tax[2])),
        currency="EUR",
        invoice_type="Final bill",
        billing_periods=periods,
        credits=credits,
        authority="Printed invoice facts; headline arithmetic checked, not imported",
    )


def reference_key(value):
    return re.sub(r"\s", "", value or "").lstrip("0")


def compare_invoices(transactions, evidence):
    """Require exact payment reference and amount; never match on amount alone."""
    lines, matched = [], set()
    for tx in transactions:
        key = reference_key(tx.get("payment_reference"))
        if (
            len(key) < 6
            or sum(reference_key(t.get("payment_reference")) == key for t in transactions) != 1
        ):
            continue
        candidates = [
            r
            for r in evidence
            if r.get("source") == "Email PDF attachment"
            and reference_key(r.get("payment_reference")) == key
            and r.get("currency") == tx.get("currency")
            and r.get("total_eur") is not None
            and Decimal(r["total_eur"]) == -Decimal(tx["amount"])
        ]
        unique = {r.get("sha256", r.get("filename")): r for r in candidates}
        if len(unique) != 1:
            continue
        invoice = next(iter(unique.values()))
        periods = sorted(
            {
                (p["period_start"], p["period_end"])
                for p in invoice.get("billing_periods", invoice.get("energy", []))
            }
        )
        period_text = ", ".join(f"{a}–{b}" for a, b in periods) or "billing period not extracted"
        detail = (
            f"{tx['booking_date']} · {Decimal(tx['amount']):.2f} {tx['currency']}: "
            f"{invoice.get('invoice_type', 'Invoice')} {invoice['invoice_number']}, "
            f"issued {invoice['date']}, covers {period_text} "
            f"({invoice['filename']}; exact payment reference and amount)."
        )
        for credit in invoice.get("credits", []):
            detail += (
                f" {credit['description']}: {credit['amount_eur']} EUR (page {credit['page']})."
            )
        mail = [
            m
            for m in evidence
            if m.get("source") == "Gmail read-only"
            and m.get("reference") == invoice.get("reference")
        ]
        if any("loppulaskun nyt vasta" in m.get("excerpt", "").lower() for m in mail):
            detail += " The accompanying email says the final bill was sent late."
        lines.append(detail)
        matched.add(tx["transaction_id"])
    return lines, matched


def document_identity(pages):
    """Label-bound identity facts; no account-holder inference from the payer."""
    facts = {"contracts": [], "field_pages": {}}
    head = flat(pages[0])
    customer = re.search(r"Asiakkaan nimi Asiakasnumero\n(.+?) \d+", head)
    if not customer:
        customer = re.search(r"\bAsiakas (.+)", head)
    if customer:
        facts["customer"] = customer[1].strip()
        facts["field_pages"]["customer"] = [1]
    due = re.search(r"(?:Eräpäivä|Förfallodag) (" + DATE + ")", head)
    if due:
        facts["due_date"] = str(day(due[1]))
        facts["field_pages"]["due_date"] = [1]
    for page, raw in enumerate(pages, 1):
        for m in re.finditer(
            r"(Sähköverkkosopimus|Sähköntuotannon verkkosopimus) (\d+)\. "
            r"Sopimus on voimassa (toistaiseksi|" + DATE + r" asti)",
            flat(raw),
        ):
            end = None if m[3] == "toistaiseksi" else str(day(m[3].split()[0]))
            facts["contracts"].append(
                {
                    "kind": m[1],
                    "identifier": m[2],
                    "end_date": end,
                    "status": "Open-ended" if end is None else "Ends " + end,
                    "page": page,
                }
            )
    return facts


def evidence_comparison(records):
    """Compare exactly two distinct PDFs; unknown facts never count as differences."""
    docs = list(
        {
            r["sha256"]: r
            for r in records
            if r.get("source") == "Email PDF attachment" and r.get("sha256")
        }.values()
    )
    if len(docs) != 2:
        return None
    fields = [
        ("customer", "Customer / account holder"),
        ("vendor", "Supplier"),
        ("invoice_number", "Invoice number"),
        ("contracts", "Contract / account identifier"),
        ("contract_dates", "Contract dates"),
        ("periods", "Billing period"),
        ("date", "Invoice date"),
        ("due_date", "Printed due date"),
        ("amount", "Amount"),
        ("payment_reference", "Payment reference"),
        ("invoice_type", "Invoice type"),
    ]

    def values(doc):
        result = dict(doc)
        result["periods"] = sorted(
            {
                (p["period_start"], p["period_end"])
                for p in doc.get("billing_periods", doc.get("energy", []))
            }
        )
        result["contracts"] = [f"{c['kind']}: {c['identifier']}" for c in doc.get("contracts", [])]
        result["contract_dates"] = [f"{c['kind']}: {c['status']}" for c in doc.get("contracts", [])]
        result["amount"] = (
            f"{Decimal(doc['total_eur']):.2f} {doc['currency']}"
            if doc.get("total_eur") is not None and doc.get("currency")
            else None
        )
        return result

    a, b = [values(d) for d in docs]
    rows, differences, unresolved = [], [], []
    for key, label in fields:

        def display(value, key=key):
            if key == "periods":
                return "; ".join(f"{start}–{end}" for start, end in value) if value else None
            return "; ".join(value) if isinstance(value, list) else value

        av, bv = display(a.get(key)), display(b.get(key))
        rows.append({"field": label, "a": av, "b": bv})
        if not av or not bv:
            absent = " and ".join(n for n, v in [("A", av), ("B", bv)] if not v)
            unresolved.append(f"{label}: not extracted from Document {absent}.")
        elif key == "periods":
            overlap = any(x <= v and u <= y for x, y in a[key] for u, v in b[key])
            differences.append(
                "Billing periods overlap." if overlap else "Billing periods do not overlap."
            )
        elif (reference_key(av) if key == "payment_reference" else av.casefold()) != (
            reference_key(bv) if key == "payment_reference" else bv.casefold()
        ):
            differences.append(f"{label} differs: A — {av}; B — {bv}.")
    facts = []
    for name, doc in zip(("A", "B"), docs, strict=True):
        for contract in doc.get("contracts", []):
            facts.append(
                f"Document {name}, page {contract['page']}: {contract['kind']} "
                f"{contract['identifier']} — {contract['status']}."
            )
        if doc.get("customer"):
            facts.append(f"Document {name}, page 1 names {doc['customer']} as the customer.")
    different_customers = bool(
        a.get("customer")
        and b.get("customer")
        and a["customer"].casefold() != b["customer"].casefold()
    )
    ended_final = any(
        d.get("invoice_type") == "Final bill"
        and any(c.get("end_date") for c in d.get("contracts", []))
        for d in docs
    )
    inference = []
    if different_customers and ended_final:
        inference.append(
            "The different customers and an ending contract are consistent with an "
            "account-holder change. The final bill closes the earlier contract; "
            "the documents alone do not establish the reason for the change."
        )
        unresolved.append(
            "The exact transfer arrangement and who was responsible for paying "
            "the earlier account are not established by these invoices."
        )
    if different_customers:
        unresolved.append(
            "A matching bank payment identifies the payment, not the invoice's account holder."
        )
    return {
        "documents": [
            {
                "label": label,
                "filename": d.get("filename", "PDF"),
                "sha256": d["sha256"],
                "message_id": d.get("reference"),
            }
            for label, d in zip(("A", "B"), docs, strict=True)
        ],
        "fields": rows,
        "differences": differences,
        "documented_facts": facts,
        "reasonable_inference": inference,
        "unresolved_points": unresolved,
    }


def add_evidence_comparison(result):
    comparison = evidence_comparison(result.supporting_records)
    if comparison:
        result.optional_details["evidence_comparison"] = comparison
        if comparison["reasonable_inference"]:
            summary = (
                "The PDFs name different customers; one is a final bill for an ending contract."
            )
        else:
            summary = "Two source documents compared. " + " ".join(comparison["differences"][:2])
        result = result.model_copy(update={"answer": summary, "direct_answer": summary})
    return result
