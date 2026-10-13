# Human-label workflow verification

## Finalized dataset — 2026-10-13

This section supersedes the historical pending-review reports below. Human decisions
in the completed CSV are authoritative; no labels were reinterpreted or corrected.

- Source: `data/processed/bank/review_queue_v2_grouped.csv` (Numbers semicolon CSV).
- Exact SHA-256: `8256aa17efd9ce99adff2a2a15d14edb93d8ca901b432640700733f37022fcdc`.
- Reviewer: `risto`; taxonomy version 2; method `human_csv_v2`.
- All 100 UUIDs, source facts, amount displays and frozen suggestions validated.
- Import: 99 REVIEWED, 1 SKIPPED_AMBIGUOUS, 0 UNREVIEWED; 0 validation failures.
- Repeat with identical file/reviewer: 100 unchanged, no new reviews or replacements.
- Ground truth: **99 rows** in private `data/processed/bank/ground_truth.csv`.
- Private aggregate report: `data/processed/bank/reviewed_dataset_quality.json`.
- Original bytes archived under `data/processed/bank/review_imports/<sha256>.csv`.
  Original CSV and all human cells remain unchanged. Evidence/group/document fields
  stay in this archive, linked by the stored hash; no new schema migration was needed.
- Evidence states: 95 UNKNOWN, 5 AVAILABLE; five rows have a review group. These do
  not change or invalidate the user's confirmed classifications.

### Confirmed label distribution

| Category | Count |
| --- | ---: |
| ELECTRICITY | 4 |
| GRID_DISTRIBUTION | 6 |
| FORESTRY_SERVICE | 7 |
| TIMBER_INCOME | 2 |
| TAX | 6 |
| GROCERIES | 9 |
| FUEL | 6 |
| TRAVEL | 4 |
| INSURANCE | 6 |
| MAINTENANCE | 5 |
| TRANSFER | 1 |
| SUBSCRIPTION | 0 |
| OTHER | 42 |
| UNKNOWN | 1 |

| Business context | Count |
| --- | ---: |
| PERSONAL | 69 |
| PROPERTY | 15 |
| FORESTRY | 14 |
| UNKNOWN | 1 |

Reviewed cash-flow balance: **87 debits / 12 credits**. Paytrail: 15 reviewed.
Forestry: 14; property: 15; personal: 69. UNKNOWN category: 1; UNKNOWN context: 1
(the same record, so either-label UNKNOWN count is 1).

### Rule agreement on reviewed subset

| Target | All reviewed | Excluding UNKNOWN weak suggestions |
| --- | --- | --- |
| Category | 25/99 = 25.25% | 24/24 = 100% |
| Business context | 19/99 = 19.19% | 18/18 = 100% |

The rules cover only 24/99 category suggestions and 18/99 context suggestions with
non-UNKNOWN values. Perfect agreement on those small covered subsets is not broad
coverage, classifier accuracy or population precision. Sampling was intentionally
stratified; frozen suggestions are used only for this separate audit baseline.

### Class balance and Experiment 03 readiness

Category has **13 represented classes out of 14**. Including absent taxonomy classes:

- Fewer than 2: TRANSFER 1, UNKNOWN 1, SUBSCRIPTION 0.
- Fewer than 5: those above plus TIMBER_INCOME 2, ELECTRICITY 4 and TRAVEL 4.
- Fewer than 10: every category except OTHER (42); exact counts are in the table.

Business context has **4 represented classes**. UNKNOWN (1) is the only context
below 2, below 5 and below 10; PERSONAL 69, PROPERTY 15 and FORESTRY 14 are larger.
A singleton cannot support both training and independent class-level evaluation;
absent subscriptions cannot be learned or evaluated from these records. Low counts
also make per-class performance unstable. The single-context dataset correctly
excludes the skipped mixed-purpose record without inventing an allocation.

**Recommendation B:** a small targeted second human-labeling batch would materially
improve evaluation, especially for categories. Plan approximately 20–30 additional
cases if the source contains them, prioritizing transfers, timber income, electricity
and travel, plus genuine subscriptions only when supported by the human reviewer.
Aim for at least five independently reviewed examples in sparse known categories,
preferably more and across distinct merchants/trips. This is a pragmatic exploration
target, not a guarantee of reliable evaluation. Do not manufacture UNKNOWN examples,
relabel prepaid purchases, or alter broad/personal decisions to fill quotas.

The existing data is sufficient for a **limited exploratory business-context pilot**
with explicit class-support limitations, but not robust all-category evaluation.
Before broader Experiment 03 evaluation, improve sparse-class support and decide how
to handle singleton/absent classes and repeated-merchant dependence. No second batch,
resampling, train/test split, training, cross-validation or classifier was created.

### Leakage, privacy and verification

