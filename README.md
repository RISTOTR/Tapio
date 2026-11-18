# Tapio

Tapio is a local-first financial, property and forestry intelligence project built
around a Finnish rural property and small forestry activity. It connects bank
transactions, electricity readings and source documents into inspectable evidence.

**The LLM interprets; code calculates.** Financial and energy calculations are
deterministic. The language model proposes typed evidence plans and references;
code retrieves the required evidence, validates the references and renders the
financial explanation. It does not delegate financial arithmetic to the model.

Built with **Python 3.12, PostgreSQL, FastAPI, Pydantic v2, SQLAlchemy 2 and Polars**.
TAPIO is a **personal, local browser application** with an evidence assistant and
explicitly gated import/review writes. Its earlier read-only agent passed a frozen
development gate and a single sealed holdout; those results describe that historical
baseline, not every feature subsequently added.

## What it does

- Imports Finnish bank CSVs and Sampo card exports with preview, duplicate detection
  and explicit import confirmation.
- Ingests hourly electricity consumption and solar export data.
- Reconstructs electricity costs from source-backed tariffs and compares fixed
  versus spot pricing using real historical consumption.
- Ingests invoices and forestry-sale documents and reconciles them with bank entries.
- Keeps human-confirmed classifications authoritative over weak suggestions.
- Provides a bounded read-only evidence layer across financial domains.
- Answers questions using typed query plans, deterministic calculations and current
  confirmed classifications, preserving requested dates, categories and contexts.
- Routes relevant questions to read-only Gmail/MCP evidence and can analyze supported
  email attachments, including PDF text. Sources and material evidence gaps are visible.
- Provides evidence-driven tax suggestions while keeping classification and tax
  treatment separate; normal answers avoid repetitive disclaimer boilerplate.

## Browser workspace

- **Import** (`/app/import`): inspect a CSV, see its account, date range, new rows and
  duplicates, then explicitly choose **Import and analyze**. New records enter Review.
- **Review** (`/pilot/confirmation/groups`): grouped, quick and individual confirmations, with evidence,
  preview/apply safeguards and authoritative server state. Category and context are
  independent decisions.
- **Ask** (`/app/ask`): natural-language questions, direct answers, structured transaction
  results and expandable evidence. Supported transaction results can be exported as CSV.
- **Summary** (`/app/summary`): placeholder for a future period overview.

### Sampo card imports

Choose **Sampo card export** in Import to add expenses paid outside the Finnish bank
account, such as Spanish Visa travel expenses. The supported UTF-8 CSV columns are:

```csv
transaction_date,merchant,description,amount,currency,sampo_category,source_account,source_transaction_id,source_system
```

Use ISO dates (`YYYY-MM-DD`), signed decimal amounts (`-29.90` for an expense),
`EUR` currency and `SAMPO` as the source system. Each file must contain one account.
Keep its account name and transaction IDs stable across exports. Other currencies
and multiple-account files are currently rejected.

Sampo has a separate source namespace from Finnish bank imports. Repeated IDs in
that account are skipped only when their source fields match; conflicting records
are rejected. Original descriptions, account names and Sampo categories are retained
as evidence. Importing does not confirm TAPIO categories, contexts or tax treatment.
Deduplication uses source identity; it does not automatically reconcile the same
purchase represented in two different systems.

The first Sampo import and subsequent analysis/review were confirmed working by the
user on 18 November 2026. Focused import tests and a desktop/mobile browser preview
passed during implementation; no full-repository verification was run for this change.

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

Conditional external evidence retrieval:
Ask -> bounded evidence routing -> local MCP -> Gmail API (gmail.readonly)
                                           -> relevant messages / attachments
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
- Gmail uses `gmail.readonly`; credentials stay local. Ask uses Gmail when email
  evidence is relevant or local evidence is insufficient, not for every question.
- Import/review writes require deliberate actions and integrity gates. Historical
  source records remain protected while verified append-only imports are accepted.

## Historical evaluation

The earlier read-only acceptance baseline comprised **806 tests**. Development reached **20/20
evidence-complete and 8/8 critical**; the first and only sealed holdout reached
**8/8 evidence-complete**. There were no retries or tuning against the holdout.
The accepted configuration and dependencies are frozen by SHA-256. Subsequent
pilot tests expanded the suite; historical hygiene verification is recorded in
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

For the existing configured personal workspace on macOS, run:

```sh
./scripts/start_pilot.sh
```

This starts Colima/PostgreSQL, checks the accepted local configuration and starts
TAPIO at **http://127.0.0.1:8011/app/import**. It requires the existing private pilot
artifacts and local configuration. Import/review writes also require the activated
profile and matching implementation verification seal. Do not bypass a failing gate
or regenerate historical baselines to make startup pass.

### Base API / fresh development environment

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

### Proportionate verification

Normal iteration uses focused tests for changed behavior and lint/format checks on
changed files. Add one relevant browser smoke check for visible UI changes. Do not
routinely run the full suite, privacy scans or repository-wide integrity audits.
Persistence, import/deduplication and review-authority changes need focused subsystem
coverage. Broader release verification is a separate, explicitly requested task.

For example, the import subsystem can be checked with:

```sh
uv run pytest -q apps/api/tests/test_sampo_import.py apps/api/tests/test_import_workspace.py -k 'not real_import_ask_browser'
```

Database integration tests require `TAPIO_TEST_DATABASE_URL` pointing to local
PostgreSQL; they create disposable migrated schemas. Without it, database tests are
skipped, so a passing unit-only run is not an integration verification.

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

**Working personal workspace with controlled import/review writes and read-only
Ask evidence retrieval.** Finnish bank and Sampo card imports are available. Summary
remains a placeholder. Gmail has no write permissions; tax output is evidence-driven
suggestion, not an automatic recorded tax decision.

For a repository audit, distinguish historical acceptance reports from current
implementation. Useful priorities are Ask query constraints and evidence traceability,
current classification authority, source identity/deduplication, append-only recovery,
and Gmail/attachment boundaries. Audit findings should identify concrete reproduction
steps and affected code; do not modify private data, acceptance baselines or verification
seals merely to make checks pass.

## Tech stack

Python 3.12 · PostgreSQL 16 · SQLAlchemy 2 · Alembic · FastAPI · Pydantic v2 ·
Polars · Pandera · scikit-learn · pytest · Ruff · uv · Docker · local MCP · Gmail API
