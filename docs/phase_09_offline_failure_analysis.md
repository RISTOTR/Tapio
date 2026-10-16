# Phase 09 offline agent failure analysis — 2026-10-16

**Diagnosis only. Pilot remains NOT_READY.** Zero model calls, zero API tokens and zero fresh source-tool executions. Holdout contents remain sealed. Source data, human labels, live orchestration, tool descriptions, evidence requirements, renderer and scoring are unchanged. Phase 07/08 scores are not revised.

## Evidence and method

All 60 Phase 08 development traces and all 60 retained native finals were available. The private machine-readable inventory is `data/interim/phase09/failure_inventory.json` (analysis version 3). It records configuration, question/class, expected views and tools, actual plan, ordered indexed ledger, success/failure, repeat positions, omitted views, raw/effective message keys, raw/validated references, rejection, critical/outcome status, rounds, budget attribution and replay provenance. Earlier classifier drafts are retained separately and are not final results.

The analysis freezes every Phase 08 run artifact hash. It uses unchanged `infer_requirements`, `missing_requirements`, `evaluate_case`, `score`, and the trusted renderer. Raw absence is never replaced by inferred data; an unavailable final would be recorded as unavailable. Results from a rejected final are a loop fallback containing all retrieved results, not validated selected references. The analyzer explicitly distinguishes these.

Observed behavior can establish omissions, wrong filters and invalid indexes. It cannot establish the model’s internal reasoning. Description ambiguity is a documented plausible contributor, not a proven psychological cause. All class counts below overlap.

## Dominant findings

Of 39 failed runs, **36 omitted required retrieval**, **two had sufficient evidence but rejected references** (A/primary and C/payment_evidence), and **one had sufficient evidence but the wrong tax-boundary message** (A/deductions). There were no failed source-tool results. No valid final was shown to omit a retrieved mandatory view; successful retrieval selection is not the dominant bottleneck.

| Failure class | A | B | C |
| --- | ---: | ---: | ---: |
| EVIDENCE_NOT_REQUESTED | 12 | 14 | 10 |
| WRONG_TOOL_SELECTED | 1 | 1 | 5 |
| WRONG_FILTER_OR_SCOPE | 2 | 2 | 0 |
| EVIDENCE_PLAN_INCOMPLETE | 0 | 0 | 0 |
| PLAN_NOT_FOLLOWED | 0 | 0 | 8 |
| ROUND_BUDGET_EXHAUSTED | 0 | 0 | 3 |
| REPEATED_CALL_WASTE | 1 | 0 | 0 |
| TOOL_RESULT_MISREAD | 0 | 0 | 0 |
| FINAL_REFERENCE_OUT_OF_RANGE | 2 | 0 | 2 |
| FINAL_REFERENCE_OMITS_VALID_EVIDENCE | 0 | 0 | 0 |
| FINAL_MESSAGE_KEY_WRONG | 1 | 0 | 0 |
| REQUIRED_POLICY_NOT_TRIGGERED | 1 | 0 | 1 |
| TOOL_DESCRIPTION_AMBIGUITY | 1 | 1 | 5 |
| PROVIDER_FINALIZATION_ERROR | 0 | 0 | 0 |
| OTHER_EXPLICITLY_DOCUMENTED | 0 | 0 | 0 |

WRONG_TOOL_SELECTED here means an observed generic-document detour while invoice-view evidence remained missing. TOOL_RESULT_MISREAD and PROVIDER_FINALIZATION_ERROR remain zero because these traces do not establish either cause. Raw C/tax says `missing_evidence`, but the existing planner changes the effective message to `tax_review_required`; its actual failure is missing transaction evidence, not an effective tax-message failure.

## Evidence-selection subtypes

