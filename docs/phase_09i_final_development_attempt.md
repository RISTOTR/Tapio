# Phase 09I — final development attempt

**DEVELOPMENT_GATE_PASSED**. One development-only C run: **20/20 evidence-complete; 8/8 critical**. No A/B, holdout inspection, retries or tuning.

## Frozen configuration

`PHASE09H_EXCLUSIVE_C_V1`; SHA-256 `3b3e0d809c205ca37f7c39414aca407fe01a58a15935d1a3db93d2ae2d97988b`.

Exact requested and returned model: `gpt-5.4-mini-2026-03-17`. Settings: {"max_completion_tokens": 3000, "max_rounds": 6, "parallel_tool_calls": false, "reasoning_effort": "none", "store": false}.

Phase 09H had verified implementation hashes but no standalone live configuration. This task created its first immutable configuration from those verified hashes before any provider call; it did not replace or regenerate an existing freeze. All source fingerprints, snapshot/development hashes, schemas, registry, policy, coordinators, final schema, renderer, evaluator/scoring, model/settings and sealed holdout byte digest were verified before the run.

The evaluator and scoring source files are unchanged. The existing deterministic-render equality criterion is bound to the frozen H renderer for this version, as specified in the H report. An offline retained deductions replay verified that binding before the live run. The 850-word threshold and all evidence requirements remain unchanged.

## Case results

| Case | Group | Pass | Plan quality | Failure | 09D / 09G |
|---|---|---|---|---|---|
| primary | READY | PASS | POLICY_COMPLETION_REQUIRED | — | FAIL / FAIL |
| electricity | MODEL_DEPENDENT | PASS | POLICY_COMPLETION_REQUIRED | — | PASS / FAIL |
| timber | MODEL_DEPENDENT | PASS | POLICY_COMPLETION_REQUIRED | — | PASS / FAIL |
| receipts | MODEL_DEPENDENT | PASS | POLICY_COMPLETION_REQUIRED | — | FAIL / FAIL |
| ambiguous | READY | PASS | POLICY_COMPLETION_REQUIRED | — | FAIL / PASS |
| property | MODEL_DEPENDENT | PASS | MODEL_PLAN_SUFFICIENT | — | PASS / FAIL |
| spot | MODEL_DEPENDENT | PASS | MODEL_PLAN_SUFFICIENT | — | PASS / FAIL |
| review | READY | PASS | POLICY_COMPLETION_REQUIRED | — | FAIL / FAIL |
| tax | READY | PASS | MODEL_PLAN_SUFFICIENT | — | FAIL / FAIL |
| missing | READY | PASS | MODEL_PLAN_SUFFICIENT | — | PASS / PASS |
| doublecount | MODEL_DEPENDENT | PASS | POLICY_COMPLETION_REQUIRED | — | PASS / FAIL |
| reversal | MODEL_DEPENDENT | PASS | POLICY_COMPLETION_REQUIRED | — | PASS / FAIL |
| deductions | READY | PASS | MODEL_PLAN_SUFFICIENT | — | PASS / FAIL |
| arithmetic | READY | PASS | MODEL_PLAN_SUFFICIENT | — | PASS / PASS |
| forestry_evidence | READY | PASS | POLICY_COMPLETION_REQUIRED | — | PASS / PASS |
| electricity_evidence | READY | PASS | MODEL_PLAN_SUFFICIENT | — | PASS / PASS |
| unresolved_forestry | MODEL_DEPENDENT | PASS | MODEL_PLAN_SUFFICIENT | — | PASS / FAIL |
| coverage | READY | PASS | POLICY_COMPLETION_REQUIRED | — | PASS / PASS |
| payment_evidence | MODEL_DEPENDENT | PASS | MODEL_PLAN_SUFFICIENT | — | PASS / FAIL |
| trust | READY | PASS | POLICY_COMPLETION_REQUIRED | — | PASS / PASS |

The nine MODEL_DEPENDENT rows are the nine requested focus cases. NEW_FAILURE among the eleven structurally ready cases: none.

## Context and final handles

Model context counts: {'SELECTED': 5, 'UNSPECIFIED': 6, 'ALL': 9}. Effective context counts: {'ALL': 11, 'UNSPECIFIED': 5, 'SELECTED': 4}.

| Metric | Count |
|---|---:|
| finals_all_required_handles | 20 |
| finals_missing_handles | 0 |
| missing_handles | 0 |
| unknown_handles | 0 |
| duplicate_handles | 0 |
| failed_result_handles | 0 |
| schema_invalid_finals | 0 |
| numeric_index_regressions | 0 |
| invalid_context_plans | 0 |
| rejected_before_retrieval | 0 |
| context_selection_failures | 0 |
| context_choice_evidence_loss_cases | 0 |
| protocol_failures | 0 |
| optional_calls | 1 |
| invented_financial_amounts | 0 |
| unsupported_reconciliation_decisions | 0 |

