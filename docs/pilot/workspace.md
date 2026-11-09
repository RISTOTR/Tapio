# Local workspace

The local application now shares Import / Review / Ask / Summary navigation.
Review is the entry destination. The existing review API and frozen financial
engine remain authoritative; this change does not introduce a new backend.

| Destination | Route | Status |
| --- | --- | --- |
| Entry | `/` or `/app` | Redirects to Review |
| Import | `/app/import` | Explicit placeholder |
| Review queue | `/pilot/confirmation/groups` | Grouped, quick and judgment cases |
| Individual review | `/pilot/confirmation` | Compact current state and original suggestion |
| Ask | `/app/ask` | Integrated evidence workflow; `/pilot` remains compatible |
| Summary | `/app/summary` | Explicit placeholder |

Review retains independent category/context selection, preview before apply,
server-authoritative current state, stale-state protection, explicit UNKNOWN,
correction reasons, signed tokens and append-only history. Original suggestions
are labelled separately. Evidence and previews use structured rows and tables;
internal tokens are not rendered as approval content. Concepts, user rules and
category mappings remain reachable under Review.

## Ask routing

Financial totals and ordinary transaction searches use the existing deterministic
local engine. The workspace never calculates financial answers with an LLM.
Document, receipt, invoice and contract questions check accepted persistent
knowledge, stored email evidence and imported document metadata. Payment-purpose
questions check bank evidence first. Accepted contract dates can provide a direct
answer; unverified email matches remain candidates, not established facts.

The existing read-only Gmail MCP is called when email is explicitly requested or
local evidence cannot resolve an evidence question. Searches require a sender
and supported period (one calendar year or one month), and return at most five
metadata records and three message bodies. Known stored message references can
be read directly without a broader search. No attachments are downloaded, no
messages are sent and no evidence is automatically accepted. Missing scope or
unavailable Gmail produces a limitation, never a claim that evidence is absent.

The response shows the direct answer, material limitations, sources used or
unavailable, and expandable supporting records. Email content is rendered as
text. Numeric questions do not trigger Gmail. Routing is deliberately bounded
and rule-based; unsupported phrasing can require a narrower question. Persistent
knowledge comes from the verified active review snapshot, not arbitrary files.

## Verification and design pass

Real Chrome fixtures cover shared navigation, Ask submission, source provenance,
keyboard focus, accessible control names, desktop/narrow/intermediate reflow and
offline recovery. Review browser fixtures exercise preview/apply, independent
fields, explicit UNKNOWN, corrections, reload/navigation and server restart using
isolated PostgreSQL schemas. Authenticated live Gmail is not exercised: adapter
and routing tests use synthetic messages through the existing tool boundary.

The Impeccable polish pass tightened individual review, hid inapplicable inputs,
clarified current versus original values, retained visible preview/apply actions,
and moved raw evidence objects into readable labelled rows. Screenshots and test
logs are private local artifacts in `data/interim/workspace_ui/`; screenshots use
synthetic records. Automated accessibility checks do not claim certification.

## Next increments

Import needs an upload/validation workflow showing source, date range, duplicate
and new-row counts, followed by analysis and routing into the existing Review
queue. Summary needs deterministic period/context aggregates, electricity/grid
and forestry activity, recent imports, pending review and supported anomalies.
Neither placeholder pretends those capabilities are already implemented.

Latest focused validation: 83 Ask/pilot/presentation tests, 41 Review integration
checks, two Review Chrome tests and one database write-rejection test passed.
The two Chrome tests initially hit browser startup timeouts; both passed on rerun
with startup diagnostics and a longer launch allowance. The previously skipped
database check passed separately. The Ask Chrome workflow also passed. Ruff,
whitespace checks and the repository privacy scan passed. Verified text contrast
is at least 5.69:1 and the input border contrast is 3.11:1 on white. All 15 domain
table fingerprints, the accepted financial engine and frozen review sources were
unchanged; the local review seal was renewed for the verified implementation.

## Local startup integrity

The earlier `SOURCE_SNAPSHOT_CHANGED` launch failure is resolved by the
[historical-subset guard](startup-integrity.md). The original protected baseline
is unchanged; authenticated historical rows must remain identical while appended
imports are permitted. Normal startup, Review queue loading and all five workspace
routes passed. The existing review write profile and safeguards remain enabled.
