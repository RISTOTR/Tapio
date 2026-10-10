# Bank transaction ingestion and deterministic groundwork

## Scope and source inspection

This phase imports bank facts and adds conservative suggestions and analytical
candidates. No classifier, embeddings, LLMs, PDF parsing, invoice reconciliation,
tax decisions, API or frontend was added. Energy ingestion and ML are unchanged.
The LLM interprets; code calculates.

Inspected local exports:

- tapahtumat20250101-20251231.csv: 225 rows.
- tapahtumat20260101-20261005.csv: 169 rows.
- tapahtumat20260101-20261007.csv: 170 rows, including the same 169 earlier rows.

The files use UTF-8 (optional BOM supported), semicolons and quoted CSV fields.
The exact required headers are Kirjauspäivä, Arvopäivä, Määrä EUROA, Laji, Selitys,
Saaja/Maksaja, Saajan tilinumero, Saajan pankin BIC, Viite, Viesti and Arkistointitunnus.
Unknown layouts/encodings are rejected, not guessed. Despite being Finnish bank
exports, the dates actually use YYYY-MM-DD, not dd.mm.yyyy.

**Arkistointitunnus** is a valuable opaque source archive identifier. It is present
and unique in every inspected file, unchanged across all 169 overlapping rows,
and disjoint between the annual exports. The source does not identify the owning
account: the recipient account column must not be mistaken for it. The CLI therefore
requires a stable local account alias. The inspected annual files are treated as one
account, `primary`; this is an explicit operator assignment, not inferred from names.
Archive-ID uniqueness beyond this source/account is not assumed.

## Parsing, validation and canonical facts

`parse_bank_csv` uses Polars with all columns read as strings. It preserves spelling,
case, leading zeroes, message/reference contents and signed decimal text. Quoted CSV
syntax is decoded normally; the original file remains local and its bytes are hashed.
The typed conversion is a separate `canonical_bank` step, followed by Pandera source
validation, deterministic enrichment and a second strict loader-boundary contract.

| Canonical field | Type/policy |
| --- | --- |
| booking_date | Required Date; exact ISO syntax and valid calendar date |
| value_date | Nullable Date; empty stays null |
| amount | Decimal(20,6), constructed directly from signed decimal-comma text; no float conversion |
| currency | EUR, explicitly supplied by the Määrä EUROA source header |
| direction | Existing INCOMING for positive, OUTGOING for negative |
| raw_counterparty | Original source text, nullable |
| normalized_counterparty | Explicit alias or superficial normalized name |
| payment_intermediary | Paytrail Oyj when the inspected counterparty prefix matches |
| ultimate_recipient | Explicit message recipient only; otherwise null |
| reference | Remove the observed `ref=` wrapper; empty payload becomes null; preserve leading zeroes |
| message | Original nonempty message; empty becomes null |
| transaction_type_code | Original Laji string, nullable |
| source_file | Source basename, required |
| source_transaction_id | Required nonempty Arkistointitunnus; never parsed as a number |
| raw_source | All original source field strings serialized for private audit storage |
| category / business_context | Separate weak suggestions, not confirmed labels |
| rule_metadata | Rule version, matched rule identifiers and weak-label semantics |

Amounts require an optional sign, 1–14 integer digits, comma, and exactly two decimal
places, matching the observed format and NUMERIC(20,6) capacity. NaN, infinity,
thousands separators, excess precision and malformed amounts fail. Zero amounts
are explicitly rejected: the current direction enum has no neutral member, and no
real input contains zero. No incoming/outgoing value is fabricated for zero.
Pandera enforces required columns, date/Decimal/string dtypes, currency, nonzero
amounts, allowed direction/context/category values and required provenance. The
loader checks amount/direction agreement. It never coerces malformed fields.

All original source strings, including the unmodified reference wrapper, description,
recipient account and BIC, remain in private `Transaction.raw_source` JSONB. These
source-specific fields do not become dozens of relational columns or public fixtures.

## Counterparties and intermediary handling

