"""GET /metrics/history — period series for audience views (handoff 0023,
design point 4).

PERSISTED FIGURES ONLY, VERBATIM. This endpoint serves computed.metric_values
rows exactly as the calculation library wrote them — value as the exact
NUMERIC string, detail verbatim, metric_value_id on every point so each dot
on a chart keeps its receipt door. The ``bucket`` parameter GROUPS points
under a calendar key derived from each figure's own period start; the server
NEVER sums, averages, or otherwise derives a number no calc produced. A true
quarterly/annual rollup is a calculation library job with receipts (recorded
open question, handoff 0023).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import Identity
from ..authz import require_authenticated
from ..db import get_db
from ..exports import is_simulated_detail
from .metrics import MetricValue, _SELECT_VALUES, _detail_as_dict

router = APIRouter(tags=["metrics"])

BUCKETS = ("day", "week", "month", "quarter")

#: Response bound with cap honesty (truncated + total_matching served).
MAX_HISTORY_POINTS = 5_000

GROUPING_NOTE = (
    "Buckets group persisted figures by the calendar bucket their period "
    "starts in. The server never sums, averages, or otherwise derives a new "
    "number from grouped figures — every value is a calculation library "
    "figure served verbatim with its metric_value_id receipt. A true "
    "quarterly or annual rollup is a calculation library job, not this "
    "endpoint's."
)

_COUNT_VALUES = "SELECT count(*) FROM computed.metric_values"


class HistoryPoint(MetricValue):
    """A full metric-value row (verbatim, provenance-bearing) plus the
    simulated label the audience chart must render (mirror of the export
    surfaces' simulated flag — derived from detail.source_mix, a label,
    never a number)."""

    simulated: bool


class HistoryBucket(BaseModel):
    #: 'day' → '2026-07-14'; 'week' → ISO '2026-W29'; 'month' → '2026-07';
    #: 'quarter' → '2026-Q3'. Derived from each point's own period_start.
    bucket_key: str
    points: list[HistoryPoint]


class HistoryResponse(BaseModel):
    bucket: str
    #: Filters echoed exactly as applied (scope is the resolved value when
    #: ``mode`` was given).
    metric: Optional[str]
    scope: Optional[str]
    calc_version: Optional[str]
    period_from: Optional[dt.date]
    period_to: Optional[dt.date]
    buckets: list[HistoryBucket]
    point_count: int
    #: Rows matching the filters in the store (equals point_count unless
    #: truncated).
    total_matching: int
    cap: int = MAX_HISTORY_POINTS
    truncated: bool = False
    grouping_note: str = GROUPING_NOTE
    note: Optional[str] = None


def bucket_key_for(period_start: dt.date, bucket: str) -> str:
    """The calendar key a figure's period start falls in — a LABEL derived
    from the date, no arithmetic on any figure."""
    if bucket == "day":
        return period_start.isoformat()
    if bucket == "week":
        iso = period_start.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"
    if bucket == "month":
        return f"{period_start.year:04d}-{period_start.month:02d}"
    if bucket == "quarter":
        quarter = (period_start.month - 1) // 3 + 1
        return f"{period_start.year:04d}-Q{quarter}"
    raise ValueError(f"unknown bucket {bucket!r}")  # guarded by Query pattern


@router.get("/metrics/history", response_model=HistoryResponse)
def metric_history(
    metric: Optional[str] = Query(
        default=None, description="Filter to one metric, e.g. 'vrm' or 'upt'."
    ),
    mode: Optional[str] = Query(
        default=None,
        description=(
            "Convenience filter for per-mode figures: 'bus' selects scope "
            "'mode:bus'. Mutually exclusive with ``scope``."
        ),
    ),
    scope: Optional[str] = Query(
        default=None,
        description="Exact scope filter, e.g. 'agency' or 'mode:bus'.",
    ),
    calc_version: Optional[str] = Query(
        default=None, description="Filter to one calculation version."
    ),
    period_from: Optional[dt.date] = Query(
        default=None,
        alias="from",
        description="Only figures whose period starts on or after this date.",
    ),
    period_to: Optional[dt.date] = Query(
        default=None,
        alias="to",
        description="Only figures whose period ends on or before this date.",
    ),
    bucket: str = Query(
        default="month",
        pattern="^(day|week|month|quarter)$",
        description=(
            "Calendar grouping for the returned points (grouping only — "
            "never arithmetic; see grouping_note)."
        ),
    ),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> HistoryResponse:
    """The period-series read for audience views: persisted figures grouped
    by calendar bucket, each point receipt-linkable via metric_value_id and
    carrying its simulated + certification + ops-category labels. Ordering
    is stable (period_start, metric, scope, computed_at, metric_value_id);
    the response is bounded (cap + truncated + total_matching honesty)."""
    if mode is not None and scope is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Use either 'mode' (a shorthand for scope 'mode:<mode>') or "
                "'scope', not both — two scope filters at once would be "
                "ambiguous."
            ),
        )
    if mode is not None:
        scope = f"mode:{mode}"

    clauses: list[str] = []
    params: list[object] = []
    if metric is not None:
        clauses.append("metric = %s")
        params.append(metric)
    if scope is not None:
        clauses.append("scope = %s")
        params.append(scope)
    if calc_version is not None:
        clauses.append("calc_version = %s")
        params.append(calc_version)
    if period_from is not None:
        clauses.append("period_start >= %s")
        params.append(period_from)
    if period_to is not None:
        clauses.append("period_end <= %s")
        params.append(period_to)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        _SELECT_VALUES
        + where
        + " ORDER BY period_start, metric, scope, computed_at, metric_value_id"
        + " LIMIT %s"
    )
    rows = db.execute(sql, tuple(params) + (MAX_HISTORY_POINTS + 1,)).fetchall()
    truncated = len(rows) > MAX_HISTORY_POINTS
    if truncated:
        rows = rows[:MAX_HISTORY_POINTS]
        total_matching = db.execute(
            _COUNT_VALUES + where, tuple(params)
        ).fetchone()[0]
    else:
        total_matching = len(rows)

    buckets: dict[str, list[HistoryPoint]] = {}
    order: list[str] = []
    for r in rows:
        detail = _detail_as_dict(r[11])
        point = HistoryPoint(
            metric_value_id=str(r[0]),
            metric=r[1],
            unit=r[2],
            period_start=r[3],
            period_end=r[4],
            scope=r[5],
            value=str(r[6]) if isinstance(r[6], Decimal) else str(Decimal(str(r[6]))),
            calc_name=r[7],
            calc_version=r[8],
            computed_at=r[9],
            certification_status=r[10],
            detail=detail,
            category=r[12],
            simulated=is_simulated_detail(detail),
        )
        key = bucket_key_for(point.period_start, bucket)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(point)

    note = None
    if truncated:
        note = (
            f"More figures match these filters than one response serves: "
            f"showing the first {MAX_HISTORY_POINTS} of {total_matching} "
            f"by period start. Narrow the window (from/to) or the filters "
            f"to see the rest."
        )
    return HistoryResponse(
        bucket=bucket,
        metric=metric,
        scope=scope,
        calc_version=calc_version,
        period_from=period_from,
        period_to=period_to,
        buckets=[
            HistoryBucket(bucket_key=k, points=buckets[k]) for k in order
        ],
        point_count=sum(len(v) for v in buckets.values()),
        total_matching=total_matching,
        truncated=truncated,
        note=note,
    )
