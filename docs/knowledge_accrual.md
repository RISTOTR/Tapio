# Provenance-backed knowledge accrual

The implementation is an explicit offline derivation layer, not model training or a
background agent. PostgreSQL source tables remain unchanged. Private, content-addressed
JSON event bundles and validated snapshots live under `data/interim/knowledge/`.
No database migration, Gmail connection, classification write, confirmation action or
pilot suggestion UI is introduced. Nothing automatically loads the new snapshot into
the running pilot.

## Contracts and authority

`tapio/knowledge/models.py` defines provider-neutral typed Claim, Provenance,
KnowledgeEvent, KnowledgeItem, Contradiction and Snapshot contracts. Supported kinds:
ENTITY, ENTITY_ALIAS, VOCABULARY, SOURCE_FIELD_MEANING, MERCHANT_OBSERVATION,
DOCUMENT_FACT, CONTRACT_FACT, RELATIONSHIP, RECURRING_PATTERN and SEARCH_TERM_MAPPING.

Each item carries HUMAN_CONFIRMED, DETERMINISTIC_SOURCE_FACT, SUGGESTED or UNKNOWN.
Human authority requires a confirmation reference. A parsed field or existing registry
mapping is a deterministic source fact about that evidence, not human confirmation of
its real-world correctness. Candidate aliases/allocations remain SUGGESTED. Unknown
source-field meanings remain UNKNOWN. Suggested or unknown relationships cannot have
CONFIRMED status. Relationships retain CONFIRMED, CANDIDATE, AMBIGUOUS or REJECTED.

Provenance requires source type, source ID, SHA-256, originating field, observation time
and extraction method. Confirmation references are retained where applicable. Database
rows use hashes of their canonical snapshots; configuration files use their file hash.
Accepted email observations retain message ID/content hash, and accepted contract facts
retain the mapping hash and explicit decision hash with a relationship back to the
review hash, source message IDs and document hash. Bodies and excerpts are not copied.

First/last seen measure observation in the knowledge event stream, not the original
transaction date. Support counts distinct source revisions/fields; replaying an event
or repeating a backfill does not increase support. Source dates remain source facts.
The explicit `--observed-at` parameter fixes the backfill observation time for replay.

## Extraction and reconstruction

Run explicitly from the repository with a chosen observation timestamp:

```sh
PYTHONPATH=. .venv/bin/python scripts/backfill_knowledge.py \
  --observed-at 2026-10-26T00:00:00+01:00
```

The runner uses PostgreSQL read-only sessions and verifies all 14 protected source
fingerprints before and after. It reads imported transactions, review records,
documents, invoices, allocations and reversal candidates. Its accepted-evidence
adapters read the previously accepted import contract mapping/decision chain, accepted
Gmail field observations and the explicitly recorded property-specific export decision.
It does not ingest pending email search candidates or turn source-review language into
human approval. The import contract mapping and review hashes must match the decision.

Events are replayable and content-addressed. Reversing input event order and duplicating
all events produce the same snapshot. Loading a bundle replays its events and rejects
a mismatching snapshot. A later backfill creates another bundle rather than overwriting
history; old and new event bundles may be combined explicitly to audit source revisions.
No automatic watcher or append loop is enabled.

A scope identifies the transaction for reviewed context observations and the relevant
contract/property interval for contractual facts. Different contracts, periods or
transactions are not flattened into a global claim. Single-valued claims within the
same scope are checked for contradictory values. Both claims, their sources and their
authorities remain stored. A unique higher-authority value can be preferred for
retrieval; equal-authority disagreement blocks authoritative reuse. Ambiguous aliases
also block expansion. This is exact scoped conflict detection, not semantic contradiction
inference across arbitrary prose. Relationship ambiguity is reported separately.

## Fields, vocabulary and observations

`tapio/knowledge/fields.py` is the central searchable-field registry used by bank search.
It preserves message, Selitys, merchant, recipient and processor fields. Previously
unregistered raw-source keys are accumulated as non-searchable UNKNOWN field definitions;
discovery cannot expose account identifiers or arbitrary JSON to search. Enabling a
new field still requires an explicit registry decision.

