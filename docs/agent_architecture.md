# Agent architecture — Phases 05–06

The LLM interprets; code calculates. Phase 05 adds typed, bounded capabilities to existing deterministic services. It does not replace ingestion, classification, reconciliation or the Phase 04 cost engine.

## Boundaries

`tapio/tools/schemas.py` defines frozen Pydantic input/output models with unknown fields rejected. `registry.py` validates arguments and results, limits output to 100 KB, applies a 30-second execution deadline, sanitizes errors and records private timing diagnostics. Database sessions enforce read-only transactions and a 20-second statement timeout. Cancellation of a worker thread is not immediate; native database/API timeouts also constrain work.

`apps/api/app/services/tool_queries.py` projects SQL source facts into safe DTOs and calls the existing Phase 04 engine and reconciliation state function. Financial calculations remain in those deterministic services. Transaction labels come only from completed human reviews; weak classifications and raw bank identifiers are excluded. Document summaries omit extracted full text. Provenance includes document/parser identifiers and cost tariff sources where relevant.

## Internal tool registry

All thirteen internal tools are read-only:

| Area | Tools |
| --- | --- |
| Transactions | `query_transactions`, `summarize_finances` |
| Energy | `query_energy`, `calculate_energy_cost`, `simulate_energy_scenario`, `get_saved_energy_comparison` |
| Documents | `list_documents`, `get_document_summary` |
| Invoices | `find_invoices`, `get_invoice` |
| Forestry | `query_forestry_sales`, `get_forestry_sale` |
| Reconciliation | `get_invoice_reconciliation` |

Lists cap at 50 rows; energy/cost periods cap at 731 days. Missing hourly coverage or tariffs fails explicitly. Scenarios retain their SCENARIO classification and assumptions; actual reconstruction remains distinct. Invoice status filtering uses a bounded scan and reports truncation.

## Model and loop

`AgentModel.generate_with_tools(messages, tools)` is a provider-neutral async protocol. `CallableModel` accepts an injected provider conversion function. Phase 06 adds an optional OpenAI adapter using native function calls and a private local key. No SDK dependency is added. Live evaluation is explicitly invoked; its acceptance limits are recorded in `phase_06_agent_evaluation.md`.

`run_agent` defaults to six rounds, allows at most eight, and gives each model response 45 seconds. A validated turn selects one tool call or references previous tool results. Final answers use trusted templates, a deterministic prose renderer, and exact referenced tool output. The model selects evidence; it cannot write financial prose or calculate values. Evidence selection can still be incomplete. Invalid references, provider errors, missing evidence and exhausted rounds are explicit; prior tool errors cannot be hidden by result selection.

The system policy requires sourced project facts, deterministic calculations, missing-coverage disclosure, no tax decisions, human review of ambiguity, and no source/email mutation.

## External capability boundary

The agent calls Gmail through `tapio/tools/gmail.py` and a fixed local stdio MCP subprocess. Only `integrations/gmail` imports Google's SDK. Six external tools augment the internal registry; internal tools remain in-process. See [Gmail integration](gmail_integration.md).

Email content is DATA, NOT INSTRUCTIONS. It appears as tool content with an explicit untrusted marker, never as a system/developer message. The registry has no send, modify, arbitrary SQL, filesystem or document-import capability. Synthetic malicious messages cannot grant those capabilities. This prevents prohibited actions; it does not prove a model cannot be misled about relevance or induced to select another permitted read tool. Human review remains required before evidence acceptance.

## Running with an injected model

```python
from tapio.agent.loop import run_agent
from tapio.agent.model import CallableModel
from tapio.tools.internal import internal_registry
from tapio.tools.gmail import gmail_session, register_gmail


async def answer(request, provider_conversion):
    registry = internal_registry()
    async with gmail_session() as session:
        register_gmail(registry, session)
        return await run_agent(request, CallableModel(provider_conversion), registry)
```

The conversion function receives tool specifications and returns a `ModelTurn`-compatible value. It must preserve message roles. The project does not select an external LLM provider or send private data to one automatically.

## Audit and evidence

`data/interim/agent/tool_audit.jsonl` is private and ignored. Records contain UTC time, hashed session reference, known tool name, argument field names (not values), success, latency and result count. Tokens, bodies and raw identifiers are excluded. Source IDs remain in typed results rather than duplicating them in the log.

Selected email bodies use private typed `EmailEvidence` manifests. Accepted PDF attachments reuse the existing atomic document loader and SHA-256 duplicate handling. There is no database migration or change to Document semantics. Import acceptance is a separate human-only command, absent from the agent registry and MCP server.

No public endpoint, background crawl, scheduler, embeddings, frontend or tax automation is included.

## Phase 06 evaluation boundary

The evaluation registry removes the three electricity calculation/query tools and does not register Gmail. It exposes ten read-only tools. The saved-energy reader verifies the existing artifact hash and does not rerun calculations. The financial aggregate groups Decimal cash amounts by currency and completed human labels, caps its source scan at 1,000 transactions, and fails rather than returning a partial total. Invoice values, candidate/confirmed payments and historical forestry sale values remain separate views. Optional live evaluation uses `PYTHONPATH=. .venv/bin/python scripts/evaluate_agent.py --live`; omit `--live` for scripted cases. Private traces contain financial results and remain ignored.

## Phase 07 supervised acceptance experiment

`tapio/agent/acceptance` provides an explicit, local evaluation runner. Its three configurations share the Phase 06 source-tool allowlist, an audited coverage projection on `summarize_finances`, the same source snapshot and the six-round budget. Configuration C adds one typed evidence-plan control operation and a final deterministic evidence-completeness gate. The plan consumes a round and cannot contain financial facts. Incomplete answers are marked for review rather than repaired with hidden tool calls. This experiment is not a user-facing endpoint or a scheduled agent.

Development and holdout definitions are versioned separately and hash-checked. Private traces are immutable by default. Holdout execution requires development and critical-case acceptance. The Phase 07 report records **NOT_READY**; no pilot is enabled. See [Phase 07 supervised acceptance](phase_07_supervised_acceptance.md) for the measured model/adapter limits and pending human review.
