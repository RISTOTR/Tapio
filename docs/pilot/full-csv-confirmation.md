# Full bank fields and controlled confirmation

The inspected importer already retained all eleven columns in `raw_source`, including
Viesti, and projected Viesti into `message`. No immutable transaction backfill is needed.
The repair makes exact source-column provenance explicit and centralizes field use in
search, named-subject supporting evidence, knowledge and suggestions. Reference/date/
amount evidence can generate candidates; it does not confirm a document relationship.
Account/BIC/archive identifiers remain private structured metadata rather than generic
purpose-search or vocabulary input. See the generated bank field audit for every column.

`FULL_CSV_CARDS_V2` keeps the historical sixteen-card batch and feedback untouched.
Paytrail category suggestions may use consistent human-confirmed categories for the exact
recipient explicitly named by Viesti; they never inherit a processor-wide category or
context. Recipient visibility is reported separately from proven purchase purpose.
All new recommendations remain SUGGESTED. No model or Gmail calls are required.

## Five-card pilot boundary

The fixed private allowlist is `data/interim/full_csv_confirmation/preview.json`, at most
five cards. It excludes Paytrail, ambiguous retailers, conflicting cards and ambiguous
reconciliation cases. The page is `/pilot/confirmation`. It displays merchant/date/amount,
Selitys and Viesti, separate category/context selections, reasons and warnings. No fields
are preselected for confirmation. CONFIRM accepts only displayed proposed values;
CHANGE accepts explicitly selected taxonomy values. SKIP changes no classifications.

A preview always performs no writes. Its signed token expires after fifteen minutes and
binds the selected fields, evidence/card/batch hashes, source/review version, browser
session and one idempotency key. Any edit invalidates the displayed apply control. A
separate click applies the displayed changes. Server-side validation, same-origin checks,
HTTP-only SameSite session cookies and CSRF checks enforce the narrow browser path.
There is no agent tool, feedback conversion or background write worker.

`TAPIO_CONFIRMATION_WRITES=false` is the default. Even setting it true requires a matching
`dry_run_verified.json` seal for the batch and implementation files. After all verification
passes, a local operator can restart the pilot with that environment variable set true.
Do not enable it for an expanded batch without another dry-run/integrity review.
This phase leaves it false and never applies the five previews automatically.

## Persistence and correction

Migration 0006 adds an empty `confirmation_revisions` ledger with a database trigger
rejecting UPDATE and DELETE. It does not modify bank rows or legacy review rows.
Each explicit CONFIRM/CHANGE atomically appends selected fields, current per-field
value/authority, old/new values, action/time, original SUGGESTED card, evidence shown,
correction reason and replayable HUMAN_REVIEW_CONFIRMED event with its ID. An omitted
field retains its existing value and authority. An explicitly selected UNKNOWN remains
UNKNOWN; it is not conflated with omission.

Transaction locking and version checks reject stale previews. Retries of the same signed
preview return the original revision. Corrections require a reason and append a new
revision linked to its predecessor; earlier values, suggestions and events remain intact.
External changes to legacy review rows cause a reconciliation error instead of silently
overriding newer human evidence. Source facts, tax-review state and source metadata are
never updated by this service.

Live transaction search and named-subject retrieval project the latest ledger state.
Frozen benchmark/core paths and their original label snapshot remain unchanged.
Explicit knowledge backfill reads the ledger and projects only the latest selected
claim per transaction/field, retaining untouched legacy claims. Corrected context replaces
its older active merchant observation without deleting audit history or inventing a
merchant-wide rule. Original source facts and event bundles remain inspectable.

## Reproduction

1. Read-only source export and original-CSV hash verification produce a private inventory.
2. `scripts/audit_bank_fields.py --csv-dir <local original CSV directory>` generates the
   field audit, append-only derived knowledge bundle, Paytrail evidence comparison,
   V2 candidates and bounded preview. Do not regenerate a batch after human use without
   an explicit new-version lifecycle.
3. Run full tests in isolated PostgreSQL schemas, static/privacy checks and fingerprints.
4. Run the private real five-card dry-run verification with writes disabled; inspect every
   diff/audit/event preview and confirm the ledger remains empty. Seal the verified batch.
5. Review the local page. Enabling the environment flag is separate from generating a
   preview; applying each card still requires the user's explicit final click.
