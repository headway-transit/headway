"""Mode dimension for the calc library (handoff 0009).

MR-20 requires the four data points PER MODE (2025 NTD Monthly and Weekly
Reference Policy Manual p. 32, verified — REGULATORY_TRACKER.md, "Verified —
Monthly Ridership form MR-20"). The reader joins canonical.routes.mode onto
every position and passenger event (LEFT JOIN via canonical.trips); this
module partitions those inputs by mode and runs the UNCHANGED calculations
per subset.

Versioning position (documented in the tracker's "Mode scoping" section):
subsetting the input rows by mode is INPUT SELECTION, not a semantics change
— the math applied to each subset is byte-for-byte the shipped calc version
(vrm_v0 0.2.0, vrh_v0 0.4.0, upt_v0 0.1.0, voms_v0 0.1.0), exactly as
running the calc over a different period is not a new version. Existing calc
versions therefore do NOT bump; mode-scoped rows are distinguished by
computed.metric_values.scope = 'mode:<mode>' (the handoff-0001 scope column,
TEXT default 'agency' — no migration).

The unknown bucket: a NULL mode (unassigned position/event, unknown trip, or
unknown route) is bucketed as 'unknown' — counted, computed, and surfaced via
ONE info finding per run ('unknown_mode_share', built by
``unknown_mode_finding``); rows are NEVER dropped and a mode is NEVER
guessed. The bucket name matches the transform's MODE_UNKNOWN
(headway_transform.gtfs_static: unmapped GTFS route_type → 'unknown').

Pure and deterministic: stdlib only; partition keys iterate sorted.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable, Iterable

from headway_calc.attestation import AttestationContext
from headway_calc.types import (
    SEVERITY_INFO,
    CalcResult,
    Finding,
    PassengerEvent,
    StopTime,
    VehiclePosition,
)
from headway_calc.pmt import compute_pmt
from headway_calc.upt import IMBALANCE_THRESHOLD, MISSING_TRIP_THRESHOLD, compute_upt
from headway_calc.voms import compute_voms
from headway_calc.vrh import compute_vrh
from headway_calc.vrm import compute_vrm
from headway_calc._blocks import LAYOVER_MAX_SECONDS
from headway_calc._grouping import COVERAGE_THRESHOLD, GAP_THRESHOLD_SECONDS

#: The NULL-mode bucket — matches the transform's mapping for an unmapped
#: GTFS route_type (headway_transform.gtfs_static.MODE_UNKNOWN).
MODE_UNKNOWN = "unknown"

#: How many unknown-mode records the info finding cites verbatim before
#: truncating (the full counts are always stated in the description — the
#: upt_v0 missing-trips precedent for unboundedly large citation sets).
_UNKNOWN_RECORDS_CITED = 100

#: Identity the runner routes the run-level unknown-mode info finding under
#: (dq.issues descriptions name the raiser). Not a calculation — an
#: input-selection note of the mode dimension, documented in the tracker's
#: "Mode scoping" section.
MODE_DIMENSION_NAME = "mode_dimension"
MODE_DIMENSION_VERSION = "0.1.0"


def mode_bucket(mode: str | None) -> str:
    """NULL mode → the 'unknown' bucket; anything else passes through."""
    return MODE_UNKNOWN if mode is None else mode


def scope_for_mode(bucket: str) -> str:
    """The computed.metric_values.scope value for one mode bucket."""
    return f"mode:{bucket}"


def partition_positions_by_mode(
    positions: Iterable[VehiclePosition],
) -> dict[str, list[VehiclePosition]]:
    """Partition positions by mode bucket (sorted keys, input order kept
    within each bucket). Every position lands in exactly one bucket — NULL
    mode in 'unknown'; nothing is dropped."""
    buckets: dict[str, list[VehiclePosition]] = {}
    for pos in positions:
        buckets.setdefault(mode_bucket(pos.mode), []).append(pos)
    return {bucket: buckets[bucket] for bucket in sorted(buckets)}


def partition_events_by_mode(
    events: Iterable[PassengerEvent],
) -> dict[str, list[PassengerEvent]]:
    """Partition passenger events by mode bucket (sorted keys, input order
    kept within each bucket); NULL mode in 'unknown', nothing dropped."""
    buckets: dict[str, list[PassengerEvent]] = {}
    for event in events:
        buckets.setdefault(mode_bucket(event.mode), []).append(event)
    return {bucket: buckets[bucket] for bucket in sorted(buckets)}


def operated_trip_ids_by_mode(
    positions: Iterable[VehiclePosition],
) -> dict[str, list[str]]:
    """Per mode bucket, the distinct trip_ids observed operating (sorted).

    The mode-scoped analogue of reader.load_operated_trip_ids: derived from
    the SAME canonical.vehicle_positions rows the run loaded, so the fleet
    denominator is exactly the union of the per-mode denominators (a trip's
    positions all share the trip's route mode)."""
    trips: dict[str, set[str]] = {}
    for pos in positions:
        if pos.trip_id is None:
            continue
        trips.setdefault(mode_bucket(pos.mode), set()).add(pos.trip_id)
    return {bucket: sorted(trips[bucket]) for bucket in sorted(trips)}


def unknown_mode_finding(
    positions: Iterable[VehiclePosition],
    events: Iterable[PassengerEvent],
) -> Finding | None:
    """ONE info finding per run listing the unknown-mode share, or None.

    Counts positions and passenger events whose mode is NULL (unassigned
    rows, unknown trips, unknown routes — all bucketed 'unknown', never
    dropped, never guessed). Returns None when every row carries a mode.
    Citations are truncated to the first 100 unknown-mode records (the full
    counts are always stated in the description)."""
    positions = list(positions)
    events = list(events)
    unknown_position_ids = [p.source_record_id for p in positions if p.mode is None]
    unknown_event_ids = [e.source_record_id for e in events if e.mode is None]
    if not unknown_position_ids and not unknown_event_ids:
        return None

    cited: dict[str, None] = {}
    for record_id in unknown_position_ids + unknown_event_ids:
        if len(cited) >= _UNKNOWN_RECORDS_CITED:
            break
        cited.setdefault(record_id, None)
    n_unknown = len(unknown_position_ids) + len(unknown_event_ids)
    return Finding(
        issue_type="unknown_mode_share",
        severity=SEVERITY_INFO,
        title=(
            f"Unknown-mode rows in this run: "
            f"{len(unknown_position_ids)} of {len(positions)} positions, "
            f"{len(unknown_event_ids)} of {len(events)} passenger events"
        ),
        description=(
            f"{len(unknown_position_ids)} of {len(positions)} vehicle "
            f"positions and {len(unknown_event_ids)} of {len(events)} "
            f"passenger events carry no route mode (unassigned row, unknown "
            f"trip, or unknown route — LEFT JOIN canonical.trips → "
            f"canonical.routes yields NULL). Per handoff 0009 these rows are "
            f"bucketed under scope 'mode:unknown' — counted, computed, and "
            f"surfaced here; they are NEVER dropped and a mode is NEVER "
            f"guessed. Mode-scoped figures for the named modes exclude these "
            f"rows by construction; the fleet-wide scope 'agency' figures "
            f"are unaffected. Citations list the first "
            f"{min(n_unknown, _UNKNOWN_RECORDS_CITED)} of {n_unknown} "
            f"unknown-mode records."
        ),
        source_record_ids=tuple(cited),
    )


def compute_vrm_by_mode(
    positions: Iterable[VehiclePosition],
    gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
    coverage_threshold: Decimal = COVERAGE_THRESHOLD,
) -> dict[str, CalcResult]:
    """vrm_v0 0.2.0 per mode bucket: the UNCHANGED compute_vrm over each
    mode's positions (input selection, not a semantics change — module
    docstring). Sorted bucket keys; only buckets present in the input."""
    return {
        bucket: compute_vrm(subset, gap_threshold_seconds, coverage_threshold)
        for bucket, subset in partition_positions_by_mode(positions).items()
    }


def compute_vrh_by_mode(
    positions: Iterable[VehiclePosition],
    gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
    coverage_threshold: Decimal = COVERAGE_THRESHOLD,
    layover_max_seconds: float = LAYOVER_MAX_SECONDS,
) -> dict[str, CalcResult]:
    """vrh_v0 0.4.0 per mode bucket: the UNCHANGED compute_vrh over each
    mode's positions. Sorted bucket keys; only buckets present in the
    input. (A GTFS block never spans routes of different modes in practice;
    were a feed to do so, the per-mode subset simply applies the same
    per-trip fallback rules the fleet run applies — same math, subset
    input.)"""
    return {
        bucket: compute_vrh(
            subset, gap_threshold_seconds, coverage_threshold, layover_max_seconds
        )
        for bucket, subset in partition_positions_by_mode(positions).items()
    }


def compute_upt_by_mode(
    events: Iterable[PassengerEvent],
    positions: Iterable[VehiclePosition],
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
    attestations_for_scope: (
        Callable[[str], tuple[AttestationContext, ...]] | None
    ) = None,
) -> dict[str, CalcResult]:
    """upt_v0 0.2.0 per mode bucket: the UNCHANGED compute_upt over each
    mode's events, with that mode's operated-trip denominator derived from
    the run's positions (operated_trip_ids_by_mode). Buckets are the union
    of the event buckets and the operated-trip buckets — a mode with
    operated trips but zero passenger events still gets a result (its
    missing-trip share is 1, so the p. 146 rule blocks it — the honest
    outcome, never an invented zero). Sorted bucket keys.

    Note the p. 146 factor-up now applies PER MODE on this path — closer to
    the manual's per-mode/TOS totals than the fleet-wide factor (the
    documented upt_v0 limitation); the fleet-wide scope 'agency' figure is
    unchanged.

    ``attestations_for_scope`` (handoff 0019): a pure selector called with
    each bucket's scope string (scope_for_mode(bucket), e.g. 'mode:bus')
    returning the statistician attestations applicable to THAT scope — the
    runner passes headway_calc.attestation.applicable_attestations bound to
    the run's period, so an attestation never leaks across scopes (hard
    limit 3). Default None: no attestation context, the pre-0019 behavior
    byte for byte."""
    positions = list(positions)
    event_buckets = partition_events_by_mode(events)
    operated_buckets = operated_trip_ids_by_mode(positions)
    results: dict[str, CalcResult] = {}
    for bucket in sorted(set(event_buckets) | set(operated_buckets)):
        results[bucket] = compute_upt(
            event_buckets.get(bucket, []),
            operated_buckets.get(bucket, []),
            missing_trip_threshold=missing_trip_threshold,
            imbalance_threshold=imbalance_threshold,
            attestations=(
                ()
                if attestations_for_scope is None
                else attestations_for_scope(scope_for_mode(bucket))
            ),
        )
    return results


def compute_pmt_by_mode(
    events: Iterable[PassengerEvent],
    positions: Iterable[VehiclePosition],
    stop_times: Iterable[StopTime],
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
    shape_dist_unit_miles: Decimal | None = None,
    attestations_for_scope: (
        Callable[[str], tuple[AttestationContext, ...]] | None
    ) = None,
) -> dict[str, CalcResult]:
    """pmt_v0 0.2.0 per mode bucket (handoff 0011): the UNCHANGED compute_pmt
    over each mode's events, with that mode's operated-trip denominator
    derived from the run's positions — bucket construction identical to
    compute_upt_by_mode (a mode with operated trips but zero events still
    gets a result: its missing share is 1, so the p. 146 rule blocks it —
    the honest outcome, never an invented zero). The stop geometry is passed
    WHOLE: it is keyed by trip_id, so each mode's trips consume exactly
    their own rows (input selection, not a semantics change). Sorted bucket
    keys.

    Note the p. 146 factor-up applies PER MODE on this path — closer to the
    manual's per-mode/TOS totals than the fleet-wide factor; the fleet-wide
    scope 'agency' figure is unchanged (the upt_v0 precedent).

    ``attestations_for_scope`` (handoff 0019): exactly as
    compute_upt_by_mode — a pure per-scope selector; default None keeps the
    pre-0019 behavior byte for byte."""
    positions = list(positions)
    stop_times = list(stop_times)
    event_buckets = partition_events_by_mode(events)
    operated_buckets = operated_trip_ids_by_mode(positions)
    results: dict[str, CalcResult] = {}
    for bucket in sorted(set(event_buckets) | set(operated_buckets)):
        results[bucket] = compute_pmt(
            event_buckets.get(bucket, []),
            operated_buckets.get(bucket, []),
            stop_times,
            missing_trip_threshold=missing_trip_threshold,
            imbalance_threshold=imbalance_threshold,
            shape_dist_unit_miles=shape_dist_unit_miles,
            attestations=(
                ()
                if attestations_for_scope is None
                else attestations_for_scope(scope_for_mode(bucket))
            ),
        )
    return results


def compute_voms_by_mode(
    positions: Iterable[VehiclePosition],
    period_start,
    period_end,
) -> dict[str, CalcResult]:
    """voms_v0 0.1.0 per mode bucket: the UNCHANGED compute_voms over each
    mode's positions. Sorted bucket keys; only buckets present in the input.
    NOTE: VOMS is NOT additive across modes — each mode's maximum may occur
    on a different day, so the fleet figure is bounded by
    max(per-mode) <= fleet <= sum(per-mode), never assumed equal to the
    sum (property-tested)."""
    return {
        bucket: compute_voms(subset, period_start, period_end)
        for bucket, subset in partition_positions_by_mode(positions).items()
    }
