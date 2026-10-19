# Phase 09B mandatory evidence execution — 2026-10-16

Implemented a versioned, opt-in coordinated agent path. **NOT_READY remains unchanged.**
No live model calls, paid benchmark reruns, holdout-content inspection or source/label
changes occurred. Historical loops, provider adapters, scoring, datasets, renderer,
Phase 09 analysis and Phase 06/07/08 artifacts remain unchanged.

## Flow and integration

Previously: model plans → model manually requests each source → model selects ledger
positions → post-answer gate may reject incomplete evidence.

Now: model submits `MandatoryPlan` → semantic policy validates/augments requirements →
coordinator executes mandatory retrieval → successful evidence gets explicit handles →
model may request bounded optional evidence → coordinator validates handle selection and
mandatory completeness → existing trusted renderer.

Entry point: `run_coordinated_agent` in `tapio/agent/mandatory.py`, with
`OpenAIHandleModel` from `tapio/agent/providers/openai_handles.py` and
`coordinated_registry(coverage=...)`. Callers supply an explicit validated reporting
period. The historical `run_agent` and evaluation runners are intentionally not redirected;
a future smoke/benchmark harness must explicitly select this new version. The new provider
rejects use through the legacy index-based method.

The default and maximum model-decision budget is **six**. Mandatory retrieval is
coordinator work, not extra model decisions. A plan and a final can therefore take two
model decisions regardless of the intervening mandatory source calls. Optional requests
consume remaining model decisions; the last decision is constrained to finalization.
A separate deterministic source-call cap of 24 bounds mandatory plus optional retrieval.
This is not an increase in the model round budget.

## Typed plan and evidence views

`MandatoryPlan` retains the existing plan's question type, required views, required
contexts, coverage flag and tax flag, adding `needs_reconciliation`. Views are an enum;
there are no amount, arithmetic, financial conclusion or free-form evidence-ID fields.

| View | Deterministic retrieval |
| --- | --- |
| BANK_CASH_FLOW | `summarize_finances`, separately for each required context |
| COVERAGE | Bank summary with configured source/review coverage metadata |
| DOCUMENTS | `list_documents`: generic catalog metadata |
| INVOICES | `find_invoices`: structured invoice evidence |
| RECONCILIATION | Invoice discovery followed by `get_invoice_reconciliation` for discovered invoices |
| FORESTRY_SALE | `query_forestry_sales`, separate from bank income |
| REVIEW_COVERAGE | `query_transactions(review_state=NEEDS_REVIEW)` |
| ELECTRICITY_SAVED_COMPARISON | Existing frozen comparison reader, no recalculation |
| GRID_SCOPE | Bank cash query including both ELECTRICITY and GRID_DISTRIBUTION |
| TAX_BOUNDARY_CONTEXT | Human-labeled transaction evidence plus mandatory tax-boundary response |

Required views derive from the typed plan and general semantic policy, never a question-ID
lookup table. Existing conservative evidence requirements are retained. The existing
policy still requires saved energy evidence alongside electricity-spending evidence;
its limited modeled period is never substituted for actual bank cash flow.

Multiple contexts produce multiple filtered bank/review queries. A FORESTRY plan does
not silently become an all-context bank query. Invoice, catalog and sale tools have no
business-context input: they perform bounded period discovery and retain their own
source/context provenance. Their outputs are not relabeled as the requested bank context.
This distinction is an explicit limitation, not an inferred merchant classification.

Both a reconciliation view and `needs_reconciliation=true` require direct reconciliation
lookups. An invoice list or generic document result cannot satisfy that view. Empty
invoice discovery leaves direct reconciliation incomplete. Existing ambiguity, candidate
allocations and reversal limitations are preserved as returned; no settlement is inferred.

Truncated date-bounded pages are split into disjoint date intervals within the same
source-call cap. Only untruncated leaf responses receive usable handles; original leaf
results are retained unchanged. Combined item lists are used only for dependency discovery,
never to calculate or render new financial totals. An unsplittable/truncated page or cap
exhaustion produces incomplete evidence and explicit errors.

## Evidence handles and final contract

Every successful usable source result receives `E0`, `E1`, … with `view`, `views`, and
the unchanged typed result. Planning does not enter this ledger. Failed and truncated
calls do not create usable handles, though executed calls remain in the internal trace.

Native finals use `references: [{"evidence_handle": "E0"}, ...]`. The model never sees
`call_index`, ledger-length instructions or index arithmetic. Trusted coordinator code
maps handles to existing internal `ResultReference(call_index=...)` objects. Unknown,
duplicate and failed-result references reject; no integer wrapping, shifting, clamping
or fabricated references are available in this protocol.

The coordinator requires every mandatory result handle to be selected. Optional evidence
cannot replace a mandatory view, and a model cannot hide a mandatory result by omitting
its handle. Missing retrieval, tool errors or omitted mandatory handles yield
`EVIDENCE_INCOMPLETE`, with no supported financial answer. Tax questions force the existing
`tax_review_required` template. The financial renderer itself is unchanged.

Native provider responses and normalized handle DTOs are retained privately. Provider
schema validity is explicitly labeled as pending ledger validation. Coordinator final
validation separately retains the requested final, canonical references, handle map,
executed tool ledger and validation outcome under `data/interim/phase09b/`. Private
writes use the existing restricted-permission mechanism.

## Merchant and tax boundaries

Tokmanni, K-Rauta and Oikea Konekauppa remain ambiguous multi-context merchants. Human
labels are queried as authoritative; no source labels or tax records are written.
A model-supplied merchant-only context is rejected unless the question provides explicit
context. Explicit PERSONAL, PROPERTY and FORESTRY user scopes remain permitted.
Category, business context and tax treatment remain separate.

