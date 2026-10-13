# Deterministic document ingestion

The LLM interprets; code calculates. This pipeline reads local PDFs with pypdf
6.20.1, detects explicit known layout signatures, parses source-specific text,
validates Pydantic/Decimal facts and commits structured rows atomically. It does
not use OCR, remote extraction, embeddings or document classification models.

## Supported layouts and versions

| Detailed type | Source | Parser version | Existing DocumentType |
| --- | --- | --- | --- |
| ENERGY_INVOICE | Vattenfall consolidated consumption/export bills | vattenfall-1 | INVOICE |
| GRID_INVOICE | Elenia itemized consumption/production bill | elenia-invoice-1 | INVOICE |
| GRID_CONTRACT | Elenia consumption and production confirmations | elenia-contract-1 | OTHER |
| FORESTRY_INVOICE | MHY single-page service invoice, two total-table variants | mhy-invoice-1 | INVOICE |
| FORESTRY_SALE_SUMMARY | MHY six-column planned/actual timber table | mhy-sale-1 | TIMBER_SALE |

The stable existing enum is retained. `Document.metadata.kind` supplies the detailed
source type. Contracts and tariff facts use validated structured document metadata;
there is no new tariff schema or hypothetical cost engine.

## CLI

```sh
uv run python -m data_pipeline.ingest.documents --file /private/path/invoice.pdf
uv run python -m data_pipeline.verify_documents
# Optional private JSON array of local PDF paths: re-extract and compare every fact.
uv run python -m data_pipeline.verify_documents --manifest /private/path/sources.json
```

Import output contains counts, parser version and error codes. Source names, hashes,
customer information, account details and payment references are not printed.
The verifier is read-only and checks persisted headers, every line, energy components,
forestry lines, source hashes and parser provenance. Source documents remain at their
original paths; the database does not store PDF binaries.

## Canonical facts and database mapping

`data_pipeline/ingest/documents` owns PDF extraction and transactional loading.
`data_pipeline/documents` contains a typed contract, signature detector and separate
Vattenfall, Elenia, Elenia-contract, MHY-invoice and forestry-summary parsers.

One Document links to one ImportRun and retains SHA-256, basename, document date,
vendor, parser version, page count, warnings and the complete canonical projection.
The ImportRun records UTC attempt/completion times, outcome and safe errors.

One consolidated utility bill creates **one payable Invoice**, with all billed lines
and separate EnergyBillDetails per usage point. Consumption and export never share
a metering-point fact. InvoiceLine.source_metadata records source page, line ordinal,
usage point, whether the unit price includes VAT, printed rate precision and warnings.
Header-only customer/reference/order information stays in private document metadata.

Energy facts include actual billing dates, product, fuse size where printed, base
fee, consumed kWh, energy rate, export kWh, export price and margin. Solar export
is exported electricity, **not gross PV generation**. Elenia tax and seasonal
transfer quantities/prices remain separate billed lines. Printed gross utility
unit prices are explicitly labeled; missing per-line net/VAT amounts in Vattenfall
remain null rather than being invented by prorating header VAT.

Contracts retain usage point, role, number, effective date, product, fuse, tax class,
price-sheet dates and source pages. Consumption metadata stores the printed winter
period/time rule and both net/gross seasonal, base and tax rates. Production metadata
stores the printed fee and the below-50-kVA exemption condition. The exemption is not
inferred from fuse size, and no hypothetical charge is calculated.

ForestrySale and ForestrySaleLine retain planned and actual quantities, unit prices,
values, harvest types and assortments. The document metadata additionally retains
association, line pages and calculated differences. Missing planned cells stay null.
A sale discrepancy is reported without altering any printed total.

## Validation and rounding

Money and quantities use Decimal with NUMERIC(20,6) representability checks. Required
identifiers, dates, nonnegative quantities, VAT ranges, 18-digit usage points and
source pages are validated. Invoice net + VAT must equal gross; gross line sums must
equal the invoice total. When all net/VAT line values are printed, their sums must
also match headers. Components must reconcile before a consolidated bill is accepted.

Net-priced service lines must reproduce their net amount with half-up cent rounding.
Printed utility average prices can be rounded: the permissible arithmetic difference
is bounded by quantity × half the printed rate quantum + EUR 0.01 and explicitly
warned. Printed line VAT may differ from recomputed rounded VAT by at most one cent,
with a warning. Larger inconsistencies fail. These tolerances never rewrite source
amounts, fabricate balancing lines or relax invoice/component total equality.

## Idempotency and failure policy

A transaction-scoped PostgreSQL advisory lock serializes document writers and
reconciliation. Exact hash + parser version re-import adds an audit attempt and no
structured rows. Changed output under the same parser version fails with
`same_version_output_conflict`. The same bytes with a new parser version fail with
`parser_revision_requires_explicit_review`; old facts are never replaced. A vendor +
invoice number seen in different bytes fails with `invoice_identity_conflict`.
Buyer + sale contract identity is protected similarly. There is deliberately no
new global invoice-number uniqueness constraint.

Persistence uses a savepoint: any failure removes all new structured rows while
retaining a FAILED ImportRun. Tests also cover concurrent identical imports.
Unsupported signatures, missing fields, encrypted/malformed PDFs and image-only or
empty pages fail explicitly. Unsupported fee/adjustment layouts are not flattened
into energy lines. Supporting an additional layout requires inspected evidence and
synthetic regression coverage; OCR requires a separate decision.

## Privacy and limits

Real PDFs remain outside the repository. Private extracted text, manifests and
verification artifacts are under ignored data/interim/documents. Canonical JSON in
the database includes personal source facts and must also be treated as private.
Fixtures are invented text and generated PDFs; no real PDF or extracted text is a
fixture. Only aggregate verification findings belong in committed documentation.
Gitignore is protection against accidental staging, not access control.

Immutability is enforced by these append-only importer workflows, not by database
roles or UPDATE-blocking triggers. Direct database edits are outside the supported
workflow. Parser revisions and human allocation correction need explicit audited
workflows before they can replace prior interpretations.
