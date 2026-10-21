# Human transaction labels

This workflow collects human-confirmed economic categories and business contexts
for later classification research. Deterministic suggestions are weak labels, not
ground truth. No classifier or automated confirmation is part of this phase.
TaxReview remains separate: classification labels do not determine tax treatment.

## Taxonomy version 2

Category answers “what kind of economic transaction is this?” independently of
its purpose or business context. Refunds retain the underlying economic category
when known; direction retains the source cash-flow sign.

| Category | Meaning |
| --- | --- |
| ELECTRICITY | Electricity supply charges or related supply settlements. |
| GRID_DISTRIBUTION | Electricity network/distribution charges. |
| FORESTRY_SERVICE | Forestry management, advice or contracted forestry work. |
| TIMBER_INCOME | Proceeds from timber sales, or an identified reversal of those proceeds. |
| TAX | Tax payments or refunds; no deductibility inference. |
| GROCERIES | Food and ordinary household consumables. |
| FUEL | Vehicle or machinery fuel. |
| TRAVEL | Transport fares, accommodation and other direct travel costs. Use FUEL for separately identified fuel; context still depends on the trip purpose. |
| INSURANCE | Insurance premiums or identified insurance settlements. |
| MAINTENANCE | Repairs, upkeep, tools and maintenance supplies. |
| TRANSFER | Known movement of funds without a more specific economic purchase/income category. |
| SUBSCRIPTION | Recurring access/service subscriptions, such as telecom; use a more specific category for electricity or insurance. |
| OTHER | Economic nature is understood but falls outside the categories above. |
| UNKNOWN | Available evidence does not establish the economic nature. |

The observed grocery, fuel, maintenance, insurance and subscription candidates
support retaining this compact initial list. Keyword matches are only sampling
hints, not proof of purchases. No extra business category is justified now.

Context answers “which life/business domain does this belong to?”:

| Context | Meaning |
| --- | --- |
| PERSONAL | Personal or household purpose. |
| PROPERTY | The rural property's operation or upkeep. |
| FORESTRY | Forestry activity. |
| UNKNOWN | Purpose is not established, including inseparable mixed purposes. |

MIXED from the older domain enum is deliberately not accepted here. Neither
OTHER_BUSINESS nor tax deductibility states are added. A merchant alone cannot
establish context: fuel could be personal or forestry, and hardware may require
a receipt. A bank transfer mechanism does not establish economic TRANSFER.

## Ambiguity and review states

- `REVIEWED`: explicitly reviewed by a person; both labels required. `UNKNOWN`
  is a valid deliberate decision for either or both labels.
- `SKIPPED_AMBIGUOUS`: no dependable pair of labels can be supplied now. Leave
  both label fields blank and explain the missing evidence in review_notes.
- `UNREVIEWED`: pending; both labels blank. Draft notes remain in the CSV and
  are not persisted by the importer until a final state is supplied.

Do not copy suggestions just to fill the queue. OTHER means understood but outside
the taxonomy; UNKNOWN means insufficient information. Documents or the owner's
knowledge may be necessary. Skipped rows stay outside ground truth, while reviewed
UNKNOWN rows are retained for possible later abstention evaluation.

## Storage and audit

Migration `0003` adds `transaction_label_reviews`, one row per transaction enforced
by a unique indexed foreign key. It stores frozen suggested category/context,
confirmed category/context, status, reviewer, reviewed_at, notes, label_source,
review_file_sha256, taxonomy_version and created_at, alongside a UUID primary key.
The taxonomy and status combinations are database CHECK constraints on text fields.
REVIEWED requires both labels; other states require null confirmed labels. Final
states require reviewer, timestamp and file hash. Queue creation writes only
UNREVIEWED placeholders and snapshots, never confirmed labels.

Human imports record the operator-supplied reviewer alias, UTC import instant,
`human_csv_v1` or `human_csv_v2` method, exact file SHA-256 and the taxonomy version used at import (currently 2). The alias is
provenance, not authenticated identity; the timestamp is import time, not the time
the person edited the file. Suggestions on Transaction and TaxReview are untouched.
Later rule changes cannot change the frozen snapshots or confirmed labels.

## Sampling

The default target is 100 with seed 42. Stable SHA-256 ranking of seed plus
transaction UUID makes selection independent of input order. Reproduction requires
the same transaction IDs, facts, rules, review state and code; a fresh import with
new UUIDs need not select the same records. Final reviewed/skipped rows are excluded
from subsequent queues.

Overlapping strata prioritize forestry/property weak matches, Paytrail, tax,
grocery/fuel/maintenance/insurance/subscription candidates, transfers, credits,
debits, recurrence, unknown contexts and unknown-to-rule merchants. Merchant
patterns inspect effective recipient, message and source description. “Unknown
merchant” includes rows with unknown weak category, not only absent merchant names.
Paytrail uses its underlying recipient for the cap where available.

