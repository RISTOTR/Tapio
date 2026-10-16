# Phase 07 — evidence completeness and supervised acceptance

## Decision

**NOT_READY** for a human-supervised user-facing pilot. The acceptance evaluation is complete; human transaction review is still pending. No labels were inferred or imported to improve scores. No pilot design or frontend was produced because the acceptance gate failed.

The frozen Phase 06 nano result remains **5/14**, with its original traces and documentation unchanged. The new 20-case development evaluation produced **5/20 for A**, **1/20 for B**, and **3/20 for C**. All configurations fail critical cases. The eight-question holdout remains sealed and was **not run**, rather than being counted as zero or claimed to pass.

## Bank coverage audit

The audit used imported bank metadata, the original bank exports in the Downloads location documented by the existing ingestion guide, and the project's existing file inventory. No Gmail access was used.

| Source export | Source rows | Booking dates | Import finding |
| --- | ---: | --- | --- |
| `tapahtumat20250101-20251231.csv` | 225 | 2025-01-02–2025-12-29 | Prior-year source |
| `tapahtumat20260101-20261005.csv` | 169 | 2026-01-02–2026-10-05 | Initial 2026 source |
| `tapahtumat20260101-20261007.csv` | 170 | 2026-01-02–2026-10-06 | 169 overlapping source identities; one additional transaction |

All three local file hashes match their imported SHA-256 identities. Duplicate import attempts are distinguished from new source files. Exact fingerprints, import-run IDs, claimed intervals, observed dates and overlap counts are in private `data/interim/phase07/bank_coverage.json`.

The earliest/latest **filename-claimed 2026 interval** is January 1–October 7. The filename does not establish file-generation time, an official statement boundary, completeness within that interval, or year completeness. October 6 is the latest observed booking date, **not a verified statement boundary**. No later matching bank export was found in the inspected locations, and no later imported bank source was present. There are no established interior gaps, but absence of established gaps is not evidence of continuous coverage.

Status is **PARTIAL_YEAR / UNKNOWN_COVERAGE**. `COMPLETE_FOR_SOURCE_INTERVAL` is not assigned without statement-level evidence. Missing transactions, zero-activity months and missing-year totals are not invented.

## Human review status

2026 still contains **170 transactions: 47 human-reviewed and 123 unresolved**. The private queue is available as `data/interim/phase07/review_queue.csv` and `.json`:

| Priority | Rows | Purpose |
| --- | ---: | --- |
| P1 | 25 | Large cash flows (absolute value at least EUR 500), incoming amounts, transfer/energy suggestions, domain suggestions, invoice/reversal links |
| P2 | 3 | Possible domain relevance requiring receipts or context |
| P3 | 95 | Ordinary personal or lower-materiality items; review later |

Each row includes date, amount, direction, normalized counterparty, ultimate recipient, sanitized message/reference, weak suggestions, linked invoice/document IDs and status, recurrence dates/count, reversal candidates, priority and reasons. Repeated counterparties are evidence of recurrence, not proof of a subscription. Irrelevant bank account, BIC and archive identifiers are redacted. Structured lists are retained in JSON and serialized in CSV. This evidence queue is not an automatically importable label-decision file.

Human decision fields remain blank. Existing policy is included: broad personal classifications are acceptable; DNA prepaid is OTHER/PERSONAL; fuel remains FUEL/PERSONAL unless explicitly decided otherwise; K-Rauta/Tokmanni require receipts for domain attribution. Weak suggestions never become authoritative through prioritization. No artificial class balancing or tax determination is performed.

The user was asked to review P1/P2. No decisions were received during this evaluation, so authoritative coverage has **not improved yet**. All model comparisons use the same unchanged source data. A later human-approved label import requires a new evaluation-data snapshot.

## Frozen datasets and acceptance rules

Versionable definitions are under `tapio/agent/acceptance/datasets/`. The first 14 development questions, expected tools and message keys are copied unchanged from Phase 06; a regression test verifies equality. Six additions cover forestry evidence, electricity evidence, unresolved forestry relevance, source coverage, the ambiguous payment and trust limitations.

The eight holdout questions were authored and hash-sealed before orchestration implementation, then not inspected or changed while developing the rules. Tests check their bytes against the manifest without loading their expected plans. No holdout question or expected tool plan enters model prompts. This is a reserved internal holdout, not an independently authored external benchmark.

Thresholds were fixed before live evaluation:

- 100% on critical ambiguity, double-counting, tax, missing-data, arithmetic and payment-evidence cases;
- at least 90% evidence completeness on development;
- at least 85% on untouched holdout;
- no invented financial amounts or unsupported reconciliation decisions in accepted answers.

The Phase 06 nine-part rubric remains intact. Phase 07 adds general evidence-view completeness, required context, supplier-plus-grid scope and direct reconciliation checks. A material omitted view fails even if the numbers present are correct. These additional requirements apply equally to A/B/C; the old Phase 06 score is not rewritten under them.

Per-case traces record calls, arguments/results, errors, model turns, rounds, selected evidence, missing evidence, additional/repeated calls, ambiguity/tax/coverage checks, deterministic-render equality, latency, tokens and estimated cost. Exact duplicate calls are identified as unnecessary; other additional calls are recorded rather than automatically assumed wasteful. Factual correctness checks are structural and source-based, not an independent expert audit of every source document.

## Evidence planning and deterministic requirements

The existing 13 internal tools remain unchanged. All three configurations expose the same 10 read-only source tools used by the Phase 06 evaluation; the three electricity calculation/query tools and Gmail remain excluded. A Phase 07 registry wrapper adds the audited bank-source/review coverage to the existing financial-summary result. This metadata is identical across configurations.

