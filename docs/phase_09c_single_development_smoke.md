# Phase 09C — one live development smoke

Result: **PASS** for the coordinated protocol and existing case diagnostics. Pilot status remains **NOT_READY**. This is one smoke case, not a benchmark score. No A/B/C rerun, holdout inspection, tuning, implementation fixes, or historical score changes occurred.

The exact existing development case was `reversal`: “Assume the €588.07 refund reversed the first debit.” This critical case previously omitted required evidence. The existing evaluation reporting-year prefix was preserved. Requested and returned model: `gpt-5.4-mini-2026-03-17`, configuration C architecture through `run_coordinated_agent`. Settings remained six model rounds maximum, 3,000 completion tokens per request, reasoning effort `none`, parallel tool calls disabled and provider storage disabled. Actual execution used two model rounds.

The untouched provider plan was:

```json
{"question_type":"reconciliation","required_views":["BANK_CASH_FLOW","RECONCILIATION"],"required_contexts":["UNKNOWN"],"needs_coverage_check":false,"needs_tax_boundary":false,"needs_reconciliation":true}
```

No manual plan repair occurred. The unchanged Phase 09B policy expanded effective views to BANK_CASH_FLOW, COVERAGE, INVOICES and RECONCILIATION; the coverage flag remained false despite the policy-required coverage view. The coordinator retrieved all four effective views without another model decision. Raw-plan completeness and effective policy completeness are distinct; this run demonstrates the latter.

| Handle | Source result | Views |
|---|---|---|
| E0 | summarize_finances | BANK_CASH_FLOW, COVERAGE |
| E1 | find_invoices | INVOICES |
| E2 | get_invoice_reconciliation, first discovered invoice | RECONCILIATION |
| E3 | get_invoice_reconciliation, second discovered invoice | RECONCILIATION |
| E4 | get_invoice_reconciliation, third discovered invoice | RECONCILIATION |

The bank query used 2026-01-01 through 2026-12-31, business_context=unknown, and no category filter. Invoice discovery used that same period, limit 50, no status filter; all three discovered invoices received direct reconciliation lookups. Invoice discovery is period-wide, not context-filtered. UNKNOWN was the model's scope choice, not a human classification or a claim of all-context bank coverage. The existing case diagnostics do not independently establish that this context choice is optimal. The exact ambiguous target is verified separately below.

There were zero retrieval errors, zero missing effective views and zero optional calls. Repeated reconciliation tool names correspond to distinct invoice IDs, not redundant retrieval of one invoice.

Untouched provider final arguments:

```json
{"references":[{"evidence_handle":"E0"},{"evidence_handle":"E1"},{"evidence_handle":"E2"},{"evidence_handle":"E3"},{"evidence_handle":"E4"}],"message_key":"human_review"}
```

All referenced handles existed, were unique, selected successful results and covered every mandatory handle. No numeric provider references or nonexistent-handle normalization occurred. Internal canonical indexes were produced only by the trusted ledger. The final schema carries references and a message key, with no financial prose or arithmetic. The unchanged trusted renderer succeeded, producing 315 words. Existing evidence-completeness and critical ambiguity/policy diagnostics passed, with no missing evidence or unsupported claims. The original rubric's legacy ModelTurn arithmetic check is vacuous in retained-response replay; actual protection is independently established by the typed HandleFinal schema and exact trusted-renderer equality. Diagnostics were run against the retained response and trace without another model or source retrieval.

Execution latency: **4.709785 seconds** (excludes environment startup and integrity checks). Tokens: **10,797 input**, **0 cached input**, **191 output**. Estimated cost: **USD 0.00895725**, using the existing frozen C rates of $0.75/$0.075/$4.50 per million input/cached/output tokens; this is not a billing record or a newly verified price quote.

Private artifacts are under `data/interim/phase09c/`: exact requests (without headers/credentials), native responses, raw plan/final arguments, provider parsing records, effective plan, full mandatory trace, optional-call list, handle registry, final validation, rendered answer, timing, usage and cost. The harness refuses a second attempt after its start marker exists. Before the live attempt the database runtime required startup; those failed preflights made no model calls.

Source fingerprints, human-review rows, Phase 08 snapshot, historical artifacts, electricity artifacts, implementation/renderer/scoring and holdout byte hash are verified separately in the private integrity records. Holdout contents were not parsed. Privacy verification covers versionable files, ignored private artifacts and credential exclusion from live artifacts.

A **separately authorized full development rerun is technically justified** by this successful protocol smoke. This is not authorization to run it, evidence of general model competence, or pilot readiness. No fixes were implemented and execution stopped after this one live case.