| Subtype | A | B | C |
| --- | ---: | ---: | ---: |
| A: required view absent from emitted plan | N/A | N/A | 0 |
| B: declared view not retrieved | N/A | N/A | 8 |
| C: existing tool called with wrong scope/filter | 2 | 2 | 0 |
| D: mandatory retrieved view omitted from valid final | 0 | 0 | 0 |
| E: incomplete observed trajectory reaches six rounds | 0 | 0 | 3 |
| F: equivalent repeat in a failed run | 1 | 0 | 0 |
| G: generic-document versus invoice-view ambiguity | 1 | 1 | 5 |
| G: satisfied generic plan lacks frozen source-specific requirement | 0 | 0 | 1 |

A/B do not emit plans, so absence of a plan is not evidence of a wrong internal plan. Their general inferred requirement object is not supplied to the model as it is in C (apart from the provider’s shared overview guidance). This is a material orchestration difference, not simply model size. A and B electricity cases each use supplier-only category filtering and omit grid/comparison evidence. Review failures omit the review tool rather than calling it with a bad filter.

A/unresolved_forestry repeats equivalent summaries (omitted nullable filters versus explicit null). A/missing also repeats an identical summary but passes. B/receipts repeats `find_invoices` with a larger limit; this is recorded as a repeated tool, not classified as equivalent-call waste because the query differs. It contributes no missing evidence view and still finalizes early.

## Out-of-range reference forensics

| Case | Raw references | Total/successful ledger positions | Evidence calls | Valid range | Observation |
| --- | --- | ---: | ---: | --- | --- |
| A/primary | 0,2,1,3,4 | 4/4 | 4 | 0–3 | Complete zero-based set plus next nonexistent position 4 |
| A/doublecount | 1,2,3 | 3/3 | 3 | 0–2 | Exact one-based full-ledger pattern |
| C/reversal | 1,2,3,4 | 4/4 | 3 | 0–3 | Exact one-based full ledger; plan occupies 0 |
| C/payment_evidence | 1,2,3,4,5 | 5/5 | 4 | 0–4 | Exact one-based full ledger; plan occupies 0 |

Every invalid value is exactly the next nonexistent position N. No reference targets a failed call (all calls succeeded). Three outputs match one-based numbering over the entire ledger. The C outputs also resemble intended exclusion of plan index 0 followed by an inclusive-upper-bound mistake; the traces cannot choose between those hypotheses. A/primary mixes zero-based valid references with one extra index, so a universal one-based conversion is disproved. No clamping, shifting or normalization was applied.

Assistant tool-call turns correspond one-to-one to ledger positions, so one-based assistant-call numbering is another observationally equivalent explanation for three cases. Full conversation-message numbering is not established. Filtering failed calls cannot explain the failures because none failed. Evidence-only zero-based numbering would have smaller ranges in C and cannot validate the emitted maxima. The nonexistent position could be an imagined future call or finalization itself; neither interpretation is proven.

Provider conversion generates `tapio_call_N` identifiers and matching tool-message `tool_call_id`s. Thus numbering is not wholly invisible: the index can be inferred from a transport identifier and ordering. But tool result bodies do not explicitly state `call_index` or a stable evidence handle. The prompt says zero-based and reports the number of calls, leaving the model to distinguish a count N from a maximum index N−1.

The adapter, loop and evaluator all count the same full call/result ledger, including the planning control call at index 0 in C. There is no observed internal index-unit disagreement. Two valid C finals even include the plan as reference 0 (forestry_evidence and unresolved_forestry), showing that control and evidence namespaces are not separated. Planning changes evidence offsets and adds an avoidable interpretation burden.

Proposed design, not implemented: result bodies expose immutable `evidence_ref: E3` handles minted only for successful source evidence. The adapter resolves handles through a session ledger to canonical internal `call_index`; planning uses a separate control namespace. Transport call IDs remain transport IDs. Unknown, duplicate, failed or stale handles must reject. This would not authorize inventing or auto-adding references.

## Configuration C planning effectiveness