Each ordinary merchant group is capped at six. All detected refund/duplicate
relationship rows are mandatory, even if this exceeds the cap or requested size.
The sampler reuses the existing candidate functions, then fills underrepresented
merchant groups. If caps prevent the target, the report exposes the smaller sample
and unmet quotas. This is a purposeful review set, not a probability sample;
agreement does not estimate population accuracy.

## Generate and complete the private CSV

From the repository root, with the local database running:

```sh
uv run alembic upgrade head
uv run python -m data_pipeline.labels.review_transactions --account-key primary --size 100 --seed 42
```

The generated file is `data/processed/bank/review_queue.csv`. Existing output files
are never overwritten; use `--output-name another_queue.csv` for a new artifact.
Output names must be CSV basenames in the same ignored directory.

1. Import the CSV into your editor using UTF-8 and comma delimiters. In a spreadsheet,
   import **all columns as text** to preserve UUIDs, ISO dates and six-decimal amounts.
2. Edit only `reviewed_category`, `reviewed_business_context`, `review_status`, and
   `review_notes`. Keep headers/order, source facts, suggestion snapshots and hints.
3. Use the exact uppercase labels above. For a completed row, set both labels and
   `REVIEWED`. Use UNKNOWN deliberately when appropriate. For a skipped row, leave
   both labels blank, use SKIPPED_AMBIGUOUS and explain why in the notes.
4. Leave unfinished rows UNREVIEWED with blank labels. Partial review is supported.
5. Save as comma-separated UTF-8 CSV, preserving all read-only text exactly. Do not
   add bank details to notes. Keep a private copy before spreadsheet edits.

The queue contains UUID, date, amount, direction, normalized counterparty, ultimate
recipient, message, source type code, weak snapshots, sampling reasons and candidate
hints. Suggestions and hints are context for review only.

For the known one-credit/two-debit refund case, all three rows are included. Notes
may say `REFUND relationship confirmed to transaction <UUID>` or
`unresolved / ambiguous`. UUIDs in review_hint identify the possible partners.
Only a person with evidence can resolve the relationship. Notes are free text, not
parsed relationships or invoice allocations. If category/context are independently
known, REVIEWED can coexist with an unresolved relationship note; otherwise skip.

## Import, retries and corrections

After completing some or all rows, replace the reviewer alias below:

```sh
uv run python -m data_pipeline.labels.import_transaction_reviews \
  --file data/processed/bank/review_queue.csv --reviewer your-local-alias
```

The importer checks exact schema, labels, UUID uniqueness/existence, registered
queue membership, source facts and frozen snapshots. One transaction covers the
whole file, with an advisory lock serializing queue/import writes. Any invalid or
conflicting row rolls back the entire import. Diagnostics contain stable error
codes and line numbers, not transaction text. Successful output counts new reviewed,
skipped, pending, unchanged and validation failures.

An identical final review with the same reviewer is a no-op, preserving original
time and hash. Any changed final label, note, status or reviewer is rejected.
Correct CSV drafts before first import. There is no replacement flag or audited
post-import correction workflow yet; do not bypass protection with routine SQL.
A future explicit versioned correction mechanism is needed for finalized mistakes.
Old copies with UNREVIEWED values for now-finalized rows also conflict safely.

## Ground truth and quality report

```sh
uv run python -m data_pipeline.labels.export_ground_truth --account-key primary --report-only
uv run python -m data_pipeline.labels.export_ground_truth --account-key primary
```

The second command creates private `data/processed/bank/ground_truth.csv` and refuses
an existing filename. Use `--output-name` for a new export. Only REVIEWED rows are
included, including explicitly confirmed UNKNOWN. Columns are transaction_id,
normalized_counterparty, ultimate_recipient, message, transaction_type_code, exact
amount, direction, month, day_of_week (Monday=0), confirmed_category and
confirmed_business_context. Confirmed columns are targets, not model features;
transaction_id is traceability metadata. No rule columns or review notes are exported.

The aggregate report covers reviewed/skipped/pending counts, all label counts,
credit/debit balance, Paytrail, property, forestry and either-label UNKNOWN counts.
Category and context each report **rule agreement on reviewed subset**: exact
snapshot/confirmed matches divided by reviewed rows. A separate denominator/rate
excludes UNKNOWN suggestions to expose coverage. Empty denominators give null,
not zero. This measures neither model accuracy nor unbiased population rule
precision. Frozen queue-time rules, selection bias and reviewer uncertainty matter.
No training, train/test split or classifier evaluation is implemented.

## Privacy and operational limits

