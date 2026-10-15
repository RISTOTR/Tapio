"""Monthly billed credits stay authoritative; all provenance identifiers are synthetic."""

import copy
import hashlib
import json
from decimal import Decimal as D

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from apps.api.app.domain.models import Document
from apps.api.tests.test_energy_load import factory as factory
from data_pipeline.energy_cost.actual_export import (
    AcceptedExportCredits,
    apply_actual_export_credits,
)
from data_pipeline.energy_cost.types import CostError


@pytest.fixture
def accepted():
    return AcceptedExportCredits.model_validate(
        {
            "version": "actual-export-credits-1",
            "customer_vat_liability": "NON_VAT_LIABLE",
            "applicability_source": "HUMAN_CONFIRMED_PROPERTY_CONTEXT",
            "scope": "PROPERTY_EXPORT_ONLY",
            "credits": [
                {
                    "year_month": f"2026-{month:02d}",
                    "export_kwh": "10.00",
                    "actual_credit_eur": credit,
                    "billed_margin_snt_per_kwh": "0.24" if month == 8 else "0.30",
                    "evidence_status": "ACTUAL_BILLED",
                    "source": {
                        "invoice_reference": f"SYNTHETIC-{month}",
                        "message_id": "synthetic-message",
                        "attachment_filename": "synthetic.pdf",
                        "pdf_sha256": "a" * 64,
                        "review_sha256": "b" * 64,
                        "acceptance_sha256": "c" * 64,
                        "page": 5,
                        "extraction_status": "REVIEWED_EXTRACTED_LINES_NOT_IMPORTED",
                    },
                }
                for month, credit in zip(
                    range(4, 9), ["2.15", "4.03", "4.54", "1.05", "3.44"], strict=True
                )
            ],
        }
    )


@pytest.fixture
def saved():
    def row(month, spot):
        return {
            "month": f"2026-{month:02d}",
            "complete_month": True,
            "solar_export_credit": None,
            "net_total_cost": None,
            "supplier_energy_cost": "60.00" if spot else "80.00",
            "supplier_fixed_cost": "5.00",
            "grid_transfer_cost": "10.00",
            "electricity_tax_cost": "15.00",
            "grid_fixed_cost": "20.00",
            "scope_total": "110.00" if spot else "130.00",
            "raw_spot_energy_cost": "58.00" if spot else None,
            "retailer_markup_cost": "2.00" if spot else None,
            "consumption_kwh": "100.00",
        }

    return {
        "scope": "HOUSEHOLD_IMPORT_SIDE",
        "fixed": {"monthly": [row(m, False) for m in range(4, 10)]},
        "spot": {"monthly": [row(m, True) for m in range(4, 10)]},
    }


@pytest.mark.parametrize(
    "month,credit", [(4, "2.15"), (5, "4.03"), (6, "4.54"), (7, "1.05"), (8, "3.44")]
)
def test_each_accepted_month(month, credit, saved, accepted):
    result = apply_actual_export_credits(saved, accepted)
    row = next(r for r in result["monthly"] if r["year_month"] == f"2026-{month:02d}")
    assert row["actual_export_credit"] == D(credit)
    assert row["net_fixed_household_total"] == D("130") - D(credit)
    assert row["net_spot_household_total"] == D("110") - D(credit)


def test_same_credit_preserves_difference_and_winner(saved, accepted):
    for r in apply_actual_export_credits(saved, accepted)["monthly"]:
        assert r["fixed_minus_spot_eur"] == D(20)
        assert r["winner"] == "spot" and r["winner_unchanged"]
        assert r["difference_percent_of_net_fixed"] == D(20) / r["net_fixed_household_total"] * 100


def test_five_month_sum_excludes_september(saved, accepted):
    r = apply_actual_export_credits(saved, accepted)
    assert r["excluded_import_months"] == ["2026-09"]
    assert len(r["monthly"]) == 5
    assert r["aggregate"]["actual_export_credit"] == D("15.21")
    assert r["aggregate"]["net_fixed_household_total"] == D("634.79")
    assert r["aggregate"]["net_spot_household_total"] == D("534.79")


def test_no_tariff_or_hourly_diagnostic_promotion(saved, accepted):
    saved["hourly_export_diagnostic"] = {"credit": "999999", "policy": "FLOOR"}
    r = apply_actual_export_credits(saved, accepted)
    assert r["continuous_export_tariff"] is None
    assert r["aggregate"]["actual_export_credit"] == D("15.21")
    assert r["negative_price_policy"].startswith("UNRESOLVED")


def test_provenance_and_saved_components_preserved(saved, accepted):
    before = copy.deepcopy(saved)
    r = apply_actual_export_credits(saved, accepted)
    assert saved == before
    assert r["monthly"][0]["accepted_export_evidence"] == accepted.credits[0].model_dump()
    assert r["monthly"][0]["saved_import_components"]["fixed"] == saved["fixed"]["monthly"][0]
    r["monthly"][0]["saved_import_components"]["fixed"]["scope_total"] = "0"
    assert saved == before


@pytest.mark.parametrize(
    "change", ["float", "duplicate", "tariff", "hourly", "invalid_month", "fractional_cent"]
)
def test_invalid_evidence_rejected(accepted, change):
    raw = accepted.model_dump(mode="json")
    c = raw["credits"][0]
    if change == "float":
        c["actual_credit_eur"] = 2.15
    if change == "duplicate":
        raw["credits"].append(copy.deepcopy(c))
    if change == "tariff":
        c["continuous_tariff_inference"] = True
    if change == "hourly":
        c["evidence_status"] = "RECONSTRUCTED"
    if change == "invalid_month":
        c["year_month"] = "2026-13"
    if change == "fractional_cent":
        c["actual_credit_eur"] = "2.155"
    with pytest.raises(ValidationError):
        AcceptedExportCredits.model_validate(raw)


@pytest.mark.parametrize("change", ["missing", "partial", "netted", "grid", "total"])
def test_invalid_import_inputs_rejected(saved, accepted, change):
    row = saved["fixed"]["monthly"][0]
    if change == "missing":
        saved["fixed"]["monthly"].pop(0)
    if change == "partial":
        row["complete_month"] = False
    if change == "netted":
        row["solar_export_credit"] = "2.15"
    if change == "grid":
        row["grid_transfer_cost"] = "11.00"
        row["scope_total"] = "131.00"
    if change == "total":
        row["scope_total"] = "99.00"
    with pytest.raises(CostError):
        apply_actual_export_credits(saved, accepted)


def test_protected_input_file_unchanged(tmp_path, saved, accepted):
    p = tmp_path / "saved.json"
    p.write_text(json.dumps(saved))
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    first = apply_actual_export_credits(json.loads(p.read_text()), accepted)
    second = apply_actual_export_credits(json.loads(p.read_text()), accepted)
    assert first == second
    assert hashlib.sha256(p.read_bytes()).hexdigest() == digest


def test_database_source_tables_unchanged(factory, saved, accepted):
    def snapshot():
        with factory() as s:
            return {
                t.name: list(s.execute(select(t)).mappings())
                for t in Document.metadata.sorted_tables
            }

    before = snapshot()
    apply_actual_export_credits(saved, accepted)
    assert snapshot() == before
