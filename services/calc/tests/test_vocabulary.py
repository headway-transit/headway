"""Gap findings name the vehicle and route (handoff 0032).

The UAT sentence under test: a telemetry-gap warning must show WHAT VEHICLE
AND ROUTE it concerns, in the order a dispatcher scans — route, vehicle,
when — e.g. "Route 42, vehicle 5335: 12-minute telemetry silence
(22:41–22:53 Jul 28)". And it must fall back HONESTLY when a part is
unknown: a shortened opaque id when the feed broadcast no fleet label, no
route at all when the trip is unresolvable. No label is ever invented.

Covers the _vocabulary helpers, the rewritten titles of every gap-family
finding (0.2.0 group exclusion, 0.3.0 block exclusion, 0.4.0 trip excision,
both layover paths, block_unavailable), the vehicle reference on the
subject, and its frozen form in the stored subject context. No math is
touched: the values these findings ride on are pinned by the untouched
goldens.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from conftest import RecordingConnection

from headway_calc._blocks import (
    apply_block_gap_policy,
    apply_trip_excision_policy,
    block_group_seconds,
    group_block_positions,
)
from headway_calc._grouping import apply_gap_exclusion_policy, group_in_trip_positions
from headway_calc._vocabulary import (
    day_phrase,
    duration_phrase,
    short_id,
    subject_phrase,
    vehicle_handle,
    window_phrase,
)
from headway_calc.dq import route_findings
from headway_calc.subjects import resolve_contexts
from headway_calc.types import Finding, SubjectRef, VehicleRef, VehiclePosition

UTC = timezone.utc
T0 = datetime(2026, 7, 28, 22, 41, 0, tzinfo=UTC)

#: The agency's live shape: opaque UUID vehicle ids, fleet-number labels.
UUID_VEHICLE = "07b5efcb-8d21-4c3e-9f10-3a52aa77c001"
UUID_TRIP = "f3a4a888-1c2d-4e5f-8a9b-0c1d2e3f4a5b"


def pos(
    t: datetime,
    *,
    vehicle_id: str = UUID_VEHICLE,
    trip_id: str | None = UUID_TRIP,
    rec: str = "rec-0",
    block_id: str | None = None,
    vehicle_label: str | None = None,
    route_short_name: str | None = None,
) -> VehiclePosition:
    return VehiclePosition(
        time=t,
        vehicle_id=vehicle_id,
        trip_id=trip_id,
        latitude=42.35,
        longitude=-71.06,
        source_record_id=rec,
        block_id=block_id,
        vehicle_label=vehicle_label,
        route_short_name=route_short_name,
    )


def gapped_trip(
    *,
    gap_seconds: float = 731.0,
    vehicle_label: str | None = "5335",
    route_short_name: str | None = "42",
    trip_id: str = UUID_TRIP,
    vehicle_id: str = UUID_VEHICLE,
    block_id: str | None = None,
) -> list[VehiclePosition]:
    """Two positions bounding one within-trip gap of ``gap_seconds``."""
    return [
        pos(
            T0,
            rec="rec-a",
            trip_id=trip_id,
            vehicle_id=vehicle_id,
            block_id=block_id,
            vehicle_label=vehicle_label,
            route_short_name=route_short_name,
        ),
        pos(
            T0 + timedelta(seconds=gap_seconds),
            rec="rec-b",
            trip_id=trip_id,
            vehicle_id=vehicle_id,
            block_id=block_id,
            vehicle_label=vehicle_label,
            route_short_name=route_short_name,
        ),
    ]


# --- the helpers, each honest about absence ---------------------------------


def test_short_id_keeps_fleet_style_ids_whole_and_folds_uuids():
    assert short_id("y1747") == "y1747"
    assert short_id("G-10099") == "G-10099"
    assert short_id(UUID_VEHICLE) == "07b5efcb…"


def test_vehicle_handle_prefers_the_label_and_never_invents_one():
    assert vehicle_handle(UUID_VEHICLE, "5335") == "vehicle 5335"
    assert vehicle_handle(UUID_VEHICLE, None) == "vehicle 07b5efcb…"


def test_subject_phrase_orders_route_then_vehicle_the_dispatchers_scan():
    assert subject_phrase(("42",), UUID_VEHICLE, "5335") == "Route 42, vehicle 5335"
    assert (
        subject_phrase(("42", "57"), UUID_VEHICLE, "5335")
        == "Routes 42, 57, vehicle 5335"
    )
    # No route known: the vehicle leads, capitalized — no placeholder route.
    assert subject_phrase((), UUID_VEHICLE, "5335") == "Vehicle 5335"
    assert subject_phrase((), UUID_VEHICLE, None) == "Vehicle 07b5efcb…"


def test_subject_phrase_states_a_route_overflow_never_drops_it_silently():
    routes = ("1", "42", "57", "66", "9")
    assert (
        subject_phrase(routes, "veh-1", "5335")
        == "Routes 1, 42, 57 and 2 more, vehicle 5335"
    )


def test_durations_read_in_minutes_at_two_minutes_and_up():
    """A dispatcher reads '12-minute', not '731s' — the exact seconds stay
    in the description, which is why the title may round."""
    assert duration_phrase(731) == "12-minute"
    assert duration_phrase(120) == "2-minute"
    assert duration_phrase(3900) == "65-minute"
    # Below two minutes, whole seconds — '1-minute' would hide the size.
    assert duration_phrase(119) == "119-second"
    assert duration_phrase(90) == "90-second"


def test_windows_state_utc_times_with_the_date():
    assert (
        window_phrase(T0, T0 + timedelta(minutes=12)) == "22:41–22:53 Jul 28"
    )
    # Crossing midnight, BOTH sides keep their date.
    assert (
        window_phrase(T0 + timedelta(minutes=77), T0 + timedelta(minutes=92))
        == "23:58 Jul 28–00:13 Jul 29"
    )
    assert day_phrase(date(2026, 7, 28)) == "Jul 28"
    assert day_phrase(T0) == "Jul 28"


# --- the UAT title itself: 0.2.0 group exclusion ----------------------------


def test_the_gap_title_reads_route_vehicle_when():
    """The exact shape the handoff binds: 'Route 42, vehicle 5335:
    12-minute telemetry silence (22:41–22:53 Jul 28)'."""
    groups = group_in_trip_positions(gapped_trip())
    outcome = apply_gap_exclusion_policy(groups, 300.0, Decimal("0"))
    (warning,) = outcome.warnings
    assert warning.title == (
        "Route 42, vehicle 5335: 12-minute telemetry silence "
        "(22:41–22:53 Jul 28)"
    )
    # The exact seconds and the full ids remain in the description — the
    # provenance is the footnote, not the headline.
    assert "731s" in warning.description
    assert UUID_TRIP in warning.description
    # The vehicle rides the subject, label and all.
    assert warning.subject.vehicle == VehicleRef(UUID_VEHICLE, "5335")
    assert warning.subject.ids == (UUID_TRIP,)


