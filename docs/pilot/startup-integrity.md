# Startup integrity during ongoing operation

## Root cause

`scripts/start_pilot.sh` runs `python -m tapio.pilot.health`. Its source preflight
calls `tapio.pilot.config.source_fingerprints()`. Previously that function selected
all rows of every protected table and required the whole-table count and SHA-256
to equal the frozen financial pilot configuration. A legitimate append therefore
raised `SOURCE_SNAPSHOT_CHANGED`, just as a historical mutation would.

The authoritative configuration is
`data/interim/phase09i/phase09h_configuration.json`, SHA-256
`3b3e0d809c205ca37f7c39414aca407fe01a58a15935d1a3db93d2ae2d97988b`.
It references `data/interim/phase08/human_review_20261016_268cbff95973/snapshot.json`,
SHA-256 `ee55cdd801da98d66acd09dd754222457cdc464f38fabe0471b186456e0b5221`.
Neither artifact was changed.

Production differed only in transactions (395 → 402) and import runs (125 → 126).
Every historical row remained equivalent, and current source fingerprints matched
the existing signed bank-import acceptance. Thus seven legitimate transactions
and one import run triggered the old whole-table equality check.

`load_config()` also raises `SOURCE_SNAPSHOT_CHANGED` if the snapshot **file** hash
changes. That independent protection remains unchanged; it was not this failure.
Historical evaluation scripts retain their exact-snapshot comparisons.

## Historical protected baseline

The preserved archive `data/interim/ongoing_import/before.json` contains the
pre-import rows. Before using any archived IDs, the guard recomputes each archived
table fingerprint and requires it to equal the original accepted fingerprint.
This authenticates the archived field values and ID set using the existing
baseline. Startup never creates, refreshes or rewrites this archive from live data.
Keep this private archive with the accepted snapshot when moving the installation.
Missing, modified or incompatible archives fail closed when append validation is
needed. An exact full-table match still proves integrity without consulting it.

The protected historical scope remains all fields of 16,192 rows in 14 tables:

| Table | Protected rows |
| --- | ---: |
| transactions | 395 |
| import_runs | 125 |
| documents | 12 |
| energy_bill_details | 14 |
| energy_readings | 15,431 |
| forestry_sales | 1 |
| forestry_sale_lines | 24 |
| invoices | 9 |
| invoice_lines | 40 |
| metering_points | 2 |
| transaction_invoice_allocations | 9 |
| transaction_label_reviews | 128 |
| transaction_reversal_candidates | 2 |
| tax_reviews | 0 |

The guard selects current rows with those historical primary keys and compares
the deterministic all-field aggregate to the **original** accepted hash. Missing
IDs, changed fields (including amounts, dates, merchant, raw source, source file,
import linkage and other provenance), duplicate primary IDs, and bank source-ID
collisions fail. Replacing a historical row under a new identity also fails.
Decimal and date serialization preserves the original fingerprint format.

## Current append-only state

Additional rows outside that authenticated ID set are permitted. They do not
become historical baseline entries automatically. Import validation, database
uniqueness constraints, signed review-source acceptance, review/audit history,
and knowledge/candidate integrity mechanisms remain unchanged. This guard is not
a substitute for those mechanisms and does not assert that arbitrary appended
content is trustworthy.

`source_fingerprints()` returns the full **current** fingerprints after historical
verification. Ask's preflight/postflight comparison therefore still detects
changes during a question. Review still compares against its separately signed
current source state; this change does not auto-accept an import into a review
window or weaken its current-source guard. New audit/knowledge/candidate records
outside the historical table scope do not invalidate the historical baseline.

## Focused verification

`apps/api/tests/test_historical_sources.py` covers unchanged data, appends,
amount/date/merchant/source/provenance mutation, deletion with and without a
replacement row, primary/source identity collisions, tampered archive rejection,
normal bank import, duplicate re-import, fresh-process verification after import,
and a missing archive. Integration uses a disposable PostgreSQL schema; no
production import or review decision is performed.

Run with the project's `TAPIO_TEST_DATABASE_URL`:

```sh
.venv/bin/pytest -q apps/api/tests/test_historical_sources.py \
  apps/api/tests/test_ongoing_sources.py apps/api/tests/test_pilot.py \
  apps/api/tests/test_workspace.py
```

Private production counts and verification artifacts are under
`data/interim/startup_guard/`. The existing accepted configuration, snapshot,
archive, and production records are not regenerated or rewritten.

Final result: **80 focused tests passed**; Ruff and whitespace checks passed.
The normal `./scripts/start_pilot.sh` preflight passed and Uvicorn started on
`http://127.0.0.1:8011`. Review queue, individual Review, Ask, Import and Summary
returned HTTP 200. The Review data endpoint loaded successfully with the existing
verified write profile enabled. No model calls, production imports or review
commits were made during this verification. The local review implementation seal
was renewed for the tested guard and helper; its baseline source artifacts were
not changed.
