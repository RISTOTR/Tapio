# Phase 08 development rerun — 2026-10-16

**NOT_READY.** A, B and C all failed the frozen development acceptance gate. Holdout was not opened or executed. No question, expected evidence, scoring, critical definition, prompt, tool description, model setting, round budget, renderer or source data was changed during evaluation. No failed case was retried.

## Frozen evidence and configuration

Snapshot: `data/interim/phase08/human_review_20261016_268cbff95973/snapshot.json`.
SHA-256: `ee55cdd801da98d66acd09dd754222457cdc464f38fabe0471b186456e0b5221`.

2026 review state: 75/170 reviewed (44.12%); 95 unresolved, all P3; P1/P2 zero. Contexts: PERSONAL 45, PROPERTY 20, FORESTRY 10, unresolved/UNKNOWN 95. Bank coverage remains PARTIAL_YEAR / UNKNOWN_COVERAGE. Human choices remain authoritative; ambiguous merchants receive no merchant-only context or tax classification.

The runner explicitly supplies frozen Phase 08 bank/review coverage metadata to the existing registry; its default Phase 07 behavior remains unchanged. This configuration input was established before the smoke test. All three configurations used the same live database fingerprints, checked before and after each run. `inputs.json` freezes source fingerprints, review counts, dataset hashes (holdout hash copied from its manifest), tool specifications, registry/runner/policy hashes and adapter hashes.

A: `gpt-5.4-nano-2026-03-17`; B and C: `gpt-5.4-mini-2026-03-17`. C retains the existing typed planning architecture. Six rounds, five tool calls before forced finish, `reasoning_effort=none`, 3000 maximum completion tokens, parallel calls disabled; no substitutions.

## Live strict-schema smoke test

The existing development `primary` case ran once with B before the benchmark. All five API requests succeeded, including strict final-function schema acceptance. The final selected canonical references were `[0, 1, 2, 3]` (stored as `{"call_index": n}` objects). Raw native arguments, normalized final, validation and tool ledger are retained privately. Result: COMPLETE, EVIDENCE_COMPLETE, exact trusted rendering; zero normalization or rejection.

Latency 9.5104 seconds; input 75,510 tokens (0 cached), output 195; estimated cost $0.05751000. This preliminary smoke case is separate from the subsequent 20-case B run.

