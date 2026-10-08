# Data dictionary

All tables have UUID primary keys. Foreign keys are indexed and do not cascade
deletes. Numeric values use NUMERIC(20,6); JSON objects use JSONB. Missing optional
values remain NULL. Date-only source values use DATE; instants use TIMESTAMPTZ.
Python enum member names are stored in PostgreSQL.

## import_runs

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| source_type | VARCHAR | no | Source family identifier; extensible text. |
| source_filename | VARCHAR | no | Original source filename, not file contents. |
| sha256 | VARCHAR(64) | no | SHA-256 hex digest of source bytes; indexed, retries allowed. |
| parser_version | VARCHAR | no | Parser version responsible for this import attempt. |
| started_at | DATETIME | no | Import start instant; defaults to database current time. |
| completed_at | DATETIME | yes | Import completion instant, if finished. |
| row_count | INTEGER | yes | Rows accepted by this import; null until known. |
| status | VARCHAR(9) | no | Workflow state; see enum values below. |
| source_metadata | JSONB | no | Source-specific provenance as JSONB. |

## metering_points

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| external_code | VARCHAR | no | Unique external metering-point identifier. |
| address | VARCHAR | yes | Metering-point address, when available. |
| contract_type | VARCHAR | yes | Source contract classification; extensible text. |

## documents

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| document_type | VARCHAR(14) | no | Stable document family; other supports uncategorized evidence. |
| source_filename | VARCHAR | no | Original source filename, not file contents. |
| sha256 | VARCHAR(64) | no | SHA-256 hex digest of source bytes; indexed, retries allowed. |
| document_date | DATE | yes | Date shown on document, when known. |
| import_run_id | CHAR(32) | no | Foreign key to import_runs.id. |
| metadata | JSONB | no | Document-specific JSONB. Python attribute: document_metadata (metadata is reserved). |

## energy_readings

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| metering_point_id | CHAR(32) | no | Foreign key to metering_points.id. |
| timestamp | DATETIME | no | Measurement interval start instant; normalize to UTC. |
| consumption_kwh | NUMERIC(20, 6) | no | Imported/consumed electricity in kWh. |
| solar_export_kwh | NUMERIC(20, 6) | no | Netted/exported solar electricity in kWh, NOT gross PV generation. |
| temperature_c | NUMERIC(20, 6) | yes | Observed temperature in degrees Celsius; missing allowed. |
| source_grain | VARCHAR | no | Source interval label (for example hourly); never inferred from the timestamp. |
| import_run_id | CHAR(32) | no | Foreign key to import_runs.id. |

## transactions

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| booking_date | DATE | no | Bank booking calendar date. |
| value_date | DATE | yes | Bank value calendar date. |
| amount | NUMERIC(20, 6) | no | Signed source transaction amount; retain source sign. Direction is explicit. |
| currency | VARCHAR(3) | no | Three-character currency code from normalized source; no FX conversion. |
| direction | VARCHAR(8) | no | Incoming/outgoing cash-flow classification. |
| raw_counterparty | VARCHAR | yes | Unmodified counterparty text. |
| normalized_counterparty | VARCHAR | yes | Normalized counterparty if established; retain raw evidence. |
| payment_intermediary | VARCHAR | yes | Payment processor, if identified. |
| ultimate_recipient | VARCHAR | yes | Underlying recipient, if identified. |
| reference | VARCHAR | yes | Payment reference as text, preserving leading zeroes. |
| message | VARCHAR | yes | Source payment message. |
| category | VARCHAR | yes | Extensible transaction category. |
| business_context | VARCHAR(8) | yes | Context classification; not a confirmed tax treatment. |
| source_file | VARCHAR | no | Transaction source filename retained alongside import provenance. |
| import_run_id | CHAR(32) | no | Foreign key to import_runs.id. |

## forestry_sales

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| document_id | CHAR(32) | no | Foreign key to documents.id. |
| buyer | VARCHAR | no | Timber buyer name. |
| contract_number | VARCHAR | yes | Source sale contract identifier. |
| sale_date | DATE | yes | Sale calendar date. |
| sale_type | VARCHAR | yes | Source sale type; extensible text. |
| municipality | VARCHAR | yes | Municipality as source text. |
| total_area_ha | NUMERIC(20, 6) | yes | Sale area in hectares. |
| estimated_volume_m3 | NUMERIC(20, 6) | yes | Estimated timber volume in cubic metres. |
| actual_volume_m3 | NUMERIC(20, 6) | yes | Actual timber volume in cubic metres. |
| estimated_value_eur | NUMERIC(20, 6) | yes | Estimated timber value in EUR. |
| actual_value_eur | NUMERIC(20, 6) | yes | Actual timber value in EUR. |

## invoices

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| document_id | CHAR(32) | no | Foreign key to documents.id. |
| vendor | VARCHAR | no | Vendor name as evidence; not a unique vendor identity. |
| invoice_number | VARCHAR | yes | Invoice identifier as text; not globally unique. |
| invoice_date | DATE | yes | Invoice issue date. |
| due_date | DATE | yes | Invoice payment due date. |
| subtotal_eur | NUMERIC(20, 6) | yes | Invoice subtotal in EUR. |
| vat_eur | NUMERIC(20, 6) | yes | Invoice VAT in EUR. |
| total_eur | NUMERIC(20, 6) | yes | Invoice total in EUR. |
| business_context | VARCHAR(8) | yes | Context classification; not a confirmed tax treatment. |

