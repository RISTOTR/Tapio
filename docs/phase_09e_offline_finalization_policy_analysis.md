# Phase 09E — offline finalization and policy analysis

**NOT_READY remains unchanged.** Phase 09D remains **15/20 evidence-complete and 6/8 critical passed**. This analysis made **zero model calls and spent zero API tokens**. It inspected retained development traces and performed local read-only counterfactual queries. No orchestration, prompts, schema, scoring, thresholds, labels or source data were changed. Holdout remains sealed.

The smallest justified proposal is **Option C: provide an explicit required-final-handle list and retain fail-closed validation**, plus an explicit distinction between all-context, selected-context and unspecified discovery scope. Do not automatically attach references or weaken mandatory evidence requirements. These are proposals only.

## 1. Three final-reference omission traces

All three final requests contained every retrieved evidence envelope. Each envelope had `evidence_handle`, `view`, `views` and the complete typed result. The payload contained `trust`, `mandatory_plan` and `evidence`; it had **no explicit required-final-handles list or per-handle final-required flag**.

The base system policy said “Select relevant results from every required evidence view”; it also expressly prohibited dropping the bank summary for document evidence. The coordinated extension said “Select all mandatory evidence handles.” The finish-function description said “Include all mandatory handles.” Thus the instructions combined view-level relevance selection with an all-handle requirement. They did not say “most relevant,” but the older relevance wording remains a plausible source of ambiguity. The inherited five-tool-call instruction also remains present alongside deterministic retrieval; there is no evidence that it caused these omissions.

| Case | Raw plan | Effective views | Retrieved handles | Raw final references | Omitted |
|---|---|---|---|---|---|
| receipts | receipts; FORESTRY; DOCUMENTS, INVOICES, RECONCILIATION, COVERAGE; coverage/reconciliation true | BANK_CASH_FLOW, COVERAGE, DOCUMENTS, FORESTRY_SALE, INVOICES, RECONCILIATION | E0–E6 | E1, E3, E4, E5, E6 | E0, E2 |
| ambiguous | reconciliation; PROPERTY, FORESTRY, PERSONAL, UNKNOWN; BANK_CASH_FLOW, RECONCILIATION, COVERAGE; coverage/reconciliation true | BANK_CASH_FLOW, COVERAGE, INVOICES, RECONCILIATION | E0–E7 | E5, E4, E0, E1, E2, E3 | E6, E7 |
| review | review; PROPERTY, FORESTRY, PERSONAL, UNKNOWN; BANK_CASH_FLOW, RECONCILIATION, REVIEW_COVERAGE; coverage/reconciliation true | BANK_CASH_FLOW, COVERAGE, INVOICES, RECONCILIATION, REVIEW_COVERAGE | E0–E11 | E0, E1, E2, E3, E4, E5, E7, E8, E9, E10, E11 | E6 |

All three raw finals used `message_key="results"`, with references shaped as `{"evidence_handle":"E…"}`. All referenced handles existed, were unique and represented successful results. Finalization returned `EVIDENCE_INCOMPLETE` with `MANDATORY_REFERENCE_OMITTED`, empty selected results and an empty answer. There was no rendered financial result. The evaluator then reported missing selected evidence and downstream policy/provenance failures. The primary cause was the rejected reference set, not a failed source query.

The complete untouched native finals, plans, handle maps, requests and omitted-result contents are in private `data/interim/phase09e/finalization_policy_analysis.json` and the preserved Phase 09D artifacts.

**What the trace supports about intent:**

- A: the evidence was delivered; whether the model consciously knew and chose to exclude it cannot be established.
- B: relevance-oriented wording exists, but explicit all-mandatory wording also exists. Causation is unproven.
- C: supported narrowly—there was no concrete list identifying exactly which handles must appear. There was a general instruction requiring all mandatory handles.
- D: no evidence of malformed-handle semantics: all emitted handles were valid. Understanding the complete mandatory set is unproven.
- E: the omission pattern is consistent with relevance/redundancy selection: non-ambiguous reconciliation results were omitted in ambiguous/review; an empty sale result was omitted in receipts. This is a plausible explanation, not a finding about model intent.

