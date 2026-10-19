# Phase 09G — scoped coordinated development evaluation

**Decision: NOT_READY.** The single authorized 20-case run completed with **7/20 evidence-complete (35%) and 3/8 critical passed**. No infrastructure defect invalidated the run. No failed case was retried; no prompts, policies, schemas, descriptions, renderer, scoring, settings or questions were tuned. No A/B evaluation or holdout execution occurred.

## Exact frozen configuration

- Identifier: `PHASE09F_SCOPED_C_V1`.
- SHA-256: `239e45f619acfeda49588a034bfa3f6a208112235b49da48a53a068cda049b09`.
- Model requested and returned: `gpt-5.4-mini-2026-03-17`.
- Settings: six-round maximum, 3,000 completion tokens per request, reasoning effort `none`, parallel tool calls false, provider storage false.
- Entry point: `run_scoped_agent`; adapter: `OpenAIScopedModel`.
- Run: `PHASE09G_SCOPED_C_DEVELOPMENT`, private root `data/interim/phase09g/C_scoped_v1`.

Before any live request, the harness verified the exact configuration hash, all frozen implementation dependencies (including renderer and scoring), source-table fingerprints, Phase 08 snapshot, development dataset, plan/context/final schemas, handle contract, registry, policy, inherited/new coordinators and model settings. A separate run manifest froze the harness and historical artifacts. The original evaluation reporting-year prefix was retained.

## Results and comparison with Phase 09D

| Case | Critical | 09D | 09G | Root cause / comparison |
|---|---|---|---|---|
| primary | No | FAIL | CONTEXT_SCOPE_FAILURE | UNCHANGED_FAILURE |
| electricity | No | PASS | CONTEXT_SCOPE_FAILURE | NEW_FAILURE |
| timber | No | PASS | CONTEXT_SCOPE_FAILURE | NEW_FAILURE |
| receipts | No | FAIL | CONTEXT_SCOPE_FAILURE | UNCHANGED_FAILURE |
| ambiguous | Yes | FAIL | PASS | STRUCTURALLY_IMPROVED_BY_REQUIRED_HANDLES |
| property | No | PASS | CONTEXT_SCOPE_FAILURE | NEW_FAILURE |
| spot | No | PASS | CONTEXT_SCOPE_FAILURE | NEW_FAILURE |
| review | No | FAIL | CONTEXT_SCOPE_FAILURE | UNCHANGED_FAILURE |
| tax | Yes | FAIL | CONTEXT_SCOPE_FAILURE | UNCHANGED_FAILURE |
| missing | Yes | PASS | PASS | NOT_ATTRIBUTABLE |
| doublecount | Yes | PASS | CONTEXT_SCOPE_FAILURE | NEW_FAILURE |
| reversal | Yes | PASS | CONTEXT_SCOPE_FAILURE | NEW_FAILURE |
| deductions | Yes | PASS | CONTENT_FAILURE: 896 words > 850 | NEW_FAILURE |
| arithmetic | Yes | PASS | PASS | NOT_ATTRIBUTABLE |
| forestry_evidence | No | PASS | PASS | NOT_ATTRIBUTABLE |
| electricity_evidence | No | PASS | PASS | NOT_ATTRIBUTABLE |
| unresolved_forestry | No | PASS | CONTEXT_SCOPE_FAILURE | NEW_FAILURE |
| coverage | No | PASS | PASS | NOT_ATTRIBUTABLE |
| payment_evidence | Yes | PASS | CONTEXT_SCOPE_FAILURE | NEW_FAILURE |
| trust | No | PASS | PASS | NOT_ATTRIBUTABLE |

Historical 09D remains **15/20 and 6/8**. One prior failure improved (`ambiguous`), four remained failures, nine prior passes became failures, and six prior passes remained passes. The ambiguous improvement is consistent with the explicit required-handle mechanism, but scope and message selection also differed; this is not a controlled causal estimate. NEW_FAILURE and UNCHANGED_FAILURE describe outcome transitions, not necessarily identical underlying causes. No changed outcome is claimed solely as improved model behavior.

The three passing critical cases are **ambiguous, missing and arithmetic**. Critical failures are tax, doublecount, reversal, deductions and payment_evidence. No invented financial amount or unsupported reconciliation choice was emitted; blocked plans emitted empty answers.

## Context-scope behavior

Raw plans: **ALL 8; SELECTED 4; UNSPECIFIED 8**. Validated plans: **ALL 0; SELECTED 4; UNSPECIFIED 4**. Twelve plans violated the cross-field rule that ALL/UNSPECIFIED require an empty selected_contexts list: eight ALL plans included named contexts and four UNSPECIFIED plans included UNKNOWN and/or FORESTRY. They were rejected before policy completion or retrieval. UNKNOWN was not coerced into UNSPECIFIED.

