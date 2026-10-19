# Phase 09F — explicit finalization and context scope

**Implemented and verified offline; pilot status remains NOT_READY.** No live model was called, no API tokens were spent, and no benchmark score was rewritten. This is Option C: explicit required handles plus rejection, without automatic reference attachment.

The new versioned entry point is `tapio.agent.scoped.run_scoped_agent`, paired with `tapio.agent.providers.openai_scoped.OpenAIScopedModel`. Historical Phase 09B–09E entry points, provider adapters, policies, rubrics and artifacts remain unchanged. The new coordinator reuses the existing deterministic query executor, ledger resolver and trusted financial renderer. No tools, source tables, human labels, retrieval engine, frontend or autonomy were added.

## Context semantics and validation

`ScopedPlan` replaces the provider-facing `required_contexts` field with:

| Scope | Selected contexts | Execution |
|---|---|---|
| ALL | Must be empty | One unfiltered deterministic bank aggregate; unfiltered context-dependent discovery. |
| SELECTED | One or more unique stored contexts | Apply those exact context filters; never simulate ALL by enumeration. |
| UNSPECIFIED | Must be empty | Discovery without assuming or assigning business context. |

Stored contexts remain PERSONAL, PROPERTY, FORESTRY and UNKNOWN. Contradictory scope/list combinations, duplicates and invalid context values reject. UNKNOWN is never coerced into UNSPECIFIED. A small internal compatibility property maps explicit scope to the existing executor's context arguments; it is not exposed as the old ambiguous plan field.

For merchant-specific tax discovery, UNSPECIFIED is allowed. A planner's unsupported SELECTED FORESTRY, PROPERTY or UNKNOWN still rejects. Retrieved human-confirmed labels remain authoritative; tax treatment remains separate. Existing tax finalization forces the tax-refusal template, and the finalization contract lists only `tax_review_required` for tax-boundary evidence.

Cross-domain/property-and-forestry overviews and broad financial summaries receive an explicit ALL policy scope. This maps directly to `summarize_finances(business_context=null)`, retaining separate context groupings, not four filtered aggregates. Raw model scope, policy changes and effective scope are separately retained.

## Review coverage safety

General review/unresolved/incomplete requests deterministically require REVIEW_COVERAGE and ALL scope unless the user supplies a specific context. The coordinator also rejects a context-restricted mandatory review query for a general-review request, so a caller cannot silently bypass the policy by supplying a restrictive query.

The original review regression now retrieves **all 95 unresolved rows**, with 95 unique transaction IDs, through unfiltered NEEDS_REVIEW discovery and existing date-partition pagination. These rows have no human-confirmed review label; they are not relabeled UNKNOWN. The old selected-context predicates excluded them because the joined review columns were null.

Explicit context-specific review requests remain selected as requested. For example, a FORESTRY review query does not silently assign the potential purpose of unreviewed rows to forestry. Its broader unknown-purpose limitation remains a product consideration. General queries, including broad coverage/financial summaries with review requirements, now retain the unresolved population.

## Retrieval and final-reference requirements

Each policy-owned `ViewRequirement` has independent `retrieval_required` and `final_reference_required` booleans. Every current mandatory view retains both flags as true; no frozen requirement or final-required evidence was removed. Per-result envelopes and handle metadata retain the flags. A synthetic test demonstrates retrieval-required/final-reference-not-required behavior without enabling that policy relaxation in production.

`required_final_handles` is derived from successful, nontruncated results whose policy requires a final reference. It is separate from optional evidence. Failed/truncated results cannot acquire usable handles. Empty successful results remain evidence and retain their requirements.

The compact finalization contract supplies:

- Available evidence handles, views and requirement flags.
- The exact `required_final_handles` list.
- Allowed message keys.
- An explicit instruction requiring every listed handle while permitting additional valid evidence.

The contract contains no ledger indexes or financial conclusions. Source results are supplied once when retrieved; after optional retrieval, only new results and an updated compact contract are appended. The model must return its own reference list. Missing, unknown, duplicate and failed-result handles still reject. Nothing appends omitted references or manufactures provenance.

Audit/response data separately retain MODEL_PLAN, POLICY_ADDITIONS, EFFECTIVE_PLAN, VIEW_REQUIREMENTS and REQUIRED_FINAL_HANDLES. The schema accepts only the explicit new scope representation; old recorded plans are migrated only in the clearly labeled offline replay, not silently in the provider adapter.

## Five Phase 09D regressions

