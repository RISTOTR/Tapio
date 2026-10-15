# Phase 05 review — 2026-10-14

## Delivered

Provider-neutral typed tools and bounded orchestration work with synthetic model turns. Real Gmail OAuth and local stdio MCP research succeeded. Candidate discovery stops before human acceptance or source import.

| Area | Implementation |
| --- | --- |
| Internal tools | Eleven typed read-only tools for transactions, energy, cost/scenarios, documents, invoices, forestry and reconciliation |
| Services | `apps/api/app/services/tool_queries.py` composes existing deterministic code and safe SQL projections |
| Tool contracts | `tapio/tools/{schemas,registry,internal,errors,gmail}.py` |
| Agent | `tapio/agent/{model,loop,policy}.py`; six rounds by default, maximum eight |
| Gmail | `integrations/gmail/{auth,client,models,mime,cache,server,research,evidence}.py` |
| Tests | `test_phase05.py`, `test_phase05_database.py`, synthetic Gmail fixture and stdio fixture modules |
| Dependencies/privacy | `pyproject.toml`, `uv.lock`, `.gitignore` |
| Documentation | Agent architecture, Gmail integration, this review, architecture cross-reference |

No database models or migrations changed. Migration 0007 is unnecessary: selected email bodies use private typed EmailEvidence manifests, while PDFs retain existing Document semantics.

## Agent and deterministic boundary

Pydantic validates arguments and output, rejects extra fields, caps lists and periods, and returns DTOs rather than ORM objects. Human-reviewed transaction labels are authoritative; weak labels and raw bank identifiers are omitted. Read-only PostgreSQL transactions protect source data.

The async AgentModel protocol and CallableModel adapter isolate provider conversion. No live LLM provider was selected or tested. The model can select tools and reference their results, while trusted final templates retain exact tool-produced arithmetic and provenance. Missing evidence, errors, human tax/reconciliation review, and max-round exhaustion are explicit.

## Gmail acceptance

The actual access-token grant was checked against Google's token information endpoint and was exactly:

`https://www.googleapis.com/auth/gmail.readonly`

The first browser attempt failed before a token was created because consent was not completed. After the user's test-user setup correction, authorization succeeded. Token persistence is private, ignored, and mode 0600.

The six MCP tools are `gmail_search_messages`, `gmail_get_message`, `gmail_get_thread`, `gmail_list_attachments`, `gmail_download_attachment`, and `gmail_list_links`. Real discovery used search/get only. All six operations also passed synthetic stdio round trips, including selected PDF download and typed errors.

Real API testing exposed 404-character opaque attachment IDs. The adapter now uses a separate bounded attachment-ID type (maximum 4096 URL-safe characters); message IDs remain separately constrained. Regression tests cover long IDs and path/size rejection. No write scopes or Gmail mutation tools exist.

## Candidate research

The final narrow pass used eight sender/date/term queries, capped at five matches each and twelve unique selected bodies. It completed without errors and produced six candidate emails:

| Candidate category | Count |
| --- | ---: |
| Supplier invoice | 3 |
| Supplier contract/order confirmation | 2 |
| Supplier expiry/renewal notice | 1 |

Four PDF attachments and three potentially relevant links were identified as metadata. No PDFs were downloaded in the real pass, no links were followed, and no evidence was imported. Search caps were reached (`more_available=true`); this is not an exhaustive mailbox inventory. Earlier broad term matches included recent invoices/newsletters, so queries were refined toward 2025 supplier evidence and pre-April-2026 grid terms, with newsletters excluded.

The bounded searches produced no Elenia or export-term candidates. Forestry was not searched in this electricity-focused acceptance pass. This does not establish that those records are absent from the mailbox. Personal identifiers, subjects and bodies remain out of this versionable review; the complete private candidate list is `data/interim/gmail/candidate_report.json`, with a readable companion Markdown report.

Candidate categories and explicitly matched dates are hints, not accepted tariff facts. Invoice billing periods await PDF review. Offered renewal terms are not evidence of acceptance. No Phase 04 calculations or tariffs were changed.

## Handoff, security and integrity

Synthetic PDF handoff reused the existing document loader and parser. Tests verified message/thread/attachment linkage, download hash, Document ID/SHA, duplicate idempotency, unsupported preservation and no Document creation on failure. Existing atomic loader regression tests remain intact. Email manifests support retry after a crash between database import and manifest finalization; the two stores are not a distributed transaction.

Synthetic prompt-injection tests preserved email as tool data and rejected unavailable send/modify/delete/import/SQL/filesystem capabilities. Email cannot grant new capabilities. This is not a claim that semantic prompt injection cannot influence selection among permitted read tools. Source updates require a separate explicit human command.

Six real internal tool smoke checks passed. All fourteen source-table fingerprints match the Phase 04 baseline and remain unchanged across tool execution. Private evidence, caches, credentials and audit files are ignored; source/secret scanning found no matches in changed versionable files. OAuth values are never logged; routine audit contains only argument field names, hashed session labels, status, counts and timing.

## Verification

- Full pytest suite: **500 passed** (49.50 seconds), including 86 Phase 05 tests and the 414 existing tests.
- Ruff format: 162 files already formatted; Ruff lint: passed; Git diff whitespace check: passed.
- Dependency lock: 129 packages resolved; lock check passed.
- Alembic: no new upgrade operations detected; no new migration to cycle.
- Real MCP search: six candidates, eight queries, four PDFs and three relevant-link hints, zero errors.
- Real internal tool smoke checks: six passed; all fourteen source fingerprints match Phase 04.
- Privacy: 33 changed/versionable files scanned, 50 private files confirmed ignored, zero secret/source-identifier matches, token mode 0600.

Initial database setup errors were resolved by restarting the existing local Colima/PostgreSQL runtime. Private diagnostics are in `data/interim/agent/final_verification.json`, `privacy_verification.json`, and `completion.json`.

## Limitations and next step

The provider-neutral loop is tested with a fake provider, not a live LLM. Search is intentionally bounded and incomplete. No link fetching, public endpoint, background scanning, OCR, frontend or autonomous imports were added. Testing-app OAuth tokens may require reauthorization. The SDK major is pinned to the implemented v1 API.

Next: review `data/interim/gmail/candidate_report.md` and select individual bodies/PDFs for acceptance, starting with the contract confirmation if relevant. Phase 05 stops here as requested; do not import candidates, update tariffs or extend Phase 04 automatically.


## Subsequent human acceptance — separate Phase 04 step

On 15 October 2026, a separate explicitly authorized Phase 04 step projected the reviewed Vattenfall contract into supplier tariffs and reran the newly supported import-side comparisons. The Phase 05 acceptance results and original review gate above are unchanged. See [the subsequent Phase 04 review](energy_cost_engine_review.md#vattenfall-contract-evidence-accepted--2025-12-01-onward).
