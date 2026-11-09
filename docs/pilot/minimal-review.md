# Minimal human review

`/pilot/confirmation/groups` audits every transaction without both fields confirmed,
including unresolved cases in earlier windows. It does not advance the numbered queue
or require pending semantic/mapping candidates to be reviewed. The existing window
remains available for historical review.

Exact-history proposals require at least three distinct transactions with the same
current human-confirmed field value and no conflicting/UNKNOWN observations. A full
category/context proposal requires three jointly confirmed observations. Active user
rules and already eligible confirmed semantic mappings can also support groups.
Suggestions never acquire human authority until the user previews and applies them.

Groups share an exact normalized recipient, active user rule, or semantic mapping,
and identical proposed fields/values. Different purpose evidence or transaction
direction splits groups. Category conflicts, receipt/document ambiguity and opaque
processors prevent grouping. Context conflicts and multi-context warnings remove
context from the proposed group; remaining context reviews stay in the effort report.
Pending duplicates without sufficient support are audited but cannot be bulk-confirmed.

The initial individual review budget is five. The deterministic score exposes each
component: unseen entity +5, conflicting evidence +5, context boundary +4, new processor
recipient +4, pending semantic boundary +3, blocked rule boundary +3, repeated entity +1,
stable complete exact history -5, active rule -5, duplicate pending entity -4. Initial
selection diversifies evidence problems before returning to duplicates. Next 5
is an explicit user action. No model confidence is involved.

Group preview lists all transaction IDs, selected fields, values and individual changes.
Apply uses the existing confirmation writer inside one database transaction, retaining
one revision and knowledge event per transaction. Any stale member rolls back the whole
group. Source fingerprints, current review versions, evidence versions, preview expiry,
CSRF, same-origin checks and the existing implementation verification seal remain in
force. Shared transaction rows are locked before rechecking history. Group provenance
records all affected IDs and the repeated-confirmation metric. No source/legacy labels
are updated. Individual corrections remain append-only.

Signed private plan artifacts retain the review URL across reload/restart, including
access to individual corrections after a group is applied. The pending queue rebuilds
automatically after each save and whenever its authoritative decision generation changes. Group skip records presentation metadata only. The full audit and
estimated effort report live under the ignored `data/interim/persistent_review/minimal_review/`.

Effort is an estimate: one field-selection action per unresolved field plus preview and
apply for each individual transaction; one preview and one apply per group. Residual
individual fields and ineligible cases remain in the denominator. The report distinguishes
potential avoided confirmations from actual applied group events. Navigation and reading
time are not counted, and a five-item initial display does not imply only ten reviews remain.

## Recognition and false novelty

The minimal queue resolves both observations and pending identities through the existing
explicit identity registry and a signed local `reuse.json` file. Local links retain canonical
IDs, exact aliases, source-row hashes and any purpose/context limitations. Matching never
uses fuzzy names or a generic private-road suffix. Source changes or alias collisions fail
closed. No source identities or historical human decisions are rewritten.

Vocabulary links reuse an existing active concept or taxonomy rule through a bounded token
and an explicit anchor. The original confirmation remains the authority. A synonym cannot
activate a pending concept, create a rule, supply context from an entity type, or bypass
receipt/purpose conflicts. Local vocabulary and identity links participate in plan versions;
opening a saved plan after a change rebuilds its pending set.

Novelty distinguishes unknown entities from known entities with new purchase purposes.
Prior exact or canonical observations, active rules, confirmed concepts, and partial human
reviews suppress the unseen-entity score. This does not lower the three-observation threshold
for stable-history proposals. Known cases with insufficient or conflicting evidence remain
individual judgment cases and expose that reason. Fully supported single cases use the same
preview/apply flow as groups, avoiding repeated field selection without automatic writes.

The audit reports recognition separately from removal from individual review. A false-novel
identity can still require purpose evidence. Counts from a historical plan are calculated
using that plan's revision baseline, with subsequent user decisions reported separately.


