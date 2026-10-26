# Pilot failure classification and narrowing

This repair changes only the pilot wrapper and presentation. The accepted coordinator,
model, evidence requirements, reference checks, financial renderer, tax boundary and
source data are unchanged. Fallbacks never release unvalidated financial facts or model prose.

## Root cause and trace

The pilot treated `PILOT_EVIDENCE_INCOMPLETE` as `EVIDENCE_UNAVAILABLE`, the same
category used for a refused PostgreSQL connection. Its fallback combined both cases
into “The local evidence source is unavailable or retrieval is incomplete.”

Read-only inspection found seven retained requests with that exact message. Six were
genuine database connection failures before model execution. The newest was different:
database preflight passed, the provider returned a valid plan, and mandatory retrieval
ran. The plan requested eight evidence views; all 24 executed tool calls succeeded,
but retrieval reached the fixed source-call limit and required transaction evidence remained truncated. Returned view names did
not establish completeness. There was no validated final answer.

Private per-request traces, raw/parsed plan references, retrieval audit entries and an
offline classification replay are retained under
`data/interim/pilot_fallback_classification/`. Historical records are not rewritten.
The latest failure is now classified as `QUESTION_TOO_BROAD`, with its evidence
incompleteness retained in diagnostics. The six connection failures remain infrastructure failures.

## Categories and public presentation

| Category | Public guidance | Badges |
| --- | --- | --- |
| INFRASTRUCTURE_UNAVAILABLE | Database offline/recovery instructions, or model service unavailable, according to the actual failed dependency | UNAVAILABLE |
| QUESTION_TOO_BROAD | Narrow to a year and one evidence area | UNSUPPORTED · NEEDS_NARROWING |
| UNSUPPORTED_SCOPE | No validated read-only evidence path for that request | UNSUPPORTED · HUMAN_REVIEW_REQUIRED |
| EVIDENCE_INCOMPLETE | Some relevant evidence was found but is insufficient, when nonempty evidence actually exists; otherwise required retrieval did not provide enough complete evidence | PARTIAL_COVERAGE · HUMAN_REVIEW_REQUIRED |
| PLAN_INVALID | Could not map the question to a safe supported evidence query; narrow year, domain or subject | UNSUPPORTED · NEEDS_NARROWING |
| NO_MATCH | Completed named-subject lookup found no matching imported evidence | SUPPORTED · NO_MATCH |
| AGENT_EXECUTION_ERROR | The evidence workflow encountered an execution error | UNSUPPORTED · HUMAN_REVIEW_REQUIRED |

Existing configuration, safety and final-validation failure categories remain distinct.
A missing final handle still blocks release even after retrieval completes.
A database statement error does not itself establish that the database is offline.
A healthy database does not imply that a separate provider is available.

## Broad-question behavior

There are two conservative paths:

- After successful source preflight, an explicit unbounded multi-domain request such as
  “Give me a complete overview of all my finances and taxes” gets narrowing guidance.
- After a failed release, a validated multi-domain plan that hits the fixed source-call
  limit gets the same guidance. This uses the actual plan and execution facts, rather
  than relying only on question keywords.

Other incomplete retrieval remains `EVIDENCE_INCOMPLETE`. Invalid planning remains
`PLAN_INVALID`. No plan is guessed or repaired, no mandatory evidence is skipped,
and no accepted execution limit is raised. Ordinary yearly aggregates and named-subject
questions continue through the accepted path.

For partial retrieval, the page reports completed/incomplete evidence areas and
truncation when known. This is structural coverage, not a validated financial answer.
It does not expose raw errors, identifiers or unvalidated totals.

## Narrowing suggestions and feedback

The page shows a small “Try asking:” list. Suggestions use fixed supported templates,
prioritized by the question's domain and validated plan views. Explicit years are
retained; otherwise 2026 appears as an example year, not an inferred evidence claim.
Suggestions never execute automatically.

Examples:

- “What were my main property expenses in 2026?”
- “What forestry income reached my bank account in 2025?”
- “What parts of my 2026 bank data are still incomplete?”

Feedback remains GOOD, INCOMPLETE, WRONG_EVIDENCE, UNCLEAR or OTHER and saves normally
for fallback responses.

## Private diagnostics

Each new record includes request ID, failure category/stage, database/provider availability
when established, planning validation, planner/model calls, retrieval-attempt status,
per-call success/truncation, required/returned views, completeness, and safe error codes.
Raw provider plans remain in the existing private provider protocol records. They are
not exposed in the normal UI.
