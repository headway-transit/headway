"""Minimal GTFS static loader: routes.txt + trips.txt -> canonical.routes/trips.

Parses a GTFS static zip (stdlib zipfile + csv) into CanonicalRoute and
CanonicalTrip dataclasses per handoff 0001, with one LineageEdge per row back
to the static feed's content-addressed record_id, and a DQFinding for every
row or file that could not be normalized — never a silent skip.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass

from .model import (
    SEVERITY_BLOCKING,
    SEVERITY_WARNING,
    DQFinding,
    LineageEdge,
)

TRANSFORM_NAME = "normalize_gtfs_static"
TRANSFORM_VERSION = "0.1.0"

INPUT_KIND = "raw.records"
ROUTES_OUTPUT_KIND = "canonical.routes"
TRIPS_OUTPUT_KIND = "canonical.trips"

# GTFS route_type -> canonical text mode.
# Source: GTFS Schedule Reference, routes.txt route_type enum, gtfs.org
# (https://gtfs.org/documentation/schedule/reference/#routestxt), consulted
# 2026-07 — VERIFY against the current published spec before extending; the
# spec also defines an extended route-type range not mapped here (any
# unmapped value becomes mode 'unknown' plus a DQFinding, never a guess).
ROUTE_TYPE_TO_MODE: dict[int, str] = {
    0: "tram",         # Tram, Streetcar, Light rail
    1: "subway",       # Subway, Metro
    2: "rail",         # Rail (intercity/long-distance)
    3: "bus",          # Bus
    4: "ferry",        # Ferry
    5: "cable_tram",   # Cable tram
    6: "aerial_lift",  # Aerial lift (gondola, cable car)
    7: "funicular",    # Funicular
    11: "trolleybus",  # Trolleybus
    12: "monorail",    # Monorail
}

MODE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class CanonicalRoute:
    """One canonical.routes row (handoff 0001)."""

    route_id: str  # TEXT PRIMARY KEY
    short_name: str | None  # TEXT
    long_name: str | None  # TEXT
    mode: str  # TEXT NOT NULL


@dataclass(frozen=True)
class CanonicalTrip:
    """One canonical.trips row (handoff 0001)."""

    trip_id: str  # TEXT PRIMARY KEY
    route_id: str  # TEXT NOT NULL REFERENCES canonical.routes
    service_id: str  # TEXT NOT NULL
    direction_id: int | None  # SMALLINT


def _read_csv(zf: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with zf.open(name) as fh:
        # utf-8-sig: GTFS files commonly carry a BOM.
        text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text))


def normalize(
    zip_bytes: bytes, record_id: str
) -> tuple[list[CanonicalRoute], list[CanonicalTrip], list[LineageEdge], list[DQFinding]]:
    """Normalize a GTFS static zip's routes.txt and trips.txt.

    Returns (routes, trips, lineage_edges, dq_findings). Every emitted row
    has exactly one lineage edge (input = the feed's record_id); every file
    or row that cannot be normalized is a DQFinding.
    """
    routes: list[CanonicalRoute] = []
    trips: list[CanonicalTrip] = []
    edges: list[LineageEdge] = []
    findings: list[DQFinding] = []

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        findings.append(
            DQFinding(
                issue_type="undecodable_payload",
                severity=SEVERITY_BLOCKING,
                title="GTFS static payload is not a readable zip",
                description=(
                    f"Record {record_id}: {exc}. Feed was not normalized; "
                    "raw record retained."
                ),
                source_record_ids=[record_id],
            )
        )
        return routes, trips, edges, findings

    with zf:
        names = set(zf.namelist())

        def _edge(kind: str, output_id: str) -> LineageEdge:
            return LineageEdge(
                output_kind=kind,
                output_id=output_id,
                transform_name=TRANSFORM_NAME,
                transform_version=TRANSFORM_VERSION,
                input_kind=INPUT_KIND,
                input_id=record_id,
            )

        # --- routes.txt -------------------------------------------------
        if "routes.txt" not in names:
            findings.append(
                DQFinding(
                    issue_type="malformed_entity",
                    severity=SEVERITY_BLOCKING,
                    title="GTFS static feed is missing routes.txt",
                    description=(
                        f"Record {record_id}: routes.txt (required by the "
                        "GTFS Schedule spec, gtfs.org) is absent; no routes "
                        "normalized."
                    ),
                    source_record_ids=[record_id],
                )
            )
        else:
            for index, row in enumerate(_read_csv(zf, "routes.txt")):
                route_id = (row.get("route_id") or "").strip()
                if not route_id:
                    findings.append(
                        DQFinding(
                            issue_type="malformed_entity",
                            severity=SEVERITY_WARNING,
                            title="routes.txt row has no route_id",
                            description=(
                                f"Record {record_id}, routes.txt row {index}: "
                                "route_id is missing/empty; row quarantined, "
                                "not dropped silently."
                            ),
                            source_record_ids=[record_id],
                        )
                    )
                    continue

                raw_type = (row.get("route_type") or "").strip()
                try:
                    route_type: int | None = int(raw_type)
                except ValueError:
                    route_type = None
                mode = (
                    ROUTE_TYPE_TO_MODE.get(route_type, MODE_UNKNOWN)
                    if route_type is not None
                    else MODE_UNKNOWN
                )
                if mode == MODE_UNKNOWN:
                    findings.append(
                        DQFinding(
                            issue_type="unknown_route_type",
                            severity=SEVERITY_WARNING,
                            title="GTFS route_type not in the canonical mode map",
                            description=(
                                f"Record {record_id}, route {route_id!r}: "
                                f"route_type {raw_type!r} is not mapped by "
                                "ROUTE_TYPE_TO_MODE (GTFS Schedule Reference, "
                                "gtfs.org). Mode recorded as 'unknown' — a "
                                "human must classify it; the pipeline never "
                                "guesses."
                            ),
                            source_record_ids=[record_id],
                        )
                    )

                route = CanonicalRoute(
                    route_id=route_id,
                    short_name=(row.get("route_short_name") or "").strip() or None,
                    long_name=(row.get("route_long_name") or "").strip() or None,
                    mode=mode,
                )
                routes.append(route)
                edges.append(_edge(ROUTES_OUTPUT_KIND, route.route_id))

        # --- trips.txt --------------------------------------------------
        if "trips.txt" not in names:
            findings.append(
                DQFinding(
                    issue_type="malformed_entity",
                    severity=SEVERITY_BLOCKING,
                    title="GTFS static feed is missing trips.txt",
                    description=(
                        f"Record {record_id}: trips.txt (required by the "
                        "GTFS Schedule spec, gtfs.org) is absent; no trips "
                        "normalized."
                    ),
                    source_record_ids=[record_id],
                )
            )
        else:
            for index, row in enumerate(_read_csv(zf, "trips.txt")):
                trip_id = (row.get("trip_id") or "").strip()
                route_id = (row.get("route_id") or "").strip()
                service_id = (row.get("service_id") or "").strip()
                missing = [
                    name
                    for name, value in (
                        ("trip_id", trip_id),
                        ("route_id", route_id),
                        ("service_id", service_id),
                    )
                    if not value
                ]
                if missing:
                    findings.append(
                        DQFinding(
                            issue_type="malformed_entity",
                            severity=SEVERITY_WARNING,
                            title="trips.txt row is missing required fields",
                            description=(
                                f"Record {record_id}, trips.txt row {index}: "
                                f"missing {', '.join(missing)}; row "
                                "quarantined, not dropped silently."
                            ),
                            source_record_ids=[record_id],
                        )
                    )
                    continue

                raw_direction = (row.get("direction_id") or "").strip()
                direction_id: int | None
                if not raw_direction:
                    direction_id = None
                else:
                    try:
                        direction_id = int(raw_direction)
                    except ValueError:
                        direction_id = None
                        findings.append(
                            DQFinding(
                                issue_type="malformed_entity",
                                severity=SEVERITY_WARNING,
                                title="trips.txt direction_id is not an integer",
                                description=(
                                    f"Record {record_id}, trip {trip_id!r}: "
                                    f"direction_id {raw_direction!r} is not "
                                    "an integer; stored as NULL and flagged "
                                    "— never coerced to a guess."
                                ),
                                source_record_ids=[record_id],
                            )
                        )

                trip = CanonicalTrip(
                    trip_id=trip_id,
                    route_id=route_id,
                    service_id=service_id,
                    direction_id=direction_id,
                )
                trips.append(trip)
                edges.append(_edge(TRIPS_OUTPUT_KIND, trip.trip_id))

    return routes, trips, edges, findings
