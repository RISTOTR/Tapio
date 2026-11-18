# Ask feedback implementation review

All 73 saved Answer feedback items were inspected with their original questions and responses. The per-item classification and rationale are private in `data/interim/import_workspace/feedback-review.json`; original feedback files are unchanged.

| Classification | Items |
| --- | ---: |
| No longer applicable, including positive feedback and superseded failures | 38 |
| Actionable answer-quality issue | 15 |
| Suggestion requiring broader architecture | 3 |
| Provenance/presentation issue | 7 |
| Evidence-routing issue | 6 |
| Actionable UX issue | 1 |
| Bug | 3 |

Implemented changes:

- Finance aggregates and period comparisons overlay current authoritative human revisions instead of relying exclusively on legacy labels. Category and context remain independent, including corrections.
- Explicit bilingual vocabulary covers pharmacy, restaurants, road fees, tax and building supplies. Finnish payment syntax is separated from source evidence terms; the observed typo in “transactions” is accepted. Date constraints remain bounded.
- A single-period question about both electricity suppliers runs two separate existing deterministic bank queries. Values are never combined using model arithmetic.
- Solar and electricity-bill questions use local energy readings or invoices, then existing document/knowledge and read-only Gmail tools when evidence is insufficient. Supplier and period scope are explicit. Exported electricity is distinguished from total panel generation. Invoice dates are distinguished from bank payment dates. Candidate email evidence never becomes a verified invoice amount automatically.
- The previous saved question provides bounded follow-up scope for tax payments. Supporting rows show dates, amounts and provenance. Ambiguous context asks for clarification. The UI exposes a fresh-question action and clearer feedback wording.

Existing merchant identity resolution, direct answers, expandable evidence, coverage limitations, source visibility, conditional Gmail routing and tax caution remain in place.

Deferred intentionally: a comprehensive multi-domain Summary, automatic durable learning from feedback, inferred complete statement coverage, automatic tax conclusions, and calculating energy totals from unvalidated email/attachment candidates. Feedback alone cannot authorize a USER_RULE or semantic knowledge change. Bank expenses remain bank cash flow; unpaid emailed invoices are not silently added to paid expenses.

Regression checks exercise the implemented examples and the existing Ask, review, import and historical-source safeguards. Gmail fallback is tested through the existing tool boundary with synthetic evidence; verification does not send messages, import emails or mutate Gmail.
