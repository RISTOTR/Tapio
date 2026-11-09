"""Current review contract and real Chromium/PostgreSQL refresh regression."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from apps.api.tests.test_confirmation_workflow import apply
from apps.api.tests.test_confirmation_workflow import setup as setup
from apps.api.tests.test_energy_load import factory as factory
from tapio.confirmation.service import Selection


def test_current_authority_and_deliberate_unknown(setup):
    service, card, _ = setup
    current = service.current_review(card["card_id"])
    assert current["context"]["value"] is None
    assert current["context"]["authority"] == "UNKNOWN"
    apply(service, card, fields={"category": "OTHER", "context": "PERSONAL"})
    current = service.current_review(card["card_id"])
    assert current["category"]["value"] == "OTHER"
    assert current["category"]["authority"] == "HUMAN_CONFIRMED"
    assert current["audit_event_id"]
    request = dict(
        card_id=card["card_id"],
        action="CHANGE",
        fields={"context": "UNKNOWN"},
        correction_reason="Explicit test correction",
        review_version=current["review_version"],
    )
    for extra in [{}, {"touched_fields": ["context"]}]:
        with pytest.raises(ValueError, match="UNCONFIRMED_UI_STATE_CHANGE"):
            service.preview(Selection(**request, **extra), "browser")
    service.preview(
        Selection(**request, touched_fields=["context"], explicit_unknown_fields=["context"]),
        "browser",
    )
    with pytest.raises(ValueError, match="STALE_STATE"):
        service.preview(Selection(**{**request, "review_version": "stale"}), "browser")


def test_real_browser_current_reload_navigation_restart(setup, factory):
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not chrome.exists():
        pytest.skip("Real Chromium required for browser integration test")
    service, _, _ = setup
    from tapio.knowledge.models import digest

    for card in service.batch["cards"]:
        card["suggestion"]["category"] = card["suggestion"]["context"] = None
    service.batch["cards_hash"] = digest(service.batch["cards"])
    env = {
        **os.environ,
        "BROWSER_TEST_DATABASE_URL": factory.kw["bind"].url.render_as_string(hide_password=False),
        "BROWSER_TEST_BATCH": json.dumps(service.batch),
        "BROWSER_BASELINE_HTML": "data/interim/review_state_repair/old_page.html",
    }
    result = subprocess.run(
        ["node", "apps/api/tests/js/review_browser.cjs"],
        env=env,
        capture_output=True,
        text=True,
        timeout=480,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_BROWSER_PASS" in result.stdout
    print(result.stdout)


@pytest.mark.parametrize(
    "concept,merchant",
    [
        ("AIRLINE", "Iberia-Vta a Bordo"),
        ("DEPARTMENT_STORE", "Stockmann"),
        ("AIRPORT_FOOD_SERVICE", "HMSHost"),
        ("GENERAL_RETAILER", "Shop"),
    ],
)
def test_entity_identity_requires_compatible_purchase_evidence(concept, merchant):
    from apps.api.tests.test_semantic_concepts import apply as concept_apply
    from apps.api.tests.test_semantic_concepts import candidate, card

    c = candidate(merchant, concept, "TRAVEL", mode="EXACT_IDENTITY")
    result = concept_apply(c, merchant=merchant)
    assert result["suggestion"]["category"] is None
    assert "PURCHASE_PURPOSE_SUPPORT_REQUIRED" in result["blocked_generalizations"]
    base = card(merchant)
    base["receipt_category_added"] = True
    base["suggestion"]["category"] = "OTHER"
    result = concept_apply(c, merchant=merchant, base=base)
    assert result["suggestion"]["category"] == "OTHER"
    assert not result["semantic_category_used"]


def test_candidate_refresh_never_rewrites_decisions(tmp_path):
    from tapio.confirmation.candidate_evidence import refreshed

    folder = tmp_path / "evidence_refresh"
    folder.mkdir()
    (folder / "w0004.json").write_text(json.dumps({"c": {"support_count": 2}}))
    assert refreshed(tmp_path, [{"id": "c", "support_count": 1}], {})[0]["support_count"] == 2
    assert (
        refreshed(tmp_path, [{"id": "c", "support_count": 1}], {"c": {}})[0]["support_count"] == 1
    )
    (folder / "w0004.json").write_text(json.dumps({"c": {"authority": "HUMAN_CONFIRMED"}}))
    with pytest.raises(ValueError, match="INVALID_CANDIDATE_EVIDENCE_REFRESH"):
        refreshed(tmp_path, [{"id": "c"}], {})
