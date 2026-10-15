"""Human-curated evidence comparison only. No parser, database or tariff writes."""

from typing import Literal

from pydantic import Field

from tapio.tools.schemas import Schema


class Observation(Schema):
    source_id: str
    source_kind: Literal["CONFIRMATION", "CONTRACT_PDF", "EXPIRY_NOTICE", "OFFER", "CURRENT_WEB"]
    field: str
    value: str
    excerpt: str = Field(min_length=1)
    locator: str

    def eligible(self):
        return self.source_kind in ("CONFIRMATION", "CONTRACT_PDF") or (
            self.source_kind == "EXPIRY_NOTICE" and self.field == "previous_contract.end_date"
        )


def compare_observations(observations, fields):
    """Never vote away conflicts or infer missing values. Sources are operator-reviewed."""
    observations = [Observation.model_validate(o) for o in observations]
    matrix = []
    for field in fields:
        all_values = [o for o in observations if o.field == field]
        eligible = [o for o in all_values if o.eligible()]
        values = sorted({o.value for o in eligible})
        status = (
            "CONFLICT"
            if len(values) > 1
            else "CONFIRMED"
            if len({o.source_id for o in eligible}) > 1
            else "SUPPORTED_BY_ONE_SOURCE"
            if eligible
            else "OFFER_ONLY"
            if any(o.source_kind == "OFFER" for o in all_values)
            else "MISSING"
        )
        matrix.append(
            {
                "field": field,
                "status": status,
                "accepted_value": values[0] if len(values) == 1 else None,
                "observations": [o.model_dump() for o in all_values],
            }
        )
    return matrix
