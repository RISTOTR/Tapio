# Document ingestion and reconciliation review — 2026-10-13

## Delivered

Source-specific local PDF extraction, typed validation, atomic document ingestion,
structured persistence, deterministic bank/invoice candidates, explicit exact-match
confirmation and independent refund/debit candidates are implemented. No classifier
optimization, OCR, LLM, embedding, frontend or tax automation was added.

New code: `data_pipeline/documents/` (canonical contract, detection and five parsers),
`data_pipeline/ingest/documents/` (extraction, loader and CLI),
`data_pipeline/reconcile/invoices.py`, `data_pipeline/verify_documents.py`, synthetic
fixture helpers, parser/import tests and reconciliation tests. Updated files include
domain models, pyproject.toml/uv.lock (pypdf only), README, architecture and dictionary.
The ingestion and reconciliation guides describe the exact supported workflow.

Migration **0005** adds InvoiceLine source metadata; allocation status, evidence,
created_at and pair uniqueness; and TransactionReversalCandidate with indexed source
foreign keys. No previous migration was edited. Existing document enum values and
invoice identity constraints are retained. Contract/tariff facts use document metadata.

## Real source verification

All **eight target documents** parsed successfully: two Vattenfall invoices, the
September 2026 Elenia bill, both Elenia contracts, both requested MHY invoices and
the forestry sale summary. An additional historical utility scan examined eleven
paths: four more invoices were accepted, one was an exact duplicate, and six failed
explicitly. Overall: **19 paths, 12 unique imported documents, 1 duplicate path,
6 unsupported files**. Failed attempts have audit records and no structured rows.

Stored and independently verified:

| Record | Count |
| --- | ---: |
| Documents | 12 |
| Invoices | 9 |
| Invoice lines | 40 |
| EnergyBillDetails / separate usage-point components | 14 |
| Grid contracts in structured document metadata | 2 |
| Forestry sales | 1 |
| Forestry sale lines | 24 |

Every successful exact re-import returned already_imported without new facts.
Re-extraction from original bytes matched private canonical metadata. The verifier
compared all persisted header/line/energy/sale fields with that projection. Source
bank transactions, human classification reviews and energy readings were fingerprinted
before/after; counts and content were unchanged.

### Invoice amounts

| Source | Subtotal / VAT where central to acceptance | Gross EUR |
| --- | --- | ---: |
| Vattenfall, September 2024 billing | 66.34 / 16.92 | 83.26 |
| Vattenfall, January 2025 billing | 150.81 / 38.46 | 189.27 |
| Elenia, September 2026 billing | 69.54 / 17.73 | 87.27 |
| Additional historical Elenia invoice | verified from source | 193.92 |
| Additional historical Elenia invoice | verified from source | 178.51 |
| Additional historical Elenia invoice | verified from source | 172.88 |
| Additional historical Elenia invoice | verified from source | 77.86 |
| MHY 25749 | 468.58 / 119.49 | 588.07 |
| MHY 27789 | 668.53 / 170.48 | 839.01 |

All accepted invoice gross-line/header differences are **EUR 0.00**. Net/VAT sums
also match wherever individual net/VAT line amounts are printed. No balancing or
replacement amounts were invented.

Vattenfall September consumption is **814.54 kWh**, with EUR 5.04 base fee and
EUR 79.81 energy charge at a printed 9.80 snt/kWh. Separate export is **17.34 kWh**:
EUR 0.06 margin and EUR -1.65 spot-energy value, total EUR -1.59. Consumption total
EUR 84.85 plus export total EUR -1.59 equals payable EUR 83.26. January consumption
is **2,064.35 kWh**, EUR 5.95 base + EUR 183.32 energy; export is **0.00 kWh** and
EUR 0.00. Usage points remain distinct and are omitted from this public report.

Elenia September 2026 consumption is **707.43 kWh**. Printed gross lines: base
EUR 47.10; winter-day transfer 0.00 kWh / EUR 0.00; other-time transfer 707.43 kWh /
EUR 19.53; electricity tax 707.43 kWh / EUR 20.64. Product is Vuodenaikasiirto 3x25 A.
Production-side transfer is **19.63 kWh / EUR 0.00**, with a separate EUR 0.00 base
line. Printed rates are retained, including the rounded tax rate; no simulation
or inference of gross PV generation is performed.

MHY 25749 retains product M1305, its multi-line description, **509.33 m3 × EUR 0.92**,
net EUR 468.58, VAT 25.5% / EUR 119.49 and gross EUR 588.07. MHY 27789 retains product
M307 / Laikkumätästys, **1.1 ha × EUR 607.75**, net EUR 668.53, VAT EUR 170.48 and
gross EUR 839.01. Totals were parsed, not embedded in parser code.

