# Pilot intent and presentation routing

This is a pilot-only presentation repair. It does not change the accepted model,
coordinator, evidence requirements, tool descriptions, final-handle validation, financial
renderer, tax rules, source data, labels or benchmark history.

## Cause

The old presentation router defaulted to EVIDENCE_LOOKUP. Its final display branch
attempted subject matching even when subject extraction returned nothing. It then
displayed “Named-subject lookup is incomplete” for general questions.

Two routing gaps made this more common: the coverage matcher matched “complete” but
not “incomplete”, and review matching required the literal word “transaction”.
Neither the presence of retrieved documents nor missing subject evidence establishes
that the question is about a named subject.

Read-only inspection found nine retained responses with this wording and no resolved
subject. Eight were general questions: repeated financial overviews, important-things
requests, a property/forestry overview, an unresolved-issues request and an incomplete-data
question. One older response involved an unsupported date phrase in an explicit
entity question. Private per-request records include intent, candidate, resolution,
old/new mode, failure category and requested/returned views under
`data/interim/pilot_intent_routing/`. This is a counterfactual routing replay, not
a benchmark or a rewrite of historical answers.

## Eligibility and modes

NAMED_SUBJECT requires all of:

- an explicit, non-generic subject candidate extracted from the question;
- a completed subject inventory lookup for that same candidate and year;
- MATCH_FOUND, NO_MATCH or AMBIGUOUS_IDENTITY resolution status;
- a retained identity for MATCH_FOUND.

An explicit unknown merchant can legitimately have NO_MATCH and no canonical name.
Its queried candidate must still exist; a generic noun cannot qualify this way.
Domain words, years, context/category labels, tool names and generic evidence nouns
are rejected as subject candidates. With no candidate, no subject database lookup runs.

| Intent | Presentation |
| --- | --- |
| Resolved merchant/provider evidence | NAMED_SUBJECT |
| Resolved merchant payments | FINANCIAL_TOTAL |
| Tax question, including merchant-specific tax discovery | TAX_BOUNDARY |
| Imported-data completeness | COVERAGE |
| General transaction review or unresolved rows | TRANSACTION_REVIEW |
| Reconciliation ambiguity | AMBIGUITY |
| Saved fixed/spot comparison | COMPARISON |
| Explicit generic evidence inventory | EVIDENCE_LOOKUP, without subject wording |
| Broad overview or unsupported “biggest/most important” prioritization | QUESTION_TOO_BROAD |
| Explicit subject without a completed resolution | EVIDENCE_INCOMPLETE |

Explicit question intent takes priority. The validated plan's coverage/review intent
is used when the question has no more specific display request. Modes are not selected
from the mere presence or absence of result blocks.

Coverage shows the imported bank period and reviewed/unresolved counts when available,
with document limitations and complete-statement caveats. No new totals are computed.

## Precedence and badges

Infrastructure, execution, plan, safety and final-validation failures are handled before
supported presentation or subject-card rendering. Broad/unsupported presentation and
incomplete resolution also precede any subject display. A subject card cannot overwrite
a failed accepted path.

Broad requests show UNSUPPORTED · NEEDS_NARROWING with fixed supported suggestions.
Incomplete evidence shows PARTIAL_COVERAGE · HUMAN_REVIEW_REQUIRED.
A completed explicit-entity no-match shows SUPPORTED · NO_MATCH.
AMBIGUOUS is reserved for actual identity or reconciliation ambiguity. A broad fallback
does not inherit incidental ambiguity badges from retrieved evidence.

Supported source projections retain the original validated answer and provenance.
Fallbacks do not release unvalidated totals, invent references or combine financial
domains into a new authoritative summary. Feedback continues to save normally.

## Regression coverage

The offline matrix covers financial overviews, important-things requests, mixed
property/forestry summaries, incomplete financial data, transaction review, Elenia
evidence, Vattenfall payments, K-Rauta evidence and K-Rauta tax questions. It also checks
generic-subject rejection, absent/unrelated/incomplete resolution, explicit unknown
merchants, actual ambiguous identities, planner-intent fallback and failure precedence.