| Case | Offline result | Limit |
|---|---|---|
| receipts | REFERENCE_OMISSION_PREVENTABLE: previously omitted bank/coverage and empty sale results are explicitly listed as required. | A new model can still omit a listed handle; validator rejects. |
| ambiguous | REFERENCE_OMISSION_PREVENTABLE: required PAID and UNMATCHED direct reconciliation results remain listed. AMBIGUOUS evidence and reversal candidates remain unchanged. | No claim of new model success. |
| review | Reference dimension: previously omitted PAID reconciliation is explicitly required. Semantic dimension: all 95 unresolved rows included without restrictive context predicates. | Both dimensions checked; final selection remains model-dependent. |
| tax | POLICY_REJECTION_STRUCTURALLY_PREVENTED for the explicitly requested UNSPECIFIED discovery hypothesis. Relevant truncated-name candidate evidence carries existing human-confirmed context; tax refusal remains required. | Original SELECTED UNKNOWN still rejects. No fabricated model plan/final or inferred tax decision. |
| primary | SCOPE_REPRESENTATION_STRUCTURALLY_PREVENTED: effective ALL maps to one actual unfiltered bank aggregate. | Final reference selection and subsequent model behavior still require live evaluation. |

The replay preserves original raw plans alongside deterministic migration metadata. For tax only, the user-requested UNSPECIFIED hypothesis is explicitly recorded as a scope change; it is not described as semantically equivalent to the old UNKNOWN filter. No model final was fabricated or benchmark pass awarded.

## Twenty-case structural replay

All **20/20** retained development intents completed mandatory retrieval and received explicit final-handle contracts using local read-only tools. There were **zero model calls and zero API tokens**.

Effective retrieval scope changed for **primary, review, tax, coverage and trust**. Other apparent differences caused only by query order are not classified as scope changes; comparison uses multisets of exact tool arguments. The initial comparison artifact is retained privately alongside the refined report.

The primary ALL representation and the tax UNSPECIFIED hypothesis are classified STRUCTURALLY_PREVENTED for their specific prior scope failure modes. Receipts, ambiguous and review are REFERENCE_OMISSION_PREVENTABLE but STILL_MODEL_DEPENDENT for final selection. All 20 cases remain model-dependent for a future final answer; an explicit requirement cannot prove that a model will obey it. This is structural replay, not a 20/20 benchmark score.

The unchanged 24-source-call bound and six-model-round maximum remain. Source queries, calculations, tax/ambiguity protections and trusted rendering retain their existing behavior. Replay artifacts include every source trace, policy addition, handle map, review count and regression assertion under `data/interim/phase09f/structural_replay.json`.

## Tests, integrity and frozen configuration

Added **31 synthetic tests**, preserving all existing **748 tests**, for a total of **779**. They cover all three scopes, UNKNOWN, contradictory scope/list combinations, tax discovery and refusal, merchant-context rejection, primary ALL aggregation, review NULL-row inclusion and pagination, independent requirement flags, required-handle derivation, extra optional references, omission/duplicate/unknown/failed rejection, no attachment, three omission regressions, ambiguity preservation, exact trusted rendering, source-object immutability, compact payload, new provider schema via fake transport, and unchanged round limit.

Final verification includes full pytest, Ruff format/check, diff check, dependency lock, Alembic, all source/human-review fingerprints, protected electricity files, historical Phase 06–09 artifacts, Phase 08 data snapshot, holdout byte hash and privacy/secret scan. Holdout contents were neither decoded nor exposed. The local database runtime needed restarting during final verification; affected checks were rerun against the existing database without source mutations.

The next-run configuration descriptor is `data/interim/phase09f/next_live_configuration.json`, identifier **PHASE09F_SCOPED_C_V1**. It freezes the evidence-plan/context schemas, evidence policy, new and inherited coordinator, evidence-handle contract, final schema, adapter/implementation dependencies, registry, development dataset, unchanged data snapshot, source fingerprints and exact model settings. It does not overwrite any earlier configuration.

Configuration SHA-256: `239e45f619acfeda49588a034bfa3f6a208112235b49da48a53a068cda049b09`.

## Exact criteria for another live run

One separately authorized coordinated C development-only rerun is technically justified after these offline checks pass. It must explicitly use the new scoped entry point/provider and frozen descriptor, the same `gpt-5.4-mini-2026-03-17` and settings, unchanged six-round limit, 20 frozen development questions and existing scoring. Abort if the model is unavailable or frozen inputs differ. Do not retry selected failures, tune mid-run, rerun A/B, or open holdout. Historical scores stay unchanged.

No live run is authorized or performed by this phase. NOT_READY remains until a separately evaluated run meets the existing acceptance gates.
