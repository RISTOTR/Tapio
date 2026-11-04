"""Bounded, deterministic receipt resolution. Email content is data, never instructions."""

import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Literal

from pydantic import Field, field_validator

from tapio.knowledge.models import Claim, KnowledgeEvent, Provenance, Typed, digest

VERSION = "RECEIPT_RESOLUTION_V1"


def norm(text):
    return " ".join(unicodedata.normalize("NFKC", str(text)).casefold().split())


def reference_key(value):
    value = norm(value)
    # Bank export pads numeric payment references; keep the original fact as evidence.
    return value.lstrip("0") or "0" if value.isascii() and value.isdigit() else value


def quoted(text):
    # Only literal search words; Gmail operators cannot escape the quoted term.
    words = re.findall(r"[\w]+", text, re.UNICODE)
    return '"' + " ".join(words)[:100] + '"'


class ReceiptSearch(Typed):
    transaction_date: date
    amount: Decimal = Field(gt=0)
    currency: Literal["EUR"] = "EUR"
    processor: Literal["Paytrail"] = "Paytrail"
    merchant: str = Field(default="", max_length=120)
    reference: str = Field(default="", max_length=100)
    days: int = Field(default=7, ge=0, le=7)

    @field_validator("reference")
    @classmethod
    def valid_reference(cls, value):
        if value and not re.fullmatch(r"[\w-]{6,100}", value):
            raise ValueError("EXPLICIT_REFERENCE_REQUIRED")
        return value

    def queries(self):
        bounds = (
            f"after:{(self.transaction_date - timedelta(days=self.days + 1)):%Y/%m/%d} "
            f"before:{(self.transaction_date + timedelta(days=self.days + 1)):%Y/%m/%d}"
        )
        # Search is capped at four queries and twenty messages per query. Match
        # evaluation below enforces the actual date window independently of Gmail.
        amount = f"{self.amount:.2f}"
        queries = [
            f'{bounds} paytrail "{amount.replace(".", ",")}"',
            f'{bounds} paytrail "{amount}"',
        ]
        if self.reference:
            queries.append(f"{bounds} {quoted(reference_key(self.reference))}")
        if len(re.findall(r"\w", self.merchant)) >= 3:
            queries.append(f'{bounds} {quoted(self.merchant)} "{amount.replace(".", ",")}"')
        return list(dict.fromkeys(queries))


LABELS = {
    "merchant": r"(?:myyjä|kauppias|merchant|seller|yritys|maksun saaja|palveluntarjoaja)",
    "order_number": r"(?:tilausnumero|tilausnro|tilaustunnus|order (?:number|id)|tilaus)",
    "invoice_number": r"(?:laskunumero|laskun numero|invoice (?:number|id))",
    "payment_reference": r"(?:maksun viitenumero|viitenumero|maksuviite|payment reference|viite)",
    "description": r"(?:tuote|palvelu|product|service|description|kuvaus|ostoksen sisältö)",
    "receipt_date": r"(?:laskun päiväys|receipt date|invoice date|maksupäivä|tilauspäivä)",
}
MONEY = r"(?<![\d.,])(\d{1,6}(?:[ \u00a0]\d{3})*[,.]\d{2})\s*(?:EUR|€)"
TOTAL = (
    r"(?:yhteensä|total|maksettu|summa|amount|loppusumma)\s*[:：]?\s*(?:EUR\s*)?"
    r"(\d{1,6}(?:[ \u00a0]\d{3})*[,.]\d{2})"
)


def money(value):
    return Decimal(value.replace("\u00a0", "").replace(" ", "").replace(",", "."))


def extract(message):
    """Only labeled fields and source metadata; no merchant/context guessing."""
    text = message.subject + "\n" + message.body
    facts = []

    def add(field, value, snippet, location):
        facts.append(
            {
                "field": field,
                "value": value,
                "snippet": snippet[:240],
                "location": location,
                "message_id": message.message_id,
                "thread_id": message.thread_id,
                "content_hash": message.content_hash,
                "extraction_method": VERSION + ":explicit-label",
                "authority": "DETERMINISTIC_SOURCE_FACT",
                "timestamp": message.retrieved_at.isoformat(),
            }
        )

    for field, pattern in LABELS.items():
        for match in re.finditer(r"(?im)^\s*" + pattern + r"\s*[:：#]\s*([^\n]{1,160})", text):
            add(field, match[1].strip(), match[0], "subject/body:" + str(match.start()))
    totals = list(re.finditer(TOTAL, text, re.I))
    amounts = totals or list(re.finditer(MONEY, text, re.I))
    for match in amounts:
        add("amount", str(money(match[1])), match[0], "subject/body:" + str(match.start()))
    for currency in re.findall(r"\b(?:USD|GBP|SEK|NOK)\b", text, re.I):
        add("currency", currency.upper(), currency, "subject/body")
    if "vahvistus maksustasi" in norm(text):
        add("document_type", "PAYMENT_CONFIRMATION", "vahvistus maksustasi", "subject/body")
    else:
        add("document_type", "RECEIPT_OR_ORDER_CANDIDATE", message.subject, "header:Subject")
    if re.search(r"\bEUR\b|€", text, re.I):
        add("currency", "EUR", "EUR/€ explicitly present", "subject/body")
    if re.search(r"\bpaytrail\b", text + " " + message.sender, re.I):
        add("processor", "Paytrail", "Paytrail explicitly present", "subject/body/from")
    add("sender", message.sender, message.sender, "header:From")
    domain = re.search(r"@([A-Za-z0-9.-]+)", message.sender)
    if domain:
        add("sender_domain", domain[1].lower(), domain[0], "header:From")
    add("message_date", message.message_date, message.message_date, "header:Date")
    return facts