CSV files and all detailed outputs remain gitignored under data/processed/bank.
There are no account, BIC, archive-ID, raw JSON or reference columns in these
exports. Known source account/BIC/archive identifiers across the database are
redacted from free text as well, with generic IBAN redaction and spreadsheet-formula
escaping. This is not full anonymization: merchant names and messages remain private.
New source identifiers can change redaction; an older queue may then fail the exact
source-fact check and need regeneration. Never publish queues, ground truth or notes.

Only synthetic rows belong in tests; documentation records aggregates. Gitignore
is not an access control. This local workflow assumes a trusted operator; direct
SQL writers are not blocked by an authorization layer. Queue placeholders commit
before disk output, so a file-write failure may leave harmless unreviewed drafts.
The next step is manual labeling, followed by validated import and dataset-quality
review before any separately authorized classification experiment.

## Evidence-aware review queue v2 (2026-10-12)

Bank transaction text alone is often insufficient for business-context ground
truth. A hardware-store payment, fuel purchase or generic transfer may require a
receipt, invoice or the owner's knowledge of its purpose. Keep these four concepts
separate:

| Concept | Meaning |
| --- | --- |
| Weak suggestion | A deterministic rule's provisional category/context, not evidence of human confirmation. |
| Human label | The reviewer's economic category and life/business context after considering available evidence. |
| Evidence state | Whether supporting evidence is needed, available and checked, or unavailable. It creates no label. |
| Tax treatment | A separate tax-review decision; neither category nor evidence status determines deductibility. |

The new private working file is `data/processed/bank/review_queue_v2.csv`.
It uses the **same UUIDs and order**, preserving every existing review cell. The
original CSV and Numbers document remain unchanged. No sample is regenerated and
no reviews are imported. The v2 migration verifies source facts and frozen
suggestions against the database before copying edits. A mismatch stops the merge.

`amount_display` is near the front, with an explicit sign, thousands grouping and
EUR suffix: `-46.13 EUR`, `+588.07 EUR`, `+37,712.50 EUR`. It shows at least two
decimals and retains any nonzero sub-cent precision rather than rounding it away.
The original six-decimal `amount` remains unchanged near the end for validation.
The display is constructed only from a finite Decimal and fixed currency suffix;
no user-supplied expression is evaluated. UUIDs and source facts remain read-only.
Import CSV columns as text in Numbers/Excel to preserve their exact representation.

### Evidence status

| Value | Meaning |
| --- | --- |
| NOT_REQUIRED | The reviewer knows enough from the transaction and its context. |
| AVAILABLE | Supporting evidence exists and has been checked. |
| NEEDS_DOCUMENT | A receipt, invoice or other document must be found/checked before reliable labeling. |
| UNAVAILABLE | Supporting evidence is needed but is not available. |
| UNKNOWN | The need for evidence has not yet been assessed. |

All migrated rows start with evidence_status UNKNOWN, including previously reviewed
rows: the migration does not infer that a document was checked. Existing labels,
statuses and notes are preserved exactly, without trimming or reinterpretation.

For a transaction awaiting a receipt, prefer **UNREVIEWED + NEEDS_DOCUMENT**, with
blank labels and a note describing what to find. Do not use category/context UNKNOWN
as a substitute for evidence that has not yet been checked. A confirmed UNKNOWN
label means the reviewer considered available evidence but still cannot establish
the label. REVIEWED still requires both labels; SKIPPED_AMBIGUOUS still requires a
note and blank labels. Evidence status never changes review status or creates labels.
For the 22 existing reviews, revisit evidence status manually; the migration does
not undo or auto-finalize the decisions already entered.

Two optional fields remain blank initially:

- `supporting_document_id`: optional document UUID for future use; leave blank unless
  you know the identifier. Validation checks UUID syntax, not document existence.
- `supporting_document_note`: a private note about evidence checked or still needed,
  such as where to look for a receipt. It is not a parsed document link.

These three new evidence fields are **queue-only** in this phase. There is no schema
migration, document matching, invoice reconciliation or PDF processing. The importer now accepts v1 and v2 schemas. Evidence/document/group fields remain
in a private exact-byte archive linked by review_file_sha256, rather than database
columns. They are validated but do not override the human category/context.

### Safe upgrade utility

For an edited v1 comma-separated CSV:

```sh
uv run python -m data_pipeline.labels.upgrade_review_queue \
  --file data/processed/bank/edited_review_queue.csv
```

Numbers may export semicolon-separated CSV under a European locale. Select that
explicitly; the output is always UTF-8 with BOM and comma-separated:

```sh
uv run python -m data_pipeline.labels.upgrade_review_queue \
  --file data/processed/bank/review_queue_numbers_export.csv --delimiter ';'
```

