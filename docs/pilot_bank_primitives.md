# Literal bank search and filtered period comparison

Implemented and verified offline. The running pilot is not restarted by this phase.
No model calls, benchmark executions, source edits or human-label writes are required.

## Literal search

Catalog detection remains first. Bounded literal request grammars cover bare terms,
“Find X transactions”, “Find transactions containing X”, “Show anything mentioning X”,
“Search the bank data for X” and “Do I have anything mentioning X?”. A recognized
literal concept can still use the centralized catalog. Otherwise the explicit phrase
is normalized and searched as a whole phrase; no invented synonyms, embeddings or
fuzzy matching. Unknown qualifiers are not silently removed. Complex requests outside
this grammar retain the existing planner path; this is not unrestricted language parsing.

The imported Finnish CSV has two description fields: Viesti maps to `message`, while
Selitys remains in `raw_source`. Search now also whitelists `raw_source.Selitys`, with
SOURCE_TEXT provenance. Arbitrary JSON keys, account numbers and archive identifiers
remain excluded. Merchant, recipient and processor fields remain searchable. Literal
search needs no labels; label-backed matches are disclosed separately. Weak suggested
labels are excluded from these new public result cards.

Results use the existing transaction-search renderer: count, original signed amounts,
existing labels, exact term/field provenance and no unrelated documents or aggregates.
Empty results are SUPPORTED / NO_MATCH and explicitly do not establish zero spending.

## Filtered comparison

`ComparisonPlan` contains subject, explicit filter kind, metric and two validated date
ranges. Supported metrics are BANK_OUTFLOW, BANK_INFLOW, NET_CASH_FLOW and
TRANSACTION_COUNT. Natural-language parsing supports English calendar months (full
names/abbreviations) with years, shared-month two-year phrasing and whole years.
“Last September … the September before” resolves using the local current date and
is tested with an injected date. Other relative/complex periods are not guessed.
The user sees exact dates. Periods are ordered chronologically; difference is B minus A.

The shared `subject_identity.resolve_subject` resolves bank merchant/recipient/processor
names, including existing aliases/legal suffixes. No comparison-specific alias map
exists. This bank-only operation does not retrieve invoices or documents. Explicit
stored context/category filters use reviewed labels only; weak labels never establish
purpose. The typed primitive also supports explicit month ranges for category filters.
Unfiltered broad comparisons retain existing routing rather than inventing a subject.

A bounded read-only scan retrieves all imported bank rows before filtering. Loaded
scalar rows are detached before the session rollback. Decimal calculations retain
currency separation: negative amounts contribute to outflow, positive amounts to
inflow, and all signed amounts to net cash flow. Transaction counts include every
matching row; payment counts include negative rows. No exchange rate is inferred.

Both periods remain visible when a side is empty. Differences use zero only for an
empty *imported-row sum*, never as proof of zero real spending. Coverage reports all
imported bank row counts and observed dates for each period and warns that even rows
on both boundary dates do not prove complete statements. No annualization, silent
partial-period extrapolation or tax conclusion is produced.

Comparison output uses the existing COMPARISON presentation mode and collapsible
raw-row details. The accepted engine and its tool contracts remain unchanged.

## Actual-source observations

The broader diagnostic audit found two interest-description rows in Selitys; the
initial search missed them because only Viesti/message was searchable. The field
whitelist fix addresses the schema gap generically, not the specific interest term.
Private dates, amounts, review states and full comparison evidence are retained in
`data/interim/bank_primitives/results.json`; the raw-field audit is in
`literal_audit.json`. Only the bounded description field was added to search.

Actual-source checks include literal Finnish queries and paraphrases, an existing
merchant outside the concept catalog, a nonsense term, three equivalent month-pair
comparison phrasings, a second merchant and confirmed forestry inflow. Provider
construction is explicitly forbidden in the verification runner. Existing human
labels and source fingerprints remain unchanged.

## Verification result

31 new regressions; full suite 1147 passed, with one existing dependency deprecation
warning. Ruff, format, diff and Alembic checks pass. Privacy scan checked 291 files
with zero findings. All 14 source fingerprints remain unchanged. Historical checks
covered 1543 hashes with only the two documented pre-existing hygiene exceptions;
accepted core/configuration and holdout/manifest byte hashes remain unchanged.
Ten actual-source Pilot requests passed with provider construction blocked.
No live server restart was performed: a restart is required to load these changes.
