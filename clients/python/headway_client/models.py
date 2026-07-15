"""Typed models mirroring the Headway API contracts (services/api/openapi.json).

Explore and compute freely: nothing computed outside Headway's calculation
library (services/calc) can ever become a reported figure. Only the
calculation library writes computed.metric_values, and the walls are
structural database CHECKs, not policy.

Modeling rules, inherited from the platform's non-negotiables:

- A figure's ``value`` (and every delta) is kept as the exact decimal
  STRING the API served — NUMERIC in the database, string in JSON, string
  here. ``value_decimal`` parses it with :class:`decimal.Decimal`; binary
  floating point never touches a reported value.
- ``detail`` is carried VERBATIM as the calc library persisted it (ratios
  and thresholds inside are strings for the same reason).
- Nothing is coalesced: a missing comparison cell stays ``None`` with its
  ``missing_reason``; an unmeasured ``resolution_minutes`` stays ``None``.
- ``simulated`` implements the repo-wide simulated-data rule exactly as the
  web UI does (web/src/detail.ts isSimulated): True when
  ``detail.source_mix`` names any source containing "simulated".
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional


def _date(raw: str) -> _dt.date:
    return _dt.date.fromisoformat(raw)


def _datetime(raw: str) -> _dt.datetime:
    # The API serializes timestamps as ISO-8601 with a Z/offset suffix.
    return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))


@dataclass(frozen=True)
class MetricValue:
    """One computed figure, exactly as ``computed.metric_values`` holds it.

    Provenance is not an add-on: ``metric_value_id`` (the input to the
    lineage walk), ``calc_name``/``calc_version`` (the versioned calculation
    that produced the figure), ``category`` (the migration-0024 honesty
    boundary: 'ntd' regulatory figures vs 'ops' operations metrics, which
    are never certifiable), ``certification_status``, and the simulated-data
    flag derived from ``detail.source_mix`` are all first-class fields.
    """

    metric_value_id: str
    metric: str
    unit: str
    period_start: _dt.date
    period_end: _dt.date
    scope: str
    #: The figure, VERBATIM as served — an exact decimal string, never float.
    value: str
    calc_name: str
    calc_version: str
    computed_at: _dt.datetime
    certification_status: str
    #: 'ntd' or 'ops' — the honesty boundary. An 'ops' figure is an
    #: operations metric, never certifiable, never an NTD reported figure.
    category: str
    #: Per-figure calculation detail, VERBATIM as the calc library persisted
    #: it (coverage, missing-trip accounting, refusal counts, source_mix…).
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def value_decimal(self) -> Decimal:
        """The figure as an exact :class:`~decimal.Decimal` (never float)."""
        return Decimal(self.value)

    @property
    def source_mix(self) -> Optional[dict[str, int]]:
        """``detail.source_mix`` (record counts per envelope source), or
        ``None`` when this figure's detail does not carry one."""
        mix = self.detail.get("source_mix")
        return mix if isinstance(mix, dict) else None

    @property
    def simulated(self) -> bool:
        """The repo-wide simulated-data rule (handoff 0005), matching the
        web UI's isSimulated exactly: True when ``detail.source_mix`` names
        any source containing "simulated". Such a figure must never be
        submitted, and every surface marks it."""
        mix = self.source_mix
        if mix is None:
            return False
        return any("simulated" in source.lower() for source in mix)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "MetricValue":
        return cls(
            metric_value_id=raw["metric_value_id"],
            metric=raw["metric"],
            unit=raw["unit"],
            period_start=_date(raw["period_start"]),
            period_end=_date(raw["period_end"]),
            scope=raw["scope"],
            value=raw["value"],
            calc_name=raw["calc_name"],
            calc_version=raw["calc_version"],
            computed_at=_datetime(raw["computed_at"]),
            certification_status=raw["certification_status"],
            category=raw["category"],
            detail=raw.get("detail") or {},
        )


@dataclass(frozen=True)
class LineageNode:
    """One node of the provenance tree behind a figure.

    ``transform_name``/``transform_version`` describe the transform that
    PRODUCED this node from its ``inputs`` (per lineage.edges). Raw records
    are leaves: no transform, no inputs.
    """

    kind: str
    id: str
    transform_name: Optional[str] = None
    transform_version: Optional[str] = None
    inputs: tuple["LineageNode", ...] = ()

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "LineageNode":
        return cls(
            kind=raw["kind"],
            id=raw["id"],
            transform_name=raw.get("transform_name"),
            transform_version=raw.get("transform_version"),
            inputs=tuple(
                LineageNode.from_json(child) for child in raw.get("inputs", [])
            ),
        )


@dataclass(frozen=True)
class LineageTrail:
    """The full "explain this number" trail for one metric value.

    ``root`` is the figure's node; walking ``inputs`` bottoms out at the
    content-addressed raw records the figure was computed from. ``nodes()``
    flattens the tree depth-first with (depth, parent, node) so the whole
    trail can be listed or framed; ``raw_record_ids()`` collects the leaf
    raw-record ids in first-encountered order.
    """

    root: LineageNode

    def nodes(
        self,
    ) -> list[tuple[int, Optional[LineageNode], LineageNode]]:
        """Depth-first (depth, parent, node) triples, root first."""
        out: list[tuple[int, Optional[LineageNode], LineageNode]] = []

        def visit(
            node: LineageNode, parent: Optional[LineageNode], depth: int
        ) -> None:
            out.append((depth, parent, node))
            for child in node.inputs:
                visit(child, node, depth + 1)

        visit(self.root, None, 0)
        return out

    def raw_record_ids(self) -> list[str]:
        """Unique raw.records ids in the trail, first-encountered order —
        the immutable, content-addressed records this figure came from."""
        seen: dict[str, None] = {}
        for _, _, node in self.nodes():
            if node.kind == "raw.records":
                seen.setdefault(node.id)
        return list(seen)


