# Read-only suggestion-card pilot

A fixed batch of 16 unresolved transactions is generated explicitly from the retained,
replay-verified knowledge snapshot and a read-only source connection. No model is used.
The generator never runs in the background. Fully human-reviewed rows are ineligible;
known fields in partially reviewed rows remain authoritative.

`Card` contains the transaction, current state, separate nullable category/context
suggestions, reasons with evidence references, provenance-bearing evidence, knowledge
IDs, warnings, priority, rule version and selection tags. Every recommendation is
`SUGGESTED`; every card is `READ_ONLY`. Exact provenance and internal IDs stay in the
private batch/report; the browser receives concise summaries and an opaque card ID.

The deterministic rule uses other accepted human-reviewed observations of the exact
merchant. A field is suggested only when its observed non-UNKNOWN values agree.
Category and context are independent. Merchant-policy ambiguity blocks inherited
context; disagreements do not use majority voting. Candidate/ambiguous reconciliation
links block both recommendations. Vocabulary, repeated occurrence and document links
explain review opportunities; they do not independently assign labels or tax treatment.
Priorities describe review value, never numeric confidence.

Selection reserves available examples of explicit retailer policy, ambiguous reversal,
multi-context observations, conflicting observations, document relationships, consistent
history, literal source matches, recurrence and unknown purpose. Remaining slots favor
distinct merchants in stable date/ID order. Missing sample types are not invented.

## Manual review

Open http://127.0.0.1:8011/pilot/suggestions (also linked from the pilot home page).
Read the current state, suggestion, explanations, evidence authorities and warnings.
Choose CORRECT, PARTIALLY_USEFUL, WRONG, INSUFFICIENT_EVIDENCE or SKIP, optionally add
an evaluation note, and click **Save evaluation feedback**. No choice is preselected.
CORRECT is usefulness feedback, not confirmation of a transaction label.

The only POST operation writes a private append-only feedback JSON file under
`data/interim/suggestion_pilot/feedback/`. It retains the card/transaction reference,
suggestion snapshot, choice, note, timestamp and batch/card hashes. Feedback has no
source, review, reconciliation or knowledge write connection. Repeated submissions
remain in the audit trail; metrics count the latest explicit response per card.
Metrics break down by priority, reason, merchant, input authority and suggestion
availability. Overlapping groups are explicitly labeled; these are not accuracy metrics.

`batch.json`, `report.md`, `summary.json` and `integrity.json` in that private directory
retain the offline audit. API access rechecks all source fingerprints and fails closed
if the source snapshot changed. A changed batch requires a separate explicit generation
and review cycle; it cannot overwrite the fixed batch.
