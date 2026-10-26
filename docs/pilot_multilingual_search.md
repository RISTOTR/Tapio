# Multilingual search in the read-only pilot

Recognized catalog requests now bypass the provider and use deterministic plans.
The centralized `tapio/pilot/concepts.py` catalog retains the reviewed expansions for
PHARMACY, DENTIST, CAR_REPAIR, FUEL, INSURANCE and HARDWARE_BUILDING_SUPPLIES.
The offline experiment imports this same catalog. At most ten terms are searched;
translations never assign category, context or tax treatment.

Input recognition uses exact catalog phrases and a bounded English/Spanish/Finnish
search grammar. It supports bare concepts, “Show pharmacy transactions”, “Busca compras
de farmacia” and “Näytä apteekkiostokset”. Unknown qualifiers are not silently dropped:
they use the existing routing/validation path. This is not unrestricted natural-language
translation. Year-only requests preserve their date scope; unsupported date syntax is
not interpreted by the catalog. Mixed/ambiguous concepts are not guessed.

The main answer shows count, signed individual rows, total matched negative bank
amounts grouped by currency, actual search terms, label availability and coverage
limits. Totals describe retrieved imported rows only, not total category spending.
Spanish and Finnish catalog requests receive localized count, warning, totals and
coverage text; schema field names, category codes and the surrounding pilot shell
remain unchanged. Long lists retain the existing first-30 display and collapsible
all-row details. Search metadata is now included in the expandable evidence panel.

Each retained match includes original term, normalized term, normalization version,
matched field and field authority. SOURCE_TEXT identifies raw description/merchant,
recipient or processor; CANONICAL_MERCHANT identifies normalized merchant text;
HUMAN_LABEL identifies confirmed category/context. ALIAS is reserved: this path has no
alias resolver and never invents alias provenance. Canonical merchant text is not a
human-confirmed business classification. Raw versus normalized fields are explicit;
matching itself is accent/case/punctuation-normalized whole token/phrase matching.

Catalog results exclude weak suggested-label matches and do not expose suggestions.
Existing human labels remain authoritative. Unreviewed and UNKNOWN rows stay visible.
Warnings count matches involving human labels and those relying solely on those labels,
so users can distinguish label-backed retrieval from literal source evidence.
Empty results retain SUPPORTED / NO_MATCH and explicitly state that no matches do not
establish zero spending. No review buttons or write paths have been added.

Verification uses the actual Pilot service with provider construction blocked,
read-only real source sessions and source fingerprints, plus isolated synthetic tests.
Private reports live under `data/interim/multilingual_enabled/`. Neither the accepted
engine nor benchmark/holdout contents are changed or executed by this work.

## Verified result

26 new integration/contract cases; full suite 1116 passed (one existing dependency
warning). All 92 focused search/ablation tests pass. Nineteen actual-source pilot
requests pass with provider construction forbidden: equivalent language queries
retain counts of 1 pharmacy, 7 dental, 6 fuel and 6 insurance matches; car repair and
hardware have no lexical matches. Fuel and insurance are correctly disclosed as
entirely human-label-dependent. Outflow totals exclude positive credits and therefore
must not be compared directly with the prior experiment's signed net sums.

Ruff, formatting, diff and Alembic checks pass. Privacy scan: 287 files, no findings.
All 14 source-table fingerprints and accepted configuration/core remain unchanged.
Historical verification checks 1543 protected hashes, with only the two recorded
pre-existing hygiene exceptions; holdout and manifest byte hashes are unchanged.
No benchmark run, source/review write, suggestion write or provider call occurred.