@dataclass(frozen=True)
class DqIssue:
    """One data-quality issue: a surfaced gap, conflict, or validation
    failure with a type, severity, owner, and resolution workflow state.
    Nothing here is ever coalesced — an unmeasured ``resolution_minutes``
    is ``None``, never zero."""

    issue_id: str
    issue_type: str
    severity: str
    status: str
    owner: Optional[str]
    title: str
    description: str
    source_record_ids: Optional[list[str]]
    created_at: _dt.datetime
    resolved_at: Optional[_dt.datetime]
    resolution: Optional[str]
    resolution_minutes: Optional[int]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "DqIssue":
        return cls(
            issue_id=raw["issue_id"],
            issue_type=raw["issue_type"],
            severity=raw["severity"],
            status=raw["status"],
            owner=raw.get("owner"),
            title=raw["title"],
            description=raw["description"],
            source_record_ids=raw.get("source_record_ids"),
            created_at=_datetime(raw["created_at"]),
            resolved_at=(
                _datetime(raw["resolved_at"]) if raw.get("resolved_at") else None
            ),
            resolution=raw.get("resolution"),
            resolution_minutes=raw.get("resolution_minutes"),
        )


@dataclass(frozen=True)
class DqIssueCounts:
    """Severity/status counts over exactly the rows ``dq_issues`` serves
    under the same filter — a summary can never disagree with the table."""

    total: int
    by_severity: dict[str, int]
    by_status: dict[str, int]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "DqIssueCounts":
        return cls(
            total=raw["total"],
            by_severity=dict(raw["by_severity"]),
            by_status=dict(raw["by_status"]),
        )


@dataclass(frozen=True)
class Comparand:
    """One comparison column, echoed back exactly as the API parsed it."""

    key: str
    period_start: _dt.date
    period_end: _dt.date
    calc_name: Optional[str]
    calc_version: Optional[str]
    baseline: bool

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Comparand":
        return cls(
            key=raw["key"],
            period_start=_date(raw["period_start"]),
            period_end=_date(raw["period_end"]),
            calc_name=raw.get("calc_name"),
            calc_version=raw.get("calc_version"),
            baseline=raw["baseline"],
        )


@dataclass(frozen=True)
class CompareCell:
    """One (scope, comparand) cell: the FULL metric-value row (verbatim,
    provenance included) or an explicit ``missing_reason`` — a missing
    figure is shown as missing, never invented. Deltas are the API's exact
    decimal strings; they are comparison affordances, never reported
    figures (never persisted, never certifiable)."""

    comparand_index: int
    value: Optional[MetricValue]
    missing_reason: Optional[str]
    delta_vs_baseline: Optional[str]
    delta_vs_previous: Optional[str]

    @property
    def delta_vs_baseline_decimal(self) -> Optional[Decimal]:
        return None if self.delta_vs_baseline is None else Decimal(self.delta_vs_baseline)

    @property
    def delta_vs_previous_decimal(self) -> Optional[Decimal]:
        return None if self.delta_vs_previous is None else Decimal(self.delta_vs_previous)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "CompareCell":
        return cls(
            comparand_index=raw["comparand_index"],
            value=(
                MetricValue.from_json(raw["value"])
                if raw.get("value") is not None
                else None
            ),
            missing_reason=raw.get("missing_reason"),
            delta_vs_baseline=raw.get("delta_vs_baseline"),
            delta_vs_previous=raw.get("delta_vs_previous"),
        )


@dataclass(frozen=True)
class CompareRow:
    scope: str
    cells: tuple[CompareCell, ...]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "CompareRow":
        return cls(
            scope=raw["scope"],
            cells=tuple(CompareCell.from_json(c) for c in raw["cells"]),
        )


@dataclass(frozen=True)
class CompareResponse:
    """GET /metrics/compare, verbatim: one metric across 2–4 comparands per
    scope. The API never computes a figure here — every cell is a persisted
    calc-library row, and the deltas are exact decimal differences of two
    served figures."""

    metric: str
    unit: Optional[str]
    comparands: tuple[Comparand, ...]
    scopes: tuple[str, ...]
    rows: tuple[CompareRow, ...]
    directions: dict[str, Optional[str]]
    direction_note: str
    delta_note: str
    mixed_certification: bool
    mixed_certification_note: Optional[str]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "CompareResponse":
        return cls(
            metric=raw["metric"],
            unit=raw.get("unit"),
            comparands=tuple(Comparand.from_json(c) for c in raw["comparands"]),
            scopes=tuple(raw["scopes"]),
            rows=tuple(CompareRow.from_json(r) for r in raw["rows"]),
            directions=dict(raw["directions"]),
            direction_note=raw["direction_note"],
            delta_note=raw["delta_note"],
            mixed_certification=raw["mixed_certification"],
            mixed_certification_note=raw.get("mixed_certification_note"),
        )
