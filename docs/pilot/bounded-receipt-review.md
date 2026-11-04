# Bounded review with receipt provenance

The `BOUNDED_CONFIRMATION_V1` profile accepts 25–50 frozen cards (default 30).
Preparation refuses to overwrite an existing batch. An operator must finish and
archive the active batch before preparing another; there is no arbitrary-transaction,
bulk-confirm or background write route. The server accepts only a sealed fixed local
batch. Every action still requires browser session, same-origin CSRF, a signed preview
and a separate explicit final click.

Eligibility includes unresolved and partially human-reviewed transactions. Fully
confirmed transactions (including deliberately confirmed UNKNOWN), unstable identities,
reversal conflicts and the excluded reconciliation amount are ineligible. Existing
human fields are not resuggested. Completing a partial review appends to its existing
revision chain; changing an already confirmed field requires an explicit correction
reason. Prior audit and human evidence remain preserved.

## Receipt resolution

`integrations.gmail.receipts.ReceiptSearch` constructs at most four literal searches
per Paytrail transaction, each within a configurable 0–7 day window. It uses exact
amount variants, Paytrail, an explicit payment reference and the bank recipient.
Queries cannot introduce Gmail operators through source strings. Every query returns
at most 20 messages; pagination marks the result incomplete and cannot yield a resolved
match. The initial implementation does not broaden date windows, follow links or
read attachment bytes. Attachment metadata is retained for manual follow-up.

The existing connector verifies the **actual** OAuth grant is exactly `gmail.readonly`.
Receipt resolution calls only `messages.list` and `messages.get`; it cannot send,
draft, mark, move, archive, delete or label mail. OAuth renewal updates the local token,
not mailbox state. No model is used. Existing Gmail private cache policy applies.

A match requires one plausible message, exact unambiguous EUR amount, a close date,
and an explicit reference or exact labeled merchant match. Numeric reference leading
zeros are formatting only; original bank and email values remain visible. Conflicting
payment references, truncated bodies and incomplete searches cannot resolve a match.
A matching amount alone is insufficient. Multiple plausible messages remain ambiguous,
even when they may be a payment confirmation and its itemized receipt.

Statuses: RECEIPT_MATCHED, RECEIPT_CANDIDATE, MULTIPLE_RECEIPTS, NO_RECEIPT_FOUND,
INSUFFICIENT_RECEIPT_EVIDENCE. Absence is displayed as
NO_RECEIPT_FOUND_IN_AVAILABLE_MAIL: older receipts may have been deleted. Keeping
future receipts improves available evidence; Tapio implements no retention policy.

The parser distinguishes payment confirmations from receipt/order candidates. A
matched payment confirmation identifies payment facts, not item-level purchase purpose.
Explicit labeled facts retain message/thread IDs, source hash, location/snippet,
extraction version, authority and retrieval time. Full email bodies are not copied
into knowledge. Extracted facts are DETERMINISTIC_SOURCE_FACT; candidate links remain
CANDIDATE. No alias, vocabulary or merchant-wide rule is created merely from a match.

Only explicit supported product/service descriptions can add a category suggestion.
Receipt-derived context is not guessed. Paytrail and multi-context retailers never
supply a context rule. Human, bank or document conflicts are shown for review and do
not overwrite existing values. Classification remains SUGGESTED until the user acts;
no tax deductibility, VAT treatment or expense eligibility is inferred.

## Frozen evidence and field outcomes

Cards contain frozen source, suggestion, receipt and knowledge versions. Preview and
commit verify the card hash, receipt-registry version and current local Gmail content
version; a refresh that changes evidence blocks the old card with STALE_STATE. Source
and human-review state are checked immediately before classification writes. Review
does not silently fetch or replace Gmail evidence; externally changed mail that has
not been refreshed is explicitly outside this local snapshot check.

UI actions stay CONFIRM / CHANGE / SKIP. Each field records:

- SUGGESTION_ACCEPTED: explicitly selected value equals the shown proposal.
- SUGGESTION_CHANGED: explicitly selected value replaces a shown proposal.
- MANUALLY_COMPLETED: explicitly selected value has no proposal.
- LEFT_UNRESOLVED: no selection and no human-confirmed value.
- NOT_APPLICABLE: untouched field already has a human-confirmed value.

New append-only audits record the outcomes and receipt snapshot; human-event provenance
also records the selected field's outcome. Primary analytics count field outcomes,
not CHANGE clicks. Thus accepting a proposed category and adding a missing context is
one accepted suggestion plus one manual completion. SKIP creates no classification or
human-confirmed event. Previous pilot reports and action interpretations are not rewritten.

Private artifacts under `data/interim/bounded_confirmation` retain bounded-search
results, the frozen batch, source/knowledge provenance and verification. The first batch
is prepared and activated only after tests and integrity checks pass. It remains entirely
unreviewed until the user acts at `/pilot/confirmation`.
