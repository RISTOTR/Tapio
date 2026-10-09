# Tapio architecture

Tapio is a learning and portfolio project for a Finnish rural property and small
forestry activity. Its foundation prioritizes Python data engineering, relational
modeling and reproducible validation. There is no frontend or product workflow yet.

## Intelligence boundaries

**The LLM interprets; code calculates.**

- Deterministic: PostgreSQL stores facts and provenance. Python, Polars and SQL
  perform validation, normalization, reconciliation and calculations.
- Statistical (future): scikit-learn generates predictions and scores. Time-series
  features must use past information only, with chronological evaluation and
  documented baselines. Predictions remain distinct from observed facts.
- Generative (future): an LLM selects typed tools and explains their structured
  results. It does not calculate balances, invent measurements or make tax decisions.

The repository implements the schema, configuration, health endpoint and energy
validation contract. Energy ingestion now has format-independent normalization,
a transactional loader, inspected Finnish CSV source parser, local import CLI
and read-only monthly verification; see [energy ingestion](energy_ingestion.md).
There is no trained model, retrieval system or agent.

## Domains and evidence

Bank transactions, energy readings, bills, forestry sales and tax review records
are structured facts. Source documents are unstructured evidence linked through
Document and ImportRun. Invoice lines, forestry lines and transaction/invoice
allocations support evidence reconciliation without assuming one payment per bill.
Solar export is netted electricity exported from the property, not gross PV generation.

Import runs preserve source filename, SHA-256, parser version and metadata. Hashes
are indexed but not unique: retries and parser revisions must remain auditable.
Energy loading defines idempotency by source type, raw SHA-256 and parser version;
audit attempts remain separate from the original successful import. Source documents
retain their hashes; this schema does not store document binaries or personal source files.

## Storage and API

PostgreSQL 16 provides exact NUMERIC arithmetic, JSONB, timezone-aware timestamps,
foreign keys and native enums, with a later path to pgvector. SQLite would make
these semantics and migration tests diverge from the intended database.
SQLAlchemy 2 typed models describe the schema; Alembic is the only schema-change
mechanism. Migrations are explicit snapshots, not runtime calls to create_all.
UUID primary keys are application-generated; timestamps are aware and stored as
TIMESTAMPTZ. Foreign keys restrict deletion by default to preserve provenance.

Python places Polars, Pandera and future scikit-learn/time-series work in one
language. Implementing the backend in Node would duplicate this data tooling and
shift effort back toward already-familiar TypeScript work.
FastAPI runs locally outside Docker. Docker Compose runs PostgreSQL only, bound
to localhost. Each API request receives a session that closes afterward; future
write workflows must explicitly commit or use a transaction context. /health checks
SELECT 1 and reports 503 when PostgreSQL is unavailable; it is not a schema check.

## Validation from day one

Pandera defines the contract between normalization and loading, established before
the source importer was implemented. The current Polars contract is strict: all four required fields, UTC
microsecond timestamps, Float64 measurements, nonnegative finite energy values,
and nullable temperature within -60 to 60 degrees Celsius. These bounds are
validation policy, not a climatological claim. It rejects invalid values without
coercing them. The source parser reads text fields explicitly; normalization handles
decimal commas, source units and timestamps. The loader checks decimal
representability before insertion.
See [Pandera's Polars integration](https://pandera.readthedocs.io/en/stable/polars.html).

Validate each metering point/source-grain series separately. Duplicate timestamps
are rejected; neither summing nor keeping an arbitrary row is safe. The database
also enforces uniqueness on meter + timestamp + grain. The normalizer resolves
Europe/Helsinki local times using source offsets when available, then converts to UTC. Ambiguous or nonexistent naive local times are
rejected; timezone-naive timestamps never reach the canonical validation boundary.

## Decisions and constraints

Monetary amounts and measured quantities use NUMERIC(20,6); this avoids binary
floating-point storage and retains unit-price precision. Rounding and invoice
reconciliation policies remain future work. Optional source fields stay nullable;
missing data must not become fabricated zeroes. Enums cover stable workflow
categories only; vendor, sale type, source grain and match method remain text.
Enums are persisted by their uppercase member names and evolve through migrations.
Meter external codes and the energy reading key are unique. Vendor names alone
cannot establish invoice identity, so vendor/number is not unique. FK columns and
source hashes are indexed; additional indexes should follow actual query evidence.

TaxReview keeps suggested_context/treatment/confidence separate from
confirmed_context and human review fields. Future prediction writes must be limited
to suggestion fields on unconfirmed records, atomically guarded by status.
They must never overwrite confirmed reviews or human decisions. There is no
prediction writer or review endpoint in this phase; the schema alone does not
provide authorization or distinguish a human SQL UPDATE from an automated one.
Any future prediction integration must add concurrency and confirmed-review
regression tests before it can write records.

## Future migrations

Retrieval will introduce pgvector and document chunks in a separate migration,
with document provenance, multilingual Sentence Transformer embeddings and explicit
retrieval evaluation. Only after deterministic typed tools and evaluated retrieval
exist should an LLM be connected to explain their outputs. No pgvector extension,
LLM dependency, orchestration framework, cloud infrastructure or auth is included now.

## Local data hygiene

Raw/interim/processed directories, .env, PDFs, spreadsheets, CSVs and model artifacts
are ignored. Only explicitly named synthetic sample CSV/JSON files are allowed in
data/sample. Gitignore prevents ordinary accidental staging, not force-add or
sensitive text pasted into source code; review every diff. Recreate ignored data
directories after cloning using the README command. No personal data is included.
