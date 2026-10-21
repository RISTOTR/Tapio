# Energy ingestion

## Import policy (defined before implementation)

The existing schema and migration 0001 remain unchanged. Read source bytes once;
hash and parse that same snapshot. Each readable-file attempt creates an ImportRun.
Use the source type + SHA-256 + parser version as the successful-import lookup key.
Serialize competing attempts for that key with a PostgreSQL transaction advisory
lock, expressed through SQLAlchemy. Hash collisions in the lock only serialize
unrelated work; the full fingerprint is used for the actual lookup.

A completed original import returns `already_imported` on a repeat. Record a new
COMPLETED attempt with row_count=0, outcome=already_imported and the original run
ID in source_metadata. Only outcome=imported is eligible as the original success.
Reject the same fingerprint targeted at a different meter instead of falsely
claiming it was imported there. A newer parser version may retry but must respect
the existing meter/timestamp/grain unique key; never delete or replace readings.

Use one outer database transaction per attempt, with a savepoint for parsing,
validation, metering-point creation and reading inserts. On expected input or
constraint failure, roll back the savepoint and mark the attempt FAILED with zero
loaded rows and a sanitized error code. On success commit readings and COMPLETED
status together. Database unavailability, process termination or commit failure
can prevent an audit record; never report success before commit succeeds.

Meter identity must be an explicit external code from the source or CLI. Conflicts
between those identifiers are errors. Reuse the unique external_code; never infer
identity from addresses. All imported series in this phase use source_grain=hourly.

## Canonical contract

UTC microsecond timestamps, Float64 consumption_kwh and solar_export_kwh, and
nullable Float64 temperature_c. Energy is finite and nonnegative; temperature
bounds remain [-60,60] Celsius. Validate with Pandera before inserts. Reject
empty input and duplicate UTC instants; never aggregate duplicates or fabricate
zeroes. Solar export means netted grid export, not gross PV generation.

Database quantities remain NUMERIC(20,6). Reject values that cannot be represented
at that precision instead of silently rounding. Decimal conversion is a separate
persistence boundary from the canonical Polars frame.

## Inspected source formats

All three supplied files use UTF-8 with a BOM and semicolon delimiters. Strict UTF-8
without a BOM is also accepted; there is no lossy encoding fallback or delimiter
sniffing. Headers must match exactly, including order and units. Blank records,
extra/missing cells and malformed numeric text are rejected. Polars reads the
fields as strings; a CSV structural check ensures it cannot silently skip rows.

| Format | Source columns | Units / temperature |
| --- | --- | --- |
| Annual | Aika; Kulutus (netotettu) kWh; Tuotanto (netotettu) kWh; Vuorokauden keskilämpötila | kWh, decimal commas; daily mean Celsius repeated on hourly rows |
| Day | Aika; Kulutus Wh; Tuotanto Wh | Wh converted by dividing by 1000; no temperature column, therefore null |

The annual source's `Tuotanto (netotettu)` maps to `solar_export_kwh`, never gross
PV generation. The day source's `Tuotanto` maps to the same export channel under
the supplied grid-export semantics, but its header does not assert netting. No
netting calculation is performed. Its values can differ from the annual source;
see the review report. The files contain no meter code, so --metering-point is
required. For these real 2025/2026 files the user supplied external metering-point
code `<METERING_POINT_CONSUMPTION>`; consumption and netted solar export are loaded together
as one hourly series. Vattenfall separately uses contractual usage-point ID
`<METERING_POINT_PRODUCTION>` for solar-export/Omatuotanto settlement. This is not a second
copy of the CSV or a second MeteringPoint. Model that contractual/export identifier
later if a source requires it. The day file was confirmed to belong to the same
meter and is rejected when its hours overlap the annual data.

Filename and byte hash are retained; no address inference is used.

`Aika` uses ISO calendar dates, T, HH:MM:SS and optional three-digit milliseconds.
Annual files require explicit +/-HH:MM offsets. Day files may be naive Finnish
local time. Only exact hour starts are accepted. Explicit offsets must agree with
Europe/Helsinki for the supplied wall-clock date; malformed dates, non-hourly
instants and contradictory offsets are errors. The two 2025 autumn 03:00 hours
are distinct because their source offsets are +03:00 and +02:00.

Naive times are checked by round-tripping both DST folds through UTC. One unique
instant is accepted; zero means a nonexistent spring-forward time and two means
an ambiguous autumn time. Both cases are rejected rather than guessed from row
order. Normalized timestamps are always UTC microsecond datetimes.

Blank/missing temperature is null; unknown marker strings are rejected. Required
energy blanks are errors. Plain decimal comma/dot numbers are accepted; NaN,
infinity, mixed separators, unit suffixes and scientific notation are rejected.
Negatives are not clamped or made absolute; Pandera rejects negative energy.

## Import command

```sh
uv run python -m data_pipeline.ingest.energy --file data/raw/2025.csv --metering-point <code>
```

Both inspected formats are supported by parser version 1.0.0, source type
finnish_energy_csv. The CLI returns concise JSON with status and counts. Exit 0
means imported/already_imported; exit 1 means input/database failure (argparse uses
2 for invalid arguments). Errors omit source values and SQL parameters. An unreadable
file cannot supply a hash and therefore cannot create a reliable ImportRun.

## Verification methodology

Use synthetic source fixtures only in Git. Real files stay local and ignored.
Monthly checks group timestamps in Europe/Helsinki, not UTC. August reconciliation
uses [2026-08-01 00:00 Europe/Helsinki, 2026-09-01 00:00 Europe/Helsinki).
Compare Decimal database sums with the user-supplied bill values 588.02 kWh
consumption and 74.20 kWh export. Absolute difference is abs(database - invoice);
percentage difference is 100 * absolute difference / abs(invoice). Never adjust
readings to match a bill. Check boundaries, missing hours, duplicates and source
precision before interpreting a discrepancy.

## Implemented boundaries

`data_pipeline.normalize.energy` provides decimal-text normalization and timezone
resolution. The source parser returns a typed ParsedEnergy with text-valued canonical
column names and explicit units/offset policy; normalization creates the typed
canonical Polars frame. These remain separate from database model instances.

`data_pipeline.load.energy.import_energy_bytes` receives immutable source bytes,
explicit provenance and a source normalization callable. It always runs the canonical
Pandera validation itself. Its typed result includes outcome, source filename,
rows parsed/loaded, meter, parser version, digest, run ID and a sanitized error code.
Reading batches share a single savepoint and outer transaction. Failed batches
also roll back a newly-created metering point. Concurrent same-fingerprint attempts
are serialized. Direct writes outside this loader are still governed by database
keys, not by its application-level idempotency policy.

`data_pipeline.verify_energy` runs read-only monthly SQLAlchemy aggregations for
consumption/export totals, average temperature, row counts, null temperatures,
duplicates and minimum/maximum instants. `reconcile_month` performs exact Decimal
comparison for a caller-supplied month and bill quantities. No rows means unknown
totals, not fabricated zeroes. A zero invoice total yields undefined (null) percentage.

```sh
uv run python -m data_pipeline.verify_energy --metering-point <code>
```

Implementation references: [Python zoneinfo](https://docs.python.org/3/library/zoneinfo.html)
for explicit folds/offsets and [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)
for savepoint rollback within the audit transaction.
