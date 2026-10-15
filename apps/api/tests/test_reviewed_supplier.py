"""Synthetic human-reviewed tariffs and import-only actual/spot comparisons."""

import copy
import hashlib
import json
from datetime import date

import pytest
from pydantic import ValidationError

from apps.api.tests.test_energy_cost import readings, scenario, tariffs
from data_pipeline.energy_cost.engine import calculate
from data_pipeline.energy_cost.import_comparison import compare_actual_import
from data_pipeline.energy_cost.reviewed import AcceptedSupplier, load_reviewed, verify_review
from data_pipeline.energy_cost.scenarios import SupplierScenario
from data_pipeline.energy_cost.sources import Tariffs
from data_pipeline.energy_cost.spot import SpotMetadata, SpotPrices
from data_pipeline.energy_cost.types import Component, CostError, D


@pytest.fixture
def contract():
    return AcceptedSupplier(
        authority="HUMAN_CONFIRMED",
        meter_sha256=hashlib.sha256(b"synthetic-meter").hexdigest(),
        supplier="Synthetic supplier",
        product="Synthetic 24-month contract",
        pricing_type="FIXED",
        contract_type="FIXED_TERM",
        start_date=date(2025, 12, 1),
        end_date=date(2027, 11, 30),
        price_valid_from=date(2025, 12, 1),
        price_valid_to=date(2027, 11, 30),
        previous_end_date=date(2025, 11, 30),
        duration_months=24,
        energy_snt_per_kwh=D("8.24"),
        monthly_fee_eur=D("4.95"),
        vat_percent=D("25.5"),
        vat_basis="INCLUDED",
        review_path="synthetic-review.json",
        reviewed_source={
            "source_message_ids": ("synthetic4", "synthetic5", "synthetic6"),
            "pdf_download_sha256": "a" * 64,
            "review_sha256": "b" * 64,
            "caveat": "Separate evidence required for actual tax changes",
        },
    )


def review_for(c):
    fields = (
        "supplier",
        "product",
        "pricing_type",
        "contract_type",
        "start_date",
        "end_date",
        "price_valid_from",
        "price_valid_to",
        "duration_months",
        "energy_snt_per_kwh",
        "monthly_fee_eur",
        "vat_percent",
        "vat_basis",
    )
    pairs = {"new_contract." + f: str(getattr(c, f)) for f in fields}
    pairs["previous_contract.end_date"] = str(c.previous_end_date)
    return {
        "evidence_matrix": [
            {
                "field": f,
                "status": "SUPPORTED_BY_ONE_SOURCE",
                "accepted_value": v,
                "observations": [{"value": v, "source_kind": "CONTRACT_PDF"}],
            }
            for f, v in pairs.items()
        ],
        "sources": [
            {
                "message_id": m,
                **(
                    {"download_sha256": "a" * 64, "document_id": None, "parser_version": None}
                    if i == 2
                    else {}
                ),
            }
            for i, m in enumerate(c.reviewed_source.source_message_ids)
        ],
    }


def spot_for(rows):
    prices = SpotPrices(
        {r.timestamp: D(".06") for r in rows},
        SpotMetadata(
            source="synthetic",
            market_area="FI",
            currency="EUR",
            resolution="PT1H",
            timezone="UTC",
            price_basis="NET",
            vat_rate=D("25.5"),
        ),
        "synthetic",
    )
    return SupplierScenario(
        scenario(
            import_pricing_type="spot",
            fixed_import_price=None,
            supplier_monthly_fee=D("5.95"),
            spot_markup_per_kwh=D(".005"),
        ),
        prices,
    )


def test_mapping_and_no_fabricated_document(contract):
    energy, fee = contract.tariffs()
    assert energy.unit_price == D(".0824") and fee.unit_price == D("4.95")
    assert energy.gross_rate == D(".0824") and energy.vat_rate == D("25.5")
    assert energy.source_document_id is None and energy.source_kind == "REVIEWED_CONTRACT"
    assert energy.reviewed_source.structured_document_parser is False
    assert energy.source_version == "reviewed-supplier-1"


@pytest.mark.parametrize(
    "day,covered",
    [
        (date(2025, 11, 30), False),
        (date(2025, 12, 1), True),
        (date(2027, 11, 30), True),
        (date(2027, 12, 1), False),
    ],
)
def test_inclusive_source_boundaries(contract, day, covered):
    assert contract.tariffs()[0].covers(day) == covered


def test_previous_contract_cannot_overlap(contract):
    with pytest.raises(ValidationError):
        AcceptedSupplier.model_validate(
            {**contract.model_dump(), "previous_end_date": date(2025, 12, 1)}
        )


def test_overlap_rejected_not_silently_overwritten(contract):
    with pytest.raises(CostError, match="OVERLAPPING"):
        Tariffs(contract.tariffs() + contract.tariffs())


