"""Read endpoints for computed values + the "explain this number" traversal.

This router never computes, rounds, adjusts, or defaults a figure. It serves
exactly what the calc library wrote to computed.metric_values, and ``value``
is serialized as a STRING so NUMERIC precision survives JSON (never float).
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ..audit import write_event
from ..auth import Identity
from ..authz import require_authenticated
from ..db import get_db
from ..machine_auth import (
    SCOPE_READ_METRICS,
    MachineIdentity,
    require_human_session_or_machine_scope,
)

router = APIRouter(tags=["metrics"])


class MetricValue(BaseModel):
    metric_value_id: str
    metric: str
    unit: str
    period_start: dt.date
    period_end: dt.date
    scope: str
    # A reported figure is NUMERIC in the database and a string in JSON;
    # floating point never touches it.
    value: str
    calc_name: str
    calc_version: str
    computed_at: dt.datetime
    certification_status: str
    # Per-value calculation detail (computed.metric_values.detail, JSONB,
    # migration 0010), served VERBATIM as the calc library persisted it:
    # coverage details for vrm/vrh (CoverageDetail and descendants), UPT
    # detail (UptDetail) — see services/calc/headway_calc/types.py to_dict.
    # Ratios/factors inside are STRINGS for the same reason ``value`` is.
    # ``{}`` for detail-less rows (the column default). Additive field —
    # documented in handoff 0001's wave-8 response section.
    detail: dict[str, Any] = {}
    # THE HONESTY BOUNDARY (handoff 0014 / migration 0024): 'ntd' for
    # regulatory-pipeline figures, 'ops' for OPERATIONS metrics (otp,
    # headway_adherence). The UI MUST render category='ops' figures visibly
    # distinct — "Operations metric — not an NTD reported figure" — and the
    # certifiable surfaces (certification, MR-20/S&S, the public certified
    # endpoint) structurally exclude them.
    category: str


class LineageNode(BaseModel):
    """One node of the provenance tree.

    ``transform_name``/``transform_version`` describe the transform that
    PRODUCED this node from its ``inputs`` (per lineage.edges). Raw records
    are leaves: no transform, no inputs.
    """

    kind: str
    id: str
    transform_name: Optional[str] = None
    transform_version: Optional[str] = None
    inputs: list["LineageNode"] = []


LineageNode.model_rebuild()

_SELECT_VALUES = (
    "SELECT metric_value_id, metric, unit, period_start, period_end, scope, "
    "value, calc_name, calc_version, computed_at, certification_status, "
    "detail, category "
    "FROM computed.metric_values"
)


def _detail_as_dict(raw: object) -> dict[str, Any]:
    """JSONB comes back as a dict from psycopg; tolerate drivers that hand
    back the JSON text instead. NULL (pre-0010 rows) serves as {} — the
    column default — never invented content."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