| Case | Model selection | Effective selection | Required / returned handles | Words | Review rows |
|---|---|---|---:|---:|---:|
| primary | {"mode": "SELECTED", "contexts": ["PROPERTY", "FORESTRY"]} | {"mode": "ALL"} | 11 / 11 | 845 | 95 |
| electricity | {"mode": "UNSPECIFIED"} | {"mode": "UNSPECIFIED"} | 7 / 7 | 387 | 0 |
| timber | {"mode": "ALL"} | {"mode": "ALL"} | 7 / 7 | 456 | 0 |
| receipts | {"mode": "ALL"} | {"mode": "ALL"} | 7 / 7 | 456 | 0 |
| ambiguous | {"mode": "UNSPECIFIED"} | {"mode": "UNSPECIFIED"} | 6 / 6 | 436 | 0 |
| property | {"mode": "SELECTED", "contexts": ["PROPERTY"]} | {"contexts": ["PROPERTY"], "mode": "SELECTED"} | 6 / 6 | 354 | 0 |
| spot | {"mode": "UNSPECIFIED"} | {"mode": "UNSPECIFIED"} | 1 / 1 | 87 | 0 |
| review | {"mode": "UNSPECIFIED"} | {"mode": "ALL"} | 8 / 8 | 770 | 95 |
| tax | {"mode": "UNSPECIFIED"} | {"mode": "UNSPECIFIED"} | 12 / 12 | 846 | 0 |
| missing | {"mode": "SELECTED", "contexts": ["PROPERTY"]} | {"contexts": ["PROPERTY"], "mode": "SELECTED"} | 6 / 6 | 354 | 0 |
| doublecount | {"mode": "ALL"} | {"mode": "ALL"} | 6 / 6 | 449 | 0 |
| reversal | {"mode": "UNSPECIFIED"} | {"mode": "UNSPECIFIED"} | 5 / 5 | 429 | 0 |
| deductions | {"mode": "ALL"} | {"mode": "ALL"} | 13 / 13 | 845 | 0 |
| arithmetic | {"mode": "SELECTED", "contexts": ["PROPERTY"]} | {"contexts": ["PROPERTY"], "mode": "SELECTED"} | 6 / 6 | 355 | 0 |
| forestry_evidence | {"mode": "ALL"} | {"mode": "ALL"} | 7 / 7 | 456 | 0 |
| electricity_evidence | {"mode": "SELECTED", "contexts": ["PROPERTY"]} | {"contexts": ["PROPERTY"], "mode": "SELECTED"} | 4 / 4 | 167 | 0 |
| unresolved_forestry | {"mode": "ALL"} | {"mode": "ALL"} | 9 / 9 | 789 | 95 |
| coverage | {"mode": "ALL"} | {"mode": "ALL"} | 11 / 11 | 845 | 95 |
| payment_evidence | {"mode": "ALL"} | {"mode": "ALL"} | 7 / 7 | 455 | 0 |
| trust | {"mode": "ALL"} | {"mode": "ALL"} | 11 / 11 | 845 | 95 |

Full model plans, policy additions, effective plans, retrieved evidence, required/returned handles, final messages, raw provider responses and unchanged evaluator results are private in `data/interim/phase09i/`. No references were attached automatically. Exact renderer equality and typed final handles establish that no model-authored financial amount or reconciliation choice entered the answer; this is not an independent financial correctness oracle.

## Failure details and historical comparison

No remaining failed cases. On the exact newly selected evidence, the historical renderer would produce 1,125 words for tax and 1,132 for deductions; the frozen bounded renderer produced 846 and 845 respectively, retaining the complete structured evidence. No context-choice evidence loss was observed under the unchanged frozen checks. General review retrieved all 95 unique unresolved rows; primary, unresolved_forestry, coverage and trust also retained all 95. Merchant-specific tax discovery used UNSPECIFIED and retained the human-reviewed FORESTRY label without converting it into deductibility.


Historical 09D remains **15/20, 6/8**. Historical 09G remains **7/20, 3/8**. New result: **20/20, 8/8**. Historical scores were not rewritten.

| Case | Change from 09D | Change from 09G |
|---|---|---|
| primary | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| electricity | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| timber | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| receipts | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| ambiguous | NOT_ATTRIBUTABLE | NOT_ATTRIBUTABLE |
| property | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| spot | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| review | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| tax | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| missing | NOT_ATTRIBUTABLE | NOT_ATTRIBUTABLE |
| doublecount | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| reversal | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| deductions | NOT_ATTRIBUTABLE | IMPROVED_BY_CONCISION_REPAIR |
| arithmetic | NOT_ATTRIBUTABLE | NOT_ATTRIBUTABLE |
| forestry_evidence | NOT_ATTRIBUTABLE | NOT_ATTRIBUTABLE |
| electricity_evidence | NOT_ATTRIBUTABLE | NOT_ATTRIBUTABLE |
| unresolved_forestry | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| coverage | NOT_ATTRIBUTABLE | NOT_ATTRIBUTABLE |
| payment_evidence | NOT_ATTRIBUTABLE | IMPROVED_BY_EXCLUSIVE_CONTEXT_CONTRACT |
| trust | NOT_ATTRIBUTABLE | NOT_ATTRIBUTABLE |

Outcome comparisons are not controlled causal estimates; exclusive-contract improvements may also involve changed semantic choices.

## Latency, tokens and cost

Total case-execution latency: **59.054386 seconds** (excludes preflight, between-case integrity checks and verification). Provider requests: **41**. Tokens: input **447,426**, cached input **2,560**, output **3,019**. Estimated cost: **USD 0.34742700**, using frozen historical C rates of $0.75/$0.075/$4.50 per million input/cached/output tokens; not a current-price claim or bill.

## Verification and next step

**806 tests passed** (73.61 seconds). Ruff check/format, git diff whitespace check, dependency lock (129 packages), and Alembic check passed. All 14 source/human-review table fingerprints, 1,234 historical/code hashes, 66 protected electricity artifacts, the snapshot/configuration, and sealed holdout manifest/byte hashes are unchanged. All 41 provider requests and responses used the exact frozen model/settings. The private-artifact credential scan found zero matches.

Final verification is recorded in `data/interim/phase09i/verification.json` and `privacy_verification.json`: full pytest, Ruff format/check, diff check, dependency lock, Alembic, source/human-review fingerprints, protected electricity/historical artifacts, data snapshot/configuration hashes and holdout manifest/byte hash. Holdout content is never deserialized.

The development gate passed. Recommend a separately authorized, one-time sealed holdout evaluation using this unchanged configuration. Do not infer pilot readiness from development alone.
