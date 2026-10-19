# Phase 09H — exclusive contexts and bounded rendering

Offline verification only. Phase 09G remains NOT_READY; historical scores are unchanged. No live provider calls, holdout inspection, source edits or evaluation-requirement changes.

## Contract

`context_selection` is a union of three disjoint objects: `{"mode":"ALL"}`, `{"mode":"UNSPECIFIED"}`, or `{"mode":"SELECTED","contexts":[...]}`. ALL and UNSPECIFIED forbid the contexts property, including an empty list. SELECTED requires one or more PERSONAL, PROPERTY, FORESTRY or UNKNOWN labels; duplicates reject. UNKNOWN is never converted to UNSPECIFIED.

The provider schema uses nested anyOf with mutually exclusive literal tags and additionalProperties=false. Offline JSON Schema tests verify exactly one matching branch for all six requested valid intents and rejection of contradictory shapes. No provider-boundary intent guessing was added.

Versioned entry points: `tapio.agent.exclusive.run_scoped_agent`, `tapio.agent.providers.openai_exclusive.OpenAIExclusiveModel`, and `tapio.agent.render_bounded.render_answer`. Historical scoped/provider/renderer modules remain byte-identical for reproducibility. Evidence policy and retrieval/reference gates are unchanged.

## Retained-plan counterfactual replay

All 12 contradictory JSON shapes are excluded by the new contract. Of those 12, **3 effective intents are unambiguous under the existing policy**: primary and review resolve to ALL; tax resolves to UNSPECIFIED because SELECTED UNKNOWN violates the existing ambiguous-merchant safeguard. **9 remain model-dependent**. This is policy-constrained alternative analysis, not a claim to know the model’s hidden intent, and no automatic migration is used in the provider.

For each retained contradiction, replay considers the explicit mode and the explicit selected-label list separately. It rejects policy-invalid alternatives and deduplicates equal effective selections. Multiple remaining selections are retained as alternatives; none is chosen using expected benchmark outcomes.

## Twenty-case structural check

STRUCTURALLY_READY means one effective scope, successful mandatory retrieval, explicit complete required-handle contract, preserved safety boundaries, and bounded renderer output. It does not mean a model final was generated or passed. STILL_MODEL_DEPENDENT means multiple valid effective scopes; every listed branch still passed the mechanical retrieval/render checks. All final handle selection remains model-dependent.

| Case | Offline result |
|---|---|
| primary | STRUCTURALLY_READY |
| electricity | STILL_MODEL_DEPENDENT |
| timber | STILL_MODEL_DEPENDENT |
| receipts | STILL_MODEL_DEPENDENT |
| ambiguous | STRUCTURALLY_READY |
| property | STILL_MODEL_DEPENDENT |
| spot | STILL_MODEL_DEPENDENT |
| review | STRUCTURALLY_READY |
| tax | STRUCTURALLY_READY |
| missing | STRUCTURALLY_READY |
| doublecount | STILL_MODEL_DEPENDENT |
| reversal | STILL_MODEL_DEPENDENT |
| deductions | STRUCTURALLY_READY |
| arithmetic | STRUCTURALLY_READY |
| forestry_evidence | STRUCTURALLY_READY |
| electricity_evidence | STRUCTURALLY_READY |
| unresolved_forestry | STILL_MODEL_DEPENDENT |
| coverage | STRUCTURALLY_READY |
| payment_evidence | STILL_MODEL_DEPENDENT |
| trust | STRUCTURALLY_READY |

**11 STRUCTURALLY_READY; 9 STILL_MODEL_DEPENDENT; 0 STRUCTURAL_FAILURE.** All 29 alternative executions completed mandatory evidence retrieval. No model finals were fabricated. Eight existing successful final payloads were re-rendered without changing their selected source results.

## Safety and concision

General review retrieves all **95 unique unresolved rows**, with no restrictive context filter. Merchant tax discovery uses UNSPECIFIED, retrieves the human-reviewed merchant candidate, preserves its human-confirmed labels, and permits only tax_review_required final messaging. Tapio makes no deductibility decision.

Deductions previously rendered up to ten transaction examples per retrieved page. The repair preserves outputs already within 850 words, then reduces optional whole-row transaction examples across the answer until the frozen limit is met. The retained deductions final is **845 words**, down from 896. Required references, full source rows, financial totals, coverage and tax-boundary content remain intact. Coverage and trust remain 845 words.

For arbitrarily large evidence, a fixed-size evidence-index fallback explicitly points to the complete structured results rather than claiming a partial financial summary. No sentence is cut and no structured evidence/reference is removed. This fallback was stress-tested; none of the 20 development cases needed it.

## Verification and decision

**806 tests passed: all original 779 plus 27 focused tests.** Final renderer refinement additionally passed all 27 focused tests. Ruff check/format (225 files), git diff whitespace check, dependency lock (129 packages), and Alembic check passed. All 14 source/human-review table fingerprints, 1,218 protected historical hashes, and 66 electricity artifacts remain unchanged. The privacy scan found zero secret/source-identifier matches; 1,101 private files were confirmed ignored by Git. Holdout verification used a byte digest only. Private traces and detailed integrity/privacy results are in `data/interim/phase09h/`.

One final development-only C run is justified to observe the nine unresolved model choices and final-reference selection. No run is authorized or performed here. Freeze a new configuration using the exclusive adapter and bounded renderer; retain the existing model, budget, questions and evidence/scoring requirements. The deterministic-render identity check must bind to this version’s renderer, while historical runs retain their original renderer. Do not reuse or rewrite PHASE09F_SCOPED_C_V1. Pilot status remains NOT_READY until a real development gate passes.
