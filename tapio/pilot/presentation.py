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


def present(response, session, review_snapshot, *, question=None, named_subject=None):
    from tapio.pilot.answer_cards import mode_for
    from tapio.pilot.subject_identity import eligible_subject

    if question is not None:
        mode = mode_for(question, response, named_subject)
        if mode in {"QUESTION_TOO_BROAD", "UNSUPPORTED_SCOPE", "EVIDENCE_INCOMPLETE"}:
            return unsupported(session, mode, question=question)
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
    public = PilotResponse(
        answer=public_text(response["answer"], results),
        evidence_state=dominant,
        evidence_states=sorted(states),
        coverage=coverage,
        evidence=evidence,
        human_review=reviews,
        limitations=list(dict.fromkeys(limitations)),
        session=session,
    )
    if question is not None:
        from tapio.pilot.answer_cards import build_cards

        public = PilotResponse.model_validate(
            {
                **public.model_dump(mode="json"),
                **build_cards(question, response, public, named_subject),
            }
        )
    if (
        question is not None
        and eligible_subject(question, named_subject)
        and named_subject.get("status") == "NO_MATCH"
    ):
        public = public.model_copy(
            update={
                "evidence_state": "SUPPORTED",
                "evidence_states": ["SUPPORTED", "NO_MATCH"],
                "failure_category": "NO_MATCH",
            }
        )
    if (
        question is not None
        and eligible_subject(question, named_subject)
        and named_subject.get("status") == "AMBIGUOUS_IDENTITY"
    ):
        public = public.model_copy(
            update={
                "evidence_state": "AMBIGUOUS",
                "evidence_states": ["AMBIGUOUS", "HUMAN_REVIEW_REQUIRED"],
            }
        )
    return public


def unsupported(
    session,
    reason="UNSUPPORTED_SCOPE",
    *,
    failure_code=None,
    question="",
    plan=None,
    coverage_note="",
    partial_found=False,
):
    from tapio.pilot.failures import suggestions

    # Compatibility for callers of the old pilot helper; never equate incomplete with offline.
    reason = {
        "UNSUPPORTED_QUESTION": "UNSUPPORTED_SCOPE",
        "EVIDENCE_UNAVAILABLE": "EVIDENCE_INCOMPLETE",
        "MODEL_UNAVAILABLE": "INFRASTRUCTURE_UNAVAILABLE",
    }.get(reason, reason)
    explanation = {
        "QUESTION_TOO_BROAD": (
            "This question is broader than one validated evidence path. "
            "Try narrowing it to a year and one area such as bank, forestry, property, "
            "electricity, documents, or review status."
        ),
        "UNSUPPORTED_SCOPE": (
            "Tapio does not currently have a validated read-only evidence path "
            "for that type of question."
        ),
        "EVIDENCE_INCOMPLETE": (
            "I found some relevant evidence, but not enough to produce a validated "
            "answer for the full question."
            if partial_found
            else "Required evidence retrieval did not provide enough complete evidence "
            "to produce a validated answer for the full question."
        ),
        "PLAN_INVALID": (
            "I couldn't map that question to a safe supported evidence query. "
            "Try narrowing it to one year, domain, or named subject."
        ),
        "INFRASTRUCTURE_UNAVAILABLE": "A required service is unavailable. Please retry later.",
        "CONFIGURATION_ERROR": "The local pilot configuration needs attention.",
        "VALIDATION_ERROR": "The proposed answer did not pass evidence validation.",
        "AGENT_EXECUTION_ERROR": (
            "The evidence workflow could not complete because of an execution error."
        ),
        "SAFETY_REJECTION": "A safety check prevented release of the answer.",
    }[reason]
    if reason == "INFRASTRUCTURE_UNAVAILABLE":
        if (failure_code or "").startswith("DATABASE_"):
            from tapio.pilot.health import DATABASE_HELP

            explanation = DATABASE_HELP
        else:
            explanation = "The configured model service is unavailable. Please retry later."
    states = {
        "QUESTION_TOO_BROAD": ["UNSUPPORTED", "NEEDS_NARROWING"],
        "PLAN_INVALID": ["UNSUPPORTED", "NEEDS_NARROWING"],
        "EVIDENCE_INCOMPLETE": ["PARTIAL_COVERAGE", "HUMAN_REVIEW_REQUIRED"],
        "INFRASTRUCTURE_UNAVAILABLE": ["UNAVAILABLE"],
    }.get(reason, ["UNSUPPORTED", "HUMAN_REVIEW_REQUIRED"])
    narrowing = (
        suggestions(question, plan)
        if reason
        in {"QUESTION_TOO_BROAD", "PLAN_INVALID", "UNSUPPORTED_SCOPE", "EVIDENCE_INCOMPLETE"}
        else []
    )
    return PilotResponse(
        presentation_mode=reason
        if reason
        in {
            "QUESTION_TOO_BROAD",
            "UNSUPPORTED_SCOPE",
            "EVIDENCE_INCOMPLETE",
            "PLAN_INVALID",
            "INFRASTRUCTURE_UNAVAILABLE",
        }
        else "EXECUTION_ERROR",
        failure_category=reason,
        suggestions=narrowing,
        direct_answer=explanation,
        answer=explanation + " " + coverage_note + " The pilot has no source-update operations.",
        coverage_note=coverage_note,
        evidence_state=states[0],
        evidence_states=states,
        coverage=Coverage(status="UNAVAILABLE"),
        evidence=[],
        human_review=[
            Review(
                type=reason,
                summary="Narrow the question or review the available source evidence."
                if narrowing
                else "Review the reported failure before retrying.",
            )
        ],
        limitations=["No unvalidated model prose is returned."],
        session=session,
    )
