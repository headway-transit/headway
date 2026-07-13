"""derive_stop_passages — OBSERVED stop passages from vehicle positions.

OPERATIONS derivation (handoff 0014, design point 3; category 'ops' — its
outputs feed otp_v0/headway_adherence_v0 and NEVER any NTD figure). Given
one period's canonical.vehicle_positions and the scheduled stops of the
trips observed operating, derives the instant each vehicle passed each of
its scheduled stops. Deterministic and versioned like every calculation:
same inputs, same passages, byte for byte; changing the geometry or cadence
tolerances mints a NEW derivation version.

The measurement, and where the tolerances come from (2026-07-13, live MBTA
canonical.vehicle_positions, 2,238,739 within-trip consecutive gaps over
[2026-07-09, 2026-07-11]):

    inter-position gap seconds: p25=24 p50=30 p75=34 p90=45 p95=59 p99=99
    (12.36% of consecutive rows repeat the same vehicle timestamp across
    poll snapshots; 0.70% of gaps exceed 120 s; max 87,220 s)
    movement between distinct reports: p50=104 m, p90=364 m

Method (documented in services/calc/OPS_DEFINITIONS.md, "Headway
operational definition: derive_stop_passages"):

1. Positions are grouped per (trip_id, vehicle_id) and split into trip
   OCCURRENCES wherever consecutive positions are more than
   OCCURRENCE_SPLIT_SECONDS apart (the same GTFS trip_id recurs every
   service day). Rows repeating the vehicle's previous timestamp are
   collapsed (they are the same vehicle report re-polled — see the
   measured 12.36%); the count is reported, never hidden.
2. For each scheduled stop of the trip that has coordinates, the passage
   instant is the event time of the occurrence's CLOSEST-APPROACH position
   (equirectangular approximation — exact enough at the ~100 m scale this
   operates on; ties break to the earliest position). This is a
   measurement with stated uncertainty, not an interpolation: no position
   is invented between reports.
3. A passage is REFUSED — counted per reason, never silently dropped —
   when the cadence cannot support it:
   - closest approach farther than STOP_RADIUS_METERS (the vehicle was
     never observed at the stop);
   - closest approach at the occurrence's first or last position (the true
     pass may lie outside the observed window — unbounded);
   - either inter-position gap bounding the closest approach exceeds
     MAX_PASSAGE_GAP_SECONDS (the passage instant would carry more than
     ±MAX_PASSAGE_GAP_SECONDS/2 of uncertainty).

Tolerances (v0, chosen FROM the measurement above, Headway-defined —
OPS_DEFINITIONS.md):
- MAX_PASSAGE_GAP_SECONDS = 120 — above the measured p99 (99 s), so normal
  MBTA cadence (30 s polls) always qualifies while real gaps refuse; the
  passage-time uncertainty is at most ±60 s, small against the minutes-
  scale on-time window.
- STOP_RADIUS_METERS = 100 — the measured median movement between distinct
  reports is 104 m, so a vehicle that truly passes a stop is typically
  observed within ~52 m of it; 100 m accepts normal cadence without
  claiming passages the data cannot support.
- OCCURRENCE_SPLIT_SECONDS = 10800 (3 h) — far above any within-trip gap
  the tolerances accept, far below the 24 h service-day recurrence.
- MIN_OCCURRENCE_POSITIONS = 3 — fewer positions cannot bound any passage
  (rule 3's endpoint refusal would reject everything anyway); skipped
  occurrences are counted.

Stdlib only, pure functions over immutable inputs (the calc guardrail).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from headway_calc.types import OpsScheduledStop, StopPassage, VehiclePosition

DERIVATION_NAME = "derive_stop_passages"
DERIVATION_VERSION = "0.1.0"

#: Tolerances — data-derived, version-pinned (see module docstring). These
#: are part of the derivation's IDENTITY, not policy knobs: changing one
#: changes what "an observed passage" means, so it mints a new version.
MAX_PASSAGE_GAP_SECONDS = 120.0
STOP_RADIUS_METERS = 100.0
OCCURRENCE_SPLIT_SECONDS = 10800.0
MIN_OCCURRENCE_POSITIONS = 3

#: Meters per degree of latitude (spherical approximation; the same
#: convention as headway_calc.distance's haversine radius).
_METERS_PER_DEGREE = 111320.0


@dataclass(frozen=True)
class PassageDerivationStats:
    """Refusal-and-coverage accounting of one derivation run.

    Every scheduled stop the derivation looked at is accounted for exactly
    once: derived, or counted under its refusal reason — nothing is
    silently dropped (fail-loudly). Persisted (as ``to_dict()``) inside
    every ops metric's detail: the cadence evidence travels with the
    figure.
    """

    positions_considered: int
    positions_deduplicated: int
    occurrences: int
    occurrences_skipped_few_positions: int
    trips_observed: int
    trips_without_schedule: int
    stops_considered: int
    stops_missing_coordinates: int
    passages_derived: int
    refused_not_reached: int
    refused_endpoint_unbounded: int
    refused_cadence_gap: int

    def to_dict(self) -> dict:
        return {
            "derivation_name": DERIVATION_NAME,
            "derivation_version": DERIVATION_VERSION,
            "max_passage_gap_seconds": MAX_PASSAGE_GAP_SECONDS,
            "stop_radius_meters": STOP_RADIUS_METERS,
            "occurrence_split_seconds": OCCURRENCE_SPLIT_SECONDS,
            "min_occurrence_positions": MIN_OCCURRENCE_POSITIONS,
            "positions_considered": self.positions_considered,
            "positions_deduplicated": self.positions_deduplicated,
            "occurrences": self.occurrences,
            "occurrences_skipped_few_positions": (
                self.occurrences_skipped_few_positions
            ),
            "trips_observed": self.trips_observed,
            "trips_without_schedule": self.trips_without_schedule,
            "stops_considered": self.stops_considered,
            "stops_missing_coordinates": self.stops_missing_coordinates,
            "passages_derived": self.passages_derived,
            "refused_not_reached": self.refused_not_reached,
            "refused_endpoint_unbounded": self.refused_endpoint_unbounded,
            "refused_cadence_gap": self.refused_cadence_gap,
        }


def derive_stop_passages(
    positions: list[VehiclePosition],
    schedule: list[OpsScheduledStop],
) -> tuple[tuple[StopPassage, ...], PassageDerivationStats]:
    """Derive observed stop passages for one period (module docstring).

    ``positions`` — the period's canonical positions (any order; sorted
    internally by the deterministic (trip_id, vehicle_id, time,
    source_record_id) total order). Unassigned positions (trip_id None)
    cannot be matched to a schedule and are not considered (the NTD calcs
    document the same trip-assignment proxy).
    ``schedule`` — OpsScheduledStop rows for (at least) the observed trips.

    Returns (passages, stats); passages are ordered deterministically by
    (trip_id, vehicle_id, occurrence start, stop_sequence, stop_id).
    """
    schedule_by_trip: dict[str, list[OpsScheduledStop]] = {}
    for stop in sorted(
        schedule, key=lambda s: (s.trip_id, s.stop_sequence, s.stop_id)
    ):
        schedule_by_trip.setdefault(stop.trip_id, []).append(stop)

    assigned = [p for p in positions if p.trip_id is not None]
    assigned.sort(
        key=lambda p: (p.trip_id, p.vehicle_id, p.time, p.source_record_id)
    )

    # Group into (trip_id, vehicle_id) runs.
    groups: dict[tuple[str, str], list[VehiclePosition]] = {}
    for p in assigned:
        groups.setdefault((p.trip_id, p.vehicle_id), []).append(p)

    passages: list[StopPassage] = []
    deduplicated = 0
    occurrences = 0
    occurrences_skipped = 0
    stops_considered = 0
    stops_missing_coords = 0
    refused_not_reached = 0
    refused_endpoint = 0
    refused_cadence = 0
    trips_observed = len({p.trip_id for p in assigned})
    trips_without_schedule = len(
        {p.trip_id for p in assigned if p.trip_id not in schedule_by_trip}
    )

    for (trip_id, _vehicle_id), rows in sorted(groups.items()):
        trip_schedule = schedule_by_trip.get(trip_id)

        # Collapse repeated vehicle timestamps (the same report re-polled).
        collapsed: list[VehiclePosition] = []
        for p in rows:
            if collapsed and p.time == collapsed[-1].time:
                deduplicated += 1
                continue
            collapsed.append(p)

        # Split into occurrences on the service-day recurrence gap.
        occurrence: list[VehiclePosition] = []
        occurrence_lists: list[list[VehiclePosition]] = []
        for p in collapsed:
            if (
                occurrence
                and (p.time - occurrence[-1].time).total_seconds()
                > OCCURRENCE_SPLIT_SECONDS
            ):
                occurrence_lists.append(occurrence)
                occurrence = []
            occurrence.append(p)
        if occurrence:
            occurrence_lists.append(occurrence)

        for occ in occurrence_lists:
            occurrences += 1
            if len(occ) < MIN_OCCURRENCE_POSITIONS:
                occurrences_skipped += 1
                continue
            if trip_schedule is None:
                # Counted once per trip above; occurrences of unscheduled
                # trips derive nothing.
                continue

            times = [p.time for p in occ]
            lats = [p.latitude for p in occ]
            lons = [p.longitude for p in occ]

            for stop in trip_schedule:
                stops_considered += 1
                if stop.latitude is None or stop.longitude is None:
                    stops_missing_coords += 1
                    continue

                cos_lat = math.cos(math.radians(stop.latitude))
                radius_deg2 = (STOP_RADIUS_METERS / _METERS_PER_DEGREE) ** 2

                best_i = -1
                best_d2 = math.inf
                for i in range(len(occ)):
                    dy = lats[i] - stop.latitude
                    dx = (lons[i] - stop.longitude) * cos_lat
                    d2 = dx * dx + dy * dy
                    if d2 < best_d2:  # strict: ties keep the EARLIEST index
                        best_d2 = d2
                        best_i = i

                if best_d2 > radius_deg2:
                    refused_not_reached += 1
                    continue
                if best_i == 0 or best_i == len(occ) - 1:
                    refused_endpoint += 1
                    continue
                gap_before = (times[best_i] - times[best_i - 1]).total_seconds()
                gap_after = (times[best_i + 1] - times[best_i]).total_seconds()
                bounding_gap = max(gap_before, gap_after)
                if bounding_gap > MAX_PASSAGE_GAP_SECONDS:
                    refused_cadence += 1
                    continue

                p = occ[best_i]
                passages.append(
                    StopPassage(
                        trip_id=trip_id,
                        vehicle_id=p.vehicle_id,
                        route_id=stop.route_id,
                        direction_id=stop.direction_id,
                        stop_id=stop.stop_id,
                        stop_sequence=stop.stop_sequence,
                        observed_time=p.time,
                        scheduled_arrival_seconds=stop.arrival_seconds,
                        scheduled_departure_seconds=stop.departure_seconds,
                        bounding_gap_seconds=bounding_gap,
                        distance_m=math.sqrt(best_d2) * _METERS_PER_DEGREE,
                        source_record_id=p.source_record_id,
                    )
                )

    stats = PassageDerivationStats(
        positions_considered=len(assigned),
        positions_deduplicated=deduplicated,
        occurrences=occurrences,
        occurrences_skipped_few_positions=occurrences_skipped,
        trips_observed=trips_observed,
        trips_without_schedule=trips_without_schedule,
        stops_considered=stops_considered,
        stops_missing_coordinates=stops_missing_coords,
        passages_derived=len(passages),
        refused_not_reached=refused_not_reached,
        refused_endpoint_unbounded=refused_endpoint,
        refused_cadence_gap=refused_cadence,
    )
    return tuple(passages), stats
