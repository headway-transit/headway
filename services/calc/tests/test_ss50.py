"""Tests for headway_calc.ss50 (handoff 0010): the due-date rule, the SQL
shapes (latest classification per event; the handoff-0009 operated-mode
derivation), per-mode/TOS non-major counting with per-cell provenance,
explicit zero rows, the exclusion lists (major / not-reportable /
superseded / unclassified), the S&S-40 detail export, and the CLI boundary.
No live database.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from conftest import RecordingConnection

from headway_calc._cli import _parse_ss50_args, ss50_main
from headway_calc.ss50 import (
    build_ss40_export,
    build_ss50_package,
    ss50_due_date,
)

UTC = timezone.utc
JUNE = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


def month_event_row(
    event_id,
    *,
    mode="bus",
    tos="DO",
    category="other",
    fatalities=0,
    injuries=0,
    assault_on_worker=False,
    superseded_by=None,
    classification="not_reportable",
    thresholds_met=(),
    occurred_at=JUNE,
):
    """One pre-joined row in _SELECT_MONTH_EVENTS_SQL column order."""
    return (
        event_id, occurred_at, mode, tos, category, fatalities, injuries,
        assault_on_worker, superseded_by, classification,
        list(thresholds_met) if thresholds_met is not None else None,
        "sscls_v0 0.1.0",
    )


# --- due date (p. 4 + Exhibit 3, p. 5: end of the following month) -------------


def test_ss50_due_date_is_end_of_following_month():
    assert ss50_due_date("2026-06") == date(2026, 7, 31)
    assert ss50_due_date("2026-01") == date(2026, 2, 28)  # January→Feb 28
    assert ss50_due_date("2026-12") == date(2027, 1, 31)  # December→Jan 31
    assert ss50_due_date("2026-11") == date(2026, 12, 31)
    assert ss50_due_date("2027-01") == date(2027, 2, 28)


# --- SQL shapes -----------------------------------------------------------------


def test_sql_latest_classification_per_event_and_mode_derivation():
    conn = RecordingConnection()
    build_ss50_package(conn, "2026-06")

    assert len(conn.executed) == 2
    events_sql, events_params = conn.executed[0]
    assert "SELECT DISTINCT ON (e.event_id)" in events_sql
    assert "LEFT JOIN safety.event_classifications" in events_sql
    assert "WHERE e.occurred_at >= %s AND e.occurred_at < %s" in events_sql
    assert (
        "ORDER BY e.event_id, c.classified_at DESC, c.classification_id DESC"
        in events_sql
    )
    assert events_params == (
        datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 7, 1, tzinfo=UTC),
    )
    modes_sql, modes_params = conn.executed[1]
    # The SAME derivation as the per-mode calc path (handoff 0009).
    assert "SELECT DISTINCT r.mode" in modes_sql
    assert "FROM canonical.vehicle_positions AS p" in modes_sql
    assert "LEFT JOIN canonical.trips AS t ON t.trip_id = p.trip_id" in modes_sql
    assert "LEFT JOIN canonical.routes AS r ON r.route_id = t.route_id" in modes_sql
    assert modes_params == events_params


# --- the package ----------------------------------------------------------------


@pytest.fixture
def month_rows():
    return [
        # A major event: excluded from S&S-50 counts (S&S-40 territory).
        month_event_row(
            "ev-major", category="collision", fatalities=1, injuries=2,
            classification="major",
            thresholds_met=("fatality", "injury_immediate_transport"),
        ),
        # Rail injury below the rail serious-injury criteria → non-major
        # injury-threshold event.
        month_event_row(
            "ev-inj-rail", mode="rail", category="collision", injuries=1,
            classification="non_major",
        ),
        # Non-major fire (purchased-transportation TOS: its own cell).
        month_event_row(
            "ev-fire", tos="PT", category="fire", classification="non_major",
        ),
        # Assault on a worker, NO injury — still counted (p. 3 quote).
        month_event_row(
            "ev-assault", category="assault", assault_on_worker=True,
            classification="non_major",
        ),
        # Assault on a worker WITH an injury — counts in both groups, but
        # not in without_injury.
        month_event_row(
            "ev-assault-inj", category="assault", assault_on_worker=True,
            injuries=1, classification="non_major",
        ),
        # Not reportable: listed, never counted.
        month_event_row("ev-none", classification="not_reportable"),
        # A superseded original: excluded, its replacement carries the truth.
        month_event_row(
            "ev-old", superseded_by="ev-new", injuries=3,
            classification="non_major",
        ),
        # An unclassified event: surfaced loudly, never counted.
        month_event_row("ev-limbo", classification=None, thresholds_met=None),
    ]


def _package(month_rows, operated=(("bus",), ("ferry",), (None,))):
    conn = RecordingConnection(
        safety_event_rows=month_rows, operated_mode_rows=list(operated)
    )
    return build_ss50_package(conn, "2026-06")


def test_package_counts_per_mode_tos_with_provenance(month_rows):
    package = _package(month_rows)
    cells = {(c["mode"], c["type_of_service"]): c for c in package["cells"]}

    bus_do = cells[("bus", "DO")]["counts"]
    assert bus_do["assaults_on_worker"] == {
        "count": 2,
        "without_injury": 1,
        "event_ids": ["ev-assault", "ev-assault-inj"],
    }
    assert bus_do["injury_events"] == {
        "count": 1,
        "people_injured": 1,
        "event_ids": ["ev-assault-inj"],
    }
    assert bus_do["non_major_fires"]["count"] == 0

    rail_do = cells[("rail", "DO")]["counts"]
    assert rail_do["injury_events"] == {
        "count": 1,
        "people_injured": 1,
        "event_ids": ["ev-inj-rail"],
    }

    bus_pt = cells[("bus", "PT")]["counts"]
    assert bus_pt["non_major_fires"] == {"count": 1, "event_ids": ["ev-fire"]}


def test_package_zero_rows_for_operated_modes_even_if_no_event(month_rows):
    package = _package(month_rows)
    cells = {(c["mode"], c["type_of_service"]): c for c in package["cells"]}
    # ferry operated, no events → explicit zero row ("even if no event
    # occurs"); NULL mode buckets as 'unknown', never dropped.
    assert package["operated_modes"] == ["bus", "ferry", "unknown"]
    for mode in ("ferry", "unknown"):
        zero = cells[(mode, "unknown")]
        assert zero["zero_event"] is True
        assert zero["counts"]["injury_events"]["count"] == 0
        assert zero["counts"]["non_major_fires"]["count"] == 0
        assert zero["counts"]["assaults_on_worker"]["count"] == 0
    # bus had countable events — no spurious zero row for it.
    assert cells[("bus", "DO")]["zero_event"] is False


def test_package_exclusions_are_visible_never_counted(month_rows):
    package = _package(month_rows)
    assert package["excluded"] == {
        "major_event_ids": ["ev-major"],
        "not_reportable_event_ids": ["ev-none"],
        "superseded_event_ids": ["ev-old"],
        "unclassified_event_ids": ["ev-limbo"],
    }
    # The superseded original's 3 injuries are nowhere in the counts.
    all_ids = [
        event_id
        for cell in package["cells"]
        for group in cell["counts"].values()
        for event_id in group["event_ids"]
    ]
    assert "ev-old" not in all_ids and "ev-major" not in all_ids
    caveat_ids = [c["id"] for c in package["caveats"]]
    assert "unclassified_events" in caveat_ids
    assert "superseded_excluded" in caveat_ids


def test_package_header_banner_citations_and_determinism(month_rows):
    package = _package(month_rows)
    assert package["form"] == "S&S-50"
    assert package["reportable"] is False
    assert package["banner"].startswith("NOT REPORTABLE")
    assert package["month"] == "2026-06"
    assert package["due_date"] == "2026-07-31"
    citation_ids = [c["id"] for c in package["citations"]]
    assert citation_ids == ["ss50_scope", "ss50_timing", "cr_ar_nuance"]
    assert any(
        "even if no event occurs" in c["text"] for c in package["citations"]
    )
    caveat_ids = [c["id"] for c in package["caveats"]]
    assert caveat_ids[:3] == [
        "not_reportable_preview", "cr_ar_not_applied", "tos_attribution",
    ]
    # Cells sorted by (mode, tos); JSON-safe throughout.
    keys = [(c["mode"], c["type_of_service"]) for c in package["cells"]]
    assert keys == sorted(keys)
    json.dumps(package)
    # Deterministic: same inputs, same package.
    assert _package(month_rows) == package


def test_package_no_events_no_telemetry_is_all_zero_rows():
    package = _package([], operated=(("bus",),))
    assert [c["zero_event"] for c in package["cells"]] == [True]
    assert package["excluded"]["unclassified_event_ids"] == []


def test_single_injury_other_safety_event_flows_from_classifier_to_ss50():
    """End-to-end over the REAL classifier (sscls_v0 0.1.1 correction): a
    single-injury Other Safety Event classifies non_major (p. 22 — 'are
    reported on the Non-Major Summary Report') and the generator counts it
    as an injury-threshold event, with provenance. Likewise a zero-injury
    assault on a worker (Example 6F: 'reported on the S&S-50 Monthly
    Summary form')."""
    from headway_calc.sscls import SafetyEvent, classify_event

    slip = SafetyEvent(
        event_id="ev-slip",
        occurred_at=JUNE,
        mode="bus",
        event_category="other",
        fatalities=0,
        injuries=1,
        property_damage_usd=None,
        serious_injury=False,
        substantial_damage=False,
        towed=False,
        evacuation_life_safety=False,
        assault_on_worker=False,
        involves_transit_vehicle=True,
        involves_second_rail_vehicle=False,
        grade_crossing=False,
        type_of_service="DO",
    )
    slip_verdict = classify_event(slip)
    assert slip_verdict.classification == "non_major"

    spit = SafetyEvent(
        event_id="ev-spit",
        occurred_at=JUNE,
        mode="bus",
        event_category="assault",
        fatalities=0,
        injuries=0,
        property_damage_usd=None,
        serious_injury=False,
        substantial_damage=False,
        towed=False,
        evacuation_life_safety=False,
        assault_on_worker=True,
        involves_transit_vehicle=False,
        involves_second_rail_vehicle=False,
        grade_crossing=False,
        type_of_service="DO",
    )
    spit_verdict = classify_event(spit)
    assert spit_verdict.classification == "non_major"

    rows = [
        month_event_row(
            "ev-slip", category="other", injuries=1,
            classification=slip_verdict.classification,
        ),
        month_event_row(
            "ev-spit", category="assault", assault_on_worker=True,
            classification=spit_verdict.classification,
        ),
    ]
    package = _package(rows, operated=(("bus",),))
    (cell,) = package["cells"]
    assert cell["counts"]["injury_events"] == {
        "count": 1, "people_injured": 1, "event_ids": ["ev-slip"],
    }
    assert cell["counts"]["assaults_on_worker"] == {
        "count": 1, "without_injury": 1, "event_ids": ["ev-spit"],
    }


# --- S&S-40 detail export --------------------------------------------------------


def single_event_row(
    event_id="ev-major",
    *,
    classification="major",
    thresholds_met=("fatality", "property_damage_25k"),
    superseded_by=None,
):
    """One pre-joined row in _SELECT_ONE_EVENT_SQL column order (27 columns
    since migration 0018 added runaway_train and evacuation_to_rail_row)."""
    return (
        event_id, JUNE, "bus", "DO", "collision",
        "Bus 1207 struck a utility pole.", "Elm St & 3rd Ave",
        1, 2, Decimal("31000.00"), False, False, True, False, False,
        True, False, False, False, False, "stella",
        datetime(2026, 6, 10, 13, 0, tzinfo=UTC), superseded_by,
        classification,
        list(thresholds_met) if thresholds_met is not None else None,
        "sscls_v0 0.1.1",
        datetime(2026, 6, 10, 13, 0, 5, tzinfo=UTC),
    )


def test_ss40_export_thresholds_carry_supporting_fields():
    conn = RecordingConnection(safety_single_event_rows=[single_event_row()])
    export = build_ss40_export(conn, "ev-major")

    assert export["form"] == "S&S-40"
    assert export["reportable"] is False
    # Due date: occurred_at + 30 days (Exhibit 2, p. 4).
    assert export["due"]["due_date"] == "2026-07-10"
    assert "30 days after the date of the event" in export["due"]["citation"]
    assert export["classification"]["classification"] == "major"
    by_threshold = {t["threshold"]: t["supporting_fields"] for t in export["thresholds"]}
    assert by_threshold["fatality"] == {"fatalities": 1}
    # NUMERIC survives as an exact string, never a float.
    assert by_threshold["property_damage_25k"] == {
        "property_damage_usd": "31000.00"
    }
    assert export["event"]["narrative"] == "Bus 1207 struck a utility pole."
    assert export["notes"] == []
    json.dumps(export)


def test_ss40_export_refuses_unknown_event_and_flags_non_major():
    conn = RecordingConnection(safety_single_event_rows=[single_event_row()])
    with pytest.raises(ValueError, match="No safety event"):
        build_ss40_export(conn, "ev-ghost")

    non_major = single_event_row(
        "ev-nm", classification="non_major", thresholds_met=()
    )
    conn = RecordingConnection(safety_single_event_rows=[non_major])
    export = build_ss40_export(conn, "ev-nm")
    assert export["thresholds"] == []
    assert any("NOT an S&S-40 obligation" in n for n in export["notes"])

    limbo = single_event_row("ev-limbo", classification=None, thresholds_met=None)
    conn = RecordingConnection(safety_single_event_rows=[limbo])
    export = build_ss40_export(conn, "ev-limbo")
    assert export["classification"] is None
    assert any("NO classification row" in n for n in export["notes"])


# --- CLI boundary -----------------------------------------------------------------


def test_cli_requires_exactly_one_of_month_or_ss40_event():
    with pytest.raises(SystemExit):
        _parse_ss50_args([])
    with pytest.raises(SystemExit):
        _parse_ss50_args(["--month", "2026-06", "--ss40-event", "ev-1"])
    args = _parse_ss50_args(["--month", "2026-06"])
    assert args.month == "2026-06"
    args = _parse_ss50_args(["--ss40-event", "ev-1"])
    assert args.ss40_event == "ev-1"


def test_cli_refuses_without_database_url(monkeypatch):
    monkeypatch.delenv("HEADWAY_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="HEADWAY_DATABASE_URL"):
        ss50_main(["--month", "2026-06"])