## 2. Required retrieval versus required final reference

Current code conflates these at the **result-handle level**: every successful nontruncated mandatory retrieval adds its handle to `mandatory_handles`; finalization requires that entire set. A typed view can therefore require several final handles, including different contexts, invoices, empty results and overlapping invoice/direct-reconciliation representations.

A future contract should distinguish `retrieval_required` from `final_reference_required`, but **no removal from the current final-required set is proposed for this repair**. Retrieval establishes what can safely be concluded; final references establish the evidence and limitations actually included in the trusted response. Reference necessity is claim- and scope-dependent, not just a tool-name property.

| Semantic view | Recommended default when required for the answer | Reason |
|---|---|---|
| BANK_CASH_FLOW | BOTH | Authoritative cash/context totals and exclusions must support financial statements. |
| COVERAGE | BOTH | Missing periods and source limitations qualify the answer, even without a positive amount. |
| INVOICES | BOTH | Structured source values, human-label links and payment status must remain distinct from bank cash. |
| RECONCILIATION | BOTH | Payment/ambiguity statements require their actual evidence; no candidate debit may be silently selected. |
| FORESTRY_SALE | BOTH | Sale value is distinct from bank income; empty period discovery is also a limitation. |
| REVIEW_COVERAGE | BOTH | Unresolved classification conclusions need evidence, including an appropriately scoped empty result. |
| GRID_SCOPE | BOTH | Supplier-only evidence cannot support an electricity total including distribution. |
| SAVED_ELECTRICITY_COMPARISON | BOTH | The frozen calculation and its limited scenario period qualify any savings statement. |
| TAX_CONTEXT | BOTH | Human-confirmed context is evidence, while tax deductibility remains undetermined. |
| DOCUMENTS | RETRIEVAL_REQUIRED for a discovery catalog; BOTH for document evidence relied upon | Catalog discovery is not itself proof that a receipt supports a classified expense. |

Implementation names are `ELECTRICITY_SAVED_COMPARISON` and `TAX_BOUNDARY_CONTEXT`. No view should default to FINAL_REFERENCE_REQUIRED without retrieval: references must resolve to successful evidence. BOTH does not mean every overlapping discovery result is intrinsically needed for every future product answer; that narrower design requires separate evidence rules, not a post-hoc exception for failed cases.

## 3. Ambiguous case

E4 was the invoice list, containing nested reconciliation states for all three invoices. E5 was direct reconciliation for the **€588.07 AMBIGUOUS** invoice, including candidate cash flows; both were selected. E6 and E7 were **direct reconciliation for different invoices**, respectively PAID and UNMATCHED. They were not an omitted invoice-list handle, an aggregate, or separate candidate handles for the €588.07 target. Candidate evidence lives inside the selected ambiguous reconciliation result.

The renderer does not structurally require every direct lookup and can render an arbitrary successful subset. The frozen legacy requirements demand invoice evidence and at least one direct reconciliation result for this question; they do not independently enumerate every invoice ID. The stronger current coordinator contract additionally requires **every mandatory result handle**, hence E6 and E7. Both contracts remain in force for Phase 09D; passing the legacy view checks cannot excuse violating the coordinator gate.

PAID may look irrelevant to “ambiguous,” and UNMATCHED is a different unresolved state; that pattern explains a possible selection strategy without proving intent. No requirement is weakened. The counterfactual keeps the original message key and all source values; the exact reversal remains unestablished and candidate links remain preserved.

## 4. Review case

