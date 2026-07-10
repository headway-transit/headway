#!/usr/bin/env python3
"""TIDES passenger_events simulator (handoff 0005, slice 2).

Generates SIMULATED, TIDES-spec-valid ``passenger_events.csv`` rows for the
trips actually operated on a service date (trips present in
``canonical.vehicle_positions`` that day), so downstream UPT calcs have
event-level APC data aligned with real operations. No public event-level APC
dataset exists (TIDES /samples is template-only), hence simulation.

The output is SIMULATED DATA. It must be dropped into the TIDES connector
with ``TIDES_SOURCE=tides_simulated`` — never ``tides`` — so the envelope
source makes the simulation permanently distinguishable in provenance
(handoff 0005 binding rule).

Determinism: all randomness flows through one ``random.Random(seed)``
instance (seeded randomness is fine in a simulator; this is not calc code).
Same inputs + same seed => byte-identical output.

Defect-injection flags exist to exercise the FTA validation rules quoted in
handoff 0005 (2026 NTD Policy Manual):
- ``--missing-trip-share``: operated trips with zero passenger events —
  exercises the p. 146 missing-trip factor-up / 2% statistician threshold.
- ``--imbalance-share``: trips whose alightings differ from boardings by
  more than 10% — exercises the p. 151 boarding/alighting imbalance flag.
- ``--negative-load-share``: trips with an early alighting exceeding prior
  boardings, driving running load below zero — exercises the p. 151
  negative-load flag.

Schema verified against TIDES-transit/TIDES spec/passenger_events.schema.json
(commit d887d42ce081f3fb6155664a3c486101d62ec52b, fetched 2026-07-10).
Connection: CLI reads DATABASE_URL or libpq-style PG* env like db/migrate.py;
the core logic takes an injected DB-API connection (tests use a fake).
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# event_type enumeration (constraints.enum) from the verified TIDES
# passenger_events schema, verbatim:
EVENT_TYPE_ENUM = [
    "Vehicle arrived at stop",
    "Vehicle departed stop",
    "Door opened",
    "Door closed",
    "Passenger boarded",
    "Passenger alighted",
    "Kneel was engaged",
    "Kneel was disengaged",
    "Ramp was deployed",
    "Ramp was raised",
    "Ramp deployment failed",
    "Lift was deployed",
    "Lift was raised",
    "Individual bike boarded",
    "Individual bike alighted",
    "Bike rack deployed",
]

# The two event types this simulator emits (both members of the enum above).
EVENT_BOARDED = "Passenger boarded"
EVENT_ALIGHTED = "Passenger alighted"

# Output columns: all required TIDES fields (passenger_event_id,
# service_date, event_timestamp, trip_stop_sequence, event_type, vehicle_id)
# plus the optional fields this simulator populates.
FIELDNAMES = [
    "passenger_event_id",
    "service_date",
    "event_timestamp",
    "trip_id_performed",
    "trip_stop_sequence",
    "event_type",
    "vehicle_id",
    "event_count",
]

OUTPUT_FILENAME = "passenger_events.csv"

OPERATED_TRIPS_SQL = """
SELECT vp.trip_id,
       min(vp.vehicle_id) AS vehicle_id,
       min(vp."time")     AS first_seen,
       max(vp."time")     AS last_seen
