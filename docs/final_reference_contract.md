# Native final-reference contract repair

This is protocol hardening and an offline counterfactual parser replay. No A/B/C benchmark, paid model call, holdout inspection, source mutation, scoring change, model change or round-budget increase was performed. Historical Phase 06/07 reports and results are unchanged.

## Root cause and conversion boundary

The original path was:

1. `AgentModel.generate_with_tools` returns a provider-neutral `ModelTurn`.
2. `OpenAIModel.generate_with_tools` translates the existing tool schemas and messages into Chat Completions function calls. Its adapter-only `finish_evidence_answer` function advertised object references but used `strict: false`.
3. The provider returns `choices[0].message.tool_calls[0].function.arguments` as a JSON string. Previously the adapter passed `json.loads(arguments)` directly into `ModelTurn.model_validate`.
4. `ModelTurn.references` requires `ResultReference` objects. A native list such as `[0, 1]` therefore failed before a canonical final turn existed, even if those indexes selected valid retrieved evidence.
5. `run_agent` caught the validation failure as `MODEL_TOOL_SCHEMA_ERROR`. The trusted renderer was never called. The evaluation subsequently failed final-answer checks; it did not repair representations.

The captured Phase 07 diagnostic demonstrated exactly this failure: integer references `[0, 1, 2, 3]` accompanying `message_key: results`. It replayed the B-primary final turn after four successful source calls. It was a separate diagnostic response, not the missing original benchmark response.

The repaired boundary is `OpenAIModel.parse_response`, shared by live parsing and offline replay. It decodes JSON, normalizes only documented reference shapes, validates the required final fields and execution ledger, then constructs a canonical `ModelTurn`. Downstream loop, renderer and scoring functions are unchanged.

## Canonical DTO and permitted normalization

The sole internal reference type remains `ResultReference { call_index: int }`. Its integer is now strict and nonnegative: strings, floats and booleans do not coerce into indexes. Integer shorthand is accepted only at the provider boundary, never by `ModelTurn` or the renderer.

| Native `references` value | Result |
| --- | --- |
| `[{"call_index": 0}]` | Canonical, unchanged |
| `[0, 1]` | `[{"call_index": 0}, {"call_index": 1}]` |
| `0` | `[{"call_index": 0}]` |
| `[1, {"call_index": 0}]` | Valid mixed representations; original order retained |
| `[]` | Remains empty; the existing missing-evidence behavior is unchanged |
| Strings, floats, booleans, nulls, nested/malformed values | Rejected |

Both `references` and `message_key` are required for the final-answer function; unknown fields are rejected. The final schema permits the same message-key values and at most eight references as before. Duplicate reference indexes are explicitly rejected, never silently deduplicated. Duplicate JSON object keys are also rejected rather than resolved by last-value-wins parsing.

Every referenced index must identify a completed, successful tool call in the actual assistant-call/tool-result sequence. Failed calls retain their original index positions; they are not removed or renumbered. Pending calls, orphan results, failed-call references and out-of-range indexes are rejected. The adapter does not infer which evidence matters, add missing references, select another call, calculate facts, alter a message key or suppress earlier tool errors.

## Strict native schema

The final function now uses `strict: true` and a dedicated required-field `FinalAnswer` schema built from the same canonical `ResultReference` and message-key enum. It excludes the generic intermediate `call` field and unused free-form tool-call definitions. All object schemas forbid additional properties and require every declared property.

