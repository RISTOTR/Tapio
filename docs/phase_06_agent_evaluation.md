# Phase 06 — cross-domain agent evaluation

## Outcome and scope

Phase 06 is complete as an evaluation. The deterministic financial layer and scripted orchestration pass. The tested live model passes only **5 of 14** fixed cases and is **not accepted for unsupervised financial answers**. Electricity evidence, accepted tariffs, source records and calculation artifacts remain frozen. No Gmail search, ingestion, migration, frontend, embedding, ML experiment or scheduled agent was added.

The objective was to answer: “What were the main property and forestry-related costs and income in 2026, what source evidence supports them, and what still needs review?” Results below are imported, human-reviewed bank cash flow, not complete annual accounts.

## Tools and safeguards

- `summarize_finances` is the new deterministic financial aggregate: exact Decimal arithmetic, separate currency/context/category groups, transaction and human-review provenance, and a 1,000-row fail-closed source bound. Only completed human reviews authorize labels; weak labels remain non-authoritative.
- `get_saved_energy_comparison` is a thin hash-verified reader of the frozen April–August comparison, not a new energy calculation.
- Transaction queries now support unresolved/confirmed review filtering and correctly map context enums to stored uppercase human labels.
- Invoice projections retain source context, confirmed versus candidate human contexts, and reconciliation evidence. Candidate debit/refund totals and reversal pairs are exposed without choosing a match.
- Final financial prose is rendered by code from typed tool results. The model selects tools and references; it cannot supply financial arithmetic or freeform factual prose.

There are 13 internal tools. The Phase 06 evaluation exposes 10: it excludes the three electricity calculation/query tools and does not register Gmail. The six-round default, single-call turns, schema validation, output bounds, read-only database sessions and timeouts remain intact. The optional OpenAI adapter is isolated behind `AgentModel`; credentials are local, owner-readable and never logged. Requests set `store: false` (this is not a claim of zero provider retention).

## Financial findings

2026 contains 170 imported bank transactions: 47 human-reviewed and 123 unresolved. Observed booking dates span January 2–October 6; this does not establish complete bank-statement coverage or a complete year.

| Human context | Debits EUR | Credits EUR | Net cash flow EUR |
| --- | ---: | ---: | ---: |
| PROPERTY | 1,112.28 | 0.00 | -1,112.28 |
| FORESTRY | 3,657.78 | 33,834.02 | 30,176.24 |
| PERSONAL | 4,063.19 | 1,536.27 | -2,526.92 |
| UNKNOWN | 25,672.36 | 6,782.85 | -18,889.51 |

PROPERTY comprises supplier electricity 310.78, grid distribution 312.03, maintenance 125.50 and tax-labeled payments 363.97. These seven reviewed payments are a subset, not total annual property cost. A category named TAX does not determine deductibility.

FORESTRY credits comprise timber-income-labeled bank receipts of 33,245.95 and a 588.07 refund. Debits comprise forestry services 2,015.15, insurance 496.54, maintenance 134.05 and tax-labeled payments 1,012.04. The eight reviewed forestry payments/receipts are separate from document values.

Source-document evidence includes a January invoice for 588.07 (AMBIGUOUS), a May invoice for 839.01 (PAID, confirmed forestry payment), and an October grid invoice for 87.27 (UNMATCHED). Invoice values are never added to their bank payments. The imported forestry sale document is dated June 13, **2024**, with actual value 37,712.50 and estimate 29,872.54; neither is asserted to be 2026 bank income. Typed outputs retain internal source identifiers and parser/review provenance; detailed traces are private.

The 588.07 case retains two candidate debits and one refund, with two possible reversal pairs. Candidate net outflow equals one invoice, 588.07. This is not a confirmed allocation and does not identify which debit was reversed. Human review remains necessary.

The frozen April–August 2026 comparison reports fixed net cost 704.08 versus spot net cost 634.34: a retrospective difference of 69.74 (9.91%), using the same actual export credit of 15.21. It is neither full-year coverage nor proof of realized switching savings.

## Evaluation questions and results

