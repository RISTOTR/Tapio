# Uncertainty-aware bounded review

An explicit UNKNOWN field is HUMAN_CONFIRMED_UNKNOWN, distinct from an unreviewed field,
an unresolved field, and a confirmed known value. Transaction decisions take precedence
regardless of whether their value is UNKNOWN. Corrections append review revisions; current
projections use the latest explicit field decision and retain original audit history.

Exact-identity UNKNOWN observations are displayed on later cards. Multiple distinct reviewed
transactions yield REPEATED_UNKNOWN_MERCHANT, not a merchant-wide rule. Weak history and
semantic suggestions abstain for the affected field. A separately confirmed scoped user rule
or transaction-specific receipt can provide new evidence on a different transaction; neither
can replace an UNKNOWN decision on the original transaction. Processor identities never pool
uncertainty about different recipients. No UNKNOWN is converted to OTHER.

New semantic interpretations, category mappings and user rules have separate review surfaces.
Supplemental semantic candidates remain SUGGESTED until an explicit, audited decision. New
category mappings additionally require independent mapping approval and at least two current
agreeing category observations. Unknown, conflicting, hardware-policy and government-identity
mapping restrictions remain enforced. Semantic identity never supplies context. An airline
identity does not prove a ticket purchase; onboard-purchase history can block a travel mapping.
No knowledge layer decides tax deductibility.

Vocabulary matching folds case, accents, spacing and punctuation and recognizes bounded bank
prefixes, while preserving original evidence. Tokens have word boundaries. Concatenated chain
names require a scoped exact observed identity rather than permissive substring matching.

The offline consolidation separates accepted suggestions, manually completed known values,
and confirmed uncertainty. Reports include field-level audit IDs, corrections, exact-history
friction, available-at-creation user-rule audits and reason-coded abstentions. Historical
windows and source data are not rewritten. New bounded windows freeze uncertainty, mapping,
concept and user-rule versions and retain all matched decision provenance. Pending optional
concept/mapping candidates are not needed to open a window using existing knowledge.

Synthetic tests cover uncertainty that is absent from a particular real queue. A report must
not fabricate UNKNOWN controls, missing-reuse failures, or benefit from candidate activation.
