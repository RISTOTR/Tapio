# Phase 11 — human-supervised read-only pilot

This is a separate local usability pilot around the accepted `PHASE09H_EXCLUSIVE_C_V1` engine. The configuration SHA-256 remains `3b3e0d809c205ca37f7c39414aca407fe01a58a15935d1a3db93d2ae2d97988b`; the model remains `gpt-5.4-mini-2026-03-17`, with six rounds maximum, 3,000 completion tokens per request, reasoning `none`, parallel calls disabled and provider storage disabled. Phase 10 acceptance history is unchanged.

## Start and stop

From the project directory, with the existing private API key and PostgreSQL database available:

```sh
cd /path/to/Tapio
./scripts/start_pilot.sh
```

The startup script starts Colima if needed, waits for PostgreSQL health, and verifies the frozen configuration and source fingerprints before serving requests. Keep Colima running while using the pilot. PostgreSQL restarts with Docker unless explicitly stopped. The page checks database availability before submitting a question; this check makes no model call. Database outages show a specific recovery message.

Open **http://127.0.0.1:8011/pilot**. Type a question and click **Ask**. Each question is independent; previous questions are not added to the model context. Each submission may incur the displayed model cost. Requests run only when submitted; there is no scheduler, background agent or automatic retry. Stop with **Ctrl+C**. Pilot mode defaults to disabled. Bind only to loopback; this is not an authenticated or deployable remote service.

For local troubleshooting, set `TAPIO_PILOT_DIAGNOSTICS=true` alongside pilot mode.
Private question records then include safe stack-frame metadata as well as failure
stage/category, planner/coordinator invocation and evidence-view diagnostics. A
database outage is recorded separately from an unsupported question. See the
[zero-call failure diagnosis](pilot_failure_diagnostics.md) for the request trace,
verification and recovery steps. Year-only questions are supported.

The endpoint can also be used directly:

```sh
curl -sS http://127.0.0.1:8011/pilot/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What were my main property expenses in 2026 and what is still incomplete?"}'
```

## Architecture and safety gate

`tapio/pilot/` is new wrapper code. It leaves the accepted core files, tool descriptions, policies, context union, mandatory retrieval, explicit final handles, ambiguity rules and financial renderer unchanged. The pilot invokes the exact accepted orchestration function code with a private per-call globals mapping that redirects coordinator audit storage into the pilot history mechanism. This avoids changing process-global engine bindings or writing new records into historical evaluation directories. No prompt tuning or model comparison is included.

Before answering, the wrapper checks the immutable configuration, accepted implementation hashes, accepted evidence artifacts and current source-table fingerprints. The production registry must match the frozen registry schema/description hash and contain only the accepted read-only tools. PostgreSQL connections default to read-only transactions; each query session explicitly sets `READ ONLY`, has a statement timeout and rolls back on exit. No SQL execution, transaction update, review import, reconciliation confirmation, source import, Gmail, email, shell or arbitrary filesystem tool is exposed to the model. Private pilot logs are the only pilot filesystem writes.

The final safety gate requires complete mandatory retrieval, complete valid explicit final handles, successful selected results, exact trusted rendering, the 850-word renderer bound, the tax boundary and unchanged source fingerprints. Coverage is derived before release. Disabled mode or unavailable bootstrap/private storage fails closed with HTTP 503. Configuration and execution failures reached inside the service return `UNSUPPORTED` with a private failure category; failed answer validation returns no financial evidence or free-form model fallback. Private history must be writable before an answer can be returned.

The minimal page is loopback-only, rejects cross-origin requests, uses text-only insertion for returned content and sends `Cache-Control: no-store`. The pilot app is separate from the existing API app and imports no mutation routes.

## Typed response and evidence

`POST /pilot/ask` accepts only `{"question":"..."}`. `PilotResponse` contains:

- `answer`: trusted renderer text, with private identifier redaction applied only to presentation.
- `evidence_state` and `evidence_states`: deterministic source-derived states, never numeric confidence.
- `coverage`: requested/observed bank periods, selected-row review counts, separately labeled snapshot review counts, supported electricity months and document provenance limitations.
- `evidence`: human-readable source descriptions and record counts, without source IDs or hashes.
- `human_review`: unresolved classification, ambiguous payment, unresolved reconciliation and tax-review items.
- `limitations`: only additional limitations relevant to the selected evidence. The accepted renderer's existing safety paragraph remains unchanged.
- `session`: an answer/feedback identifier, timestamp, model calls, rounds, latency, tokens and estimated cost.

States are `SUPPORTED`, `PARTIAL_COVERAGE`, `HUMAN_REVIEW_REQUIRED`, `AMBIGUOUS` and `UNSUPPORTED`. Multiple states can apply. The primary state follows that last-to-first safety priority: unsupported, ambiguous, human review, partial coverage, supported. Empty source results establish absence of imported evidence, not zero expense or income.

For 2026 bank evidence, the separately labeled frozen review snapshot is 75 human-reviewed of 170 transactions, with 95 unresolved. Filtered-row counts are shown separately; excluded unknown-context rows are disclosed. UNKNOWN remains an actual stored label, never unspecified intent. Human-confirmed categories/contexts remain authoritative. Merchant names do not decide context or tax deductibility.

