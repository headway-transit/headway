#!/usr/bin/env python3
"""Demand-response dispatch-day simulator (handoff 0013, DR module v0).

Generates SIMULATED, contract-valid ``demand_response_trips.csv`` files
(wire contract: ``contracts/demand-response-trip.v0.schema.json`` +
``contracts/demand-response-trip.v0.md``): multi-vehicle dispatch days with
shared rides (overlapping bookings on one vehicle), no-shows, lunch/fuel
interruptions, garage/dispatching-point returns, ADA-related and sponsored
splits, odometer readings, and defect-injection flags. It exists because no
public booking-level DR dispatch dataset is available; the DR calcs and the
intake path need realistic dispatch days.

The output is SIMULATED DATA. It must enter Headway with envelope
``source = "dr_simulated"`` — never ``"dr"``: file drops via the DR
connector with ``DR_SOURCE=dr_simulated``; machine-API pushes via a key
bound to source label ``dr_simulated`` (the handoff-0005 binding rule,
applied to DR by handoff 0013). The source flows to
``canonical.dr_trips.source`` so simulated records stay permanently
distinguishable in provenance.

Determinism: all randomness flows through one ``random.Random(seed)``
instance (seeded randomness is fine in a simulator; this is not calc code).
Same arguments + same seed => byte-identical output.

Defect-injection flags exist to exercise the fail-loudly paths downstream:

- ``--missing-distance-share``: completed trips with NO onboard_miles and NO
  odometer readings — exercises the dr_vrm/dr_pmt unmeasured-distance
  warnings (a distance is never guessed).
- ``--negative-duration-share``: trips whose dropoff precedes their pickup —
  exercises the transform's malformed-row quarantine.
- ``--ada-sponsored-conflict-share``: trips flagged BOTH ada_related and
  sponsored — exercises the dr_upt conflict warning (ADA-related UPT is
  never sponsored, manual pp. 143-144 as quoted in the tracker).
- ``--missing-sponsor-share``: sponsored trips without a sponsor label —
  exercises the transform's malformed-row quarantine.

No database connection is needed: DR trips originate in dispatch platforms,
not in Headway's canonical GTFS tables, so the simulator is self-contained.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# The full contract column list (contracts/demand-response-trip.v0.schema.json).
FIELDNAMES = [
    "dr_trip_id",
    "service_date",
    "vehicle_id",
    "mode",
    "tos",
    "request_timestamp",
    "dispatch_timestamp",
    "pickup_timestamp",
    "dropoff_timestamp",
    "pickup_lat",
    "pickup_lon",
    "dropoff_lat",
    "dropoff_lon",
    "onboard_miles",
    "distance_source",
    "pickup_odometer_miles",
    "dropoff_odometer_miles",
    "riders",
    "attendants_companions",
    "ada_related",
    "sponsored",
    "sponsor",
    "no_show",
    "interruption_after",
    "driver_shift_id",
    "dispatching_point_id",
]

OUTPUT_FILENAME = "demand_response_trips.csv"

TOS_VALUES = ("DO", "PT", "TX", "TN")
SPONSORS = ("Medicaid NEMT", "Meals-On-Wheels", "County Senior Services")
INTERRUPTIONS = ("lunch", "fuel", "garage_return", "dispatch_return")

# Simulated service area (vendor-neutral; roughly a small city grid).
BASE_LAT, BASE_LON = 42.30, -71.10


@dataclass
class _VehicleState:
    vehicle_id: str
    tos: str
    clock: datetime  # current simulated time
    odometer: float  # miles


def _fmt_ts(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fmt_miles(miles: float) -> str:
    return f"{miles:.2f}"


def parse_tos_mix(text: str) -> list[tuple[str, int]]:
    """Parse 'DO:3,PT:2,TX:1' into [('DO', 3), ('PT', 2), ('TX', 1)]."""
    mix: list[tuple[str, int]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        tos, _, count = part.partition(":")
        tos = tos.strip().upper()
        if tos not in TOS_VALUES:
            raise argparse.ArgumentTypeError(
                f"unknown TOS {tos!r}: must be one of {', '.join(TOS_VALUES)}"
            )
        try:
            n = int(count)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"bad vehicle count {count!r} for TOS {tos}"
            )
        if n < 0:
            raise argparse.ArgumentTypeError(f"negative vehicle count for TOS {tos}")
        mix.append((tos, n))
    if not any(n for _, n in mix):
        raise argparse.ArgumentTypeError("tos-mix names zero vehicles")
    return mix


def _vehicle_day(
    state: _VehicleState,
    service_date: date,
    trips_target: int,
    rng: random.Random,
) -> list[dict]:
    """Generate one vehicle's dispatch day as contract rows.

    DO/PT/TN vehicles get interruptions (lunch/fuel/returns) that break the
    revenue span; a shared ride is a second booking picked up while the
    first is still onboard. TX vehicles (non-dedicated) run sequential
    bookings without interruption markers. Odometer readings advance with a
    per-leg speed so empty inter-passenger travel is measurable.
    """
    rows: list[dict] = []
    trip_seq = 0
    lunch_after = rng.randint(3, max(3, trips_target - 2))
    shift_id = f"shift-{state.vehicle_id}-{service_date.isoformat()}"
    dispatch_point = f"dp-{rng.randint(1, 2)}"

    while trip_seq < trips_target:
        trip_seq += 1
        # Empty travel to the next pickup (deadhead before the first pickup;
        # revenue empty travel between passengers within a span).
        empty_minutes = rng.uniform(3.0, 12.0)
        empty_miles = empty_minutes * rng.uniform(0.25, 0.45)
        state.clock += timedelta(minutes=empty_minutes)
        state.odometer += empty_miles

        no_show = rng.random() < 0.12
        shared = (not no_show) and rng.random() < 0.3
        pickup = state.clock
        request_ts = pickup - timedelta(minutes=rng.uniform(20.0, 180.0))
        dispatch_ts = pickup - timedelta(minutes=rng.uniform(5.0, 18.0))
        pickup_lat = BASE_LAT + rng.uniform(-0.08, 0.08)
        pickup_lon = BASE_LON + rng.uniform(-0.08, 0.08)
        pickup_odo = state.odometer

        base = {
            "dr_trip_id": f"sim:{service_date.isoformat()}:{state.vehicle_id}:{trip_seq}",
            "service_date": service_date.isoformat(),
            "vehicle_id": state.vehicle_id,
            "mode": "DR",
            "tos": state.tos,
            "request_timestamp": _fmt_ts(request_ts),
            "dispatch_timestamp": _fmt_ts(dispatch_ts),
            "pickup_timestamp": _fmt_ts(pickup),
            "pickup_lat": f"{pickup_lat:.5f}",
            "pickup_lon": f"{pickup_lon:.5f}",
            "distance_source": "odometer",
            "sponsor": "",
            "interruption_after": "none",
            "driver_shift_id": shift_id,
            "dispatching_point_id": dispatch_point,
        }

        if no_show:
            # Driver arrives, waits, passenger never shows: revenue time per
            # Exhibit 36 (as quoted in the tracker), ZERO boardings.
            wait = timedelta(minutes=rng.uniform(3.0, 6.0))
            state.clock = pickup + wait
            rows.append(
                base
                | {
                    "dropoff_timestamp": _fmt_ts(state.clock),
                    "dropoff_lat": base["pickup_lat"],
                    "dropoff_lon": base["pickup_lon"],
                    "onboard_miles": "0.00",
                    "pickup_odometer_miles": _fmt_miles(pickup_odo),
                    "dropoff_odometer_miles": _fmt_miles(state.odometer),
                    "riders": 0,
                    "attendants_companions": 0,
                    "ada_related": "true" if rng.random() < 0.5 else "false",
                    "sponsored": "false",
                    "no_show": "true",
                }
            )
            continue

        # One speed per trip block keeps the odometer physically consistent
        # across a shared ride's overlapping bookings.
        speed = rng.uniform(0.25, 0.45)  # miles per minute
        onboard_minutes = rng.uniform(8.0, 25.0)
        onboard_miles = onboard_minutes * speed
        dropoff = pickup + timedelta(minutes=onboard_minutes)
        ada = rng.random() < 0.4
        sponsored = (not ada) and rng.random() < 0.25
        row = base | {
            "dropoff_timestamp": _fmt_ts(dropoff),
            "dropoff_lat": f"{pickup_lat + rng.uniform(-0.05, 0.05):.5f}",
            "dropoff_lon": f"{pickup_lon + rng.uniform(-0.05, 0.05):.5f}",
            "onboard_miles": _fmt_miles(onboard_miles),
            "pickup_odometer_miles": _fmt_miles(pickup_odo),
            "dropoff_odometer_miles": _fmt_miles(pickup_odo + onboard_miles),
            "riders": rng.randint(1, 3),
            "attendants_companions": 1 if rng.random() < 0.25 else 0,
            "ada_related": "true" if ada else "false",
            "sponsored": "true" if sponsored else "false",
            "sponsor": rng.choice(SPONSORS) if sponsored else "",
            "no_show": "false",
        }
        rows.append(row)

        if shared and trip_seq < trips_target:
            # Shared ride: a second booking boards while the first is still
            # onboard (same vehicle, overlapping onboard windows).
            trip_seq += 1
            board_offset = onboard_minutes * rng.uniform(0.3, 0.6)
            pickup2 = pickup + timedelta(minutes=board_offset)
            ride2_minutes = rng.uniform(6.0, 15.0)
            dropoff2 = max(dropoff, pickup2 + timedelta(minutes=ride2_minutes))
            pickup2_odo = pickup_odo + board_offset * speed
            dropoff2_odo = (
                pickup_odo
                + (dropoff2 - pickup).total_seconds() / 60.0 * speed
            )
            onboard2 = dropoff2_odo - pickup2_odo
            ada2 = rng.random() < 0.4
            rows.append(
                base
                | {
                    "dr_trip_id": f"sim:{service_date.isoformat()}:{state.vehicle_id}:{trip_seq}",
                    "request_timestamp": _fmt_ts(pickup2 - timedelta(minutes=rng.uniform(20.0, 90.0))),
                    "dispatch_timestamp": _fmt_ts(pickup2 - timedelta(minutes=rng.uniform(4.0, 12.0))),
                    "pickup_timestamp": _fmt_ts(pickup2),
                    "dropoff_timestamp": _fmt_ts(dropoff2),
                    "pickup_lat": f"{pickup_lat + rng.uniform(-0.02, 0.02):.5f}",
                    "pickup_lon": f"{pickup_lon + rng.uniform(-0.02, 0.02):.5f}",
                    "dropoff_lat": f"{pickup_lat + rng.uniform(-0.05, 0.05):.5f}",
                    "dropoff_lon": f"{pickup_lon + rng.uniform(-0.05, 0.05):.5f}",
                    "onboard_miles": _fmt_miles(onboard2),
                    "pickup_odometer_miles": _fmt_miles(pickup2_odo),
                    "dropoff_odometer_miles": _fmt_miles(pickup2_odo + onboard2),
                    "riders": rng.randint(1, 2),
                    "attendants_companions": 0,
                    "ada_related": "true" if ada2 else "false",
                    "sponsored": "false",
                    "no_show": "false",
                }
            )
            dropoff = dropoff2
            state.clock = dropoff
            state.odometer = dropoff2_odo
        else:
            state.clock = dropoff
            state.odometer = pickup_odo + onboard_miles

        # Interruptions break the revenue span (p. 129 rule as quoted in the
        # tracker). TX vehicles are non-dedicated: no interruption markers.
        if state.tos != "TX":
            marker = None
            if trip_seq == lunch_after:
                marker = "lunch"
            elif rng.random() < 0.10:
                marker = rng.choice(INTERRUPTIONS[1:])  # fuel/garage/dispatch
            if marker is not None and trip_seq < trips_target:
                rows[-1]["interruption_after"] = marker
                pause = rng.uniform(20.0, 45.0) if marker == "lunch" else rng.uniform(10.0, 25.0)
                travel = rng.uniform(1.0, 4.0)  # interruption travel miles:
                state.clock += timedelta(minutes=pause)  # neither revenue nor
                state.odometer += travel  # deadhead (p. 130)

    return rows


def _inject_defects(
    rows: list[dict],
    rng: random.Random,
    missing_distance_share: float,
    negative_duration_share: float,
    ada_sponsored_conflict_share: float,
    missing_sponsor_share: float,
) -> None:
    """Deterministically inject defects into disjoint row sets (in place)."""
    candidates = [r for r in rows if r["no_show"] == "false"]
    picked: set[str] = set()

    def pick(share: float, predicate=lambda r: True) -> list[dict]:
        pool = [
            r
            for r in candidates
            if r["dr_trip_id"] not in picked and predicate(r)
        ]
        n = min(round(share * len(rows)), len(pool))
        chosen = rng.sample(pool, n) if n > 0 else []
        picked.update(r["dr_trip_id"] for r in chosen)
        return chosen

    for row in pick(missing_distance_share):
        row["onboard_miles"] = ""
        row["pickup_odometer_miles"] = ""
        row["dropoff_odometer_miles"] = ""
        row["distance_source"] = ""
    for row in pick(negative_duration_share):
        # dropoff before pickup: a contradiction the transform must quarantine.
        pickup = datetime.fromisoformat(row["pickup_timestamp"].replace("Z", "+00:00"))
        row["dropoff_timestamp"] = _fmt_ts(pickup - timedelta(minutes=5))
    for row in pick(ada_sponsored_conflict_share):
        row["ada_related"] = "true"
        row["sponsored"] = "true"
        row["sponsor"] = rng.choice(SPONSORS)
    # Only non-ADA trips: forcing sponsored onto an ADA trip would create an
    # unintended second defect (the ADA/sponsored conflict above).
    for row in pick(missing_sponsor_share, lambda r: r["ada_related"] == "false"):
        row["sponsored"] = "true"
        row["sponsor"] = ""


def generate_trips(
    service_date: date,
    seed: int,
    tos_mix: list[tuple[str, int]],
    trips_per_vehicle: int,
    missing_distance_share: float = 0.0,
    negative_duration_share: float = 0.0,
    ada_sponsored_conflict_share: float = 0.0,
    missing_sponsor_share: float = 0.0,
) -> list[dict]:
    """Generate contract-valid demand_response_trip rows for one dispatch day.

    Deterministic for a given argument set: all randomness comes from one
    random.Random(seed).
    """
    rng = random.Random(seed)
    rows: list[dict] = []
    vehicle_n = 0
    for tos, count in tos_mix:
        for _ in range(count):
            vehicle_n += 1
            start = datetime.combine(
                service_date, datetime.min.time(), tzinfo=timezone.utc
            ) + timedelta(hours=7, minutes=rng.uniform(0.0, 90.0))
            state = _VehicleState(
                vehicle_id=f"dr-van-{vehicle_n:02d}",
                tos=tos,
                clock=start,
                odometer=rng.uniform(10_000.0, 90_000.0),
            )
            target = max(1, trips_per_vehicle + rng.randint(-2, 2))
            rows.extend(_vehicle_day(state, service_date, target, rng))

    _inject_defects(
        rows,
        rng,
        missing_distance_share,
        negative_duration_share,
        ada_sponsored_conflict_share,
        missing_sponsor_share,
    )
    return rows


def write_csv(rows: list[dict], out_dir: Path) -> Path:
    """Write rows to <out_dir>/demand_response_trips.csv and return the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def _share(value: str) -> float:
    f = float(value)
    if not 0.0 <= f <= 1.0:
        raise argparse.ArgumentTypeError(f"share must be in [0, 1], got {value}")
    return f


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--service-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--seed", type=int, default=0, help="deterministic RNG seed")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument(
        "--tos-mix",
        type=parse_tos_mix,
        default=parse_tos_mix("DO:3,PT:2,TX:1"),
        help="vehicles per TOS, e.g. 'DO:3,PT:2,TX:1' (default) — TOS per the contract enum",
    )
    parser.add_argument(
        "--trips-per-vehicle",
        type=int,
        default=8,
        help="mean bookings per vehicle-day (default 8; +-2 jitter per vehicle)",
    )
    parser.add_argument(
        "--missing-distance-share",
        type=_share,
        default=0.0,
        help="share of completed trips with NO distance data (unmeasured-distance path)",
    )
    parser.add_argument(
        "--negative-duration-share",
        type=_share,
        default=0.0,
        help="share of trips with dropoff before pickup (transform quarantine path)",
    )
    parser.add_argument(
        "--ada-sponsored-conflict-share",
        type=_share,
        default=0.0,
        help="share of trips flagged both ada_related and sponsored (dr_upt conflict warning)",
    )
    parser.add_argument(
        "--missing-sponsor-share",
        type=_share,
        default=0.0,
        help="share of sponsored trips without a sponsor label (transform quarantine path)",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    service_date = date.fromisoformat(args.service_date)
    rows = generate_trips(
        service_date,
        seed=args.seed,
        tos_mix=args.tos_mix,
        trips_per_vehicle=args.trips_per_vehicle,
        missing_distance_share=args.missing_distance_share,
        negative_duration_share=args.negative_duration_share,
        ada_sponsored_conflict_share=args.ada_sponsored_conflict_share,
        missing_sponsor_share=args.missing_sponsor_share,
    )
    out_path = write_csv(rows, Path(args.out))
    vehicles = len({r["vehicle_id"] for r in rows})
    print(
        f"SIMULATED data: {len(rows)} demand_response_trip rows for "
        f"{vehicles} vehicles on {service_date} -> {out_path} "
        f"(drop with DR_SOURCE=dr_simulated, or push with a machine key "
        f"bound to source label dr_simulated)"
    )
    return out_path


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