def resolve(search, messages, *, queries=None, complete=True):
    plausible, insufficient = [], []
    for message in {m.message_id: m for m in messages}.values():
        facts = extract(message)

        def values(key, facts=facts):
            return {f["value"] for f in facts if f["field"] == key}

        try:
            mail_date = parsedate_to_datetime(message.message_date).date()
        except (ValueError, TypeError):
            mail_date = None
        close = (
            mail_date is not None and abs((mail_date - search.transaction_date).days) <= search.days
        )
        amounts = values("amount")
        amount = amounts == {str(search.amount)} or (
            len(amounts) == 1 and money(next(iter(amounts))) == search.amount
        )
        amount = amount and values("currency") == {"EUR"}
        references = values("order_number") | values("invoice_number") | values("payment_reference")
        reference = bool(search.reference) and reference_key(search.reference) in {
            reference_key(r) for r in references
        }
        merchant = bool(search.merchant) and norm(search.merchant) in {
            norm(v) for v in values("merchant")
        }
        signals = [
            s
            for s, ok in [
                ("EXACT_AMOUNT", amount),
                ("CLOSE_DATE", close),
                ("ORDER_REFERENCE_MATCH", reference),
                ("UNDERLYING_MERCHANT_MATCH", merchant),
                ("PROCESSOR_MENTION", bool(values("processor"))),
            ]
            if ok
        ]
        payment_refs = values("payment_reference")
        conflicting_reference = bool(search.reference and payment_refs) and reference_key(
            search.reference
        ) not in {reference_key(r) for r in payment_refs}
        strong = (
            amount
            and close
            and (reference or merchant)
            and not conflicting_reference
            and not message.body_truncated
        )
        entry = {
            "message_id": message.message_id,
            "thread_id": message.thread_id,
            "facts": facts,
            "signals": signals,
            "strong": strong,
            "attachment_metadata": [a.model_dump(mode="json") for a in message.attachments],
        }
        if amount and close:
            plausible.append(entry)
        else:
            insufficient.append(entry)
    if len(plausible) > 1:
        status = "MULTIPLE_RECEIPTS"
    elif len(plausible) == 1:
        status = "RECEIPT_MATCHED" if plausible[0]["strong"] and complete else "RECEIPT_CANDIDATE"
    elif insufficient or not complete:
        status = "INSUFFICIENT_RECEIPT_EVIDENCE"
    else:
        status = "NO_RECEIPT_FOUND"
    result = {
        "version": VERSION,
        "status": status,
        "search_attempted": True,
        "display_status": "NO_RECEIPT_FOUND_IN_AVAILABLE_MAIL"
        if status == "NO_RECEIPT_FOUND"
        else status,
        "search": search.model_dump(mode="json"),
        "queries": queries or search.queries(),
        "search_complete": complete,
        "candidates": plausible,
        "insufficient": insufficient,
        "authority": "DETERMINISTIC_SOURCE_FACT",
        "searched_at": datetime.now(UTC).isoformat(),
        "limitation": (
            "No available receipt does not mean no receipt ever existed; "
            "older mail may have been deleted."
        ),
    }
    result["evidence_version"] = digest(result)
    return result


def search_receipts(client, search):
    """Only approved Gmail read operations; no threads/links followed or attachments fetched."""
    search = ReceiptSearch.model_validate(search)
    messages = {}
    complete = True
    for query in search.queries():
        raw = client.execute(
            client.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=20, includeSpamTrash=False)
        )
        complete = complete and not bool(raw.get("nextPageToken"))
        for item in raw.get("messages", [])[:20]:
            if item["id"] not in messages:
                messages[item["id"]] = client.get_message(item["id"])
    return resolve(search, list(messages.values()), complete=complete)


def receipt_events(transaction_id, result):
    """Receipt facts are source facts, never confirmed labels or merchant rules."""
    claims = []
    for candidate in result["candidates"]:
        for fact in candidate["facts"]:
            claims.append(
                Claim(
                    kind="DOCUMENT_FACT",
                    subject="gmail:" + candidate["message_id"],
                    predicate="receipt_" + fact["field"],
                    value={
                        "value": fact["value"],
                        "snippet": fact["snippet"],
                        "thread_id": fact["thread_id"],
                    },
                    authority="DETERMINISTIC_SOURCE_FACT",
                    provenance=Provenance(
                        source_type="gmail",
                        source_id=fact["message_id"],
                        source_hash=fact["content_hash"],
                        originating_field=fact["location"],
                        observed_at=fact["timestamp"],
                        extraction_method=fact["extraction_method"],
                    ),
                )
            )
        claims.append(
            Claim(
                kind="RELATIONSHIP",
                subject=transaction_id,
                predicate="receipt_email",
                value=candidate["message_id"],
                scope=transaction_id,
                authority="DETERMINISTIC_SOURCE_FACT",
                relationship_status="CONFIRMED"
                if result["status"] == "RECEIPT_MATCHED"
                else "CANDIDATE",
                provenance=Provenance(
                    source_type="gmail",
                    source_id=candidate["message_id"],
                    source_hash=digest(candidate),
                    originating_field="receipt_match.signals",
                    observed_at=result["searched_at"],
                    extraction_method=VERSION,
                ),
            )
        )
    return [KnowledgeEvent(event_type="SOURCE_PARSED", claims=tuple(claims))] if claims else []