@pytest.mark.parametrize(
    "start,end,hours",
    [(date(2025, 12, 1), date(2025, 12, 31), 744), (date(2026, 2, 1), date(2026, 2, 28), 672)],
)
def test_actual_complete_month(contract, start, end, hours):
    result = calculate(
        readings(start, end),
        Tariffs(contract.tariffs()),
        start,
        end,
        scope="supplier",
        export_policy="exclude",
    )
    m = result["monthly"][0]
    assert result["mode"] == "ACTUAL_RECONSTRUCTION"
    assert m["consumption_kwh"] == D(hours)
    assert m["supplier_fixed_cost"] == D("4.95")
    assert m["supplier_energy_cost"] == (D(hours) * D(".0824")).quantize(D(".01"))


def test_partial_october_no_fee_proration(contract):
    start, end = date(2026, 10, 1), date(2026, 10, 5)
    m = calculate(
        readings(start, end),
        Tariffs(contract.tariffs()),
        start,
        end,
        scope="supplier",
        export_policy="exclude",
    )["monthly"][0]
    assert m["supplier_fixed_cost"] is None and m["scope_total"] is None
    assert m["fixed_fee_policy"] == "FULL_CALENDAR_MONTH_ONLY"


def test_identical_consumption_and_period_aggregation(contract):
    start, end = date(2025, 12, 1), date(2026, 1, 31)
    rows = readings(start, end, export="2")
    before = [r.model_dump() for r in rows]
    result = compare_actual_import(rows, Tariffs(contract.tariffs()), start, end, spot_for(rows))
    a, b = result["fixed"]["totals"], result["spot"]["totals"]
    assert a["consumption_kwh"] == b["consumption_kwh"] == D("1488")
    assert a["supplier_fixed_cost"] == D("9.90") and b["supplier_fixed_cost"] == D("11.90")
    assert a["scope_total"] == sum(m["scope_total"] for m in result["fixed"]["monthly"])
    assert [r.model_dump() for r in rows] == before
    assert result["scope"] == "SUPPLIER_IMPORT_ONLY" and result["net_household_total"] is None
    assert result["fixed"]["monthly"][0]["solar_export_credit"] is None


def test_household_import_label_and_missing_export(contract):
    start, end = date(2026, 4, 1), date(2026, 4, 30)
    rows = readings(start, end, export="2")
    grid = [
        t
        for t in tariffs().values
        if t.component
        in (Component.GRID_TRANSFER, Component.ELECTRICITY_TAX, Component.GRID_FIXED_FEE)
    ]
    ts = Tariffs([*grid, *contract.tariffs()])
    result = compare_actual_import(rows, ts, start, end, spot_for(rows), scope="all")
    assert result["scope"] == "HOUSEHOLD_IMPORT_SIDE" and result["net_household_total"] is None
    assert result["fixed"]["monthly"][0]["net_total_cost"] is None
    for field in ("grid_transfer_cost", "electricity_tax_cost", "grid_fixed_cost"):
        assert result["fixed"]["totals"][field] == result["spot"]["totals"][field]
    with pytest.raises(CostError, match="MISSING_PRICE"):
        calculate(rows, ts, start, end)  # Default never silently omits missing export.


@pytest.mark.parametrize(
    "kind,status", [("OFFER", "OFFER_ONLY"), ("OFFER", "CONFIRMED"), ("CURRENT_WEB", "CONFIRMED")]
)
def test_offer_or_live_web_cannot_override(contract, kind, status):
    r = review_for(contract)
    r["evidence_matrix"][0]["status"] = status
    r["evidence_matrix"][0]["observations"][0]["source_kind"] = kind
    with pytest.raises(CostError):
        verify_review(contract, r)


def test_review_hash_and_meter_binding(contract, tmp_path):
    r = review_for(contract)
    payload = json.dumps(r).encode()
    rp = tmp_path / "review.json"
    rp.write_bytes(payload)
    c = AcceptedSupplier.model_validate(
        {
            **contract.model_dump(),
            "review_path": str(rp),
            "reviewed_source": {
                **contract.reviewed_source.model_dump(),
                "review_sha256": hashlib.sha256(payload).hexdigest(),
            },
        }
    )
    cfg = tmp_path / "approved.json"
    cfg.write_text(json.dumps([c.model_dump(mode="json")]))
    assert len(load_reviewed("synthetic-meter", cfg)) == 2
    assert load_reviewed("unrelated-meter", cfg) == []
    rp.write_text("{}")
    with pytest.raises(CostError, match="HASH_MISMATCH"):
        load_reviewed("synthetic-meter", cfg)


def test_conflicting_accepted_value_rejected(contract):
    r = copy.deepcopy(review_for(contract))
    r["evidence_matrix"][0]["status"] = "CONFLICT"
    with pytest.raises(CostError):
        verify_review(contract, r)


def test_reviewed_provenance_cannot_claim_document(contract):
    t = contract.tariffs()[0]
    with pytest.raises(ValidationError):
        type(t).model_validate({**t.model_dump(), "source_document_id": "fabricated"})
