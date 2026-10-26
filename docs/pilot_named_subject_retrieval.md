# Pilot named-subject retrieval repair

The accepted agent and evidence policy are unchanged. This repair adds a deterministic,
read-only subject lookup in the pilot wrapper after accepted final validation and before
the existing source postflight check. Its evidence and identity trace are stored separately
in private question history; they do not manufacture agent handles or satisfy missing
mandatory evidence. An invalid accepted answer still fails before subject lookup.

## Observed failure

The retained successful Vattenfall and Oikea questions had no extracted subject, normalized
subject, subject type or merchant/provider filter. Their effective plans used UNSPECIFIED
context. Both invoked `summarize_finances`, `list_documents`, `find_invoices`, and three
`get_invoice_reconciliation` calls. Neither invoked `query_transactions`.

Each run returned one broad bank aggregate (170 transactions), six documents, three
invoices and three reconciliation results. All were scoped to 2026, including the undated
Oikea question. Context and category filters were null. There was no reviewed-only or
required-document transaction filter: the named bank lookup never happened. Model plan
question types differed (comparison for one Vattenfall run, overview for Oikea), but neither
provided a subject route. The presentation then looked for names in retrieved transaction
rows and document vendors; absent matching retrieved evidence became a misleading no-match.
`pay` was also absent from its financial-intent matcher.

The existing transaction tool filters only `normalized_counterparty` with a case-insensitive
substring. It does not search the ultimate recipient or payment intermediary. Document and
invoice tools separately search vendor fields. Bank normalization already handles case,
whitespace, periods and a small exact alias map; it does not expand arbitrary truncated card
descriptors. Thus a full Oikea name would still miss its stored descriptor even if supplied
to that tool. This repair leaves those frozen tool definitions and implementations untouched.

## Subject resolution and scope

The pilot recognizes explicit single-subject payment, evidence and deductibility question
forms. It records extracted text, normalized text, NAMED_ENTITY type, explicit year and
matched identity fields. Resolution priority is exact normalized identity, exact alias,
then unambiguous legal-suffix equivalence (Oy/Oyj/ry). Conflicting identities return
AMBIGUOUS_IDENTITY; no approximate or fuzzy matching is used.

Identity comes from normalized counterparties, ultimate recipients, payment intermediaries,
invoice vendors and document vendor metadata. It does not use arbitrary message text.
The imported truncated Oikea descriptor has one explicit identity-only alias. It supplies
no category, context or tax decision, and does not change persisted normalization or labels.

The result distinguishes MATCH_FOUND, NO_MATCH and AMBIGUOUS_IDENTITY. Matching rows,
documents, invoice reconciliation, human labels, coverage and match provenance are retained.
An explicit year restricts evidence dates; an undated named discovery searches all imported
dates, with that scope displayed. No context, category, review status or document-presence
filter can suppress matching bank rows. Bank totals use complete matching rows, Decimal
arithmetic and separate currencies; the bounded lookup fails closed instead of summing a
truncated result. Identity inventory and each evidence collection are capped at 1,000 entries.

Public details use the existing identifier-redacted projections. Private history retains
source IDs and the matched identity names. The accepted original answer, references,
financial renderer, model configuration, feedback and source checks remain unchanged.
The new subject card contains only matching evidence. Tax intent is determined from the
question, not a generic backend message; actual tax questions still receive the boundary.
The two retained failing examples used the `results` message key, so tax routing was not
their observed cause. A separate regression guards the former message-triggered fallback.

## Local results

Private read-only results and traces are stored under `data/interim/pilot_named_subject/`.
Vattenfall matches its normalized legal entity through safe legal-suffix resolution.
Its supported 2026 bank payments total **€965.79 across nine debits**. No invoice/document
in the requested 2026 period was found; undated discovery finds 21 bank rows and two
invoice source documents, with reconciliation available. Invoice availability is not
required for the bank total. Observed imported dates do not prove a complete statement.

Oikea matches through the exact truncated-descriptor alias. It has **one debit of €134.05,
dated 2026-06-02**, already human-confirmed FORESTRY / MAINTENANCE. These human decisions
remain authoritative; the identity alias does not establish them. No matching document
was found. Unreviewed synthetic Oikea rows retain unresolved context, even when their weak
source suggestion says FORESTRY. Neither human context nor merchant identity decides tax
eligibility. An unseen merchant returns genuine NO_MATCH.

## Verification

Focused regressions cover extraction, case/period/legal-suffix/alias matching, identity
collisions, unknown merchants, recipient versus processor, dates, bank-only and document-only
matches, authoritative human labels, unresolved context, tax routing, complete-row bounds,
private provenance and preservation of the accepted validation gate. Final full verification
results are recorded below when complete. No live model or benchmark run is part of this task.

The verified identity paths are:

| Query text | Stored normalized identity | Resolution |
| --- | --- | --- |
| Vattenfall | Vattenfall Oy | Unique legal-suffix match |
| Oikea Konekauppa | oikea konekaupp viitasaari | Explicit identity alias |

The raw bank descriptors are `Vattenfall Oy` and `OIKEA KONEKAUPP     Viitasaari`,
respectively. Both have null processor/ultimate-recipient fields in these matching rows.
The previous year filter was not the cause for Oikea's observed transaction (it is in 2026),
but defaulting undated subject discovery to the current year was an unnecessary restriction.
The retained tax-mode example was an actual deductibility question; no recorded non-tax
example demonstrated erroneous TAX_BOUNDARY routing. The removed backend-message trigger
was a potential presentation defect, not evidence of a failed-retrieval-to-tax route.

Changed implementation files are `tapio/pilot/named_subject.py`, `service.py`,
`presentation.py` and `answer_cards.py`. Tests are in `test_pilot_named_subject.py`;
the existing `test_pilot.py` fixture now explicitly injects a no-I/O subject lookup,
just as it already injects model, registry and fingerprint dependencies. Its original
assertions are preserved, and the new integration test exercises the real lookup.

Final verification: **925 tests passed**, preserving all 901 prior tests and adding 24
focused cases. Ruff, formatting, diff and Alembic checks passed. The full privacy scan
checked 265 files with zero findings and the private denylist loaded; subsequent edits
also passed a focused privacy check. All 14 source-table fingerprints and accepted core,
configuration, snapshot and holdout/manifest byte hashes remained unchanged. The historical
check covered 1,543 hashes with only the two previously documented hygiene exceptions.

Both retained named-subject plans and their original final references were replayed against
the read-only database, passed the unchanged validator, and retained six required handles
each. The repaired public results matched the local values above. This was an offline
counterfactual replay, not a live model run or a rewrite of historical scores. No source
or label changes, context inference or tax decisions were made. The human-supervised
read-only pilot can resume after restarting its local server to load these changes.
