"""Minimal GTFS static loader: routes.txt + trips.txt + stops.txt +
stop_times.txt -> canonical.routes/trips/stops/stop_times.

Parses a GTFS static zip (stdlib zipfile + csv) into CanonicalRoute,
CanonicalTrip, CanonicalStop and CanonicalStopTime dataclasses per handoffs
0001 and 0011, with one LineageEdge per row back to the static feed's
content-addressed record_id, and a DQFinding for every row or file that
could not be normalized — never a silent skip.

Stop geometry rules (handoff 0011, binding — PMT per-segment distances):

- ``shape_dist_traveled`` is NULLABLE and preserved as-is: a feed that omits
  the optional column (e.g. MBTA) stays NULL; a distance is NEVER fabricated
  here (pmt_v0 falls back to flagged stop-to-stop haversine).
- stop coordinates are nullable: the GTFS Schedule Reference (stops.txt,
  gtfs.org, verified 2026-07-12) requires them only for location_type 0/1/2;
  generic nodes (3) and boarding areas (4) may omit them. A coordinate
  missing where the spec requires one is a warning DQFinding, stored NULL —
  never a guessed point.
- GTFS times may exceed 24:00:00 (service past midnight): parsed to integer
  seconds ("noon minus 12 h" convention); empty times are valid GTFS on
  non-timepoint rows -> NULL, no finding; malformed times -> NULL + warning.
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
from .row_guard import field_problems, iter_rows

TRANSFORM_NAME = "normalize_gtfs_static"
# 0.2.0: parses trips.txt block_id (handoff 0003, block-aware VRH).
# 0.3.0: parses stops.txt + stop_times.txt (handoff 0011, PMT geometry). New
# version so lineage edges distinguish rows normalized with stop support.
# 0.3.1: decompression-size budget (zip-bomb guard) + per-row parse
# quarantine (2026-07-13 hardening pass).
TRANSFORM_VERSION = "0.3.1"

# Decompressed-size budget (2026-07-13 hardening pass): a zip member's
# compressed size says nothing about its decompressed size — a crafted
# archive (decompression bomb) could exhaust memory/disk. The budget is
# stream-counted while reading; exceeding it ABORTS the feed with a
# blocking transform_failure finding naming the limit — never a silent
# truncation. Generous defaults: the largest real member seen so far
# (MBTA stop_times.txt, ~3.1M rows) is well under 512 MiB decompressed.
MAX_MEMBER_BYTES = 512 * 1024 * 1024  # per zip member, decompressed
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # whole archive, decompressed
_CHUNK_BYTES = 64 * 1024


class DecompressionBudgetExceeded(Exception):
    """A zip member blew the decompressed-size budget (bomb guard)."""

    def __init__(self, member: str, kind: str, limit_bytes: int) -> None:
        self.member = member
        self.kind = kind
        self.limit_bytes = limit_bytes
        super().__init__(
            f"zip member {member!r} exceeded the {kind} decompressed-size "
            f"limit of {limit_bytes} bytes while streaming"
        )


class _Budget:
    """Stream-counted decompression budget across an archive's members."""

    def __init__(self, member_limit: int, total_limit: int) -> None:
        self.member_limit = member_limit
        self.total_limit = total_limit
        self.total_used = 0

INPUT_KIND = "raw.records"
ROUTES_OUTPUT_KIND = "canonical.routes"
TRIPS_OUTPUT_KIND = "canonical.trips"
STOPS_OUTPUT_KIND = "canonical.stops"
STOP_TIMES_OUTPUT_KIND = "canonical.stop_times"

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
    """One canonical.trips row (handoff 0001; block_id per handoff 0003)."""

    trip_id: str  # TEXT PRIMARY KEY
    route_id: str  # TEXT NOT NULL REFERENCES canonical.routes
    service_id: str  # TEXT NOT NULL
    direction_id: int | None  # SMALLINT
    block_id: str | None = None  # TEXT (migration 0011; optional per GTFS)


