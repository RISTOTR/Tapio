# Durable, scoped rules for one local user

USER_RULE is distinct from semantic identity facts and inferred category mappings. A rule
is initially SUGGESTED. Only an explicit CONFIRM_RULE or EDIT_RULE in the bounded rule-review
surface creates HUMAN_CONFIRMED rule knowledge. Matching future transactions receive
SUGGESTED labels; the rule never modifies transaction source data or existing human decisions.
Rules are scoped to THIS_USER, not universal financial or tax facts.

The rule page shows source statements and review IDs, confirmed observations, contradictions,
provisional date bounds, semantic facts to be confirmed separately, and a preparation-time
count of unresolved matches. Confirmation uses same-origin browser sessions, signed previews,
expected state, explicit apply, atomic append-only audit and idempotent retry. Revision is
explicit. Pending, rejected and deferred rules do not apply. Arbitrary notes cannot execute.

Supported matching is deterministic: exact entities, existing conservative legal-name/alias
resolution, explicit vocabulary tokens, or bounded transport/date scopes. No embeddings or
model guesses are used. Processor names never match an entity rule: the underlying bank
recipient must resolve. Exact recipient identity needs no Gmail receipt. Evidence mentioning
prepaid is retained as a deterministic source fact independently of the user classification.

A confirmed taxonomy rule can deliberately supply PERSONAL for the matching user vocabulary.
This is explicit user taxonomy, not inference from a restaurant concept. Exact private-road
rules cannot generalize to other roads. Ambiguous retailers cannot receive merchant-wide
rules. Existing hardware identity confirmation remains independent of its blocked mapping.

Precedence is deterministic: transaction-specific human decisions always win; applicable
confirmed scoped user rules supersede weaker document/semantic/history/pattern suggestions.
Exact and trip/date rules retain their own match evidence. Any disagreement between applicable
human rules blocks the affected field with USER_RULE_CONFLICT instead of voting or silently
preferring one human instruction. Existing document, semantic-mapping and history safeguards
remain in the baseline generator. No rule changes tax deductibility or VAT treatment.

Trip rules require explicit start/end booking dates, transport identities/modes and purpose.
A provisional range is not an active trip rule. The reviewer must attest the boundaries and
transport scope, or edit them within the stated envelope. Non-transport merchants and dates
outside the confirmed range cannot acquire the trip context. Booking dates are not claimed
to be actual travel dates. Unrestricted transaction-pattern rules are deliberately disabled.

Repeated-explanation extraction groups bounded normalized subjects, preserving each actual
note and its review/hash/date. Repeated label confirmations are counted separately from
repeated explanations. Current user statements can seed candidates, but cannot manufacture
prior audit events. MISSED_KNOWLEDGE_REUSE requires a matching rule active when the card was
frozen, an unresolved suggested field and a later repeated explanation. Revoked rules and
rules confirmed after the card was frozen do not create false regression flags. Absence of
later observations is reported as NOT_OBSERVED, not claimed as improvement.

Rules and their version are frozen into future bounded windows. Rule decisions stale
unreviewed future cards. Completed windows and their reports remain unchanged. The next
window is blocked until all pending durable-rule candidates have explicit review decisions;
confirming a rule does not itself open a window or classify any transaction. Only an explicit
next-window action creates the next numbered window. Rule provenance appears on each matched
card, and transaction confirmation audits retain the rule evidence shown to the reviewer.