Both contracts preserve their consumption/production roles, separate usage points,
contract numbers and effective dates. The attached price sheets are dated 1 April
2026. Printed seasonal time/rate rules and the conditional production-fee exemption
are retained as metadata without calculating hypothetical costs.

### Forestry sale

| Measure | Printed total | Sum of parsed lines | Difference |
| --- | ---: | ---: | ---: |
| Contract quantity m3 | 581.42 | 581.42 | 0.00 |
| Contract value EUR | 29,872.54 | 29,872.54 | 0.00 |
| Actual quantity m3 | 681.42 | 681.42 | 0.00 |
| Actual value EUR | 37,712.50 | 37,712.50 | 0.00 |

All 24 harvest/assortment lines remain separate. Printed line quantity × price
calculations also reconcile. Planned cells absent from the source stay null.

## Bank reconciliation

There are **8 exact debit candidate links** across seven invoices. **6 unique links
are confirmed**, using exact vendor/amount, date window and checksum-validated
reference support. The two debit candidates for MHY 25749 remain unconfirmed.
One additional refund allocation candidate and two independent reversal pairs are
retained. Re-running reconciliation produces the same counts and states.

Invoice states: **6 PAID, 1 AMBIGUOUS, 2 UNMATCHED**. The unmatched invoices are the
older September 2024 Vattenfall bill and the September 2026 Elenia bill; no qualifying
payment exists in the selected bank snapshot. No invoice is confirmed PARTIALLY_PAID,
OVERPAID or REFUNDED. These states are computed, not written onto source invoices.

For MHY 25749, **two EUR 588.07 debits** and **one later EUR 588.07 credit** yield
candidate net settlement **EUR 588.07**. Both debits have reference support; the refund
is linked through same vendor, amount and later date. Both possible reversal pairs
are preserved. The invoice-level net is consistent with one intended payment, but
which debit was reversed remains unresolved. The stored state is **AMBIGUOUS**.
The separate EUR 839.01 MHY invoice has an unambiguous confirmed payment.

Initial matching exposed bank references padded to 20 digits. The final rule uses
checksum-validated domestic-reference equivalence; original strings remain intact.
Explicit re-evaluation retains earlier candidate evidence when confirming a link.

## Unsupported historical files and exact differences

Six extra historical sources were rejected without structured insertion:

- One older Elenia final-bill header layout lacks the supported header labels.
- One Vattenfall file contains an additional EUR 5.00 component outside the supported
  consumption/export layout; consolidation fails instead of dropping that component.
- One Elenia component has line-sum minus header differences of **net +EUR 0.01,
  VAT -EUR 0.01, gross EUR 0.00**. Strict component equality rejects it.
- One older Vattenfall PDF has an image-only/empty text page; OCR was not introduced.
- One Vattenfall file contains an additional EUR 2.59 component outside the supported
  consumption/export layout; component validation rejects it.
- One historical Elenia layout produces an unsupported component extraction difference
  of **net +EUR 141.84, VAT EUR 0.00, gross +EUR 141.84**. This is a parser-layout failure,
  not a claim that the source invoice is wrong.

These failures are deliberate boundaries, not forced agreement. Original files remain
unchanged and private. Wider utility-layout coverage is a separate follow-up.

## Validation and next step

Synthetic tests cover generated-PDF extraction, both MHY layouts, all utility lines,
usage-point separation, contract facts, sale differences, Decimal/VAT validation,
source provenance, concurrent idempotency, parser revision conflicts, atomic rollback,
unsupported input, matching/reference rules, partial/bulk proposals, duplicate/refund
ambiguity, computed states, rejection preservation and migration up/down/up.

Final verification: **316 tests passed**. Ruff format/check, git diff --check,
dependency lock validation and local Alembic check passed. Migration 0005 up/down/up
and schema comparison passed in a disposable PostgreSQL schema. All three real-data
CLIs passed, including exact re-import and source re-extraction verification.

A privacy scan of all **27 changed/new files** found no known source identifiers or
binary fixtures after replacing a pre-existing usage-point identifier in README with
a placeholder. Private artifacts are gitignored. Source transaction, classification
review and energy-reading fingerprints remained unchanged. No real PDF text, bank
account numbers, payment references, personal names or addresses were added to fixtures
or documentation.

**Exact next step:** manually review the retained three candidate allocation links
for MHY 25749 and both refund/debit possibilities using the private source documents
and bank entries. Keep the relationship ambiguous unless independent evidence resolves
it. Any confirmation or correction beyond the exact-match rule should first use an
explicit audited review workflow. Do not resume classifier optimization or introduce
OCR/LLM extraction as part of this phase.
