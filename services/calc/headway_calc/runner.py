"""run_period — closes the canonical→computed loop for one reporting period.

Orchestration only: load canonical.vehicle_positions (headway_calc.reader),
run the v0 calculations (compute_vrm, compute_vrh — the 0.2.0 default path,
handoff 0002), route EVERY finding to dq.issues with its own severity
(headway_calc.dq: warnings stay warnings, blocking stays blocking), then
persist each result that carries NO blocking findings (headway_calc.persist —
value + coverage detail + lineage edges; warnings persist alongside as the
already-routed dq rows). The guardrail is structural: a result with blocking
issues NEVER reaches persist_result — no certifiable value is ever emitted
over an unresolved gap, and a sub-coverage-threshold run persists nothing.

Transaction design — TWO transactions, fail-loudly-first
--------------------------------------------------------
1. **Issues first, committed first.** All dq.issues rows for the run
   (warnings AND blocking) are inserted and committed in their own
   transaction BEFORE any metric value is written. Evidence of a data problem
   must never be lost: if the value phase later fails (constraint violation,
   connection drop, bug), the findings are already durable — an operator
   investigating the failed run sees WHY the figures are blocked (or which
   groups were excluded) instead of an empty table.
2. **Values second.** computed.metric_values + lineage.edges rows for all
   non-blocked results are written and committed as one unit, so a partial
   run never leaves half-written figures: either every clean metric of the
   run lands or none does, and a failure rolls back only this phase — never
   the committed issues.

The alternative (one overall transaction) was rejected precisely because a
failed persist would roll back the routed issues too, silently destroying the
run's DQ evidence — the opposite of fail-loudly.

This module is deterministic and stdlib-only (no clock reads, no env, no
driver). The CLI process boundary (argv, HEADWAY_DATABASE_URL, psycopg) lives
in headway_calc._cli and is invoked via ``python -m headway_calc.runner``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from headway_calc._grouping import COVERAGE_THRESHOLD, GAP_THRESHOLD_SECONDS
from headway_calc.dq import route_findings
from headway_calc.persist import _METRIC_BY_CALC_NAME, persist_result
from headway_calc.reader import load_vehicle_positions
from headway_calc.types import CalcResult
from headway_calc.vrh import compute_vrh
from headway_calc.vrm import compute_vrm


@dataclass(frozen=True)
class MetricOutcome:
    """Per-metric outcome of one run.

    Exactly one of the two shapes holds:
    - persisted: metric_value_id set, value set, routed_blocking_ids empty
      (routed_warning_ids may name excluded-group warnings that persisted
      alongside the value as dq rows);
    - blocked:   metric_value_id None, value None, routed_blocking_ids
      non-empty (warnings, if any, are routed too).

    ``detail`` is the calculation's coverage detail (CoverageDetail.to_dict(),
    JSON-safe: ratios as strings, counts as ints) — the same object persisted
    to computed.metric_values.detail when the metric persists.
    """

    calc_name: str
    calc_version: str
    metric: str
    unit: str
    value: str | None  # Decimal rendered as text (JSON-safe); None when blocked
    metric_value_id: str | None
    routed_blocking_ids: tuple[str, ...]
    routed_warning_ids: tuple[str, ...]
    detail: dict | None

    @property
    def persisted(self) -> bool:
        return self.metric_value_id is not None

    @property
    def coverage(self) -> str | None:
        return None if self.detail is None else self.detail["coverage"]

    def to_dict(self) -> dict:
        return {
            "calc_name": self.calc_name,
            "calc_version": self.calc_version,
            "metric": self.metric,
            "unit": self.unit,
            "value": self.value,
            "metric_value_id": self.metric_value_id,
            "persisted": self.persisted,
            "coverage": self.coverage,
            "detail": self.detail,
            "routed_blocking_ids": list(self.routed_blocking_ids),
            "routed_warning_ids": list(self.routed_warning_ids),
            "blocking_issue_count": len(self.routed_blocking_ids),
            "warning_count": len(self.routed_warning_ids),
        }


@dataclass(frozen=True)
class RunReport:
    """Immutable report of one run_period execution."""

    period_start: date
    period_end: date
    gap_threshold_seconds: float
    coverage_threshold: Decimal
    positions_loaded: int
    outcomes: tuple[MetricOutcome, ...]

    @property
    def persisted_count(self) -> int:
        return sum(1 for o in self.outcomes if o.persisted)

    @property
    def blocked_count(self) -> int:
        return sum(1 for o in self.outcomes if not o.persisted)

    @property
    def routed_blocking_count(self) -> int:
        return sum(len(o.routed_blocking_ids) for o in self.outcomes)

    @property
    def routed_warning_count(self) -> int:
        return sum(len(o.routed_warning_ids) for o in self.outcomes)

    @property
    def routed_issue_count(self) -> int:
        return self.routed_blocking_count + self.routed_warning_count

    def to_dict(self) -> dict:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period_convention": "half-open [period_start, period_end), UTC",
            "gap_threshold_seconds": self.gap_threshold_seconds,
            # Decimal rendered as text (JSON-safe, never binary float).
            "coverage_threshold": str(self.coverage_threshold),
            "positions_loaded": self.positions_loaded,
            "persisted_count": self.persisted_count,
            "blocked_count": self.blocked_count,
            "routed_issue_count": self.routed_issue_count,
            "routed_blocking_count": self.routed_blocking_count,
            "routed_warning_count": self.routed_warning_count,
            "metrics": [o.to_dict() for o in self.outcomes],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def run_period(
    conn,
    period_start: date,
    period_end: date,
    gap_threshold_seconds: float | None = None,
    coverage_threshold: Decimal | float | str | None = None,
) -> RunReport:
    """Run vrm_v0 and vrh_v0 (0.2.0) over one half-open period [start, end).

    Loads positions via headway_calc.reader, computes both metrics under the
    handoff-0002 gap policy (per-group exclusion + coverage; both thresholds
    pass through and are recorded in the report), then:
    - EVERY finding (excluded-group warnings and blocking coverage refusals)
      is routed to dq.issues with its own severity, committed first;
    - a result with blocking findings has NO computed.metric_values row
      written (never emit a certifiable value over an unresolved gap);
    - a non-blocked result is persisted via headway_calc.persist (metric
      value + coverage detail JSONB + lineage edges over included groups
      only), its warnings standing alongside as the routed dq rows.

    Commits in two transactions, issues first (see module docstring). Any
    failure propagates after rolling back only the in-flight value phase;
    already-committed dq issues survive. Returns a frozen RunReport.
    """
    threshold = (
        GAP_THRESHOLD_SECONDS
        if gap_threshold_seconds is None
        else float(gap_threshold_seconds)
    )
    cov_threshold = (
        COVERAGE_THRESHOLD
        if coverage_threshold is None
        else Decimal(str(coverage_threshold))
    )
    positions = load_vehicle_positions(conn, period_start, period_end)
    results: tuple[CalcResult, ...] = (
        compute_vrm(positions, threshold, cov_threshold),
        compute_vrh(positions, threshold, cov_threshold),
    )

    # Transaction 1 — fail-loudly-first: route and COMMIT every finding
    # (warnings first, then blocking, each with its own severity) before any
    # value is written, so DQ evidence is durable no matter what happens in
    # the value phase.
    warning_ids_by_calc: dict[str, tuple[str, ...]] = {}
    blocking_ids_by_calc: dict[str, tuple[str, ...]] = {}
    routed_any = False
    for result in results:
        findings = list(result.warnings) + list(result.blocking_issues)
        if findings:
            issue_ids = route_findings(
                conn,
                findings,
                result.calc_name,
                result.calc_version,
                period_start,
                period_end,
            )
            routed_any = True
            n_warnings = len(result.warnings)
            warning_ids_by_calc[result.calc_name] = tuple(issue_ids[:n_warnings])
            blocking_ids_by_calc[result.calc_name] = tuple(issue_ids[n_warnings:])
    if routed_any:
        conn.commit()

    # Transaction 2 — values for non-blocked results only. All-or-nothing: a
    # failure rolls back this phase alone and propagates (the committed
    # issues above are untouched).
    outcomes: list[MetricOutcome] = []
    persisted_any = False
    try:
        for result in results:
            detail = None if result.detail is None else result.detail.to_dict()
            warning_ids = warning_ids_by_calc.get(result.calc_name, ())
            blocking_ids = blocking_ids_by_calc.get(result.calc_name, ())
            if result.blocking_issues:
                outcomes.append(
                    MetricOutcome(
                        calc_name=result.calc_name,
                        calc_version=result.calc_version,
                        metric=_METRIC_BY_CALC_NAME[result.calc_name],
                        unit=result.unit,
                        value=None,
                        metric_value_id=None,
                        routed_blocking_ids=blocking_ids,
                        routed_warning_ids=warning_ids,
                        detail=detail,
                    )
                )
            else:
                metric_value_id = persist_result(
                    conn, result, period_start, period_end
                )
                persisted_any = True
                outcomes.append(
                    MetricOutcome(
                        calc_name=result.calc_name,
                        calc_version=result.calc_version,
                        metric=_METRIC_BY_CALC_NAME[result.calc_name],
                        unit=result.unit,
                        value=str(result.value),
                        metric_value_id=metric_value_id,
                        routed_blocking_ids=(),
                        routed_warning_ids=warning_ids,
                        detail=detail,
                    )
                )
        if persisted_any:
            conn.commit()
    except BaseException:
        conn.rollback()
        raise

    return RunReport(
        period_start=period_start,
        period_end=period_end,
        gap_threshold_seconds=threshold,
        coverage_threshold=cov_threshold,
        positions_loaded=len(positions),
        outcomes=tuple(outcomes),
    )


if __name__ == "__main__":  # pragma: no cover — process boundary
    from headway_calc._cli import main

    raise SystemExit(main())
