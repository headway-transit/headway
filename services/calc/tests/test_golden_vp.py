"""Golden-dataset regression test for the vp_*_v0 calcs (handoff 0042).

Fixture: tests/golden/vp_v0/fixture.json; expectations: expected.json,
hand-worked in BASIS.md — synthetic, NOT FTA-certified (there is no
reportable VP number here: every figure REFUSES). The golden pins the
REFUSAL CONTRACT: value None, the naming blocking finding, and the honest
observed-movement context detail (basis conflict, unmeasured series,
simulated source).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from headway_calc.types import VpTelematicsDay
from headway_calc.vp import (
    compute_vp_upt,
    compute_vp_voms,
    compute_vp_vrh,
    compute_vp_vrm,
)

VP_GOLDEN_DIR = Path(__file__).resolve().parents[3] / "tests" / "golden" / "vp_v0"

_COMPUTE = {
    "vrm": compute_vp_vrm,
    "vrh": compute_vp_vrh,
    "upt": compute_vp_upt,
    "voms": compute_vp_voms,
}


def _load_rows(rows: list[dict]) -> list[VpTelematicsDay]:
    out: list[VpTelematicsDay] = []
    for r in rows:
        out.append(
            VpTelematicsDay(
                vehicle_id=r["vehicle_id"],
                service_date=date.fromisoformat(r["service_date"]),
                window_start=datetime.fromisoformat(r["window_start"]),
                window_end=datetime.fromisoformat(r["window_end"]),
                measure=r["measure"],
                basis=r["basis"],
                unit=r["unit"],
                reading_kind=r["reading_kind"],
                sample_count=r["sample_count"],
                source=r["source"],
                source_record_id=r["source_record_id"],
                vehicle_label=r.get("vehicle_label"),
                value=Decimal(r["value"]) if r.get("value") is not None else None,
                first_reading_at=(
                    datetime.fromisoformat(r["first_reading_at"])
                    if r.get("first_reading_at")
                    else None
                ),
                first_reading_value=(
                    Decimal(r["first_reading_value"])
                    if r.get("first_reading_value") is not None
                    else None
                ),
                last_reading_at=(
                    datetime.fromisoformat(r["last_reading_at"])
                    if r.get("last_reading_at")
                    else None
                ),
                last_reading_value=(
                    Decimal(r["last_reading_value"])
                    if r.get("last_reading_value") is not None
                    else None
                ),
                max_sample_gap_seconds=r.get("max_sample_gap_seconds"),
            )
        )
    return out


def _fixture() -> list[VpTelematicsDay]:
    raw = json.loads((VP_GOLDEN_DIR / "fixture.json").read_text())
    return _load_rows(raw["vanpool_day"]["rows"])


def _expected() -> dict:
    return json.loads((VP_GOLDEN_DIR / "expected.json").read_text())


def test_vp_golden_matches_expected():
    rows = _fixture()
    expected = _expected()
    for figure, fn in _COMPUTE.items():
        exp = expected[figure]
        result = fn(rows)
        assert result.value is None, figure
        assert result.unit == exp["unit"], figure
        assert result.calc_name == exp["calc_name"], figure
        assert result.calc_version == exp["calc_version"], figure
        assert list(result.input_record_ids) == exp["input_record_ids"], figure
        assert [f.issue_type for f in result.blocking_issues] == exp[
            "blocking_issue_types"
        ], figure
        assert sorted(f.issue_type for f in result.warnings) == exp[
            "warning_types"
        ], figure
        assert sorted(f.issue_type for f in result.infos) == exp["info_types"], figure
        assert result.detail.to_dict() == exp["detail"], figure


def test_vp_golden_observed_distance_excludes_unmeasured():
    """The observed distance is exactly the two MEASURED van-42 series
    (72000 + 72900); the unmeasured van-77 series adds nothing (never 0)."""
    detail = compute_vp_vrm(_fixture()).detail
    assert detail.observed_distance_meters == "144900"
    assert detail.vehicle_days_unmeasured == 1
