# Shared pilot subject identity

This is a deterministic, read-only pilot repair. The accepted agent, model, financial
calculations, evidence policy, source tables and human labels are unchanged. There are
no live model calls, benchmark runs, embeddings or fuzzy merchant matching.

## Observed routing failure

Retained history distinguishes an older failure from two remaining extraction defects.
The exact Oikea evidence question's recorded no-match occurred on October 21 before the
named-subject lookup existed: its stage list contains no NAMED_SUBJECT_RETRIEVAL.
The successful Oikea tax question on October 22 did invoke that lookup. The current exact
A/B pair already resolved identically offline before this repair; there is no retained
post-repair failure of exact question A establishing a tax-dependent identity difference.

However, the October 22 wording “What payments do we have for Oikea Konekauppa?” entered
the lookup stage but extracted no subject. “What do we know about K-Rauta purchases?”
had the same problem. The previous extractor recognized three narrow sentence patterns.
The presentation also had a separate lowercase/legal-suffix substring matcher over only
already retrieved rows. A missed extraction could therefore fall back to incomplete
broad evidence and produce a misleading named-subject no-match. Those parallel matching
implementations are now consolidated. The recorded short-name Elenia payment failure
invoked the resolver but lacked an explicit Elenia brand-to-legal-entity alias.

## Shared identity contract

`tapio/pilot/subject_identity.py` owns extraction, normalization, the alias registry,
canonical identity and resolution for evidence, payments/spending, tax, document and
reconciliation intents. Generic subject relations and object phrases replace complete
sentence templates. No question or merchant has its own routing branch. Unsupported
compound or relative scopes are not guessed. Intent is a separate presentation decision.

`SubjectIdentity` contains canonical_name, aliases, normalized_aliases, subject_types
(observed payee/recipient/processor/document-issuer roles), and matched_source_identifiers.
Private source IDs never enter the public identity projection. Identity is independent
of intent; requested dates may change matched source IDs but not the resolved entity.

Normalization uses Unicode NFKC, casefold, whitespace collapse and conservative punctuation
and hyphen normalization. Resolution checks canonical exact, alias exact, safe legal-suffix
normalization, then explicit bank-descriptor aliases. Generic prefixes, substrings,
approximate spelling and arbitrary location removal are not allowed. Multiple remaining
identities return AMBIGUOUS_IDENTITY rather than being merged. Registry entries alone
cannot manufacture source evidence.

Existing exact import aliases are retained. The inspected provider/merchant mappings are:

| Canonical identity | Observed stored descriptor / issuer | Supported query names |
| --- | --- | --- |
| Elenia Verkko Oyj | Raw Elenia Verkko Oy or Elenia Verkko Oyj; normalized and document issuer Elenia Verkko Oyj | Elenia; Elenia Verkko; Elenia Verkko Oyj |
| K-Rauta | Raw K-Rauta Viitasaari  PIELAVESI; normalized k-rauta viitasaari pielavesi | K-Rauta, K RAUTA, Krauta and Unicode hyphen equivalents |
| Oikea Konekauppa | Raw OIKEA KONEKAUPP     Viitasaari; normalized oikea konekaupp viitasaari | Oikea Konekauppa; exact recorded descriptor |

Processor and ultimate-recipient fields are null for these matched real rows. Elenia's
brand alias and K-Rauta's exact observed store descriptor are added centrally; Oikea's
existing descriptor alias is moved into the same registry. K-Rauta punctuation variants
represent spelling of that observed brand, not additional inferred stores. No alias
contains a business context, category, tax rule or receipt requirement.

## Evidence path and private trace

The pilot still requires accepted final validation first. Then all supported named intents
call the same `retrieve_subject` and `resolve_subject` functions, followed by the unchanged
source postflight check. The subject lookup cannot rescue an invalid accepted final or
supply fabricated mandatory handles. Frozen tool definitions and benchmark paths are untouched.
The legacy presentation-only fallback also calls the shared resolver; it no longer has
its own substring matcher or treats incomplete retrieval as a conclusive no-match.

Bank matching uses exact resolved values in normalized_counterparty, ultimate_recipient
and payment_intermediary. Document metadata vendor and invoice vendor are queried independently.
No context/category/review/document-presence filter suppresses bank evidence. An explicit
year filters dates; undated discovery searches all imported dates. Complete, bounded bank
rows feed the existing per-currency Decimal debit sum. Truncation still fails closed.

