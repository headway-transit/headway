"""Trip resolution (handoff 0031): spec validation, the three outcomes, the
refusal path, the service-day boundary, and the per-file summary.

The invariants under test, in the handoff's words:

- resolution is declarative per-agency configuration — a spec that cannot
  load fails loudly with every violation named, and nothing agency-specific
  is hardcoded;
- the three outcomes (resolved / ambiguous / unmatched) are all explicit;
  ambiguity and misses become DQ findings that never guess;
- the vendor's original trip identifier is PRESERVED alongside any resolved
  canonical id, never overwritten;
- an unconfirmed direction convention REFUSES (one finding per file, zero
  resolutions) rather than assuming 0/1.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from headway_transform.adapters.engine import run_adapter
from headway_transform.adapters.resolution import (
    AMBIGUOUS,
    RESOLVED,
    UNMATCHED,
    ResolutionSpecError,
    TripResolver,
    load_resolution_spec,
)
from headway_transform.adapters.spec import load_spec
from headway_transform.gtfs_static import (
    CanonicalServiceCalendar,
    CanonicalServiceCalendarDate,
)
from headway_transform.schedule_index import ScheduleIndex, ScheduledTrip

REPO_ROOT = Path(__file__).resolve().parents[3]
TRIPSPARK_DIR = REPO_ROOT / "adapters" / "tripspark" / "streets"

RECORD_ID = "ef" * 32
SOURCE = "tripspark_streets"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _confirmed_resolution_doc(**overrides) -> dict:
    """A CONFIRMED variant of the tripspark resolution config (tests only —
    the committed spec is deliberately unconfirmed until the agency signs
    off on the direction convention)."""
    doc = {
        "resolution_spec_version": 0,
        "source_label": SOURCE,
        "target_contract": "tides_passenger_events",
        "trip": {
            "vendor_identifier": {"from_field": "trip_id_performed"},
            "parse": {
                "separator": " - ",
                "components": ["route", "pattern", "start_time"],
            },
            "match": {
                "route": {"component": "route", "gtfs_field": "route_short_name"},
                "start_time": {"component": "start_time", "format": "%H:%M"},
                "direction": {
                    "from_column": "DirectionKey",
                    "confirmed": True,
                    "values": {"1": 1, "2": 0},
                    "confirmed_by": "test fixture (invented agency)",
                    "confirmed_on": "2026-07-29",
                },
                "service": {
                    "from_field": "service_date",
                    "service_day_rollover": "not_confirmed",
                },
            },
        },
        "stop": {
            "from_column": "StopCode",
            "match_order": ["stop_code", "stop_id"],
        },
        "provenance": {
            "verified_against": {
                "schedule_feed": {
                    "retrieved": "2026-07-29",
                    "trips": 4,
                    "key_uniqueness": "synthetic four-trip schedule for tests",
                },
                "vendor_export": {
                    "status": "none_available",
                    "note": "synthetic rows in the proven 18-column shape",
                },
            },
            "verification_date": "2026-07-29",
        },
    }
    for key, value in overrides.items():
        doc[key] = value
    return doc


def _write_spec(tmp_path: Path, doc: dict) -> Path:
    path = tmp_path / "resolution.v0.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def mapping_spec():
    return load_spec(TRIPSPARK_DIR / "mapping.v0.yaml")


#: 2026-07-02 is a Thursday; WK runs every day of that range.
WK = CanonicalServiceCalendar(
    service_id="WK",
    monday=True, tuesday=True, wednesday=True, thursday=True, friday=True,
    saturday=False, sunday=False,
    start_date=date(2026, 6, 1),
    end_date=date(2026, 12, 31),
)
SAT = CanonicalServiceCalendar(
    service_id="SAT",
    monday=False, tuesday=False, wednesday=False, thursday=False,
    friday=False, saturday=True, sunday=False,
    start_date=date(2026, 6, 1),
    end_date=date(2026, 12, 31),
)


def _index(**kwargs) -> ScheduleIndex:
    """A synthetic schedule shaped like the fixture's vocabulary.

    Route 12: ONE trip starting 21:30 direction 1 → resolves.
    Route 48: TWO trips starting 21:15 direction 0 → ambiguous by design.
    Route 7:  one AFTER-MIDNIGHT trip (25:10 on the previous service day).
    """
    trips = kwargs.pop(
        "trips",
        [
            ScheduledTrip("GTFS-12-2130", "R12", "12", "WK", 1, 21 * 3600 + 30 * 60),
            ScheduledTrip("GTFS-48-2115-a", "R48", "48", "WK", 0, 21 * 3600 + 15 * 60),
            ScheduledTrip("GTFS-48-2115-b", "R48", "48", "WK", 0, 21 * 3600 + 15 * 60),
            ScheduledTrip("GTFS-7-2510", "R7", "7", "WK", 1, 25 * 3600 + 10 * 60),
        ],
    )
    return ScheduleIndex.build(
        trips,
        kwargs.pop("calendars", [WK, SAT]),
        kwargs.pop("calendar_dates", []),
        kwargs.pop(
            "stops_by",
            {
                "stop_code": {"QT042": ("S-42",), "QT051": ("S-51",),
                              "QT066": ("S-66",), "QT070": ("S-70",)},
                "stop_id": {"S-42": ("S-42",)},
            },
        ),
    )


def _visit_row(
    key: str,
    trip_name: str,
    direction: str,
    *,
    board: str = "1",
    alight: str = "0",
    stop_code: str = "QT042",
    timestamp: str = "2026-07-02T21:33:10",
) -> str:
    """One synthetic 18-column stop-visit row in the proven fixture shape."""
    return (
        f"{key},7301,4,{board},{alight},{alight},1,0,0,{trip_name},"
        f"Line X,X,X Pattern,Some Stop,{stop_code},105,{direction},{timestamp}"
    )


# ---------------------------------------------------------------------------
# Spec validation
# ---------------------------------------------------------------------------

def test_committed_tripspark_resolution_spec_carries_confirmed_direction(mapping_spec):
    # The agency confirmed the DirectionKey -> direction_id mapping on
    # 2026-07-31 (derived from its own APC export + published GTFS, 27,907
    # records, zero disagreement), so the committed spec now RESOLVES rather
    # than refusing. This pins the accepted mapping so it can't drift.
    spec = load_resolution_spec(
        TRIPSPARK_DIR / "resolution.v0.yaml", mapping_spec
    )
    assert spec.source_label == SOURCE
    assert spec.direction.confirmed is True
    assert spec.direction.unconfirmed_reason is None
    # North/West/Outbound/Clockwise -> 0; South/East/Inbound -> 1;
    # Counter-clockwise (8) unobserved and deliberately unmapped.
    assert spec.direction.values == {
        "1": 0, "2": 1, "3": 1, "4": 0, "5": 1, "6": 0, "7": 0,
    }
    assert "8" not in spec.direction.values
    assert spec.direction.confirmed_by
    assert spec.direction.confirmed_on == "2026-07-31"
    assert spec.service_day_rollover == "not_confirmed"
    assert spec.stop_match_order == ("stop_code", "stop_id")
    # The config never hardcodes the observed stop_id == stop_code
    # coincidence: both fields are declared, in order.


def test_confirmed_spec_requires_values_and_attribution(tmp_path, mapping_spec):
    doc = _confirmed_resolution_doc()
    del doc["trip"]["match"]["direction"]["confirmed_by"]
    with pytest.raises(ResolutionSpecError, match="confirmed_by"):
        load_resolution_spec(_write_spec(tmp_path, doc), mapping_spec)


def test_unconfirmed_spec_requires_a_reason(tmp_path, mapping_spec):
    doc = _confirmed_resolution_doc()
    direction = doc["trip"]["match"]["direction"]
    direction["confirmed"] = False
    del direction["values"], direction["confirmed_by"], direction["confirmed_on"]
    with pytest.raises(ResolutionSpecError, match="unconfirmed_reason"):
        load_resolution_spec(_write_spec(tmp_path, doc), mapping_spec)


def test_label_mismatch_is_refused(tmp_path, mapping_spec):
    doc = _confirmed_resolution_doc(source_label="someone_else")
    with pytest.raises(ResolutionSpecError, match="does not match"):
        load_resolution_spec(_write_spec(tmp_path, doc), mapping_spec)


def test_unmapped_field_reference_is_refused(tmp_path, mapping_spec):
    doc = _confirmed_resolution_doc()
    doc["trip"]["vendor_identifier"] = {"from_field": "no_such_field"}
    with pytest.raises(ResolutionSpecError, match="no_such_field"):
        load_resolution_spec(_write_spec(tmp_path, doc), mapping_spec)


def test_undeclared_column_reference_is_refused(tmp_path, mapping_spec):
    doc = _confirmed_resolution_doc()
    doc["trip"]["match"]["direction"]["from_column"] = "NoSuchColumn"
    with pytest.raises(ResolutionSpecError, match="NoSuchColumn"):
        load_resolution_spec(_write_spec(tmp_path, doc), mapping_spec)


def test_match_component_must_come_from_parse(tmp_path, mapping_spec):
    doc = _confirmed_resolution_doc()
    doc["trip"]["match"]["route"]["component"] = "banana"
    with pytest.raises(ResolutionSpecError, match="banana"):
        load_resolution_spec(_write_spec(tmp_path, doc), mapping_spec)


# ---------------------------------------------------------------------------
# Service-day arithmetic (the GTFS calendar rules, applied at read time)
# ---------------------------------------------------------------------------

def test_active_services_weekday_flags_and_inclusive_bounds():
    index = _index()
    assert index.active_services(date(2026, 7, 2)) == {"WK"}  # Thursday
    assert index.active_services(date(2026, 7, 4)) == {"SAT"}  # Saturday
    # Inclusive bounds: both endpoints count (GTFS: end_date "is included").
    assert index.active_services(date(2026, 6, 1)) == {"WK"}  # Mon, start
    assert index.active_services(date(2026, 12, 31)) == {"WK"}  # Thu, end
    assert index.active_services(date(2027, 1, 1)) == frozenset()


def test_calendar_dates_exceptions_win():
    index = _index(
        calendar_dates=[
            CanonicalServiceCalendarDate("WK", date(2026, 7, 2), 2),  # removed
            CanonicalServiceCalendarDate("SAT", date(2026, 7, 2), 1),  # added
        ]
    )
    assert index.active_services(date(2026, 7, 2)) == {"SAT"}


# ---------------------------------------------------------------------------
# The three outcomes, through the engine (fixture-shaped synthetic rows)
# ---------------------------------------------------------------------------

def _run(mapping_spec, resolver, rows: list[str]):
    csv_bytes = ("﻿" + "\n".join(rows) + "\n").encode("utf-8")
    return run_adapter(mapping_spec, csv_bytes, RECORD_ID, SOURCE, resolver)


def _resolver(tmp_path, mapping_spec, index=None, **doc_overrides):
    doc = _confirmed_resolution_doc()
    for dotted, value in doc_overrides.items():
        node = doc
        *parents, leaf = dotted.split(".")
        for key in parents:
            node = node[key]
        node[leaf] = value
    spec = load_resolution_spec(_write_spec(tmp_path, doc), mapping_spec)
    return TripResolver(spec, index if index is not None else _index())


def test_resolved_replaces_trip_id_and_preserves_vendor_ref(
    tmp_path, mapping_spec
):
    resolver = _resolver(tmp_path, mapping_spec)
    result = _run(
        mapping_spec,
        resolver,
        [_visit_row("900001", "12 - 12WD - 21:30", "1", board="2", alight="1")],
    )
    assert result.mapped_count == 1
    assert result.resolution_counts() == {RESOLVED: 1}
    # Both fan-out events (board + alight) carry the SAME resolution.
    assert len(result.passenger_events) == 2
    for event in result.passenger_events:
        assert event.trip_id == "GTFS-12-2130"
        # NON-NEGOTIABLE: the vendor's identifier is preserved verbatim.
        assert event.vendor_trip_ref == "12 - 12WD - 21:30"
        assert event.trip_resolution == RESOLVED
    # …while the CONTRACT record still carries what the vendor stated.
    assert all(
        r["trip_id_performed"] == "12 - 12WD - 21:30" for r in result.records
    )
    # Lineage: normalizer edge + adapter edge + resolution edge per row.
    resolution_edges = [
        e for e in result.edges if e.transform_name == f"resolve_trips:{SOURCE}"
    ]
    assert len(resolution_edges) == 2
    for edge in resolution_edges:
        assert edge.input_kind == "canonical.trips"
        assert edge.input_id == "GTFS-12-2130"
        assert edge.transform_version == resolver.spec.spec_sha12
    # No ambiguity/unmatched findings; the summary states 1 of 1.
    summary = [
        f for f in result.findings if f.issue_type == "trip_resolution_summary"
    ]
    assert len(summary) == 1
    assert "1 of 1" in summary[0].title


def test_ambiguous_never_picks_and_names_the_candidates(tmp_path, mapping_spec):
    resolver = _resolver(tmp_path, mapping_spec)
    result = _run(
        mapping_spec,
        resolver,
        [_visit_row("900002", "48 - 48ND - 21:15", "2")],
    )
    assert result.resolution_counts() == {AMBIGUOUS: 1}
    [event] = result.passenger_events
    # NOT resolved: trip_id keeps the vendor's value; outcome recorded.
    assert event.trip_id == "48 - 48ND - 21:15"
    assert event.vendor_trip_ref == "48 - 48ND - 21:15"
    assert event.trip_resolution == AMBIGUOUS
    [finding] = [
        f for f in result.findings
        if f.issue_type == "trip_resolution_ambiguous"
    ]
    assert "GTFS-48-2115-a" in finding.description
    assert "GTFS-48-2115-b" in finding.description
    assert "did not pick" in finding.description
    # No resolution lineage edge for an unresolved row.
    assert not any(e.input_kind == "canonical.trips" for e in result.edges)


def test_unmatched_states_the_parse_and_the_search(tmp_path, mapping_spec):
    resolver = _resolver(tmp_path, mapping_spec)
    result = _run(
        mapping_spec,
        resolver,
        [_visit_row("900003", "99 - 99XX - 05:00", "1")],
    )
    assert result.resolution_counts() == {UNMATCHED: 1}
    [event] = result.passenger_events
    assert event.trip_id == "99 - 99XX - 05:00"
    assert event.trip_resolution == UNMATCHED
    [finding] = [
        f for f in result.findings
        if f.issue_type == "trip_resolution_unmatched"
    ]
    # The finding leads with the agency's vocabulary and shows the parse.
    assert "route 99" in finding.description
    assert "05:00" in finding.description
    assert "2026-07-02" in finding.description


def test_unmapped_direction_value_is_unmatched_not_guessed(
    tmp_path, mapping_spec
):
    resolver = _resolver(tmp_path, mapping_spec)
    result = _run(
        mapping_spec,
        resolver,
        [_visit_row("900004", "12 - 12WD - 21:30", "9")],
    )
    assert result.resolution_counts() == {UNMATCHED: 1}
    [finding] = [
        f for f in result.findings
        if f.issue_type == "trip_resolution_unmatched"
    ]
    assert "never guessed" in finding.description
    assert "'9'" in finding.description


def test_no_service_that_day_is_unmatched_with_the_day_named(
    tmp_path, mapping_spec
):
    resolver = _resolver(tmp_path, mapping_spec)
    # Sunday 2026-07-05: neither WK nor SAT runs.
    result = _run(
        mapping_spec,
        resolver,
        [
            _visit_row(
                "900005", "12 - 12WD - 21:30", "1",
                timestamp="2026-07-05T21:33:10",
            )
        ],
    )
    assert result.resolution_counts() == {UNMATCHED: 1}
    [finding] = [
        f for f in result.findings
        if f.issue_type == "trip_resolution_unmatched"
    ]
    assert "no service at all running on 2026-07-05" in finding.description


def test_unconfirmed_rollover_probes_but_does_not_use_the_next_day(
    tmp_path, mapping_spec
):
    """An after-midnight trip (GTFS 25:10 on Wednesday) shows up in the
    export at 01:10 Thursday. With rollover NOT confirmed the resolver must
    not use the previous-day reading — but the finding names it, so a human
    sees exactly what would have matched."""
    resolver = _resolver(tmp_path, mapping_spec)
    result = _run(
        mapping_spec,
        resolver,
        [
            _visit_row(
                "900006", "7 - 7NT - 01:10", "1",
                timestamp="2026-07-02T01:12:00",
            )
        ],
    )
    assert result.resolution_counts() == {UNMATCHED: 1}
    [finding] = [
        f for f in result.findings
        if f.issue_type == "trip_resolution_unmatched"
    ]
    assert "WOULD match" in finding.description
    assert "not confirmed" in finding.description


def test_confirmed_calendar_date_rollover_resolves_after_midnight(
    tmp_path, mapping_spec
):
    resolver = _resolver(
        tmp_path,
        mapping_spec,
        **{"trip.match.service.service_day_rollover": "calendar_date"},
    )
    result = _run(
        mapping_spec,
        resolver,
        [
            _visit_row(
                "900007", "7 - 7NT - 01:10", "1",
                timestamp="2026-07-02T01:12:00",
            )
        ],
    )
    assert result.resolution_counts() == {RESOLVED: 1}
    [event] = result.passenger_events
    assert event.trip_id == "GTFS-7-2510"
    assert event.vendor_trip_ref == "7 - 7NT - 01:10"


def test_refusal_when_direction_unconfirmed_resolves_nothing(
    tmp_path, mapping_spec
):
    direction_overrides = {
        "trip.match.direction.confirmed": False,
        "trip.match.direction.unconfirmed_reason": (
            "the agency has not yet confirmed the DirectionKey convention"
        ),
    }
    doc = _confirmed_resolution_doc()
    direction = doc["trip"]["match"]["direction"]
    direction["confirmed"] = False
    direction["unconfirmed_reason"] = direction_overrides[
        "trip.match.direction.unconfirmed_reason"
    ]
    del direction["values"], direction["confirmed_by"], direction["confirmed_on"]
    spec = load_resolution_spec(_write_spec(tmp_path, doc), mapping_spec)
    resolver = TripResolver(spec, _index())

    result = _run(
        mapping_spec,
        resolver,
        [_visit_row("900008", "12 - 12WD - 21:30", "1")],
    )
    # Mapped exactly as without a resolver — nothing resolved, no guess.
    assert result.mapped_count == 1
    assert result.trip_outcomes == []
    [event] = result.passenger_events
    assert event.trip_id == "12 - 12WD - 21:30"
    assert event.vendor_trip_ref is None
    assert event.trip_resolution is None
    refusals = [
        f for f in result.findings
        if f.issue_type == "trip_resolution_not_confirmed"
    ]
    assert len(refusals) == 1  # once per file, not per row
    assert "wrong trips" in refusals[0].description


def test_per_file_summary_counts_all_three_outcomes(tmp_path, mapping_spec):
    resolver = _resolver(tmp_path, mapping_spec)
    result = _run(
        mapping_spec,
        resolver,
        [
            _visit_row("900010", "12 - 12WD - 21:30", "1"),
            _visit_row("900011", "48 - 48ND - 21:15", "2"),
            _visit_row("900012", "99 - 99XX - 05:00", "1"),
        ],
    )
    assert result.resolution_counts() == {
        RESOLVED: 1, AMBIGUOUS: 1, UNMATCHED: 1
    }
    [summary] = [
        f for f in result.findings if f.issue_type == "trip_resolution_summary"
    ]
    assert "1 of 3" in summary.title
    assert "1 matched more than one" in summary.description
    assert "1 matched none" in summary.description


def test_unknown_stop_code_is_a_finding_not_a_silence(tmp_path, mapping_spec):
    resolver = _resolver(tmp_path, mapping_spec)
    result = _run(
        mapping_spec,
        resolver,
        [
            _visit_row("900020", "12 - 12WD - 21:30", "1", stop_code="ZZ999"),
        ],
    )
    # The row still lands (nothing dropped) …
    assert result.mapped_count == 1
    # … and the unknown stop is reported, with the declared match order.
    [finding] = [
        f for f in result.findings
        if f.issue_type == "stop_resolution_unmatched"
    ]
    assert "ZZ999" in finding.description
    assert "stop_code then stop_id" in finding.description


def test_stop_fallback_to_stop_id_is_declared_not_assumed(
    tmp_path, mapping_spec
):
    """A code absent from stop_code but present as a stop_id matches via the
    DECLARED fallback — second in match_order, not a hardcoded coincidence."""
    resolver = _resolver(tmp_path, mapping_spec)
    result = _run(
        mapping_spec,
        resolver,
        [_visit_row("900021", "12 - 12WD - 21:30", "1", stop_code="S-42")],
    )
    assert not any(
        f.issue_type == "stop_resolution_unmatched" for f in result.findings
    )
    [outcome] = result.stop_outcomes
    assert outcome.matched and outcome.matched_on == "stop_id"


def test_no_calendar_at_all_is_unmatched_with_the_reason(
    tmp_path, mapping_spec
):
    index = _index(calendars=[], calendar_dates=[])
    resolver = _resolver(tmp_path, mapping_spec, index=index)
    result = _run(
        mapping_spec,
        resolver,
        [_visit_row("900030", "12 - 12WD - 21:30", "1")],
    )
    assert result.resolution_counts() == {UNMATCHED: 1}
    [finding] = [
        f for f in result.findings
        if f.issue_type == "trip_resolution_unmatched"
    ]
    assert "no service days at all" in finding.description
