# Foundation review — 2026-10-08

Implemented the requested foundation only. No importer, product endpoints, frontend,
model training, LLM, retrieval, pgvector, authentication or cloud resources were added.

## Verification

- Python 3.12.13 environment installed through uv; dependency versions recorded in uv.lock.
- Ruff lint and format checks passed.
- All 16 pytest cases passed with PostgreSQL integration enabled, with no skips.
- PostgreSQL 16 started from docker-compose.yml on localhost:5433 with a new volume.
- Alembic revision 0001 generated against the empty database, reviewed and applied.
- Upgrade, downgrade to base, and re-upgrade succeeded; shared enums are removed on downgrade.
- Alembic check reports no new upgrade operations; current revision is 0001.
- FastAPI started on localhost:8000; real HTTP /health returned 200 and
  `{"status":"ok","database":"ok"}`.
- Integration tests round-trip decimals, timestamps, document JSONB and separate
  suggested/confirmed tax contexts, and verify energy duplicate-key rejection.
  All inserted synthetic rows are rolled back.
- Git ignore behavior verified in a temporary Git repository, including uppercase
  PDF/CSV filenames, private data directories, .env and model artifacts. Intended
  synthetic samples, model package marker and .env.example remain eligible for Git.

The machine needed Colima started and Docker Compose installed. Homebrew provides
`docker-compose` here; use that command in place of `docker compose` on this machine.
PostgreSQL and the local API were left running for review.

To repeat database integration tests after migrating a development/test database:

```sh
TAPIO_TEST_DATABASE_URL=postgresql+psycopg://tapio:tapio_local@localhost:5433/tapio uv run pytest -q
```

Without this explicit variable, the three PostgreSQL integration tests skip; the
remaining tests run independently of a database. Local test credentials above
match .env.example. For another database, use its URL explicitly.

## Decisions and verification limits

See architecture.md for the rationale and data_dictionary.md for every field.
Money and quantities use NUMERIC(20,6); timestamps are timezone-aware; document
metadata maps to the SQL `metadata` column through Python `document_metadata`.
Hashes remain non-unique for import-attempt history, and invoice vendor/number
remains non-unique until vendor identity rules exist. Energy series have a unique
meter/timestamp/grain key. Pandera rejects duplicates and invalid normalized data.

No requested foundation check remains unverified. Personal source files, real
import behavior and future prediction/review write workflows were not tested:
those features do not exist yet. Separate tax columns preserve the distinction
between suggestions and decisions; future automated writes still require guarded
updates and authorization, as described in architecture.md. Gitignore cannot stop
forced staging or private data embedded in otherwise permitted source files.

## Files created

This inventory covers every project file, excluding generated virtual-environment
and tool-cache files. The ignored data/raw, data/interim and data/processed directories
were also created and are empty. Local helper scripts used for setup live in /tmp
and are not part of the repository.

```text
.env.example
.gitignore
.python-version
README.md
alembic.ini
apps/__init__.py
apps/api/__init__.py
apps/api/alembic/env.py
apps/api/alembic/script.py.mako
apps/api/alembic/versions/0001_deterministic_core_schema.py
apps/api/app/__init__.py
apps/api/app/core/__init__.py
apps/api/app/core/config.py
apps/api/app/core/database.py
apps/api/app/domain/__init__.py
apps/api/app/domain/base.py
apps/api/app/domain/enums.py
apps/api/app/domain/models.py
apps/api/app/main.py
apps/api/app/routers/__init__.py
apps/api/app/routers/health.py
apps/api/app/schemas/__init__.py
apps/api/app/schemas/health.py
apps/api/app/services/__init__.py
apps/api/tests/test_database.py
apps/api/tests/test_energy_contract.py
apps/api/tests/test_health.py
data/sample/README.md
data_pipeline/__init__.py
data_pipeline/ingest/__init__.py
data_pipeline/load/__init__.py
data_pipeline/normalize/__init__.py
data_pipeline/validate/__init__.py
data_pipeline/validate/energy.py
docker-compose.yml
docs/architecture.md
docs/data_dictionary.md
docs/foundation_review.md
embeddings/__init__.py
ml/__init__.py
ml/evaluation/__init__.py
ml/experiments/__init__.py
ml/features/__init__.py
ml/models/__init__.py
pyproject.toml
uv.lock
```