@dataclass(frozen=True)
class CanonicalStop:
    """One canonical.stops row (handoff 0011 / migration 0019)."""

    stop_id: str  # TEXT PRIMARY KEY
    name: str | None  # TEXT
    latitude: float | None  # DOUBLE PRECISION (nullable — see module doc)
    longitude: float | None  # DOUBLE PRECISION (nullable)


@dataclass(frozen=True)
class CanonicalStopTime:
    """One canonical.stop_times row (handoff 0011 / migration 0019)."""

    trip_id: str  # TEXT NOT NULL
    stop_id: str  # TEXT NOT NULL
    stop_sequence: int  # INTEGER NOT NULL; PK (trip_id, stop_sequence)
    arrival_seconds: int | None  # INTEGER (GTFS HH:MM:SS, may exceed 24 h)
    departure_seconds: int | None  # INTEGER
    shape_dist_traveled: float | None  # DOUBLE PRECISION — NULL preserved


def _read_member(zf: zipfile.ZipFile, name: str, budget: _Budget) -> bytes:
    """Stream one zip member under the decompression budget (see above)."""
    used = 0
    buf = io.BytesIO()
    with zf.open(name) as fh:
        while True:
            chunk = fh.read(_CHUNK_BYTES)
            if not chunk:
                break
            used += len(chunk)
            budget.total_used += len(chunk)
            if used > budget.member_limit:
                raise DecompressionBudgetExceeded(
                    name, "per-member", budget.member_limit
                )
            if budget.total_used > budget.total_limit:
                raise DecompressionBudgetExceeded(
                    name, "whole-archive", budget.total_limit
                )
            buf.write(chunk)
    return buf.getvalue()


def _read_csv(
    zf: zipfile.ZipFile, name: str, budget: _Budget
) -> csv.DictReader:
    # utf-8-sig: GTFS files commonly carry a BOM.
    text = _read_member(zf, name, budget).decode("utf-8-sig")
    return csv.DictReader(io.StringIO(text, newline=""))


def _parse_gtfs_time(raw: str) -> int:
    """GTFS H:MM:SS / HH:MM:SS -> seconds after "noon minus 12 h".

    Hours may exceed 23 (service past midnight is e.g. 25:30:00 per the GTFS
    Schedule Reference). Raises ValueError on anything else — the caller
    quarantines, never guesses.
    """
    parts = raw.split(":")
    if len(parts) != 3:
        raise ValueError(f"not an H:MM:SS time: {raw!r}")
    hours, minutes, seconds = (int(p) for p in parts)
    if hours < 0 or not (0 <= minutes <= 59) or not (0 <= seconds <= 59):
        raise ValueError(f"out-of-range H:MM:SS time: {raw!r}")
    return hours * 3600 + minutes * 60 + seconds


#: GTFS location_type values whose coordinates are REQUIRED by the spec
#: (stops.txt, gtfs.org: required for 0/empty, 1, 2; optional for 3, 4).
_COORD_REQUIRED_LOCATION_TYPES = ("", "0", "1", "2")


