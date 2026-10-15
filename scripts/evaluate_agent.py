"""Explicit optional evaluation; never runs during normal pytest or on a schedule."""

import argparse
import asyncio
import json
from pathlib import Path

from integrations.gmail.cache import private_write
from tapio.agent.evaluation import CASES, ScriptedModel, evaluate_case, evaluation_registry, plan
from tapio.agent.providers.openai import OpenAIModel, read_key


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case", choices=[c[0] for c in CASES])
    args = parser.parse_args()
    root = Path("data/interim/phase06")
    key = read_key() if args.live else None
    mode = "live" if args.live else "fake"
    results = []
    for case in CASES:
        if args.case and case[0] != args.case:
            continue
        model = OpenAIModel(key) if args.live else ScriptedModel(plan(case))
        result = await evaluate_case(
            case, model, evaluation_registry(audit_path=root / "tool_audit.jsonl")
        )
        results.append(result)
        private_write(
            root / f"{mode}_{case[0]}.json",
            json.dumps(result, ensure_ascii=False, indent=2).encode(),
        )
        print(
            json.dumps(
                {
                    "mode": mode,
                    "case": case[0],
                    "passed": result["passed"],
                    "rounds": result["rounds"],
                    "status": result["response"]["status"],
                    "failed_checks": [k for k, v in result["rubric"].items() if not v],
                }
            ),
            flush=True,
        )
        if (
            args.live
            and result["response"]["status"] in ("MODEL_PROVIDER_ERROR", "MODEL_TOOL_SCHEMA_ERROR")
            and not result["trace"]
        ):
            break
    private_write(
        root / f"{mode}_evaluation.json",
        json.dumps(
            {
                "mode": mode,
                "case_count": len(results),
                "passed": sum(r["passed"] for r in results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ).encode(),
    )


if __name__ == "__main__":
    asyncio.run(main())
