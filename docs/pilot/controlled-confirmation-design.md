# Controlled confirmation: design only

The feedback analysis recommends designing an individual-transaction confirmation
workflow. This does not authorize or enable writes. Existing CORRECT/PARTIALLY_USEFUL
feedback and notes remain evaluation data. They cannot become confirmation tokens.
The prototype in `tapio/suggestions/confirmation_design.py` is a pure dry-run function,
not connected to the pilot API, source store or knowledge event store.

## Human interaction

Show date, merchant, amount, current values and authority, proposed values, exact fields
selected, supporting evidence, ambiguity warnings and tax boundary. Category and
context have separate controls, initially unselected. UNKNOWN is a stored label;
an omitted field means no confirmation. Never turn omitted fields into UNKNOWN writes.

CONFIRM accepts only explicitly selected fields with an existing proposal. CHANGE lets
the human choose validated values, including for an abstaining card. SKIP changes no
fields and emits no confirmation event; optional attempt metadata is separate.
For conflicting evidence or multi-context merchants, display the conflict prominently.
A human may explicitly choose transaction-specific context; no merchant-wide rule results.

The preview says, for example, `category: UNKNOWN → GROCERIES; context: unchanged`.
Only after reviewing this preview would the user press a separate final commit button.
A future server must bind that click to a current preview, exact selected fields,
transaction ID, evidence/card hashes, local human session, timestamp and idempotency key.
An arbitrary request field claiming HUMAN_CONFIRMED must never grant authority.

## Future validation and atomicity

Before enabling anything, implement and separately authorize a narrow confirmation
service. Validate allowed categories and PERSONAL/PROPERTY/FORESTRY/UNKNOWN contexts;
reject stale source/review versions, changed evidence or missing human intent. Enforce
same-origin/local access and anti-forgery controls server-side. Recheck under a transaction
lock. Disable general table-patch endpoints. Neither feedback nor model output can call
this service with confirmation authority.

Append a review revision containing per-field confirmations, an audit record and a
transactional outbox event atomically. A failed commit creates none. An idempotent replay
creates no duplicate review, support count or knowledge observation. Source bank facts
remain immutable; a reviewed-label projection is derived from review revisions.

The existing review rows are not a sufficient field-level authority ledger by themselves.
Design a new revision/field-confirmation representation and compatibility projection
before implementation. Preserve existing human decisions as authoritative baseline
revisions without inventing confirmation for previously unresolved fields. No migration
or database write is part of this phase.

## Audit and knowledge

Retain transaction ID, old/new values and authority per field, explicit fields, action,
server commit time and user interaction time, original suggestion/card snapshot, evidence
shown and hashes, human session reference, revision ID, superseded revision, correction
reason, idempotency key and generated event ID. Do not record credentials or secrets.
The original suggestion always remains SUGGESTED, including after CHANGE.

A committed explicit review emits a replayable HUMAN_REVIEW_CONFIRMED event. Its
provenance names the review revision and selected field. It can add one transaction-scoped
observation and history item. It cannot create a deterministic merchant classification,
change multi-context policy or decide tax deductibility. Repeated occurrence remains a
source fact. The dry-run event preview is not a KnowledgeEvent and is never persisted.

## Corrections and undo

A correction appends a new revision linked by `supersedes_review_id`, with a human reason.
It never deletes or edits earlier audit or suggestion records. The future knowledge replay
must understand explicit supersession: older observations remain inspectable but do not
count as current support or create a false unresolved contradiction with their correction.
The current knowledge replay lacks this full correction lifecycle; implement and test it
before enabling confirmation writes. Undo is another explicit compensating revision,
including restoration of prior field authority or unresolved state, not a destructive reset.

## Required implementation gate

The current design fixtures exercise CONFIRM, CHANGE, SKIP, independent fields, stale
state, correction history, preview audit/event contents and non-mutation. They are not
production authorization/security tests. Before enabling writes, separately test real
atomic rollback, authorization/anti-forgery, duplicate commit, stale evidence, partial
field authority, correction/supersession replay and unchanged source/tax fields against
isolated database fixtures. Then present a small real preview batch for explicit human
approval. Existing evaluation feedback is never replayed as confirmation.