def normalize(
    zip_bytes: bytes,
    record_id: str,
    *,
    max_member_bytes: int = MAX_MEMBER_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> tuple[
    list[CanonicalRoute],
    list[CanonicalTrip],
    list[CanonicalStop],
    list[CanonicalStopTime],
    list[LineageEdge],
    list[DQFinding],
]:
    """Normalize a GTFS static zip's routes.txt, trips.txt, stops.txt and
    stop_times.txt.

    Returns (routes, trips, stops, stop_times, lineage_edges, dq_findings).
    Every emitted row has exactly one lineage edge (input = the feed's
    record_id); every file or row that cannot be normalized is a DQFinding.
    A feed whose members exceed the decompression budget (zip-bomb guard)
    is ABORTED: zero rows, one blocking transform_failure finding naming
    the limit.
    """
    routes: list[CanonicalRoute] = []
    trips: list[CanonicalTrip] = []
    stops: list[CanonicalStop] = []
    stop_times: list[CanonicalStopTime] = []
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
        return routes, trips, stops, stop_times, edges, findings

    budget = _Budget(max_member_bytes, max_total_bytes)
    try:
        _normalize_members(
            zf, record_id, budget,
            routes, trips, stops, stop_times, edges, findings,
        )
    except DecompressionBudgetExceeded as exc:
        findings.append(
            DQFinding(
                issue_type="transform_failure",
                severity=SEVERITY_BLOCKING,
                title="GTFS static feed exceeds the decompression size budget",
                description=(
                    f"Record {record_id}: {exc}. Normalization ABORTED — no "
                    "rows from this feed were written (raw record retained). "
                    "The budget guards against decompression bombs; if this "
                    "is a legitimate oversized feed, raise the limit "
                    "explicitly in the transform configuration."
                ),
                source_record_ids=[record_id],
            )
        )
        return [], [], [], [], [], findings
    return routes, trips, stops, stop_times, edges, findings


def _normalize_members(
    zf: zipfile.ZipFile,
    record_id: str,
    budget: _Budget,
    routes: list[CanonicalRoute],
    trips: list[CanonicalTrip],
    stops: list[CanonicalStop],
    stop_times: list[CanonicalStopTime],
    edges: list[LineageEdge],
    findings: list[DQFinding],
) -> None:
    """Parse the archive's members into the caller's accumulators.

    Raises DecompressionBudgetExceeded (handled by normalize) when a member
    blows the streamed decompression budget.
    """
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

        def _row_defect(file_name: str, index: int, problems: list[str]) -> DQFinding:
            # Per-row parse quarantine (2026-07-13 hardening pass): one
            # hostile row (oversized field / NUL byte / stray quote) is ONE
            # finding — it can no longer abort the whole feed's batch.
            return DQFinding(
                issue_type="malformed_entity",
                severity=SEVERITY_WARNING,
                title=f"{file_name} row could not be parsed",
                description=(
                    f"Record {record_id}, {file_name} row {index}: "
                    + "; ".join(problems)
                    + ". Row quarantined, not dropped silently."
                ),
                source_record_ids=[record_id],
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
            for index, row, parse_error in iter_rows(_read_csv(zf, "routes.txt", budget)):
                defects = (
                    [f"CSV parse error: {parse_error}"]
                    if parse_error is not None
                    else field_problems(row)
                )
                if defects:
                    findings.append(_row_defect("routes.txt", index, defects))
                    continue
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
            for index, row, parse_error in iter_rows(_read_csv(zf, "trips.txt", budget)):
                defects = (
                    [f"CSV parse error: {parse_error}"]
                    if parse_error is not None
                    else field_problems(row)
                )
                if defects:
                    findings.append(_row_defect("trips.txt", index, defects))
                    continue
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

                # block_id is OPTIONAL per the GTFS Schedule Reference,
                # trips.txt (gtfs.org/documentation/schedule/reference/
                # #tripstxt, verified 2026-07-09): "Identifies the block to
                # which the trip belongs. A block consists of a single trip
                # or many sequential trips made using the same vehicle,
                # defined by shared service days and block_id." An absent
                # column or empty value is valid GTFS → NULL, NO DQ finding.
                block_id = (row.get("block_id") or "").strip() or None

                trip = CanonicalTrip(
                    trip_id=trip_id,
                    route_id=route_id,
                    service_id=service_id,
                    direction_id=direction_id,
                    block_id=block_id,
                )
                trips.append(trip)
                edges.append(_edge(TRIPS_OUTPUT_KIND, trip.trip_id))

        # --- stops.txt (handoff 0011 — PMT geometry) ----------------------
        if "stops.txt" not in names:
            findings.append(
                DQFinding(
                    issue_type="malformed_entity",
                    severity=SEVERITY_BLOCKING,
                    title="GTFS static feed is missing stops.txt",
                    description=(
                        f"Record {record_id}: stops.txt (required by the "
                        "GTFS Schedule spec, gtfs.org, for fixed-route "
                        "feeds) is absent; no stops normalized — PMT "
                        "distances cannot be derived from this feed."
                    ),
                    source_record_ids=[record_id],
                )
            )
        else:
            for index, row, parse_error in iter_rows(_read_csv(zf, "stops.txt", budget)):
                defects = (
                    [f"CSV parse error: {parse_error}"]
                    if parse_error is not None
                    else field_problems(row)
                )
                if defects:
                    findings.append(_row_defect("stops.txt", index, defects))
                    continue
                stop_id = (row.get("stop_id") or "").strip()
                if not stop_id:
                    findings.append(
                        DQFinding(
                            issue_type="malformed_entity",
                            severity=SEVERITY_WARNING,
                            title="stops.txt row has no stop_id",
                            description=(
                                f"Record {record_id}, stops.txt row {index}: "
                                "stop_id is missing/empty; row quarantined, "
                                "not dropped silently."
                            ),
                            source_record_ids=[record_id],
                        )
                    )
                    continue

                location_type = (row.get("location_type") or "").strip()
                coords: dict[str, float | None] = {}
                for field, lo, hi in (
                    ("stop_lat", -90.0, 90.0),
                    ("stop_lon", -180.0, 180.0),
                ):
                    raw = (row.get(field) or "").strip()
                    value: float | None
                    if not raw:
                        value = None
                        # Coordinates are REQUIRED for location_type 0/1/2
                        # (GTFS Schedule Reference, stops.txt) — an absence
                        # there is a defect; nodes (3) / boarding areas (4)
                        # legitimately omit them (no finding).
                        if location_type in _COORD_REQUIRED_LOCATION_TYPES:
                            findings.append(
                                DQFinding(
                                    issue_type="stop_missing_coordinates",
                                    severity=SEVERITY_WARNING,
                                    title=(
                                        f"stops.txt stop {stop_id!r} is "
                                        f"missing {field}"
                                    ),
                                    description=(
                                        f"Record {record_id}, stop "
                                        f"{stop_id!r} (location_type "
                                        f"{location_type or '0 (default)'}): "
                                        f"{field} is empty though the GTFS "
                                        "Schedule spec requires coordinates "
                                        "for this location_type. Stored "
                                        "NULL — a coordinate is never "
                                        "guessed; distance calculations "
                                        "needing this stop fail loudly."
                                    ),
                                    source_record_ids=[record_id],
                                )
                            )
                    else:
                        try:
                            value = float(raw)
                        except ValueError:
                            value = None
                        if value is not None and not (lo <= value <= hi):
                            value = None
                        if value is None:
                            findings.append(
                                DQFinding(
                                    issue_type="malformed_entity",
                                    severity=SEVERITY_WARNING,
                                    title=(
                                        f"stops.txt stop {stop_id!r} has an "
                                        f"unusable {field}"
                                    ),
                                    description=(
                                        f"Record {record_id}, stop "
                                        f"{stop_id!r}: {field} {raw!r} is "
                                        f"not a number in [{lo}, {hi}]. "
                                        "Stored NULL and flagged — never "
                                        "coerced to a guess."
                                    ),
                                    source_record_ids=[record_id],
                                )
                            )
                    coords[field] = value

                stop = CanonicalStop(
                    stop_id=stop_id,
                    name=(row.get("stop_name") or "").strip() or None,
                    latitude=coords["stop_lat"],
                    longitude=coords["stop_lon"],
                )
                stops.append(stop)
                edges.append(_edge(STOPS_OUTPUT_KIND, stop.stop_id))

        # --- stop_times.txt (handoff 0011 — PMT geometry) -----------------
        if "stop_times.txt" not in names:
            findings.append(
                DQFinding(
                    issue_type="malformed_entity",
                    severity=SEVERITY_BLOCKING,
                    title="GTFS static feed is missing stop_times.txt",
                    description=(
                        f"Record {record_id}: stop_times.txt (required by "
                        "the GTFS Schedule spec, gtfs.org) is absent; no "
                        "stop times normalized — PMT per-segment distances "
                        "cannot be derived from this feed."
                    ),
                    source_record_ids=[record_id],
                )
            )
        else:
            for index, row, parse_error in iter_rows(_read_csv(zf, "stop_times.txt", budget)):
                defects = (
                    [f"CSV parse error: {parse_error}"]
                    if parse_error is not None
                    else field_problems(row)
                )
                if defects:
                    findings.append(_row_defect("stop_times.txt", index, defects))
                    continue
                trip_id = (row.get("trip_id") or "").strip()
                stop_id = (row.get("stop_id") or "").strip()
                raw_sequence = (row.get("stop_sequence") or "").strip()
                sequence: int | None
                try:
                    sequence = int(raw_sequence) if raw_sequence else None
                except ValueError:
                    sequence = None
                if sequence is not None and sequence < 0:
                    sequence = None  # non-negative per the GTFS spec
                if not trip_id or not stop_id or sequence is None:
                    findings.append(
                        DQFinding(
                            issue_type="malformed_entity",
                            severity=SEVERITY_WARNING,
                            title=(
                                "stop_times.txt row is missing required "
                                "fields"
                            ),
                            description=(
                                f"Record {record_id}, stop_times.txt row "
                                f"{index}: trip_id={trip_id!r}, stop_id="
                                f"{stop_id!r}, stop_sequence="
                                f"{raw_sequence!r} — a required identity "
                                "field is missing or not a non-negative "
                                "integer; row quarantined, not dropped "
                                "silently."
                            ),
                            source_record_ids=[record_id],
                        )
                    )
                    continue

                times: dict[str, int | None] = {}
                for field in ("arrival_time", "departure_time"):
                    raw = (row.get(field) or "").strip()
                    if not raw:
                        # Valid GTFS on non-timepoint rows: NULL, no finding
                        # (never interpolated).
                        times[field] = None
                        continue
                    try:
                        times[field] = _parse_gtfs_time(raw)
                    except ValueError:
                        times[field] = None
                        findings.append(
                            DQFinding(
                                issue_type="malformed_entity",
                                severity=SEVERITY_WARNING,
                                title=(
                                    f"stop_times.txt trip {trip_id!r} seq "
                                    f"{sequence} has an unusable {field}"
                                ),
                                description=(
                                    f"Record {record_id}, trip {trip_id!r} "
                                    f"stop_sequence {sequence}: {field} "
                                    f"{raw!r} is not a GTFS H:MM:SS time. "
                                    "Stored NULL and flagged — never "
                                    "coerced to a guess."
                                ),
                                source_record_ids=[record_id],
                            )
                        )

                # shape_dist_traveled: OPTIONAL per the GTFS Schedule
                # Reference — absent column or empty value is valid GTFS →
                # NULL, NO finding (handoff 0011: preserve NULL, never
                # fabricate). A present but unusable value is a defect.
                raw_sdt = (row.get("shape_dist_traveled") or "").strip()
                sdt: float | None = None
                if raw_sdt:
                    try:
                        sdt = float(raw_sdt)
                    except ValueError:
                        sdt = None
                    if sdt is not None and not (sdt >= 0.0):
                        sdt = None  # negative or NaN: non-negative per spec
                    if sdt is None:
                        findings.append(
                            DQFinding(
                                issue_type="malformed_entity",
                                severity=SEVERITY_WARNING,
                                title=(
                                    f"stop_times.txt trip {trip_id!r} seq "
                                    f"{sequence} has an unusable "
                                    "shape_dist_traveled"
                                ),
                                description=(
                                    f"Record {record_id}, trip {trip_id!r} "
                                    f"stop_sequence {sequence}: "
                                    f"shape_dist_traveled {raw_sdt!r} is "
                                    "not a non-negative number. Stored "
                                    "NULL and flagged — a distance is "
                                    "never fabricated."
                                ),
                                source_record_ids=[record_id],
                            )
                        )

                stop_time = CanonicalStopTime(
                    trip_id=trip_id,
                    stop_id=stop_id,
                    stop_sequence=sequence,
                    arrival_seconds=times["arrival_time"],
                    departure_seconds=times["departure_time"],
                    shape_dist_traveled=sdt,
                )
                stop_times.append(stop_time)
                edges.append(
                    _edge(
                        STOP_TIMES_OUTPUT_KIND,
                        f"{trip_id}:{sequence}",
                    )
                )