def test_without_a_label_the_title_falls_back_to_the_shortened_id():
    groups = group_in_trip_positions(gapped_trip(vehicle_label=None))
    outcome = apply_gap_exclusion_policy(groups, 300.0, Decimal("0"))
    (warning,) = outcome.warnings
    assert warning.title.startswith("Route 42, vehicle 07b5efcb…:")
    # The FULL id is never lost: description and subject carry it.
    assert warning.subject.vehicle == VehicleRef(UUID_VEHICLE, None)


def test_without_a_route_the_title_omits_the_route_entirely():
    groups = group_in_trip_positions(
        gapped_trip(vehicle_label=None, route_short_name=None)
    )
    outcome = apply_gap_exclusion_policy(groups, 300.0, Decimal("0"))
    (warning,) = outcome.warnings
    assert warning.title.startswith("Vehicle 07b5efcb…:")
    assert "Route" not in warning.title
    assert "None" not in warning.title


def test_a_label_arriving_mid_period_is_used_deterministically():
    """The latest broadcast label wins — the case where migration 0037 lands
    mid-period and labels start flowing."""
    rows = gapped_trip(vehicle_label=None)
    labeled = pos(
        T0 + timedelta(seconds=800),
        rec="rec-c",
        vehicle_label="5335",
        route_short_name="42",
    )
    groups = group_in_trip_positions(rows + [labeled])
    outcome = apply_gap_exclusion_policy(groups, 300.0, Decimal("0"))
    (warning,) = outcome.warnings
    assert warning.title.startswith("Route 42, vehicle 5335:")


# --- 0.3.0 / 0.4.0 block paths ----------------------------------------------


def test_the_block_exclusion_title_names_every_route_the_block_ran():
    rows = gapped_trip(block_id="B1") + [
        pos(
            T0 + timedelta(seconds=800),
            rec="rec-c",
            trip_id="trip-2",
            block_id="B1",
            vehicle_label="5335",
            route_short_name="57",
        ),
        pos(
            T0 + timedelta(seconds=860),
            rec="rec-d",
            trip_id="trip-2",
            block_id="B1",
            vehicle_label="5335",
            route_short_name="57",
        ),
    ]
    groups = group_block_positions(rows)
    outcome = apply_block_gap_policy(groups, 300.0, Decimal("0"), 1800.0)
    (warning,) = outcome.warnings
    assert warning.title == (
        "Routes 42, 57, vehicle 5335: 12-minute telemetry silence "
        "(22:41–22:53 Jul 28)"
    )
    assert warning.subject.vehicle == VehicleRef(UUID_VEHICLE, "5335")


def test_the_trip_excision_title_reads_the_same_vocabulary():
    groups = group_block_positions(gapped_trip(block_id="B1"))
    outcome = apply_trip_excision_policy(groups, 300.0, Decimal("0"), 1800.0)
    (warning,) = outcome.warnings
    assert warning.title == (
        "Route 42, vehicle 5335: 12-minute telemetry silence "
        "(22:41–22:53 Jul 28)"
    )
    # Trip and block ids stay in the description.
    assert UUID_TRIP in warning.description
    assert warning.subject.vehicle == VehicleRef(UUID_VEHICLE, "5335")


