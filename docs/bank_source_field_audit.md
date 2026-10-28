# Bank source-field utilization audit

Generated from the three imported original CSVs; no sensitive values.
All 11 columns are parsed and preserved exactly in raw_source. No backfill is needed.
Viesti was already mapped to message and searchable as raw_description. This repair adds explicit source provenance and shared usage.

| Column | Class | Stored projection | Text search | Knowledge / suggestions | Reconciliation / exclusions |
| --- | --- | --- | --- | --- | --- |
| Kirjauspäivä | AMOUNT_DATE_FIELD | booking_date | False | Schema definition; Structured provenance | Date-window candidate evidence;  |
| Arvopäivä | AMOUNT_DATE_FIELD | value_date | False | Schema definition; Structured provenance | Available as supplemental date evidence;  |
| Määrä EUROA | AMOUNT_DATE_FIELD | amount/currency/direction | False | Schema definition; Structured provenance | Exact Decimal amount;  |
| Laji | CORE_STRUCTURED_FIELD | transaction_type_code | False | Schema definition; Structured provenance | Not a matching key; No generic text search: opaque code |
| Selitys | SEARCHABLE_SOURCE_TEXT | raw_source.Selitys | True | Schema definition; source observation; Evidence only; never a confirmed label | Supplemental candidate text, never automatic confirmation;  |
| Saaja/Maksaja | IDENTITY_FIELD | raw_counterparty/normalized_counterparty | True | Schema definition; source observation; Evidence only; never a confirmed label | Exact known vendor identity;  |
| Saajan tilinumero | IDENTITY_FIELD | raw_source.Saajan tilinumero | False | Schema definition; Structured provenance | Not a matching key; Sensitive account identifier: retained, not generic search/vocabulary |
| Saajan pankin BIC | IDENTITY_FIELD | raw_source.Saajan pankin BIC | False | Schema definition; Structured provenance | Not a matching key; Bank identity does not establish purchase purpose; no generic search |
| Viite | REFERENCE_FIELD | reference | True | Schema definition; Structured provenance | Exact normalized reference; candidate evidence;  |
| Viesti | SEARCHABLE_SOURCE_TEXT | message | True | Schema definition; source observation; Evidence only; never a confirmed label | Explicit message/reference tokens; candidate evidence only;  |
| Arkistointitunnus | METADATA_ONLY | source_transaction_id | False | Schema definition; Structured provenance | Not a matching key; Private stable identifier: no generic search/vocabulary |

Dates and amounts use structured filters/arithmetic, not text search. Account/BIC and archive IDs remain private metadata; they are not vocabulary or purpose evidence.
Reference matching is candidate evidence. Message text cannot override canonical payee identity or establish confirmed category/context/tax treatment.
Unknown or reordered source headers fail ingestion and require explicit schema review.
Named-subject matching uses identity fields only; source messages are attached as supporting evidence.
New derived knowledge retains all prior claims and authorities. Historical suggestion/feedback artifacts are untouched.
