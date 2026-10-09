# Energy ingestion review — 2026-10-09

## Implementation

Energy-only implementation; no foundation models or migrations changed. Source
parsing, normalization, canonical Pandera validation and transactional loading are
separate. UTF-8 BOM/semicolon exports are read by Polars as text; exact inspected
headers determine units and offset requirements. Decimal commas are explicit,
missing energy is rejected, missing temperature is null, and Wh is divided by 1000.
Production-labelled columns map to solar_export_kwh, not gross PV generation.

The importer reads a byte snapshot once for hashing and parsing. The existing
ImportRun schema records every readable-file attempt. Successful fingerprint
repeats (hash + source type + parser version) return already_imported with a new
audit attempt but no new readings. A transaction advisory lock serializes concurrent
same-fingerprint attempts. Meter mismatches fail; different parser versions do not
replace overlapping records. All writes use SQLAlchemy; there is no raw loader SQL.

Each attempt has one outer transaction and a loading savepoint. Validation,
new-meter creation and all reading batches roll back together on failure; the
outer transaction records the failed attempt. Infrastructure/commit failure may
prevent recording an audit row and is never reported as success. A duplicate key
in a later batch cannot leave earlier inserted rows committed.

Timestamps have an explicit ISO grammar. Annual offsets must match Europe/Helsinki;
naive day times use that zone and reject ambiguous/nonexistent DST instants.
The actual 2025 autumn repeated hour is disambiguated by source offsets. Canonical
and persisted timestamps are timezone-aware. Verification month boundaries use
Helsinki calendar months, not UTC months.

## Verification

- Ruff format --check: passed (48 files, including the review’s Python example).
- Ruff check: passed.
- git diff --check: passed.
- pytest with PostgreSQL enabled: **57 passed**, no skips.
- Integration tests use a disposable schema migrated with Alembic, then drop only
  that test schema. Existing personal/domain tables are not reset.
- Tests cover both CSV formats, BOM, decimal commas, null temperatures, negative
  consumption/export, bad/missing timestamps, duplicate instants, malformed CSV,
  DST offsets/gaps/ambiguity, provenance, idempotency, concurrent retries, meter
  mismatch, newer-parser overlap, batch rollback, precision rejection and CLI exit
  status. Monthly checks test local boundaries and exact reconciliation arithmetic.
- Alembic check: no schema drift. Migration 0001 is unchanged.
- Final October 9 verification initially found Colima stopped. The existing runtime
  and PostgreSQL container were restarted; all 57 tests and the schema check then
  passed again. The persisted real-data totals were rechecked after restart.
- Source files remain in Downloads; no real hourly values are copied to fixtures.
  Committed sample candidates are explicitly synthetic.

## Real source inspection and canonical validation

| File | Validated rows | Null temperatures | Hourly gaps | Duplicate instants |
| --- | ---: | ---: | ---: | ---: |
| 2025.csv | 8,760 | 0 | 0 | 0 |
| 2026.csv | 6,671 | 0 | 0 | 0 |
| 2026-10-05.csv | 24 | 24 | 0 | 0 |

2025 covers the full local calendar year. 2026 covers January 1 through October 5
23:00 inclusive; 6,671 hours is consistent with the spring DST transition. The day
file covers October 5 and overlaps the annual export's final 24 hours. No source
file contains a meter identifier.

The October 5 day export totals 34.548 kWh consumption and 0.434 kWh export. The
same annual-export hours total 34.114 kWh consumption and 0 kWh export. Every hour
preserves the same consumption-minus-export balance. Both channels differ by the
same amount, consistent with a netting difference rather than a timestamp shift.
The day headers do not assert netting. No transformation is applied to force them
to agree. These source-file checks explain why the two exports must not be combined. The
user confirmed that the day file belongs to the same meter.

## Real PostgreSQL imports and reconciliation

All real series use external metering-point code `643006966022870423` supplied by
the user. The separate Vattenfall solar-settlement usage-point identifier
`643006966035063447` is documented only: no second MeteringPoint was created and
no CSV rows were duplicated across identifiers. That contractual association can
be modeled later if an actual source requires it.

| Source / attempt | Result | Parsed | Loaded |
| --- | --- | ---: | ---: |
| 2025.csv | imported | 8,760 | 8,760 |
| 2026.csv | imported | 6,671 | 6,671 |
| 2026.csv repeat | already_imported | 0 (parsing skipped) | 0 |
| 2026-10-05.csv | failed: database_constraint_conflict | 24 | 0 |

All four attempts retain their own ImportRun audit row and raw SHA-256. The day
attempt exits 1 because every hour already exists in the annual file; no records
were replaced. After that failure the database still contains **15,431 readings**,
zero duplicate instants, zero hourly gaps and zero null temperatures. The day
source's 24 missing temperatures were verified as null during canonical validation;
its rejected rows are not in the database. Synthetic tests also verify NULL storage.

Global UTC range: 2024-12-31 22:00 through 2026-10-05 20:00, inclusive. In Helsinki
this is January 1, 2025 00:00 through October 5, 2026 23:00. March has 743 hours;
October 2025 has 745. October 2026 contains only the first five days (120 hours).
The continuous sequence and local month counts show no unexpected missing/extra
hours at the calendar or DST boundaries.

### August 2026 bill review

Reviewed the supplied 37158987.pdf locally (five pages). It is dated September 7,
2026 and covers August 1–31 for both the consumption and Omatuotanto lines. It
shows 588.02 kWh consumption and 74.20 kWh solar settlement, with the respective
usage-point identifiers described above. PDF text extraction was used only for
this local review; no PDF parser, document ingestion or invoice workflow was added.
The PDF and extracted text were not copied into the repository.

