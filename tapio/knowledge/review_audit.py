"""Offline rule-use audit against frozen plans and contemporaneous explicit decisions."""

from datetime import datetime

from tapio.knowledge.user_rules import UserRule, rule_match


def audit_rule_use(batch, transactions, events):
    at = datetime.fromisoformat(batch["created_at"])
    latest = {}
    for event in sorted(events, key=lambda e: e["timestamp"]):
        if datetime.fromisoformat(event["timestamp"]) <= at:
            latest[event["candidate_id"]] = event
    active = {k: e for k, e in latest.items() if e["action"] in {"CONFIRM_RULE", "EDIT_RULE"}}
    txs = {t["id"]: t for t in transactions}
    missed, false = [], []
    eligible = 0
    for card in batch["cards"]:
        tx = txs[card["transaction"]["id"]]
        expected = {
            k: e for k, e in active.items() if rule_match(UserRule.model_validate(e["rule"]), tx)
        }
        shown = {m["rule_id"]: m for m in card.get("user_rules", [])}
        eligible += bool(expected)
        for k, event in expected.items():
            missing = k not in shown or shown[k]["event_id"] != event["id"]
            for f in ("category", "context"):
                if card.get("current_state", {}).get("authority", {}).get(
                    f
                ) != "HUMAN_CONFIRMED" and not card.get("user_rule_conflicts"):
                    missing |= card["suggestion"].get(f) != event["rule"][f]
            if missing:
                missed.append(
                    {
                        "code": "MISSED_KNOWLEDGE_REUSE",
                        "transaction_id": tx["id"],
                        "rule_event_id": event["id"],
                    }
                )
        for k, match in shown.items():
            if (
                k not in expected
                or match["event_id"] != expected[k]["id"]
                or match["rule"] != expected[k]["rule"]
                or match["evidence"] != rule_match(UserRule.model_validate(expected[k]["rule"]), tx)
            ):
                false.append(
                    {"code": "FALSE_USER_RULE_MATCH", "transaction_id": tx["id"], "rule_id": k}
                )
    return {
        "cards": len(batch["cards"]),
        "eligible_cards": eligible,
        "active_rules_at_creation": len(active),
        "missed_reuse": missed,
        "false_matches": false,
    }
