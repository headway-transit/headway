"""preview_period / preview_ops_period (handoff 0017, design point 6) — the
sandbox what-if entry points.

THE test that matters most here is the no-write pin: a preview must perform
ZERO writes (no dq.issues, no computed.metric_values, no lineage.edges, no
commit) — its results are ephemeral, so a sandbox figure can never exist
anywhere certification could reach it. The rest pins: shared threshold
resolution (a variant with no overrides resolves exactly like a real
settings-governed run), per-variant value movement on the golden fixture
(lowering coverage_threshold un-blocks the gapped golden case exactly like
run_period's explicit flag), findings surfaced per variant without being
routed, and the ops preview's window sensitivity over the ops golden case.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from conftest import (
    RecordingConnection,
    load_ops_case_positions,
    load_ops_schedule_rows,
    load_positions,
    positions_to_rows,
)

from headway_calc.runner import (
    PreviewOpsVariant,
    PreviewVariant,
    preview_ops_period,
    preview_period,
    run_period,
)

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 2, 1)


def _gapped_conn(golden_fixture) -> RecordingConnection:
    """The full vrm/vrh golden fixture — trip-C gapped, coverage 2/3, which
    BLOCKS at the seeded 0.95 threshold and persists at an explicit 0.60."""
    return RecordingConnection(
        position_rows=positions_to_rows(load_positions(golden_fixture))
    )


def _ops_schedule_to_rows(schedule) -> list[tuple]:
    return [
        (
            s.trip_id, s.stop_id, s.stop_sequence, s.latitude, s.longitude,
            s.arrival_seconds, s.departure_seconds, s.route_id, s.direction_id,
        )
        for s in schedule
    ]


def _ops_conn(ops_golden_fixture, case: str) -> RecordingConnection:
    return RecordingConnection(
        position_rows=positions_to_rows(
            load_ops_case_positions(ops_golden_fixture, case)
        ),
        ops_schedule_rows=_ops_schedule_to_rows(
            load_ops_schedule_rows(ops_golden_fixture)
        ),
        agency_timezone_rows=[
            (tz,) for tz in ops_golden_fixture["agency_timezones"]
        ],
    )


# ---------------------------------------------------------------------------
# THE WALL: previews never write.
# ---------------------------------------------------------------------------


def test_preview_never_writes_and_never_commits(golden_fixture):
    conn = _gapped_conn(golden_fixture)
    report = preview_period(
        conn,
        PERIOD_START,
        PERIOD_END,
        [
            PreviewVariant(label="baseline"),
            PreviewVariant(label="proposed", coverage_threshold="0.60"),
        ],
    )
    # The gapped golden case blocks at 0.95 and persists at 0.60 in a REAL
    # run — this preview produced both outcomes and still wrote NOTHING.
    writes = [
        (sql, params)
        for sql, params in conn.executed
        if not sql.lstrip().upper().startswith("SELECT")
    ]
    assert writes == []
    assert conn.commits == []
    assert conn.rollback_count == 0
    assert report.persisted is False
    assert report.to_dict()["persisted"] is False


def test_ops_preview_never_writes_and_never_commits(ops_golden_fixture):
    conn = _ops_conn(ops_golden_fixture, "clean_two_trips")
    report = preview_ops_period(
        conn,
        PERIOD_START,
        PERIOD_END,
        [
            PreviewOpsVariant(label="baseline"),
            PreviewOpsVariant(label="proposed", otp_late_tolerance_seconds=900),
        ],
    )
    writes = [
        (sql, params)
        for sql, params in conn.executed
        if not sql.lstrip().upper().startswith("SELECT")
    ]
    assert writes == []
    assert conn.commits == []
    assert report.persisted is False
    assert report.to_dict()["persisted"] is False


# ---------------------------------------------------------------------------
# Values and refusals move exactly like a real run's.
# ---------------------------------------------------------------------------


def test_preview_matches_real_run_values_per_variant(golden_fixture):
    """Baseline (settings-governed 0.95) blocks vrm/vrh on the gapped golden
    case; the proposed 0.60 variant yields exactly the value a REAL run with
    the explicit flag persists."""
    preview = preview_period(
        _gapped_conn(golden_fixture),
        PERIOD_START,
        PERIOD_END,
        [
            PreviewVariant(label="baseline"),
            PreviewVariant(label="proposed", coverage_threshold="0.60"),
        ],
    )
    baseline, proposed = preview.variants
    base_by_metric = {o.metric: o for o in baseline.outcomes}
    prop_by_metric = {o.metric: o for o in proposed.outcomes}

    assert base_by_metric["vrm"].blocked and base_by_metric["vrm"].value is None
    assert any(
        f.severity == "blocking" for f in base_by_metric["vrm"].findings
    )
    assert not prop_by_metric["vrm"].blocked

    # The same period through the real runner with the same explicit flag:
    real = run_period(
        _gapped_conn(golden_fixture),
        PERIOD_START,
        PERIOD_END,
        coverage_threshold="0.60",
    )
    real_vrm = next(o for o in real.outcomes if o.metric == "vrm")
    assert prop_by_metric["vrm"].value == real_vrm.value
    assert prop_by_metric["vrm"].detail == real_vrm.detail


def test_preview_threshold_resolution_is_the_runners(golden_fixture):
    """No-override variant resolves from app.settings ('settings'); an
    override resolves 'explicit'; read_settings=False falls to defaults."""
    preview = preview_period(
        _gapped_conn(golden_fixture),
        PERIOD_START,
        PERIOD_END,
        [
            PreviewVariant(label="baseline"),
            PreviewVariant(label="proposed", layover_max_seconds=1200),
        ],
    )
    baseline, proposed = preview.variants
    assert baseline.threshold_sources == {
        "gap_threshold_seconds": "settings",
        "coverage_threshold": "settings",
        "layover_max_seconds": "settings",
        "missing_trip_threshold": "settings",
        "imbalance_threshold": "default",
    }
    assert baseline.thresholds["coverage_threshold"] == "0.95"
    assert proposed.threshold_sources["layover_max_seconds"] == "explicit"
    assert proposed.thresholds["layover_max_seconds"] == "1200.0"

    ignored = preview_period(
        _gapped_conn(golden_fixture),
        PERIOD_START,
        PERIOD_END,
        [PreviewVariant(label="defaults")],
        read_settings=False,
    )
    assert ignored.variants[0].threshold_sources["coverage_threshold"] == (
        "default"
    )


def test_preview_refuses_empty_variant_list(golden_fixture):
    with pytest.raises(ValueError):
        preview_period(_gapped_conn(golden_fixture), PERIOD_START, PERIOD_END, [])
    with pytest.raises(ValueError):
        preview_ops_period(
            _gapped_conn(golden_fixture), PERIOD_START, PERIOD_END, []
        )


def test_preview_report_shape_is_json_safe(golden_fixture):
    report = preview_period(
        _gapped_conn(golden_fixture),
        PERIOD_START,
        PERIOD_END,
        [PreviewVariant(label="baseline")],
    )
    d = report.to_dict()
    assert d["period_convention"] == "half-open [period_start, period_end), UTC"
    outcome = d["variants"][0]["outcomes"][0]
    # value is a string or None — Decimal never leaks into the dict.
    assert outcome["value"] is None or isinstance(outcome["value"], str)
    for f in outcome["findings"]:
        assert set(f) == {"issue_type", "severity", "title"}
    import json

    json.dumps(d)  # must not raise


# ---------------------------------------------------------------------------
# Ops preview: the window moves the verdict, over one shared derivation.
# ---------------------------------------------------------------------------


def test_ops_preview_window_moves_otp(ops_golden_fixture):
    """The ops golden clean case scores otp 50.00 at the 60/300 default; a
    much wider late window flips the late passage on time. Both variants
    come from ONE derivation (same passages_derived)."""
    report = preview_ops_period(
        _ops_conn(ops_golden_fixture, "clean_two_trips"),
        PERIOD_START,
        PERIOD_END,
        [
            PreviewOpsVariant(label="baseline"),
            PreviewOpsVariant(
                label="proposed", otp_late_tolerance_seconds=100000
            ),
        ],
    )
    baseline, proposed = report.variants
    assert baseline.thresholds == {
        "otp_early_tolerance_seconds": "60",
        "otp_late_tolerance_seconds": "300",
    }
    assert baseline.threshold_sources["otp_late_tolerance_seconds"] == (
        "settings"
    )
    assert proposed.threshold_sources["otp_late_tolerance_seconds"] == (
        "explicit"
    )
    (base_otp,) = baseline.outcomes
    (prop_otp,) = proposed.outcomes
    assert base_otp.metric == "otp"
    assert base_otp.value == "50.00"
    assert Decimal(prop_otp.value) > Decimal(base_otp.value)
    assert report.passages_derived > 0
    assert report.derivation  # the refusal accounting travels with the report
