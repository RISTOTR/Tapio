"""Evidence-derived presentation only; never financial arithmetic or model prose."""

import re

from tapio.agent.acceptance.planning import evidence_states
from tapio.agent.render import money
from tapio.pilot.contracts import (
    BankCoverage,
    Coverage,
    EnergyCoverage,
    Evidence,
    PilotResponse,
    Review,
    ReviewCoverage,
)

TITLES = {
    "summarize_finances": "Bank cash flow with human-reviewed classifications",
    "query_transactions": "Transaction review evidence",
    "find_invoices": "Stored invoice evidence and payment states",
    "get_invoice": "Stored invoice evidence and payment state",
    "get_invoice_reconciliation": "Read-only invoice reconciliation evidence",
    "query_forestry_sales": "Forestry sale source documents; payment is not implied",
    "get_forestry_sale": "Forestry sale source document; payment is not implied",
    "list_documents": "Source-document catalog and parser provenance",
    "get_document_summary": "Source-document metadata and parser provenance",
    "get_saved_energy_comparison": "Accepted fixed-versus-spot electricity comparison",
}


def provenance(value):
    """Retain identifiers and parser/review provenance, not full document text."""
    if isinstance(value, list):
        return [v for item in value if (v := provenance(item))]
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if (
            key == "id"
            or key.endswith(("_id", "_ids", "_sha256"))
            or key in ("sha256", "parser_version", "label_authority", "kind", "state")
        ):
            result[key] = item
        elif isinstance(item, (dict, list)):
            nested = provenance(item)
            if nested:
                result[key] = nested
    return result


def public_text(text, results):
    identifiers = set()

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key == "id"
                    or key.endswith(("_id", "_ids"))
                    or key in ("iban", "account_number", "invoice_number")
                ):
                    identifiers.update(
                        str(v)
                        for v in (item if isinstance(item, list) else [item])
                        if v is not None and len(str(v)) >= 6
                    )
                elif isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(results)
    for identifier in sorted(identifiers, key=len, reverse=True):
        text = text.replace(identifier, "[private identifier]")
    text = re.sub(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){10,30}\b", "[bank identifier]", text)
    return re.sub(
        r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", "[private identifier]", text
    )


