# Offline multilingual search and label ablation

This prototype is not enabled in the pilot. No model, benchmark, source, label, or
review writes are involved. The finite catalog in `tapio/experiments/multilingual.py`
expands exact English, Spanish and Finnish concepts into one visible list of at most
ten terms. Unrecognized concepts fail explicitly. It is a lexical baseline, not a
complete multilingual natural-language interpreter. Whole token/phrase matching uses
case folding, accent removal and punctuation normalization. Each match retains its
explicit term and source field. Finnish compounds and merchant-only descriptions can
be missed; no hidden merchant alias, stemming or embedding compensates for that.
Translations never assign category, business purpose or deductibility.

## Experiment method

The private reproducible runner is `data/interim/multilingual_ablation/run.py`, with
per-row evidence and rendered answers in `results.json`. Sixteen requested language
examples and six named-merchant/context probes run against the same imported data.
This is a deterministic retrieval/presentation experiment, not a model-answer or
benchmark evaluation. Concepts were fixed before source results were inspected.

`retrieve_search(..., hide_labels=True)` suppresses confirmed labels, weak labels
and review status before matching and before producing the evidence DTO. Weak labels
are also hidden to avoid substituting them for authoritative labels or leaking copied
values. Original labels and default production behavior are preserved. This is a
conservative all-label ablation, so losses involving weak labels cannot be attributed
solely to human confirmation. It is not a global agent tool sandbox: only this offline
search path is evaluated. Other agent tools must be projected before a future full
agent experiment; feeding an ordinary aggregate alongside hidden rows would leak.

Amounts and currency in every retrieved row are checked against source transactions.
Read-only transactions and before/after fingerprints protect all 14 source tables.
No source coverage claim is inferred from search completeness. Usefulness is measured
as retained factual retrieval, not as a human satisfaction score. Unsupported business
or tax conclusions are never generated in this deterministic path; model unsupported
conclusion rate is not measured. Context text search is not a context aggregate:
weak matches must not be treated as confirmed context totals. A future labels-hidden
context aggregate must say unavailable rather than report a fabricated zero.

## Results

395 source rows; 127 human-reviewed, 126 resolved (one retains UNKNOWN).
Review burden grows from 269 unresolved rows to 395 when labels are hidden.
All language variants of each concept produce identical terms and matching IDs.

| Concept | With labels | Hidden | Signed EUR with labels / hidden |
|---|---:|---:|---|
| Pharmacy | 1 | 1 | -8.95 / -8.95 |
| Dentist | 7 | 7 | -1836.50 / -1836.50 |
| Car repair | 0 | 0 | no matches |
| Fuel | 6 | 0 | -298.45 / no matches |
| Insurance | 6 | 0 | -2152.74 / no matches |
| Hardware/building supplies | 0 | 0 | no matches |

Named-merchant probes retain their rows/amounts where exact phrases match. One named
merchant phrase misses because token/phrase matching does not resolve aliases. Both
context probes lose all matches when labels are hidden. Zero matches are not evidence
of zero spending. Pharmacy and dental support literal evidence questions without
labels; purpose-specific questions and label-only concept matches depend on labels.
Financial dates/amounts remain deterministic source facts, not classification facts.
Detailed real counterparties and per-row provenance remain in the private report.

## Authority model (design only)

Authority belongs to each fact, not the entire transaction:

* HUMAN_CONFIRMED: explicit reviewed category/context, with review provenance.
* DETERMINISTIC_SOURCE_FACT: imported date, amount, currency or literal match with
  source identity and transformation version; does not confirm business purpose.
* SUGGESTED: proposed category/context and supporting reasons, never used as a
  confirmed filter, aggregate, or tax conclusion.
* UNKNOWN: no established value. Stored UNKNOWN is still a real context label;
  it is not unspecified query scope. Conflicting evidence is surfaced for review.

Existing HUMAN_REVIEWED is the legacy transport name for confirmed label authority;
this design does not migrate it or change existing renderers.

## Suggestion object (not implemented or enabled)

```json
{
  "transaction_id": "local-id",
  "suggested_category": null,
  "suggested_context": null,
  "reason": ["AMBIGUOUS_MULTI_CONTEXT_MERCHANT"],
  "evidence_level": "SUGGESTED",
  "evidence_refs": [],
  "rule_version": "review-design-v1",
  "allowed_actions": ["CONFIRM", "CHANGE", "SKIP"]
}
```

Nullable suggestions avoid forcing a guess. Evidence references must resolve to the
same transaction or a verified document link; candidate links remain candidate links.
Confirmed labels are shown separately and cannot be overwritten by suggestions.
Tokmanni, K-Rauta and Oikea Konekauppa never receive merchant-wide classifications.
Prior human reviews establish only those reviewed purchases' contexts.

## ASK_FOR_REVIEW (design only)

Show at most five unresolved transactions per batch with dates, amounts, exact
match/document evidence, existing confirmed fields and separate suggestions.
Ask ambiguous retailers which of PERSONAL, PROPERTY or FORESTRY applies; allow UNKNOWN
and SKIP instead of forcing a choice. A pharmacy suggestion such as OTHER/PERSONAL
must visibly remain SUGGESTED and must not establish tax deductibility.
CONFIRM accepts the displayed proposal conceptually, CHANGE supplies another value,
SKIP leaves it unresolved. This phase implements no actions, persistence or writes.
Any future write workflow needs explicit user confirmation, stale-review checks and
an audit trail; it must never silently change existing human decisions.

## Explainable prioritization (design only)

Use ordered queues, not confidence percentages: ambiguity requiring a person first,
then high financial impact (absolute amount descending within currency), then rows
with useful linked evidence, followed by remaining unresolved rows. Date and ID break
ties deterministically. Every row remains accessible; prioritization never filters
away the review backlog.

Attach independent reason codes: AMBIGUOUS_MULTI_CONTEXT_MERCHANT,
HIGH_AMOUNT (explicit configurable threshold per currency), MATCHING_DOCUMENT
(confirmed versus candidate link distinguished), RECURRING_MERCHANT,
MERCHANT_PREVIOUSLY_REVIEWED, EXACT_ALIAS_MATCH (versioned identity alias only), and
UNKNOWN_MERCHANT. Recurrence or a previous reviewed purchase can make review easier,
but never transfers category/context. Documents can support purpose suggestions,
never silently establish deductibility. No arbitrary percentage or permanent
merchant classification is created.

Recommended next pilot: enable reviewed, visible multilingual lexical expansions
with field provenance and label-availability warnings. First address explicit identity
aliases/compound limitations with reviewed examples; keep review suggestions disabled
until a separate human review of their design. A full-agent ablation is a later step,
requiring projection across every tool, document link and aggregate.

## Verification

Full suite: 1089 passed. Final focused suite: 10 passed, including the additional
presentation-leakage test added after the full run collected tests (1090 distinct
validated tests in total). Ruff, format and diff checks pass. Privacy scan: 283 files,
zero findings. All 14 source-table fingerprints unchanged; accepted configuration and
1543 historical hashes checked, with only the two previously recorded hygiene
exceptions. Holdout/manifest byte hashes unchanged; contents not inspected.