OpenAI documents strict function-schema enforcement for this API, including those requirements. See [official function-calling documentation](https://developers.openai.com/api/docs/guides/function-calling). Source-tool schemas and descriptions remain unchanged and retain their existing settings. No API/model migration was made.

Strict payload construction is tested locally. Its behavior has **not** been exercised with a new live request in this task. Defensive normalization remains necessary for retained historical outputs or other documented equivalent native shapes.

## Private audit and benchmark reporting

Every native response reaching the parser is stored in a separate owner-readable JSON artifact under ignored `data/interim/agent/provider_protocol/` (or an explicit private replay/test directory). The artifact retains:

- the original provider response, including the untouched arguments string;
- the normalized final representation when one can be constructed;
- the executed-call success ledger, representation-change flag and validation result;
- a sanitized error code for rejection.

Malformed input is not partially salvaged; the normalized field is null when no valid representation can be formed. A negative or out-of-range representation may be recorded as the attempted normalization but remains invalid. Credentials, request headers and API keys are not part of these records.

Distinct outcomes include `VALID_CANONICAL_FINAL`, `PROVIDER_FORMAT_NORMALIZED` and `INVALID_FINAL_CONTENT`. An invalid answer never receives a successful normalization classification simply because an integer was wrapped. Non-final calls and invalid envelopes have separate statuses.

Future Phase 07 result files include generic `provider_protocol` event metadata with private-artifact paths. The planning wrapper forwards this telemetry without provider-specific parsing. This adds reporting only: no rubric, question, evidence policy or scoring expression changed. Historical result files are not rewritten.

## Offline replay and limitations

Only **one raw native final response** was retained in the Phase 07 artifacts: `finish_diagnostic_native.json`. The regular benchmark traces stored validated turns, not rejected native finals. Consequently, the 25 benchmark results explicitly marked `MODEL_TOOL_SCHEMA_ERROR` cannot be individually reparsed. Other incomplete statuses also do not establish an exact native failure cause. Their original outputs must not be guessed from tool traces.

`scripts/replay_final_contract.py` uses the retained diagnostic and its documented B-primary call history. It never reads an API key or calls a provider/database. A recorded registry returns only exact matching stored tool results, and the existing loop, renderer, Phase 06 rubric and Phase 07 scoring function are reused.

| Counterfactual diagnostic replay | Result |
| --- | ---: |
| Raw native finals available | 1 |
| Previously invalid raw finals repaired | 1 |
| Still structurally invalid among available raw finals | 0 |
| Evidence-complete after parser repair | 1 |
| Still failing evidence requirements in this replay | 0 |
| Paid model / database calls | 0 / 0 |

The repaired diagnostic selects exactly the same four recorded source results and passes the unchanged evidence checks. This is evidence that the known representation defect is fixed, **not** evidence that all historical schema failures were representation defects. It does not turn B's historical 1/20 score into a different score.

A separate read-only inventory of all 60 stored development cases identifies failures that normalization cannot fix:

| Historical trace classification | Count |
| --- | ---: |
| Already passed historical acceptance | 9 |
| Retrieved evidence or scope insufficient, even if every successful result were selected | 36 |
| Structurally valid final, but failed existing acceptance | 2 |
| Sufficient retrieved evidence to investigate, but original native final unavailable | 13 |

The two valid-final failures are A `tax` and `deductions`. The 36 retrieval/scope failures are:

- A: primary, electricity, timber, receipts, ambiguous, review, doublecount, reversal, forestry_evidence, electricity_evidence, coverage, payment_evidence, trust.
- B: electricity, timber, receipts, ambiguous, review, tax, doublecount, reversal, deductions, forestry_evidence, electricity_evidence, coverage, payment_evidence, trust.
- C: timber, receipts, ambiguous, tax, reversal, forestry_evidence, unresolved_forestry, coverage, trust.

Thus **38 historical cases have known failures that a representation-only repair cannot fix**. The remaining 13 failed cases are not assumed repaired. They include B-primary: the separately captured diagnostic now passes, but the original B-primary native response remains unavailable. Detailed case classifications, checksums and counterfactual results are private in `data/interim/protocol_repair/counterfactual_replay.json`.

## Verification and readiness

Tests cover canonical and shorthand references, single integers, strict integer types, negative/out-of-range indexes, failed/pending calls, duplicate references/JSON fields, missing/unknown fields, malformed mixtures, private raw/normalized retention, strict final-schema construction, unchanged source-tool schemas, exact rendering/scoring equivalence and missing-evidence rejection after successful normalization. Hash guards protect the existing renderer, coordinator and Phase 06 evaluator.

Verification: **672 tests passed** (632 existing plus 40 protocol tests), with the full run completing in 45.96 seconds. Ruff formatting/checks and `git diff --check` pass. Fingerprints preserve 14 source tables, 66 protected electricity files and 142 protected history/code files. Private-artifact permission and secret/source-identifier scans pass. The adapter is technically prepared for a separately authorized benchmark rerun, subject to the untested live strict-schema request. This does not establish pilot readiness or promise improved evidence completeness. No A/B/C rerun was performed, and the historical NOT_READY decision remains in force.