Future feature allowlist: normalized_counterparty, ultimate_recipient, message,
transaction_type_code, amount, direction, month and day_of_week. transaction_id is
metadata only. confirmed_category and confirmed_business_context are target columns,
never model inputs, including across the two prediction tasks.

The export excludes suggested_category, suggested_business_context, rule_metadata,
review_status, review_notes, evidence_status, sampling_reason/sampling_reasons,
review_hint, review_group, supporting-document fields and TaxReview decisions.
No account, BIC, archive-ID or raw-source columns exist. A scan for known source
banking identifiers in the actual export passed; text remains sensitive despite
redaction. Repeated merchants and related travel/payment rows still pose dependence
risks for future evaluation even without explicit target leakage.

Checksums of every Transaction and TaxReview row matched before/after import.
All exported UUIDs and labels exactly match the REVIEWED source subset. Notes and
source archive bytes were verified exactly; finalized rows have reviewer and source
hash provenance. Private queues, archives, dataset and detailed reports are ignored
by Git. No real transaction text or review notes were added to tests/documentation.

**228 tests passed**, including v2 semicolon parsing/import, authoritative broad
labels, exact note/hash preservation, skipped/pending handling, idempotency and
archive-byte preservation. Ruff format/check, git diff --check and Alembic check
passed. The prior migration up/down/up checks still run in disposable test schemas.
No validation or privacy issues remain. Receipt requirements were not imposed on
intentional broad/personal classifications.

**Exact next recommended step:** agree the scope of a targeted second labeling batch
for the sparse categories above, keeping these finalized labels fixed. Do not train
until Experiment 03's intended scope and evaluation limitations are separately agreed.

---

## Historical workflow verification

Verified 2026-10-11. Implementation is complete; manual labeling is pending.
No deterministic suggestion has been promoted to a human label.

## Changes

Migration **0003_transaction_label_reviews** adds the separate
transaction_label_reviews table with a unique transaction FK, frozen suggestions,
confirmed labels, constrained review states and reviewer/time/method/file-hash
provenance. Migrations 0001 and 0002 are unchanged. TaxReview is not repurposed.

Changed domain enums/models; added migration 0003 and
apps/api/tests/test_transaction_labels.py. New data_pipeline/labels modules provide
contracts, deterministic sampling, transactional workflow, review_transactions,
import_transaction_reviews and export_ground_truth. README, architecture and data
dictionary describe the boundary; transaction_labeling.md contains the full protocol.

## Real queue

The private artifact is `data/processed/bank/review_queue.csv`: **100 transactions**
out of 395, seed 42. It contains 53 rows from 2025 and 47 from 2026, with 66 effective
merchant groups and a maximum of six rows per group. Human label/note fields are
blank and all statuses are UNREVIEWED. Repeat generation is byte-for-byte identical.

Strata overlap; their counts must not be added together:

| Stratum | Available | Selected |
| --- | ---: | ---: |
| Forestry weak rule | 10 | 8 |
| Property weak rule | 42 | 10 |
| Paytrail | 38 | 15 |
| Tax weak rule | 9 | 6 |
| Grocery-like | 38 | 8 |
| Fuel-like | 8 | 6 |
| Maintenance-like | 17 | 6 |
| Insurance-like | 13 | 6 |
| Subscription-like | 9 | 4 |
| Transfer-like | 159 | 53 |
| Incoming credits | 23 | 12 |
| Outgoing debits | 372 | 88 |
| Recurring merchant | 67 | 12 |
| Unknown weak context | 343 | 82 |
| Unknown-to-rule merchant/category | 334 | 76 |

The forestry quota of ten has a shortfall of two because the merchant cap takes
priority over ordinary quotas. The sample still includes eight forestry matches.
Transfer-like means a source-text sampling hint, not a confirmed economic label.
The known refund case's one credit and two possible debits are mandatory and all
three appear in the queue, verified against the existing private refund and duplicate
candidate JSON outputs. The duplicate pair is included among those same rows.
Their relationships remain **unresolved pending human evidence**; no allocation
or automatic matching decision was created.

## Reviewed dataset state

- Registered drafts: 100; reviewed: **0**; ambiguous/skipped final reviews: **0**.
- Category distribution: all 13 allowed categories have count 0.
- Context distribution: PERSONAL 0, PROPERTY 0, FORESTRY 0, UNKNOWN 0.
- Reviewed credits/debits, Paytrail, forestry, property and either-label UNKNOWN: 0.
- Category and context “rule agreement on reviewed subset”: denominator 0,
  matches 0, rate null; non-UNKNOWN-suggestion denominators 0 and rates null.
- Ground-truth projection: 0 rows. No populated ground-truth artifact is fabricated.

These are missing human reviews, not zero accuracy or 100 inferred UNKNOWN labels.

## Verification evidence

