"""Open data: certified figures, unauthenticated (handoff 0006, point 8).

This is the transparency-view mandate in its minimal form, and the ONE
deliberate exception to "no unauthenticated endpoint" — approved by the
Security Engineer's binding design (handoff 0006, design point 8), not a
convenience. What keeps it safe:

- It serves ONLY rows with certification_status = 'certified' — figures a
  certifying official has already legally attested for public reporting.
- Values are strings (NUMERIC precision) and ``detail`` is served VERBATIM,
  including any simulated-data flags: transparency shows the flags, it never
  hides the figures.
- There is NO PII surface: aggregate metric values, units, periods, and calc
  identity only. Even the certifier's name is not served here — it lives in
  the authenticated certification record.
- Rate-limited per client IP (the same in-process token bucket as machine
  keys, with the same documented single-instance limitation).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..db import get_db
from ..machine_auth import enforce_rate_limit
from .metrics import _detail_as_dict

router = APIRouter(tags=["public"])


class PublicMetricValue(BaseModel):
    """A certified figure, publishable form. No PII, no certifier identity."""

    metric_value_id: str
    metric: str
    unit: str
    period_start: dt.date
    period_end: dt.date
    scope: str
    value: str  # NUMERIC as a string — floating point never touches a figure
    calc_name: str
    calc_version: str
    computed_at: dt.datetime
    certification_status: str  # always 'certified' here
    detail: dict[str, Any] = {}  # served verbatim, simulated flags included
    # Always 'ntd' here: OPERATIONS figures (category 'ops', handoff 0014 /
    # migration 0024) are structurally uncertifiable AND hard-excluded by
    # this router's WHERE clause — they can never be published as certified
    # open data. Served so the payload states its own category.
    category: str = "ntd"


_SELECT_CERTIFIED = (
    "SELECT metric_value_id, metric, unit, period_start, period_end, scope, "
    "value, calc_name, calc_version, computed_at, certification_status, "
    "detail, category FROM computed.metric_values "
    "WHERE certification_status = 'certified' "
    # The migration-0024 honesty boundary, hard-clause form: an OPERATIONS
    # figure must never surface here even if the ops-never-certified CHECK
    # were somehow bypassed — defense in depth, both layers tested.
    "AND category = 'ntd' "
    "ORDER BY period_start, metric"
)


@router.get("/public/metrics/certified", response_model=list[PublicMetricValue])
def list_certified_values(request: Request) -> list[PublicMetricValue]:
    # UNAUTHENTICATED by design (see module docstring) — so no identity
    # dependency, and the only per-caller control is the IP token bucket.
    client_ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(request.app.state.public_rate_limiter, client_ip)
    db = get_db(request)
    rows = db.execute(_SELECT_CERTIFIED, ()).fetchall()
    return [
        PublicMetricValue(
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
            detail=_detail_as_dict(r[11]),
            category=r[12],
        )
        for r in rows
    ]
