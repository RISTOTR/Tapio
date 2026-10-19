# Phase 09D coordinated development evaluation

**Decision: NOT_READY.** The one authorized development run completed: **15/20 (75%) evidence-complete; 6/8 critical passed**. Historical Phase 08 C remains 9/20 and 4/8. No A/B run, retry, holdout content inspection, tuning, implementation repair, or historical score rewrite occurred.

Run identifier: `PHASE09D_C_COORDINATED`, private directory `data/interim/phase09d/C_coordinated_v1`. Exact requested and returned model: `gpt-5.4-mini-2026-03-17`. Same settings as Phase 09C: six model decisions maximum, 3,000 completion tokens per request, reasoning effort `none`, parallel calls false, provider storage false. All cases used the new coordinated entry point and the original questions plus the unchanged evaluation reporting-year prefix.

## Frozen configuration

The private `frozen.json` was written before the first live request. It contains all 14 table fingerprints, human-review counts, exact dataset/manifest, schema, registry, policy, adapter and runner hashes, model settings and protected historical artifacts. The reporting snapshot has 170 transactions in 2026, 75 human-reviewed and 95 unresolved; the 2026 bank period remains partial.

| Item | SHA-256 |
|---|---|
| snapshot_sha256 | `ee55cdd801da98d66acd09dd754222457cdc464f38fabe0471b186456e0b5221` |
| development_hash | `0c9f9a3fb7b4517ee5292dbd8a8710e31d3ba41c8961fe09f809e22012a58fb9` |
| holdout_hash | `9a6aaae0215415301c67ad374ba622d3364317dee359e0860ba46de7dcd8e404` |
| manifest_hash | `855fa4b3672bec47a42dc499de96c3b4e27d78222833b977debda8a532b52fcd` |
| evidence_policy_hash | `e574d7fe37f1c26ea4384ee5dc2b2cc8cf15be7278476b4022439d33bd78ff97` |
| base_policy_hash | `f06bc69c5bba75553ef8351b756dea93df23f7abac19e390fd1e1266b502c1b5` |
| coordinated_registry_hash | `bbc0f10e030e477befecc0b0fd841b16c306823f43faa2300a3b8a88ff818cff` |
| adapter_hash | `450fea557593cf448c04a5ab8a90b1fc3d1bb33fb5586fd4287185b4bdcd82ff` |
| final_schema_hash | `713487aa3843969003039498946e2cbce0317baa4789f27c6c36fd00c58dd509` |
| runner_hash | `45d1c6cf23cda02e2ebd6c150be414213f31090bd3d0716f632cfc52fdba9e0d` |

Holdout verification hashed raw bytes only; its JSON contents were never decoded or exposed. The registry hash covers actual versioned specifications; the policy implementation hash also covers the coordinator and semantic schema.

## Twenty-case result and plan versus policy

B = bank cash flow; C = coverage; D = document catalog; I = invoices; R = reconciliation; F = forestry sale; V = review coverage; E = saved electricity comparison; G = supplier/grid scope; T = tax boundary context. “Model implied” includes dependencies of its own flags/type (for example coverage flag implies B+C, reconciliation implies I+R). “Policy added” excludes those model-declared implications. This avoids attributing a model flag to policy completion.

| Case | Critical | Result | Model listed | Model implied | Policy added | Effective | Retrieved |
|---|---|---|---|---|---|---|---|
| primary | No | FAIL | B, D, F, I, R, V | B, C, D, F, I, R, V | E | B, C, D, E, F, I, R, V | B, C, D, E, F, I, R, V |
| electricity | No | PASS | B, D, I, R | B, C, D, I, R | E, G | B, C, D, E, G, I, R | B, C, D, E, G, I, R |
| timber | No | PASS | B, F | B, C, F, I, R | — | B, C, F, I, R | B, C, F, I, R |
| receipts | No | FAIL | C, D, I, R | B, C, D, I, R | F | B, C, D, F, I, R | B, C, D, F, I, R |
| ambiguous | Yes | FAIL | B, C, R | B, C, I, R | — | B, C, I, R | B, C, I, R |
| property | No | PASS | B, D, R | B, C, D, I, R | — | B, C, D, I, R | B, C, D, I, R |
| spot | No | PASS | E, V | B, C, E, V | — | B, C, E, V | B, C, E, V |
| review | No | FAIL | B, R, V | B, C, I, R, V | — | B, C, I, R, V | B, C, I, R, V |
| tax | Yes | FAIL | B, D, I, T | B, C, D, I, T | — | — | — |
| missing | Yes | PASS | B, D, I, R | B, C, D, I, R | — | B, C, D, I, R | B, C, D, I, R |
| doublecount | Yes | PASS | B, I | B, I | C, F, R | B, C, F, I, R | B, C, F, I, R |
| reversal | Yes | PASS | B, D, R | B, D, I, R | C | B, C, D, I, R | B, C, D, I, R |
| deductions | Yes | PASS | B, D, I, T | B, C, D, I, T | — | B, C, D, I, T | B, C, D, I, T |
| arithmetic | Yes | PASS | B, C, D, I, R | B, C, D, I, R | — | B, C, D, I, R | B, C, D, I, R |
| forestry_evidence | No | PASS | B, D | B, C, D | F, I, R | B, C, D, F, I, R | B, C, D, F, I, R |
| electricity_evidence | No | PASS | C, E, T | B, C, E, T | G | B, C, E, G, T | B, C, E, G, T |
| unresolved_forestry | No | PASS | B, C, F, R | B, C, F, I, R | V | B, C, F, I, R, V | B, C, F, I, R, V |
| coverage | No | PASS | B, C | B, C | E, F, I, R | B, C, E, F, I, R | B, C, E, F, I, R |
| payment_evidence | Yes | PASS | B, D, F | B, C, D, F, I, R | — | B, C, D, F, I, R | B, C, D, F, I, R |
| trust | No | PASS | B, C, D, I, R | B, C, D, I, R | E, F, V | B, C, D, E, F, I, R, V | B, C, D, E, F, I, R, V |

