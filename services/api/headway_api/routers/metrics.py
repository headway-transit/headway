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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from headway_calc import registry as calc_registry

from .. import exports
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


@router.get(
    "/metrics/values/export",
    response_class=Response,
    responses={
        200: {
            "description": (
                "The same rows GET /metrics/values serves, as a CSV or XLSX "
                "download. Figures are the exact served strings (XLSX cells "
                "are TEXT — never spreadsheet numbers); the preview "
                "disclaimer (and a simulated-data warning when any row is "
                "simulated) leads the CSV and forms the XLSX's first sheet."
            ),
            "content": {exports.CSV_MEDIA_TYPE: {}, exports.XLSX_MEDIA_TYPE: {}},
        }
    },
)
def export_metric_values(
    format: str = Query(default="xlsx", pattern=exports.FORMAT_PATTERN),
    metric: Optional[str] = Query(default=None),
    period_start: Optional[dt.date] = Query(default=None),
    period_end: Optional[dt.date] = Query(default=None),
    category: Optional[str] = Query(default=None, pattern="^(ntd|ops)$"),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> Response:
    """Download /metrics/values as CSV or XLSX (handoff 0017, design point
    5): ONE row assembly feeds both formats, so the XLSX values are
    byte-equal to the CSV values cell for cell (pinned by test)."""
    values = query_metric_values(db, metric, period_start, period_end, category)
    grid = exports.metrics_values_grid(values)
    stem_parts = ["headway-metric-values"]
    if metric:
        stem_parts.append(metric)
    if period_start:
        stem_parts.append(period_start.isoformat())
    if period_end:
        stem_parts.append(period_end.isoformat())
    return exports.export_response(grid, format, "-".join(stem_parts))


# ---------------------------------------------------------------------------
# GET /metrics/compare (handoff 0017, design point 1) — COMPOSITION ONLY.
#
# The endpoint composes query_metric_values (the one reader every metric read
# already goes through) once per comparand and picks each cell with the same
# latest-row discipline mr20.py pins (newest computed_at, metric_value_id as
# the deterministic tie-break). It never computes a figure. The ONLY
# arithmetic is the delta between two served figures — exact Decimal
# subtraction of the two persisted strings, serialized back to a string. A
# delta is a comparison affordance, not a reported figure: it is never
# persisted, never certifiable, and its exactness is pinned by test.
# ---------------------------------------------------------------------------

MIN_COMPARANDS = 2
MAX_COMPARANDS = 4

_COMPARAND_SYNTAX_HELP = (
    "Each comparand is '<period_start>..<period_end>' (ISO dates, the "
    "half-open period exactly as computed) optionally followed by "
    "'@<calc_name>:<calc_version>' to pin one calculation version — for "
    "example '2026-07-01..2026-08-01' or "
    "'2026-07-14..2026-07-16@dr_vrm_v0:0.1.1'. The first comparand is the "
    "baseline."
)

DELTA_NOTE = (
    "Deltas are comparison affordances, not reported figures: each is the "
    "exact decimal difference (this cell minus the baseline/previous cell) "
    "of two figures the calculation library persisted, computed without "
    "rounding and never stored anywhere. Every underlying figure is served "
    "verbatim in the cell's 'value' row with its full provenance."
)

MIXED_CERTIFICATION_NOTE = (
    "This comparison mixes certified and uncertified figures. Each cell "
    "carries its own certification_status — label both sides "
    "(handoff 0017, design point 1)."
)


class Comparand(BaseModel):
    """One comparison column, echoed back exactly as parsed."""

    key: str
    period_start: dt.date
    period_end: dt.date
    calc_name: Optional[str] = None
    calc_version: Optional[str] = None
    baseline: bool


class CompareCell(BaseModel):
    """One (scope, comparand) cell: the FULL metric-value row (verbatim —
    the receipt affordance needs metric_value_id, badges need detail/
    category/certification_status) or an explicit missing reason, plus the
    exact deltas."""

    comparand_index: int
    value: Optional[MetricValue] = None
    missing_reason: Optional[str] = None
    #: Exact signed Decimal difference vs the baseline / previous comparand
    #: cell in this row, as a string; null when either side is missing or
    #: for the baseline column itself.
    delta_vs_baseline: Optional[str] = None
    delta_vs_previous: Optional[str] = None


class CompareRow(BaseModel):
    scope: str
    cells: list[CompareCell]


class CompareResponse(BaseModel):
    metric: str
    #: The unit shared by every present cell — null when no cell is present.
    #: (A single metric name always carries one unit end to end.)
    unit: Optional[str]
    comparands: list[Comparand]
    scopes: list[str]
    rows: list[CompareRow]
    #: Direction metadata from the CALC LIBRARY's metric registry (handoff
    #: 0017: registry, not per-view; coverage only to start): the requested
    #: metric's direction (null = sign-neutral) plus 'coverage', which the
    #: vrm/vrh cell details carry.
    directions: dict[str, Optional[str]]
    direction_note: str
    delta_note: str
    #: True when present cells mix certified and uncertified figures — the
    #: UI must label both (design point 1). Derivable per cell; surfaced so
    #: no consumer can miss it.
    mixed_certification: bool
    mixed_certification_note: Optional[str]


def _parse_comparand(raw: str, index: int) -> Comparand:
    def bad(problem: str) -> HTTPException:
        return HTTPException(
            status_code=422,
            detail=(
                f"Comparand {index + 1} ('{raw}') {problem}. "
                + _COMPARAND_SYNTAX_HELP
            ),
        )

    period_part, at, calc_part = raw.partition("@")
    start_s, dots, end_s = period_part.partition("..")
    if not dots:
        raise bad("has no '..' between its two period dates")
    try:
        period_start = dt.date.fromisoformat(start_s)
        period_end = dt.date.fromisoformat(end_s)
    except ValueError:
        raise bad("does not have two ISO dates (YYYY-MM-DD)")
    if period_end <= period_start:
        raise bad(
            "has period_end on or before period_start — periods are "
            "half-open [start, end), so the end must come after the start"
        )
    calc_name: Optional[str] = None
    calc_version: Optional[str] = None
    if at:
        calc_name, colon, calc_version = calc_part.rpartition(":")
        if not colon or not calc_name or not calc_version:
            raise bad(
                "pins a calculation without the '<calc_name>:<calc_version>' "
                "form after '@'"
            )
    return Comparand(
        key=raw,
        period_start=period_start,
        period_end=period_end,
        calc_name=calc_name,
        calc_version=calc_version,
        baseline=index == 0,
    )


def _latest_cell_value(
    values: list[MetricValue], comparand: Comparand, scope: str
) -> Optional[MetricValue]:
    """The one row a cell shows: exact-period rows for the scope (and the
    pinned calc, if any), newest computed_at first, metric_value_id as the
    deterministic tie-break — the mr20.py latest-row discipline. Earlier
    rows remain append-only history."""
    candidates = [
        v
        for v in values
        if v.scope == scope
        and v.period_start == comparand.period_start
        and v.period_end == comparand.period_end
        and (comparand.calc_name is None or v.calc_name == comparand.calc_name)
        and (
            comparand.calc_version is None
            or v.calc_version == comparand.calc_version
        )
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda v: (v.computed_at, v.metric_value_id))


def _missing_reason(metric: str, comparand: Comparand, scope: str) -> str:
    pinned = (
        f" by {comparand.calc_name} {comparand.calc_version}"
        if comparand.calc_name is not None
        else ""
    )
    return (
        f"No {metric} figure exists for scope '{scope}' computed{pinned} for "
        f"the period [{comparand.period_start.isoformat()}, "
        f"{comparand.period_end.isoformat()}). A missing figure is shown as "
        f"missing, never invented."
    )


def _exact_delta(a: Optional[MetricValue], b: Optional[MetricValue]) -> Optional[str]:
    """Exact Decimal difference a - b of two served figures, or None when
    either side is missing. No rounding, no float."""
    if a is None or b is None:
        return None
    return str(Decimal(a.value) - Decimal(b.value))


@router.get("/metrics/compare", response_model=CompareResponse)
def compare_metric_values(
    metric: str = Query(..., description="The metric to compare, e.g. 'vrh'."),
    comparand: list[str] = Query(
        ...,
        description=(
            f"{MIN_COMPARANDS}–{MAX_COMPARANDS} comparison columns; repeat "
            f"the parameter. {_COMPARAND_SYNTAX_HELP}"
        ),
    ),
    scope: Optional[list[str]] = Query(
        default=None,
        description=(
            "Row scopes (repeat the parameter), e.g. 'agency' and "
            "'mode:bus'. Omit to include every scope that has at least one "
            "figure in any comparand ('agency' first, the rest sorted)."
        ),
    ),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> CompareResponse:
    """Compare one metric across 2–4 comparands (calc versions of the same
    figure, or periods) per scope. Serves the calc library's persisted rows
    VERBATIM (composition of the same reader as GET /metrics/values — this
    endpoint never computes a figure) plus exact-decimal deltas as
    comparison affordances; direction metadata comes from the calc
    library's metric registry (coverage only today)."""
    if not (MIN_COMPARANDS <= len(comparand) <= MAX_COMPARANDS):
        raise HTTPException(
            status_code=422,
            detail=(
                f"A comparison needs between {MIN_COMPARANDS} and "
                f"{MAX_COMPARANDS} comparands; you sent {len(comparand)}. "
                + _COMPARAND_SYNTAX_HELP
            ),
        )
    comparands = [_parse_comparand(raw, i) for i, raw in enumerate(comparand)]
    if len({c.key for c in comparands}) != len(comparands):
        raise HTTPException(
            status_code=422,
            detail=(
                "Two comparands are identical — every comparison column "
                "must differ (a different period, or a different pinned "
                "calculation version)."
            ),
        )

    # Composition: ONE query_metric_values call per comparand — the same
    # reader, same filters, same shape as GET /metrics/values. The exact-
    # period/scope/calc pick happens here in the open, not in new SQL.
    values_by_comparand: list[list[MetricValue]] = [
        query_metric_values(db, metric, c.period_start, c.period_end, None)
        for c in comparands
    ]

    if scope:
        scopes = list(dict.fromkeys(scope))  # de-dupe, preserve order
    else:
        present = {v.scope for values in values_by_comparand for v in values}
        scopes = (["agency"] if "agency" in present else []) + sorted(
            present - {"agency"}
        )

    rows: list[CompareRow] = []
    unit: Optional[str] = None
    statuses: set[str] = set()
    for row_scope in scopes:
        cell_values: list[Optional[MetricValue]] = [
            _latest_cell_value(values_by_comparand[i], c, row_scope)
            for i, c in enumerate(comparands)
        ]
        cells: list[CompareCell] = []
        for i, (c, v) in enumerate(zip(comparands, cell_values)):
            if v is not None:
                unit = unit if unit is not None else v.unit
                statuses.add(v.certification_status)
            cells.append(
                CompareCell(
                    comparand_index=i,
                    value=v,
                    missing_reason=(
                        None if v is not None else _missing_reason(metric, c, row_scope)
                    ),
                    delta_vs_baseline=(
                        None if i == 0 else _exact_delta(v, cell_values[0])
                    ),
                    delta_vs_previous=(
                        None if i == 0 else _exact_delta(v, cell_values[i - 1])
                    ),
                )
            )
        rows.append(CompareRow(scope=row_scope, cells=cells))

    mixed = "certified" in statuses and len(statuses) > 1
    return CompareResponse(
        metric=metric,
        unit=unit,
        comparands=comparands,
        scopes=scopes,
        rows=rows,
        directions={
            metric: calc_registry.direction_for(metric),
            "coverage": calc_registry.direction_for("coverage"),
        },
        direction_note=calc_registry.DIRECTION_NOTE,
        delta_note=DELTA_NOTE,
        mixed_certification=mixed,
        mixed_certification_note=MIXED_CERTIFICATION_NOTE if mixed else None,
    )


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
