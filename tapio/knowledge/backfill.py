"""Explicit offline derivation from immutable snapshots; never opens a source writer."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from data_pipeline.ingest.bank_fields import BANK_FIELDS
from tapio.knowledge.fields import SOURCE_FIELDS, source_text_fields
from tapio.knowledge.models import (
    Authority,
    Claim,
    EventType,
    Kind,
    KnowledgeEvent,
    Provenance,
    digest,
)
from tapio.pilot.concepts import CONCEPTS, FINNISH, SPANISH
from tapio.pilot.subject_identity import REGISTRY, resolve_subject
from tapio.pilot.transaction_search import normalize_text


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def accrue(tables: dict, *, observed_at: datetime) -> list[KnowledgeEvent]:
    events = []

    def add(
        kind,
        subject,
        predicate,
        value,
        row,
        field,
        *,
        source="transactions",
        authority=Authority.DETERMINISTIC_SOURCE_FACT,
        scope="",
        single=False,
        relationship_status=None,
        confirmation=None,
        event_type=EventType.SOURCE_PARSED,
    ):
        provenance = Provenance(
            source_type=source,
            source_id=str(row.get("id", source)),
            source_hash=row["sha256"] if set(row) == {"id", "sha256"} else digest(row),
            originating_field=field,
            observed_at=observed_at,
            extraction_method="knowledge-backfill-v1",
            confirmation_id=confirmation,
        )
        events.append(
            KnowledgeEvent(
                event_type=event_type,
                claims=(
                    Claim(
                        kind=kind,
                        subject=subject,
                        predicate=predicate,
                        value=value,
                        scope=scope,
                        authority=authority,
                        provenance=provenance,
                        single_valued=single,
                        relationship_status=relationship_status,
                    ),
                ),
            )
        )

    txs = tables.get("transactions", [])
    names = {t.get("normalized_counterparty") for t in txs if t.get("normalized_counterparty")}
    merchant_by_tx = {}
    for t in txs:
        name = t.get("normalized_counterparty") or t.get("raw_counterparty")
        if name:
            merchant_by_tx[t["id"]] = resolve_subject(name, names)["canonical_subject"] or name
    for t in txs:
        name = t.get("normalized_counterparty") or t.get("raw_counterparty")
        if name:
            resolution = resolve_subject(name, names)
            merchant = resolution["canonical_subject"] or name
            merchant_by_tx[t["id"]] = merchant
            add(Kind.ENTITY, merchant, "observed_identity", merchant, t, "normalized_counterparty")
            if sum(m == merchant for m in merchant_by_tx.values()) >= 2:
                add(
                    Kind.RECURRING_PATTERN,
                    merchant,
                    "bank_occurrence",
                    {"pattern": "REPEATED_MERCHANT", "cadence": "NOT_ESTABLISHED"},
                    t,
                    "id",
                )
            raw = t.get("raw_counterparty")
            if raw and normalize_text(raw) != normalize_text(name):
                add(
                    Kind.ENTITY_ALIAS,
                    merchant,
                    "candidate_alias",
                    raw,
                    t,
                    "raw_counterparty/normalized_counterparty",
                    authority=Authority.SUGGESTED,
                )
        for field, text in source_text_fields(t).items():
            source_name = field.removeprefix("raw_source.")
            spec = BANK_FIELDS.get(source_name)
            if spec and not spec.vocabulary:
                continue
            if not text or not text.strip():
                continue
            if field.startswith("raw_source."):
                add(
                    Kind.DOCUMENT_FACT,
                    t["id"],
                    "observed_source_text",
                    {"field": field, "text": text},
                    t,
                    field,
                )
            if len(text) <= 120:
                add(
                    Kind.VOCABULARY,
                    normalize_text(text),
                    "observed_term",
                    {
                        "term": text,
                        "normalized": normalize_text(text),
                        "language": "fi" if field == "raw_source.Selitys" else "und",
                        "concept": None,
                    },
                    t,
                    field,
                )
        for key in t.get("raw_source") or {}:
            if key not in BANK_FIELDS:
                add(
                    Kind.SOURCE_FIELD_MEANING,
                    "raw_source." + key,
                    "field_definition",
                    {"searchable": False, "meaning": None},
                    t,
                    "raw_source." + key,
                    authority=Authority.UNKNOWN,
                )
    # Registry claims describe existing reviewed software mappings, not new guesses.
    registry_source = {
        "id": "tapio/pilot/subject_identity.py",
        "sha256": file_hash("tapio/pilot/subject_identity.py"),
    }
    for merchant in sorted(set(merchant_by_tx.values())):
        if merchant in REGISTRY:
            for alias in (*REGISTRY[merchant].aliases, *REGISTRY[merchant].bank_descriptors):
                add(
                    Kind.ENTITY_ALIAS,
                    merchant,
                    "accepted_alias",
                    alias,
                    registry_source,
                    "REGISTRY." + merchant,
                    source="reviewed_identity_registry",
                )
        # Legal suffix normalization is an existing deterministic resolver operation.
        from tapio.pilot.subject_identity import legal_key

        alias = legal_key(merchant)
        if alias != normalize_text(merchant):
            add(
                Kind.ENTITY_ALIAS,
                merchant,
                "accepted_alias",
                alias,
                registry_source,
                "legal_key",
                source="reviewed_identity_registry",
            )
    for review in tables.get("transaction_label_reviews", []):
        if review["review_status"] != "REVIEWED":
            continue
        tx_id = review["transaction_id"]
        confirmation = review["review_file_sha256"]
        for field in ("confirmed_category", "confirmed_business_context"):
            add(
                Kind.RELATIONSHIP,
                tx_id,
                field,
                review[field],
                review,
                field,
                source="transaction_label_reviews",
                authority=Authority.HUMAN_CONFIRMED,
                single=True,
                confirmation=confirmation,
                relationship_status="CONFIRMED",
                event_type=EventType.HUMAN_REVIEW_CONFIRMED,
            )
        if tx_id in merchant_by_tx:
            add(
                Kind.MERCHANT_OBSERVATION,
                merchant_by_tx[tx_id],
                "reviewed_context_observation",
                review["confirmed_business_context"],
                review,
                "confirmed_business_context",
                source="transaction_label_reviews",
                authority=Authority.HUMAN_CONFIRMED,
                scope=tx_id,
                single=True,
                confirmation=confirmation,
                event_type=EventType.HUMAN_REVIEW_CONFIRMED,
            )
    fields_source = {
        "id": "tapio/knowledge/fields.py",
        "sha256": file_hash("tapio/knowledge/fields.py"),
    }
    for name, (path, meaning) in SOURCE_FIELDS.items():
        add(
            Kind.SOURCE_FIELD_MEANING,
            name,
            "field_definition",
            {"searchable": True, "path": path, "meaning": meaning},
            fields_source,
            "SOURCE_FIELDS." + name,
            source="reviewed_search_field_registry",
            single=True,
        )
    for name, spec in BANK_FIELDS.items():
        add(
            Kind.SOURCE_FIELD_MEANING,
            "raw_source." + name,
            "csv_field_contract",
            {
                "classification": spec.classification,
                "stored": spec.stored,
                "meaning": spec.meaning,
                "searchable": spec.searchable,
                "reconciliation": spec.reconciliation,
                "exclusion": spec.exclusion,
            },
            {
                "id": "data_pipeline/ingest/bank_fields.py",
                "sha256": file_hash("data_pipeline/ingest/bank_fields.py"),
            },
            "BANK_FIELDS." + name,
            source="importer_schema_registry",
            single=True,
        )
    catalog = {"id": "tapio/pilot/concepts.py", "sha256": file_hash("tapio/pilot/concepts.py")}
    for concept, terms in CONCEPTS.items():
        add(
            Kind.SEARCH_TERM_MAPPING,
            concept,
            "accepted_expansion",
            {"terms": list(terms)},
            catalog,
            "CONCEPTS." + concept,
            source="reviewed_multilingual_catalog",
            single=True,
        )
        for term in terms:
            add(
                Kind.VOCABULARY,
                concept,
                "catalog_term",
                {
                    "term": term,
                    "normalized": normalize_text(term),
                    "language": (
                        "fi"
                        if normalize_text(term) in FINNISH
                        else "es"
                        if normalize_text(term) in SPANISH
                        else "en"
                        if term == concept
                        else "und"
                    ),
                    "concept": concept,
                },
                catalog,
                "CONCEPTS." + concept,
                source="reviewed_multilingual_catalog",
            )
    for doc in tables.get("documents", []):
        for field in ("document_type", "document_date", "sha256"):
            if doc.get(field) is not None:
                add(
                    Kind.DOCUMENT_FACT,
                    doc["id"],
                    field,
                    doc[field],
                    doc,
                    field,
                    source="documents",
                    single=True,
                )
        metadata = doc.get("metadata", {})
        vendor = metadata.get("vendor")
        if vendor:
            add(
                Kind.RELATIONSHIP,
                vendor,
                "has_document",
                doc["id"],
                doc,
                "metadata.vendor",
                source="documents",
                relationship_status="CONFIRMED",
            )
    for invoice in tables.get("invoices", []):
        for field in (
            "vendor",
            "invoice_number",
            "invoice_date",
            "due_date",
            "subtotal_eur",
            "vat_eur",
            "total_eur",
        ):
            if invoice.get(field) is not None:
                add(
                    Kind.DOCUMENT_FACT,
                    invoice["id"],
                    field,
                    invoice[field],
                    invoice,
                    field,
                    source="invoices",
                    single=True,
                )
        add(
            Kind.RELATIONSHIP,
            invoice["vendor"],
            "has_invoice",
            invoice["id"],
            invoice,
            "vendor/document_id",
            source="invoices",
            relationship_status="CONFIRMED",
        )
        add(
            Kind.RELATIONSHIP,
            invoice["id"],
            "has_document",
            invoice["document_id"],
            invoice,
            "document_id",
            source="invoices",
            relationship_status="CONFIRMED",
        )
    for allocation in tables.get("transaction_invoice_allocations", []):
        status = allocation["status"]
        add(
            Kind.RELATIONSHIP,
            allocation["invoice_id"],
            "bank_allocation",
            {
                "transaction_id": allocation["transaction_id"],
                "amount_eur": allocation["allocated_amount_eur"],
                "match_method": allocation["match_method"],
            },
            allocation,
            "transaction_id/status",
            source="transaction_invoice_allocations",
            relationship_status=status,
            authority=Authority.DETERMINISTIC_SOURCE_FACT
            if status == "CONFIRMED"
            else Authority.SUGGESTED,
        )
    reversals = tables.get("transaction_reversal_candidates", [])
    for reversal in reversals:
        count = sum(r["credit_id"] == reversal["credit_id"] for r in reversals)
        add(
            Kind.RELATIONSHIP,
            reversal["credit_id"],
            "possible_reversal",
            reversal["debit_id"],
            reversal,
            "debit_id/credit_id/evidence",
            source="transaction_reversal_candidates",
            relationship_status="AMBIGUOUS" if count > 1 else "CANDIDATE",
            authority=Authority.SUGGESTED,
        )
    return events


def accepted_contract_events(mapping_path: Path, acceptance_path: Path, *, observed_at: datetime):
    """Explicit accepted mapping only. Never copy email bodies or review excerpts."""
    mapping = json.loads(mapping_path.read_text())
    acceptance = json.loads(acceptance_path.read_text())
    if acceptance["authority"] != "EXPLICIT_USER_DECISION" or acceptance[
        "mapping_sha256"
    ] != file_hash(mapping_path):
        raise ValueError("CONTRACT_ACCEPTANCE_CHAIN_INVALID")
    events = []
    fields = (
        "supplier",
        "product",
        "pricing_type",
        "contract_type",
        "start_date",
        "end_date",
        "price_valid_from",
        "price_valid_to",
        "energy_snt_per_kwh",
        "monthly_fee_eur",
        "vat_percent",
        "vat_basis",
    )
    for contract in mapping:
        if (
            contract["authority"] != "HUMAN_CONFIRMED"
            or contract["reviewed_source"]["review_sha256"] != acceptance["review_sha256"]
            or file_hash(contract["review_path"]) != acceptance["review_sha256"]
        ):
            raise ValueError("CONTRACT_REVIEW_CHAIN_INVALID")
        scope = digest(
            {
                "meter": contract["meter_sha256"],
                "start": contract["start_date"],
                "product": contract["product"],
            }
        )
        for field in fields:
            if contract.get(field) is None:
                continue
            p = Provenance(
                source_type="ACCEPTED_GMAIL_CONTRACT",
                source_id=str(mapping_path),
                source_hash=file_hash(mapping_path),
                originating_field=field,
                observed_at=observed_at,
                extraction_method="accepted-mapping-v1",
                confirmation_id=acceptance["decision_sha256"],
            )
            c = Claim(
                kind=Kind.CONTRACT_FACT,
                subject=contract["supplier"],
                predicate=field,
                scope=scope,
                value=contract[field],
                authority=Authority.HUMAN_CONFIRMED,
                provenance=p,
                single_valued=True,
            )
            events.append(KnowledgeEvent(event_type=EventType.DOCUMENT_REVIEWED, claims=(c,)))
        p = p.model_copy(update={"originating_field": "reviewed_source"})
        link = Claim(
            kind=Kind.RELATIONSHIP,
            subject=contract["supplier"],
            predicate="has_contract",
            value={
                "contract_scope": scope,
                "review_sha256": acceptance["review_sha256"],
                "document_sha256": contract["reviewed_source"]["pdf_download_sha256"],
                "source_message_ids": contract["reviewed_source"]["source_message_ids"],
            },
            authority=Authority.HUMAN_CONFIRMED,
            provenance=p,
            relationship_status="CONFIRMED",
        )
        events.append(KnowledgeEvent(event_type=EventType.DOCUMENT_REVIEWED, claims=(link,)))
    return events


def reviewed_email_events(path: Path) -> list[KnowledgeEvent]:
    """Only previously accepted field observations; never persist body/subject/excerpts."""
    from email.utils import parseaddr

    source = json.loads(path.read_text())
    if not source.get("accepted_at") or source.get("import_status") != "BODY_EVIDENCE":
        return []
    allowed = {
        "previous_contract.end_date",
        "new_contract.product",
        "new_contract.start_date",
        "new_contract.contract_type",
        "new_contract.duration_months",
        "new_contract.energy_snt_per_kwh",
        "new_contract.monthly_fee_eur",
        "new_contract.vat_percent",
        "new_contract.vat_basis",
    }
    claims = []
    observed = datetime.fromisoformat(source["accepted_at"].replace("Z", "+00:00"))
    for field, value in source.get("accepted_fields", {}).items():
        if field not in allowed:
            continue
        p = Provenance(
            source_type="REVIEWED_GMAIL_EVIDENCE",
            source_id=source["external_message_id"],
            source_hash=source["content_hash"],
            originating_field="accepted_fields." + field,
            observed_at=observed,
            extraction_method="accepted-email-fields-v1",
        )
        claims.append(
            Claim(
                kind=Kind.CONTRACT_FACT,
                subject=source["external_message_id"],
                predicate=field,
                value=value,
                authority=Authority.DETERMINISTIC_SOURCE_FACT,
                provenance=p,
                single_valued=True,
            )
        )
    sender = parseaddr(source.get("sender", ""))[1]
    if claims and "@" in sender:
        claims.append(
            Claim(
                kind=Kind.DOCUMENT_FACT,
                subject=source["external_message_id"],
                predicate="sender_domain",
                value=sender.rsplit("@", 1)[1].casefold(),
                authority=Authority.DETERMINISTIC_SOURCE_FACT,
                provenance=p.model_copy(update={"originating_field": "sender"}),
            )
        )
    return (
        [KnowledgeEvent(event_type=EventType.DOCUMENT_REVIEWED, claims=tuple(claims))]
        if claims
        else []
    )


def reviewed_export_decision_events(path: Path, *, observed_at: datetime) -> list[KnowledgeEvent]:
    """Persist the explicitly recorded property-specific decision, never broaden its scope."""
    source = json.loads(path.read_text())
    decision = source["human_decision"]
    if decision.get("source") != "HUMAN_CONFIRMED_PROPERTY_CONTEXT":
        raise ValueError("EXPORT_HUMAN_DECISION_REQUIRED")
    claims = []
    for field in (
        "applicable_margin_snt_per_kwh",
        "customer_vat_liability",
        "effective_applicability_boundary",
        "scope",
    ):
        p = Provenance(
            source_type="REVIEWED_EXPORT_DECISION",
            source_id=str(path),
            source_hash=file_hash(path),
            originating_field="human_decision." + field,
            observed_at=observed_at,
            extraction_method="export-decision-v1",
            confirmation_id=decision["request_sha256"],
        )
        claims.append(
            Claim(
                kind=Kind.CONTRACT_FACT,
                subject="Vattenfall Oy",
                predicate=field,
                value=decision[field],
                scope=decision["scope"],
                single_valued=True,
                authority=Authority.HUMAN_CONFIRMED,
                provenance=p,
            )
        )
    return [KnowledgeEvent(event_type=EventType.HUMAN_REVIEW_CONFIRMED, claims=tuple(claims))]