- **197 tests passed**, retaining the previous 156 and adding 41 synthetic tests.
- Coverage includes taxonomy, deterministic strata/caps, mandatory candidate rows,
  CSV privacy/schema, invalid/duplicate/unknown IDs, ambiguity, independent labels,
  frozen snapshots, final-review protection, idempotency, whole-file rollback,
  reviewed-only export, aggregate counts and separate agreement denominators.
- Cross-transaction embedded banking identifiers are redacted in exports; synthetic
  regression coverage includes a known identifier originating outside the row.
- Migration 0003 applied to the local database; up/down/up and Alembic check passed
  in a disposable test schema. Alembic check also passed against the local schema.
- Ruff format/check and git diff --check passed.
- Real queue schema, 100 blank human label pairs and deterministic repeat verified.
- All known source account/BIC/archive identifiers scanned against the final queue:
  no matches. No banking/reference/raw-JSON columns exported. Generated private CSVs
  and the future ground_truth.csv path are gitignored.
- Existing database counts unchanged: 395 bank transactions and 15,431 energy readings.
  Review generation adds only 100 UNREVIEWED review placeholders.

An initial broad privacy audit caught BIC strings embedded in messages from other
transactions. Redaction was extended to known source identifiers across the database,
and the still-blank generated artifacts were replaced and rechecked before handoff.
No private transaction text is included in this report or the synthetic tests.

## Limits and exact next step

The sample intentionally oversamples useful review cases; it is not representative
for unbiased population performance estimates. Human context may need receipts or
owner knowledge. UNKNOWN and skipped ambiguity are legitimate. The source text is
still sensitive despite identifier redaction. The reviewer alias is not authenticated.
Finalized corrections require a future explicit audited workflow; this importer has
no overwrite option. Reproduction assumes stable IDs/data/review state/code, and new
source identifiers can make older queues fail the strict source-fact check safely.

**Next step:** manually edit only reviewed_category, reviewed_business_context,
review_status and review_notes in the private review_queue.csv, following
[the instructions](transaction_labeling.md). Preserve other fields as text. Then
import with an explicit reviewer alias and inspect the aggregate quality report.
Only after human review should a ground-truth dataset be exported for a separately
planned classification experiment. This phase stops here without classifier training.

## Evidence-aware queue follow-up — 2026-10-12

The edited source was the private review_queue.numbers document, not the original
CSV. Numbers exported it to a separate private CSV with semicolon delimiters.
Source facts and all 100 UUIDs matched the original queue exactly. The new read-only
upgrade_review_queue utility validates these facts and frozen snapshots against
PostgreSQL, preserves all existing cell strings, and writes review_queue_v2.csv.
Neither the original CSV nor the Numbers document was edited by the merge.

Verified results:

- Same 100 transaction IDs and order; no resampling.
- All **22 reviewed rows / 72 edited review cells** preserved exactly, including six
  nonempty review notes. The remaining 78 rows stay UNREVIEWED.
- Six rows contain noncanonical draft labels. These are preserved and reported,
  not automatically corrected or accepted as final ground truth.
- amount_display has explicit sign, grouping and EUR suffix; Decimal equality
  verified for every row. The original machine amount and other source cells remain
  unchanged. Sub-cent values are covered by synthetic tests without rounding.
- Evidence status starts UNKNOWN for every row. Optional supporting document UUID
  and note remain blank. These fields are queue-only; no schema migration is needed.
- Deterministic repeat bytes match. All known source bank-account, BIC and archive
  identifiers are absent from the v2 artifact. CSV and Numbers files are gitignored.
- Database still has zero final classification reviews. No labels were imported.
- **223 tests passed** (197 previous plus 26 new tests); Ruff checks and formatting,
  and git diff --check passed. Initial DB-dependent checks required restarting the
  stopped local PostgreSQL runtime; the final complete run passed.

Continue manual review in v2. Use UNREVIEWED + NEEDS_DOCUMENT when a document may
resolve the question, instead of forcing a confirmed UNKNOWN label. Existing
noncanonical labels need manual resolution before any future import. The v1 importer
rejects v2 rather than losing its evidence metadata. No classifier, PDF matching,
reconciliation or finalization was implemented. See the updated workflow guide.

### TRAVEL and review groups — 2026-10-12

Taxonomy version 2 adds TRAVEL; migration 0004 extends the database CHECK constraint
without changing historical reviews. Optional review_group is queue-only text.
The latest v2 Numbers export was extended into review_queue_v2_grouped.csv: all 100
IDs, all existing cells (including 22 reviewed rows / 72 review edits), and evidence
fields were preserved exactly. Group values start blank. Original files remain intact.
Backward-compatible v2 parsing accepts the absent optional column; formula-like group
values are rejected. No review import or classifier training was performed.

225 tests passed, including the TRAVEL taxonomy case, optional grouping and migration
up/down/up in a disposable schema. Formatting, lint, diff checks and local Alembic
schema check passed. Real-file cell equality and deterministic encoding were verified.
