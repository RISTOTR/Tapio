# Persistent bounded review and semantic concepts

The persistent queue is a signed, private manifest of at most 1,000 eligible transaction
IDs. It exposes one frozen working window, normally 30 cards (configurable 25–50), with
a smaller final remainder. Pending IDs are not writable. Each window retains its own
source/current-state/suggestion/receipt/concept/knowledge snapshots, baseline review
revision hashes, append-only human audits, SKIP metadata and reports. Window archives
are never removed by pagination.

The UI shows READY, CONFIRMED, CHANGED, SKIPPED, STALE and BLOCKED within the active
window, and a PENDING count outside it. An explicit Next bounded batch action is allowed
only once the current window is terminal. No background review or confirmation exists.
The prior service is disabled as soon as the active window changes. Old preview tokens
cannot authorize a new window. Source and review fingerprints, browser session/CSRF,
preview signatures, per-card hashes and immediate state checks remain in force.

Concept decisions alter the knowledge version and stale unreviewed cards. The user may
explicitly refresh a stale window; the old frozen window remains archived and the new
window uses current evidence. Already reviewed decisions remain authoritative. Source
identity problems block preparation; no stale snapshots are silently regenerated.

## Candidate interpretation, approval and reuse

Knowledge supports MERCHANT_TYPE, VOCABULARY_CONCEPT, RECIPIENT_CONCEPT, BUSINESS_TYPE
and PURCHASE_PURPOSE_CONCEPT, with the existing four authority levels. Initial generation
uses a bounded explicit lexicon to propose merchant/recipient/vocabulary concepts from
repeated human-confirmed category observations. Review-note terms can also propose
candidates. These seeds interpret meaning; they are not accepted source facts. A free-text
note cannot become a global category/context rule.

Each candidate records exact transaction and review IDs/hashes, observed categories and
contexts, matching term/mode and any note. The separate concept-review page allows
CONFIRM_CONCEPT, EDIT_CONCEPT, REJECT_CONCEPT and DEFER, with signed preview and explicit
final click. Append-only decisions preserve candidate snapshots and prior decisions.
Only explicit approval creates HUMAN_CONFIRMED concept claims. No transaction changes
from a concept-review action. Rejected/deferred concepts are not used; conflicting approved
concepts or conflicting category observations block affected suggestions.

An approved concept + exact visible token/chain/recipient match + at least two agreeing
human category observations can support a SUGGESTED category. No majority vote is used.
The target transaction is excluded from its own support. The offline unseen-identity
experiment additionally excludes all exact target identity observations.

The initial category mappings are grocery retailer→GROCERIES, restaurant→OTHER,
vehicle inspection/service→MAINTENANCE, insurer→INSURANCE, bus operator→TRAVEL,
electricity supplier→ELECTRICITY, general retailer→OTHER and recreation permit→OTHER.
Hardware mappings are now blocked pending separate mapping validation; see concept-state-repair.md.
Mappings are suggestion policy, not source truth. Existing human labels are never overwritten.

No semantic concept creates PERSONAL, PROPERTY or FORESTRY. Existing independently
supported narrow context suggestions may remain, but all multi-context merchants and
Paytrail keep their restrictions. Blocked generalizations have explicit reason codes.
No tax deductibility, VAT treatment or expense eligibility is inferred.

Paytrail contributes no category concept. Only an explicit underlying recipient can
match a concept. A matched receipt may supply recipient identity; a payment confirmation
alone does not identify product/service purpose. Ambiguous/candidate receipt relationships
and conflicts block semantic recipient reuse. Gmail remains read-only; this phase reuses
existing receipt evidence and does not perform fresh mailbox searches.

## Evaluation and limits

Actual unapproved concepts have zero live effect. The offline report separates this
baseline from a counterfactual assuming explicit concept approval. That scenario is not
persisted as production knowledge or human decisions. It reports actual unresolved/unseen
transaction matches, category abstentions before/after, exact concept provenance,
blocked conflicts and newly added contexts. Unresolved targets lack ground-truth labels,
so category accuracy/usefulness and a causal benefit cannot yet be established.

Review analytics retain the five field outcomes. Semantic acceptance/change counts are
separate from general CONFIRM/CHANGE clicks; SKIP is not counted as semantic rejection.
Explicit concept rejection is tracked in its own append-only ledger. Success requires
human-reviewed usefulness without unsafe context inference, not a larger suggestion count.

Private artifacts are in `data/interim/persistent_review`. No benchmark/holdout evaluation,
model call, source mutation, automatic concept promotion or autonomous classification is
part of this workflow. A future concept extractor may use an LLM to propose candidates,
but the current bounded implementation uses deterministic explicit terms only.