All 20 emitted plans contain every inferred required view. Among 11 failures: **9 PLAN_CORRECT_EXECUTION_WRONG**, **1 REQUIREMENT_NOT_EXPRESSIBLE_IN_PLAN_SCHEMA** (tax), **1 PLAN_AND_EXECUTION_CORRECT_FINAL_WRONG** (payment_evidence). PLAN_WRONG and structural PLAN_CORRECT_BUDGET_INSUFFICIENT are zero under the defined view-level comparison.

C/tax declares bank and coverage, retrieves them plus invoices, and still omits the frozen required transaction query. The plan schema has no binding for that source-specific tax-purchase evidence. Direct reconciliation, supplier-plus-grid categories and NEEDS_REVIEW filters are also absent as typed plan fields, though C receives these requirements separately in its system text. Required contexts and coverage-check fields are declared but are not merged like required views; the runtime union only merges views and the tax flag. This makes the plan an incomplete execution contract.

C improves B’s 6/20 to 9/20, with four new passes and one lost pass. This cannot isolate the value of the planning call: C also receives explicit deterministic requirements. It spends one model/control round in every case (20 total), leaving four evidence calls and a finish. An accurate declaration often fails to produce accurate execution. The current post-answer gate detects incompleteness but does not schedule missing retrieval or prevent early finalization.

## Budget analysis

**FAILURE_DUE_TO_BUDGET: 0. FAILURE_NOT_DUE_TO_BUDGET: 39.** This is structural attribution: recorded witnesses satisfy every case’s requirements using 1–4 evidence calls, fitting the existing limits even with C’s planning round. It does not deny trajectory pressure caused by waste.

C/primary, C/forestry_evidence and C/trust exhaust the six-round trajectory while missing invoice/reconciliation evidence. Replacing generic catalog/summary retrieval with `find_invoices` fits the required evidence into the existing budget; adding an extra call to the already wasteful trajectory is not the smallest fix. C/payment_evidence uses six provider rounds but has sufficient retrieved evidence; its failure is the invalid final, not retrieval capacity. All other failed trajectories finish before the limit.

One additional recorded call can satisfy retrieval deficits in A: 1, B: 3, C: 8 failed runs. This is a conditional evidence test, not a claim that the model would choose it or that an invalid final would then pass. Some require replacement as well as addition for proper scope. Useful/noncontributing evidence-call counts across all runs: A 28/8, B 25/4, C 38/8, plus C’s 20 planning calls. “Noncontributing” means no mandatory view/tool contribution, not that the content has no possible human value.

## Tool descriptions and proposed wording (not applied)

| Tool boundary | Observed ambiguity/gap | Minimal proposed wording |
| --- | --- | --- |
| Bank aggregate vs invoice evidence | Cash summaries do not establish receipts or reconciliation; early finalization is common | “Bank cash totals only. Receipt/support/payment-state requests additionally require invoice/reconciliation evidence.” |
| list_documents/get_document_summary vs find_invoices | DOCUMENTS policy name sounds like catalog metadata, but only invoice tools satisfy it | “Catalog/provenance only; not invoice amounts or payment reconciliation. Use find_invoices for invoice evidence.” |
| find_invoices | Description only advertises bounded search; does not say it includes reconciliation states | “Returns invoice evidence including stored reconciliation states. Do not add invoice amounts to bank cash totals.” |
| Forestry bank vs sale view | Bank income aggregate is substituted for independent sale source | “Sale-document facts, separate from received bank cash; combine as evidence without summing both.” |
| Electricity bank vs saved comparison | Saved tool description says spot questions, while frozen policy also requires it for electricity totals/evidence | “Limited-period saved energy evidence; complements supplier-plus-grid bank totals, not a full-year replacement.” |
| query_transactions | Brief description omits review_state guidance and purpose review | “For unresolved classifications use review_state=NEEDS_REVIEW; scoped transaction evidence supports purpose review, not deductibility.” |
| Direct reconciliation | Generic invoice state can be mistaken for sufficient ambiguous/refund evidence | “For ambiguous/refund/reversal claims retrieve this direct state using an invoice ID discovered from invoice evidence; never assume allocation.” |

