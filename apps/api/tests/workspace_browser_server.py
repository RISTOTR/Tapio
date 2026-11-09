"""Isolated browser fixture using the production shell/routes, synthetic evidence only."""

import os
from pathlib import Path
from uuid import uuid4

from tapio.pilot import api
from tapio.pilot.contracts import Coverage, Evidence, PilotResponse, Session
from tapio.pilot.history import History

os.environ["TAPIO_PILOT_MODE"] = "true"
root = Path(os.environ["WORKSPACE_TEST_ROOT"])
if not root.name.startswith("tapio-workspace-browser-"):
    raise ValueError("TEMPORARY_TEST_ROOT_REQUIRED")


class SyntheticPilot:
    history = History(root / "history")

    async def ask(self, question, **kwargs):
        session = Session(
            id=str(uuid4()),
            timestamp="2026-11-09T10:00:00Z",
            model_calls=0,
            rounds=0,
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            latency_seconds=0.01,
            estimated_cost_usd="0",
        )
        result = PilotResponse(
            answer="Synthetic example: forestry expenses total €120.50.",
            direct_answer="Synthetic example: forestry expenses total €120.50.",
            evidence_state="PARTIAL_COVERAGE",
            evidence_states=["PARTIAL_COVERAGE"],
            coverage=Coverage(status="DETERMINED"),
            evidence=[Evidence(kind="BANK_CASH_FLOW", summary="Synthetic bank fixture", records=2)],
            human_review=[],
            limitations=[
                "Synthetic fixture only. Imported records do not establish full-year coverage."
            ],
            evidence_summary=["Two synthetic bank transactions."],
            session=session,
            optional_details={
                "transactions": [
                    {
                        "merchant": "Example forestry supplier",
                        "date": "2025-06-01",
                        "amount": "-120.50",
                        "currency": "EUR",
                        "source": "Synthetic CSV",
                    }
                ]
            },
        )
        self.history.save(session.id, {"response": result.model_dump(mode="json")})
        return result


pilot = SyntheticPilot()
api.get_pilot = lambda: pilot
api.database_available = lambda: None
app = api.app
