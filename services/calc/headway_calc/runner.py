"""run_period — closes the canonical→computed loop for one reporting period.

Orchestration only: resolve the policy thresholds (explicit argument >
app.settings row > code default — headway_calc.settings, migration 0014; see
run_period's docstring), load canonical.vehicle_positions
(headway_calc.reader, block_id joined per handoff 0003) plus
canonical.passenger_events, the operated trip_ids (handoff 0005), the
event-trip stop geometry (handoff 0011) and canonical.dr_trips (handoff
0013), run the v0 calculations (the default path: compute_vrm at 0.2.0,
compute_vrh at 0.4.0, compute_upt at 0.1.0, compute_pmt at 0.1.0 — handoffs
0002/0004/0005/0011; with per_mode=True additionally compute_voms at 0.1.0
plus one mode-scoped result per metric per mode, handoff 0009; whenever the
period holds dr_trips rows, additionally the five Demand Response calcs —
compute_dr_vrh/compute_dr_upt/compute_dr_pmt at 0.1.0 and compute_dr_vrm/
compute_dr_voms at 0.1.1, handoff 0013 + the 2026-07-13 hardening pass —
under scope 'mode:DR' + 'mode:DR:tos:<tos>'), route
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
from headway_calc.attestation import applicable_attestations
from headway_calc.dq import route_findings
from headway_calc.dr import (
    compute_dr_pmt,
    compute_dr_pmt_by_tos,
    compute_dr_upt,
    compute_dr_upt_by_tos,
    compute_dr_voms,
    compute_dr_voms_by_tos,
    compute_dr_vrh,
    compute_dr_vrh_by_tos,
    compute_dr_vrm,
    compute_dr_vrm_by_tos,
)
from headway_calc.mode import (
    MODE_DIMENSION_NAME,
    MODE_DIMENSION_VERSION,
    compute_pmt_by_mode,
    compute_upt_by_mode,
    compute_voms_by_mode,
    compute_vrh_by_mode,
    compute_vrm_by_mode,
    scope_for_mode,
    unknown_mode_finding,
)
from headway_calc.persist import _METRIC_BY_CALC_NAME, persist_result
from headway_calc.pmt import compute_pmt
from headway_calc.reader import (
    load_attestations,
    load_dr_trips,
    load_operated_trip_ids,
    load_passenger_events,
    load_trip_geometries,
    load_vehicle_positions,
)
from headway_calc.settings import load_policy_settings
from headway_calc.types import CalcResult, Finding
from headway_calc.upt import IMBALANCE_THRESHOLD, MISSING_TRIP_THRESHOLD, compute_upt
from headway_calc.voms import compute_voms
from headway_calc.vrh import compute_vrh
from headway_calc.vrm import compute_vrm

#: The fleet-wide scope value (the computed.metric_values.scope column
#: default, handoff 0001).
SCOPE_AGENCY = "agency"

#: Demand Response scopes (handoff 0013): DR figures are inherently
#: mode-level (they come from dispatch trips, not the GTFS-RT fleet), so
#: they persist ONLY under the DR mode scope and its per-TOS refinements —
#: never under 'agency' (the fleet figures remain position/event-derived).
#: 'DR' is the NTD mode code (the wire contract's vocabulary); the GTFS-
#: derived mode scopes use the transform's lowercase names ('mode:bus'), so
#: the namespaces cannot collide.
SCOPE_MODE_DR = "mode:DR"


def scope_for_dr_tos(tos: str) -> str:
    """The computed.metric_values.scope for one DR type-of-service bucket."""
    return f"mode:DR:tos:{tos}"


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
    #: canonical.stop_times rows loaded for the period's event trips —
    #: pmt_v0's geometry input (handoff 0011); default 0 keeps pre-0011
    #: constructions working.
    stop_times_loaded: int = 0
    #: canonical.dr_trips rows loaded for the period — the DR calcs' input
    #: (handoff 0013); default 0 keeps pre-0013 constructions working.
    dr_trips_loaded: int = 0
    #: Unrevoked cert.attestations rows covering the period (handoff 0019 —
    #: the statistician-attestation context of the upt_v0/pmt_v0 0.2.0
    #: factor-up path); default 0 keeps pre-0019 constructions working.
    attestations_loaded: int = 0

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
            "stop_times_loaded": self.stop_times_loaded,
            "dr_trips_loaded": self.dr_trips_loaded,
            "attestations_loaded": self.attestations_loaded,
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


def _resolve_ntd_thresholds(
    settings,
    gap_threshold_seconds: float | None,
    coverage_threshold: Decimal | float | str | None,
    layover_max_seconds: float | None,
    missing_trip_threshold: Decimal | float | str | None,
    imbalance_threshold: Decimal | float | str | None,
) -> tuple[float, Decimal, float, Decimal, Decimal, dict[str, str]]:
    """The one threshold-precedence implementation (run_period's documented
    rule, shared with preview_period so a preview can never resolve a knob
    differently from the run it models): explicit argument > app.settings
    row (``settings``, already loaded — None means the table is absent or
    was skipped) > code default. Returns the five resolved values plus the
    per-threshold provenance dict ("explicit" | "settings" | "default")."""
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

    return (
        threshold,
        cov_threshold,
        layover_max,
        missing_threshold,
        imbal_threshold,
        sources,
    )


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
    """Run vrm_v0 (0.2.0), vrh_v0 (0.4.0), upt_v0 (0.1.0) and pmt_v0
    (0.1.0, handoff 0011) over one half-open period; with ``per_mode=True``
    (the MR-20 path, handoff 0009) additionally voms_v0 (0.1.0) and one
    mode-scoped result per mode per metric. pmt_v0 shares upt_v0's p. 146
    missing_trip_threshold and p. 151 imbalance_threshold and additionally
    loads the period's event-trip stop geometry (migration 0019) for
    per-segment distances.

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

    Statistician attestations (handoff 0019): the run loads the unrevoked
    cert.attestations rows covering the period (migration 0029; a
    pre-migration database loads none and refuses exactly as before) and
    passes each scoped upt_v0/pmt_v0 computation ONLY the attestations
    matching its metric, scope, and period
    (headway_calc.attestation.applicable_attestations). A >2% missing-data
    share WITH a governing attestation factors up and persists WITH the
    attestation's provenance in the detail; WITHOUT one it refuses
    byte-for-byte as before. No other calc receives attestations.

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
    (
        threshold,
        cov_threshold,
        layover_max,
        missing_threshold,
        imbal_threshold,
        sources,
    ) = _resolve_ntd_thresholds(
        settings,
        gap_threshold_seconds,
        coverage_threshold,
        layover_max_seconds,
        missing_trip_threshold,
        imbalance_threshold,
    )
    positions = load_vehicle_positions(conn, period_start, period_end)
    passenger_events = load_passenger_events(conn, period_start, period_end)
    operated_trip_ids = load_operated_trip_ids(conn, period_start, period_end)
    trip_geometries = load_trip_geometries(conn, period_start, period_end)
    dr_trips = load_dr_trips(conn, period_start, period_end)
    # Statistician attestations (handoff 0019): unrevoked cert.attestations
    # rows covering the run period; each scoped upt/pmt computation receives
    # ONLY the attestations matching its metric AND scope AND period (the
    # pure applicable_attestations selection — hard limit 3). No other calc
    # takes an attestation: the p. 146 rule is a UPT/PMT 100%-count rule.
    attestations = load_attestations(conn, period_start, period_end)

    def _attestations_for(metric: str, scope: str):
        return applicable_attestations(
            attestations, metric, scope, period_start, period_end
        )

    results: tuple[CalcResult, ...] = (
        compute_vrm(positions, threshold, cov_threshold),
        compute_vrh(positions, threshold, cov_threshold, layover_max),
        compute_upt(
            passenger_events,
            operated_trip_ids,
            missing_trip_threshold=missing_threshold,
            imbalance_threshold=imbal_threshold,
            attestations=_attestations_for("upt", SCOPE_AGENCY),
        ),
        # pmt_v0 (handoff 0011): the same p. 146 threshold family as upt_v0.
        # shape_dist_unit_miles is deliberately NOT set here: the GTFS spec
        # leaves shape_dist units feed-defined, so consuming them requires an
        # explicit per-feed conversion (a future per-agency knob — handoff
        # 0011 Response); without it pmt_v0 uses the flagged haversine
        # fallback and says so.
        compute_pmt(
            passenger_events,
            operated_trip_ids,
            trip_geometries,
            missing_trip_threshold=missing_threshold,
            imbalance_threshold=imbal_threshold,
            attestations=_attestations_for("pmt", SCOPE_AGENCY),
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
                attestations_for_scope=lambda scope: _attestations_for(
                    "upt", scope
                ),
            ),
            compute_pmt_by_mode(
                passenger_events,
                positions,
                trip_geometries,
                missing_trip_threshold=missing_threshold,
                imbalance_threshold=imbal_threshold,
                attestations_for_scope=lambda scope: _attestations_for(
                    "pmt", scope
                ),
            ),
            compute_voms_by_mode(positions, period_start, period_end),
        )
        for by_mode in per_mode_results:
            for bucket, result in by_mode.items():
                scoped_results.append((scope_for_mode(bucket), result))
        run_finding = unknown_mode_finding(positions, passenger_events)

    # Demand Response (handoff 0013): DR figures are computed whenever the
    # period holds canonical.dr_trips rows — they are inherently mode-level
    # (dispatch-platform data, not the GTFS-RT fleet), so they run on every
    # path and persist under scope 'mode:DR' plus one scope per type of
    # service present ('mode:DR:tos:<tos>' — TOS selects the revenue rule,
    # so the per-TOS rows are the reportable refinement). The DR calcs take
    # no thresholds: no completeness threshold is quoted for DR (see
    # headway_calc.dr), so threshold provenance for these rows is the
    # absence recorded in their tracker rows.
    if dr_trips:
        dr_mode_results = (
            compute_dr_vrm(dr_trips),
            compute_dr_vrh(dr_trips),
            compute_dr_upt(dr_trips),
            compute_dr_voms(dr_trips),
            compute_dr_pmt(dr_trips),
        )
        for result in dr_mode_results:
            scoped_results.append((SCOPE_MODE_DR, result))
        dr_by_tos = (
            compute_dr_vrm_by_tos(dr_trips),
            compute_dr_vrh_by_tos(dr_trips),
            compute_dr_upt_by_tos(dr_trips),
            compute_dr_voms_by_tos(dr_trips),
            compute_dr_pmt_by_tos(dr_trips),
        )
        for by_tos in dr_by_tos:
            for tos, result in by_tos.items():
                scoped_results.append((scope_for_dr_tos(tos), result))

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
        stop_times_loaded=len(trip_geometries),
        dr_trips_loaded=len(dr_trips),
        attestations_loaded=len(attestations),
    )