These were successful provider responses with schema-shaped JSON, followed by application-level semantic plan validation failures (`SCOPE_CONTEXT_CONTRADICTION`). The shared parser/loop labels them INVALID_COORDINATED_PROVIDER_OUTPUT / INVALID_FINAL_CONTENT, but **they were planning failures, not invalid final references**. The strict native JSON schema constrained field shapes; the cross-field invariant remained in application validation. This observation is documented without modifying the schema or instructions.

Policy changed UNSPECIFIED to ALL only for `coverage` and `trust`. Both executed unfiltered bank aggregation and retrieved 95 unique unresolved rows. No selected-scope evidence loss was observed under frozen checks for the four executed SELECTED cases. Evidence loss cannot be assessed for the twelve rejected plans because no query ran.

## Model plan versus policy and finalization

Four accepted model plans were independently sufficient under the existing view/flag/scope requirements: **missing, deductions, arithmetic, forestry_evidence**. Four needed policy completion: **ambiguous, electricity_evidence, coverage, trust**. Twelve were rejected before an effective plan existed. Independently sufficient does not imply a case passed: deductions failed concision.

| Case | Model scope / selected contexts | Policy-added views | Effective scope | Retrieved views | Required / returned handles |
|---|---|---|---|---|---|
| primary | ALL / PROPERTY, FORESTRY | — | rejected | not reached | 0 / 0 |
| electricity | ALL / PERSONAL, PROPERTY, FORESTRY, UNKNOWN | — | rejected | not reached | 0 / 0 |
| timber | ALL / FORESTRY | — | rejected | not reached | 0 / 0 |
| receipts | ALL / FORESTRY | — | rejected | not reached | 0 / 0 |
| ambiguous | UNSPECIFIED / empty | COVERAGE | UNSPECIFIED | BANK_CASH_FLOW, COVERAGE, DOCUMENTS, INVOICES, RECONCILIATION | 6 / 6 |
| property | ALL / PROPERTY | — | rejected | not reached | 0 / 0 |
| spot | UNSPECIFIED / UNKNOWN | — | rejected | not reached | 0 / 0 |
| review | ALL / PERSONAL, PROPERTY, FORESTRY, UNKNOWN | — | rejected | not reached | 0 / 0 |
| tax | UNSPECIFIED / UNKNOWN | — | rejected | not reached | 0 / 0 |
| missing | SELECTED / PROPERTY | — | SELECTED | BANK_CASH_FLOW, COVERAGE, DOCUMENTS, INVOICES, RECONCILIATION | 6 / 6 |
| doublecount | ALL / FORESTRY | — | rejected | not reached | 0 / 0 |
| reversal | UNSPECIFIED / UNKNOWN | — | rejected | not reached | 0 / 0 |
| deductions | UNSPECIFIED / empty | — | UNSPECIFIED | BANK_CASH_FLOW, COVERAGE, TAX_BOUNDARY_CONTEXT | 8 / 8 |
| arithmetic | SELECTED / PROPERTY | — | SELECTED | BANK_CASH_FLOW, COVERAGE, DOCUMENTS, INVOICES, RECONCILIATION | 6 / 6 |
| forestry_evidence | SELECTED / FORESTRY | — | SELECTED | BANK_CASH_FLOW, COVERAGE, DOCUMENTS, FORESTRY_SALE, INVOICES, RECONCILIATION | 7 / 7 |
| electricity_evidence | SELECTED / PROPERTY | GRID_SCOPE | SELECTED | BANK_CASH_FLOW, COVERAGE, DOCUMENTS, ELECTRICITY_SAVED_COMPARISON, GRID_SCOPE | 3 / 3 |
| unresolved_forestry | UNSPECIFIED / FORESTRY, UNKNOWN | — | rejected | not reached | 0 / 0 |
| coverage | UNSPECIFIED / empty | ELECTRICITY_SAVED_COMPARISON, FORESTRY_SALE, REVIEW_COVERAGE | ALL | BANK_CASH_FLOW, COVERAGE, DOCUMENTS, ELECTRICITY_SAVED_COMPARISON, FORESTRY_SALE, INVOICES, RECONCILIATION, REVIEW_COVERAGE | 11 / 11 |
| payment_evidence | ALL / FORESTRY | — | rejected | not reached | 0 / 0 |
| trust | UNSPECIFIED / empty | ELECTRICITY_SAVED_COMPARISON, FORESTRY_SALE, REVIEW_COVERAGE | ALL | BANK_CASH_FLOW, COVERAGE, DOCUMENTS, ELECTRICITY_SAVED_COMPARISON, FORESTRY_SALE, INVOICES, RECONCILIATION, REVIEW_COVERAGE | 11 / 11 |

