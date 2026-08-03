"""Machine read of computed values (handoff 0006, design point 3).

This is the endpoint that CONSUMES the ``read:metrics`` scope — registered
since migration 0013 but unconsumed until now (the gap noted in handoff
0006's Response, point 3). Keys issued with the scope back then work here
unchanged, exactly as that note promised.

``GET /machine/metrics`` serves the SAME rows, filters, and shape as the
human ``GET /metrics/values`` — it delegates to the same query function
(metrics.query_metric_values), so the two can never drift: ``value`` is a
string (exact NUMERIC, never float) and ``detail`` is served verbatim as the
calc library persisted it.

LINEAGE: every row's ``metric_value_id`` is the input to the existing
"explain this number" endpoint, ``GET /metrics/values/{metric_value_id}/
lineage``, which accepts the SAME ``read:metrics`` key (dual-credential
dependency, machine_auth.require_human_session_or_machine_scope) — the
follow-up noted here in v0, now closed.

Per handoff 0006 design points 4 and 6: every successful read is audited
with actor ``key:<key_prefix>`` (auth failures and scope denials are audited
inside machine_auth), and each key spends from the same per-key token bucket
as ingest.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from ..audit import write_event
from ..db import get_db
from ..machine_auth import (
    SCOPE_READ_DQ,
    SCOPE_READ_METRICS,
    SCOPE_READ_OPS,
    MachineIdentity,
    enforce_rate_limit,
    require_machine_scope,
)
from .dq import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    DqIssue,
    DqIssueCounts,
    DqIssuePage,
    _validate_queue_filters,
    query_issue_counts,
    query_issue_detail,
    query_issue_page,
)
from .metrics import MetricValue, query_metric_values
from .ops import (
    DEFAULT_MAX_AGE_SECONDS,
    MAX_AGE_CEILING_SECONDS,
    OpsVehiclesLatest,
    query_latest_vehicles,
)

router = APIRouter(tags=["machine"])


@router.get("/machine/metrics", response_model=list[MetricValue])
def machine_list_metric_values(
    request: Request,
    metric: Optional[str] = Query(default=None, description="e.g. 'vrm' or 'vrh'"),
    period_start: Optional[dt.date] = Query(default=None),
    period_end: Optional[dt.date] = Query(default=None),
    category: Optional[str] = Query(
        default=None,
        pattern="^(ntd|ops)$",
        description=(
            "Filter on the honesty boundary (migration 0024): 'ntd' "
            "regulatory-pipeline figures or 'ops' operations metrics "
            "(never certifiable, never NTD-reported)."
        ),
    ),
    identity: MachineIdentity = Depends(require_machine_scope(SCOPE_READ_METRICS)),
    db=Depends(get_db),
) -> list[MetricValue]:
    """Computed values for machine consumers (scope ``read:metrics``): same
    filters and shape as the human ``GET /metrics/values``. Each row's
    lineage is available from ``GET /metrics/values/{metric_value_id}/
    lineage`` with this same key."""
    # Per-key token bucket — the same limiter, and therefore the same budget,
    # as ingest (handoff 0006, design point 6; in-process limitation
    # documented on machine_auth.RateLimiter).
    enforce_rate_limit(request.app.state.machine_rate_limiter, identity.key_prefix)

    rows = query_metric_values(db, metric, period_start, period_end, category)

    # Successful key use is audited at endpoint level, actor key:<prefix>
    # (design point 4) — filters and row count only, never the figures.
    with db.transaction():
        write_event(
            db,
            actor=identity.actor,
            action="machine_read_metrics",
            subject_kind="computed.metric_values",
            subject_id=None,
            detail={
                "path": request.url.path,
                "filters": {
                    "metric": metric,
                    "period_start": period_start.isoformat() if period_start else None,
                    "period_end": period_end.isoformat() if period_end else None,
                    "category": category,
                },
                "rows": len(rows),
            },
        )
    return rows


# ---------------------------------------------------------------------------
# Data-quality reads (handoff 0039, design point 2) — scope ``read:dq``.
#
# These MIRROR the human read surface; they do not fork it. Each delegates to
# the SAME query function the human /dq router uses (dq.query_issue_page /
# query_issue_counts / query_issue_detail), so figures, counts, provenance,
# and pagination can never drift between the signed-in UI and a machine
# caller. Sensitivity does not relax for machines: a machine key is a
# VIEWER-class principal and the queue already withholds source_record_ids
# from the list view (handoff 0030) — the machine list withholds it too,
# because it is the SAME query. The per-issue detail serves the provenance
# array exactly as the human detail endpoint does; no sensitive column
# (migration 0028 DR coordinates, the 0035 rules) is on the dq.issues surface
# in the first place, and none is added here (design point 3).
# ---------------------------------------------------------------------------


@router.get("/machine/dq/issues", response_model=DqIssuePage)
def machine_list_dq_issues(
    request: Request,
    status: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    cursor: Optional[str] = Query(default=None),
    identity: MachineIdentity = Depends(require_machine_scope(SCOPE_READ_DQ)),
    db=Depends(get_db),
) -> DqIssuePage:
    """One BOUNDED page of the data-quality queue for machine consumers
    (scope ``read:dq``): the SAME keyset-paginated rows, whole-queue
    ``total``, ``next_cursor``, and ``has_more`` as the human ``GET
    /dq/issues`` (handoff 0030). ``source_record_ids`` is not on a list row —
    it lives on ``GET /machine/dq/issues/{id}`` exactly as it does for the
    human detail endpoint."""
    enforce_rate_limit(request.app.state.machine_rate_limiter, identity.key_prefix)
    _validate_queue_filters(status, severity)
    page = query_issue_page(db, status, severity, limit, cursor)
    with db.transaction():
        write_event(
            db,
            actor=identity.actor,
            action="machine_read_dq_issues",
            subject_kind="dq.issues",
            subject_id=None,
            detail={
                "path": request.url.path,
                "filters": {"status": status, "severity": severity},
                "limit": limit,
                "paged": cursor is not None,
                "rows": len(page.issues),
                "total": page.total,
            },
        )
    return page


@router.get("/machine/dq/issues/counts", response_model=DqIssueCounts)
def machine_count_dq_issues(
    request: Request,
    status: Optional[str] = Query(default=None),
    identity: MachineIdentity = Depends(require_machine_scope(SCOPE_READ_DQ)),
    db=Depends(get_db),
) -> DqIssueCounts:
    """Whole-queue severity/status counts for machine consumers (scope
    ``read:dq``): the SAME GROUP BY over the SAME rows the machine list
    serves under the same optional status filter (handoff 0017/0023). A card
    total can never disagree with the page below it — the query is shared with
    the human ``GET /dq/issues/counts``."""
    enforce_rate_limit(request.app.state.machine_rate_limiter, identity.key_prefix)
    _validate_queue_filters(status, None)
    counts = query_issue_counts(db, status)
    with db.transaction():
        write_event(
            db,
            actor=identity.actor,
            action="machine_read_dq_counts",
            subject_kind="dq.issues",
            subject_id=None,
            detail={
                "path": request.url.path,
                "filters": {"status": status},
                "total": counts.total,
            },
        )
    return counts


@router.get("/machine/dq/issues/{issue_id}", response_model=DqIssue)
def machine_get_dq_issue(
    issue_id: str,
    request: Request,
    identity: MachineIdentity = Depends(require_machine_scope(SCOPE_READ_DQ)),
    db=Depends(get_db),
) -> DqIssue:
    """One issue by id for machine consumers (scope ``read:dq``): the SAME
    detail row as the human ``GET /dq/issues/{id}``, WITH the complete,
    untruncated ``source_record_ids`` provenance array (handoff 0026/0030).
    A missing or malformed id gets the same plain-language 404. Registered
    after /machine/dq/issues/counts so the literal path wins."""
    enforce_rate_limit(request.app.state.machine_rate_limiter, identity.key_prefix)
    issue = query_issue_detail(db, issue_id)
    with db.transaction():
        write_event(
            db,
            actor=identity.actor,
            action="machine_read_dq_issue",
            subject_kind="dq.issues",
            subject_id=issue.issue_id,
            detail={"path": request.url.path},
        )
    return issue


# ---------------------------------------------------------------------------
# Operations reads (handoff 0039, design point 2) — scope ``read:ops``.
#
# Latest vehicle position per vehicle inside a staleness window, delegating to
# ops.query_latest_vehicles — the SAME rows, the SAME ``truncated`` /
# ``total_in_window`` count honesty, the SAME database-clock ``age_seconds``,
# and the SAME staleness ``note`` (never interpolation, never a silent empty
# fleet) as the human ``GET /ops/vehicles/latest`` (handoff 0023).
#
# Open question resolved (handoff 0039): read:ops is TABULAR — it authorizes
# this vehicle-position surface (and ops metric values via the read:metrics
# category='ops' filter already in /machine/metrics). It does NOT authorize
# the GTFS-static geometry endpoints (route shapes / stop patterns); a
# map-drawing assistant is a separate, deliberately-absent surface, recorded
# for a future wave rather than granted implicitly here.
#
# Sensitivity does not relax (design point 3): canonical.vehicle_positions
# carries no rider-identified column (the DR coordinate withholding of
# migration 0028 is on the paratransit trip surface, which is NOT reachable by
# any machine scope in this wave). The machine caller is a VIEWER-class
# principal and sees exactly the columns the signed-in map sees.
# ---------------------------------------------------------------------------


@router.get("/machine/ops/vehicles/latest", response_model=OpsVehiclesLatest)
def machine_latest_vehicles(
    request: Request,
    max_age_seconds: int = Query(
        default=DEFAULT_MAX_AGE_SECONDS,
        ge=1,
        le=MAX_AGE_CEILING_SECONDS,
        description=(
            "Staleness window: only vehicles whose latest position is at "
            "most this many seconds old (by the database clock) are served."
        ),
    ),
    identity: MachineIdentity = Depends(require_machine_scope(SCOPE_READ_OPS)),
    db=Depends(get_db),
) -> OpsVehiclesLatest:
    """Latest position per vehicle for machine consumers (scope
    ``read:ops``): the SAME live-map snapshot as the human ``GET
    /ops/vehicles/latest`` (handoff 0023), staleness framing and count
    honesty intact. Operations data — never certifiable, never an NTD
    reported figure (the ``ops_note`` / ``category`` boundary rides on every
    response)."""
    enforce_rate_limit(request.app.state.machine_rate_limiter, identity.key_prefix)
    snapshot = query_latest_vehicles(db, max_age_seconds)
    with db.transaction():
        write_event(
            db,
            actor=identity.actor,
            action="machine_read_ops_vehicles",
            subject_kind="canonical.vehicle_positions",
            subject_id=None,
            detail={
                "path": request.url.path,
                "max_age_seconds": max_age_seconds,
                "vehicle_count": snapshot.vehicle_count,
                "truncated": snapshot.truncated,
            },
        )
    return snapshot
