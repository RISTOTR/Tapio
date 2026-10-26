# Pilot zero-call failure diagnosis

Verified 2026-10-21. This repair changes pilot observability and failure presentation,
not the accepted model, prompts, evidence requirements, scoring or financial renderer.

## Root cause

Thirteen retained failed pilot requests contain `OperationalError` and zero model
calls. The failure is in the initial `source_fingerprints()` database preflight,
before period parsing, registry creation or model construction. A database
operational failure was converted into the same generic unsupported response used
for invalid evidence. No query-specific unsupported-intent classifier caused it.

Local PostgreSQL was unavailable before the Docker runtime/service was started;
a connection-refused error was observed during the preceding local verification.
The older per-question logs retained only the exception class, so the exact driver
message for each of those 13 requests cannot be reconstructed. They prove the
pre-model database failure; they do not distinguish refusal, access denial and
other operational errors individually. The new diagnostics make that distinction.

The existing PostgreSQL service is now healthy on loopback port 5433. No source
imports, schema changes or data repairs were needed. The same accepted pipeline
works once the database is reachable. When it is unavailable, the pilot now says
that the local evidence source is unavailable or retrieval incomplete, and records
the operational category/stage privately. Changing the year or rephrasing the
question does not repair a database connection.

## Exact diagnostic request and guards

Question: **“How much forestry income did I receive in 2025?”**

The local smoke used FastAPI TestClient against the actual `/pilot/ask` route,
real provider and real read-only database. It exercised the same endpoint used by
the existing page; it was not a browser automation test. No running user pilot
process was found at inspection time, so this was an explicitly configured local
runtime rather than an inspection of another process's environment.

1. The page's form submits JSON to `POST /pilot/ask`; its question field is required
   and length-limited. The backend validates the typed request and strips whitespace.
2. The route passes trusted-host, local-client, same-origin (no Origin header in
   TestClient), and `TAPIO_PILOT_MODE=true` guards. Middleware adds no-store and CSP
   headers. Invalid host/origin/client, disabled mode and malformed requests exit
   before the service; they do not invoke a model.
3. The service lock serializes the request. It allocates a request ID and private
   directory, then verifies the frozen configuration, implementation, snapshot
   and electricity hashes. The accepted ID is `PHASE09H_EXCLUSIVE_C_V1`.
4. `SOURCE_PREFLIGHT`: the pilot's read-only session fingerprints all 14 source
   tables and compares them to the accepted configuration. **This is the failure
   point of the historical zero-call requests.** On failure `model` remains unset,
   usage is empty, and the recorded model-call count is correctly zero.
5. `QUESTION_PERIOD`: the question resolves to `2025-01-01` through `2025-12-31`.
   Year-only aggregates were already supported; no backend date repair was needed.
   The UI wording now explicitly allows a year or one named calendar month/year.
   Multi-year, multi-month and the existing unsupported relative-range checks remain.
6. `READ_ONLY_REGISTRY`: construct the same coordinated evidence registry and
   check its frozen schema/description hash and read-only tool allowlist.
7. `MODEL_INITIALIZATION`: read the local provider credential without logging it.
   `AcceptedModel` preserves `gpt-5.4-mini-2026-03-17`, at most six rounds, 3,000
   completion tokens/request, reasoning `none`, parallel calls false, store false.
8. `ACCEPTED_AGENT` / `MODEL_PLANNER`: execute the exact code object of
   `tapio.agent.exclusive.run_scoped_agent`. A per-request globals mapping supplies
   the existing audit-isolated `ScopedCoordinator` subclass. The observation proxy
   forwards the identical provider arguments/results; it adds no planner or policy.
9. `COORDINATOR_INITIALIZATION` / `EVIDENCE_RETRIEVAL`: use the existing exclusive
   ALL / UNSPECIFIED / SELECTED context union, scope policy, mandatory evidence
   requirements and ledger. UNKNOWN remains a stored context. Read-only tools
   retrieve evidence; no Gmail capability is exposed.
10. `MODEL_FINAL`: the provider returns explicit evidence handles. The unchanged
    coordinator checks required/unknown/duplicate handles and invokes the bounded
    trusted renderer. The wrapper independently checks exact renderer equality,
    successful evidence, mandatory completeness, tax boundary and the 850-word bound.
11. `SOURCE_POSTFLIGHT`: fingerprints match the preflight. `PRESENTATION` constructs
    the public DTO. `PRIVATE_HISTORY` retains diagnostics and source provenance;
    it must succeed before the answer is returned.

The accepted pipeline is not bypassed. The diagnostic observer does not attach
missing handles, infer evidence, adjust filters or manufacture model finals.

## Database visibility and configuration

The diagnostic used the real local PostgreSQL `tapio` database, not an empty test
schema. `SHOW transaction_read_only` returned `on`. The snapshot exists, the local
key file exists, and accepted source fingerprints match. Credentials are not shown.
The pilot's API-key reader, registry, coordinator and frozen provider settings
were unchanged.

