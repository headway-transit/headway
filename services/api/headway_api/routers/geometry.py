"""Map geometry: stops and schematic route lines (handoff 0023, design pt 3).

OPS CATEGORY (handoff 0014 / migration 0024 boundary, restated in every
envelope): geometry is operations data for the map — never certified, never
part of any submission, never a gate on certification.

HONESTY RULES this router enforces:
- /geometry/routes v0 is the SCHEMATIC built from ordered stop sequences —
  straight lines between stops. Headway has never ingested shapes.txt, so
  the response labels itself ``geometry_kind: "schematic_stop_sequence"``
  everywhere and must never imply street-level geometry (shapes.txt
  ingestion is the recorded v1 increment, handoff 0023 open questions).
- A stop with no coordinates (legal per GTFS for generic nodes / boarding
  areas) is never given an invented point: it is excluded from geometry and
  COUNTED, with the count served.
- Caps are served with counts (truncated=true + totals), never silent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import time as time_mod
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from ..auth import Identity
from ..authz import require_authenticated
from ..db import get_db
from .ops import OPS_NOTE

router = APIRouter(tags=["geometry"])

SCHEMATIC_KIND = "schematic_stop_sequence"

SCHEMATIC_NOTE = (
    "Schematic geometry: each route line connects the stops of the route's "
    "most common trip pattern with straight segments. It shows structure, "
    "not streets — Headway has not ingested shapes.txt (street-level "
    "geometry is a recorded future increment), and this line must not be "
    "presented as the path vehicles drive."
)

#: Cap + count honesty. 50k stops / 2k routes comfortably covers the largest
#: agencies this stack targets; beyond that the response says it truncated.
MAX_STOPS = 50_000
MAX_ROUTES = 2_000

#: /geometry/routes is served from a per-process cache for up to this many
#: seconds (staleness bounded and stated in the response): the pattern
#: aggregation walks every stop_times row (~3.9 s measured over the live
#: 3.1M-row table — handoff 0023 evidence) and schedule geometry changes
#: only when a new static GTFS feed is ingested.
ROUTES_CACHE_TTL_SECONDS = 900

_SELECT_STOPS = (
    "SELECT stop_id, name, latitude, longitude FROM canonical.stops "
    "ORDER BY stop_id LIMIT %s"
)

_COUNT_STOPS = "SELECT count(*) FROM canonical.stops"

#: Most common trip pattern per route: aggregate each trip's ordered stop
#: ids, count identical sequences per route, keep the most-frequent one
#: (deterministic tie-break: the lexicographically first pattern). Grouping
#: and counting only — no geometry is invented here; the polyline is drawn
#: through the stops' own coordinates.
_SELECT_ROUTE_PATTERNS = (
    "WITH trip_patterns AS ("
    " SELECT t.route_id, st.trip_id,"
    "        array_agg(st.stop_id ORDER BY st.stop_sequence) AS stop_ids"
    " FROM canonical.stop_times st"
    " JOIN canonical.trips t ON t.trip_id = st.trip_id"
    " GROUP BY t.route_id, st.trip_id"
    "), pattern_counts AS ("
    " SELECT route_id, stop_ids, count(*) AS trip_count"
    " FROM trip_patterns GROUP BY route_id, stop_ids"
    "), chosen AS ("
    " SELECT DISTINCT ON (route_id) route_id, stop_ids, trip_count"
    " FROM pattern_counts ORDER BY route_id, trip_count DESC, stop_ids"
    ") "
    "SELECT r.route_id, r.short_name, r.long_name, r.mode, c.stop_ids, "
    "c.trip_count "
    "FROM chosen c JOIN canonical.routes r ON r.route_id = c.route_id "
    "ORDER BY r.route_id LIMIT %s"
)

_COUNT_ROUTES_WITH_TRIPS = (
    "SELECT count(DISTINCT route_id) FROM canonical.trips"
)


class PointGeometry(BaseModel):
    type: str = "Point"
    #: GeoJSON positions: [longitude, latitude] (RFC 7946).
    coordinates: list[float]


class LineStringGeometry(BaseModel):
    type: str = "LineString"
    coordinates: list[list[float]]


class StopFeature(BaseModel):
    type: str = "Feature"
    geometry: PointGeometry
    properties: dict[str, Any]


class StopsCollection(BaseModel):
    """GeoJSON FeatureCollection of canonical.stops. The extra members are
    GeoJSON foreign members (RFC 7946 §6.1) carrying Headway's honesty
    metadata."""

    type: str = "FeatureCollection"
    features: list[StopFeature]
    category: str = "ops"
    ops_note: str = OPS_NOTE
    stop_count: int
    #: Stops excluded because GTFS legitimately omits their coordinates —
    #: never invented, counted instead.
    stops_without_coordinates: int
    cap: int = MAX_STOPS
    truncated: bool = False
    total_stops: int
    note: Optional[str] = None


class RouteFeature(BaseModel):
    type: str = "Feature"
    geometry: LineStringGeometry
    properties: dict[str, Any]


class RoutesCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[RouteFeature]
    category: str = "ops"
    ops_note: str = OPS_NOTE
    #: v0 honesty label (handoff 0023): stop-sequence schematic, NOT streets.
    geometry_kind: str = SCHEMATIC_KIND
    geometry_note: str = SCHEMATIC_NOTE
    route_count: int
    #: Routes that have trips but could not be drawn (fewer than two stops
    #: with coordinates in their most common pattern) — excluded and counted,
    #: never fabricated.
    routes_without_geometry: int
    cap: int = MAX_ROUTES
    truncated: bool = False
    total_routes_with_trips: int
    #: When this collection was computed from the database (it is served from
    #: a per-process cache for up to cache_ttl_seconds).
    computed_at: dt.datetime
    cache_ttl_seconds: int = ROUTES_CACHE_TTL_SECONDS
    cache_note: str = (
        "Served from a per-process cache for up to cache_ttl_seconds after "
        "computed_at; schedule geometry changes only when a new static GTFS "
        "feed is ingested."
    )
    note: Optional[str] = None


def _etag_for(payload_fingerprint: str) -> str:
    return f'"{payload_fingerprint}"'


def _fetch_stops(db) -> tuple[list[tuple], int, bool]:
    """All stop rows (bounded), plus the total count and truncation flag."""
    rows = db.execute(_SELECT_STOPS, (MAX_STOPS + 1,)).fetchall()
    truncated = len(rows) > MAX_STOPS
    if truncated:
        rows = rows[:MAX_STOPS]
        total = db.execute(_COUNT_STOPS, ()).fetchone()[0]
    else:
        total = len(rows)
    return rows, total, truncated


def _stops_fingerprint(rows: list[tuple]) -> str:
    """Content hash of the served stop data (id, name, lat, lon — the exact
    fields the FeatureCollection carries). canonical.stops has no ingest
    timestamp column (static-feed rows are upserted), so a content hash is
    the honest cache validator: it changes exactly when the served geometry
    would (choice recorded in handoff 0023 evidence)."""
    h = hashlib.sha256()
    for stop_id, name, lat, lon in rows:
        h.update(
            f"{stop_id}\x1f{name}\x1f{lat!r}\x1f{lon!r}\x1e".encode()
        )
    return h.hexdigest()[:32]


@router.get("/geometry/stops", response_model=StopsCollection)
def stops_geojson(
    request: Request,
    response: Response,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> Optional[StopsCollection]:
    """GeoJSON FeatureCollection of every canonical stop with coordinates
    (any signed-in role). Cacheable: a strong content-hash ETag — a matching
    If-None-Match returns 304 (the hash still reads the rows; the saving is
    serialization and transfer, recorded honestly in handoff 0023)."""
    rows, total, truncated = _fetch_stops(db)
    etag = _etag_for(f"stops-{_stops_fingerprint(rows)}")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=300"
    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": "private, max-age=300"},
        )

    features: list[StopFeature] = []
    missing = 0
    for stop_id, name, lat, lon in rows:
        if lat is None or lon is None:
            missing += 1
            continue
        features.append(
            StopFeature(
                geometry=PointGeometry(coordinates=[lon, lat]),
                properties={"stop_id": stop_id, "name": name},
            )
        )
    note = None
    if truncated:
        note = (
            f"This installation has more stops than this endpoint serves at "
            f"once: showing {len(features)} of {total}. This cap exists to "
            f"bound the response; raising it is a configuration question, "
            f"not a data gap."
        )
    return StopsCollection(
        features=features,
        stop_count=len(features),
        stops_without_coordinates=missing,
        truncated=truncated,
        total_stops=total,
        note=note,
    )


def _build_routes_collection(db) -> RoutesCollection:
    pattern_rows = db.execute(_SELECT_ROUTE_PATTERNS, (MAX_ROUTES + 1,)).fetchall()
    truncated = len(pattern_rows) > MAX_ROUTES
    if truncated:
        pattern_rows = pattern_rows[:MAX_ROUTES]
        total = db.execute(_COUNT_ROUTES_WITH_TRIPS, ()).fetchone()[0]
    else:
        total = len(pattern_rows)

    stop_rows, _stop_total, _stops_truncated = _fetch_stops(db)
    coords = {
        stop_id: (lon, lat)
        for stop_id, _name, lat, lon in stop_rows
        if lat is not None and lon is not None
    }

    features: list[RouteFeature] = []
    undrawable = 0
    for route_id, short_name, long_name, mode, stop_ids, trip_count in pattern_rows:
        line: list[list[float]] = []
        missing = 0
        for stop_id in stop_ids:
            point = coords.get(stop_id)
            if point is None:
                missing += 1
                continue
            line.append([point[0], point[1]])
        if len(line) < 2:
            # A line needs two located stops; fabricating one would imply
            # geometry we do not have. Excluded and counted.
            undrawable += 1
            continue
        features.append(
            RouteFeature(
                geometry=LineStringGeometry(coordinates=line),
                properties={
                    "route_id": route_id,
                    "short_name": short_name,
                    "long_name": long_name,
                    "mode": mode,
                    "geometry_kind": SCHEMATIC_KIND,
                    "pattern_trip_count": trip_count,
                    "stop_count": len(stop_ids),
                    "stops_missing_coordinates": missing,
                },
            )
        )

    note = None
    if truncated:
        note = (
            f"This installation has more routes than this endpoint serves "
            f"at once: showing the first {len(features)} of {total} routes "
            f"with trips."
        )
    return RoutesCollection(
        features=features,
        route_count=len(features),
        routes_without_geometry=undrawable,
        truncated=truncated,
        total_routes_with_trips=total,
        computed_at=dt.datetime.now(dt.timezone.utc),
        note=note,
    )


@router.get("/geometry/routes", response_model=RoutesCollection)
def routes_geojson(
    request: Request,
    response: Response,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> Optional[RoutesCollection]:
    """Schematic route lines (any signed-in role): per route, a straight-line
    polyline through the ordered stops of its most common trip pattern —
    labeled ``schematic_stop_sequence`` because that is exactly what it is
    (no shapes.txt has ever been ingested; street-level geometry is the
    recorded v1).

    The collection is computed at most once per ROUTES_CACHE_TTL_SECONDS per
    process (the aggregation walks every stop_times row); ``computed_at``
    and ``cache_ttl_seconds`` state the staleness bound, and the ETag lets
    clients revalidate cheaply."""
    cache = getattr(request.app.state, "geometry_routes_cache", None)
    now = time_mod.monotonic()
    if cache is not None and now < cache["expires"]:
        collection, etag = cache["collection"], cache["etag"]
    else:
        collection = _build_routes_collection(db)
        # computed_at is excluded from the validator so the ETag tracks the
        # CONTENT: identical geometry recomputed later keeps the same ETag.
        body_hash = hashlib.sha256(
            collection.model_dump_json(exclude={"computed_at"}).encode()
        ).hexdigest()[:32]
        etag = _etag_for(f"routes-{body_hash}")
        request.app.state.geometry_routes_cache = {
            "expires": now + ROUTES_CACHE_TTL_SECONDS,
            "collection": collection,
            "etag": etag,
        }
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=300"
    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": "private, max-age=300"},
        )
    return collection
