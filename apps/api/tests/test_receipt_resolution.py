"""Synthetic receipt evidence: bounded reads, conservative matches and explicit authority."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from integrations.gmail.auth import SCOPE, check_scopes
from integrations.gmail.models import Message
from integrations.gmail.receipts import ReceiptSearch, receipt_events, resolve, search_receipts
from tapio.confirmation.outcomes import field_outcomes
from tapio.confirmation.receipt_support import integrate_receipt, receipt_fresh
from tapio.knowledge.models import digest
from tapio.tools.errors import ToolFailure

NOW = datetime(2026, 1, 10, tzinfo=UTC)


def search(**kwargs):
    return ReceiptSearch(transaction_date="2026-01-10", amount=Decimal("12.34"), **kwargs)


def mail(body="", **kwargs):
    values = dict(
        message_id="synthetic1",
        thread_id="thread1",
        sender="Receipt <receipt@example.com>",
        subject="Paytrail receipt",
        message_date="Sat, 10 Jan 2026 10:00:00 +0000",
        retrieved_at=NOW,
        history_id="1",
        body="Yhteensä: 12,34 EUR\n" + body,
        body_truncated=False,
        attachments=[],
        links=[],
        content_hash="a" * 64,
    )
    values.update(kwargs)
    return Message(**values)


def test_readonly_scope_and_query_boundaries():
    check_scopes([SCOPE])
    with pytest.raises(ToolFailure):
        check_scopes([SCOPE, "https://www.googleapis.com/auth/gmail.modify"])
    queries = search(merchant='Shop" OR in:anywhere', reference="REF123456").queries()
    assert len(queries) == 4
    assert all("after:2026/01/02 before:2026/01/18" in q for q in queries)
    assert '"Shop OR in anywhere"' in queries[-1]
    with pytest.raises(ValidationError):
        search(days=8)
    with pytest.raises(ValidationError):
        search(reference='ref" OR other')


def test_receipt_search_only_lists_and_reads():
    endpoint = Mock()
    endpoint.list.return_value = {"messages": [{"id": "synthetic1"}]}
    client = SimpleNamespace(
        service=SimpleNamespace(users=lambda: SimpleNamespace(messages=lambda: endpoint)),
        execute=lambda r: r,
        get_message=Mock(return_value=mail("Viite: REF123456")),
    )
    result = search_receipts(client, search(reference="REF123456"))
    assert result["status"] == "RECEIPT_MATCHED"
    assert client.get_message.call_count == 1
    assert all(
        call.kwargs["includeSpamTrash"] is False and call.kwargs["maxResults"] == 20
        for call in endpoint.list.call_args_list
    )
    assert {c[0] for c in endpoint.mock_calls} == {"list"}


def test_exact_amount_reference_and_provenance():
    result = resolve(
        search(reference="REF123456"), [mail("Viite: REF123456\nMyyjä: Synthetic shop")]
    )
    assert result["status"] == "RECEIPT_MATCHED"
    events = receipt_events("synthetic-transaction", result)
    assert events and all(c.authority == "DETERMINISTIC_SOURCE_FACT" for c in events[0].claims)
    assert all(c.provenance.source_id == "synthetic1" for c in events[0].claims)
    assert all(c.provenance.extraction_method for c in events[0].claims)
    assert not any("confirmed_category" == c.predicate for c in events[0].claims)
    assert all("body" not in c.value for c in events[0].claims if isinstance(c.value, dict))


def test_single_amount_is_only_candidate():
    assert resolve(search(), [mail()])["status"] == "RECEIPT_CANDIDATE"
    assert (
        resolve(search(reference="REF123456"), [mail("Viite: WRONG123")])["status"]
        == "RECEIPT_CANDIDATE"
    )


def test_wrong_date_and_missing_amount_insufficient():
    assert (
        resolve(search(), [mail(message_date="Sun, 01 Feb 2026 10:00:00 +0000")])["status"]
        == "INSUFFICIENT_RECEIPT_EVIDENCE"
    )
    assert (
        resolve(search(), [mail().model_copy(update={"body": "Paytrail receipt, no amount"})])[
            "status"
        ]
        == "INSUFFICIENT_RECEIPT_EVIDENCE"
    )


def test_multiple_and_incomplete_results_never_resolved():
    args = search(reference="REF123456")
    a = mail("Viite: REF123456")
    b = mail("Viite: REF123456", message_id="synthetic2")
    assert resolve(args, [a, b])["status"] == "MULTIPLE_RECEIPTS"
    assert resolve(args, [a], complete=False)["status"] == "RECEIPT_CANDIDATE"
    assert resolve(args, [], complete=False)["status"] == "INSUFFICIENT_RECEIPT_EVIDENCE"


def test_available_mail_absence_not_historical_nonexistence():
    result = resolve(search(), [])
    assert result["status"] == "NO_RECEIPT_FOUND"
    assert result["display_status"] == "NO_RECEIPT_FOUND_IN_AVAILABLE_MAIL"
    assert "deleted" in result["limitation"]


def card():
    return {
        "card_id": "c",
        "transaction": {"id": "tx"},
        "suggestion": {"category": None, "context": None, "authority": "SUGGESTED"},
        "current_state": {"category": None, "context": None, "authority": {}},
        "source_hash": "source",
        "pilot_tags": ["ABSTENTION", "PAYTRAIL_STILL_OPAQUE"],
        "reasons": [],
        "warnings": [],
        "multi_context": True,
        "paytrail_purpose": "STILL_OPAQUE",
    }


def test_receipt_category_only_no_processor_or_context_rule():
    result = resolve(
        search(reference="REF123456"),
        [mail("Viite: REF123456\nMyyjä: Tokmanni\nTuote: car repair")],
    )
    c = integrate_receipt(card(), result)
    assert c["suggestion"] == {"category": "MAINTENANCE", "context": None, "authority": "SUGGESTED"}
    assert c["receipt_category_added"]
    assert "RECEIPT_PURPOSE_TEXT" in {r["code"] for r in c["reasons"]}
    without = integrate_receipt(
        card(), resolve(search(reference="REF123456"), [mail("Viite: REF123456")])
    )
    assert without["suggestion"]["category"] is None
    candidate = integrate_receipt(card(), resolve(search(), [mail("Tuote: car repair")]))
    assert candidate["suggestion"]["category"] is None


def test_human_and_bank_conflicts_not_overwritten():
    c = card()
    c["current_state"] = {
        "category": "OTHER",
        "context": "FORESTRY",
        "authority": {"category": "HUMAN_CONFIRMED", "context": "HUMAN_CONFIRMED"},
    }
    result = resolve(search(reference="REF123456"), [mail("Viite: REF123456\nTuote: car repair")])
    out = integrate_receipt(c, result)
    assert out["current_state"] == c["current_state"]
    assert out["receipt_conflicts"] and out["suggestion"]["category"] is None


@pytest.mark.parametrize(
    "suggestion,selected,expected",
    [
        (
            {"category": "INSURANCE"},
            {"category": "INSURANCE", "context": "PERSONAL"},
            {"category": "SUGGESTION_ACCEPTED", "context": "MANUALLY_COMPLETED"},
        ),
        (
            {"category": "OTHER"},
            {"category": "MAINTENANCE"},
            {"category": "SUGGESTION_CHANGED", "context": "LEFT_UNRESOLVED"},
        ),
        (
            {},
            {"category": "GROCERIES", "context": "PERSONAL"},
            {"category": "MANUALLY_COMPLETED", "context": "MANUALLY_COMPLETED"},
        ),
    ],
)
def test_field_outcomes(suggestion, selected, expected):
    assert field_outcomes(suggestion, selected, {}) == expected


def test_untouched_confirmed_field_not_a_missing_suggestion():
    assert field_outcomes({}, {}, {"authority": {"category": "HUMAN_CONFIRMED"}}) == {
        "category": "NOT_APPLICABLE",
        "context": "LEFT_UNRESOLVED",
    }


def test_stale_receipt_registry(tmp_path):
    import json

    c = integrate_receipt(card(), resolve(search(), []))
    path = tmp_path / "receipts" / "tx.json"
    path.parent.mkdir()
    path.write_text(json.dumps(c["receipt_evidence"]))
    assert receipt_fresh(c, tmp_path)
    result = dict(c["receipt_evidence"], status="RECEIPT_CANDIDATE")
    path.write_text(json.dumps(result))
    assert not receipt_fresh(c, tmp_path)
    assert digest(result) != digest(c["receipt_evidence"])


def test_zero_padded_bank_reference_is_representation_only():
    result = resolve(search(reference="00000000123456"), [mail("Viitenumero: 123456")])
    assert result["status"] == "RECEIPT_MATCHED"
    assert result["search"]["reference"] == "00000000123456"
    assert any(f["value"] == "123456" for f in result["candidates"][0]["facts"])


def test_conflicting_reference_prevents_merchant_only_match():
    result = resolve(
        search(reference="123456", merchant="Shop Alpha"),
        [mail("Myyjä: Shop Alpha\nViite: 654321")],
    )
    assert result["status"] == "RECEIPT_CANDIDATE"


def test_payment_confirmation_does_not_invent_itemized_purpose():
    result = resolve(
        search(reference="123456"), [mail("Viite: 123456\nTämä viesti on vahvistus maksustasi.")]
    )
    facts = result["candidates"][0]["facts"]
    assert any(f["value"] == "PAYMENT_CONFIRMATION" for f in facts)
    assert not any(f["field"] == "description" for f in facts)


def test_mixed_currencies_and_multiple_totals_not_resolved():
    assert (
        resolve(search(reference="123456"), [mail("Viite: 123456\nUSD 10.00")])["status"]
        == "INSUFFICIENT_RECEIPT_EVIDENCE"
    )
    assert (
        resolve(search(reference="123456"), [mail("Viite: 123456\nYhteensä: 10,00 EUR")])["status"]
        == "INSUFFICIENT_RECEIPT_EVIDENCE"
    )