| Read-only count | Rows |
|---|---:|
| Transactions, all years | 395 |
| Transactions in 2025 | 225 |
| Transactions with REVIEWED human labels | 127 |
| REVIEWED FORESTRY-context transactions | 16 |
| Positive bank transactions with REVIEWED FORESTRY context | 5 |
| Those positive FORESTRY transactions in 2025 | 2 |
| Documents | 12 |
| Forestry sales | 1 |
| Invoice allocations | 9 |
| Reversal candidates | 2 |

The positive-flow counts are bank receipt candidates by authoritative context;
they do not merge sale-document totals into cash receipts or decide tax treatment.

## Failure handling and private diagnostics

Every service response records request ID, route, pilot mode, accepted configuration
ID, stages reached, planner/coordinator invocation, model calls, requested/returned
views, agent status and structured failure metadata in its private `question.json`.

- `UNSUPPORTED_QUESTION`: unsupported/ambiguous calendar scope.
- `CONFIGURATION_ERROR`: missing or mismatched accepted configuration/registry.
- `MODEL_UNAVAILABLE`: missing/unavailable provider credentials or provider failures.
- `EVIDENCE_UNAVAILABLE`: database operational failures or incomplete mandatory retrieval.
- `VALIDATION_ERROR`: invalid provider final/content or presentation validation.
- `AGENT_EXECUTION_ERROR`: other execution exceptions.
- `SAFETY_REJECTION`: source drift, forbidden capabilities, invalid handles,
  renderer mismatch or tax-boundary failure.

The first failure is preserved even if the accepted engine subsequently returns a
safe status DTO. Database errors distinguish connection refusal, access denial,
authentication failure and other operational failures, with SQLSTATE where supplied.
Provider error codes survive the accepted engine's ValueError-to-status conversion.
The public response contains a safe category-specific explanation, never diagnostic
frames, raw SQL, exception messages, prompts, credentials or private identifiers.

Enable extra private stack-frame metadata locally:

```sh
colima start                         # If using Colima and it is stopped
docker-compose up -d --wait postgres
TAPIO_PILOT_MODE=true TAPIO_PILOT_DIAGNOSTICS=true \
  .venv/bin/uvicorn tapio.pilot.api:app --host 127.0.0.1 --port 8011
```

The extra frames contain only file basename, function and line number. Basic failure
categories are recorded even without diagnostic mode. Inspect
`data/interim/pilot/<request-id>/question.json` locally; diagnostic records are not
served by an API endpoint. Session directories are explicitly owner-only before
provider logs are created. If private history/bootstrap itself fails, the route
returns HTTP 503 and emits safe structured metadata to the local server logger;
it does not silently discard the exception. Mode-disabled requests remain HTTP 503.
Configuration failures reached inside the service now have a privately logged typed
unsupported response, rather than losing their reason in the route's generic 503.

## Verification

All five requested questions passed through the real database using scripted plans
and the accepted coordinator/renderer, with zero paid calls. Their evidence item
counts were A: 8, B: 1, C: 5, D: 4, E: 2. Scripted checks validate integration, not
natural-language planning accuracy. Separate synthetic provider tests assert
planner invocation, two recorded scripted calls, coordinator execution, evidence,
final validation and postflight checks for all five questions. An unsupported
multi-year question remains rejected with no evidence or model call.

One live request used the exact diagnostic question. It passed with
`HUMAN_REVIEW_REQUIRED`, usable evidence and disclosed coverage: **two model calls,
two rounds, nine evidence items**, covering BANK_CASH_FLOW, COVERAGE, DOCUMENTS,
FORESTRY_SALE, INVOICES and RECONCILIATION. Bank receipts and sale-document evidence
remain separate; human review remains required. Latency was **15.262 seconds**,
with 24,103 input tokens, 152 output tokens, zero cached tokens, and an estimated
**$0.01876125** at the frozen rates. The provider selected an all-context bank view;
this successful diagnostic is not a new score or a claim of perfect answer relevance.

**874 tests passed**, including 16 new diagnostic regressions; one existing
Starlette/httpx deprecation warning remains. Alembic reported no new upgrade
operations. Ruff and format checks passed. Pre/post source fingerprints matched
across all 14 tables, including human-review rows. The existing negative-write test
still verifies database-enforced read-only access. No source data, Gmail data,
accepted core, evaluation questions/requirements, prompts or historical scores
were changed. No benchmark was rerun; no additional live diagnostic was attempted.

The versioned-file privacy scan checked 260 files with the private denylist and
found no matches. Offline integrity checks verified 1,543 protected hashes, with
only the two already-disclosed repository-hygiene redactions differing from the
historical baseline. The accepted configuration, snapshot, core and holdout hashes
still match. The pilot implementation was unchanged between the live diagnostic
and final verification.

Changed files: `tapio/pilot/service.py`, `api.py`, `presentation.py`, `page.html`,
new `diagnostics.py`, new `apps/api/tests/test_pilot_diagnostics.py`, the pilot
startup/troubleshooting documentation and this report.

Private diagnostic artifacts are under `data/interim/pilot_debug/`. Existing pilot
question records and the earlier repository-hygiene redactions were retained.