The exact question was “Which transactions still need human review?” Frozen inferred requirements are BANK_CASH_FLOW, COVERAGE and REVIEW, with a NEEDS_REVIEW query. **They do not require reconciliation.** The raw model plan explicitly included RECONCILIATION and set `needs_reconciliation=true`. Policy preserved that declaration; dependency expansion added invoice discovery and then direct lookup of every invoice. The omitted E6 was the PAID invoice's direct reconciliation result.

For an ideal product, REVIEW_COVERAGE with correctly scoped transaction/context evidence can answer unresolved-classification questions. Reconciliation is appropriate when unresolved items have linked payment ambiguity or the question asks about payment review. Reconciliation is not universally required by this question. The excess requirement originated in the model plan, not in the frozen review benchmark. The current runtime contract nevertheless makes the declared retrievals mandatory to reference; this analysis does not remove them.

**Additional semantic gap found offline:** the four recorded NEEDS_REVIEW queries—FORESTRY, PERSONAL, PROPERTY and UNKNOWN—each returned zero rows. The same-period unfiltered tax counterfactual retrieved **95 UNREVIEWED rows** among 170 transactions. In `ToolQueries.transactions`, context filters compare against an outer-joined human-confirmed context column. Unreviewed transactions have no joined review row and therefore fail every named-context predicate, including UNKNOWN. Four named filters are not equivalent to unfiltered discovery.

Consequently, the reference-completed review answer passes the **unchanged frozen evaluator**, but that is not proof of semantic review completeness. The evaluator checks the presence of a successful NEEDS_REVIEW query, not whether it includes the 95 unreviewed rows. Do not rewrite its score; preserve this finding as a scope-safety requirement for a future repair.

## 5. Receipts case

The omitted E0 was the FORESTRY bank summary and coverage metadata. It establishes actual cash/context evidence using human labels, and must not be replaced by invoice value. E2 was **an empty period-specific forestry-sale result**, not a receipt or reconciliation result. Under the frozen forestry requirements, sale evidence is independently mandatory; emptiness documents the absence of matching imported sale evidence, not zero forestry income.

The selected E1 was a six-item document catalog. E3 was a three-invoice list with confirmed/candidate human-context links and nested reconciliation. E4–E6 were direct reconciliation results. Catalog presence does not by itself prove receipt support or business purpose. Invoice/document evidence, bank-context cross-check and reconciliation serve separate roles.

For CURRENT evaluation, **A (documents alone) is insufficient; B (documents plus bank/context) is still insufficient; C must also retain B's bank/context cross-check**, and the frozen rule additionally requires sale evidence and coverage. This is stricter than an ideal narrowly scoped receipt-supported-expense question. Future product behavior should distinguish documentation of an expense, human-confirmed purpose and proof of payment; it need not routinely retrieve unrelated sale evidence. That is a separately versioned policy question, not grounds to relax this benchmark.

## 6. Tax-context rejection and discovery counterfactual

Question: “Can I deduct the Oikea Konekauppa purchases?” Raw intent was tax; views DOCUMENTS, INVOICES, BANK_CASH_FLOW and TAX_BOUNDARY_CONTEXT; coverage and tax flags true; reconciliation false; `required_contexts=["UNKNOWN"]`.

`enforce_policy` rejects any nonempty context list for an ambiguous merchant when the question supplies no explicit context. It raised `AMBIGUOUS_MERCHANT_CONTEXT_REQUIRES_EXPLICIT_SCOPE` before retrieval. The guard did not reject tax intent; it rejected an unsupported filter. UNKNOWN is not a safe spelling of “we have not discovered context yet.” It is an actual context-filter value. The validator is appropriately strict about unsupported restriction, but the schema lacks a clear discovery-scope representation.

Only the recorded context restriction was varied; question type, views and flags were preserved, then existing deterministic policy was applied. No new model plan or final was invented.

