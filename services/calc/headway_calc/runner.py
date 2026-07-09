"""run_period — closes the canonical→computed loop for one reporting period.

Orchestration only: load canonical.vehicle_positions (headway_calc.reader),
run the v0 calculations (compute_vrm, compute_vrh — semantics and versions
unchanged), then for each result either route its blocking issues to dq.issues
(headway_calc.dq) or persist the value (headway_calc.persist). The guardrail
is structural: a result with blocking issues NEVER reaches persist_result —
no certifiable value is ever emitted over an unresolved gap.

Transaction design — TWO transactions, fail-loudly-first
--------------------------------------------------------
1. **Issues first, committed first.** All dq.issues rows for the run are
   inserted and committed in their own transaction BEFORE any metric value is
   written. Evidence of a data problem must never be lost: if the value phase
   later fails (constraint violation, connection drop, bug), the blocking
   issues are already durable — an operator investigating the failed run sees
   WHY the figures are blocked instead of an empty table.
2. **Values second.** computed.metric_values + lineage.edges rows for all
   clean results are written and committed as one unit, so a partial run never
   leaves half-written figures: either every clean metric of the run lands or
   none does, and a failure rolls back only this phase — never the committed
   issues.

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

from headway_calc._grouping import GAP_THRESHOLD_SECONDS
from headway_calc.dq import route_blocking_issues
from headway_calc.persist import _METRIC_BY_CALC_NAME, persist_result
from headway_calc.reader import load_vehicle_positions
from headway_calc.types import CalcResult
from headway_calc.vrh import compute_vrh
from headway_calc.vrm import compute_vrm


@dataclass(frozen=True)
class MetricOutcome:
    """Per-metric outcome of one run.

    Exactly one of the two shapes holds:
    - persisted: metric_value_id set, routed_issue_ids empty, value set;
    - blocked:   metric_value_id None, routed_issue_ids non-empty, value None.
    """

    calc_name: str
    calc_version: str
    metric: str
    unit: str
    value: str | None  # Decimal rendered as text (JSON-safe); None when blocked
    metric_value_id: str | None
    routed_issue_ids: tuple[str, ...]

    @property
    def persisted(self) -> bool:
        return self.metric_value_id is not None

    def to_dict(self) -> dict:
        return {
            "calc_name": self.calc_name,
            "calc_version": self.calc_version,
            "metric": self.metric,
            "unit": self.unit,
            "value": self.value,
            "metric_value_id": self.metric_value_id,
            "persisted": self.persisted,
            "routed_issue_ids": list(self.routed_issue_ids),
            "blocking_issue_count": len(self.routed_issue_ids),
        }


@dataclass(frozen=True)
class RunReport:
    """Immutable report of one run_period execution."""

    period_start: date
    period_end: date
    gap_threshold_seconds: float
    positions_loaded: int
    outcomes: tuple[MetricOutcome, ...]

    @property
    def persisted_count(self) -> int:
        return sum(1 for o in self.outcomes if o.persisted)

    @property
    def blocked_count(self) -> int:
        return sum(1 for o in self.outcomes if not o.persisted)

    @property
    def routed_issue_count(self) -> int:
        return sum(len(o.routed_issue_ids) for o in self.outcomes)

    def to_dict(self) -> dict:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period_convention": "half-open [period_start, period_end), UTC",
            "gap_threshold_seconds": self.gap_threshold_seconds,
            "positions_loaded": self.positions_loaded,
            "persisted_count": self.persisted_count,
            "blocked_count": self.blocked_count,
            "routed_issue_count": self.routed_issue_count,
            "metrics": [o.to_dict() for o in self.outcomes],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def run_period(
    conn,
    period_start: date,
    period_end: date,
    gap_threshold_seconds: float | None = None,
) -> RunReport:
    """Run vrm_v0 and vrh_v0 over one half-open period [start, end).

    Loads positions via headway_calc.reader, computes both metrics, then:
    - a result with blocking issues has them routed to dq.issues and NO
      computed.metric_values row is written for it (never emit a certifiable
      value over an unresolved gap);
    - a clean result is persisted via headway_calc.persist (metric value +
      lineage edges).

    Commits in two transactions, issues first (see module docstring). Any
    failure propagates after rolling back only the in-flight value phase;
    already-committed dq issues survive. Returns a frozen RunReport.
    """
    threshold = (
        GAP_THRESHOLD_SECONDS
        if gap_threshold_seconds is None
        else float(gap_threshold_seconds)
    )
    positions = load_vehicle_positions(conn, period_start, period_end)
    results: tuple[CalcResult, ...] = (
        compute_vrm(positions, threshold),
        compute_vrh(positions, threshold),
    )

    # Transaction 1 — fail-loudly-first: route and COMMIT all blocking issues
    # before any value is written, so DQ evidence is durable no matter what
    # happens in the value phase.
    routed_by_calc: dict[str, tuple[str, ...]] = {}
    for result in results:
        if result.blocking_issues:
            issue_ids = route_blocking_issues(
                conn,
                list(result.blocking_issues),
                result.calc_name,
                result.calc_version,
                period_start,
                period_end,
            )
            routed_by_calc[result.calc_name] = tuple(issue_ids)
    if routed_by_calc:
        conn.commit()

    # Transaction 2 — values for clean results only. All-or-nothing: a failure
    # rolls back this phase alone and propagates (the committed issues above
    # are untouched).
    outcomes: list[MetricOutcome] = []
    persisted_any = False
    try:
        for result in results:
            if result.blocking_issues:
                outcomes.append(
                    MetricOutcome(
                        calc_name=result.calc_name,
                        calc_version=result.calc_version,
                        metric=_METRIC_BY_CALC_NAME[result.calc_name],
                        unit=result.unit,
                        value=None,
                        metric_value_id=None,
                        routed_issue_ids=routed_by_calc[result.calc_name],
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
                        routed_issue_ids=(),
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
        positions_loaded=len(positions),
        outcomes=tuple(outcomes),
    )


if __name__ == "__main__":  # pragma: no cover — process boundary
    from headway_calc._cli import main

    raise SystemExit(main())