Literal vocabulary retains the observed term, normalized form, language and optional
concept. Finnish export descriptions retain their source-format language. Known language
tags from the existing catalog are reused; otherwise language is `und`. Source words
are not automatically translated. Catalog expansions retain the catalog hash. Existing
identity aliases retain registry provenance. Raw/canonical bank co-occurrence alone
creates only a candidate alias, not an accepted identity equivalence.

Merchant observations are scoped to reviewed transactions. Context counts are returned
without a classification rule. Multiple established contexts produce MULTI_CONTEXT_OBSERVED;
UNKNOWN remains visible but does not establish a second business purpose. The existing
ambiguous-merchant policy remains active independently of observed counts. Historical
human decisions remain authoritative. Repeated merchant occurrence is retained only
when supported by at least two transactions; cadence is NOT_ESTABLISHED, not inferred.

## Query and search reuse

`KnowledgeQueries` exposes read-only `get_entity_knowledge`, `get_known_aliases`,
`get_known_vocabulary`, `get_merchant_observations`, `get_related_documents`,
`get_known_relationships` and `get_searchable_fields` interfaces. Returned items retain
authority and provenance. Suggestions can be inspected but are not accepted filters.

`prepare_search` and `retrieve_with_knowledge` are opt-in retrieval adapters. They reuse
accepted exact aliases and catalog mappings, enforce the existing ten-term limit and
run the existing deterministic search. The evidence records knowledge IDs, authority,
used terms, source-field knowledge IDs and the snapshot's event hash. No embeddings or
hidden similarity are used. There is no broad document-content search added here;
related-document retrieval uses explicit persisted links and statuses.

## Current offline inventory

The final backfill reads 395 transactions, 128 review records (not all confirmed),
12 documents, 9 invoices, 9 allocations and 2 reversal candidates, plus the accepted
local Gmail/contract artifacts. It produces 6486 events and 1322 knowledge items:

| Kind | Items |
|---|---:|
| Entity | 149 |
| Entity alias | 65 |
| Vocabulary | 484 |
| Source-field meaning | 16 |
| Merchant observation | 125 |
| Document fact | 101 |
| Contract fact | 25 |
| Relationship | 296 |
| Recurring pattern | 55 |
| Search-term mapping | 6 |

Authority totals: 897 DETERMINISTIC_SOURCE_FACT, 396 HUMAN_CONFIRMED, 19 SUGGESTED,
10 UNKNOWN. These are knowledge-item counts, not distinct source counts or confidence
scores. No scoped value contradictions were found. Existing reconciliation ambiguity
remains ambiguity and is not counted as a contradictory fact.

Examples verified: existing provider aliases and a truncated merchant descriptor;
source-backed Finnish interest vocabulary with two supports; the searchable Selitys
field; accepted Gmail contract product/dates/prices with explicit units and VAT basis;
property-scoped export decision facts; and both unresolved reversal relationships.
The ambiguous hardware retailer has only one observed reviewed context in this snapshot;
other contexts are not fabricated from the policy or examples in the request.

## Next step

Review a small sample of read-only suggestion cards backed by these knowledge IDs.
Show the specific supporting transactions/documents, contrary observations and unresolved
links. Keep candidate labels SUGGESTED and allow a conceptual SKIP. Before any CONFIRM
or CHANGE implementation, design an explicit audited human decision transaction with
stale-evidence checks. This phase provides neither those writes nor automatic suggestions.

## Verification

28 new knowledge tests; full suite 1175 passed with one existing dependency warning.
Ruff, formatting, diff and Alembic checks passed. Persisted-bundle retrieval verified
five real queries with explicit knowledge traces and no provider calls. The unresolved
reversal links were checked against the original signed source amounts. All 14 source
fingerprints, accepted core/configuration and holdout/manifest byte hashes remain
unchanged. Historical verification checked 1543 hashes with only the two previously
recorded hygiene exceptions. The pilot was not started or restarted by this phase.
