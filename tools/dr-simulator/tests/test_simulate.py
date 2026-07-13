"""Tests for the demand-response dispatch-day simulator.

No database is involved (the simulator is self-contained); everything is
seeded determinism plus contract-shape checks against
contracts/demand-response-trip.v0.schema.json's field list and rules.
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import simulate  # noqa: E402
from simulate import (  # noqa: E402
    FIELDNAMES,
    OUTPUT_FILENAME,
    generate_trips,
    parse_tos_mix,
    write_csv,
)

from datetime import date  # noqa: E402

SERVICE_DATE = date(2026, 7, 14)
DEFAULT_MIX = parse_tos_mix("DO:3,PT:2,TX:1")


def _gen(seed=42, **kwargs):
    return generate_trips(
        SERVICE_DATE,
        seed=seed,
        tos_mix=kwargs.pop("tos_mix", DEFAULT_MIX),
        trips_per_vehicle=kwargs.pop("trips_per_vehicle", 8),
        **kwargs,
    )


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_deterministic_for_seed():
    assert _gen(seed=7) == _gen(seed=7)
    assert _gen(seed=7) != _gen(seed=8)


def test_rows_are_contract_shaped():
    rows = _gen()
    assert rows, "simulator generated no rows"
    for row in rows:
        assert set(row) == set(FIELDNAMES)
        assert row["mode"] == "DR"
        assert row["tos"] in ("DO", "PT", "TX", "TN")
        assert row["ada_related"] in ("true", "false")
        assert row["sponsored"] in ("true", "false")
        assert row["no_show"] in ("true", "false")
        assert row["interruption_after"] in (
            "none",
            "lunch",
            "fuel",
            "garage_return",
            "dispatch_return",
        )
        assert int(row["riders"]) >= 0
        assert int(row["attendants_companions"]) >= 0
        # Timestamps carry a UTC offset (the contract forbids naive times).
        pickup = _ts(row["pickup_timestamp"])
        dropoff = _ts(row["dropoff_timestamp"])
        assert pickup.tzinfo is not None and dropoff.tzinfo is not None
        assert dropoff >= pickup  # no defects injected in this run
        assert row["service_date"] == SERVICE_DATE.isoformat()
        # sponsored <=> sponsor label present (no defects injected).
        assert (row["sponsored"] == "true") == bool(row["sponsor"])


def test_tos_mix_respected_and_vehicle_counts():
    rows = _gen()
    by_tos = {}
    for row in rows:
        by_tos.setdefault(row["tos"], set()).add(row["vehicle_id"])
    assert len(by_tos["DO"]) == 3
    assert len(by_tos["PT"]) == 2
    assert len(by_tos["TX"]) == 1


def test_dispatch_day_features_present():
    """A default day exercises the features the DR calcs need: no-shows
    (zero boardings), shared rides (overlapping bookings on one vehicle),
    and span-breaking interruptions."""
    rows = _gen(seed=1)

    no_shows = [r for r in rows if r["no_show"] == "true"]
    assert no_shows, "expected at least one no-show"
    assert all(r["riders"] == 0 and r["attendants_companions"] == 0 for r in no_shows)

    interruptions = {r["interruption_after"] for r in rows}
    assert "lunch" in interruptions  # every DO/PT vehicle takes lunch

    # Shared ride: two bookings on one vehicle with overlapping onboard windows.
    by_vehicle = {}
    for row in rows:
        if row["no_show"] == "false":
            by_vehicle.setdefault(row["vehicle_id"], []).append(row)
    overlap_found = False
    for trips in by_vehicle.values():
        trips.sort(key=lambda r: r["pickup_timestamp"])
        for a, b in zip(trips, trips[1:]):
            if _ts(b["pickup_timestamp"]) < _ts(a["dropoff_timestamp"]):
                overlap_found = True
    assert overlap_found, "expected at least one shared ride"


def test_odometer_readings_consistent():
    """Odometer pairs must be usable by dr_vrm: non-negative onboard deltas
    matching onboard_miles, monotone per vehicle in pickup order."""
    rows = [r for r in _gen(seed=3) if r["onboard_miles"] != ""]
    for row in rows:
        pickup_odo = float(row["pickup_odometer_miles"])
        dropoff_odo = float(row["dropoff_odometer_miles"])
        assert dropoff_odo >= pickup_odo
        assert abs((dropoff_odo - pickup_odo) - float(row["onboard_miles"])) < 0.011
    by_vehicle = {}
    for row in rows:
        by_vehicle.setdefault(row["vehicle_id"], []).append(row)
    for trips in by_vehicle.values():
        trips.sort(key=lambda r: r["pickup_timestamp"])
        for a, b in zip(trips, trips[1:]):
            assert float(b["pickup_odometer_miles"]) >= float(a["pickup_odometer_miles"])


def test_defect_injection_missing_distance():
    rows = _gen(missing_distance_share=0.1)
    missing = [
        r
        for r in rows
        if r["no_show"] == "false"
        and r["onboard_miles"] == ""
        and r["pickup_odometer_miles"] == ""
        and r["dropoff_odometer_miles"] == ""
    ]
    assert len(missing) == round(0.1 * len(rows))


def test_defect_injection_negative_duration():
    rows = _gen(negative_duration_share=0.05)
    negative = [
        r for r in rows if _ts(r["dropoff_timestamp"]) < _ts(r["pickup_timestamp"])
    ]
    assert len(negative) == round(0.05 * len(rows))


def test_defect_injection_ada_sponsored_conflict():
    rows = _gen(ada_sponsored_conflict_share=0.05)
    conflicts = [
        r for r in rows if r["ada_related"] == "true" and r["sponsored"] == "true"
    ]
    assert len(conflicts) == round(0.05 * len(rows))
    assert all(r["sponsor"] for r in conflicts)


def test_defect_injection_missing_sponsor():
    rows = _gen(missing_sponsor_share=0.05)
    broken = [r for r in rows if r["sponsored"] == "true" and not r["sponsor"]]
    assert len(broken) == round(0.05 * len(rows))


def test_defect_sets_disjoint():
    rows = _gen(
        seed=5,
        missing_distance_share=0.05,
        negative_duration_share=0.05,
        ada_sponsored_conflict_share=0.05,
        missing_sponsor_share=0.05,
    )
    defect_ids = []
    for r in rows:
        if r["no_show"] == "false" and r["onboard_miles"] == "" and r["pickup_odometer_miles"] == "":
            defect_ids.append(r["dr_trip_id"])
        if _ts(r["dropoff_timestamp"]) < _ts(r["pickup_timestamp"]):
            defect_ids.append(r["dr_trip_id"])
        if r["ada_related"] == "true" and r["sponsored"] == "true":
            defect_ids.append(r["dr_trip_id"])
        if r["sponsored"] == "true" and not r["sponsor"]:
            defect_ids.append(r["dr_trip_id"])
    assert len(defect_ids) == len(set(defect_ids)), "defect sets overlap"


def test_tx_vehicles_have_no_interruption_markers():
    rows = _gen()
    assert all(
        r["interruption_after"] == "none" for r in rows if r["tos"] == "TX"
    )


def test_write_csv_roundtrip(tmp_path):
    rows = _gen(seed=2)
    out = write_csv(rows, tmp_path)
    assert out == tmp_path / OUTPUT_FILENAME
    with out.open(newline="", encoding="utf-8") as f:
        read_back = list(csv.DictReader(f))
    assert len(read_back) == len(rows)
    assert set(read_back[0]) == set(FIELDNAMES)
    # File-drop pattern match: the DR connector scans demand_response_trips*.csv.
    assert out.name.startswith("demand_response_trips")


def test_parse_tos_mix_rejects_bad_input():
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        parse_tos_mix("XX:3")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_tos_mix("DO:zero")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_tos_mix("DO:0")


def test_cli_run_prints_simulated_reminder(tmp_path, capsys):
    args = simulate.parse_args(
        [
            "--service-date",
            SERVICE_DATE.isoformat(),
            "--seed",
            "42",
            "--out",
            str(tmp_path),
        ]
    )
    simulate.run(args)
    out = capsys.readouterr().out
    assert "SIMULATED data" in out
    assert "dr_simulated" in out


def test_every_row_carries_the_structural_sim_marker():
    """Every dr_trip_id is 'sim:'-prefixed — the STRUCTURAL simulated-data
    marker (2026-07-13 hardening pass): the DR connector hard-refuses
    sim-marked rows arriving under a non-simulated source label (Shared
    Constraint 2, full provenance), so this prefix is load-bearing, not
    cosmetic. It must survive every code path, including defect injection.
    """
    rows = _gen(
        seed=11,
        missing_distance_share=0.1,
        negative_duration_share=0.1,
        ada_sponsored_conflict_share=0.1,
        missing_sponsor_share=0.1,
    )
    assert rows
    for row in rows:
        assert row["dr_trip_id"].startswith("sim:"), row["dr_trip_id"]