Normalization case-folds, collapses whitespace and removes periods for name matching.
Legal suffixes are not stripped indiscriminately. An explicit alias table maps:

- Vattenfall Oy, including case/spacing variations → Vattenfall Oy.
- Elenia Verkko Oy / Oyj → Elenia Verkko Oyj.
- Metsänhoitoyhdistys Keski-Suomi / ry → Metsänhoitoyhdistys Keski-Suomi.
- STORA ENSO OYJ → Stora Enso Oyj.
- VEROHALLINTO → Verohallinto.

Unknown names remain normalized strings without an invented merchant identity.
No fuzzy matching, embeddings or blanket removal of company suffixes is used.

The observed Paytrail source counterparty sometimes contains a merchant descriptor.
Its normalized processor stays Paytrail Oyj. Only one explicit terminal
`Lopullinen saaja:` message field may supply ultimate_recipient; missing, repeated,
empty, nonalphabetic, oversized or multi-field/control-character tails yield null.
A descriptor in the counterparty alone is insufficient. No missing accents or
truncated company names are reconstructed. The raw counterparty and message remain
unchanged. Direct merchants have null intermediary and null ultimate_recipient;
the effective merchant is then normalized_counterparty. Unresolved processors are
excluded from recurrence/refund grouping to avoid combining unrelated merchants.

## Independent suggestions, roles and human decisions

| Exact effective merchant/evidence | Category suggestion | Context suggestion |
| --- | --- | --- |
| Vattenfall Oy | electricity | PROPERTY |
| Elenia Verkko Oyj | grid_distribution | PROPERTY |
| Metsänhoitoyhdistys Keski-Suomi | forestry_service | FORESTRY |
| Stora Enso Oyj, credit | timber_income | FORESTRY |
| Stora Enso Oyj, debit | unknown | FORESTRY |
| Verohallinto | tax | UNKNOWN |
| Anything else | unknown | UNKNOWN |

Category and context have separate rule tables. Fuel, hardware, supermarkets,
personal transfers and arbitrary merchants are not forced into a business context.
A context is not a deduction decision. Forestry-service credits may include refunds;
category describes the economic subject, not whether cash is an expense or income.

`Transaction.category` and `business_context` hold **initial weak suggestions** for
these imports. `TaxReview.confirmed_context`, status, notes and review timestamps
remain the separate human-review authority. Existing architecture did not conflate
these fields with confirmed tax decisions, so no second confirmation model was added.
The bank loader only inserts new transactions: it never updates overlapping facts,
previous suggestions, or any TaxReview record. Rule revisions do not rewrite history.

Rule metadata records `bank-rules-1`, rule identifiers and `weak_suggestion`.
`high_precision_rule` describes a context rule, not a calibrated probability.
Unknown context is `unassigned`. No tax-treatment suggestion is generated.

The feature export supplies a simple suggested role: tax for a tax-category row,
otherwise expense/income from signed cash direction. These are cash-flow roles, not
taxable-income conclusions. It never labels a transfer or refund definitively without
more evidence. Refund/reversal links below remain a separate candidate analysis.

## Identity, audit and transactional loading

Migration **0002** adds nullable source_namespace, source_transaction_id,
transaction_type_code, raw_source JSONB and rule_metadata JSONB to Transaction.
It adds a unique constraint on (source_namespace, source_transaction_id). Nullable
columns preserve existing non-bank/legacy rows; the bank loader requires identity.
Migration 0001 is unchanged. No timestamp/amount/content fingerprint is used as the
unique transaction key because a stronger inspected source ID exists.

The namespace combines source family and explicit account alias. Same-date,
same-amount payments with different archive IDs remain distinct; this is essential
for detecting genuine double payments later. Same namespace/ID and identical raw
fields is an overlap and is skipped. Same ID with changed raw fields fails the entire
import for review; it never overwrites the earlier transaction. No fallback identity
is invented if the archive ID is missing.

False-negative/positive limits: a bank-issued replacement ID can appear as another
transaction; ID reuse or formatting changes under an existing ID cause a conservative
conflict. A wrongly assigned account alias can defeat account scoping. Automatic
merging across accounts/banks is unsupported. Similar content is never silently deleted.