| Hypothesis | Existing coordinator behavior | Diagnostic classification |
|---|---|---|
| UNSPECIFIED, represented by the current empty-context list | 16 local source calls; all effective views complete; 170 transaction rows across nontruncated date partitions | POLICY_REJECTION_ONLY for required-evidence discovery |
| Allow UNKNOWN as a filter | 4 local source calls; view execution complete but transaction evidence empty | ADDITIONAL_FAILURE_REMAINS |

Unfiltered discovery includes one textual candidate with a truncated bank merchant spelling, and its existing **human-confirmed FORESTRY / MAINTENANCE** labels. Exact full-name matching found zero rows; a bounded prefix inspection found the truncated-name candidate. This is discovery metadata, not an inferred identity, new context assignment or tax conclusion. Human labels remain authoritative. UNKNOWN-only discovery excludes that evidence.

There was no tax final in Phase 09D, so **no end-to-end tax pass can be claimed**. The coordinator's existing tax template rule remains applicable, but this counterfactual tests retrieval, not a hypothetical model's final references. Broad discovery also has privacy/scale costs: 170 rows and 16 calls versus a future targeted merchant query. The current schema lacks an explicit merchant discovery constraint; do not silently invent one or guess a business context.

## 7. Primary scope and schema analysis

Raw planned contexts: PROPERTY and FORESTRY. Policy added **no contexts**; effective order was FORESTRY, PROPERTY. The coordinator issued two filtered bank summaries. PERSONAL and UNKNOWN were omitted from aggregate totals, although excluded-unresolved counts disclose some limitation. Invoice and document discovery remained period-wide. The exact question asks for property/forestry costs and income plus what still needs review.

A narrow reading emphasizes PROPERTY+FORESTRY, while the review qualification needs broader unresolved visibility. For CURRENT evaluation, the ground truth is explicit: the frozen primary rubric requires one unfiltered all-context bank aggregate. `FinanceQuery.business_context` already documents null as ALL and explicitly recommends null for a property-and-forestry overview. The plan schema, however, offers only a list of named contexts; policy unions inferred PROPERTY/FORESTRY into it. A model cannot preserve an intentional empty-list all-context choice through that policy for this question.

The counterfactual used the existing `summarize_finances` with `business_context=null`, retaining categories=null, the same period, all non-bank results and the same final message. It replaced only the two bank summaries and corresponding trace calls. The unchanged renderer produced 522 words; all frozen checks passed: **SCOPE_REPRESENTATION_ONLY**. This is a deterministic aggregate-scope replay, not a new model-final success.

Recommend explicit fields:

- `context_scope`: ALL, SELECTED or UNSPECIFIED.
- `selected_contexts`: PROPERTY, FORESTRY, PERSONAL, UNKNOWN; nonempty only for SELECTED.
- ALL: unfiltered aggregate/discovery, retaining human context groupings.
- UNSPECIFIED: intent provides no justified restriction; discovery remains unfiltered until evidence supplies context, without assigning it to transactions.
- UNKNOWN: a real selected category, never synonymous with ALL, UNSPECIFIED or absence of a human review row.

No-context-needed is determined by whether the selected views use transaction/context evidence; it should not be overloaded onto `[]`. Avoid putting ALL alongside named labels in one set: combinations such as ALL+FORESTRY create another ambiguity. Policy should express required coverage separately from focus contexts and must not accidentally turn ALL into SELECTED. The review NULL-row exclusion above must be tested explicitly.

## 8. Final-reference architecture and responsibility

| Option | Assessment |
|---|---|
| A: free model selection | Loses mandatory completeness unless separately checked; unsafe for the current contract. |
| B: model selection plus rejection | Current behavior protects correctness but fails three cases despite complete retrieval. |
| C: explicit REQUIRED_FINAL_HANDLES plus B | Smallest safe next step. Supplies a concrete set, preserves the model's raw selection, validator, frozen required set and auditable failures. |
| D: deterministic attachment | Can be valid for a redesigned code-owned answer assembly contract, but would change what final selection evaluates. Must not pretend appended handles were model-used or convert historical failures into model successes. |