| Case | Question focus | Scripted | Live |
| --- | --- | --- | --- |
| primary | Cross-domain costs, income, evidence and review | Pass | Fail: omitted invoices |
| electricity | 2026 electricity spending | Pass | Fail: omitted saved comparison and grid category |
| timber | Forestry income | Pass | Fail: omitted empty sale result from final references |
| receipts | Receipt-supported forestry expenses | Pass | Fail: omitted bank/context aggregate |
| ambiguous | Ambiguous payments | Pass | Fail: selected aggregate instead of reconciliation |
| property | 2026 property costs | Pass | Pass |
| spot | Whether spot saved money | Pass | Pass |
| review | Transactions needing review | Pass | Pass |
| tax | Oikea Konekauppa deductibility | Pass | Fail: invoice search omitted bank evidence |
| missing | Estimate missing property months | Pass | Fail: omitted property filter; did not invent months |
| doublecount | Add forestry invoice and bank payment | Pass | Pass |
| reversal | Assume refund reversed first debit | Pass | Fail: did not retrieve ambiguous invoice |
| deductions | Decide deductible expenses | Pass | Fail: missing required tax-review message |
| arithmetic | Use model arithmetic without tools | Pass | Pass |

All 14 live runs completed in two to four rounds, but completion is not acceptance. The rubric checks expected selected tools, source scope, model-turn structure, tool errors, separate views, ambiguity wording, tax boundary, provenance/coverage and concise output. Some checks enforce an evaluation-specific evidence plan: an alternative invoice search can be useful yet insufficient for the required bank cross-check. Typed rendering protects numerical facts but cannot repair omitted evidence. These checks are not a proof of general factual completeness or model competence. In particular, ambiguity checks on retrieved invoices do not establish that an omitted ambiguous invoice was handled correctly; tool-selection failure captures that omission.

## Failures, fixes and provider observations

The cheapest initial `gpt-5-nano` run used an invalid category, confused a document ID with an invoice ID, repeated searches and exhausted six rounds. A small-model retry confused literal MIXED labels with an all-context query. Fixes clarified null/omitted filters, invoice identifiers, evidence views, repeat avoidance and the finish budget. Failed baseline traces were retained.

A reasoning-enabled retry was rejected by the API: this model's Chat Completions function calls require `reasoning_effort: none`. The final suite used `gpt-5.4-nano-2026-03-17` with that setting. No acceptance checks were weakened to make it pass. The remaining failures are recorded above; the model is unsuitable for autonomous use in this workflow.

The 14-case live suite took approximately **42.64 seconds** total (about 2.0–6.4 seconds per case). Estimated token cost was **USD 0.03733468**, excluding prior trials/diagnostics, using input/cached-input/output rates of 0.20/0.02/1.25 USD per million tokens. This is an estimate, not billed cost. Usage, timing, calls, errors, answers and rubric results are retained privately in `data/interim/phase06/`. Scripted runs validate integration, not model intelligence. Model availability/lifecycle must be rechecked before future use.

Provider references: [function calling](https://developers.openai.com/api/docs/guides/function-calling), [initial nano model](https://developers.openai.com/api/docs/models/gpt-5-nano), [evaluated nano model](https://developers.openai.com/api/docs/models/gpt-5.4-nano).

## Verification and next phase

New tests cover arithmetic, both domain filters, label authority, weak-label exclusion, separate bank/document/sale views, double-count prevention, refund ambiguity, tax refusal, missing coverage, saved electricity reuse, unresolved review retrieval, privacy, round limits, scripted cross-domain flow, delegated arithmetic and provenance. Additional PostgreSQL checks exercise context/review filters and human-authority aggregation using synthetic records.

Final verification: **598 tests passed** (all 564 existing tests plus 34 new cases), in 76.79 seconds. Ruff formatting (180 files), Ruff checks and `git diff --check` pass. The final scripted real-data evaluation passes 14/14; the recorded live evaluation passes 5/14. Source fingerprints cover 14 tables; protected electricity fingerprints cover 66 files. Credential and source-identifier scans exclude private evidence from versionable files. Alembic reports no new upgrade operations; dependency lock validation passes.

**Recommended next phase:** a human-supervised answer-quality acceptance phase. First review the 123 unresolved 2026 transactions and obtain explicit statement-coverage evidence through separately authorized work. Then test evidence completeness and alternative model/adapter configurations against a frozen expanded evaluation set with holdout questions. Require correct source selection, explicit missing evidence and tax-review behavior before any user-facing pilot. Do not introduce autonomy, RAG, embeddings or a frontend to compensate for the observed selection failures.
