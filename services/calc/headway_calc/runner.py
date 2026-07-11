"""run_period — closes the canonical→computed loop for one reporting period.

Orchestration only: resolve the policy thresholds (explicit argument >
app.settings row > code default — headway_calc.settings, migration 0014; see
run_period's docstring), load canonical.vehicle_positions
(headway_calc.reader, block_id joined per handoff 0003) plus
canonical.passenger_events and the operated trip_ids (handoff 0005), run the
v0 calculations (compute_vrm at
0.2.0, compute_vrh at 0.4.0, compute_upt at 0.1.0 — the default paths,
handoffs 0002/0004/0005), route
EVERY finding to dq.issues with its own severity
(headway_calc.dq: infos stay info, warnings stay warnings, blocking stays
blocking), then
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

from headway_calc._blocks import LAYOVER_MAX_SECONDS
from headway_calc._grouping import COVERAGE_THRESHOLD, GAP_THRESHOLD_SECONDS
from headway_calc.dq import route_findings
from headway_calc.mode import (
    MODE_DIMENSION_NAME,
    MODE_DIMENSION_VERSION,
    compute_upt_by_mode,
    compute_voms_by_mode,
    compute_vrh_by_mode,
    compute_vrm_by_mode,
    scope_for_mode,
    unknown_mode_finding,
)
from headway_calc.persist import _METRIC_BY_CALC_NAME, persist_result
from headway_calc.reader import (
    load_operated_trip_ids,
    load_passenger_events,
    load_vehicle_positions,
)
from headway_calc.settings import load_policy_settings
from headway_calc.types import CalcResult
from headway_calc.upt import IMBALANCE_THRESHOLD, MISSING_TRIP_THRESHOLD, compute_upt
from headway_calc.voms import compute_voms
from headway_calc.vrh import compute_vrh
from headway_calc.vrm import compute_vrm

#: The fleet-wide scope value (the computed.metric_values.scope column
#: default, handoff 0001).
SCOPE_AGENCY = "agency"


@dataclass(frozen=True)
class MetricOutcome:
    """Per-metric outcome of one run.

    Exactly one of the two shapes holds:
    - persisted: metric_value_id set, value set, routed_blocking_ids empty
      (routed_warning_ids/routed_info_ids may name findings that persisted
      alongside the value as dq rows);
    - blocked:   metric_value_id None, value None, routed_blocking_ids
      non-empty (warnings and infos, if any, are routed too).

    ``detail`` is the calculation's coverage detail (CoverageDetail.to_dict(),
    JSON-safe: ratios as strings, counts as ints) — the same object persisted
    to computed.metric_values.detail when the metric persists.

    ``scope`` (handoff 0009) is the computed.metric_values.scope the outcome
    was persisted under: 'agency' (fleet-wide, the default) or 'mode:<mode>'
    on a --per-mode run.
    """

    calc_name: str
    calc_version: str
    metric: str
    unit: str
    value: str | None  # Decimal rendered as text (JSON-safe); None when blocked
    metric_value_id: str | None
    routed_blocking_ids: tuple[str, ...]
    routed_warning_ids: tuple[str, ...]
    routed_info_ids: tuple[str, ...]
    detail: dict | None
    scope: str = SCOPE_AGENCY

    @property
    def persisted(self) -> bool:
        return self.metric_value_id is not None

    @property
    def coverage(self) -> str | None:
        # upt_v0's UptDetail carries no coverage ratio (its completeness
        # evidence is missing_share) — None, not a KeyError.
        return None if self.detail is None else self.detail.get("coverage")

    def to_dict(self) -> dict:
        return {
            "calc_name": self.calc_name,
            "calc_version": self.calc_version,
            "metric": self.metric,
            "unit": self.unit,
            "scope": self.scope,
            "value": self.value,
            "metric_value_id": self.metric_value_id,
            "persisted": self.persisted,
            "coverage": self.coverage,
            "detail": self.detail,
            "routed_blocking_ids": list(self.routed_blocking_ids),
            "routed_warning_ids": list(self.routed_warning_ids),
            "routed_info_ids": list(self.routed_info_ids),
            "blocking_issue_count": len(self.routed_blocking_ids),
            "warning_count": len(self.routed_warning_ids),
            "info_count": len(self.routed_info_ids),
        }


@dataclass(frozen=True)
class RunReport:
    """Immutable report of one run_period execution.

    ``threshold_sources`` is each threshold's provenance — the origin story
    of every threshold value the persisted detail JSONB already carries:
    ``"explicit"`` (a run_period argument / CLI flag), ``"settings"`` (the
    audited app.settings row, migration 0014) or ``"default"`` (the calc
    library's code default — used when neither of the above, i.e. when
    app.settings does not exist yet or was skipped via read_settings=False).
    ``imbalance_threshold`` is not an app.settings knob, so its source is
    only ever ``"explicit"`` or ``"default"``.

    ``per_mode`` (handoff 0009): whether the run also computed mode-scoped
    figures (scope 'mode:<mode>' outcomes alongside the 'agency' ones, plus
    voms_v0). ``run_info_ids`` carries run-level routed info ids that belong
    to no single metric — currently at most the ONE 'unknown_mode_share'
    finding a per-mode run routes.
    """

    period_start: date
    period_end: date
    gap_threshold_seconds: float
    coverage_threshold: Decimal
    layover_max_seconds: float
    missing_trip_threshold: Decimal
    imbalance_threshold: Decimal
    threshold_sources: dict[str, str]
    positions_loaded: int
    passenger_events_loaded: int
    operated_trips_loaded: int
    outcomes: tuple[MetricOutcome, ...]
    per_mode: bool = False
    run_info_ids: tuple[str, ...] = ()

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
    def routed_info_count(self) -> int:
        return sum(len(o.routed_info_ids) for o in self.outcomes) + len(
            self.run_info_ids
        )

    @property
    def routed_issue_count(self) -> int:
        return (
            self.routed_blocking_count
            + self.routed_warning_count
            + self.routed_info_count
        )

    def to_dict(self) -> dict:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period_convention": "half-open [period_start, period_end), UTC",
            "gap_threshold_seconds": self.gap_threshold_seconds,
            # Decimal rendered as text (JSON-safe, never binary float).
            "coverage_threshold": str(self.coverage_threshold),
            "layover_max_seconds": self.layover_max_seconds,
            "missing_trip_threshold": str(self.missing_trip_threshold),
            "imbalance_threshold": str(self.imbalance_threshold),
            # Per-threshold provenance: "explicit" | "settings" | "default".
            "threshold_sources": dict(self.threshold_sources),
            "positions_loaded": self.positions_loaded,
            "passenger_events_loaded": self.passenger_events_loaded,
            "operated_trips_loaded": self.operated_trips_loaded,
            "per_mode": self.per_mode,
            "run_info_ids": list(self.run_info_ids),
            "persisted_count": self.persisted_count,
            "blocked_count": self.blocked_count,
            "routed_issue_count": self.routed_issue_count,
            "routed_blocking_count": self.routed_blocking_count,
            "routed_warning_count": self.routed_warning_count,
            "routed_info_count": self.routed_info_count,
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
    layover_max_seconds: float | None = None,
    missing_trip_threshold: Decimal | float | str | None = None,
    imbalance_threshold: Decimal | float | str | None = None,
    read_settings: bool = True,
    per_mode: bool = False,
) -> RunReport:
    """Run vrm_v0 (0.2.0), vrh_v0 (0.4.0) and upt_v0 (0.1.0) over one
    half-open period; with ``per_mode=True`` (the MR-20 path, handoff 0009)
    additionally voms_v0 (0.1.0) and one mode-scoped result per mode per
    metric.

    Threshold precedence (per threshold, highest wins) — recorded per
    threshold in ``RunReport.threshold_sources``:

    1. **explicit argument** to this function (a CLI flag) — ``"explicit"``;
    2. **app.settings row** (migration 0014, the audited per-agency policy
       surface; read via headway_calc.settings.load_policy_settings) —
       ``"settings"``. A value set through the settings API therefore
       governs the next run with no flag needed. Applies to the four seeded
       knobs: coverage_threshold, gap_threshold_seconds,
       layover_max_seconds, missing_trip_threshold (imbalance_threshold is
       not a settings knob);
    3. **code default** (the calc library's documented constants) —
       ``"default"``. Reached only when app.settings does not exist (a
       pre-migration-0014 database — logged as a WARNING, never silent) or
       when ``read_settings=False`` (the CLI's ``--ignore-settings``, for
       reproducing historical runs).

    A settings table that exists but cannot be trusted (a knob row missing
    or unparseable) raises a typed headway_calc.settings.SettingsError and
    the run REFUSES before reading any canonical row — a guessed threshold
    could certify a figure the agency never approved.

    Loads positions (block_id joined), passenger events and operated
    trip_ids via headway_calc.reader, computes the three metrics — VRM under
    the handoff-0002 gap policy, VRH block-aware with trip-level excision
    per handoff 0004 and ``layover_max_seconds`` passed through (default
    1800 — data-informed and exhibit-aligned, per-agency configurable), UPT
    per handoff 0005 with ``missing_trip_threshold`` (default 0.02 — the
    REAL FTA p. 146 threshold) and ``imbalance_threshold`` (default 0.10 —
    the p. 151 validation example) passed through; all five inputs are
    recorded in the report with their provenance — then:
    - EVERY finding (block_unavailable infos, excised-trip and
      layover_exceeds_max warnings, blocking coverage refusals) is routed to
      dq.issues with its own severity, committed first;
    - a result with blocking findings has NO computed.metric_values row
      written (never emit a certifiable value over an unresolved gap);
    - a non-blocked result is persisted via headway_calc.persist (metric
      value + coverage detail JSONB — for VRH the trip-denominated coverage
      plus blocks_touched/trips_excised/layover_intervals_dropped — +
      lineage edges over included positions only), its warnings/infos
      standing alongside as the routed dq rows.

    Per-mode path (``per_mode=True``, default OFF — handoff 0009; the MR-20
    package needs the four data points PER MODE, tracker "Verified — Monthly
    Ridership form MR-20"):

    - voms_v0 0.1.0 joins the run: one fleet-wide ('agency') result plus one
      per mode (compute_voms / compute_voms_by_mode — blocking-free, see the
      voms module docstring);
    - each metric additionally runs over each mode's input subset (the
      UNCHANGED calc versions — input selection, not a semantics change; see
      headway_calc.mode and the tracker's "Mode scoping" section), persisting
      one computed.metric_values row per mode with scope 'mode:<mode>'
      alongside the unchanged scope 'agency' row; NULL modes bucket as
      'mode:unknown', never dropped;
    - mode-scoped findings route to dq.issues exactly like fleet findings,
      their descriptions naming the scope; a mode-scoped result with blocking
      findings persists no row for that scope (the structural guardrail is
      per scoped result);
    - ONE run-level info finding 'unknown_mode_share' is routed when any
      loaded position/event carries no mode (RunReport.run_info_ids).

    Commits in two transactions, issues first (see module docstring). Any
    failure propagates after rolling back only the in-flight value phase;
    already-committed dq issues survive. Returns a frozen RunReport.
    """
    # Threshold resolution: explicit argument > app.settings row > code
    # default (docstring). Reading (and refusing on a broken table) happens
    # BEFORE any canonical row is touched. A SettingsError propagates here.
    settings = load_policy_settings(conn) if read_settings else None
    sources: dict[str, str] = {}

    if gap_threshold_seconds is not None:
        threshold = float(gap_threshold_seconds)
        sources["gap_threshold_seconds"] = "explicit"
    elif settings is not None:
        threshold = float(settings.gap_threshold_seconds)
        sources["gap_threshold_seconds"] = "settings"
    else:
        threshold = GAP_THRESHOLD_SECONDS
        sources["gap_threshold_seconds"] = "default"

    if coverage_threshold is not None:
        cov_threshold = Decimal(str(coverage_threshold))
        sources["coverage_threshold"] = "explicit"
    elif settings is not None:
        cov_threshold = settings.coverage_threshold
        sources["coverage_threshold"] = "settings"
    else:
        cov_threshold = COVERAGE_THRESHOLD
        sources["coverage_threshold"] = "default"

    if layover_max_seconds is not None:
        layover_max = float(layover_max_seconds)
        sources["layover_max_seconds"] = "explicit"
    elif settings is not None:
        layover_max = float(settings.layover_max_seconds)
        sources["layover_max_seconds"] = "settings"
    else:
        layover_max = LAYOVER_MAX_SECONDS
        sources["layover_max_seconds"] = "default"

    if missing_trip_threshold is not None:
        missing_threshold = Decimal(str(missing_trip_threshold))
        sources["missing_trip_threshold"] = "explicit"
    elif settings is not None:
        missing_threshold = settings.missing_trip_threshold
        sources["missing_trip_threshold"] = "settings"
    else:
        missing_threshold = MISSING_TRIP_THRESHOLD
        sources["missing_trip_threshold"] = "default"

    # imbalance_threshold is not an app.settings knob: explicit or default.
    if imbalance_threshold is not None:
        imbal_threshold = Decimal(str(imbalance_threshold))
        sources["imbalance_threshold"] = "explicit"
    else:
        imbal_threshold = IMBALANCE_THRESHOLD
        sources["imbalance_threshold"] = "default"
    positions = load_vehicle_positions(conn, period_start, period_end)
    passenger_events = load_passenger_events(conn, period_start, period_end)
    operated_trip_ids = load_operated_trip_ids(conn, period_start, period_end)
    results: tuple[CalcResult, ...] = (
        compute_vrm(positions, threshold, cov_threshold),
        compute_vrh(positions, threshold, cov_threshold, layover_max),
        compute_upt(
            passenger_events,
            operated_trip_ids,
            missing_trip_threshold=missing_threshold,
            imbalance_threshold=imbal_threshold,
        ),
    )

    # Scoped result list: the fleet-wide ('agency') results first — unchanged
    # order and semantics — then, on the per-mode path (handoff 0009), the
    # fleet voms_v0 result and one mode-scoped result per metric per mode.
    scoped_results: list[tuple[str, CalcResult]] = [
        (SCOPE_AGENCY, result) for result in results
    ]
    run_finding = None
    if per_mode:
        scoped_results.append(
            (SCOPE_AGENCY, compute_voms(positions, period_start, period_end))
        )
        per_mode_results = (
            compute_vrm_by_mode(positions, threshold, cov_threshold),
            compute_vrh_by_mode(positions, threshold, cov_threshold, layover_max),
            compute_upt_by_mode(
                passenger_events,
                positions,
                missing_trip_threshold=missing_threshold,
                imbalance_threshold=imbal_threshold,
            ),
            compute_voms_by_mode(positions, period_start, period_end),
        )
        for by_mode in per_mode_results:
            for bucket, result in by_mode.items():
                scoped_results.append((scope_for_mode(bucket), result))
        run_finding = unknown_mode_finding(positions, passenger_events)

    # Transaction 1 — fail-loudly-first: route and COMMIT every finding
    # (infos, then warnings, then blocking, each with its own severity;
    # mode-scoped findings name their scope) before any value is written, so
    # DQ evidence is durable no matter what happens in the value phase.
    info_ids_by_key: dict[tuple[str, str], tuple[str, ...]] = {}
    warning_ids_by_key: dict[tuple[str, str], tuple[str, ...]] = {}
    blocking_ids_by_key: dict[tuple[str, str], tuple[str, ...]] = {}
    routed_any = False
    for scope, result in scoped_results:
        findings = (
            list(result.infos) + list(result.warnings) + list(result.blocking_issues)
        )
        if findings:
            issue_ids = route_findings(
                conn,
                findings,
                result.calc_name,
                result.calc_version,
                period_start,
                period_end,
                scope=None if scope == SCOPE_AGENCY else scope,
            )
            routed_any = True
            key = (result.calc_name, scope)
            n_infos = len(result.infos)
            n_warnings = len(result.warnings)
            info_ids_by_key[key] = tuple(issue_ids[:n_infos])
            warning_ids_by_key[key] = tuple(
                issue_ids[n_infos : n_infos + n_warnings]
            )
            blocking_ids_by_key[key] = tuple(issue_ids[n_infos + n_warnings :])
    run_info_ids: tuple[str, ...] = ()
    if run_finding is not None:
        run_info_ids = tuple(
            route_findings(
                conn,
                [run_finding],
                MODE_DIMENSION_NAME,
                MODE_DIMENSION_VERSION,
                period_start,
                period_end,
            )
        )
        routed_any = True
    if routed_any:
        conn.commit()

    # Transaction 2 — values for non-blocked results only. All-or-nothing: a
    # failure rolls back this phase alone and propagates (the committed
    # issues above are untouched).
    outcomes: list[MetricOutcome] = []
    persisted_any = False
    try:
        for scope, result in scoped_results:
            detail = None if result.detail is None else result.detail.to_dict()
            key = (result.calc_name, scope)
            info_ids = info_ids_by_key.get(key, ())
            warning_ids = warning_ids_by_key.get(key, ())
            blocking_ids = blocking_ids_by_key.get(key, ())
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
                        routed_info_ids=info_ids,
                        detail=detail,
                        scope=scope,
                    )
                )
            else:
                metric_value_id = persist_result(
                    conn, result, period_start, period_end, scope=scope
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
                        routed_info_ids=info_ids,
                        detail=detail,
                        scope=scope,
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
        layover_max_seconds=layover_max,
        missing_trip_threshold=missing_threshold,
        imbalance_threshold=imbal_threshold,
        threshold_sources=sources,
        positions_loaded=len(positions),
        passenger_events_loaded=len(passenger_events),
        operated_trips_loaded=len(operated_trip_ids),
        outcomes=tuple(outcomes),
        per_mode=per_mode,
        run_info_ids=run_info_ids,
    )


if __name__ == "__main__":  # pragma: no cover — process boundary
    from headway_calc._cli import main

    raise SystemExit(main())
