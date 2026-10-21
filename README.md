# Tapio

Tapio is a local-first financial, property and forestry intelligence project built
around a Finnish rural property and small forestry activity. It connects bank
transactions, electricity readings and source documents into inspectable evidence.

**The LLM interprets; code calculates.** Financial and energy calculations are
deterministic. The language model proposes typed evidence plans and references;
code retrieves the required evidence, validates the references and renders the
financial explanation. It does not delegate financial arithmetic to the model.

Built with **Python 3.12, PostgreSQL, FastAPI, Pydantic v2, SQLAlchemy 2 and Polars**.
The bounded agent has passed a frozen development gate and a single sealed holdout,
qualifying it for a **human-supervised read-only pilot**. This is an engineering
prototype, not autonomous bookkeeping or a production financial adviser.

## What it does

- Imports and normalizes bank transactions with repeat-import safeguards.
- Ingests hourly electricity consumption and solar export data.
- Reconstructs electricity costs from source-backed tariffs and compares fixed
  versus spot pricing using real historical consumption.
- Ingests invoices and forestry-sale documents and reconciles them with bank entries.
- Keeps human-confirmed classifications authoritative over weak suggestions.
- Provides a bounded read-only evidence layer across financial domains.
- Supports separate read-only Gmail evidence discovery through a local MCP integration.

## Architecture

```text
User question
    |
Typed evidence plan
    |
Deterministic evidence coordinator
    |
+----------------------------------+
| PostgreSQL: bank / energy         |
| documents / reconciliation       |
| accepted saved energy results    |
+----------------------------------+
    |
Validated evidence handles
    |
Trusted deterministic renderer

External evidence workflow (separate from pilot):
Gmail API (gmail.readonly) -> local MCP server -> human evidence review
```

SQLAlchemy 2 models and Alembic migrations define the PostgreSQL store. FastAPI
and Pydantic v2 provide API and tool contracts; Polars and Pandera handle tabular
processing and validation. scikit-learn supports offline experiments. A
provider-neutral agent interface separates model adapters from deterministic
orchestration. The local MCP integration exposes bounded Gmail evidence tools.

## Reliability / safety design

- Decimal financial arithmetic; no model-generated financial calculations.
- Human-reviewed labels override weak rules and ML suggestions.
- Separate bank cash-flow, invoice and sale-document views prevent silent double counting.
- Ambiguous reconciliation stays ambiguous; category/context does not determine tax treatment.
- Read-only pilot database sessions and tool registry, bounded agent rounds,
  mandatory retrieval and explicit validated evidence handles.
- Retrieved content is untrusted data, not instructions; prompt-injection defenses
  are tested alongside evidence and reference validation.
- Gmail uses `gmail.readonly`; credentials stay local and the pilot exposes no Gmail tools.

## Evaluation

The acceptance baseline comprised **806 tests**. Development reached **20/20
evidence-complete and 8/8 critical**; the first and only sealed holdout reached
**8/8 evidence-complete**. There were no retries or tuning against the holdout.
The accepted configuration and dependencies are frozen by SHA-256. Subsequent
pilot tests expanded the suite; the current hygiene verification is recorded in
[the privacy review](docs/repository_privacy_review.md).

These results support only a human-supervised read-only pilot. Evidence-completeness
checks do not prove general financial correctness, tax expertise, autonomous
financial advice or production readiness. See the
[sealed acceptance report](docs/phase_10_sealed_holdout_acceptance.md) for scope and limits.

## Interesting findings

- Transaction classification generalized poorly to unseen merchants, so it was not adopted autonomously.
- Energy forecasting offered limited gains over simple baselines in the tested periods; further work stopped.
- Consumption was disproportionately concentrated in expensive spot-price periods,
  making consumption-weighted pricing more informative than a simple average.
- Mandatory deterministic orchestration was more reliable than free-form tool selection
  in the development evaluation.

## Project evolution

The project progressed from structured ingestion and ML experiments to document
reconciliation, a deterministic energy-cost engine, Gmail/MCP evidence discovery,
bounded agent evaluation and supervised pilot acceptance. Historical technical
reports retain the decisions, failures and validation behind that progression.

## Privacy

Real bank files, invoices, Gmail content and source documents are not committed.
Runtime datasets, OAuth credentials and tokens remain local under ignored paths;
public fixtures are synthetic or redacted. Privacy checks scan every versioned
file, with optional private denylist matching and nonignored-new-file checks.
Historical documentation previously exposed metering identifiers; current-tree
redaction does **not** erase Git history. See the [privacy review](docs/repository_privacy_review.md).

## Running locally

Use Python 3.12, uv and Docker with Compose. Start the Docker runtime first, then
run from the repository root:

```sh
cp .env.example .env
uv sync --locked
docker compose up -d --wait
uv run alembic upgrade head
uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000
```

PostgreSQL defaults to port 5433. The example credentials are for local development;
keep `DATABASE_URL` and `POSTGRES_*` settings consistent. If installed separately,
use `docker-compose` instead of `docker compose`. `/health` checks database access.
This API startup command does not invoke a model or import private datasets.

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv lock --check
uv run alembic check
uv run python scripts/check_repository_privacy.py --include-untracked
```

Database integration tests need `TAPIO_TEST_DATABASE_URL` pointing to a local test
PostgreSQL database; they create disposable migrated schemas. Without it those
tests are skipped. For the default local setup:

```sh
TAPIO_TEST_DATABASE_URL=postgresql+psycopg://tapio:tapio_local@localhost:5433/tapio uv run pytest
```

Gmail setup is documented in [Gmail integration](docs/gmail_integration.md).
The [supervised pilot instructions](docs/phase_11_human_supervised_pilot.md) describe
the separately gated pilot, which requires private accepted artifacts and a local
provider key; a public clone alone does not include those artifacts.

## Repository guide

- [Architecture and data boundaries](docs/architecture.md)
- [Agent architecture](docs/agent_architecture.md)
- [Energy cost engine review](docs/energy_cost_engine_review.md)
- [Gmail integration](docs/gmail_integration.md)
- [Sealed holdout acceptance](docs/phase_10_sealed_holdout_acceptance.md)
- [Repository privacy review](docs/repository_privacy_review.md)

## Current status

**Human-supervised read-only pilot accepted.** Not autonomous, not a production
deployment, no write-enabled Gmail and no automatic tax decisions.

## Tech stack

Python 3.12 · PostgreSQL 16 · SQLAlchemy 2 · Alembic · FastAPI · Pydantic v2 ·
Polars · Pandera · scikit-learn · pytest · Ruff · uv · Docker · local MCP · Gmail API
