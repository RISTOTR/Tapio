"""Synthetic final-invoice facts and strict payment linkage."""

from tapio.pilot.invoice_comparison import compare_invoices, final_bill_facts

PAGES = [
    "LOPPULASKU 19.12.2024\nLaskun numero 1234567890\nElenia Verkko Oyj\n"
    "LASKUN LOPPUSUMMA YHTEENSÄ 52,81 €\n"
    "veroton summa 42,08 €, ALV 25,5 % 10,73 €\nRef. nr 1 23456 78901 23456",
    "1.11.2024 - 30.11.2024\nVapaaehtoinen hyvitys 6 - 12 tuntia: 3% -54,86 €",
]


def test_final_bill_printed_totals_period_and_credit():
    facts = final_bill_facts(PAGES)
    assert facts["invoice_type"] == "Final bill"
    assert facts["total_eur"] == "52.81"
    assert facts["billing_periods"][0]["period_end"] == "2024-11-30"
    assert facts["credits"][0]["amount_eur"] == "-54.86"
    assert final_bill_facts([PAGES[0].replace("52,81", "53,81"), PAGES[1]]) is None
    assert final_bill_facts(["Unrelated invoice"]) is None


def test_compare_requires_reference_and_amount_not_just_merchant():
    tx = dict(
        transaction_id="synthetic",
        booking_date="2025-01-22",
        amount="-52.81",
        currency="EUR",
        payment_reference="00001234567890123456",
    )
    invoice = dict(
        final_bill_facts(PAGES),
        source="Email PDF attachment",
        filename="final.pdf",
        sha256="synthetic-hash",
        reference="email1",
    )
    lines, ids = compare_invoices([tx], [invoice])
    assert ids == {"synthetic"}
    assert "Final bill" in lines[0] and "2024-11-01–2024-11-30" in lines[0]
    assert "-54.86 EUR" in lines[0]
    assert compare_invoices([{**tx, "payment_reference": "999999999"}], [invoice]) == ([], set())
    assert compare_invoices([{**tx, "amount": "-53.81"}], [invoice]) == ([], set())
    assert compare_invoices([tx], [invoice, {**invoice, "sha256": "different"}]) == ([], set())


def test_repeated_payment_reference_is_not_called_separate_invoices():
    tx = dict(
        transaction_id="one",
        booking_date="2025-01-22",
        amount="-52.81",
        currency="EUR",
        payment_reference="1234567890123456",
    )
    invoice = dict(
        final_bill_facts(PAGES), source="Email PDF attachment", filename="final.pdf", sha256="hash"
    )
    assert compare_invoices([tx, {**tx, "transaction_id": "two"}], [invoice]) == ([], set())


def test_document_identity_extracts_named_customer_and_contract_end():
    from tapio.pilot.invoice_comparison import document_identity

    facts = document_identity(
        [
            "Asiakas Example Estate\nFörfallodag 7.1.2025",
            "Sähköverkkosopimus 12345. Sopimus on voimassa 30.11.2024 asti.",
        ]
    )
    assert facts["customer"] == "Example Estate"
    assert facts["due_date"] == "2025-01-07"
    assert facts["contracts"][0]["end_date"] == "2024-11-30"
    assert facts["contracts"][0]["page"] == 2


def documents():
    a = dict(
        final_bill_facts(PAGES),
        source="Email PDF attachment",
        sha256="a",
        filename="a.pdf",
        customer="Example Estate",
        contracts=[
            dict(
                kind="Network",
                identifier="old",
                status="Ends 2024-11-30",
                end_date="2024-11-30",
                page=2,
            )
        ],
    )
    b = {
        **a,
        "sha256": "b",
        "filename": "b.pdf",
        "customer": "Example Owner",
        "invoice_type": "Invoice",
        "total_eur": "100.00",
        "payment_reference": "999999999",
        "billing_periods": [dict(period_start="2024-12-01", period_end="2024-12-31")],
        "contracts": [
            dict(kind="Network", identifier="new", status="Open-ended", end_date=None, page=2)
        ],
    }
    return a, b


def test_comparison_separates_facts_inference_unknowns_and_overlap():
    from tapio.pilot.invoice_comparison import evidence_comparison

    a, b = documents()
    result = evidence_comparison([a, b])
    assert len(result["fields"]) == 11
    assert "Billing periods do not overlap." in result["differences"]
    assert any("Customer / account holder differs" in x for x in result["differences"])
    assert any("consistent with" in x for x in result["reasonable_inference"])
    assert any("Printed due date" in x for x in result["unresolved_points"])
    b["billing_periods"] = a["billing_periods"]
    assert "Billing periods overlap." in evidence_comparison([a, b])["differences"]
    b.pop("customer")
    result = evidence_comparison([a, b])
    assert not result["reasonable_inference"]
    assert not any("Customer / account holder differs" in x for x in result["differences"])
    assert evidence_comparison([a, a]) is None
    assert evidence_comparison([a, b, {**b, "sha256": "third"}]) is None
