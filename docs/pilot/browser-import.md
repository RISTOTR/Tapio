# Browser bank imports

The personal workspace at `/app/import` uses the existing Finnish bank CSV parser and loader. Select an existing account and a UTF-8, semicolon-separated CSV (maximum 10 MB), inspect the preview, then explicitly choose **Import and analyze**. Preview performs no database or import-journal writes.

Validation distinguishes valid, invalid and unsupported files. A valid preview includes the filename, size, schema, account, date range, row count, duplicates and new rows; expandable tables show up to 50 rows of each kind. Conflicting contents for an existing source identity fail closed. Preview expires after 15 minutes or becomes stale if underlying state changes.

The explicit action preserves loader provenance and duplicate checks, verifies the append against the signed source acceptance mechanism, and builds ongoing Review work. It does not create numbered historical windows, confirm categories, assign business contexts or approve knowledge. Existing USER_RULE and semantic authority boundaries still apply.

Completion shows import and review counts and links to Review when work remains. Group counts describe groups, individual counts describe transactions, and evidence-limited cases may overlap individual judgment. A duplicate-only file writes no source rows or import run; its successful browser operation is recorded privately. A completed import with no pending work says **No review needed**.

The compact history combines recent successful loader runs and browser completions. Historical review counts that were never recorded are explicitly unknown. A signed private recovery journal supports resuming after a source import has committed but analysis was interrupted; a conflicting state fails closed for reconciliation. Browser commits require the existing verified write gate, same-origin checks, CSRF and an explicit confirmation value.

The workflow currently supports existing bank accounts and the existing CSV schema. New-account setup, other bank formats, document uploads and Summary are separate work. The preview cache is process-local; restarting before committing requires another inspection.

## Verification

Tests cover read-only previews, invalid files, duplicate and overlapping imports, source-identity conflicts, expired/foreign/stale tokens, idempotency, interruption recovery, explicit HTTP confirmation, append-only history, ongoing review handoff and no-review completion. Chrome verification uses actual uploads and a disposable PostgreSQL schema, never production import writes. Desktop and 390 px captures are private artifacts under `data/interim/import_workspace/`.
