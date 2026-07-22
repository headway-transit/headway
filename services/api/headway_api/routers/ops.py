"""Operations vehicle feed: the live map's data (handoff 0023, design point 2).

OPS CATEGORY, stated in the envelope (the handoff 0014 / migration 0024
boundary): live vehicle positions are operations data — never certifiable,
never part of any NTD submission, never a gate on certification. This router
serves canonical.vehicle_positions rows VERBATIM (plus the source label from
raw.records for the per-vehicle SIMULATED badge); the only derived field is
``age_seconds``, a presentation affordance computed from the database clock,
never persisted and never a reported figure.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..auth import Identity
from ..authz import require_authenticated
from ..db import get_db

router = APIRouter(tags=["operations"])

#: The ops-boundary statement every response carries (handoff 0014 /
#: migration 0024, restated per handoff 0023): the UI must keep this surface
#: visually distinct from reported figures.
OPS_NOTE = (
    "Operations data — not an NTD reported figure. Live vehicle positions "
    "are never certifiable, never part of any submission, and never a gate "
    "on certification (migration 0024 boundary)."
)

#: Fleet-size cap with count honesty: a sane fleet is hundreds to low
#: thousands of vehicles; a pathological feed beyond this cap is truncated
#: LOUDLY (truncated=true + total_in_window) rather than silently.
MAX_VEHICLES = 5000

#: max_age_seconds bounds: at least 1 s; at most 24 h (a wider window is a
#: history question, not a live-map question, and it bounds the scan).
MAX_AGE_CEILING_SECONDS = 86_400
DEFAULT_MAX_AGE_SECONDS = 300

#: Latest row per vehicle inside the staleness window. The DISTINCT ON walks
#: the (vehicle_id, time, source_record_id) unique index newest-first per
#: vehicle; the time predicate excludes whole hypertable chunks (measured
#: ~75 ms for a 2 h window over 15M live rows — handoff 0023 evidence).
#: now() is the DATABASE clock, the same clock `time` is compared against.
_SELECT_LATEST = (
    "SELECT DISTINCT ON (vp.vehicle_id) vp.vehicle_id, vp.time, "
    "vp.latitude, vp.longitude, vp.bearing, vp.speed_mps, vp.trip_id, "
    "vp.route_id, vp.source_record_id, r.source "
    "FROM canonical.vehicle_positions vp "
    "JOIN raw.records r ON r.record_id = vp.source_record_id "
    "WHERE vp.time >= now() - make_interval(secs => %s) "
    "ORDER BY vp.vehicle_id, vp.time DESC "
    "LIMIT %s"
)

_COUNT_IN_WINDOW = (
    "SELECT count(DISTINCT vehicle_id) FROM canonical.vehicle_positions "
    "WHERE time >= now() - make_interval(secs => %s)"
)

#: Data-age honesty: the newest position overall (no window), so an empty or
#: thin response can say how stale the feed actually is instead of implying
#: an empty fleet.
_SELECT_NEWEST = "SELECT now(), max(time) FROM canonical.vehicle_positions"


def source_is_simulated(source: str) -> bool:
    """Mirror of exports.is_simulated_detail / web isSimulated: a source
    label naming a simulated source marks the row."""
    return "simulated" in source.lower()


class OpsVehicle(BaseModel):
    """One vehicle's latest position, verbatim from
    canonical.vehicle_positions (nullable fields stay null — an unassigned
    position is served unassigned, never guessed)."""

    vehicle_id: str
    latitude: float
    longitude: float
    #: Event time from the feed (canonical.vehicle_positions.time), verbatim.
    recorded_at: dt.datetime
    #: Presentation affordance: whole seconds between the database clock
    #: (as_of) and recorded_at at query time. Derived for the staleness
    #: badge, never persisted, not a reported figure.
    age_seconds: int
    bearing: Optional[float] = None
    speed_mps: Optional[float] = None
    trip_id: Optional[str] = None
    route_id: Optional[str] = None
    #: Provenance: the raw record this position was normalized from.
    source_record_id: str
    #: The raw record's source label, verbatim (e.g. 'gtfs_rt_mbta',
    #: 'tides_simulated').
    source: str
    #: True when the source label names a simulated source — the SIMULATED
    #: badge must be renderable per vehicle.
    simulated: bool


class OpsVehiclesLatest(BaseModel):
    #: The database clock at query time — ages are relative to this.
    as_of: dt.datetime
    max_age_seconds: int
    #: The handoff 0014 / migration 0024 honesty boundary, restated.
    category: str = "ops"
    ops_note: str = OPS_NOTE
    vehicles: list[OpsVehicle]
    vehicle_count: int
    #: Distinct vehicles inside the window (equals vehicle_count unless
    #: truncated).
    total_in_window: int
    cap: int = MAX_VEHICLES
    truncated: bool = False
    #: The newest position in the whole table regardless of window — how
    #: fresh the feed really is. Null only when no position was ever
    #: ingested.
    newest_position_at: Optional[dt.datetime] = None
    #: Plain language when the response would otherwise mislead: an empty
    #: vehicle list from a stale feed, or a truncated list.
    note: Optional[str] = None


@router.get("/ops/vehicles/latest", response_model=OpsVehiclesLatest)
def latest_vehicles(
    max_age_seconds: int = Query(
        default=DEFAULT_MAX_AGE_SECONDS,
        ge=1,
        le=MAX_AGE_CEILING_SECONDS,
        description=(
            "Staleness window: only vehicles whose latest position is at "
            "most this many seconds old (by the database clock) are served."
        ),
    ),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> OpsVehiclesLatest:
    """Latest position per vehicle for the live map (any signed-in role).

    Poll guidance: the upstream GTFS-RT connector polls its feed every ~30 s
    (deploy default POLL_INTERVAL=30s), so polling this endpoint faster than
    ~15 s cannot surface newer data — 15–30 s is the recommended map poll
    interval. There is no push transport (honest scope, handoff 0023; SSE is
    a recorded open question if polling ever measurably hurts).
    """
    rows = db.execute(_SELECT_LATEST, (max_age_seconds, MAX_VEHICLES + 1)).fetchall()
    truncated = len(rows) > MAX_VEHICLES
    if truncated:
        rows = rows[:MAX_VEHICLES]
        total_in_window = db.execute(
            _COUNT_IN_WINDOW, (max_age_seconds,)
        ).fetchone()[0]
    else:
        total_in_window = len(rows)

    now_row = db.execute(_SELECT_NEWEST, ()).fetchone()
    as_of, newest_position_at = now_row[0], now_row[1]

    vehicles = [
        OpsVehicle(
            vehicle_id=r[0],
            recorded_at=r[1],
            latitude=r[2],
            longitude=r[3],
            bearing=r[4],
            speed_mps=r[5],
            trip_id=r[6],
            route_id=r[7],
            source_record_id=str(r[8]),
            source=r[9],
            simulated=source_is_simulated(r[9]),
            age_seconds=int((as_of - r[1]).total_seconds()),
        )
        for r in rows
    ]

    note: Optional[str] = None
    if truncated:
        note = (
            f"More vehicles reported positions in this window than this "
            f"endpoint serves at once: showing {MAX_VEHICLES} of "
            f"{total_in_window}. Narrow max_age_seconds to see a complete "
            f"picture."
        )
    elif not vehicles:
        if newest_position_at is None:
            note = (
                "No vehicle positions have ever been ingested. The map has "
                "nothing to show yet — this is a data availability state, "
                "not an empty fleet."
            )
        else:
            age = int((as_of - newest_position_at).total_seconds())
            note = (
                f"No vehicle has reported a position in the last "
                f"{max_age_seconds} seconds. The newest position on record "
                f"is {age} seconds old — the feed is stale or service is "
                f"not running, not an empty fleet."
            )

    return OpsVehiclesLatest(
        as_of=as_of,
        max_age_seconds=max_age_seconds,
        vehicles=vehicles,
        vehicle_count=len(vehicles),
        total_in_window=total_in_window,
        truncated=truncated,
        newest_position_at=newest_position_at,
        note=note,
    )