@dataclass(frozen=True)
class OpsRunReport:
    """Immutable report of one run_ops_period execution (handoff 0014).

    The OPERATIONS sibling of RunReport: otp_v0 + headway_adherence_v0
    outcomes only, every persisted row category='ops' (migration 0024 —
    structurally uncertifiable, excluded from every certifiable read
    path). ``derivation`` is the passage derivation's identity + refusal
    accounting (the cadence evidence); ``tolerance_sources`` mirrors
    RunReport.threshold_sources ("explicit" | "settings" | "default").
    ``routes_below_min_sample`` names route buckets observed too thinly
    for a per-route figure (also routed as one info finding).
    """

    period_start: date
    period_end: date
    otp_early_tolerance_seconds: int
    otp_late_tolerance_seconds: int
    tolerance_sources: dict[str, str]
    positions_loaded: int
    schedule_rows_loaded: int
    agency_timezones: tuple[str, ...]
    passages_derived: int
    derivation: dict
    routes_below_min_sample: dict[str, int]
    outcomes: tuple[MetricOutcome, ...]
    run_info_ids: tuple[str, ...] = ()

    @property
    def persisted_count(self) -> int:
        return sum(1 for o in self.outcomes if o.persisted)

    @property
    def blocked_count(self) -> int:
        return sum(1 for o in self.outcomes if not o.persisted)

    def to_dict(self) -> dict:
        return {
            "category": "ops",
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period_convention": "half-open [period_start, period_end), UTC",
            "otp_early_tolerance_seconds": self.otp_early_tolerance_seconds,
            "otp_late_tolerance_seconds": self.otp_late_tolerance_seconds,
            "tolerance_sources": dict(self.tolerance_sources),
            "positions_loaded": self.positions_loaded,
            "schedule_rows_loaded": self.schedule_rows_loaded,
            "agency_timezones": list(self.agency_timezones),
            "passages_derived": self.passages_derived,
            "derivation": dict(self.derivation),
            "routes_below_min_sample": dict(self.routes_below_min_sample),
            "run_info_ids": list(self.run_info_ids),
            "persisted_count": self.persisted_count,
            "blocked_count": self.blocked_count,
            "metrics": [o.to_dict() for o in self.outcomes],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def _resolve_ops_tolerances(
    ops_settings,
    otp_early_tolerance_seconds: int | None,
    otp_late_tolerance_seconds: int | None,
) -> tuple[int, int, dict[str, str]]:
    """The one OTP-window precedence implementation (run_ops_period's
    documented rule, shared with preview_ops_period): explicit argument >
    app.settings row > code default, with per-tolerance provenance."""
    from headway_calc.ops import (
        OTP_EARLY_TOLERANCE_SECONDS,
        OTP_LATE_TOLERANCE_SECONDS,
    )

    sources: dict[str, str] = {}
    if otp_early_tolerance_seconds is not None:
        early = int(otp_early_tolerance_seconds)
        sources["otp_early_tolerance_seconds"] = "explicit"
    elif ops_settings is not None:
        early = ops_settings.otp_early_tolerance_seconds
        sources["otp_early_tolerance_seconds"] = "settings"
    else:
        early = OTP_EARLY_TOLERANCE_SECONDS
        sources["otp_early_tolerance_seconds"] = "default"
    if otp_late_tolerance_seconds is not None:
        late = int(otp_late_tolerance_seconds)
        sources["otp_late_tolerance_seconds"] = "explicit"
    elif ops_settings is not None:
        late = ops_settings.otp_late_tolerance_seconds
        sources["otp_late_tolerance_seconds"] = "settings"
    else:
        late = OTP_LATE_TOLERANCE_SECONDS
        sources["otp_late_tolerance_seconds"] = "default"
    return early, late, sources


def run_ops_period(
    conn,
    period_start: date,
    period_end: date,
    otp_early_tolerance_seconds: int | None = None,
    otp_late_tolerance_seconds: int | None = None,
    read_settings: bool = True,
) -> OpsRunReport:
    """Run the OPERATIONS calcs — otp_v0 and headway_adherence_v0 — over
    one half-open period (handoff 0014; ``python -m headway_calc.runner
    --ops``).

    A deliberately SEPARATE entry point from run_period: operations
    analytics never share a run (or a transaction phase) with NTD figures,
    so no code path can interleave the categories — the migration-0024
    boundary applied to orchestration. The two-transaction fail-loudly-
    first design is the same as run_period's.

    Pipeline: load canonical.vehicle_positions + the observed trips'
    schedules (stop_times × stops × trips) + the feed-declared agency
    timezones; derive observed stop passages (headway_calc.passages —
    deterministic, versioned, cadence-refusing); compute otp_v0 and
    headway_adherence_v0 fleet-wide ('agency' scope) and per route
    ('route:<route_id>', minimum sample sizes in headway_calc.ops); route
    EVERY finding to dq.issues with category='ops' (never gating
    certification), including one run-level 'ops_passage_derivation_summary'
    info finding carrying the derivation's refusal accounting and one
    'ops_routes_below_min_sample' info finding when any route was observed
    too thinly for a per-route figure; persist non-blocked results —
    headway_calc.persist stamps category='ops' from the calc registry, and
    the migration-0024 CHECK makes a certified ops row unrepresentable.

    OTP window precedence per tolerance (recorded in tolerance_sources):
    explicit argument > app.settings row (migration-0024 knobs, audited) >
    code default (headway_calc.ops — the TCQSM-cited 60/300 s window,
    OPS_DEFINITIONS.md). A broken settings table refuses
    (headway_calc.settings.SettingsError), never guesses.
    """
    from headway_calc.ops import (
        HEADWAY_CALC_NAME,
        OTP_CALC_NAME,
        compute_headway_adherence,
        compute_headway_adherence_by_route,
        compute_otp,
        compute_otp_by_route,
        routes_below_min_sample,
        scope_for_route,
    )
    from headway_calc.passages import (
        DERIVATION_NAME,
        DERIVATION_VERSION,
        derive_stop_passages,
    )
    from headway_calc.reader import load_agency_timezones, load_ops_schedule
    from headway_calc.settings import load_ops_policy_settings

    ops_settings = load_ops_policy_settings(conn) if read_settings else None
    early, late, sources = _resolve_ops_tolerances(
        ops_settings, otp_early_tolerance_seconds, otp_late_tolerance_seconds
    )

    positions = load_vehicle_positions(conn, period_start, period_end)
    schedule = load_ops_schedule(conn, period_start, period_end)
    timezones = tuple(load_agency_timezones(conn))

    passages, stats = derive_stop_passages(positions, schedule)
    thin_routes = routes_below_min_sample(passages)

    scoped_results: list[tuple[str, CalcResult]] = [
        (SCOPE_AGENCY, compute_otp(passages, stats, timezones, early, late)),
        (SCOPE_AGENCY, compute_headway_adherence(passages, stats)),
    ]
    for route, result in compute_otp_by_route(
        passages, stats, timezones, early, late
    ).items():
        scoped_results.append((scope_for_route(route), result))
    for route, result in compute_headway_adherence_by_route(
        passages, stats
    ).items():
        scoped_results.append((scope_for_route(route), result))

    # Run-level findings: the derivation's refusal accounting is the
    # cadence evidence behind every figure (and every refusal) — always
    # routed, category 'ops'.
    run_findings = [
        Finding(
            issue_type="ops_passage_derivation_summary",
            title="Observed stop-passage derivation summary (operations)",
            description=(
                f"{DERIVATION_NAME} {DERIVATION_VERSION} over "
                f"[{period_start.isoformat()}, {period_end.isoformat()}): "
                + json.dumps(stats.to_dict(), sort_keys=True)
                + ". Every scheduled stop considered is accounted for: "
                "derived, or refused under a named cadence/geometry reason "
                "(tolerances above; basis in services/calc/"
                "OPS_DEFINITIONS.md). OPERATIONS finding — never gates "
                "certification."
            ),
            severity="info",
        )
    ]
    if thin_routes:
        run_findings.append(
            Finding(
                issue_type="ops_routes_below_min_sample",
                title=(
                    "Routes observed too thinly for a per-route ops figure"
                ),
                description=(
                    f"{len(thin_routes)} route bucket(s) had observed "
                    "passages but fewer than the per-route minimum sample "
                    "(headway_calc.ops MIN_PASSAGES_PER_ROUTE): "
                    + json.dumps(thin_routes, sort_keys=True)
                    + ". No per-route row was persisted for them — a thin "
                    "figure is withheld loudly, never served silently. "
                    "OPERATIONS finding — never gates certification."
                ),
                severity="info",
            )
        )

    # Transaction 1 — fail-loudly-first (same design as run_period): every
    # finding committed before any value, all category='ops'.
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
                category="ops",
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
    run_info_ids = tuple(
        route_findings(
            conn,
            run_findings,
            DERIVATION_NAME,
            DERIVATION_VERSION,
            period_start,
            period_end,
            category="ops",
        )
    )
    conn.commit()

    # Transaction 2 — values for non-blocked results only (persist stamps
    # category='ops' from the calc registry; the migration-0024 CHECK
    # makes a certified ops row unrepresentable).
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

    # Deterministic sanity: exactly the two ops calcs ran (plus their
    # route scopes) — the registry names them, nothing else joins an ops
    # run.
    assert {r.calc_name for _s, r in scoped_results} <= {
        OTP_CALC_NAME,
        HEADWAY_CALC_NAME,
    }

    return OpsRunReport(
        period_start=period_start,
        period_end=period_end,
        otp_early_tolerance_seconds=early,
        otp_late_tolerance_seconds=late,
        tolerance_sources=sources,
        positions_loaded=len(positions),
        schedule_rows_loaded=len(schedule),
        agency_timezones=timezones,
        passages_derived=len(passages),
        derivation=stats.to_dict(),
        routes_below_min_sample=thin_routes,
        outcomes=tuple(outcomes),
        run_info_ids=run_info_ids,
    )


# ---------------------------------------------------------------------------
# Sandbox PREVIEW entry points (handoff 0017, design point 6)
# ---------------------------------------------------------------------------
#
# WHY A NEW ENTRY POINT EXISTS (the handoff requires this documented either
# way): the preferred path was composing run_period / run_ops_period with
# explicit-flag thresholds (--ignore-settings-style), but composition
# genuinely cannot serve a what-if preview, because BOTH existing entry
# points DURABLY WRITE by design — they route every finding to dq.issues and
# COMMIT (fail-loudly-first, transaction 1) before persisting values
# (transaction 2). A preview that wrote would pollute the real DQ workflow
# with hypothetical findings and computed.metric_values with hypothetical
# figures. Wrapping run_period in a rolled-back transaction was rejected as
# dishonest (it would defeat run_period's own commit discipline with a
# doctored connection). So the runner gains the BOUNDED preview entry points
# below, with a structural guarantee instead:
#
#   preview_period / preview_ops_period NEVER WRITE. They load canonical
#   inputs, run the same deterministic calc functions run_period runs, and
#   return a report. No route_findings, no persist_result, no INSERT, no
#   commit — pinned by test (test_preview.py asserts zero INSERTs and zero
#   commits on the recording connection). Nothing a preview produces exists
#   anywhere a certification (or any read path) could reach: a sandbox
#   preview is EPHEMERAL and therefore structurally uncertifiable — and the
#   migration-0024 CHECK stands behind that as the database-level wall for
#   anything ops-categorized that IS persisted by the real ops runner.
#
# Threshold resolution is SHARED with the real runs (_resolve_ntd_thresholds
# / _resolve_ops_tolerances), so a preview's baseline is exactly what the
# next real run would use.


@dataclass(frozen=True)
class PreviewFinding:
    """One would-be finding of a preview computation. NOT a dq.issues row —
    previews never write — just the honest summary of what the calc refused
    or flagged under the previewed thresholds."""

    issue_type: str
    severity: str
    title: str

    def to_dict(self) -> dict:
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "title": self.title,
        }


