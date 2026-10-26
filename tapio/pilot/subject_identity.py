"""One conservative identity contract for every pilot subject intent. No context rules."""

import re
import unicodedata
from typing import Literal

from pydantic import Field

from apps.api.app.domain.enums import BusinessContext, TransactionCategory
from data_pipeline.normalize.bank import ALIASES
from tapio.tools.schemas import Schema


class IdentityAliases(Schema):
    aliases: tuple[str, ...] = ()
    bank_descriptors: tuple[str, ...] = ()


# Existing exact import aliases, plus identities inspected read-only in the pilot.
# Elenia's brand is explicitly tied to its imported legal entity, never prefix-matched.
# Spelling variants of K-Rauta refer to the same observed brand, not arbitrary stores.
REGISTRY = {
    name: IdentityAliases(aliases=tuple(a for a, n in ALIASES.items() if n == name))
    for name in sorted(set(ALIASES.values()))
}
REGISTRY.update(
    {
        "Elenia Verkko Oyj": IdentityAliases(aliases=("Elenia", "Elenia Verkko Oy")),
        "Oikea Konekauppa": IdentityAliases(bank_descriptors=("oikea konekaupp viitasaari",)),
        "K-Rauta": IdentityAliases(
            aliases=("Krauta", "K Rauta"), bank_descriptors=("k-rauta viitasaari pielavesi",)
        ),
    }
)

MatchMethod = Literal[
    "CANONICAL_EXACT",
    "ALIAS_EXACT",
    "LEGAL_SUFFIX_NORMALIZED",
    "BANK_DESCRIPTOR_ALIAS",
    "AMBIGUOUS_IDENTITY",
    "NO_MATCH",
]


class SubjectIdentity(Schema):
    canonical_name: str
    aliases: list[str]
    normalized_aliases: list[str]
    subject_types: list[str] = Field(default_factory=list)
    matched_source_identifiers: dict[str, list[str]] = Field(default_factory=dict)


class SubjectResolution(Schema):
    status: Literal["MATCH_FOUND", "NO_MATCH", "AMBIGUOUS_IDENTITY"]
    canonical_subject: str | None
    identity: SubjectIdentity | None
    names: list[str]
    method: MatchMethod
    aliases_considered: list[str]
    source_match_methods: dict[str, MatchMethod]


