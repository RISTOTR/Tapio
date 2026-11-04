# Authoritative concept review and independent mappings

The concept decision ledger is authoritative. Each complete event is hash chained, includes
its candidate snapshot, and is atomically published under a process lock. Current state is
replayed from the latest event per candidate, so there is no separately updated current-state
row that can drift from the audit. Historical confirmations remain in replay; suggestion
consumers always gate on the latest CONFIRM_CONCEPT/EDIT_CONCEPT decision.

The former browser handler appended a success message but never replaced the initially
rendered PENDING status. The repaired API re-reads the persisted record and returns its
canonical decision, authority, event ID, timestamp, active semantic state and version. The
browser replaces the card from this response, disables further submissions, and offers an
explicit REVISE DECISION action. Page show/navigation and manual refresh fetch authoritative
records without caching. Refresh reuses a valid local session instead of invalidating other
open tabs. Errors are explicit; stale/session errors force a state refresh.

Previews bind the expected per-concept state and candidate snapshot. A changed state rejects
submission with STALE_CONCEPT_STATE. Exact token retries and fresh previews of an identical
current decision return ALREADY_APPLIED without appending audit or promotion events. A changed
decision appends history. The API requires an explicit revision flow for previously decided
concepts. No real concept decision is manufactured from UI appearance or expected user intent.

Category mappings are separate CATEGORY_MAPPING objects, with independent SUGGESTED authority,
IDs, candidate-specific scope, supporting transaction/review hashes, support counts, conflicts
and eligibility. They are derived from current confirmed category observations and frozen
alongside the next window, with a separate knowledge claim for each mapping. A confirmed
semantic fact does not confirm a mapping. Editing a semantic concept cannot borrow the old
concept's mapping. Conflicting categories block reuse; no majority vote occurs. Target
observations are excluded from their own support.

Mappings are limited to the matching candidate's term/scope; a general-retailer observation
is not a global GENERAL_RETAILER→OTHER rule. Hardware mappings are currently blocked pending
separate validation, even when the identity fact is confirmed and a document exists. Context
is independent, multi-context/processor safeguards remain active, and no tax decision is made.

Pagination now replays previous review events in memory and writes only to the new window.
It does not refresh or rewrite the archived window's reports, knowledge or suggestions.
Completed windows remain byte-for-byte historical. The new window includes only current
active concepts with separately eligible mappings; deferred/rejected facts cannot contribute.

Tests exercise persistence/restart, atomic publication failure, duplicate retries, stale state,
revision history, API sessions, mappings/conflicts, the six requested semantic safety examples,
and preservation of all prior-window files. A disposable DOM harness executes the actual page
script for response replacement, reload/navigation and disabled repeat actions; it also
reproduces the former success-message-only handler. This harness is not a visual browser test.
