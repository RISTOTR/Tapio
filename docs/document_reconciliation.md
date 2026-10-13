# Bank and invoice reconciliation

Reconciliation preserves source transactions and documents. It adds proposed or
confirmed TransactionInvoiceAllocation links and independent refund/debit candidates.
All calculations use Decimal. Classification labels and tax reviews are not inputs.

```sh
uv run python -m data_pipeline.reconcile.invoices --account-key primary
# Explicitly confirm only eligible exact matches; preserve previous evidence.
uv run python -m data_pipeline.reconcile.invoices --account-key primary --confirm-exact
```

The command prints aggregate counts only. Detailed IDs and evidence stay in the
private database. The scope is one bank source/account namespace in EUR and all
loaded invoices; zero/negative payable invoices are not automatically matched.

## Deterministic signals

Version `invoice-match-2` compares exact normalized vendor identities using existing
explicit bank aliases. Payment intermediaries use the recorded ultimate recipient.
No fuzzy vendor search, free-text invoice-number substring match or amount-only
matching is used.

A debit becomes a candidate when the vendor matches, booking is within 31 days before
through 90 days after due date, and either amount is within EUR 0.01 or the payment
reference matches. Reference-supported partial and bulk payments can therefore be
proposed without pretending that amount equality holds.

Evidence stores exact amount status/difference, reference support/presence, date gap,
window, rule version and score components: vendor 40, exact amount 30 (near amount 10),
reference 50 and date 10. Scores are audit signals, not calibrated probabilities;
`match_confidence` remains null. Thresholding a score does not confirm an allocation.

Whitespace is removed from references. For ASCII numeric references up to 20 digits,
leading zero padding is equivalent only when the resulting domestic reference has
at least four digits and a valid 7/3/1 checksum. This follows
[Finance Finland's reference-number specification](https://www.finanssiala.fi/wp-content/uploads/2021/03/Forming_a_Finnish_reference_number.pdf).
Original reference strings remain untouched. RF references are compared literally
after whitespace/case normalization; no RF-to-domestic conversion is implemented.

## Candidate versus confirmed

Migration 0005 adds status (CANDIDATE, CONFIRMED, REJECTED), evidence and created_at,
and a unique transaction/invoice pair. Existing legacy links default conservatively
to CANDIDATE. A normal run never confirms. `--confirm-exact` confirms only when:

- normalized vendor and invoice amount match exactly;
- booking is in the declared date window;
- the invoice and transaction each have one candidate, including refund competition;
- no existing active allocation competes on either side, including other accounts;
- the invoice reference matches if one is printed.

Explicit re-evaluation can promote a machine-generated candidate with unchanged
allocation amount. Previous evidence/status and the re-evaluation timestamp are
retained. CONFIRMED and REJECTED decisions are never overwritten. Exact re-runs do
not add duplicate allocations or duplicate audit snapshots.

## Many-to-many and signed amounts

Allocation amounts are settlement contributions: positive for debit payments,
negative for incoming refunds. Candidate partial/bulk amounts use the smaller of
the debit magnitude and invoice total. They are proposals, never a balance assertion.
The model supports multiple transactions per invoice and multiple invoices per
transaction. Bulk candidates require explicit common-reference support; this phase
has no arbitrary subset-sum allocator or manual allocation confirmation UI/CLI.
Only mutually unique full-payment candidates are eligible for automatic confirmation.

Refunds require an equal-amount later credit from the same normalized vendor and
account, within 365 days of a candidate debit. Every possible pair is retained in
TransactionReversalCandidate. A refund is linked once per invoice in allocations,
with all possible debit IDs in its evidence; it is never auto-confirmed. A credit
with two possible debits produces two reversal candidates, not a chosen reversal.

## Computed states and duplicate payments

Only confirmed allocations count toward confirmed paid/refunded/net totals. An active
candidate makes the invoice AMBIGUOUS. Otherwise net above total is OVERPAID, equal
is PAID, positive below total is PARTIALLY_PAID, a fully returned payment is REFUNDED,
and no confirmed settlement is UNMATCHED. REJECTED links do not contribute.

The report separately counts exact debit candidates, distinct refund credits and
possible reversal pairs. Two equal debit candidates and one equal refund can have a
candidate net consistent with one intended payment. This is disclosed as an
invoice-level consistency observation; it does not turn uncertain links into
confirmed allocations. Competing invoice candidates prevent that conclusion.

The real MHY case satisfies this pattern. Its source debit/debit/credit remain three
independent immutable facts, both reversal possibilities remain candidates, and the
invoice remains AMBIGUOUS pending human review.

## Limits

Results describe the currently loaded invoices and selected bank account. Missing
invoices or future transactions may introduce new competition. Confirmation does
not prove tax treatment or underlying delivery. Manual partial/bulk/refund decisions,
retractions and corrections require a future audited workflow. Re-running never
silently rewrites a finalized decision. Refund proposals do not establish which
specific payment was reversed.
