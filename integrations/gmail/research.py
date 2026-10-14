"""Explicit one-shot candidate research over MCP. No imports or attachment downloads."""

import asyncio
import json
import re
from collections import Counter
from pathlib import Path

from pydantic import Field

from tapio.tools.gmail import gmail_session, register_gmail
from tapio.tools.registry import Registry
from tapio.tools.schemas import Schema

from .cache import private_write

QUERIES = (
    (
        "SUPPLIER_TERMS_CANDIDATE",
        "from:vattenfall after:2024/12/01 before:2026/01/01 sähkösopimus -subject:uutiskirje",
    ),
    ("SUPPLIER_CONTRACT_CANDIDATE", "from:vattenfall after:2024/12/01 subject:sopimusvahvistus"),
    (
        "SUPPLIER_PRICE_CHANGE",
        "from:vattenfall after:2024/12/01 hinta -subject:lasku -subject:uutiskirje",
    ),
    ("GRID_TARIFF", "from:elenia after:2024/01/01 before:2026/04/01 hinnasto"),
    ("GRID_PRICE_CHANGE", "from:elenia after:2024/01/01 before:2026/04/01 hinta"),
    ("EXPORT_TERMS", "from:vattenfall after:2024/01/01 ylijäämäsähkö -subject:uutiskirje"),
    ("EXPORT_TERMS", "from:vattenfall after:2024/01/01 aurinkosähkö -subject:uutiskirje"),
    ("EXPORT_CONTRACT", "from:vattenfall after:2024/01/01 tuotanto -subject:uutiskirje"),
)


class Candidate(Schema):
    message_id: str
    thread_id: str
    date: str
    sender: str
    subject: str
    evidence_categories: list[str]
    attachment_count: int
    pdf_count: int
    relevant_link_count: int
    likely_coverage_period: str = "Not established; human review required"
    why_it_matters: str
    retrieved_at: str
    body_truncated: bool


class CandidateReport(Schema):
    status: str
    candidates: list[Candidate] = Field(max_length=12)
    search_count: int
    more_available: bool
    errors: list[str]
    import_state: str = "NOT_IMPORTED_REVIEW_REQUIRED"


def describe_evidence(message, query_categories):
    """Conservative hints from retrieved text, never accepted tariff facts."""
    subject = message["subject"].casefold()
    body = re.sub(r"<[^>]+>", " ", message["body"])
    period = "Not established; human review required"
    start = re.search(r"Sopimuksen alkamisaika:\s*(\d{2}\.\d{2}\.\d{4})", body, re.I)
    ending = re.search(r"päättymässä\s+(\d{2}\.\d{2}\.\d{4})", body, re.I)
    if start:
        period = "Body states contract start " + start[1] + "; not yet accepted as source evidence"
    elif ending:
        period = "Body states existing contract ends " + ending[1] + "; renewal requires review"
    if subject.startswith("lasku "):
        return (
            ["SUPPLIER_INVOICE_CANDIDATE"],
            period,
            ("Invoice PDF may document billed supplier rates; billing period requires PDF review."),
        )
    if "vahvistus" in subject and "sopim" in subject:
        return (
            ["SUPPLIER_CONTRACT_CANDIDATE"],
            period,
            (
                "Contract/order confirmation may establish supplier terms; "
                "review body or selected PDF."
            ),
        )
    if "päättyy" in subject and "sopim" in subject:
        return (
            ["SUPPLIER_RENEWAL_CANDIDATE"],
            period,
            (
                "Expiry/renewal notice may bound the previous contract; "
                "offered terms are not proof of acceptance."
            ),
        )
    return (
        sorted(set(query_categories)),
        period,
        (
            "Matched a targeted electricity query; category is a search hint, "
            "not verified effective terms."
        ),
    )


async def discover(registry):
    selected = {}
    more = False
    errors = []
    search_count = 0
    for category, query in QUERIES:
        result = await registry.call(
            "gmail_search_messages",
            {"query": query, "max_results": 5},
            session_id="electricity-evidence-research",
        )
        search_count += 1
        if not result["ok"]:
            errors.append(result["error"]["code"])
            if result["error"]["code"] in ("AUTHENTICATION_REQUIRED", "SCOPE_REJECTED"):
                break
            continue
        more |= result["data"]["more_available"]
        for item in result["data"]["items"]:
            if any(word in item["subject"].casefold() for word in ("uutiskirje", "newsletter")):
                continue
            mid = item["message_id"]
            if mid not in selected and len(selected) >= 12:
                more = True
                continue
            selected.setdefault(mid, {"metadata": item, "categories": []})["categories"].append(
                category
            )
    candidates = []
    for mid, entry in selected.items():
        result = await registry.call(
            "gmail_get_message", {"message_id": mid}, session_id="electricity-evidence-research"
        )
        if not result["ok"]:
            errors.append(result["error"]["code"])
            continue
        m = result["data"]
        # Link relevance is a lexical candidate hint only; no destination is fetched.
        links = [
            url
            for url in m["links"]
            if any(
                word in url.lower()
                for word in (".pdf", "sopimus", "hinta", "tariff", "contract", "price", "tuotanto")
            )
        ]
        categories, period, reason = describe_evidence(m, entry["categories"])
        candidates.append(
            Candidate(
                message_id=mid,
                thread_id=m["thread_id"],
                date=m["message_date"],
                sender=m["sender"],
                subject=m["subject"],
                evidence_categories=categories,
                attachment_count=len(m["attachments"]),
                pdf_count=sum(a["mime_type"] == "application/pdf" for a in m["attachments"]),
                relevant_link_count=len(links),
                likely_coverage_period=period,
                why_it_matters=reason,
                retrieved_at=m["retrieved_at"],
                body_truncated=m["body_truncated"],
            )
        )
    return CandidateReport(
        status="INCOMPLETE"
        if errors
        else "CANDIDATES_READY"
        if candidates
        else "NO_MATCHING_MESSAGES",
        candidates=candidates,
        search_count=search_count,
        more_available=more,
        errors=sorted(set(errors)),
    )


async def research(output):
    async with gmail_session() as session:
        registry = Registry()
        register_gmail(registry, session)
        report = await discover(registry)
    private_write(output, report.model_dump_json(indent=2).encode())
    return report


def main():
    import argparse

    p = argparse.ArgumentParser(
        description="One-shot narrow electricity email search; stop before import."
    )
    p.add_argument("--output", type=Path, default=Path("data/interim/gmail/candidate_report.json"))
    args = p.parse_args()
    r = asyncio.run(research(args.output))
    print(
        json.dumps(
            {
                "status": r.status,
                "candidate_count": len(r.candidates),
                "search_count": r.search_count,
                "pdf_candidates": sum(c.pdf_count for c in r.candidates),
                "link_candidates": sum(c.relevant_link_count for c in r.candidates),
                "categories": dict(Counter(k for c in r.candidates for k in c.evidence_categories)),
                "more_available": r.more_available,
                "errors": r.errors,
                "import_state": r.import_state,
            }
        )
    )
    if r.errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