## Live authoritative history

Plan freshness includes a deterministic digest of source transactions, all confirmation revisions
and legacy human reviews, as well as rule, concept, alias, mapping and receipt versions. Opening an
old URL checks freshness and rebuilds all pending evidence and scores. Same-batch decisions
invalidate proposals too. Stale automatic confirmations are rejected under transaction locks;
an already-applied signed request remains idempotent. Explicit individual corrections use
the current transaction version and retain their original audit trail.

The UI separates group confirmations, quick confirmations, and cases requiring judgment.
Saving automatically reloads the current queue. Focus and periodic freshness checks detect
other review sessions; an unsaved edit is preserved with a notice until saved. Saved decisions
remain available in a separate correction panel across reloads in the same browser tab.
No refresh, batch advance, restart or consolidation is required to use a recent decision.

Every judgment card states its concrete unresolved evidence or boundary. Recognition newly
supported by a decision since the preceding plan is annotated FALSE_NOVEL_RECENT_REVIEW,
while the underlying conflict/purpose classification remains visible. Recognition alone
never lowers the evidence threshold or writes a classification.


## Ongoing review after historical reconciliation

The default view shows at most five informative pending transactions at once, with explicit
next/previous navigation. Quick confirmations and safe repeated groups have separate sections.
No numbered batch or generic validation window is created by this workflow.

New transactions first require deterministic ingestion and source enrichment. For new source
files, refresh and verify the source manifest through the existing controlled ingestion path;
the ongoing queue does not silently bypass source-fingerprint checks. Once verified, the queue
rebuilds exact/canonical history, active rules, semantic/category support, recipient and purpose
evidence. Strongly supported singles become quick confirmations, repeated supported cases
become groups, and genuine ambiguity goes to the five-case judgment view.

Already resolved transactions do not return to the pending queue. Explicit corrections remain
available through saved decisions and existing historical views. New contradictory evidence
requires a targeted reconciliation: report affected IDs and evidence, then seek correction only
where necessary. Automatic reopening on source changes is not enabled; changes fail closed
until source verification. A reviewed UNKNOWN remains a recorded evidence limit, not an excuse
to ask the same question again or infer reusable label authority.

A stale pending individual card cannot bypass live history by using the manual CHANGE action.
Both preview and apply reject it, and the current browser refreshes the queue. Completed
transaction corrections retain their current-state/version checks and append-only audit trail.

Historical exit is READY_FOR_ONGOING_REVIEW_MODE when no novel/high-value judgments,
contradictions, stale novelty, accidental UNKNOWN, missed aliases or unresolved reuse regressions
remain. Evidence-limited reviewed cases and unactivated learning candidates are retained for
future evidence; they do not create another historical review assignment. The final private audit
records the exit decision and metrics, with denominators and limitations explicit.

### Verified bank source updates

The historical pilot configuration remains immutable. After an authorized bank import,
`accept_bank_import` verifies the original file hash, successful importer provenance,
canonical new rows, exact skipped overlaps, and unchanged prior rows across every table.
Only additions to transactions and import runs are accepted. Human reviews and knowledge
cannot be added through this path. A signed source-acceptance record advances the ongoing
review manifest and transaction allowlist without creating a numbered window. The review
service checks current database fingerprints against that signed acceptance; without one,
the original historical source guard remains in force. Interrupted or tampered acceptance
fails closed. This source update does not confirm any transaction labels.

### Refresh after a saved decision

Concurrent refresh requests in one browser share a single load. Focus checks and polling
wait for that load or an active review action to finish, so a slow response cannot be
repeatedly discarded. Open previews retain their originating plan ID and pause automatic
refresh until applied or explicitly refreshed. Old bookmarked plan URLs reuse the latest
verified-current queue, including after a server restart. They never bypass stale-preview
checks or resubmit rejected decisions automatically.