The utility only reads the database and never imports labels. It refuses existing
output files; `--output-name` selects another private CSV basename for verification.
It preserves source cell strings exactly, so spreadsheet date/number reformatting
causes a safe validation failure instead of guessed corrections. It detects source
file changes during the merge. Given identical input and database facts, output
bytes are deterministic. Only selected UUIDs are loaded; the sampler is not called.

Spreadsheet escaping of source text remains intact. Formula-like or known banking
identifier text in edited cells stops the merge for manual correction rather than
silently changing the user's edits. The original files remain intact on failure.
New notes must also remain plain text, without account numbers, BICs or archive IDs.
Queues and Numbers documents remain private and gitignored.

Continue reviewing the v2 file by editing the four original review fields plus
evidence_status and the two optional supporting-document fields. Keep all other
columns unchanged. The same import CLI now accepts completed v2 queues. No classifier training is
part of this phase.

The merge also preserves noncanonical draft labels (for example combined categories)
exactly, reporting their CSV record numbers as `label_validation_issue_lines`.
This is preservation of work in progress, not acceptance as ground truth. Strict v2
validation still rejects labels outside the taxonomy and REVIEWED rows without both
labels. Resolve combined entries manually later, using evidence and a single allowed
label per field; the utility never picks a category or context for the reviewer.


### Travel and optional grouping (2026-10-12)

Taxonomy version 2 adds TRAVEL to the original 13 categories. Migration 0004 extends
the database category constraint; old migrations and historical review versions stay
unchanged. New human imports record version 2. Downgrading with stored TRAVEL reviews
fails safely instead of relabeling them.

`review_group` is an optional private, free-text tag, for example `trip-2026-10` or
`receipt-batch-01`. Reuse a tag to group related transactions or receipts for manual
review. Leave it blank when not useful. It is queue-only metadata, independent of
economic category, business context, evidence status and tax treatment; it creates
no document links, allocation or reconciliation. Avoid personal/banking identifiers
and spreadsheet formulas in tags. Old v2 files without the column remain readable.

The current working copy with this column is
`data/processed/bank/review_queue_v2_grouped.csv`, preserving the latest v2 Numbers
export cells. Existing files are retained. To extend another v2 draft safely:

```sh
uv run python -m data_pipeline.labels.upgrade_review_queue \
  --file data/processed/bank/review_queue_v2_numbers_export.csv --delimiter ';' \
  --from-v2 --output-name review_queue_v2_grouped.csv
```

The utility verifies UUID/source facts, preserves review/evidence/document cells,
and refuses to overwrite an existing output. No labels are imported by this command.


## Finalized human import (2026-10-13)

The user's completed CSV is authoritative. DNA prepaid may intentionally be
OTHER/PERSONAL; fuel may intentionally be FUEL/PERSONAL; broad OTHER/PERSONAL
labels need no additional receipt merely because a merchant sells multiple products.
Do not infer tax treatment or replace human decisions with rule suggestions.
UNKNOWN evidence is accepted on REVIEWED rows: evidence metadata is independent
of the user's explicit classification decision. NEEDS_DOCUMENT is preserved/reported,
not an automatic label change or an extra receipt requirement.

The importer accepts the exact v1/v2 schemas with comma or semicolon delimiters,
including the older v2 schema without optional review_group. Labels are validated
strictly without normalizing them. Source facts and frozen suggestions must match.
The source CSV is never rewritten. Every CLI attempt that passes structural
validation archives its exact bytes under
`data/processed/bank/review_imports/<sha256>.csv` before database writes. Thus an
archive is evidence of an attempt, not proof of successful import. A final database
review stores the hash linking to the full evidence/group/document fields. Keep
these archives backed up with the database; none are ML features.

Finalized notes retain whitespace exactly. New imports record taxonomy version 2
and human_csv_v2 for v2 input. Identical repeated reviews preserve their original
hash, timestamp and provenance. A changed evidence-only file is separately archived;
it does not revise a finalized database review or its original hash. Pending row
notes/evidence stay in the archive; no confirmed labels are created for pending or
skipped rows. This phase adds no schema changes or replacement workflow.

```sh
uv run python -m data_pipeline.labels.import_transaction_reviews \
  --file data/processed/bank/review_queue_v2_grouped.csv --reviewer local-reviewer
uv run python -m data_pipeline.labels.export_ground_truth --account-key primary --report-only
uv run python -m data_pipeline.labels.export_ground_truth --account-key primary
```

Future model inputs must be explicitly limited to normalized_counterparty,
ultimate_recipient, message, transaction_type_code, amount, direction, month and
day_of_week. transaction_id is metadata only. Both confirmed label columns are
separate targets, never features (including the other task's target). Suggestions,
rule_metadata, review status/notes, evidence, grouping, document fields, sampling
reasons, review hints and TaxReview decisions are excluded. Recurring merchants and
related payments can still make later evaluation optimistic; a future experiment
must address that dependence without altering these human labels.