Nine accepted plans were complete without policy-added views: timber, ambiguous, property, spot, review, missing, deductions, arithmetic, payment_evidence. This is semantic-view completeness, not a claim that every filter is ideal or that the final passed. In particular, `ambiguous` and `review` later omitted final references.

Ten cases required policy-added views: primary, electricity, receipts, doublecount, reversal, forestry_evidence, electricity_evidence, unresolved_forestry, coverage, trust. The remaining `tax` plan was rejected before an effective plan existed; its empty policy-added list does not signify completeness.

## Failures and critical behavior

| Failed case | Root cause | Classification |
|---|---|---|
| primary | Filtered FORESTRY and PROPERTY summaries retrieved, but the frozen primary rubric requires an unfiltered all-context summary. All mandatory handles were selected. | WRONG_SCOPE |
| receipts | Final omitted E0 (bank/coverage) and E2 (forestry sale). Retrieval was complete; final failed closed. | FINAL_REFERENCE_FAILURE |
| ambiguous (critical) | Final omitted E6 and E7, two mandatory direct reconciliation results. | FINAL_REFERENCE_FAILURE |
| review | Final omitted E6, a mandatory direct reconciliation result. | FINAL_REFERENCE_FAILURE |
| tax (critical) | Model chose UNKNOWN context from a merchant-only question. Existing policy rejects any nonempty context list without explicit user scope. No retrieval or final occurred. | WRONG_CONTEXT; TAX_BOUNDARY_FAILURE |

Tax failure is a blocked answer, not an unsafe tax decision: the generic loop status INVALID_FINAL_CONTENT masks the more precise retained policy error AMBIGUOUS_MERCHANT_CONTEXT_REQUIRES_EXPLICIT_SCOPE. This is not a final-reference/schema failure. The model did not claim FORESTRY, but UNKNOWN is still a restrictive ledger filter rather than an instruction to leave context unspecified.

The six passing critical cases are missing, doublecount, reversal, deductions, arithmetic and payment_evidence. Both monetary-target cases directly retrieved the €588.07 invoice reconciliation and retained AMBIGUOUS plus human_review_required. No invented financial amount or unsupported reconciliation decision reached an answer. Missing-data refusal, double-count prevention, tax boundary and arithmetic delegation passed where the frozen rubric accepted the case. Failed finals emitted no financial answer.

## Plan and policy limitations

The smallest recurring failure is mandatory-handle omission (three cases, including one critical). All 19 policy-accepted plans retrieved their effective views; zero mandatory retrieval failures occurred. Better retrieval alone therefore does not guarantee final evidence completeness.

The primary all-context condition cannot be expressed alongside required named contexts by the current plan/coordinator contract: contexts are a list of filters and policy unions named contexts; there is no separate include-all-context aggregate flag. This known incompatibility remains a scored failure, not a scoring exemption.

Semantic limitations outside the frozen pass/fail checks remain visible: `electricity` chose PROPERTY despite an unscoped question; `reversal` chose UNKNOWN; policy retained those restrictions. Invoice retrieval was still period-wide, and the exact reversal target was found, so these are not proven factual errors or new score deductions. `unresolved_forestry` queries confirmed FORESTRY review scope and cannot establish the potential forestry impact of UNKNOWN-purpose rows. The schema has no merchant-specific or target-amount discovery constraint; invoice reconciliation compensates by looking up every discovered invoice. `electricity_evidence` unnecessarily requested tax-boundary evidence, forcing the tax template despite a results final key. These limitations were documented without changing requirements or scores.

There are no additional definitively wrong accepted context choices under the existing frozen constraints beyond primary’s scope mismatch. UNKNOWN in tax is definitively rejected. Broader semantic adequacy is not established by the score; the issues above require offline review.

## Reference and optional-call behavior

