"""Identical source tools in all Phase 07 configurations; coverage is metadata."""

import json
from dataclasses import replace
from pathlib import Path

from tapio.agent.evaluation import evaluation_registry
from tapio.tools.finance_schemas import FinanceSummary


class CoveredFinanceSummary(FinanceSummary):
    bank_source_coverage: dict


def acceptance_registry(*, coverage=None, **kwargs):
    registry = evaluation_registry(**kwargs)
    tool = registry.tools["summarize_finances"]
    original = tool.handler
    if coverage is None:
        coverage = json.loads(Path("data/interim/phase07/bank_coverage.json").read_text())
    public = {k: v for k, v in coverage.items() if k not in ("sources", "overlaps")}

    def covered(args):
        result = original(args)
        return CoveredFinanceSummary(**result.model_dump(), bank_source_coverage=public)

    registry.tools["summarize_finances"] = replace(
        tool,
        handler=covered,
        output_model=CoveredFinanceSummary,
        description=tool.description + " Includes bank source and review coverage.",
    )
    return registry
