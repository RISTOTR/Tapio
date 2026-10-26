# Generic pilot bank transaction search

TRANSACTION_SEARCH is a separate pilot capability for ad-hoc bank text searches.
It does not change the accepted coordinator, frozen tool registry, model, source data,
human labels or benchmark history. It makes no tax, purpose or business-relevance decision.

## Route and plan

Show/find/list/search requests involving transactions, purchases or payments, and explicit
“mentioning/related wording” searches, route here before broad-question fallback. A short
standalone search phrase is also supported. Review, coverage, tax and financial-total
questions retain their existing paths. Broad financial overviews remain broad.

The unchanged configured model proposes a typed plan with:

- intent: TRANSACTION_SEARCH;
- one to ten explicit terms, each at least three normalized characters;
- an optional date range, checked against the user's explicit year or month/year.

This is one generic route, with no topic-specific code or synonym dictionary.
The model receives the question and deterministic date scope, not bank rows. It can
propose translations/synonyms but cannot generate SQL, choose database fields, supply
financial facts, change labels or write a final answer. The provider uses a constrained
function schema. Raw output and validated terms are retained privately.

No date means all imported dates. Unsupported relative/multiple-period scopes fail
explicitly; a planner cannot add or remove a date filter. Invalid terms or plans fail
before retrieval. Live provider behavior has not been smoke-tested in this repair;
offline checks use an explicitly marked synthetic provider response.

## Deterministic execution

The executor uses a read-only session and a parameter-bound date-filtered query over
transactions joined to label reviews. Text matching is performed locally:

1. Unicode NFKD normalization;
2. casefold and accent removal;
3. punctuation converted to spaces;
4. whitespace collapse;
5. whole normalized token/phrase matching.

There are no embeddings, fuzzy distances, hidden synonym expansion or SQL wildcards.
For example, accented and unaccented Spanish terms compare equally, while “dental”
does not match a substring inside “accidental”.

Searchable fields are the original transaction message/description, raw and normalized
merchant, recipient, processor, and category/context labels. The bank import's original
description is retained in the message column. Raw-source JSON, account references and
source identifiers are not searched or displayed.

Confirmed human labels are authoritative. Suggested category/context fields are searchable
only for unconfirmed rows and are labeled non-authoritative. Each result records the exact
matching terms and fields; a text match never becomes a category or context assignment.

Execution streams at most 100,000 rows and allows at most 1,000 matches. Exceeding either
bound fails as EVIDENCE_INCOMPLETE, never as NO_MATCH or a silently complete result.
The source fingerprint gate runs before and after execution.

## Presentation

The deterministic response contains matching transaction dates, merchants, signed amounts,
currencies, review status, confirmed labels and matched terms. It contains no unrelated
bank aggregates or documents. The main answer shows up to 30 matches; all retrieved matches
are retained in transaction details with per-row match provenance.

No matches produces SUPPORTED · NO_MATCH and lists the terms that were actually searched.
Unconfirmed rows and human-confirmed UNKNOWN labels retain HUMAN_REVIEW_REQUIRED.
Imported-source coverage and suggested-label limitations are stated when relevant.
No model-authored financial prose is released.

## Offline verification

The private directory `data/interim/pilot_transaction_search/` contains:

- the explicit dental/Spanish search fixture and exact real imported matches;
- per-row term/field provenance and original review status;
- before/after source-table fingerprints;
- marked offline provider fixtures exercising the actual pilot search route;
- date-filter and no-match checks, plus K-Rauta search/identity equivalence.

Expected real rows were observed from the database rather than embedded in production code.
Synthetic regression tests cover the general routing matrix, normalization, field matching,
label authority, date bounds, limits, provider validation, identifier redaction and the
source postflight gate. No live model calls or benchmarks are required for these checks.