These wording proposals clarify generic source contracts rather than embedding benchmark questions or mandatory case IDs. Naming DOCUMENTS as an invoice-evidence view could be considered in a later version, but this phase does not rename requirements. Tool-result misreading cannot be distinguished from selection habits in the current traces; it is not asserted.

## Semantic orchestration opportunities

| Intent | Mandatory evidence policy to execute |
| --- | --- |
| Forestry cash/source overview | Bank cash + invoice/reconciliation view + sale view; preserve separate accounting bases |
| Property costs | Property bank/context + review/coverage metadata; add energy evidence when energy is in scope |
| Ambiguous payment/refund | Bank context + invoice discovery + direct reconciliation; retain uncertainty |
| Tax-purpose question | Scoped transaction/purpose evidence + applicable source evidence + bank/coverage + mandatory human tax boundary |
| Unresolved review | Bank coverage/context + NEEDS_REVIEW transaction query, independent of merchant heuristics |
| Multi-domain overview/coverage | Unfiltered bank summary + invoice/reconciliation + sale + saved energy evidence with limited periods |
| Spot comparison | Saved accepted comparison with its actual period, not inferred annual coverage |

These are semantic capabilities and constraints, not a per-question tool sequence. A coordinator should discover dependencies (e.g. invoice IDs), preserve scope, enforce caps and expose honest incomplete status when evidence cannot be obtained. It must not assert that a generic query necessarily establishes a specific payment or tax fact.

## Architecture options

| Dimension | 1: Model chooses tools, clearer descriptions | 2: Typed plan, deterministic coordinator | 3: Deterministic intent router/bundles |
| --- | --- | --- | --- |
| Reliability | Still depends on model remembering/completing retrieval | Enforceable required views, scope and dependency completion | Strong for covered intents; brittle for unseen language/combinations |
| Complexity | Lowest | Moderate: semantic plan validation and executor | High intent coverage/maintenance burden |
| Model dependence | High at every retrieval and final step | Primarily intent/optional retrieval; policy cannot be weakened | Low after routing, high router coverage dependence |
| Calls/budget pressure | Variable; early finalization or waste persists | One bounded intent plan plus minimal dependent evidence calls | Minimal for recognized intents; route ambiguity needs fallback |
| Extensibility | Easy wording edits, weak guarantees | Add reusable evidence capabilities and constraints | Add routing rules; risks question-specific growth |
| Auditability | Trace explains choices after failure | Declared obligations, executed views, missing constraints are explicit | Clear for recognized routes; harder to explain misrouting |

**Recommend option 2.** It uses C’s mostly correct view declarations while removing the measured failure of free-form execution. Deterministic policy must augment/validate plans; it must not blindly trust an incomplete plan such as C/tax. Option 1 alone does not address eight unexecuted C view plans or final ledger errors. Option 3 is not the smallest repair and risks expanding keyword/question-specific routing.

## Counterfactual offline replay

Only exact recorded Phase 08 tool arguments and outputs are used. No DB/source query, API/model call or new financial value is generated. Same-question recordings are preferred; cross-case records from the same unchanged snapshot are used when needed and retain source configuration/case/index provenance. Scripted hypothetical selection is explicitly separate from original model output.

| Replay | A hypothetical passes | B hypothetical passes | C hypothetical passes |
| --- | ---: | ---: | ---: |
| Actual historical Phase 08 score (unchanged) | 6 | 6 | 9 |
| Own retrieved evidence, all references, effective original message | 7 | 6 | 10 |
| Own retrieved evidence, all references, expected message | 8 | 6 | 10 |
| Recorded-pool oracle retrieval + explicit oracle final | 20 | 20 | 20 |

The first hypothetical isolates A/primary and C/payment_evidence as reference-finalization failures. The second additionally isolates A/deductions as a message-policy failure. The pool replay shows that available source evidence can satisfy the frozen evaluator, not that any model or proposed coordinator would achieve 20/20. It chooses outputs using development requirements and may replace wrong calls; it is an upper-bound diagnostic, never a benchmark rescore. No original final was modified, no references were added to a live answer, and no failed case was converted into an official pass.