def normalize_subject(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    value = "".join(" " if unicodedata.category(c) == "Pd" or c == "," else c for c in value)
    return " ".join(value.replace(".", "").split())


def legal_key(value):
    return re.sub(r"\s+(oy|oyj|ry)$", "", normalize_subject(value))


def subject_intent(question):
    q = normalize_subject(question)
    if re.search(r"\b(deduct\w*|tax treatment|tax advice|vat reclaim)\b", q):
        return "TAX_BOUNDARY"
    if re.search(r"\breconcil\w*\b|\bsettlement\b|\brefund\w*\b", q):
        return "RECONCILIATION_LOOKUP"
    if re.search(r"\bhow much\b|\btotal\b|\bspen[dt]\b", q):
        return "FINANCIAL_TOTAL"
    if re.search(r"\b(invoices?|documents?|receipts?)\b", q):
        return "DOCUMENT_LOOKUP"
    return "EVIDENCE_LOOKUP"


# Generic evidence/domain phrases cannot identify a merchant, even in entity-like grammar.
GENERIC_SUBJECT_WORDS = {
    "finances",
    "financial",
    "finance",
    "data",
    "property",
    "forestry",
    "electricity",
    "transactions",
    "transaction",
    "documents",
    "document",
    "invoices",
    "invoice",
    "receipts",
    "receipt",
    "payments",
    "payment",
    "income",
    "expenses",
    "expense",
    "coverage",
    "review",
    "status",
    "issues",
    "evidence",
    "bank",
    "personal",
    "unknown",
    "tax",
    "taxes",
    "context",
    "category",
    "categories",
    "records",
    "imported",
    "unresolved",
    "summary",
    "overview",
    "information",
    "things",
    "this",
    "that",
    "it",
    "everything",
    "overall",
    "all",
    "the",
    "my",
    "our",
    "of",
    "in",
    "so",
    "far",
    "still",
    "incomplete",
    "complete",
    "query_transactions",
    "summarize_finances",
    "list_documents",
    "find_invoices",
}


GENERIC_SUBJECT_WORDS.update(
    word
    for label in [*BusinessContext, *TransactionCategory]
    for word in label.value.casefold().split("_")
)
GENERIC_SUBJECT_WORDS.update(
    {
        "bank",
        "cash",
        "flow",
        "get_invoice_reconciliation",
        "get_document_summary",
        "get_invoice",
        "query_forestry_sales",
        "get_saved_energy_comparison",
    }
)


def generic_subject(value):
    normalized = normalize_subject(value)
    if normalized in GENERIC_SUBJECT_WORDS:
        return True
    tokens = set(re.findall(r"[^\W_]+", normalized))
    return bool(tokens) and all(t in GENERIC_SUBJECT_WORDS or t.isdigit() for t in tokens)


def eligible_subject(question, resolution):
    """An explicit candidate AND a completed matching resolution are required.

    NO_MATCH can have no canonical identity, but must retain the actual queried candidate.
    """
    request = extract_subject(question)
    if request is None or not resolution:
        return False
    retained = resolution.get("request") or {}
    if (
        retained.get("normalized") != request["normalized"]
        or retained.get("year") != request["year"]
    ):
        return False
    if resolution.get("status") not in {"MATCH_FOUND", "NO_MATCH", "AMBIGUOUS_IDENTITY"}:
        return False
    if not resolution.get("trace", {}).get("inventory_queried"):
        return False
    return resolution["status"] != "MATCH_FOUND" or bool(resolution.get("identity"))


def extract_subject(question):
    """Extract an explicit subject phrase independently of tax/payment/evidence intent.

    Relations and object phrases are generic grammar, not merchant/question templates.
    Unsupported compound/relative scopes are left to the accepted path without guessing.
    """
    q = " ".join(unicodedata.normalize("NFKC", question).split()).strip().rstrip("?.")
    years = set(re.findall(r"\b20\d{2}\b", q))
    if len(years) > 1 or re.search(r"\b(since|between|last|yesterday|quarter)\b", q, re.I):
        return None
    year = next(iter(years)) if years else None
    if year:
        # Only an explicit year suffix; do not interpret a year embedded in an entity name.
        if not re.search(r"\bin " + year + r"$", q, re.I):
            return None
        q = re.sub(r"\s+in " + year + r"$", "", q, flags=re.I)
    q = re.sub(r"\s+(?:from taxes|for tax purposes)$", "", q, flags=re.I)
    match = re.search(
        r"\b(?:for|from|about|at|to|with|pay|paid|deduct)\s+"
        r"(?:(?:to|at|the)\s+)*(.+)$",
        q,
        re.I,
    )
    if match is None:
        match = re.fullmatch(
            r"(?:show|list|find|review|reconcile)\s+(?:me\s+)?(?:the\s+)?"
            r"(.+?)\s+(?:invoices|documents|receipts|payments|purchases)",
            q,
            re.I,
        )
    if match is None:
        match = re.fullmatch(r"Are (.+?) purchases deductible", q, re.I)
    if match is None:
        return None
    subject = re.sub(
        r"\s+(?:purchases|payments|invoices|documents|receipts)$", "", match[1], flags=re.I
    )
    normalized = normalize_subject(subject)
    if (
        not 2 <= len(subject) <= 100
        or not any(c.isalpha() for c in subject)
        or re.search(r"\b(and|or|my|our)\b|[€?]", subject, re.I)
        or generic_subject(subject)
    ):
        return None
    return {"text": subject, "normalized": normalized, "year": year, "type": "NAMED_ENTITY"}


def resolve_subject(subject, names):
    """Resolve against observed identities; registered aliases never manufacture evidence."""
    catalog = {}
    for name in sorted({n for n in names if n}):
        key = normalize_subject(name)
        known = [
            canonical
            for canonical, entry in REGISTRY.items()
            if key
            in {normalize_subject(a) for a in (canonical, *entry.aliases, *entry.bank_descriptors)}
        ]
        if len(known) > 1:
            raise ValueError("SUBJECT_ALIAS_REGISTRY_COLLISION")
        canonical = known[0] if known else name
        group = catalog.setdefault(normalize_subject(canonical), {"name": canonical, "sources": []})
        group["sources"].append(name)
    key = normalize_subject(subject)
    candidates, method = [], "NO_MATCH"
    for kind in (
        "CANONICAL_EXACT",
        "ALIAS_EXACT",
        "LEGAL_SUFFIX_NORMALIZED",
        "BANK_DESCRIPTOR_ALIAS",
    ):
        for group in catalog.values():
            canonical = group["name"]
            entry = REGISTRY.get(canonical, IdentityAliases())
            match = {
                "CANONICAL_EXACT": key == normalize_subject(canonical),
                "ALIAS_EXACT": key in {normalize_subject(a) for a in entry.aliases},
                "LEGAL_SUFFIX_NORMALIZED": legal_key(subject)
                in {legal_key(a) for a in (canonical, *entry.aliases)},
                "BANK_DESCRIPTOR_ALIAS": key
                in {normalize_subject(a) for a in entry.bank_descriptors},
            }[kind]
            if match:
                candidates.append(group)
        if candidates:
            method = kind
            break
    considered = sorted(
        {
            alias
            for g in candidates
            for alias in (
                g["name"],
                *REGISTRY.get(g["name"], IdentityAliases()).aliases,
                *REGISTRY.get(g["name"], IdentityAliases()).bank_descriptors,
            )
        }
    )
    if len(candidates) != 1:
        status = "AMBIGUOUS_IDENTITY" if candidates else "NO_MATCH"
        return SubjectResolution(
            status=status,
            canonical_subject=None,
            identity=None,
            names=[],
            method=status,
            aliases_considered=considered,
            source_match_methods={},
        ).model_dump(mode="json")
    group = candidates[0]
    canonical, sources = group["name"], group["sources"]
    entry = REGISTRY.get(canonical, IdentityAliases())
    aliases = sorted({canonical, *entry.aliases, *entry.bank_descriptors, *sources})
    source_methods = {
        n: "BANK_DESCRIPTOR_ALIAS"
        if normalize_subject(n) in {normalize_subject(a) for a in entry.bank_descriptors}
        else "CANONICAL_EXACT"
        if normalize_subject(n) == normalize_subject(canonical)
        else "ALIAS_EXACT"
        for n in sources
    }
    return SubjectResolution(
        status="MATCH_FOUND",
        canonical_subject=canonical,
        identity=SubjectIdentity(
            canonical_name=canonical,
            aliases=aliases,
            normalized_aliases=sorted({normalize_subject(a) for a in aliases}),
        ),
        names=sources,
        method=method,
        aliases_considered=considered,
        source_match_methods=source_methods,
    ).model_dump(mode="json")
