# Gmail read-only integration

Tapio uses the official Gmail API behind a local Python adapter and stdio MCP server. Gmail OAuth and MCP are separate: Google authorizes API reads; MCP exposes bounded local capabilities to the agent.

## Local OAuth setup

1. Enable Gmail API in your Google Cloud project.
2. Configure Google Auth Platform. For an External testing app, keep Testing and add your exact Google account under Audience → Test users.
3. Create a Desktop app OAuth client and save its downloaded JSON as `.private/gmail/client_secret.json`.
4. From the repository root run `.venv/bin/python -m integrations.gmail.auth --authorize`, and complete browser consent.

The only requested scope is `https://www.googleapis.com/auth/gmail.readonly`. Saved scopes, returned grants and Google's actual access-token scope are checked against that exact singleton. Missing or broader scopes stop access. Tokens are written atomically with mode 0600 to `.private/gmail/token.json`. Never paste credentials into chat or commit them. MCP startup does not silently launch consent.

Google documents the [installed-app setup](https://developers.google.com/workspace/gmail/api/quickstart/python), [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes) and [testing-app verification exception](https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification#projects-used-in-dev-test-stage). Testing apps can have limited refresh-token lifetimes; reauthorize when needed.

`GmailSettings` supports environment or `.env` overrides: `TAPIO_GMAIL_CLIENT_SECRET`, `TAPIO_GMAIL_TOKEN`, `TAPIO_GMAIL_CACHE`, `TAPIO_GMAIL_EVIDENCE`. Paths are operator configuration, not agent arguments. Keep overrides outside version control.

## MCP

Start manually with `.venv/bin/python -m integrations.gmail.server`. Transport is stdio only. The Tapio MCP client launches the same fixed module and verifies the exact six-tool allowlist:

- `gmail_search_messages`
- `gmail_get_message`
- `gmail_get_thread`
- `gmail_list_attachments`
- `gmail_download_attachment`
- `gmail_list_links`

There are no send, draft, reply, forward, delete, archive, label, mark-read or settings operations. Downloads write a private local cache but never mutate Gmail or import source facts; MCP marks that local write explicitly.

An optional local Codex configuration is:

```toml
[mcp_servers.tapio_gmail]
command = "/path/to/Tapio/.venv/bin/python"
args = ["-m", "integrations.gmail.server"]
cwd = "/path/to/Tapio"
startup_timeout_sec = 30
tool_timeout_sec = 30
```

Place this in your user configuration only if you want Codex to connect directly; this phase does not alter global configuration. Update the absolute paths for another checkout. See [official MCP configuration](https://developers.openai.com/codex/extend/mcp). The Python SDK is pinned to the v1 major API used by this implementation; [SDK source](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x).

MCP arguments are nested under `args`, for example `{"args":{"query":"from:vattenfall after:2024/12/01 sähkösopimus","max_results":5}}`. Tapio's internal wrapper accepts the inner fields directly.

## Search, MIME and limits

Search requires a positive sender and lower date bound, caps results at 20, rejects wildcard/broad queries and does not paginate automatically. The supported Gmail syntax is intentionally narrower than unrestricted Gmail search. Search returns metadata; a separate selected-message call retrieves body text. Threads return at most 20 metadata entries.

MIME normalization bounds recursion and parts, prefers plain text, strips HTML scripts/styles and extracts HTTP/HTTPS links. Body text caps at 16,000 characters and reports truncation. Remote images/scripts are never rendered. Links are metadata only; no link fetching or redirect handling exists. Thus even a private-network URL cannot cause a fetch.

Only explicitly selected PDF attachments up to 10 MiB can be downloaded. Actual PDF signature and SHA-256 are checked, filenames are normalized, and cache filenames use the hash. There is no alternate PDF parser. API requests have native timeouts and bounded retries; typed errors omit underlying exception details.

## Private cache and accepted evidence

Message metadata/body caches live under `data/interim/gmail/cache`, keyed by message ID and relevant history/content hash, with retrieval timestamps and a 24-hour reuse window. Explicit message refresh is available. Attachment files use content hashes. Cache entries are retrieval artifacts, not accepted source facts.

Selected bodies may be accepted as private typed `EmailEvidence` manifests under `data/interim/gmail/evidence`. These retain provider, message/thread IDs, sender, subject, date, retrieval time, body/hash, links and optional attachment/Document linkage. Truncated body-only acceptance is rejected. No mailbox-wide persistence into Document occurs and no migration is needed.

After human review only:

```sh
.venv/bin/python -m integrations.gmail.evidence --message-id SELECTED_ID --attachment-id SELECTED_ATTACHMENT --confirm-selected-evidence
```

Omit the attachment option for selected body-only evidence. This command is not agent-accessible. PDF handoff first records pending provenance, invokes the existing atomic loader, then links the Document ID/SHA. Repeating a handoff reuses duplicate content; unsupported files remain private with failure status and no new Document. A crash after import can be retried safely using the loader's SHA idempotency. The file manifest and database are not a distributed transaction.

## First research pass and review gate

`.venv/bin/python -m integrations.gmail.research` performs eight targeted electricity queries, five results each, at most twelve unique selected bodies. It writes `data/interim/gmail/candidate_report.json` privately. It does not download PDFs, follow links or import evidence. `more_available` discloses capped results. Unknown coverage periods remain unknown until reviewed.

Review the report before selecting any evidence for acceptance. The first pass deliberately searches electricity providers only; forestry correspondence is a supported future narrow search, not part of this acceptance run.

## Privacy, revocation and troubleshooting

Credentials, tokens, caches, attachments, candidate reports and content-free audit logs are ignored by Git. Files written by this integration use mode 0600. Email content is untrusted tool data, never instructions. Tests use synthetic senders only.

To revoke access, remove this app's access in your Google Account third-party connections, then remove the local token when you no longer need it. Deleting a local token alone does not revoke Google's grant. Never broaden scopes to resolve an authorization failure.

`AUTHENTICATION_REQUIRED`: check Desktop client type, enabled Gmail API, browser consent and token expiry. A testing/access-denied page may mean the selected account is not listed as a test user. `SCOPE_REJECTED`: stop, revoke the prior grant and authorize only readonly. `GMAIL_API_FAILURE`: check API enablement, connectivity and quota; no credentials appear in tool errors. `NO_MATCHING_MESSAGES` is a bounded-search result, not evidence that the entire mailbox lacks relevant records. `OUTPUT_LIMIT` or unsupported MIME requires a narrower/manual review, not an unrestricted export.


## Selected contract evidence review

`contract_review.py` compares operator-reviewed, typed observations; it is not a PDF parser or an agent tool. Confirmation/PDF facts may support accepted conclusions, while expiry notices support only a previous contract end date. Offers and current webpages cannot establish accepted historical terms. Conflicting eligible values remain conflicts; missing dates are never inferred. Field values are exact strings with source excerpts and locators.

`accept_evidence` also supports literal selected excerpts, accepted field annotations and source classification. This retains full-source content hashes and Gmail provenance while keeping unrelated body text and links out of the accepted manifest. Selection contributes to the manifest identity, so retries are idempotent and differently reviewed excerpts remain separate. These annotations are supplied by a human-directed review, not automatically trusted model output.

For unsupported PDFs, use the existing extraction/parser-detection stages and preserve the download hash plus unsupported status. Do not fabricate a Document ID or parser version and do not force a failed database import. Evidence sufficiency does not itself authorize tariff changes.