FROM canonical.vehicle_positions vp
-- No JOIN to canonical.trips: MBTA RT includes ADDED trips absent from the
-- static schedule; they operated, so the missing-trip denominator must see
-- them (matches headway_calc.reader.load_operated_trip_ids).
WHERE vp."time" >= %s AND vp."time" < %s
GROUP BY vp.trip_id
ORDER BY vp.trip_id
"""


@dataclass(frozen=True)
class OperatedTrip:
    """One trip observed in canonical.vehicle_positions on the service date."""

    trip_id: str
    vehicle_id: str
    first_seen: datetime
    last_seen: datetime


def fetch_operated_trips(conn, service_date: date) -> list[OperatedTrip]:
    """Read the operated trips for service_date via an injected connection.

    Operated = the trip appears in canonical.vehicle_positions during the
    service date (UTC day bounds) and exists in canonical.trips.
    """
    day_start = datetime.combine(service_date, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    cur = conn.cursor()
    cur.execute(OPERATED_TRIPS_SQL, (day_start, day_end))
    rows = cur.fetchall()
    return [
        OperatedTrip(trip_id=r[0], vehicle_id=r[1], first_seen=r[2], last_seen=r[3])
        for r in rows
    ]


def _pick_defect_sets(
    trips: list[OperatedTrip],
    rng: random.Random,
    missing_trip_share: float,
    imbalance_share: float,
    negative_load_share: float,
) -> tuple[set[str], set[str], set[str]]:
    """Deterministically assign disjoint defect sets by trip_id.

    Counts are round(share * n); sampling comes from the seeded rng, so the
    assignment is reproducible for a given seed and trip list.
    """
    remaining = [t.trip_id for t in trips]  # already sorted by the query
    picked: list[set[str]] = []
    for share in (missing_trip_share, imbalance_share, negative_load_share):
        n = min(round(share * len(trips)), len(remaining))
        chosen = set(rng.sample(remaining, n)) if n > 0 else set()
        remaining = [t for t in remaining if t not in chosen]
        picked.append(chosen)
    return picked[0], picked[1], picked[2]


def _trip_events(
    trip: OperatedTrip,
    service_date: date,
    rng: random.Random,
    imbalanced: bool,
    negative_load: bool,
) -> list[dict]:
    """Generate one trip's boarding/alighting rows.

    Plausible profile: boardings early/mid trip, alightings mid/late trip,
    everyone off at the last stop. Default trips balance exactly
    (alightings == boardings). Timestamps are spread across the trip's
    observed position window.
    """
    n_stops = rng.randint(8, 16)
    span = (trip.last_seen - trip.first_seen).total_seconds()
    if span <= 0:
        span = 600.0  # degenerate single-ping trip: assume a 10-minute run

    rows: list[dict] = []
    counter = 0

    def add(seq: int, event_type: str, count: int) -> None:
        nonlocal counter
        counter += 1
        offset = span * (seq - 1) / max(n_stops - 1, 1)
        ts = trip.first_seen + timedelta(seconds=offset)
        rows.append(
            {
                "passenger_event_id": f"sim:{service_date.isoformat()}:{trip.trip_id}:{counter}",
                "service_date": service_date.isoformat(),
                "event_timestamp": ts.astimezone(timezone.utc).isoformat(),
                "trip_id_performed": trip.trip_id,
                "trip_stop_sequence": seq,
                "event_type": event_type,
                "vehicle_id": trip.vehicle_id,
                "event_count": count,
            }
        )

    boarded = 0
    load = 0
    negative_done = False
    for seq in range(1, n_stops + 1):
        if negative_load and not negative_done and seq >= 2:
            # Defect: alight more passengers than have boarded so far, so
            # the running load drops below zero (FTA p. 151 example).
            add(seq, EVENT_ALIGHTED, load + 2)
            load = -2
            negative_done = True
            continue
        if seq < n_stops and rng.random() < 0.8:
            count = rng.randint(1, 5)
            add(seq, EVENT_BOARDED, count)
            boarded += count
            load += count
        if seq > n_stops // 2 and seq < n_stops and load > 0 and rng.random() < 0.5:
            count = rng.randint(1, min(load, 4))
            add(seq, EVENT_ALIGHTED, count)
            load -= count
    if load > 0:
        add(n_stops, EVENT_ALIGHTED, load)  # everyone off at the last stop
        load = 0

    if imbalanced and boarded > 0:
        # Defect: shrink total alightings so |boardings - alightings|
        # exceeds 10% of boardings (FTA p. 151 example). floor(10%) + 1 is
        # strictly greater than 10% for any boarding total. Trim from the
        # final alighting rows.
        deficit = int(boarded * 0.10) + 1
        for row in reversed(rows):
            if deficit == 0:
                break
            if row["event_type"] != EVENT_ALIGHTED:
                continue
            take = min(row["event_count"], deficit)
            row["event_count"] -= take
            deficit -= take
        rows = [r for r in rows if r["event_count"] > 0]

    return rows


def generate_events(
    trips: list[OperatedTrip],
    service_date: date,
    seed: int,
    missing_trip_share: float = 0.0,
    imbalance_share: float = 0.0,
    negative_load_share: float = 0.0,
) -> list[dict]:
    """Generate spec-valid passenger_events rows for the operated trips.

    Deterministic for a given (trips, service_date, seed, flags) input: all
    randomness comes from one random.Random(seed).
    """
    rng = random.Random(seed)
    trips = sorted(trips, key=lambda t: t.trip_id)
    missing, imbalanced, negative = _pick_defect_sets(
        trips, rng, missing_trip_share, imbalance_share, negative_load_share
    )

    rows: list[dict] = []
    for trip in trips:
        if trip.trip_id in missing:
            continue  # operated but no events: the missing-trip defect
        rows.extend(
            _trip_events(
                trip,
                service_date,
                rng,
                imbalanced=trip.trip_id in imbalanced,
                negative_load=trip.trip_id in negative,
            )
        )
    return rows


def write_csv(rows: list[dict], out_dir: Path) -> Path:
    """Write rows to <out_dir>/passenger_events.csv and return the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def run(conn, args: argparse.Namespace) -> Path:
    """Core entry point over an injected DB-API connection."""
    service_date = date.fromisoformat(args.service_date)
    trips = fetch_operated_trips(conn, service_date)
    rows = generate_events(
        trips,
        service_date,
        seed=args.seed,
        missing_trip_share=args.missing_trip_share,
        imbalance_share=args.imbalance_share,
        negative_load_share=args.negative_load_share,
    )
    out_path = write_csv(rows, Path(args.out))
    print(
        f"SIMULATED data: {len(rows)} passenger_events rows for "
        f"{len(trips)} operated trips on {service_date} -> {out_path} "
        f"(drop with TIDES_SOURCE=tides_simulated)"
    )
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
        "--missing-trip-share",
        type=_share,
        default=0.0,
        help="share of operated trips generating NO events (FTA p. 146 rule)",
    )
    parser.add_argument(
        "--imbalance-share",
        type=_share,
        default=0.0,
        help="share of trips with |boardings-alightings| > 10%% (FTA p. 151)",
    )
    parser.add_argument(
        "--negative-load-share",
        type=_share,
        default=0.0,
        help="share of trips whose running load drops below zero (FTA p. 151)",
    )
    return parser.parse_args(argv)