The private trace records intent, extracted/normalized subject, canonical identity,
resolver function/version, aliases considered, source matching methods, date/context/category
filters, query invocation flags and returned row counts. Match provenance uses
CANONICAL_EXACT, ALIAS_EXACT, LEGAL_SUFFIX_NORMALIZED, BANK_DESCRIPTOR_ALIAS and
AMBIGUOUS_IDENTITY (plus NO_MATCH). Canonical query matching and the descriptor-to-canonical
source link have separate provenance, so a canonical query may still rely on a recorded
bank-descriptor alias. Normal UI evidence summaries do not print technical matching codes.

## Offline A–F trace

All rows below invoke `tapio.pilot.subject_identity.resolve_subject` through the same
read-only lookup. Bank, document and invoice evidence queries are independently invoked
for each resolved identity. No context, category or review-state filters are applied.
Document counts include catalog documents; invoices can refer to those same source documents
and are not extra documents.

| Case | Intent | Extracted / normalized subject | Canonical subject | Scope | Bank / documents / invoices |
| --- | --- | --- | --- | --- | --- |
| A: Oikea evidence | EVIDENCE_LOOKUP | Oikea Konekauppa / oikea konekauppa | Oikea Konekauppa | All imported dates | 1 / 0 / 0 |
| B: Oikea deductibility | TAX_BOUNDARY | Oikea Konekauppa / oikea konekauppa | Oikea Konekauppa | All imported dates | 1 / 0 / 0 |
| C: Elenia payments | FINANCIAL_TOTAL | Elenia / elenia | Elenia Verkko Oyj | 2026 | 9 / 3 / 1 |
| D: Elenia evidence | EVIDENCE_LOOKUP | Elenia / elenia | Elenia Verkko Oyj | All imported dates | 21 / 7 / 5 |
| E: K-Rauta evidence | EVIDENCE_LOOKUP | K-Rauta / k rauta | K-Rauta | All imported dates | 2 / 0 / 0 |
| F: K-Rauta spending | FINANCIAL_TOTAL | K-Rauta / k rauta | K-Rauta | 2026 | 0 / 0 / 0 |

A and B retain exactly the same identity and source evidence. C and D use ALIAS_EXACT;
A/B/E/F use CANONICAL_EXACT with BANK_DESCRIPTOR_ALIAS source links for the two merchants.
All exact arguments, source identifiers and alias sets are retained privately under
`data/interim/pilot_subject_consistency/`; historical records and scores are not rewritten.

## Expected local answers and boundaries

Oikea evidence lookup returns its one **€134.05 debit on 2026-06-02**, with the existing
human-confirmed FORESTRY / MAINTENANCE labels and no matching document. Tax wording uses
the same evidence and adds the no-deductibility-decision boundary.

Elenia's 2026 payment query leads with **€1,182.41 across nine bank payments**. Undated
Elenia discovery includes 21 bank rows and seven source documents; legal and short brand
names resolve identically. Imported coverage is stated and is not a full-statement guarantee.

K-Rauta evidence returns two 2025 debits: **€84.85 on 2025-07-28**, whose human context
remains unresolved, and **€15.95 on 2025-10-21**, human-confirmed PERSONAL / OTHER. These
are not promoted to FORESTRY, PROPERTY or tax deductibility. No matching document exists
in the imported catalog. The requested 2026 slice has no matching rows: its identity is
resolved but evidence status is NO_MATCH for that period, with zero matching payments
and zero matching debit total. No currency is invented for an empty result, and 2025
spending is not moved into 2026. Unknown merchants retain NO_MATCH with no invented identity.

## Verification

The focused suite covers cross-intent identity/evidence equality, Unicode/hyphen/alias
variants, collisions, provenance, independent bank/document matches, human-label authority,
unknown context, explicit dates, empty dated slices, unknown merchants, privacy and the
nine-question pilot matrix. End-to-end tests use a scripted provider, never a live model.
Final full-suite and integrity results are recorded below after completion.

Final verification: **959 tests passed**, retaining the 925 existing tests and adding
34 consistency regressions. Existing match-method assertions were updated to the explicit
provenance vocabulary; their matching and rejection requirements were not relaxed. The
focused 85-test presentation/subject suite and all 13 real read-only intent replays passed.
Ruff, formatting, diff and Alembic checks passed. The repository privacy scan checked
268 files with zero findings and the private denylist loaded.

All 14 source-table fingerprints remain unchanged, including human review labels. Accepted
core/configuration/snapshot and holdout/manifest byte hashes are unchanged. The historical
check verified 1,543 artifacts with only the two previously documented hygiene exceptions;
this repair adds no historical changes. Holdout contents were not inspected. No live model,
benchmark, source mutation, merchant-context assignment or tax decision occurred.

The human-supervised read-only pilot can resume after restarting its local server to load
the shared resolver. New private traces identify `subject-identity-v2`, which distinguishes
current execution from older retained results. Accepted validation still fails closed;
subject retrieval does not override an invalid agent final.
