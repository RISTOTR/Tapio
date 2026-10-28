# Fixed five-card human confirmation pilot

Only the five existing cards in the hashed preview allowlist can be confirmed. The
other suggestion pages remain read-only. The local flag must be true and the
current implementation/batch verification seal must match. There is no bulk action.

Open `/pilot/confirmation`. Choose CONFIRM, CHANGE or SKIP for each card. Category
and context checkboxes start unchecked. Preview displays the current authoritative
state and selected field differences; only a separate apply click writes a decision.
SKIP has its own final click and records private review-attempt metadata, never a label.
Opening a page and previewing a card create no review/audit/event records.

Cards show READ_ONLY, READY_TO_CONFIRM, CONFIRMED, CHANGED, SKIPPED or STALE. A stale
preview cannot overwrite newer decisions. Refresh and obtain a new preview before
correcting an earlier confirmation; corrections require a reason and preserve history.

Current review state is a projection of the append-only confirmation ledger over
legacy reviews. Legacy human-review rows are deliberately preserved, not updated in
place. Every explicit decision contains independent field authority, source/evidence
shown, the original SUGGESTED proposal, and its HUMAN_REVIEW_CONFIRMED event.

After each explicit action the bounded local coordinator verifies the source and
legacy review fingerprints, every ledger entry's allowlisted transaction and event,
and its current review state. It replays human-dependent derived knowledge into a
new content-addressed private bundle. No unconditional merchant rules are generated.
If verification fails after commit, the response says the write was recorded and
blocks further writes; it does not falsely suggest rollback or automatic retry.

Private `data/interim/controlled_confirmation/report.json` reports per-card states,
action/partial-field/stale counts, audit and event counts, and knowledge differences.
Repeated delivery of a signed action does not duplicate a revision or skip attempt.
Corrections count as additional actions; cards reviewed counts distinct cards.

The implementation seal is `data/interim/controlled_confirmation/verified.json`;
the previous phase's dry-run seal and reports remain historical and unchanged.
The recommendation remains KEEP_FIXED_BATCH_ONLY until all five human decisions and
the subsequent full test/integrity verification are complete. Workflow results are
not model accuracy. No benchmark/model/Gmail execution is part of this pilot.