Electricity questions reuse the accepted saved April–August 2026 comparison. Coverage explicitly identifies its months and retrospective unchanged-load basis; it is not actual bank cash flow or a realized supplier switch. The saved result separately identifies accepted source-review evidence rather than a fresh parser result. The accepted document catalog does not expose unsupported-layout review records, so the pilot does not claim those attachments are parsed or reviewed catalog entries. Document summaries distinguish recorded parser provenance from missing provenance; source-catalog presence alone does not establish reviewed contents, payment or tax treatment.

The calendar wrapper accepts one explicit calendar year and optionally one English month name. An unspecified period uses the current calendar year. Multi-year/multi-month and unsupported relative-period requests fail safely rather than guessing. This is a pilot limitation, not a change to evidence-plan semantics. The saved electricity comparison retains its complete accepted period even if a question requests a narrower period; read its disclosed supported months. There is no new electricity calculation.

## Human review, feedback and private history

The page displays unresolved evidence with a human-review action; it provides no confirm, classify, reconcile or tax-decision operation. The €588.07 reversal ambiguity remains unresolved. Tax answers can show source facts and human-confirmed context, but Tapio does not decide deductibility.

Use the small feedback form after each answer: `GOOD`, `INCOMPLETE`, `WRONG_EVIDENCE`, `UNCLEAR` or `OTHER`, with an optional note. `POST /pilot/feedback/{session_id}` writes a separate private feedback event. It does not retrain, change prompts, alter labels or modify source data. Latest feedback per answer is used in aggregate metrics; earlier feedback events remain retained.

History lives under gitignored **`data/interim/pilot/`**, protected by an owner-only root directory (0700) and private files (0600). Nested directories are inaccessible to other users through that root:

- `<session>/question.json`: question, timestamp, public response, plan/policy summary, views, required/returned handles and minimal exact source/parser/review provenance.
- `<session>/provider_protocol/`: provider-native plan/final records and validation, without request prompts, API keys or headers.
- `<session>/tool_audit.jsonl`: content-free tool audit.
- `<session>/feedback/`: separate feedback records.

Full source documents, extracted document bodies and full tool ledgers are not copied into question history. The private record retains exact source IDs and handles for local auditing; these are not exposed in the normal page/response. To inspect a private record deliberately, use `.venv/bin/python -m json.tool data/interim/pilot/<session>/question.json` locally. Do not paste raw history into public issues.

`GET /pilot/metrics` returns question count, mean/median latency, total tokens, model calls, total estimated cost, feedback distribution and primary evidence-state distribution. Cost uses the accepted frozen historical USD rates ($0.75/$0.075/$4.50 per million input/cached/output tokens), not live pricing or a bill. Failed provider requests are counted; if usage is missing, the response and aggregate metrics flag incomplete usage rather than assuming the final bill is zero. Latency includes source checks and engine execution; audit persistence occurs immediately afterward.

## Practical pilot checklist

These are usability examples supplied for this pilot, not a benchmark or holdout reuse. Ask spontaneous questions too and record what is unclear or unsupported.

1. What were my main property expenses this year?
2. What forestry income has actually reached the bank?
3. What forestry expenses have source documents?
4. What is still unresolved?
5. What do we know about the €588.07 payment?
6. Was fixed or spot electricity cheaper?
7. How much did electricity cost in August 2026?
8. What transactions have not been reviewed?
9. What evidence do we have for Oikea Konekauppa?
10. What parts of the 2026 summary are incomplete?

Evaluate usefulness, answer clarity, evidence transparency, coverage, review ergonomics, latency/cost and questions the current tools cannot answer. No tuning against feedback is part of this phase.

## Verification and one pilot smoke

Verification results and the separately identified single smoke question are recorded privately under `data/interim/phase11/`. The smoke is not a benchmark. No development or holdout evaluation is rerun. No full frontend, deployment, autonomous action, Gmail search/write, tax decision or source mutation is enabled.

Completed verification: **837 tests passed**, preserving the existing 806 and adding 31 pilot tests. Ruff, formatting, dependency lock, Alembic and diff checks passed. The negative mutation test verified PostgreSQL rejects writes. All 14 source-table fingerprints, 1,543 historical artifact hashes, 66 electricity artifacts, and the holdout/manifest byte hashes remained unchanged. Privacy checks found no credentials or private source identifiers in versionable changes; all 1,447 checked private files were ignored by Git. The smoke's public response exposed none of its 52 privately retained source identifiers. Pilot implementation hashes remained unchanged from the smoke through final verification.

The one live smoke asked: **“What were my main property expenses in 2026 and what is still incomplete?”** It passed the wrapper's safety gate and returned `AMBIGUOUS`, with human-review and partial-coverage disclosures. Its PROPERTY selection contained 20 human-reviewed transactions; it separately disclosed 95 excluded UNKNOWN-context rows and the overall 75/170 reviewed snapshot with 95 unresolved. It preserved the payment/reversal ambiguity and tax boundary. These unresolved rows were not assigned to PROPERTY.