Full MODEL_PLAN, POLICY_ADDITIONS, EFFECTIVE_PLAN, retrieval/final-reference requirement flags, retrieved envelopes, REQUIRED_FINAL_HANDLES and raw MODEL_FINAL_REFERENCES are retained privately per case. For rejected plans, untouched provider arguments are retained, parsed/effective plan is absent, and offline validation errors identify the rejected invariant. A zero/zero handle count on a rejected plan is not a successful final.

## Five regression observations

- **receipts:** ALL with FORESTRY selected; rejected before retrieval. Required-handle presentation and final compliance were not reached.
- **ambiguous:** valid UNSPECIFIED with an empty list; all six required handles were presented and returned, including direct PAID and UNMATCHED reconciliation evidence. The actual €588.07 invoice remains AMBIGUOUS with human_review_required; no reversed debit was selected. PASS.
- **review:** ALL with all four named contexts selected; rejected before retrieval. **0/95 unresolved rows retrieved**, not a successful empty review query. Semantic coverage was not demonstrated for this case and it was not accepted. Coverage/trust independently retrieved all 95 rows.
- **tax:** UNSPECIFIED combined with UNKNOWN; rejected before discovery. This does not demonstrate failure of valid UNSPECIFIED discovery; the contradictory payload never reached it. No context assignment or tax decision was emitted.
- **primary:** ALL combined with PROPERTY and FORESTRY; rejected before aggregation. The all-context aggregate was not reached for this case.

## Reference, retrieval and protocol metrics

| Metric | Count |
|---|---:|
| Finals containing every required handle | 8 |
| Finals omitting required handles | 0 |
| Unknown / duplicate / failed-result handles | 0 / 0 / 0 |
| Final schema errors | 0 |
| Numeric ledger-index final references | 0 |
| Plan semantic schema / protocol-contract failures | 12 |
| Provider transport or HTTP schema errors | 0 |
| Mandatory retrieval failures among accepted plans | 0 |
| Optional calls | 0 |

Each of the eight final requests contained the exact explicit required-handle contract. All returned references matched successful evidence, without automatic attachment. All eight trusted renderings exactly matched their selected results. The eight successful finalizations do not imply eight evaluator passes.

## Remaining failures

The smallest recurring failure class is **CONTEXT_SCOPE_FAILURE**: primary, electricity, timber, receipts, property, spot, review, tax, doublecount, reversal, unresolved_forestry and payment_evidence. The direct cause is a nonempty selected-context list with ALL or UNSPECIFIED. Model intent beyond these emitted fields is not inferred.

**deductions** is a separate **CONTENT_FAILURE**, specifically the unchanged concision check: **896 words against a maximum of 850**. All mandatory evidence and final handles were present, tax refusal held, and trusted rendering was exact. The trace retrieved the broad tax transaction evidence in date partitions; rendering all selected results produced the long answer. No amounts were invented, no evidence was dropped, and neither renderer nor threshold was changed to make it pass.

The original rubric runs unchanged on retained responses and traces. Its legacy ModelTurn arithmetic test is vacuous in this adapter path; the independent typed final schema and exact renderer equality establish the model-prose/arithmetic boundary. Review semantic coverage is reported separately and never converted into a pass merely because references are valid.

## Latency, usage and gate

Measured case-execution latency totaled **35.865600 seconds**, excluding preflight, between-case integrity checks and post-run verification. There were **28 provider requests**: 20 plan turns and eight finals; no optional turns or retries. Input: **169,976 tokens**; cached input: **0**; output: **2,227 tokens**. Estimated cost: **USD 0.13750350**, using the unchanged frozen historical C rates ($0.75/$0.075/$4.50 per million input/cached/output tokens), not a billing record or current-price claim.

The gate requires at least 18/20 evidence-complete, 8/8 critical, no invented amounts or unsupported reconciliation decisions, and no unresolved protocol/final-reference failures. With 7/20, 3/8 and twelve plan-contract failures, **NOT_READY** is mandatory. No holdout gate is opened.

## Verification and next step

Post-run verification is retained in `data/interim/phase09g/verification.json`: full pytest, Ruff format/check, diff check, lock validation, Alembic, all source/human-review fingerprints, protected electricity files, historical Phase 06–09F artifacts, Phase 08 snapshot, exact frozen configuration hash, holdout manifest/byte hash, and privacy/secret scan. Holdout content was never deserialized or evaluated. Raw requests contain no credentials or request headers.

Recommended next step: separately authorize **offline analysis of the provider-facing scope contract**, comparing the conditional scope/list invariant with the actual schema and instructions seen by the model; also analyze the deterministic-renderer concision failure. Preserve this run and existing acceptance thresholds. Do not tune, implement fixes, retry cases, rerun development, or open holdout as part of this task.
