# Tapio

Python data foundation for a Finnish rural property and small forestry activity.
The LLM interprets; code calculates. This phase contains a PostgreSQL schema,
FastAPI health endpoint and a Pandera energy validation contract.

Python 3.12, FastAPI/Pydantic v2, SQLAlchemy 2, Alembic, Polars and Pandera.
PostgreSQL 16 runs in Docker; the application runs locally.
See [architecture](docs/architecture.md) and [data dictionary](docs/data_dictionary.md).

## Local setup

Install uv and Docker with Compose; start your Docker runtime first. From the repository root:

```sh
cp .env.example .env
mkdir -p data/raw data/interim data/processed
uv sync --locked
docker compose up -d --wait
uv run alembic upgrade head
uv run uvicorn apps.api.app.main:app --reload --host 127.0.0.1 --port 8000
```

PostgreSQL defaults to localhost:5433. If changing credentials or ports, update
both DATABASE_URL and the POSTGRES_* values in .env. Defaults are local development
credentials. If Compose is installed as a standalone command, use `docker-compose`.

## Health check

```sh
curl --fail http://127.0.0.1:8000/health
```

Returns `{"status":"ok","database":"ok"}` after a database query, or HTTP 503
if the database is unavailable. This does not verify migration state.

## Database migrations

```sh
uv run alembic current
uv run alembic upgrade head
uv run alembic check
uv run alembic revision --autogenerate -m "describe schema change"
```

Review generated migrations before applying them. `uv run alembic downgrade -1`
reverts the latest migration and may delete data. Never use create_all for schema setup.

```sh
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

## Energy ingestion

Import an inspected Finnish energy export using an explicit metering-point code:

```sh
uv run python -m data_pipeline.ingest.energy --file data/raw/2025.csv --metering-point <code>
uv run python -m data_pipeline.verify_energy --metering-point <code>
```

The importer returns a JSON summary and exits nonzero on failure. Exact successful
repeats are audited and skipped; overlapping hours are rejected. See
[energy ingestion](docs/energy_ingestion.md) for formats, DST and failure policies,
and the [verification report](docs/energy_ingestion_review.md) for results.

## Consumption experiment

```sh
uv run python -m ml.experiments.temperature_consumption --metering-point <code>
```

Runs a fixed chronological comparison with seasonal naive, Ridge and HGB.
Detailed results and plots remain ignored under `ml/evaluation/output/`.
See [Experiment 01](docs/ml_experiment_01.md) for availability assumptions and results.

Experiment 02 uses the fixed January–February 2026 winter holdout and compares
last-hour, daily and weekly naive baselines with the same Ridge/HGB models:

```sh
uv run python -m ml.experiments.temperature_consumption --metering-point 643006966022870423 --winter
```

See [winter results](docs/ml_experiment_02.md) and
[verification](docs/ml_experiment_02_review.md). Persistence is the strongest winter
baseline; Ridge improves MAE by 3.18%, while HGB is worse. Detailed outputs remain
ignored; the reviewed aggregate snapshot is in `ml/evaluation/experiment_02_summary.json`.

## Bank ingestion

After `uv run alembic upgrade head`, import an inspected bank CSV using a stable local
account alias (not an account number):

```sh
uv run python -m data_pipeline.ingest.bank --file /Users/tyokone/Downloads/tapahtumat20250101-20251231.csv --account-key primary
uv run python -m data_pipeline.verify_bank --account-key primary --private-output
```

See [bank ingestion](docs/bank_ingestion.md) and [verification](docs/bank_ingestion_review.md).
Category/context rules are weak suggestions; recurrence and refund matches are
candidates. No classifier, tax decisions or invoice reconciliation is implemented.
Detailed generated outputs stay under ignored `data/processed/bank/`.

## Human transaction labels

Migration 0003 separates confirmed classification labels from weak suggestions.
The private review queue is ready for manual review; no human labels are invented.
See [label definitions and CSV instructions](docs/transaction_labeling.md) and
[verification results](docs/transaction_labeling_review.md).

**Current workflow:** the finalized v2 CSV can be imported with a local reviewer
alias. Exact source bytes, including evidence/group fields, are archived privately;
human category/context labels remain authoritative. See
[the finalized import instructions](docs/transaction_labeling.md#finalized-human-import-2026-10-13).

```sh
uv run python -m data_pipeline.labels.import_transaction_reviews --file data/processed/bank/review_queue_v2_grouped.csv --reviewer risto
uv run python -m data_pipeline.labels.export_ground_truth --account-key primary --report-only
```

Final reviews are protected from replacement. Ground-truth export accepts only
human-reviewed rows. Transaction classifier training remains a later phase.