API compatibility was checked against [official OpenAI function-calling documentation](https://developers.openai.com/api/docs/guides/function-calling): strict function schemas require required properties and disallow additional object properties. Live acceptance, rather than documentation alone, established compatibility for these exact requests.

## Development results

| Metric | A | B | C |
| --- | ---: | ---: | ---: |
| Evidence complete / 20 | 6 | 6 | 9 |
| Critical pass / 8 | 3 | 3 | 4 |
| Final/schema rejections | 2 | 0 | 2 |
| Provider-format normalizations | 0 | 0 | 0 |
| Missing-evidence failures | 12 | 14 | 10 |
| Wrong-scope failures | 3 | 3 | 1 |
| Tool error events | 0 | 0 | 0 |
| Unsupported claims detected | 0 | 0 | 0 |
| Ambiguity failures | 4 | 2 | 2 |
| Tax-boundary/disclosure failures | 3 | 0 | 2 |
| Coverage-disclosure failures | 2 | 0 | 2 |
| Average returned rounds | 2.7000 | 2.4500 | 4.2000 |
| Total latency, seconds | 67.8901 | 71.1224 | 99.0454 |
| Estimated cost, USD | 0.06790294 | 0.12410415 | 0.39836310 |
| Tokens: input | 397587 | 274977 | 540620 |
| Tokens: cached_input | 79872 | 134272 | 36608 |
| Tokens: output | 2210 | 1890 | 3913 |

Labels: `PHASE08_A_NEW_SNAPSHOT`, `PHASE08_B_NEW_SNAPSHOT`, `PHASE08_C_NEW_SNAPSHOT`. Costs use frozen Phase 07 rates, not billed charges or a claim of current pricing. Combined development latency: 238.0579 seconds; including smoke: 247.5683 seconds. Total estimated cost including smoke: **$0.64788019**.

Failure counts overlap. Missing evidence means frozen requirements missing or required selected tools omitted. Wrong scope includes the original rubric and dedicated energy/review scope requirements. Returned-round averages exclude a provider turn rejected before becoming a canonical DTO; token/latency totals still include returned provider usage. Tax/coverage/ambiguity counts include missing required disclosures when a final was rejected, not necessarily an affirmative unsafe claim.

All four native final rejections are `FINAL_REFERENCE_OUT_OF_RANGE`: A/primary, A/doublecount, C/reversal, C/payment_evidence. Their representations were already canonical; normalization must not repair nonexistent references. C/reversal is externally EVIDENCE_INCOMPLETE after its existing gate, so protocol-event inspection is required to count that rejection. B has zero final/schema rejection. No provider transport/API-schema rejection occurred.

No unsupported financial prose was detected by exact trusted-renderer equality. This is not an independent factual oracle. Missing direct reconciliation evidence remains a failure; absence of unsupported prose does not make those answers acceptable.

## Critical outcomes

| Frozen critical case | A | B | C |
| --- | --- | --- | --- |
| ambiguous | FAIL | FAIL | FAIL |
| tax | PASS | FAIL | FAIL |
| missing | PASS | PASS | PASS |
| doublecount | FAIL | FAIL | PASS |
| reversal | FAIL | FAIL | FAIL |
| deductions | FAIL | PASS | PASS |
| arithmetic | PASS | PASS | PASS |
| payment_evidence | FAIL | FAIL | FAIL |

All configurations miss the required 18/20 development threshold and 8/8 critical gate. Holdout score: **not run**. The eight frozen critical cases cover ambiguity, double counting, tax boundaries, missing-data fabrication, deterministic arithmetic and payment/reconciliation evidence.

## Phase 07 comparison and attribution

Historical Phase 07 scores remain A 5/20, B 1/20, C 3/20. New Phase 08 scores are A 6/20, B 6/20, C 9/20. Historical result files and scores were not rewritten. Schema-format behavior improved, but source evidence, protocol and stochastic outputs differ together. Most historical native finals were not retained. No causal improvement is assigned to human review, protocol repair or model selection without a controlled comparison.

Per-case classification: 32 UNCHANGED_EVIDENCE_FAILURE, 3 NEW_FAILURE, 25 NOT_ATTRIBUTABLE (including unchanged passes). The private `assessment.json` contains every old/new outcome and explanation. Typical remaining gaps include linked documents, forestry-sale evidence, direct reconciliation, required bank context and energy scope. C improves some evidence selection but still fails critical cases.

| Case | A old→new; classification | B old→new; classification | C old→new; classification |
| --- | --- | --- | --- |
| primary | FAIL→FAIL; NOT_ATTRIBUTABLE | FAIL→PASS; NOT_ATTRIBUTABLE | PASS→FAIL; NEW_FAILURE |
| electricity | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | PASS→PASS; NOT_ATTRIBUTABLE |
| timber | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE |
| receipts | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE |
| ambiguous | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE |
| property | PASS→PASS; NOT_ATTRIBUTABLE | FAIL→PASS; NOT_ATTRIBUTABLE | PASS→PASS; NOT_ATTRIBUTABLE |
| spot | PASS→PASS; NOT_ATTRIBUTABLE | FAIL→PASS; NOT_ATTRIBUTABLE | FAIL→PASS; NOT_ATTRIBUTABLE |
| review | FAIL→PASS; NOT_ATTRIBUTABLE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; NOT_ATTRIBUTABLE |
| tax | FAIL→PASS; NOT_ATTRIBUTABLE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE |
| missing | PASS→PASS; NOT_ATTRIBUTABLE | FAIL→PASS; NOT_ATTRIBUTABLE | FAIL→PASS; NOT_ATTRIBUTABLE |
| doublecount | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→PASS; NOT_ATTRIBUTABLE |
| reversal | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE |
| deductions | FAIL→FAIL; NOT_ATTRIBUTABLE | FAIL→PASS; NOT_ATTRIBUTABLE | FAIL→PASS; NOT_ATTRIBUTABLE |
| arithmetic | PASS→PASS; NOT_ATTRIBUTABLE | FAIL→PASS; NOT_ATTRIBUTABLE | FAIL→PASS; NOT_ATTRIBUTABLE |
| forestry_evidence | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE |
| electricity_evidence | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→PASS; NOT_ATTRIBUTABLE |
| unresolved_forestry | PASS→FAIL; NEW_FAILURE | PASS→FAIL; NEW_FAILURE | FAIL→PASS; NOT_ATTRIBUTABLE |
| coverage | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE |
| payment_evidence | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; NOT_ATTRIBUTABLE |
| trust | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE | FAIL→FAIL; UNCHANGED_EVIDENCE_FAILURE |

## Retention, verification and next step

Private run root: `data/interim/phase08/development_rerun_v1/`. Per-case reports link untouched provider-native response artifacts, normalized canonical finals and validation status. `retained_finals.json` consolidates raw argument strings, normalization status, executed tool ledgers, selected references and evidence-completeness outcomes for all 60 development cases. Request records retain final schema and success status without keys/headers. No final is fabricated for a case that emits none.

Full regression suite: **684 passed**. Ruff format/check, git diff check, dependency lock and Alembic checks passed. Final verification checks all 14 source tables, 66 protected electricity files, 259 combined protected/historical artifacts, frozen Phase 08 snapshot, protocol/scoring/renderer hashes and private-output retention. Privacy scan results are in `privacy_verification.json`; complete verification is in `verification.json`.

**Recommended next step:** authorize a separate offline failure-analysis and repair phase using these retained traces, focusing on evidence selection and out-of-range references. Keep holdout sealed. Any subsequent changes require a new evaluation version and a separately authorized development rerun; this run is complete and must not be tuned or selectively retried.
