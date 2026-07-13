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
    SCOPE_READ_METRICS,
    MachineIdentity,
    enforce_rate_limit,
    require_machine_scope,
)
from .metrics import MetricValue, query_metric_values

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
