"""Thin bindings: deterministic business logic stays in existing services."""

from apps.api.app.services.tool_queries import Queries

from . import finance_schemas as F
from . import schemas as S
from .registry import Registry, Tool


def internal_registry(queries=None, **kwargs):
    q = queries or Queries()
    registry = Registry(**kwargs)
    definitions = [
        (
            "summarize_finances",
            F.FinanceQuery,
            F.FinanceSummary,
            q.summarize_finances,
            (
                "Deterministic bank cash totals by human context/category/currency. "
                "Unknowns separate; never sum transaction pages or mix invoices/sales "
                "with cash. Maximum 1000 rows, fails rather than truncating totals."
            ),
        ),
        (
            "get_saved_energy_comparison",
            F.SavedEnergyQuery,
            F.SavedEnergySummary,
            q.saved_energy_comparison,
            (
                "Read frozen accepted April-August 2026 fixed-versus-spot household net "
                "result. No electricity recalculation. Use for spot savings questions; "
                "disclose limited retrospective coverage."
            ),
        ),
        (
            "query_transactions",
            S.TransactionQuery,
            S.Page[S.TransactionSummary],
            q.transactions,
            "Bounded transactions with human-reviewed labels only; no raw bank identifiers.",
        ),
        (
            "query_energy",
            S.EnergyQuery,
            S.EnergySummary,
            q.energy,
            "Measured energy total from deterministic code; requires complete hourly coverage.",
        ),
        (
            "calculate_energy_cost",
            S.CostQuery,
            S.CostSummary,
            q.cost,
            "Phase 04 costs. Missing tariffs fail; totals cover selected components.",
        ),
        (
            "simulate_energy_scenario",
            S.ScenarioQuery,
            S.ScenarioSummary,
            q.scenario,
            "Phase 04 retrospective scenario/comparison; same measured profile, explicit pricing.",
        ),
        (
            "list_documents",
            S.DocumentQuery,
            S.Page[S.DocumentSummary],
            q.documents,
            "Bounded source document metadata without extracted text.",
        ),
        (
            "get_document_summary",
            S.DocumentID,
            S.DocumentSummary,
            q.document_summary,
            "Source metadata and parser provenance for one document.",
        ),
        (
            "get_invoice",
            S.InvoiceID,
            S.InvoiceSummary,
            q.invoice,
            "Stored invoice amounts and read-only reconciliation state.",
        ),
        (
            "find_invoices",
            S.InvoiceQuery,
            S.Page[S.InvoiceSummary],
            q.invoices,
            "Bounded invoice search; truncated means further records may exist.",
        ),
        (
            "get_invoice_reconciliation",
            S.InvoiceID,
            S.ReconciliationSummary,
            q.invoice_reconciliation,
            "Read-only existing allocation state; ambiguous requires human review.",
        ),
        (
            "get_forestry_sale",
            S.ForestryID,
            S.ForestrySummary,
            q.forestry_sale,
            "Stored forestry amounts, volumes and source provenance; no tax decision.",
        ),
        (
            "query_forestry_sales",
            S.ForestryQuery,
            S.Page[S.ForestrySummary],
            q.forestry_sales,
            "Bounded forestry source-fact search.",
        ),
    ]
    for name, input_, output, handler, description in definitions:
        registry.add(Tool(name, description, input_, output, handler))
    return registry