## tax_reviews

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| transaction_id | CHAR(32) | no | Foreign key to transactions.id. |
| suggested_context | VARCHAR(8) | yes | Unconfirmed suggestion, separate from human decision. |
| suggested_treatment | VARCHAR | yes | Unconfirmed treatment suggestion as text. |
| suggested_confidence | NUMERIC(20, 6) | yes | Optional suggestion score in [0,1]. |
| confirmed_context | VARCHAR(8) | yes | Human-confirmed context; never a prediction output. |
| status | VARCHAR(26) | no | Workflow state; see enum values below. |
| reviewed_at | DATETIME | yes | Human review instant. |
| review_notes | VARCHAR | yes | Human review notes; never a prediction output. |

## energy_bill_details

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| invoice_id | CHAR(32) | no | Foreign key to invoices.id. |
| metering_point_id | CHAR(32) | no | Foreign key to metering_points.id. |
| period_start | DATE | no | First billing calendar date, inclusive. |
| period_end | DATE | no | Last billing calendar date, inclusive; normalize source convention later. |
| consumption_kwh | NUMERIC(20, 6) | yes | Imported/consumed electricity in kWh. |
| solar_export_kwh | NUMERIC(20, 6) | yes | Netted/exported solar electricity in kWh, NOT gross PV generation. |
| energy_price_eur_per_kwh | NUMERIC(20, 6) | yes | Consumption unit price in EUR/kWh. |
| base_fee_eur | NUMERIC(20, 6) | yes | Base fee in EUR. |
| export_price_eur_per_kwh | NUMERIC(20, 6) | yes | Export remuneration in EUR/kWh. |
| export_margin_eur_per_kwh | NUMERIC(20, 6) | yes | Export margin in EUR/kWh; no assumed sign or settlement formula. |

## forestry_sale_lines

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| forestry_sale_id | CHAR(32) | no | Foreign key to forestry_sales.id. |
| harvest_type | VARCHAR | yes | Extensible harvest classification. |
| timber_product | VARCHAR | yes | Extensible timber product classification. |
| estimated_volume_m3 | NUMERIC(20, 6) | yes | Estimated timber volume in cubic metres. |
| actual_volume_m3 | NUMERIC(20, 6) | yes | Actual timber volume in cubic metres. |
| estimated_price_eur_per_m3 | NUMERIC(20, 6) | yes | Estimated EUR per cubic metre. |
| actual_price_eur_per_m3 | NUMERIC(20, 6) | yes | Actual EUR per cubic metre. |
| estimated_value_eur | NUMERIC(20, 6) | yes | Estimated timber value in EUR. |
| actual_value_eur | NUMERIC(20, 6) | yes | Actual timber value in EUR. |

## invoice_lines

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| invoice_id | CHAR(32) | no | Foreign key to invoices.id. |
| description | VARCHAR | no | Source invoice-line description. |
| product_code | VARCHAR | yes | Source product identifier. |
| quantity | NUMERIC(20, 6) | yes | Quantity in the line unit. |
| unit | VARCHAR | yes | Source quantity unit. |
| unit_price_eur | NUMERIC(20, 6) | yes | Price per unit in EUR. |
| vat_rate | NUMERIC(20, 6) | yes | VAT percentage points (25.5 means 25.5%); not a tax-policy decision. |
| net_amount_eur | NUMERIC(20, 6) | yes | Line net amount in EUR. |
| vat_amount_eur | NUMERIC(20, 6) | yes | Line VAT amount in EUR. |
| gross_amount_eur | NUMERIC(20, 6) | yes | Line gross amount in EUR. |

## transaction_invoice_allocations

| Column | Database type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | CHAR(32) | no | Application-generated UUID primary key. |
| transaction_id | CHAR(32) | no | Foreign key to transactions.id. |
| invoice_id | CHAR(32) | no | Foreign key to invoices.id. |
| allocated_amount_eur | NUMERIC(20, 6) | no | EUR amount allocated between transaction and invoice; sign policy deferred. |
| match_method | VARCHAR | no | Extensible reconciliation method identifier. |
| match_confidence | NUMERIC(20, 6) | yes | Optional score in [0,1]; not a calibrated probability by assumption. |

## Enum members

- ImportStatus: PENDING, RUNNING, COMPLETED, FAILED.
- TransactionDirection: INCOMING, OUTGOING.
- BusinessContext: PERSONAL, PROPERTY, FORESTRY, MIXED, UNKNOWN.
- DocumentType: INVOICE, TIMBER_SALE, BANK_STATEMENT, OTHER.
- TaxReviewStatus: UNREVIEWED, LIKELY_BUSINESS_EXPENSE, LIKELY_PERSONAL, NEEDS_REVIEW, CONFIRMED_BUSINESS_EXPENSE, CONFIRMED_NON_BUSINESS.

Unique business keys: metering_points.external_code and energy_readings
(metering_point_id, timestamp, source_grain). Import hashes, invoice numbers,
allocations and tax reviews are not unique; workflow cardinalities remain open.