C adds one **control-only** `submit_evidence_plan` operation. Its typed schema permits only enumerated question type, evidence views, contexts and coverage/tax flags; arithmetic, amounts and freeform factual prose are rejected. The planning turn consumes one of the unchanged six rounds, leaving at most four evidence calls and a finish. Provider/model facts are not placed in system prompts.

General domain rules require bank cash flow and coverage for costs; invoice/reconciliation and separate sale views for forestry summaries; supplier and grid coverage plus the saved comparison for electricity questions; unresolved-review retrieval for review questions; direct reconciliation for ambiguous-payment questions; and evidence plus the mandatory tax boundary for tax questions. These are semantic-class rules, not question-specific answer or tool-call lookup tables.

The model still chooses source calls. Code validates selected results against the requirements and marks C as `EVIDENCE_INCOMPLETE` when evidence is missing. It does not silently retrieve omitted facts, increase the round budget, approve labels, resolve a refund, or substitute a missing amount. The trusted renderer remains the sole source of financial prose.

Evidence-state labels derive from results: SUPPORTED, PARTIAL_COVERAGE, HUMAN_REVIEW_REQUIRED, AMBIGUOUS and UNSUPPORTED. Empty or rejected answers cannot be SUPPORTED. A post-run context/state validation replay tightened these checks without model calls, changed no acceptance outcome, and preserved the original raw traces. No numeric confidence percentage is generated.

## Models and measured results

| Configuration | Exact model | Evidence complete | Original rubric, first 14 | Total case latency | Estimated USD |
| --- | --- | ---: | ---: | ---: | ---: |
| A: nano, existing orchestration | `gpt-5.4-nano-2026-03-17` | 5/20 (25%) | 5/14 | 55.87 s | 0.05256949 |
| B: stronger, existing orchestration | `gpt-5.4-mini-2026-03-17` | 1/20 (5%) | 1/14 | 54.58 s | 0.12286635 |
| C: stronger + planning/gates | `gpt-5.4-mini-2026-03-17` | 3/20 (15%) | 3/14 | 104.74 s | 0.35920845 |

These are single runs, not statistical estimates of general model quality. The API, source tools, six-round bound, native single-call protocol and renderer were kept the same. No fallback model was used. `reasoning_effort` stayed `none`; the comparison is specific to this configuration and adapter.

Input/cached-input/output tokens were A: 322,376/79,872/1,977; B: 222,725/77,568/1,818; C: 552,729/107,776/3,869. Cached tokens are a subset of input. Cost estimates use USD per million input/cached/output tokens: nano 0.20/0.02/1.25; mini 0.75/0.075/4.50. API access established availability for this account. Pricing and model documentation: [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [GPT-5.4 nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano). These are estimated token costs, not invoices.

### Failure analysis

B had 15 final/schema rejections; C had 9 under that status, plus incomplete-evidence rejections. One bounded replay of B's primary final turn demonstrated the contract mismatch: native `references: [0, 1, 2, 3]` was rejected because references must be objects such as `{"call_index": 0}`. This diagnosis explains that replay, not necessarily every schema rejection. Rejected turns were not normalized into benchmark passes. B's primary run retrieved all four required source tools but failed to produce a valid final turn.

C successfully completed the primary overview, electricity spending and property-cost cases. It still missed required evidence in other cases, selected general documents instead of invoice/reconciliation evidence, and suffered final-reference failures. Planning did not demonstrate sufficient acceptance performance despite a modest improvement over B.

A failed six of the eight critical cases: ambiguous payments, tax evidence, double counting, reversal, deductions and payment evidence. B and C failed all eight critical cases. These are acceptance failures, often caused by omitted evidence or response rejection; they are not evidence that source data was changed or an incorrect tax decision was executed.

No unsupported financial amount or reconciliation decision reached an accepted deterministic answer. This is not a claim that all rejected native model outputs were independently fact-checked. The EUR 588.07 ambiguity and bank/document/sale separation remain unchanged.

### Infrastructure incident

On the resumed session, Colima/PostgreSQL was stopped. Initial A/B/C attempts consequently returned database tool errors; these runs are preserved under `data/interim/phase07/invalid_database_unavailable/` and excluded from model-comparison scores. The runtime/database were restarted, source hashes verified, and unchanged configurations rerun. A read-only preflight now stops before live calls if required tools fail.

Invalid runs cost an estimated USD 0.19761421; the bounded final-contract diagnostic cost USD 0.00184095. Total estimated live usage including valid runs, invalid runs and that diagnostic was **USD 0.73409945**. Timings in the comparison table are sums of case latencies, not elapsed wall time for concurrent configurations.

## Verification and next step

**632 tests pass**: all 598 existing tests plus 34 Phase 07 tests. Ruff formatting/checks and `git diff --check` pass. Dependency-lock validation resolves the same 129 packages; Alembic reports no upgrade operations. No migrations or dependencies were added. Fingerprint checks preserve all 14 source tables, 66 protected electricity files and 36 frozen Phase 06 files. Two independent read-only audit builds produce identical coverage and review queues, with unchanged evaluation-facing metadata. Private traces and the human-review queue remain ignored and owner-readable; API-key and known source-identifier scans find no matches in versionable changes.

**Exact next step:** review the 25 P1 and three P2 queue entries without importing inferred labels; obtain statement-level coverage evidence if available. In a separately scoped follow-up, repair and test the native final-reference contract, then rerun the same frozen development requirements with source/data snapshots recorded. Do not inspect the reserved holdout until development and every critical gate pass. Only after untouched holdout acceptance should a human-supervised pilot interaction be designed. Do not add a frontend, retrieval system, new ML work or background autonomy to mask these failures.

Phase 07 stops here. Human decisions remain outstanding; no automatic source mutation is authorized by the queue or evaluation.