Each file attempt hashes exactly the bytes parsed and creates an ImportRun. Exact
successful (SHA-256, source_type, parser_version) repeats return `already_imported`;
a different account alias for the same successful file is rejected. Repeats are new
audit attempts, linked to the original. Their rows_parsed count is recovered from
the original successful audit rather than reparsing, rows_loaded is zero, and
rows_skipped_duplicates is the original parsed count.

PostgreSQL transaction advisory locks acquire file identity first, then account
identity. This serializes exact repeats across conflicting aliases and overlapping
imports within one account. One outer transaction contains the audit and a nested savepoint
for all source/transaction work. Success commits together; processing errors roll
back all inserted transactions but preserve a failed audit when the database remains
available. Infrastructure/commit failure is reported without pretending an audit was
saved. Failed loads report zero loaded/skipped rows and a sanitized error code, not
SQL parameters or private source text. Parser failures before a frame exists report
rows_parsed=0. First-source provenance remains on a transaction; later overlap attempts
retain file-level hashes, filenames and skip counts in ImportRun.

## Recurrence and refund candidates

Recurring analysis groups by effective merchant, currency and source namespace.
It examines debits only and returns the longest contiguous qualifying run: at least
three consecutive calendar months, 24–38 days between payments, and day-of-month
(or distance-to-month-end) spread no greater than seven days. Irregular or multiple
payments break a run. Amount mean, variance and relative range are reported, allowing
variable utility bills. One run does not claim recurrence over the entire history.
No repeated-merchant shortcut is used; irregular histories can remain unclassified.

Refund/reversal candidates require the same effective merchant, currency and account,
opposite signs, **exactly equal** absolute amounts, and a later credit within 365 days.
The one-year bound permits the observed delayed forestry refund; it was enlarged from
an initial 120-day draft after inspecting that source pattern. This is deterministic
rule development, not predictive validation. Multiple possible debits are all retained
and explicitly counted. Partial/combined refunds, changed merchant names, same-day
ordering and delays beyond one year are not resolved.

A separate possible-double-payment rule requires distinct debit rows with the same
merchant, currency, account, meaningful nonempty reference and exact amount within
31 days. The source placeholder `ref=` does not qualify as a reference. Candidates
are never deletions, reconciliations, invoice allocations or confirmed refunds.

## Future classification export

`classification_features(frame)` returns a private in-memory Polars frame containing
normalized counterparty, ultimate recipient, message, transaction type code, exact
amount, direction, month and weekday (Monday=0), plus suggested role, category and
context. Labels carry `deterministic_weak_label_not_ground_truth`. It excludes account
numbers, raw audit JSON and archive IDs. Messages remain sensitive.

Do not use the suggestion/provenance columns as model inputs. Measuring agreement
with these rules would not measure classification accuracy against human truth.
No TF-IDF, classifier, embeddings, training or F1 calculation was performed.

## Commands and privacy

```sh
uv sync --locked
uv run alembic upgrade head
uv run python -m data_pipeline.ingest.bank --file /Users/tyokone/Downloads/tapahtumat20250101-20251231.csv --account-key primary
uv run python -m data_pipeline.ingest.bank --file /Users/tyokone/Downloads/tapahtumat20260101-20261007.csv --account-key primary
uv run python -m data_pipeline.verify_bank --account-key primary --private-output
```

Import output contains status, counts, parser version, source hash and audit ID; it
never prints message/reference/account contents. Verification prints reviewed
aggregate counts and business-counterparty totals, not private transaction rows.
With --private-output, detailed recurrence/refund/duplicate candidates and the feature
CSV are written only under `data/processed/bank/`, already excluded by .gitignore.
The last verification replaces these generated analysis files; database import
history is never replaced. Real CSVs remain in Downloads and are never copied into
fixtures. All tests use fabricated source rows. Database raw_source contains sensitive
financial evidence and must remain private, including backups and debug output.

See [verification and results](bank_ingestion_review.md).
