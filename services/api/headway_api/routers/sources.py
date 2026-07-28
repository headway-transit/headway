"""Data-source status, read-only v0 (handoff 0025, design point 2).

The first real agency UAT asked for an admin page "where you can add and
connect your data sources". Connecting a source is honestly NOT an in-app
act today — feeds are configured in the deployment's .env, APC files land
in the drop folder or arrive over the machine-key API
(docs/connecting-your-data.md) — and this surface never pretends otherwise:
there is NO add-source mutation here, and the served connecting_note states
how connecting actually works. In-app source *configuration*
(settings-driven ingestion) is the recorded roadmap increment (Platform
Architect open question, handoff 0025).

What this endpoint DOES serve is what the database has actually SEEN, per
(source, connector) from raw.records — the immutable ingest registry:

- the latest record time (landed_at / fetched_at) and the first-seen time;
- record counts and malformed (quarantined-at-parse) counts, both all-time
  and inside a bounded window (default 24 h);
- the canonical liveness the ops endpoint already computes: the newest
  canonical vehicle position against the database clock (the exact
  ops/vehicles/latest freshness fields, restated here).

Numbers here are OPERATIONAL counts about the pipeline itself — row counts
from the registry, never a reported/regulatory figure (those come only from
the calculation library, served with provenance elsewhere).

Role: data steward and above. The four-role model is an escalating
hierarchy (authz.py); the handoff names data_steward + certifying_official,
and the smallest rule that fits the hierarchy without carving a
non-monotonic exception is require_at_least(data_steward) — recorded in the
handoff evidence.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..auth import Identity
from ..authz import require_at_least
from ..db import get_db
from .ops import _SELECT_NEWEST, source_is_simulated

router = APIRouter(tags=["sources"])

#: Window bounds: at least 1 h, at most 30 days. The window bounds the
#: "recent" counts only; totals are all-time.
DEFAULT_WINDOW_HOURS = 24
MAX_WINDOW_HOURS = 720

#: How connecting works today — served with the payload so every consumer
#: states the same honest story (no fake add-source affordance anywhere).
CONNECTING_NOTE = (
    "Connecting a new data source is not an in-app action yet. Feeds are "
    "configured in the deployment's .env file (GTFS and GTFS-Realtime "
    "URLs), APC/TIDES files land in the watched drop folder or arrive over "
    "the machine-key ingest API, and vendor exports go through the vendor "
    "adapters — the step-by-step guide is docs/connecting-your-data.md in "
    "your Headway installation. In-app source configuration is a recorded "
    "roadmap item."
)

#: Per (source, connector): totals, malformed counts, first/latest times,
#: and the bounded-window counts — one aggregate pass over raw.records.
_SELECT_SOURCE_STATUS = (
    "SELECT source, connector, "
    "(array_agg(connector_version ORDER BY landed_at DESC))[1], "
    "count(*), "
    "count(*) FILTER (WHERE parse_status = 'malformed'), "
    "min(landed_at), max(landed_at), max(fetched_at), "
    "count(*) FILTER (WHERE landed_at >= now() - make_interval(hours => %s)), "
    "count(*) FILTER (WHERE parse_status = 'malformed' "
    "AND landed_at >= now() - make_interval(hours => %s)) "
    "FROM raw.records "
    "GROUP BY source, connector "
    "ORDER BY source, connector"
)


class SourceStatus(BaseModel):
    """One (source, connector) pair as raw.records has actually seen it."""

    source: str
    connector: str
    #: The connector version on the newest record — what is running now.
    latest_connector_version: str
    records_total: int
    #: Rows that failed parsing and were quarantined as malformed —
    #: refused loudly at ingest, never silently dropped (raw.records
    #: parse_status).
    malformed_total: int
    first_seen_at: dt.datetime
    latest_landed_at: dt.datetime
    #: When the newest record was fetched/observed at the source, per the
    #: connector's envelope.
    latest_fetched_at: dt.datetime
    #: Presentation affordance: whole seconds between the database clock
    #: (as_of) and latest_landed_at. Derived for staleness display, never
    #: persisted, not a reported figure.
    latest_age_seconds: int
    records_in_window: int
    malformed_in_window: int
    #: True when the source label names a simulated source (same rule as
    #: the ops vehicles endpoint) — the UI badges these rows.
    simulated: bool


class CanonicalLiveness(BaseModel):
    """The same feed-freshness honesty GET /ops/vehicles/latest serves:
    the newest normalized vehicle position vs the database clock."""

    newest_vehicle_position_at: Optional[dt.datetime] = None
    #: Whole seconds between as_of and the newest position; null when no
    #: position was ever ingested.
    age_seconds: Optional[int] = None
    note: str


class SourcesStatusResponse(BaseModel):
    #: The database clock at query time — every age is relative to this.
    as_of: dt.datetime
    window_hours: int
    sources: list[SourceStatus]
    canonical: CanonicalLiveness
    #: How connecting works today, stated honestly (no add-source form
    #: exists because no add-source API exists).
    connecting_note: str = CONNECTING_NOTE
    #: Plain language when the list itself would mislead (nothing ever
    #: ingested).
    note: Optional[str] = None


@router.get("/sources/status", response_model=SourcesStatusResponse)
def sources_status(
    window_hours: int = Query(
        default=DEFAULT_WINDOW_HOURS,
        ge=1,
        le=MAX_WINDOW_HOURS,
        description=(
            "Bounded window (hours) for the recent-activity counts. "
            "Totals are always all-time."
        ),
    ),
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> SourcesStatusResponse:
    """What every data source has actually delivered — per (source,
    connector): latest record times, all-time and windowed record counts,
    and malformed (quarantined) counts — plus the canonical vehicle-position
    liveness the ops endpoint computes. Read-only: connecting sources
    happens outside the app today (see connecting_note)."""
    rows = db.execute(
        _SELECT_SOURCE_STATUS, (window_hours, window_hours)
    ).fetchall()
    now_row = db.execute(_SELECT_NEWEST, ()).fetchone()
    as_of, newest_position_at = now_row[0], now_row[1]

    sources = [
        SourceStatus(
            source=r[0],
            connector=r[1],
            latest_connector_version=r[2],
            records_total=r[3],
            malformed_total=r[4],
            first_seen_at=r[5],
            latest_landed_at=r[6],
            latest_fetched_at=r[7],
            latest_age_seconds=int((as_of - r[6]).total_seconds()),
            records_in_window=r[8],
            malformed_in_window=r[9],
            simulated=source_is_simulated(r[0]),
        )
        for r in rows
    ]

    if newest_position_at is None:
        canonical_note = (
            "No vehicle positions have been normalized yet. Once a "
            "real-time feed is connected and flowing, the newest position "
            "time appears here."
        )
        age_seconds = None
    else:
        age_seconds = int((as_of - newest_position_at).total_seconds())
        canonical_note = (
            "The newest normalized vehicle position, against the database "
            "clock — the same freshness the live map states."
        )

    note = None
    if not sources:
        note = (
            "No raw records have ever landed on this Headway instance. "
            "Nothing is connected yet, or nothing has flowed — see the "
            "connecting guide below."
        )

    return SourcesStatusResponse(
        as_of=as_of,
        window_hours=window_hours,
        sources=sources,
        canonical=CanonicalLiveness(
            newest_vehicle_position_at=newest_position_at,
            age_seconds=age_seconds,
            note=canonical_note,
        ),
        note=note,
    )
