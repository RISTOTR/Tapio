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
