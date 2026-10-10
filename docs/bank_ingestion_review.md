# Bank ingestion review — 2026-10-10

## Delivered and schema changes

Implemented source parsing, exact normalization, Pandera contracts, independent
category/context suggestions, intermediary separation, transactional imports,
recurrence/refund candidates, a private future-classification export and local CLIs.
No classifier, embeddings, invoice reconciliation, tax treatment, frontend or API
was added. Energy ML and ingestion code are unchanged.

Migration **0002_bank_source_identity** adds five nullable Transaction columns:
source_namespace, source_transaction_id, transaction_type_code, raw_source JSONB
and rule_metadata JSONB. A unique constraint scopes archive IDs to source/account.
All bank imports require identity; nulls preserve legacy/non-bank compatibility.
Migration 0001 is unchanged. Transaction category/context values are initial weak
suggestions; human-confirmed TaxReview fields remain separate and untouched.

## Source and normalization verification

The real exports are UTF-8, semicolon-delimited, with ISO dates and signed
comma-decimal amounts. All source columns are first read as strings. Amounts become
Decimal(20,6) without floats. Source currency is explicitly EUR. Invalid required
values fail; optional empty text remains null. Zero is rejected rather than assigned
an invented direction. Pandera validates facts before rules and the enriched frame
again at the load boundary.

All inspected references use a `ref=` wrapper; its empty payload becomes null.
Raw original strings, including that wrapper, recipient banking details and Laji,
are retained privately. Source messages/references/account numbers are absent from
committed fixtures and this report. Source archive IDs are nonempty and unique in
each file and unchanged in all observed overlaps. There is no guessed content key.

| Source | Parsed | Newly loaded | Overlap skipped |
| --- | ---: | ---: | ---: |
| 2025 annual export | 225 | 225 | 0 |
| 2026 through October 5 export | 169 | 169 | 0 |
| 2026 through October 7 export | 170 | 1 | 169 |
| Exact repeat of latest 2026 export | 170 (original audit count) | 0 | 170 |
| Exact repeat of 2025 export | 225 (original audit count) | 0 | 225 |

Both repeats return `already_imported`, with separate completed audit attempts.
Final database total: **395 distinct transactions**, with no duplicate scoped IDs.
The latest filename's October 7 boundary contains transactions only through October 6;
no date was fabricated to match the filename.

| Year | Final rows | Debits | Credits | Observed booking-date range |
| --- | ---: | ---: | ---: | --- |
| 2025 | 225 | 211 | 14 | 2025-01-02–2025-12-29 |
| 2026 | 170 | 161 | 9 | 2026-01-02–2026-10-06 |

Every one of the 395 database records was independently compared with a standard
CSV read of the source: exact Decimal amounts, dates, original counterparty/message,
reference normalization, type code, complete raw JSON and import provenance agree.
Total signed amounts also agree. Existing energy data remains **15,431 readings**.

## Merchant and intermediary checks

| Canonical counterparty | Transactions |
| --- | ---: |
| Vattenfall Oy | 21 |
| Elenia Verkko Oyj | 21 |
| Metsänhoitoyhdistys Keski-Suomi | 8 |
| Stora Enso Oyj | 2 |
| Verohallinto | 9 |
| Paytrail Oyj | 38 |

Case, whitespace and exact known legal-name variations normalize consistently.
All 38 Paytrail rows have one explicit usable `Lopullinen saaja:` field. The processor
and that recipient text are stored separately; extracted text is not independent
verification of an entity's full legal name. Missing/truncated names are not guessed.
Synthetic missing/ambiguous/malformed recipient messages correctly produce null.
Direct merchants retain a null ultimate_recipient and use their normalized name.

## Forestry and property checks

**Transactions currently classified into forestry business context:** 10, involving
Metsänhoitoyhdistys Keski-Suomi and Stora Enso Oyj. Total credits: **€40,728.44**.
Total debits: **€4,194.62**. These are cash-flow totals, not timber-only income,
net costs, or deductible forestry expenses; credits include a refund candidate.
All 10 have an assigned economic-category suggestion, so category-unknown count
within that suggested subset is zero. All remain unconfirmed weak labels.

Across the complete dataset, **343 transactions remain UNKNOWN business context**.
We cannot tell how many of those belong to forestry without human evidence; zero
unknown categories within the matched subset does not imply complete forestry coverage.
Verohallinto is categorized as tax but remains UNKNOWN context.

| Property-energy counterparty | Count (all debits) | Total debits | Booking-date range |
| --- | ---: | ---: | --- |
| Vattenfall Oy | 21 | €2,173.95 | 2025-01-15–2026-09-23 |
| Elenia Verkko Oyj | 21 | €2,555.28 | 2025-01-17–2026-09-17 |

