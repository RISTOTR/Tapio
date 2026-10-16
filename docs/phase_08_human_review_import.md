# Phase 08 human-review import — 2026-10-16

The existing Phase 07 CSV contains 28 completed human decisions and 95 blank rows,
not 123 completed decisions. Its semicolon-delimited spreadsheet serialization is
accepted without changing the input bytes or user choices. No new queue was generated.

The dry run validated all 123 identities and taxonomy/context values against the
original frozen JSON queue and current transactions. Non-decision fields were unchanged.
All 28 decisions differed from the previous unreviewed state. Categories imported:
OTHER 5, TRANSFER 7, TAX 2, FORESTRY_SERVICE 1, GRID_DISTRIBUTION 6, ELECTRICITY 7.
Contexts imported: PERSONAL 13, PROPERTY 13, FORESTRY 2.

The existing `import_reviews` mechanism now accepts the Phase 07 format with its
original queue manifest. It writes the existing `TransactionLabelReview` model;
there is no migration or second label system. Only completed rows create records.
The existing reviewer alias `risto`, original file SHA-256, timestamp, taxonomy
version 2 and label source `human_phase07_csv_v1` preserve provenance. The exact
input bytes are archived through the existing review-import archive convention.
Weak suggestions remain separate. Existing conflicting human reviews are rejected,
consistent with the earlier import contract; this task did not require overwriting any.

First import: 28 inserted, 95 unresolved, zero validation failures. Repeat: zero
inserted, 28 unchanged, 95 unresolved. All prior review rows are byte-equivalent
under the source fingerprint serialization; repeat timestamps are unchanged.

2026 coverage: 75/170 reviewed (44.12%), 95 unresolved. No unresolved P1/P2 rows;
95 P3 rows. Bank coverage remains PARTIAL_YEAR / UNKNOWN_COVERAGE.

| Confirmed category | Count |
| --- | ---: |
| ELECTRICITY | 9 |
| GRID_DISTRIBUTION | 9 |
| FORESTRY_SERVICE | 5 |
| TIMBER_INCOME | 1 |
| TAX | 4 |
| GROCERIES | 6 |
| FUEL | 4 |
| TRAVEL | 2 |
| INSURANCE | 2 |
| MAINTENANCE | 4 |
| TRANSFER | 8 |
| SUBSCRIPTION | 0 |
| OTHER | 21 |
| UNKNOWN | 0 |

Contexts: PERSONAL 45, PROPERTY 20, FORESTRY 10; 95 unreviewed/UNKNOWN,
zero explicitly human-confirmed UNKNOWN. Income-related count is 9: this means
human-classified positive cash flows, including transfers/refunds, not taxable income.
Electricity and grid counts are 9 each; forestry-related context count is 10.

Frozen private snapshot:
`data/interim/phase08/human_review_20261016_268cbff95973/snapshot.json`.
Its sibling `before.json` preserves pre-import fingerprints and review rows.
The snapshot contains all 14 source-table fingerprints, current review rows/counts,
bank coverage, 13 tool specifications, protocol hashes, development dataset hash,
and the sealed holdout hash copied from its manifest. No holdout contents were opened.
Historical snapshots and scores are unchanged. No provider calls or paid benchmark runs occurred.

Prospective merchant policy: Tokmanni, K-Rauta and Oikea Konekauppa receive the
review reason `AMBIGUOUS_MULTI_CONTEXT_MERCHANT`. Merchant names do not assign
context; linked receipts remain review evidence and never imply tax deductibility.
Existing human decisions remain authoritative. No merchant-wide classification was added.

Validation: 684 tests passed, including 12 new synthetic regression cases;
ruff format/check, git diff check, lock validation and Alembic check passed.
Only `transaction_label_reviews` changed: 28 new rows. Transaction facts and all
other source tables, including TaxReview, are unchanged. All 66 protected electricity
files and 259 combined historical/protected artifacts passed fingerprint checks.
The private verification report records the final source, history and privacy checks.

Next step: separately authorize a fresh development-only A/B/C evaluation against
this frozen evidence snapshot, with new report paths and unchanged scoring. Phase 07
remains NOT_READY; the new review coverage does not constitute model validation.