def present(response, session, review_snapshot):
    results = response["results"]
    states = set(evidence_states(response))
    coverage = Coverage(status="DETERMINED")
    evidence, reviews, limitations = [], [], []
    seen_reviews = set()
    for result in results:
        if not result.get("ok"):
            continue
        name, data = result["tool"], result["data"]
        items = data.get("items", [data])
        evidence.append(Evidence(kind=name, summary=TITLES[name], records=len(items)))
        if name == "summarize_finances":
            coverage.bank.append(
                BankCoverage(
                    requested_from=data["date_from"],
                    requested_to=data["date_to"],
                    observed_from=data["observed_first_date"],
                    observed_to=data["observed_last_date"],
                    context=data["context_filter"],
                    selected_rows=data["transaction_count"],
                    human_reviewed=data["confirmed_count"],
                    unresolved=data["unresolved_count"],
                    excluded_unknown_context_rows=data["excluded_unresolved_context_count"],
                )
            )
            if data["date_from"].startswith(str(review_snapshot["year"])):
                coverage = coverage.model_copy(
                    update={
                        "snapshot_review": ReviewCoverage(
                            **{
                                k: review_snapshot[k]
                                for k in ("year", "total", "human_reviewed", "unresolved")
                            }
                        )
                    }
                )
            limitations.append(
                "Imported bank rows do not establish a complete statement or calendar year."
            )
            if data["unresolved_count"] or data["excluded_unresolved_context_count"]:
                reviews.append(
                    Review(
                        type="UNREVIEWED_TRANSACTIONS",
                        summary=(
                            f"Selected rows: {data['unresolved_count']} unresolved; "
                            f"{data['excluded_unresolved_context_count']} unknown-context rows "
                            "excluded by the context filter."
                        ),
                    )
                )
        elif name == "get_saved_energy_comparison":
            coverage.energy.append(EnergyCoverage(supported_months=data["months"]))
            limitations.append(
                "Electricity comparison covers only the listed months and models unchanged "
                "consumption; it is not a realized supplier switch."
            )
        elif name in (
            "list_documents",
            "get_document_summary",
            "find_invoices",
            "get_invoice",
            "query_forestry_sales",
            "get_forestry_sale",
        ):
            coverage.documents.append(
                "Stored source evidence only; missing imported documents do not establish "
                "zero expense or income."
            )
            for item in items:
                parser = item.get("parser_version")
                if parser:
                    coverage.documents.append(
                        "Parsed source evidence has recorded parser provenance; "
                        "payment and tax treatment are separate."
                    )
                else:
                    coverage.documents.append(
                        "Parser provenance is unavailable in this projection; "
                        "catalog presence alone does not establish reviewed contents."
                    )
        if name in ("find_invoices", "get_invoice", "get_invoice_reconciliation"):
            for item in items:
                rec = item.get("reconciliation", item)
                key = rec.get("invoice_id", item.get("id", str(rec)))
                if rec.get("state") == "AMBIGUOUS" and key not in seen_reviews:
                    seen_reviews.add(key)
                    pairs = len(rec.get("reversal_candidates", []))
                    summary = (
                        "Payment/reversal evidence remains ambiguous; "
                        "the exact reversed debit is not established."
                    )
                    if rec.get("candidate_net_outflow_eur") is not None:
                        summary += (
                            " Candidate net outflow EUR "
                            + money(rec["candidate_net_outflow_eur"])
                            + " is not confirmed settlement."
                        )
                    if pairs:
                        summary += f" {pairs} candidate reversal pairs remain preserved."
                    reviews.append(Review(type="AMBIGUOUS_PAYMENT", summary=summary))
                elif rec.get("human_review_required") and key not in seen_reviews:
                    seen_reviews.add(key)
                    states.add("HUMAN_REVIEW_REQUIRED")
                    reviews.append(
                        Review(
                            type="UNRESOLVED_PAYMENT",
                            summary="Payment reconciliation requires human review.",
                        )
                    )
        if name == "query_transactions" and any(
            i.get("label_authority") == "UNREVIEWED" for i in items
        ):
            states.add("HUMAN_REVIEW_REQUIRED")
            reviews.append(
                Review(
                    type="UNREVIEWED_TRANSACTIONS",
                    summary=(
                        f"{len(items)} retrieved transaction rows on this page; "
                        "unreviewed labels remain unresolved."
                    ),
                )
            )
    if response.get("message", "").startswith("Tax treatment"):
        limitations.append(
            "Tapio does not decide tax deductibility. "
            "Human-confirmed business context is not a tax decision."
        )
        reviews.append(
            Review(
                type="TAX_REVIEW",
                summary="Available source facts require a separate human tax review.",
            )
        )
    coverage = coverage.model_copy(update={"documents": list(dict.fromkeys(coverage.documents))})
    dominant = next(
        s
        for s in (
            "UNSUPPORTED",
            "AMBIGUOUS",
            "HUMAN_REVIEW_REQUIRED",
            "PARTIAL_COVERAGE",
            "SUPPORTED",
        )
        if s in states
    )
    return PilotResponse(
        answer=public_text(response["answer"], results),
        evidence_state=dominant,
        evidence_states=sorted(states),
        coverage=coverage,
        evidence=evidence,
        human_review=reviews,
        limitations=list(dict.fromkeys(limitations)),
        session=session,
    )


def unsupported(session):
    return PilotResponse(
        answer=(
            "A validated evidence-backed answer is not available. "
            "The pilot has no source-update operations."
        ),
        evidence_state="UNSUPPORTED",
        evidence_states=["UNSUPPORTED", "HUMAN_REVIEW_REQUIRED"],
        coverage=Coverage(status="UNAVAILABLE"),
        evidence=[],
        human_review=[
            Review(
                type="UNSUPPORTED_REQUEST",
                summary="Please clarify the question or review the available source evidence.",
            )
        ],
        limitations=["No unvalidated model prose is returned."],
        session=session,
    )
