"""Tests for headway_calc.mr20 (handoff 0009): the month period rule, the
latest-per-(metric, scope) SELECT shape, cell/flag/caveat derivation, the
explicit-null missing cell, rail-pending-D2 flagging, the exact-JSON package
golden, and the CLI boundary. No live database.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from conftest import RecordingConnection

from headway_calc._cli import _parse_mr20_args, mr20_main
from headway_calc.mr20 import (
    RAIL_MODES,
    build_mr20_package,
    month_period,
)


def _rows_from_fixture(fixture: dict) -> list[tuple]:
    """Render the canned metric rows as the generator's SELECT would return
    them (detail as JSON text — the fake stands in for the driver)."""
    return [
        (
            r["metric"],
            r["scope"],
            r["metric_value_id"],
            r["value"],
            r["unit"],
            r["calc_name"],
            r["calc_version"],
            r["certification_status"],
            json.dumps(r["detail"], sort_keys=True),
        )
        for r in fixture["rows"]
    ]


# --- month period -------------------------------------------------------------


def test_month_period_is_half_open_calendar_month():
    assert month_period("2026-06") == (date(2026, 6, 1), date(2026, 7, 1))
    assert month_period("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))


@pytest.mark.parametrize("bad", ["2026", "2026-6", "06-2026", "2026-13", "garbage"])
def test_month_period_refuses_malformed_months(bad):
    with pytest.raises(ValueError):
        month_period(bad)


# --- SQL shape -----------------------------------------------------------------


def test_select_is_latest_per_metric_scope_for_the_exact_period():
    conn = RecordingConnection(metric_value_rows=[])
    build_mr20_package(conn, "2026-06")

    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    # Latest per (metric, scope): newest computed_at, metric_value_id
    # tie-break — earlier rows are append-only history, untouched.
    assert "SELECT DISTINCT ON (metric, scope)" in sql
    assert "FROM computed.metric_values" in sql
    assert "WHERE period_start = %s AND period_end = %s" in sql
    assert "metric IN ('upt', 'vrh', 'vrm', 'voms')" in sql
    assert "ORDER BY metric, scope, computed_at DESC, metric_value_id DESC" in sql
    assert params == (date(2026, 6, 1), date(2026, 7, 1))


# --- the exact-JSON package golden ---------------------------------------------


def test_golden_package_exact_json(mr20_golden_fixture, mr20_golden_expected):
    """The package over the canned rows equals expected.json EXACTLY
    (tests/golden/mr20/BASIS.md — every cell, flag, caveat, banner and the
    missing subway voms cell hand-checked)."""
    conn = RecordingConnection(metric_value_rows=_rows_from_fixture(mr20_golden_fixture))
    package = build_mr20_package(conn, mr20_golden_fixture["month"])
    # Round-trip through JSON so the comparison is on the serialized form
    # (the package must already be JSON-safe: no Decimals, no dates).
    assert json.loads(json.dumps(package)) == mr20_golden_expected


def test_golden_package_headline_rules(mr20_golden_fixture):
    conn = RecordingConnection(metric_value_rows=_rows_from_fixture(mr20_golden_fixture))
    package = build_mr20_package(conn, "2026-06")

    # NOT REPORTABLE, always.
    assert package["reportable"] is False
    assert package["banner"].startswith("NOT REPORTABLE")
    # Rail pending D2 (subway is a rail-running mode per the transform map).
    assert package["modes"]["subway"]["non_reportable_pending_d2"] is True
    assert package["modes"]["bus"]["non_reportable_pending_d2"] is False
    # Missing cell = explicit null + reason, never invented.
    subway_voms = package["modes"]["subway"]["voms"]
    assert subway_voms["value"] is None
    assert "'voms'" in subway_voms["reason"] and "'mode:subway'" in subway_voms["reason"]
    assert "never invented" in subway_voms["reason"]
    # Caveats: every flag present in any cell has a caveat, plus the missing
    # cell caveat and the fixed D1-D6 list.
    caveat_ids = [c["id"] for c in package["caveats"]]
    all_flags = {
        flag
        for scope_cells in (list(package["modes"].values()) + [package["fleet"]])
        for cell in scope_cells.values()
        if isinstance(cell, dict)
        for flag in cell.get("flags", [])
    }
    for flag in all_flags:
        assert f"flag:{flag}" in caveat_ids
    assert "missing_cells" in caveat_ids
    assert caveat_ids[-6:] == ["D1", "D2", "D3", "D4", "D5", "D6"]
    # D1 is CLOSED (block-aware layover, vrh 0.4.0); the rest open.
    by_id = {c["id"]: c for c in package["caveats"]}
    assert by_id["D1"]["status"] == "closed"
    assert all(by_id[d]["status"] == "open" for d in ("D2", "D3", "D4", "D5", "D6"))


def test_rail_modes_match_the_transform_route_type_map():
    """The rail mode strings come from headway_transform.gtfs_static's
    ROUTE_TYPE_TO_MODE (route_types 0/1/2/5/7/12) — pinned here so a map
    change surfaces as a test failure, not a silent drift."""
    assert RAIL_MODES == {
        "tram",
        "subway",
        "rail",
        "cable_tram",
        "funicular",
        "monorail",
    }
    assert "bus" not in RAIL_MODES
    assert "trolleybus" not in RAIL_MODES  # rubber-tyred: not a rail mode
    assert "ferry" not in RAIL_MODES
    assert "aerial_lift" not in RAIL_MODES


def test_empty_table_yields_fleet_of_missing_cells_and_no_modes():
    conn = RecordingConnection(metric_value_rows=[])
    package = build_mr20_package(conn, "2026-06")

    assert package["modes"] == {}
    for metric in ("upt", "vrh", "vrm", "voms"):
        assert package["fleet"][metric]["value"] is None
        assert "never invented" in package["fleet"][metric]["reason"]
    caveat_ids = [c["id"] for c in package["caveats"]]
    assert "missing_cells" in caveat_ids
    assert caveat_ids[-6:] == ["D1", "D2", "D3", "D4", "D5", "D6"]
    # No cells -> no flag-derived caveats.
    assert not any(c.startswith("flag:") for c in caveat_ids)


def test_certified_current_version_cell_drops_the_version_flags(
    mr20_golden_fixture,
):
    """Flags derive from row facts: a (hypothetical) certified 1.0.0 row
    carries neither pre_verification nor uncertified."""
    rows = [
        (
            "vrm",
            "agency",
            "mv-1",
            "100.00",
            "miles",
            "vrm_v0",
            "1.0.0",
            "certified",
            json.dumps({"coverage": "1.0000"}),
        )
    ]
    package = build_mr20_package(RecordingConnection(metric_value_rows=rows), "2026-06")
    cell = package["fleet"]["vrm"]
    assert cell["flags"] == []
    assert cell["coverage"] == "1.0000"
    caveat_ids = [c["id"] for c in package["caveats"]]
    assert "flag:pre_verification" not in caveat_ids
    assert "flag:uncertified" not in caveat_ids


def test_package_is_json_serializable_and_deterministic(mr20_golden_fixture):
    rows = _rows_from_fixture(mr20_golden_fixture)
    a = build_mr20_package(RecordingConnection(metric_value_rows=rows), "2026-06")
    b = build_mr20_package(RecordingConnection(metric_value_rows=rows), "2026-06")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# --- CLI boundary ---------------------------------------------------------------


def test_mr20_cli_requires_month_and_parses_run_flag():
    with pytest.raises(SystemExit):
        _parse_mr20_args([])
    args = _parse_mr20_args(["--month", "2026-07"])
    assert args.month == "2026-07" and args.run is False
    assert _parse_mr20_args(["--month", "2026-07", "--run"]).run is True


def test_mr20_cli_refuses_without_database_url(monkeypatch):
    monkeypatch.delenv("HEADWAY_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="HEADWAY_DATABASE_URL is not set"):
        mr20_main(["--month", "2026-07"])