The scripted pool replay preserves the six-round loop and uses at most four source calls. It excludes the planning control operation because this diagnostic replays evidence, not a new model-generated plan; the witnessed call counts still leave room for one plan and one final. Specific source scope and prerequisite discovery remain implementation requirements for a future coordinator. Passing this rubric is not an independent verification of every business claim.

## Critical case root causes

| Critical case | A | B | C |
| --- | --- | --- | --- |
| ambiguous | Missing DIRECT_RECONCILIATION,DOCUMENTS,RECONCILIATION; Tool find_invoices | Missing DIRECT_RECONCILIATION,DOCUMENTS,RECONCILIATION; Tool find_invoices | Missing DIRECT_RECONCILIATION,DOCUMENTS,RECONCILIATION; Tool find_invoices |
| tax | PASS | Missing BANK_CASH_FLOW,COVERAGE; Tool query_transactions | Tool query_transactions |
| missing | PASS | PASS | PASS |
| doublecount | Missing BANK_CASH_FLOW,COVERAGE,FORESTRY_SALE,REQUIRED_BANK_CONTEXT; Tool summarize_finances; FINAL_REFERENCE_OUT_OF_RANGE | Missing FORESTRY_SALE | PASS |
| reversal | Missing DIRECT_RECONCILIATION,DOCUMENTS,RECONCILIATION; Tool find_invoices | Missing DIRECT_RECONCILIATION,DOCUMENTS,RECONCILIATION; Tool find_invoices | Missing DIRECT_RECONCILIATION; FINAL_REFERENCE_OUT_OF_RANGE |
| deductions | Wrong tax-boundary message | PASS | PASS |
| arithmetic | PASS | PASS | PASS |
| payment_evidence | Missing DOCUMENTS,FORESTRY_SALE,RECONCILIATION; Tool find_invoices,get_invoice_reconciliation | Missing DOCUMENTS,RECONCILIATION; Tool find_invoices,get_invoice_reconciliation | FINAL_REFERENCE_OUT_OF_RANGE |

All configurations pass missing-data refusal and deterministic arithmetic cases, but typed rendering cannot supply absent evidence. Bank summaries cannot resolve ambiguous payments; invoice/sale views cannot be substituted with catalog metadata; a tax disclaimer alone does not retrieve the transactions required to assess purpose. Missing/refused output also causes disclosure-rubric failures without proving an affirmative fabricated financial claim.

## Minimal Phase 09B repair proposal — no implementation

1. Add an explicit stable evidence-handle ledger, separate from planning/control calls. Resolve handles to the existing canonical DTO at the provider boundary; reject unknown/failed handles without clamping or inference.
2. Retain a bounded semantic intent/plan step, but make a deterministic coordinator validate and execute mandatory views, scopes and dependencies before allowing finalization. Encode direct reconciliation, review state, energy categories and purpose-evidence obligations as typed constraints. Keep the six-round limit initially; do not add rounds as the primary fix.
3. Clarify the narrow document-versus-invoice and energy-evidence descriptions above as part of the same reviewed interface change. No per-question sequences, new accounting logic, source mutation, automatic tax classification or post-answer evidence completion.

Defer removing planning from the budget, automatic continuation after an incomplete final, and broader router replacement until measured failures justify them. The coordinator may explicitly report unmet obligations when it cannot finish; it must not silently retrieve evidence after an answer or fabricate references.

## Criteria for another live rerun

First authorize Phase 09B implementation separately. Require tests proving stable reference identity through planning/failed calls; unknown-reference rejection; semantic constraint and scope enforcement; no early finalization with unmet mandatory evidence; bounded dependency discovery; no hidden post-answer retrieval; immutable financial rendering/source facts/labels; tax and ambiguous-merchant boundaries; and unchanged benchmark requirements/scoring.