## Minimal description changes

Only the versioned registry appends clarifications to six existing descriptions:

- `list_documents`: catalog metadata, not structured invoices.
- `get_document_summary`: provenance, not payment/allocation evidence.
- `find_invoices`: structured invoices; direct reconciliation remains separate.
- `get_invoice_reconciliation`: direct payment/refund/reversal evidence is mandatory when requested.
- `get_saved_energy_comparison`: modeled limited-period evidence, not actual bank cash or full-year grid coverage.
- `query_transactions`: use NEEDS_REVIEW for unresolved classifications; merchants do not determine purpose/tax.

No tools are merged. Historical descriptions and evaluation configuration remain intact.

## Offline replay

Primary artifact: `data/interim/phase09b/mandatory_replay.json`.
All 60 records are classified, with no invented model plan or final:

| Classification | Count |
| --- | ---: |
| MANDATORY_EVIDENCE_COMPLETE | 16 |
| PLAN_ITSELF_INCOMPLETE | 4 |
| MANDATORY_EVIDENCE_RETRIEVAL_FAILED | 0 |
| NOT_REPLAYABLE | 40 |

A/B emitted no typed plans, so all 40 A/B records are NOT_REPLAYABLE under the requested
same-plan test. All 20 C plans were replayed through fresh local deterministic read-only
tools against the unchanged Phase 08 snapshot. Every declared retrieval succeeded.
These are **evidence-availability outcomes**, not model-finalization scores.

Legacy plan migration is explicit: the old DOCUMENTS enum meant invoice evidence and
maps to INVOICES only in the replay migrator. New DOCUMENTS retains its literal catalog
meaning. Old ENERGY and REVIEW map to the corresponding new semantic views. No financial
output or model decision is invented during migration.

Four retained plans omit explicit constraints required by the new contract:

| C case | Missing explicit view |
| --- | --- |
| primary | REVIEW_COVERAGE |
| electricity | GRID_SCOPE |
| electricity_evidence | GRID_SCOPE |
| trust | REVIEW_COVERAGE |

The two GRID_SCOPE omissions reflect constraints not representable in the older plan
schema; they are not evidence that a model knowingly ignored a formerly available field.
The primary/trust plans did not declare the required review view. No historical score is
changed because of these new-contract classifications.

A separately retained check in `policy_completion.json` executes the deterministic
policy additions used by the new runtime, without generating another model plan.
All four policy-augmented cases retrieve complete mandatory evidence (10, 2, 2 and 12
source calls respectively). Thus the new policy-plus-coordinator flow has local evidence
availability for all 20 retained C intents, while the primary same-plan classification
honestly preserves the four omissions.

**Eight previous C retrieval failures are structurally prevented**: timber, receipts,
ambiguous, review, tax, reversal, forestry_evidence and coverage. Nine previously failing
C runs now have complete mandatory evidence under the same-plan classification; the ninth,
payment_evidence, already met the frozen tool/view availability checks and failed its old
final references. Exact verification also found that its direct lookup targeted a different
paid invoice. The new coordinator retrieves the €588.07 target too: its direct state remains
AMBIGUOUS, requires human review, and exactly matches the frozen reconciliation evidence.
This exposes a limitation of tool/view completeness as a proxy for precise target selection.
It is not counted as a newly repaired retrieval failure. Handle regression tests cover
that reference contract, but no claim is made that a future model cannot emit an unknown
handle or omit a mandatory handle.

The initial reporting artifact is preserved separately; its counter counted all nine
prior failures with available evidence. The final report distinguishes the eight retrieval
repairs from the reference-only case. This reporting correction does not alter source
results, historical scores or model decisions.

## Remaining limitations and next-run criteria

- This is a versioned entry point, not a replacement of frozen historical runners. A future
  evaluator must explicitly invoke it and preserve unchanged acceptance requirements.
- Old strict literal scope checks may reject multiple correctly filtered context queries
  where they previously expected an all-context query. No scoring change or silent context
  fallback is made here; integration must expose and review such compatibility limits.
- Plans/semantic policy can still miss intent. Unknown handles and omitted mandatory handles
  still reject rather than being silently repaired. No live handle-schema acceptance has
  yet been measured.
- Scoped review queries do not assign unknown-context transactions to the requested domain;
  unknown purpose remains a human-review limitation. No receipt or merchant creates tax
  deductibility.
- Broad invoice discovery can require multiple direct lookups. The 24-call cap, page limits,
  empty discovery and source/tool errors can still produce incomplete evidence. No budget
  enlargement is proposed to hide these outcomes.
- More selected evidence may increase trusted-renderer length. No renderer or concision
  scoring rule was changed, and local retrieval completeness is not a benchmark pass.

One separately authorized small live development smoke test is technically justified,
using `OpenAIHandleModel`, the coordinated entry point, explicit period and frozen snapshot.
It should require multiple evidence views and retain native output, canonical mappings,
ledger, completeness and rendering. Stop on provider-schema/handle errors. Do not proceed
to a full benchmark or holdout without separate authorization and the unchanged gates.

## Verification

734 tests passed, including 40 new targeted cases. Full Ruff format/check, git diff check,
dependency-lock validation and Alembic checks passed. Source fingerprints confirm all 14
source tables unchanged. Phase 08 snapshot, protected Phase 06/07/08/09 artifacts, historical
protocol/scoring/renderer and sealed holdout byte hash are unchanged. Holdout was hashed
without decoding or parsing expected contents. Privacy scan found no known secret/source-ID
matches in changed versionable files. Details are in `data/interim/phase09b/verification.json`.