The smoke used two model calls over two rounds: 10,054 input tokens, zero cached input tokens and 147 output tokens. Measured latency was 11.252 seconds; estimated cost at the frozen rates was **$0.008202**. No feedback was fabricated. No further live question was executed. The local server is not left running; use the startup command above when beginning the supervised pilot.

## Question-specific presentation

The default page now displays a deterministic presentation projection **after** the
accepted answer has passed every existing evidence, handle, renderer and source
integrity check. Evidence required internally is not necessarily evidence that
must be printed in full. Planning, retrieval, context semantics and tax boundaries
are unchanged; the model does not write the new cards.

The response adds `presentation_mode`, `direct_answer`, `relevant_breakdown`,
`coverage_note`, `human_review_note`, `evidence_summary` and `optional_details`.
The original `answer`, `coverage`, `evidence`, `human_review`, `limitations`, session
metrics and private provenance remain available. Existing feedback and its five
categories are unchanged. The original answer remains the validated renderer
output; the default UI leads with the new direct answer.

Seven deterministic modes cover financial totals, transaction review, ambiguity,
comparison, evidence lookup, coverage and tax boundaries. Financial cards copy
existing authoritative aggregate fields, distinguish timber income from all
forestry credits and show only relevant context/category breakdowns. They do not
sum a bounded page, mix currencies, infer a merchant's context or substitute
invoice/sale values for bank cash flow. If the retrieved evidence lacks a complete
reviewed total for the requested scope (including a provider-specific total), the
card says so; presentation does not fetch missing evidence or manufacture a total.

Review cards lead with the unresolved count and preview at most ten retrieved
rows. Additional rows are explicitly omitted from the summary, not discarded.
All retrieved transaction rows are in collapsed optional details, with the
retrieved/expected counts retained. The preview never claims to be the whole list.
A complete retrieved list still does not establish complete bank-statement coverage.

Reconciliation facts are deduplicated by source identity and matching content.
Distinct invoices with equal amounts and conflicting variants remain distinct.
Document/catalog projections of the same source are merged only when their shared
facts agree. Evidence handles and original result/provenance structures are not
removed or edited. Amount matching uses Decimal equality, so database scale such
as trailing zeros does not hide an ambiguous event.

The page hierarchy is status badges, direct answer, relevant breakdown, one material
coverage note, one review note, concise evidence summary, optional details and
feedback. Raw coverage JSON, long transaction lists and the original verbose answer
are collapsed by default. Generic tax prose is not repeated in unrelated main
answers; tax-mode cards retain the explicit deductibility boundary. The unchanged
validated answer and backend limitations remain inspectable in the details.

Optional details include identifier-redacted transactions, documents, reconciliation,
bank aggregates, sale/comparison facts, coverage and backend warnings. Exact private
source IDs and evidence handles remain in private provenance, not ordinary UI text.
These projections preserve all retrieved rows; they are not new database queries
or a claim that unavailable documents do not exist.

Offline replay of the four retained pilot plans and final references passed after
read-only evidence retrieval. Main-presentation sizes were 53, 47, 73 and 128 words
respectively; all 8, 9, 7 and 8 required handles remained validated. The review case
retained all 95 rows with ten previewed. Income and expenses matched the reviewed
aggregates and disclosed 174 unknown-context exclusions. The payment case led with
two debit candidates and one credit/refund candidate, without asserting the exact
reversal. No model calls or benchmark reruns were used for this presentation work.

Presentation verification completed with **901 tests passed**, including 27 new
presentation tests and all 874 existing tests. Ruff, formatting, dependency-lock,
Alembic and diff checks passed. The repository privacy scan checked 262 files with
zero findings and the private denylist loaded. All 14 source-table fingerprints,
the accepted engine/configuration/snapshot and holdout/manifest hashes remained
unchanged. The historical integrity check retained the two previously documented
repository-hygiene exceptions; this task introduced no new historical differences.
The four replay cases and browser-script checks passed without a live model call.
The human-supervised read-only pilot can resume after restarting the local server
to load the presentation changes; this does not authorize a benchmark rerun.

Named-subject pilot questions now have a separate read-only identity lookup after accepted
validation and before source postflight. See [the named-subject repair report](pilot_named_subject_retrieval.md)
for the observed failure, matching contract, scope, local results and verification. This
additive pilot lookup does not change the accepted agent, benchmark or evidence requirements.

The subsequent [shared subject identity repair](pilot_subject_identity_consistency.md)
consolidates extraction and matching across evidence, payment, tax, document and
reconciliation paths, including Elenia and the inspected K-Rauta store descriptor.
It supersedes the first repair's narrow sentence-pattern extraction and parallel
presentation matcher; the accepted validation and source-integrity gates remain in place.

See [fallback classification and narrowing](pilot_fallback_classification.md) for the distinction between service outages, unsupported scope, invalid planning and incomplete retrieval.

See [intent and presentation routing](pilot_intent_routing.md) for named-subject eligibility and broad/coverage/review routing.

See [generic bank transaction search](pilot_transaction_search.md) for bounded ad-hoc text queries and explicit multilingual search terms.