The SQL comparison selects UTC instants in the Helsinki-local half-open interval
[August 1 00:00, September 1 00:00), equivalent to
[July 31 21:00 UTC, August 31 21:00 UTC). All **744 hours** are present.

| Measure | Database kWh | Invoice kWh | Absolute difference kWh | Percentage difference |
| --- | ---: | ---: | ---: | ---: |
| Consumption | 588.024 | 588.02 | 0.004 | 0.000680249% |
| Solar export | 74.200 | 74.20 | 0.000 | 0% |

The consumption difference is exactly consistent with displaying the database
sum to two decimal places: 588.024 rounds to 588.02. Export matches exactly.
There is no evidence here of a boundary, missing-hour or netting discrepancy in
the annual series. The separate day file demonstrates a netting difference, but
was not substituted into that series. No source values were altered for agreement.

### Monthly database checks

Totals use exact NUMERIC arithmetic; mean temperature is displayed to three decimals.
It is an hourly-row-weighted average of the source daily means. Every month has
zero duplicate instants and zero null temperatures. Full per-month minimum/maximum
timestamps are also returned by the read-only verification command.

| Helsinki month | Readings | Consumption kWh | Solar export kWh | Mean temperature °C |
| --- | ---: | ---: | ---: | ---: |
| 2025-01 | 744 | 2064.351 | 0.000 | -4.616 |
| 2025-02 | 672 | 1852.061 | 0.000 | -4.639 |
| 2025-03 | 743 | 1345.942 | 9.740 | -0.220 |
| 2025-04 | 720 | 1042.630 | 39.156 | 4.090 |
| 2025-05 | 744 | 784.311 | 85.149 | 8.487 |
| 2025-06 | 720 | 550.402 | 81.948 | 13.463 |
| 2025-07 | 744 | 529.973 | 145.523 | 19.965 |
| 2025-08 | 744 | 542.236 | 86.587 | 14.329 |
| 2025-09 | 720 | 687.639 | 31.483 | 11.727 |
| 2025-10 | 745 | 1037.667 | 0.703 | 5.526 |
| 2025-11 | 720 | 1538.847 | 0.000 | 1.313 |
| 2025-12 | 744 | 1857.384 | 0.000 | -1.061 |
| 2026-01 | 744 | 2558.235 | 0.000 | -11.697 |
| 2026-02 | 672 | 2445.298 | 0.000 | -13.300 |
| 2026-03 | 743 | 1208.138 | 10.636 | 2.585 |
| 2026-04 | 720 | 1025.358 | 49.652 | 3.803 |
| 2026-05 | 744 | 673.951 | 107.701 | 10.855 |
| 2026-06 | 720 | 498.003 | 122.142 | 15.807 |
| 2026-07 | 744 | 512.550 | 83.368 | 16.406 |
| 2026-08 | 744 | 588.024 | 74.200 | 14.445 |
| 2026-09 | 720 | 707.428 | 19.630 | 10.667 |
| 2026-10 | 120 | 155.053 | 0.535 | 8.820 |

The monthly totals are seasonally plausible: greater consumption in cold months
and summer export. This is a sanity check, not a weather/consumption model or an
independent validation of every supplier measurement.

Reproduce monthly checks with:

```sh
uv run python -m data_pipeline.verify_energy --metering-point 643006966022870423
```

Reproduce the exact August comparison using the read-only helper:

```python
from datetime import date
from decimal import Decimal
from apps.api.app.core.database import SessionLocal
from data_pipeline.verify_energy import reconcile_month

with SessionLocal() as session:
    result = reconcile_month(
        session,
        "643006966022870423",
        date(2026, 8, 1),
        Decimal("588.02"),
        Decimal("74.20"),
    )
print(result)
```

## Files created

- data_pipeline/ingest/energy.py
- data_pipeline/ingest/energy_csv.py
- data_pipeline/normalize/energy.py
- data_pipeline/load/energy.py
- data_pipeline/verify_energy.py
- apps/api/tests/test_energy_parser.py
- apps/api/tests/test_energy_normalization.py
- apps/api/tests/test_energy_load.py
- data/sample/synthetic_energy_hourly.csv
- data/sample/synthetic_energy_day.csv
- docs/energy_ingestion.md
- docs/energy_ingestion_review.md

## Files changed

- README.md
- docs/architecture.md
- docs/data_dictionary.md

No dependency, schema, foundation validation contract or existing test changes.

## Assumptions and limitations

Only the two inspected header layouts are accepted. The annual source's temperature
is a daily mean repeated hourly; monthly AVG is weighted by available hourly rows.
Day export production is treated as the grid-export channel under the task's
semantics, but its netting differs from the annual export; vendor documentation
would be needed to generalize this behavior to other exports. Unsupported precision
is rejected rather than silently rounded. Unknown null markers are errors.

The loader's advisory lock protects clients using this import path; direct SQL
writers still rely on database constraints. Host timezone data supplies Europe/Helsinki.
Failed transaction setup/commit or process termination may leave no audit attempt.
No automatic replacement, correction, gap filling or duplicate aggregation exists.

## Remaining limits and next step

All requested energy-ingestion checks were completed. The overlapping day export
is intentionally not loaded; automatic reconciliation or replacement of differing
source measurements remains outside scope. The two contractual identifiers have
not been modeled as separate sources or accounts. Tests cover deterministic
behavior; they cannot independently certify the supplier's upstream measurements.

Next step: review and accept this energy-ingestion implementation and its documented
netting/overlap policy before choosing a new phase. No ML or bank ingestion was started.