def query_metric_values(
    db,
    metric: Optional[str],
    period_start: Optional[dt.date],
    period_end: Optional[dt.date],
    category: Optional[str] = None,
) -> list[MetricValue]:
    """The one query behind every metric-values read (human, machine): same
    filters, same shape, value as a Decimal-exact string, detail verbatim.
    Shared so the machine endpoint can never drift from the human one.
    ``category`` filters on the migration-0024 honesty boundary ('ntd' |
    'ops'); every returned row carries its category either way."""
    clauses: list[str] = []
    params: list[object] = []
    if metric is not None:
        clauses.append("metric = %s")
        params.append(metric)
    if period_start is not None:
        clauses.append("period_start >= %s")
        params.append(period_start)
    if period_end is not None:
        clauses.append("period_end <= %s")
        params.append(period_end)
    if category is not None:
        clauses.append("category = %s")
        params.append(category)
    sql = _SELECT_VALUES
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY period_start, metric"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [
        MetricValue(
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


@router.get("/metrics/values", response_model=list[MetricValue])
def list_metric_values(
    metric: Optional[str] = Query(default=None, description="e.g. 'vrm' or 'vrh'"),
    period_start: Optional[dt.date] = Query(default=None),
    period_end: Optional[dt.date] = Query(default=None),
    category: Optional[str] = Query(
        default=None,
        pattern="^(ntd|ops)$",
        description=(
            "Filter on the honesty boundary (migration 0024): 'ntd' for "
            "regulatory-pipeline figures, 'ops' for operations metrics "
            "(on-time performance, headway adherence — never certifiable, "
            "never NTD-reported). Every row carries its category either "
            "way, so the UI can badge operations figures."
        ),
    ),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[MetricValue]:
    return query_metric_values(db, metric, period_start, period_end, category)


# Recursive CTE: walk lineage.edges downward from the metric value until the
# graph bottoms out (raw.records rows have no further edges). Depth-capped as
# a cycle guard — a lineage graph deeper than 64 hops is a pipeline defect and
# should surface, not spin.
_LINEAGE_CTE = (
    "WITH RECURSIVE walk AS ("
    " SELECT output_kind, output_id, transform_name, transform_version,"
    "        input_kind, input_id, 1 AS depth"
    " FROM lineage.edges"
    " WHERE output_kind = 'computed.metric_values' AND output_id = %s"
    " UNION ALL"
    " SELECT e.output_kind, e.output_id, e.transform_name, e.transform_version,"
    "        e.input_kind, e.input_id, w.depth + 1"
    " FROM lineage.edges e"
    " JOIN walk w ON e.output_kind = w.input_kind AND e.output_id = w.input_id"
    " WHERE w.depth < 64"
    ") "
    "SELECT output_kind, output_id, transform_name, transform_version,"
    " input_kind, input_id FROM walk"
)

_SELECT_VALUE_EXISTS = (
    "SELECT metric_value_id FROM computed.metric_values WHERE metric_value_id = %s"
)


@router.get(
    "/metrics/values/{metric_value_id}/lineage", response_model=LineageNode
)
def explain_metric_value(
    metric_value_id: str,
    request: Request,
    identity: Identity | MachineIdentity = Depends(
        require_human_session_or_machine_scope(SCOPE_READ_METRICS)
    ),
    db=Depends(get_db),
) -> LineageNode:
    """"Explain this number": the full provenance tree from the reported
    figure down to the raw records that produced it (ADR-0007).

    Dual credential (handoff 0006 follow-up): a signed-in human session OR a
    ``read:metrics`` machine key. The machine path is rate-limited per key
    and audited with actor ``key:<key_prefix>``; the human path is unchanged.
    """
    exists = db.execute(_SELECT_VALUE_EXISTS, (metric_value_id,)).fetchone()
    if exists is None:
        raise HTTPException(
            status_code=404,
            detail="No reported figure with that id exists.",
        )
    edges = db.execute(_LINEAGE_CTE, (metric_value_id,)).fetchall()
    if not edges:
        # Fail loudly: a figure with no lineage is a pipeline defect, not an
        # empty-200. An unexplained number must never look fine.
        raise HTTPException(
            status_code=500,
            detail=(
                "This figure has no recorded lineage, so Headway cannot "
                "explain where it came from. This is a data pipeline problem "
                "that must be fixed before the figure is trusted."
            ),
        )
    edges_by_output: dict[tuple[str, str], list[tuple]] = {}
    for e in edges:
        edges_by_output.setdefault((e[0], str(e[1])), []).append(e)

    def build(kind: str, node_id: str, path: frozenset) -> LineageNode:
        key = (kind, node_id)
        producing = edges_by_output.get(key, [])
        transform_name = producing[0][2] if producing else None
        transform_version = producing[0][3] if producing else None
        inputs = []
        for e in producing:
            child_key = (e[4], str(e[5]))
            if child_key in path:
                # A cycle in the lineage graph is a defect; surface it loudly.
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "The lineage graph for this figure contains a loop, "
                        "which should be impossible. This is a data pipeline "
                        "problem that needs attention."
                    ),
                )
            inputs.append(build(child_key[0], child_key[1], path | {key}))
        return LineageNode(
            kind=kind,
            id=node_id,
            transform_name=transform_name,
            transform_version=transform_version,
            inputs=inputs,
        )

    tree = build("computed.metric_values", str(metric_value_id), frozenset())
    if isinstance(identity, MachineIdentity):
        # Successful key use is audited at endpoint level, actor key:<prefix>
        # (handoff 0006, design point 4) — the id only, never the figures.
        # The human path is unchanged: no per-read audit, like every other
        # signed-in GET.
        with db.transaction():
            write_event(
                db,
                actor=identity.actor,
                action="machine_read_lineage",
                subject_kind="computed.metric_values",
                subject_id=str(metric_value_id),
                detail={"path": request.url.path},
            )
    return tree