def connect_kwargs() -> dict:
    """Connection parameters from the environment (same rules as db/migrate.py).

    DATABASE_URL wins if set (credentials must be percent-encoded);
    otherwise libpq-style PG* variables are passed as psycopg keyword args.
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return {"conninfo": database_url}
    kwargs = {
        keyword: os.environ[env_var]
        for keyword, env_var in (
            ("host", "PGHOST"),
            ("port", "PGPORT"),
            ("user", "PGUSER"),
            ("password", "PGPASSWORD"),
            ("dbname", "PGDATABASE"),
        )
        if os.environ.get(env_var)
    }
    if "host" not in kwargs or "dbname" not in kwargs:
        print(
            "ERROR: no connection configured: set DATABASE_URL (percent-encode "
            "credentials), or set PGHOST and PGDATABASE (plus PGPORT/PGUSER/"
            "PGPASSWORD as needed)",
            file=sys.stderr,
        )
        sys.exit(1)
    return kwargs


def main() -> None:
    args = parse_args()
    try:
        import psycopg
    except ImportError:
        print("ERROR: psycopg (v3) is required: pip install 'psycopg[binary]'", file=sys.stderr)
        sys.exit(1)
    with psycopg.connect(**connect_kwargs()) as conn:
        run(conn, args)


if __name__ == "__main__":
    main()