@dataclass(frozen=True)
class PreviewOutcome:
    """One metric's outcome under one previewed threshold set. ``value`` is
    None when the computation refused (blocking findings) — a preview
    refuses exactly where a real run would, never papering over a gap."""

    calc_name: str
    calc_version: str
    metric: str
    unit: str
    scope: str
    value: str | None
    detail: dict | None
    findings: tuple[PreviewFinding, ...]

    @property
    def blocked(self) -> bool:
        return self.value is None

    def to_dict(self) -> dict:
        return {
            "calc_name": self.calc_name,
            "calc_version": self.calc_version,
            "metric": self.metric,
            "unit": self.unit,
            "scope": self.scope,
            "value": self.value,
            "blocked": self.blocked,
            "detail": self.detail,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class PreviewVariant:
    """One threshold set to preview. Every None falls through to the same
    precedence a real run uses (app.settings row, then code default)."""

    label: str
    gap_threshold_seconds: float | None = None
    coverage_threshold: Decimal | float | str | None = None
    layover_max_seconds: float | None = None
    missing_trip_threshold: Decimal | float | str | None = None


@dataclass(frozen=True)
class PreviewVariantReport:
    label: str
    thresholds: dict[str, str]
    threshold_sources: dict[str, str]
    outcomes: tuple[PreviewOutcome, ...]

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "thresholds": dict(self.thresholds),
            "threshold_sources": dict(self.threshold_sources),
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


@dataclass(frozen=True)
class PreviewReport:
    """Immutable report of one preview_period execution. Nothing in it was
    persisted anywhere; ``persisted`` is a constant False so every consumer
    can state that honestly."""

    period_start: date
    period_end: date
    positions_loaded: int
    passenger_events_loaded: int
    operated_trips_loaded: int
    stop_times_loaded: int
    variants: tuple[PreviewVariantReport, ...]

    persisted: bool = False

    def to_dict(self) -> dict:
        return {
            "persisted": False,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period_convention": "half-open [period_start, period_end), UTC",
            "positions_loaded": self.positions_loaded,
            "passenger_events_loaded": self.passenger_events_loaded,
            "operated_trips_loaded": self.operated_trips_loaded,
            "stop_times_loaded": self.stop_times_loaded,
            "variants": [v.to_dict() for v in self.variants],
        }


def _preview_outcome(result: CalcResult, scope: str) -> PreviewOutcome:
    findings = tuple(
        PreviewFinding(
            issue_type=f.issue_type, severity=f.severity, title=f.title
        )
        for f in (
            list(result.infos)
            + list(result.warnings)
            + list(result.blocking_issues)
        )
    )
    return PreviewOutcome(
        calc_name=result.calc_name,
        calc_version=result.calc_version,
        metric=_METRIC_BY_CALC_NAME[result.calc_name],
        unit=result.unit,
        scope=scope,
        value=None if result.blocking_issues else str(result.value),
        detail=None if result.detail is None else result.detail.to_dict(),
        findings=findings,
    )


def preview_period(
    conn,
    period_start: date,
    period_end: date,
    variants: tuple[PreviewVariant, ...] | list[PreviewVariant],
    read_settings: bool = True,
) -> PreviewReport:
    """READ-ONLY what-if run of the four fleet-wide NTD calcs (vrm_v0,
    vrh_v0, upt_v0, pmt_v0 — 'agency' scope) over one half-open period,
    once per threshold variant, sharing one canonical-input load.

    GUARANTEE (the sandbox honesty wall, handoff 0017 design point 6): this
    function performs NO writes of any kind — no dq.issues rows, no
    computed.metric_values rows, no lineage edges, no commit. Its results
    exist only in the returned report; they can never be certified because
    they never exist anywhere certification (or any other read path) can
    see. Pinned by test.

    Scope is deliberately bounded: fleet-wide figures only (no per-mode, no
    DR — the DR calcs take no policy thresholds, so no knob can move them),
    and only the four seeded NTD knobs vary. ``imbalance_threshold`` is not
    an app.settings knob and is not previewable. A broken settings table
    refuses exactly like a real run (SettingsError propagates).
    """
    if not variants:
        raise ValueError("preview_period needs at least one variant.")
    settings = load_policy_settings(conn) if read_settings else None
    positions = load_vehicle_positions(conn, period_start, period_end)
    passenger_events = load_passenger_events(conn, period_start, period_end)
    operated_trip_ids = load_operated_trip_ids(conn, period_start, period_end)
    trip_geometries = load_trip_geometries(conn, period_start, period_end)
    # Attestations are resolved exactly as a real run resolves them (handoff
    # 0019) — a preview whose upt/pmt outcome differed from the next real
    # run's would be a lie. Loading them is a SELECT: the no-writes
    # guarantee stands.
    attestations = load_attestations(conn, period_start, period_end)

    variant_reports: list[PreviewVariantReport] = []
    for variant in variants:
        (
            threshold,
            cov_threshold,
            layover_max,
            missing_threshold,
            imbal_threshold,
            sources,
        ) = _resolve_ntd_thresholds(
            settings,
            variant.gap_threshold_seconds,
            variant.coverage_threshold,
            variant.layover_max_seconds,
            variant.missing_trip_threshold,
            None,
        )
        results = (
            compute_vrm(positions, threshold, cov_threshold),
            compute_vrh(positions, threshold, cov_threshold, layover_max),
            compute_upt(
                passenger_events,
                operated_trip_ids,
                missing_trip_threshold=missing_threshold,
                imbalance_threshold=imbal_threshold,
                attestations=applicable_attestations(
                    attestations, "upt", SCOPE_AGENCY, period_start, period_end
                ),
            ),
            compute_pmt(
                passenger_events,
                operated_trip_ids,
                trip_geometries,
                missing_trip_threshold=missing_threshold,
                imbalance_threshold=imbal_threshold,
                attestations=applicable_attestations(
                    attestations, "pmt", SCOPE_AGENCY, period_start, period_end
                ),
            ),
        )
        variant_reports.append(
            PreviewVariantReport(
                label=variant.label,
                thresholds={
                    "gap_threshold_seconds": str(threshold),
                    "coverage_threshold": str(cov_threshold),
                    "layover_max_seconds": str(layover_max),
                    "missing_trip_threshold": str(missing_threshold),
                },
                threshold_sources=sources,
                outcomes=tuple(
                    _preview_outcome(r, SCOPE_AGENCY) for r in results
                ),
            )
        )

    return PreviewReport(
        period_start=period_start,
        period_end=period_end,
        positions_loaded=len(positions),
        passenger_events_loaded=len(passenger_events),
        operated_trips_loaded=len(operated_trip_ids),
        stop_times_loaded=len(trip_geometries),
        variants=tuple(variant_reports),
    )


@dataclass(frozen=True)
class PreviewOpsVariant:
    """One OTP-window set to preview (the two migration-0024 ops knobs)."""

    label: str
    otp_early_tolerance_seconds: int | None = None
    otp_late_tolerance_seconds: int | None = None


@dataclass(frozen=True)
class PreviewOpsReport:
    """Immutable report of one preview_ops_period execution — read-only,
    exactly like PreviewReport (see preview_period's GUARANTEE)."""

    period_start: date
    period_end: date
    positions_loaded: int
    schedule_rows_loaded: int
    passages_derived: int
    derivation: dict
    variants: tuple[PreviewVariantReport, ...]

    persisted: bool = False

    def to_dict(self) -> dict:
        return {
            "persisted": False,
            "category": "ops",
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period_convention": "half-open [period_start, period_end), UTC",
            "positions_loaded": self.positions_loaded,
            "schedule_rows_loaded": self.schedule_rows_loaded,
            "passages_derived": self.passages_derived,
            "derivation": dict(self.derivation),
            "variants": [v.to_dict() for v in self.variants],
        }


def preview_ops_period(
    conn,
    period_start: date,
    period_end: date,
    variants: tuple[PreviewOpsVariant, ...] | list[PreviewOpsVariant],
    read_settings: bool = True,
) -> PreviewOpsReport:
    """READ-ONLY what-if run of otp_v0 ('agency' scope) over one half-open
    period, once per OTP-window variant, sharing one input load and ONE
    passage derivation (the derivation takes no knobs — only the on-time
    verdict moves with the window).

    Same GUARANTEE as preview_period: no writes, no commit, ephemeral
    results only — and the ops category means even the REAL ops runner's
    persisted figures sit behind the migration-0024 never-certifiable CHECK.
    headway_adherence_v0 is deliberately not previewed: it takes no policy
    knob, so a sandbox cannot move it.
    """
    from headway_calc.ops import compute_otp
    from headway_calc.passages import derive_stop_passages
    from headway_calc.reader import load_agency_timezones, load_ops_schedule
    from headway_calc.settings import load_ops_policy_settings

    if not variants:
        raise ValueError("preview_ops_period needs at least one variant.")
    ops_settings = load_ops_policy_settings(conn) if read_settings else None
    positions = load_vehicle_positions(conn, period_start, period_end)
    schedule = load_ops_schedule(conn, period_start, period_end)
    timezones = tuple(load_agency_timezones(conn))
    passages, stats = derive_stop_passages(positions, schedule)

    variant_reports: list[PreviewVariantReport] = []
    for variant in variants:
        early, late, sources = _resolve_ops_tolerances(
            ops_settings,
            variant.otp_early_tolerance_seconds,
            variant.otp_late_tolerance_seconds,
        )
        result = compute_otp(passages, stats, timezones, early, late)
        variant_reports.append(
            PreviewVariantReport(
                label=variant.label,
                thresholds={
                    "otp_early_tolerance_seconds": str(early),
                    "otp_late_tolerance_seconds": str(late),
                },
                threshold_sources=sources,
                outcomes=(_preview_outcome(result, SCOPE_AGENCY),),
            )
        )

    return PreviewOpsReport(
        period_start=period_start,
        period_end=period_end,
        positions_loaded=len(positions),
        schedule_rows_loaded=len(schedule),
        passages_derived=len(passages),
        derivation=stats.to_dict(),
        variants=tuple(variant_reports),
    )


if __name__ == "__main__":  # pragma: no cover — process boundary
    from headway_calc._cli import main

    raise SystemExit(main())