D could improve mechanical provenance guarantees if raw model references and code-attached provenance were recorded separately. In this renderer, however, attaching a handle also renders its source facts; it is not merely adding a citation footnote. D would weaken evidence-selection evaluation under the present contract and could obscure omissions. It is **not recommended as the minimal repair**.

The model should decide intent, semantic evidence needs, optional retrieval and framing. Code should guarantee required evidence validity, deterministic arithmetic and preserved ambiguity. The measured failures show that recalling an implicit mandatory set is unreliable. Code should expose the exact set and validate it; under Option C the model still explicitly selects references, but remembering the set without structured help is no longer its task. No claim is made that C will eliminate omissions until independently tested.

## 9. Offline counterfactual results and limits

| Failure | Result | What changed diagnostically |
|---|---|---|
| receipts | REFERENCE_OMISSION_ONLY | Append only E0 and E2 to the retained final. |
| ambiguous | REFERENCE_OMISSION_ONLY | Append only E6 and E7. |
| review | REFERENCE_OMISSION_ONLY under frozen evaluator | Append only E6; the separate unreviewed-row scope gap remains. |
| tax | POLICY_REJECTION_ONLY with UNSPECIFIED discovery; ADDITIONAL_FAILURE_REMAINS with UNKNOWN filter | Replace only context restriction; no model final replay possible. |
| primary | SCOPE_REPRESENTATION_ONLY | Replace filtered bank summaries with one unfiltered existing aggregate. |

Reference replays preserve the original referenced-handle order and message key, append only existing omitted mandatory handles, and leave every retrieved source result and requirement unchanged. The original failures had empty rendered answers; a successful replay necessarily generates an answer through the unchanged renderer. There was **no manual answer-content edit, new financial claim, model prose or model call**. Literal preservation of the original empty rendered string would preclude testing successful rendering. These are diagnostic counterfactuals, not revised scores or predicted live performance.

## 10. Proposed minimum repair and next-run criteria

Propose, without implementing:

1. Expose the exact required-final-handle list and per-handle requirement status; retain existing rejection of omissions, unknown/duplicate/failed handles. Do not auto-attach references or change the required set.
2. Add explicit context scope and validation. Permit unspecified merchant/tax discovery without allowing merchant-based context assignment. Use an ALL aggregate for the frozen primary requirement and retain unreviewed NULL-label rows for broad review discovery.
3. Keep existing tools, source values, human labels, tax refusal, €588.07 ambiguity, renderer, scoring, thresholds and six-round budget. Existing tool execution can remain; scope construction and finalization input need the proposed changes. No new retrieval engine is justified.

Before another live development run: separately authorize implementation; verify these exact offline regressions; prove UNKNOWN remains distinct from unreviewed; test preservation of human-confirmed contexts and tax refusal; prove exact all-context scope; test final-required lists without reference manufacture; pass the full suite and integrity/privacy checks; freeze a new version and obtain separate authorization for one development-only run. Do not open holdout. An improved counterfactual score alone does not justify immediate paid rerunning.

## 11. Artifacts and verification

Analysis tooling only: `scripts/analyze_phase09e.py`; 14 synthetic tests in `apps/api/tests/test_phase09e_analysis.py`. Private structured output: `data/interim/phase09e/finalization_policy_analysis.json`. The initial local-query capture is preserved separately; postprocessing of retained rows distinguishes exact full-name matching from the truncated-name candidate and exposes the review scope limitation. No extra model or source query was needed for that enrichment.

Final verification is recorded privately in `data/interim/phase09e/verification.json`: full pytest (original 734 plus 14 analysis tests), Ruff format/check, diff check, dependency lock, Alembic, source/human-review fingerprints, Phase 08 snapshot, Phase 09D and prior artifact hashes, protected electricity files, holdout byte hash and privacy scan. The live runner, coordinator, provider, policy, schema, renderer and scorer remain unchanged. No repairs have been implemented.
