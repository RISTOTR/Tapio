# TAPIO workspace brief

Status: user-confirmed target direction; documentation only, not implemented.
Mode: Operate.
Scope: the local FastAPI browser application and its existing review workflows.
Authorities: PRODUCT.md for product truth; DESIGN.md for visual direction.

## Navigation and workflow

Import → Review → Ask → Summary is the target task sequence. Keep all four areas
reachable without requiring a conversation. Existing individual/grouped
confirmation, semantic concepts, user rules and historical/ongoing review logic
must remain available. Route names and integration details are not yet committed.

## Import

Make bank CSV selection, source validation and the imported date range clear.
Distinguish duplicate rows skipped from genuinely new transactions. Report the
actual import outcome and route new work into Review. Do not imply a successful
import or complete analysis while validation or processing is unresolved.

## Review

Prioritize grouped and quick confirmations where supported. Separate genuine
judgment from evidence-limited cases. Show what needs a decision, why it is here,
current authority and the relevant evidence together. Preserve explicit preview,
apply, stale-state handling, independent category/context authority and history.
Group actions must preserve existing membership and confirmation checks.

When nothing needs action, show a clear completed/empty state with its scope.
Distinguish historical backlog from work caused by recent imports. Keep concepts
and user rules reachable without making every routine confirmation visit them.

## Ask

Provide a focused question input and concise evidence-backed answer. Numeric
results come from deterministic code. Keep material caveats and source references
visible, with supporting evidence expandable. Conversation is a capability within
the workspace, not its organizing layout.

## Summary

Show an explicit current month/recent-period scope. Separate personal, property
and forestry activity; include income/expenses, electricity and grid overview,
forestry activity, pending review, recent imports and supported notable changes.
Keep cash flow distinct from invoice and sale-document views to prevent double
counting. Incomplete coverage is not zero activity. Comparisons require visible
periods and compatible evidence, not invented anomalies or unsupported totals.

## Implementation acceptance checks

- Desktop density stays readable; narrow layouts and zoom retain evidence/actions.
- Amounts, dates and source references are easy to scan and consistently formatted.
- Important evidence is visible without repeated disclosure navigation.
- Empty, loading, blocked, stale and failure states remain distinguishable.
- Keyboard operation, focus visibility, labels and contrast are verified on render.
- Existing behavior, confirmation boundaries and backend architecture are preserved.

## Open decisions

Exact navigation placement, shared visual tokens, locale/date conventions and
screen-level implementation scope remain open. No backend work or UI replacement
is authorized merely by these context files.