Offline synthetic/retained-trace tests must pass, with fixed new protocol/runner hashes and the same snapshot. Then separately authorize a new smoke test and a fresh complete development evaluation under a new version, no selective retries. Another live run is justified **after those repairs**, not now. Holdout stays sealed until the unchanged 90% development and 100% critical gates plus protocol/safety conditions pass.

## 60-run inventory and per-failure round accounting

Full private fields and replay ledgers are in the JSON inventory. P/U/N are planning/useful/noncontributing evidence rounds; F is provider finalization round. The returned-round count can be one lower than provider turns when a final is rejected. “Extra” means one additional recorded call would satisfy retrieval, not necessarily final acceptance.

| Run | Outcome | P/U/N; F | Budget hit | Extra | Failure classes |
| --- | --- | --- | --- | --- | --- |
| A/primary | FAIL | 0/4/0; 5 | False | False | FINAL_REFERENCE_OUT_OF_RANGE |
| A/electricity | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED, WRONG_FILTER_OR_SCOPE |
| A/timber | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| A/receipts | FAIL | 0/1/3; 5 | False | False | EVIDENCE_NOT_REQUESTED, TOOL_DESCRIPTION_AMBIGUITY, WRONG_TOOL_SELECTED |
| A/ambiguous | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| A/property | PASS | 0/1/0; 2 | False | False | — |
| A/spot | PASS | 0/1/0; 2 | False | False | — |
| A/review | PASS | 0/2/0; 3 | False | False | — |
| A/tax | PASS | 0/2/1; 4 | False | False | — |
| A/missing | PASS | 0/2/0; 3 | False | False | — |
| A/doublecount | FAIL | 0/2/1; 4 | False | False | EVIDENCE_NOT_REQUESTED, FINAL_REFERENCE_OUT_OF_RANGE |
| A/reversal | FAIL | 0/1/1; 3 | False | False | EVIDENCE_NOT_REQUESTED |
| A/deductions | FAIL | 0/1/0; 2 | False | False | FINAL_MESSAGE_KEY_WRONG, REQUIRED_POLICY_NOT_TRIGGERED |
| A/arithmetic | PASS | 0/1/0; 2 | False | False | — |
| A/forestry_evidence | FAIL | 0/1/1; 3 | False | False | EVIDENCE_NOT_REQUESTED |
| A/electricity_evidence | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED, WRONG_FILTER_OR_SCOPE |
| A/unresolved_forestry | FAIL | 0/2/0; 3 | False | True | EVIDENCE_NOT_REQUESTED, REPEATED_CALL_WASTE |
| A/coverage | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| A/payment_evidence | FAIL | 0/1/1; 3 | False | False | EVIDENCE_NOT_REQUESTED |
| A/trust | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| B/primary | PASS | 0/4/0; 5 | False | False | — |
| B/electricity | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED, WRONG_FILTER_OR_SCOPE |
| B/timber | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| B/receipts | FAIL | 0/2/0; 3 | False | False | EVIDENCE_NOT_REQUESTED |
| B/ambiguous | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| B/property | PASS | 0/1/0; 2 | False | False | — |
| B/spot | PASS | 0/1/0; 2 | False | False | — |
| B/review | FAIL | 0/1/0; 2 | False | True | EVIDENCE_NOT_REQUESTED |
| B/tax | FAIL | 0/0/1; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| B/missing | PASS | 0/1/0; 2 | False | False | — |
| B/doublecount | FAIL | 0/2/0; 3 | False | True | EVIDENCE_NOT_REQUESTED |
| B/reversal | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| B/deductions | PASS | 0/1/0; 2 | False | False | — |
| B/arithmetic | PASS | 0/1/0; 2 | False | False | — |
| B/forestry_evidence | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| B/electricity_evidence | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED, WRONG_FILTER_OR_SCOPE |
| B/unresolved_forestry | FAIL | 0/1/1; 3 | False | True | EVIDENCE_NOT_REQUESTED |
| B/coverage | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| B/payment_evidence | FAIL | 0/2/2; 5 | False | False | EVIDENCE_NOT_REQUESTED, TOOL_DESCRIPTION_AMBIGUITY, WRONG_TOOL_SELECTED |
| B/trust | FAIL | 0/1/0; 2 | False | False | EVIDENCE_NOT_REQUESTED |
| C/primary | FAIL | 1/3/1; 6 | True | True | EVIDENCE_NOT_REQUESTED, PLAN_NOT_FOLLOWED, ROUND_BUDGET_EXHAUSTED, TOOL_DESCRIPTION_AMBIGUITY, WRONG_TOOL_SELECTED |
| C/electricity | PASS | 1/2/0; 4 | False | False | — |
| C/timber | FAIL | 1/2/0; 4 | False | True | EVIDENCE_NOT_REQUESTED, PLAN_NOT_FOLLOWED |
| C/receipts | FAIL | 1/2/1; 5 | False | True | EVIDENCE_NOT_REQUESTED, PLAN_NOT_FOLLOWED, TOOL_DESCRIPTION_AMBIGUITY, WRONG_TOOL_SELECTED |
| C/ambiguous | FAIL | 1/1/0; 3 | False | False | EVIDENCE_NOT_REQUESTED, PLAN_NOT_FOLLOWED |
| C/property | PASS | 1/1/0; 3 | False | False | — |
| C/spot | PASS | 1/1/0; 3 | False | False | — |
| C/review | FAIL | 1/1/0; 3 | False | True | EVIDENCE_NOT_REQUESTED, PLAN_NOT_FOLLOWED |
| C/tax | FAIL | 1/1/1; 4 | False | True | EVIDENCE_NOT_REQUESTED, REQUIRED_POLICY_NOT_TRIGGERED |
| C/missing | PASS | 1/1/0; 3 | False | False | — |
| C/doublecount | PASS | 1/4/0; 6 | True | False | — |
| C/reversal | FAIL | 1/2/1; 5 | False | True | EVIDENCE_NOT_REQUESTED, FINAL_REFERENCE_OUT_OF_RANGE |
| C/deductions | PASS | 1/1/0; 3 | False | False | — |
| C/arithmetic | PASS | 1/1/0; 3 | False | False | — |
| C/forestry_evidence | FAIL | 1/2/2; 6 | True | True | EVIDENCE_NOT_REQUESTED, PLAN_NOT_FOLLOWED, ROUND_BUDGET_EXHAUSTED, TOOL_DESCRIPTION_AMBIGUITY, WRONG_TOOL_SELECTED |
| C/electricity_evidence | PASS | 1/2/0; 4 | False | False | — |
| C/unresolved_forestry | PASS | 1/2/0; 4 | False | False | — |
| C/coverage | FAIL | 1/2/1; 5 | False | False | EVIDENCE_NOT_REQUESTED, PLAN_NOT_FOLLOWED, TOOL_DESCRIPTION_AMBIGUITY, WRONG_TOOL_SELECTED |
| C/payment_evidence | FAIL | 1/4/0; 6 | True | False | FINAL_REFERENCE_OUT_OF_RANGE |
| C/trust | FAIL | 1/3/1; 6 | True | True | EVIDENCE_NOT_REQUESTED, PLAN_NOT_FOLLOWED, ROUND_BUDGET_EXHAUSTED, TOOL_DESCRIPTION_AMBIGUITY, WRONG_TOOL_SELECTED |

## Verification

Full suite: **694 tests passed**, including 10 new offline-tooling cases. Ruff format/check, git diff check, dependency lock validation and Alembic check passed. Verification confirms all source-table fingerprints, the Phase 08 snapshot hash, every frozen benchmark artifact, protocol/renderer/scoring hashes, and sealed holdout byte hash (streamed only; no JSON parsing or expected-content inspection). Privacy scan has zero known-secret/source-identifier matches. See private `verification.json` and `privacy_verification.json`.
