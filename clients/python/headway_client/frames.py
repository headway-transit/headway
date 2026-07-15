"""DataFrame helpers — provenance columns are ALWAYS present.

Explore and compute freely: nothing computed outside Headway's calculation
library (services/calc) can ever become a reported figure. Only the
calculation library writes computed.metric_values, and the walls are
structural database CHECKs, not policy.

The rule these helpers enforce (handoff 0018, binding): every metric-value
frame carries the provenance columns — ``metric_value_id``, ``calc_name``,
``calc_version``, ``category``, ``certification_status``, ``simulated``,
``source_mix`` — with no kwarg to omit them. Dropping provenance is the
caller's explicit act (``df.drop(columns=...)``), never this library's
default. A number that cannot say where it came from is not a Headway
number.

Figures stay exact: the ``value`` column (and the compare frames' delta
columns) holds :class:`decimal.Decimal` objects parsed from the API's
decimal strings — object dtype, deliberately, because float64 would
corrupt reported figures. Decimal columns sum/subtract exactly; convert to
float yourself only for plotting, knowing what you give up.

pandas is an optional extra: ``pip install headway-client[pandas]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Union

from .models import CompareResponse, DqIssue, LineageTrail, MetricValue

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd


def _pandas():
    try:
        import pandas
    except ImportError as exc:  # pragma: no cover - exercised via message test
        raise ImportError(
            "The DataFrame helpers need pandas, which is an optional extra "
            "of headway-client. Install it with: "
            "pip install 'headway-client[pandas]'"
        ) from exc
    return pandas


#: The always-present provenance columns of every metric-value frame.
PROVENANCE_COLUMNS = (
    "metric_value_id",
    "calc_name",
    "calc_version",
    "category",
    "certification_status",
    "simulated",
    "source_mix",
)


def metric_values_frame(values: Iterable[MetricValue]) -> "pd.DataFrame":
    """One row per computed figure, provenance columns always included.

    ``value`` holds exact Decimals; ``simulated`` is the repo-wide
    simulated-data rule over ``detail.source_mix``; ``detail`` rides along
    verbatim so nothing the calc library said about its own run is lost.
    """
    pd = _pandas()
    rows = [
        {
            "metric": v.metric,
            "period_start": v.period_start,
            "period_end": v.period_end,
            "scope": v.scope,
            "value": v.value_decimal,
            "unit": v.unit,
            "metric_value_id": v.metric_value_id,
            "calc_name": v.calc_name,
            "calc_version": v.calc_version,
            "category": v.category,
            "certification_status": v.certification_status,
            "simulated": v.simulated,
            "source_mix": v.source_mix,
            "computed_at": v.computed_at,
            "detail": v.detail,
        }
        for v in values
    ]
    columns = [
        "metric", "period_start", "period_end", "scope", "value", "unit",
        *PROVENANCE_COLUMNS, "computed_at", "detail",
    ]
    # dict.fromkeys de-dupes while preserving order (PROVENANCE_COLUMNS
    # already contains metric_value_id et al. exactly once here).
    columns = list(dict.fromkeys(columns))
    return pd.DataFrame(rows, columns=columns)


def dq_issues_frame(issues: Iterable[DqIssue]) -> "pd.DataFrame":
    """One row per data-quality issue. ``resolution_minutes`` stays a
    nullable integer — an unmeasured effort is missing, never zero."""
    pd = _pandas()
    rows = [
        {
            "issue_id": i.issue_id,
            "issue_type": i.issue_type,
            "severity": i.severity,
            "status": i.status,
            "owner": i.owner,
            "title": i.title,
            "description": i.description,
            "source_record_ids": i.source_record_ids,
            "created_at": i.created_at,
            "resolved_at": i.resolved_at,
            "resolution": i.resolution,
            "resolution_minutes": i.resolution_minutes,
        }
        for i in issues
    ]
    frame = pd.DataFrame(
        rows,
        columns=[
            "issue_id", "issue_type", "severity", "status", "owner", "title",
            "description", "source_record_ids", "created_at", "resolved_at",
            "resolution", "resolution_minutes",
        ],
    )
    # Nullable integer, not float: 12 minutes must never become 12.0, and a
    # missing measurement must stay <NA>, not NaN-as-float.
    frame["resolution_minutes"] = frame["resolution_minutes"].astype("Int64")
    return frame


def lineage_frame(trail: Union[LineageTrail, "MetricValue"]) -> "pd.DataFrame":
    """The flattened "explain this number" trail: one row per lineage node,
    depth-first, with its parent — from the figure (depth 0) down to the
    content-addressed raw records at the leaves."""
    pd = _pandas()
    if not isinstance(trail, LineageTrail):
        raise TypeError(
            "lineage_frame expects a LineageTrail (from "
            "HeadwayClient.walk_lineage); got "
            f"{type(trail).__name__}. For a figure, walk its lineage first."
        )
    rows = [
        {
            "depth": depth,
            "kind": node.kind,
            "id": node.id,
            "transform_name": node.transform_name,
            "transform_version": node.transform_version,
            "parent_kind": parent.kind if parent else None,
            "parent_id": parent.id if parent else None,
        }
        for depth, parent, node in trail.nodes()
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "depth", "kind", "id", "transform_name", "transform_version",
            "parent_kind", "parent_id",
        ],
    )


def compare_frame(response: CompareResponse) -> "pd.DataFrame":
    """One row per (scope, comparand) cell of a comparison, provenance
    columns always included for present cells. Missing cells keep their
    plain-language ``missing_reason`` — a missing figure is shown as
    missing, never invented. Deltas are exact Decimals (comparison
    affordances, never reported figures)."""
    pd = _pandas()
    rows = []
    for row in response.rows:
        for cell in row.cells:
            v = cell.value
            rows.append(
                {
                    "scope": row.scope,
                    "comparand": response.comparands[cell.comparand_index].key,
                    "baseline": response.comparands[cell.comparand_index].baseline,
                    "value": v.value_decimal if v else None,
                    "unit": v.unit if v else None,
                    "delta_vs_baseline": cell.delta_vs_baseline_decimal,
                    "delta_vs_previous": cell.delta_vs_previous_decimal,
                    "missing_reason": cell.missing_reason,
                    "metric_value_id": v.metric_value_id if v else None,
                    "calc_name": v.calc_name if v else None,
                    "calc_version": v.calc_version if v else None,
                    "category": v.category if v else None,
                    "certification_status": v.certification_status if v else None,
                    "simulated": v.simulated if v else None,
                    "source_mix": v.source_mix if v else None,
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "scope", "comparand", "baseline", "value", "unit",
            "delta_vs_baseline", "delta_vs_previous", "missing_reason",
            *PROVENANCE_COLUMNS,
        ],
    )
