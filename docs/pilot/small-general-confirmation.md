# Small general human-confirmation pilot

The active profile is explicitly selected with `TAPIO_CONFIRMATION_BATCH=GENERAL_V1`.
It reads only `data/interim/general_confirmation/preview.json`, a frozen 15–25-card
allowlist with batch ID, transaction identities, complete card/evidence snapshots,
knowledge version, original source/review fingerprints and historical revision hashes.
Writes also require `TAPIO_CONFIRMATION_WRITES=true` and a matching implementation and
whole-batch verification seal. No arbitrary batch path or transaction ID is accepted.
The original five cards are excluded from this batch and their records are unchanged.

The preparer selects diverse cases deterministically and refuses to overwrite a frozen
batch. Before activation, an unused candidate was retained separately because counting
Paytrail as multi-context did not ensure any non-processor ambiguous retailer was included.
The final batch explicitly includes those retailers. No human review of the candidate ran.

Source identity, accepted human labels and unresolved reversal exclusions are checked
before selection. The EUR 588.07 ambiguity is excluded. A recipient name alone does not
prove purchase purpose. Paytrail classifications distinguish explicit source/document
purpose, partial evidence with agreeing recipient-scoped human category observations,
and opacity. Opaque cases abstain. Paytrail never supplies a context rule. Merchant
identity cannot supply context for known ambiguous retailers or merchants with multiple
observed contexts. Document candidates retain their relationship status.

The page displays batch identity and progress. Only supported fields offer CONFIRM
actions; abstentions offer CHANGE and SKIP. Manual CHANGE requires selecting each field
individually. Preview and final apply are separate actions. Unselected fields are left
unresolved. SKIP records batch/card/time only and changes no classification or authority.
The immutable source messages, recipients/references, document matching status and
existing evidence remain visible. The workflow contains no tax-treatment decision.

Each successful decision appends its batch/card IDs, original suggestions/reasons,
source/document/knowledge evidence, old/new values, selected fields and human event IDs.
The monitor verifies that all historical revisions retain their hashes and that every
new revision belongs to this batch. It checks source/legacy-review fingerprints and
replays only permitted derived knowledge. Corrections retain old audit entries but
supersede their active field observations. The required correction exercise uses a
disposable test-schema transaction; no real label is changed to manufacture a test.

The private report separates actions, distinct cards, partial fields, corrections,
Paytrail outcomes, abstentions, proposal/final differences and reason-code exposure.
Reason-code outcomes are associations, not proof that a particular message caused a
decision. This is a workflow pilot, not a model-accuracy benchmark. Final recommendation
and post-pilot verification remain pending until the user reviews the frozen batch.

No additional cards, general write access, background confirmation, benchmark execution
or automatic promotion of previous feedback is enabled by this profile.