19 provider finals passed the handle schema; 16 passed ledger/mandatory validation, and 3 omitted mandatory handles. Unknown handles: 0; duplicate handles: 0; failed-result handles: 0; raw numeric/index finals: 0; final schema errors: 0. Tax had no final. Missing references were neither manufactured nor repaired. The trusted renderer succeeded for all 16 accepted finals, and every rendered answer exactly matched rendering of its selected source results.

Optional calls: **0 across all 20 cases**. Usefulness, duplication, wrong optional scope and necessity are therefore not applicable. Mandatory calls with repeated tool names used distinct contexts or invoice IDs. No extra-call penalty was added.

Scoring reuses the unchanged historical rubric and evidence requirements on retained responses/traces. The legacy no_arithmetic_by_llm test is vacuous without legacy ModelTurns; independent typed HandleFinal validation and exact renderer equality establish the arithmetic/prose boundary. This limitation is explicit rather than silently treated as new model-competence evidence. Message-key mismatches are retained; the historical rubric does not require exact key equality except its tax behavior checks. In particular ambiguous/review used results, but were already rejected for missing handles; no counterfactual extra score is invented.

## Comparison with historical C

| Case | Phase 08 C | Phase 09D | Attribution |
|---|---|---|---|
| primary | FAIL | FAIL | UNCHANGED_FAILURE |
| electricity | PASS | PASS | NOT_ATTRIBUTABLE |
| timber | FAIL | PASS | STRUCTURALLY_IMPROVED_BY_MANDATORY_RETRIEVAL |
| receipts | FAIL | FAIL | UNCHANGED_FAILURE |
| ambiguous | FAIL | FAIL | UNCHANGED_FAILURE |
| property | PASS | PASS | NOT_ATTRIBUTABLE |
| spot | PASS | PASS | NOT_ATTRIBUTABLE |
| review | FAIL | FAIL | UNCHANGED_FAILURE |
| tax | FAIL | FAIL | UNCHANGED_FAILURE |
| missing | PASS | PASS | NOT_ATTRIBUTABLE |
| doublecount | PASS | PASS | NOT_ATTRIBUTABLE |
| reversal | FAIL | PASS | STRUCTURALLY_IMPROVED_BY_MANDATORY_RETRIEVAL |
| deductions | PASS | PASS | NOT_ATTRIBUTABLE |
| arithmetic | PASS | PASS | NOT_ATTRIBUTABLE |
| forestry_evidence | FAIL | PASS | STRUCTURALLY_IMPROVED_BY_MANDATORY_RETRIEVAL |
| electricity_evidence | PASS | PASS | NOT_ATTRIBUTABLE |
| unresolved_forestry | PASS | PASS | NOT_ATTRIBUTABLE |
| coverage | FAIL | PASS | STRUCTURALLY_IMPROVED_BY_MANDATORY_RETRIEVAL |
| payment_evidence | FAIL | PASS | NOT_ATTRIBUTABLE |
| trust | FAIL | PASS | STRUCTURALLY_IMPROVED_BY_MANDATORY_RETRIEVAL |

Six prior failures now pass; all nine prior passes remain passes; five failures remain. The five STRUCTURALLY_IMPROVED_BY_MANDATORY_RETRIEVAL labels indicate that previously missing source calls are now coordinator-enforced, not a controlled causal estimate. Some also required policy completion. Payment_evidence is NOT_ATTRIBUTABLE because its historical failure was final-reference related; the new handles and coordinator both changed. No case is claimed as solely IMPROVED_PLAN; no NEW_FAILURE occurred. Historical results are immutable.

## Latency, usage and acceptance

Total measured case execution latency: **51.917304 seconds**, excluding preflight, between-case hash checks and final verification. Total model decisions: 39 (19 plan/final pairs plus one rejected plan). Input tokens: **248,434**; cached input: **0**; output: **3,444**. Estimated cost: **USD 0.20182350**, using frozen historical C rates $0.75/$0.075/$4.50 per million input/cached/output tokens, not a current pricing claim or bill.

The development gate requires at least 18/20, all 8 critical cases, no invented financial amounts, no unsupported reconciliation decisions and no unresolved final-reference/protocol failures. This run has 15/20, 6/8 and three unresolved reference omissions: **NOT_READY**. The run itself is valid, with no systemic infrastructure failure.

## Verification and next step

Verification results are recorded in `data/interim/phase09d/verification.json`: full pytest, Ruff format/check, diff check, dependency lock, Alembic, all source/human-review fingerprints, 66 protected electricity artifacts, historical artifacts, frozen snapshot, holdout byte hash and privacy scan. Raw plans, exact requests without headers, native responses/finals, effective plans, traces, handle maps, final validation, rendered responses, diagnostics, latency and usage remain private.

Recommended next step: separately authorize offline analysis/design for mandatory-reference omissions, the merchant-context rejection and primary’s all-context constraint. Preserve this run and the frozen scoring; do not open holdout or rerun live development. No implementation fix has been made in this task.