These 42 rows are PROPERTY suggestions only; no invoice, energy quantity or tariff
was matched to them and no tax decision was inferred.

## Recurring payments and refund candidates

Found **four merchant groups with a qualifying monthly run**, including Elenia and
Vattenfall. The longest qualifying runs contain 11 and 20 payments respectively;
mean intervals are approximately 30.40 and 30.32 days. Amount variability is measured
and retained privately; utility amounts need not be constant. A run is not a declaration
that every payment in the merchant's history is recurring. Other private schedules
and merchant identities are not published here.

Found **one possible duplicate-payment pair** with distinct archive IDs, the same
meaningful reference, same merchant/currency/account and exact debit amount within
31 days. Those payments remain separate facts. Empty `ref=` placeholders cannot
trigger this rule.

Found **two refund/reversal candidate pairs concerning one credit**. That credit has
two possible earlier matching debits. Both alternatives remain visible and neither
is chosen automatically. Exact-amount candidate matching uses a maximum one-year
delay; the initial 120-day draft missed this delayed source pattern. No invoices
were read or allocations created. Partial/combined refunds remain unsupported.

The private classification feature export contains text/calendar/amount/direction
features plus explicitly marked weak category/context/role labels. It is preparation
only: no model fit, TF-IDF, predictions or classification score was produced.

## Tests and final checks

- **156 tests passed**, including all 90 previous tests and PostgreSQL integration
  tests against Alembic-migrated disposable schemas.
- New synthetic tests cover parsing/quoting/UTF-8 rejection, exact decimal commas,
  dates, signs/zero policy, missing optional fields, malformed values, alias rules,
  direct/intermediary recipients, conservative categories/contexts, `ref=` handling,
  recurrence with irregular interruptions, nonrecurring merchants, delayed and
  ambiguous reversals, account/identity isolation and weak-label export semantics.
- PostgreSQL tests cover exact repeat and overlapping files, distinct identical
  payments, duplicate archive rows, rollback after a new row precedes a conflict,
  audited failures and retries, exact Decimal persistence, raw provenance, concurrent
  overlap, conflicting aliases for the same concurrent file, sanitized CLI output,
  and no overwrite of transaction labels or confirmed TaxReview state.
- Ruff format --check, Ruff check and git diff --check passed.
- Alembic upgrade to 0002 succeeded; Alembic check reports no new upgrade operations.
- Both real annual periods imported; the extra 2026 export provided a real partial
  overlap test. Exact repeats inserted zero rows. Every persisted row was independently
  checked against source data as described above.
- .gitignore explicitly checked: data/processed/bank JSON reports, candidate records,
  and classification_features.csv are ignored. All fixtures are synthetic.
- No changes to energy ingestion/ML files, no new dependencies, and no edit to 0001.

## Files created

- apps/api/alembic/versions/0002_bank_source_identity.py
- data_pipeline/ingest/bank_csv.py and bank.py
- data_pipeline/normalize/bank.py and bank_analysis.py
- data_pipeline/validate/bank.py
- data_pipeline/load/bank.py
- data_pipeline/verify_bank.py
- apps/api/tests/test_bank.py and test_bank_load.py
- docs/bank_ingestion.md and docs/bank_ingestion_review.md

Files changed: apps/api/app/domain/models.py, docs/data_dictionary.md,
docs/architecture.md and README.md. Existing ignore rules already cover private
outputs, so .gitignore did not need alteration.

Generated privately under data/processed/bank/: aggregate.json, recurring.json,
refund_candidates.json, duplicate_payment_candidates.json and classification_features.csv.
No raw CSV rows, archive IDs, private references/messages or account numbers are
included in source fixtures or this report.

## Limitations and exact next step

Support is intentionally limited to the inspected source layout, currency, date and
amount syntax. An explicit account alias is required because the owner account is
absent from the CSV. Archive-ID stability is observed, not a bank-wide guarantee;
changed IDs cannot be deduplicated safely by content alone. Existing-ID changes fail
for review. Rule coverage is low, and suggestions are not human truth. Monthly runs
and exact-amount credit matches can be coincidental and require review. Tax treatment
remains unassessed; financial totals are not deduction decisions.

**Next recommended step:** create a small, human-reviewed category and business-context
label set, recording confirmed labels separately from these rule suggestions and
reviewing the ambiguous refund candidate. Define the later classification experiment
only after that ground truth exists. No classifier or next-domain phase was started.