def test_the_layover_title_reads_route_vehicle_when():
    rows = [
        pos(T0, rec="rec-a", vehicle_label="5335", route_short_name="42",
            block_id="B1"),
        pos(T0 + timedelta(seconds=60), rec="rec-b", vehicle_label="5335",
            route_short_name="42", block_id="B1"),
        pos(T0 + timedelta(seconds=60 + 2000), rec="rec-c", trip_id="trip-2",
            vehicle_label="5335", route_short_name="42", block_id="B1"),
        pos(T0 + timedelta(seconds=120 + 2000), rec="rec-d", trip_id="trip-2",
            vehicle_label="5335", route_short_name="42", block_id="B1"),
    ]
    (group,) = group_block_positions(rows)
    _, findings = block_group_seconds(group, 1800.0)
    (finding,) = findings
    assert finding.issue_type == "layover_exceeds_max"
    assert finding.title == (
        "Route 42, vehicle 5335: 33-minute layover not counted "
        "(22:42–23:15 Jul 28)"
    )
    assert "2000s" in finding.description
    assert finding.subject.vehicle == VehicleRef(UUID_VEHICLE, "5335")


def test_the_block_unavailable_title_reads_route_vehicle_when():
    groups = group_block_positions(
        [
            pos(T0, rec="rec-a", vehicle_label="5335", route_short_name="42"),
            pos(T0 + timedelta(seconds=60), rec="rec-b", vehicle_label="5335",
                route_short_name="42"),
        ]
    )
    outcome = apply_block_gap_policy(groups, 300.0, Decimal("0"), 1800.0)
    (info,) = outcome.infos
    assert info.title == (
        "Route 42, vehicle 5335: no block in the schedule on Jul 28 "
        "(1 trip(s) counted per-trip)"
    )
    assert info.subject.vehicle == VehicleRef(UUID_VEHICLE, "5335")


# --- the vehicle reference, frozen into the stored context ------------------


def test_the_stored_context_carries_the_vehicle_id_and_label():
    conn = RecordingConnection(trip_label_rows=[])
    finding = Finding(
        issue_type="telemetry_gap_excluded",
        title="t",
        description="d",
        severity="warning",
        subject=SubjectRef(
            kind="canonical.trips",
            ids=(UUID_TRIP,),
            vehicle=VehicleRef(UUID_VEHICLE, "5335"),
        ),
    )
    (context,) = resolve_contexts(conn, [finding])
    assert context["vehicle"] == {"vehicle_id": UUID_VEHICLE, "label": "5335"}


def test_an_unlabeled_vehicle_stores_a_null_label_never_a_guess():
    conn = RecordingConnection(trip_label_rows=[])
    finding = Finding(
        issue_type="telemetry_gap_excluded",
        title="t",
        description="d",
        severity="warning",
        subject=SubjectRef(
            kind="canonical.trips",
            ids=(UUID_TRIP,),
            vehicle=VehicleRef(UUID_VEHICLE, None),
        ),
    )
    (context,) = resolve_contexts(conn, [finding])
    assert context["vehicle"] == {"vehicle_id": UUID_VEHICLE, "label": None}


def test_a_subject_without_a_vehicle_stores_no_vehicle_key_at_all():
    """Additive under CONTEXT_VERSION 1: a context without a vehicle renders
    exactly as every pre-0032 context does."""
    conn = RecordingConnection(trip_label_rows=[])
    finding = Finding(
        issue_type="apc_missing_trips_above_fta_threshold",
        title="t",
        description="d",
        severity="blocking",
        subject=SubjectRef(kind="canonical.trips", ids=(UUID_TRIP,)),
    )
    (context,) = resolve_contexts(conn, [finding])
    assert "vehicle" not in context


def test_route_findings_freezes_the_vehicle_on_the_dq_row():
    conn = RecordingConnection(trip_label_rows=[])
    finding = Finding(
        issue_type="telemetry_gap_excluded",
        title="t",
        description="d",
        severity="warning",
        subject=SubjectRef(
            kind="canonical.trips",
            ids=(UUID_TRIP,),
            vehicle=VehicleRef(UUID_VEHICLE, "5335"),
        ),
    )
    route_findings(
        conn, [finding], "vrh_v0", "0.4.0", date(2026, 7, 1), date(2026, 8, 1)
    )
    (sql, params) = conn.statements_matching("INSERT INTO dq.issues")[0]
    assert "subject_context" in sql
    stored = json.loads(params[7])
    assert stored["vehicle"] == {"vehicle_id": UUID_VEHICLE, "label": "5335"}
    # The trip ids remain alongside — any reader can re-derive.
    assert stored["unmatched"]["trip_ids"] == [UUID_TRIP]
