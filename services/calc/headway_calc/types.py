"""Core value types for the calculation library.

All types are frozen (immutable) dataclasses: calculations are pure functions
over immutable inputs and produce immutable results. Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

#: Finding severities — mirror dq.issues.severity exactly.
SEVERITY_BLOCKING = "blocking"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

_ALLOWED_SEVERITIES = (SEVERITY_BLOCKING, SEVERITY_WARNING, SEVERITY_INFO)

#: Day-type schedule vocabulary (handoff 0020; daytype_v0). The three
#: schedule types the 2026 NTD Policy Manual's Days Operated section names
#: verbatim ("the weekday schedule, Saturday schedule, and Sunday schedule
#: service", p. 155 — REGULATORY_TRACKER.md, "Verified — Days Operated and
#: day-type schedules").
DAY_TYPE_WEEKDAY = "weekday"
DAY_TYPE_SATURDAY = "saturday"
DAY_TYPE_SUNDAY = "sunday"
DAY_TYPES = (DAY_TYPE_WEEKDAY, DAY_TYPE_SATURDAY, DAY_TYPE_SUNDAY)


@dataclass(frozen=True)
class VehiclePosition:
    """One canonical vehicle position (read contract: canonical.vehicle_positions).

    ``time`` MUST be timezone-aware UTC event time (the vehicle timestamp from
    the feed, never ingest time). ``trip_id`` is None when the position is
    unassigned — v0 calculations treat trip assignment as the revenue-service
    proxy and simply exclude unassigned positions (documented approximation).
    ``source_record_id`` is the content-addressed raw record id this position
    derives from; it feeds the lineage graph (ADR-0007). ``block_id`` is the
    trip's GTFS block (joined from canonical.trips by the reader — handoff
    0003, calc vrh_v0 0.3.0); None when the position is unassigned or the feed
    omits the optional field, in which case VRH falls back to per-trip
    grouping. ``mode`` is the trip's route mode (canonical.routes.mode, joined
    trips→routes by the reader — handoff 0009); None when the position is
    unassigned or the trip/route is unknown, in which case mode-scoped
    computations bucket it as 'unknown' (never dropped, never guessed).
    """

    time: datetime
    vehicle_id: str
    trip_id: str | None
    latitude: float
    longitude: float
    source_record_id: str
    block_id: str | None = None
    mode: str | None = None

    def __post_init__(self) -> None:
        if self.time.tzinfo is None or self.time.utcoffset() is None:
            raise ValueError(
                f"VehiclePosition.time must be timezone-aware UTC; got naive "
                f"datetime {self.time!r} (source_record_id={self.source_record_id!r})"
            )
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(
                f"latitude {self.latitude!r} out of range [-90, 90] "
                f"(source_record_id={self.source_record_id!r})"
            )
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(
                f"longitude {self.longitude!r} out of range [-180, 180] "
                f"(source_record_id={self.source_record_id!r})"
            )


@dataclass(frozen=True)
class PassengerEvent:
    """One canonical passenger event (read contract: canonical.passenger_events,
    migration 0012, handoff 0005 — TIDES vocabulary per ADR-0003).

    ``event_timestamp`` MUST be timezone-aware UTC event time (the APC event
    timestamp, never ingest time). ``trip_id`` (from TIDES
    ``trip_id_performed``) is None when the event is unassigned — upt_v0
    treats trip assignment as the revenue-service proxy, consistent with
    vrm_v0/vrh_v0 (documented approximation), and simply excludes unassigned
    events from the counted figure. ``event_type`` carries the verbatim TIDES
    ``event_type`` enum value (e.g. ``"Passenger boarded"`` /
    ``"Passenger alighted"`` — see headway_calc.upt for the verified
    citation). ``event_count`` is preserved as-is: None stays None (the
    handoff-0005 contract forbids coalescing a NULL count to a guessed
    number; the calc warns and counts 0). ``source`` is the ingestion
    envelope source (``"tides"`` for real feeds, ``"tides_simulated"`` for
    simulator output — the simulated-data rule makes the distinction
    permanent). ``source_record_id`` is the content-addressed raw record id
    this event derives from; it feeds the lineage graph (ADR-0007). ``mode``
    is the trip's route mode (canonical.routes.mode, joined trips→routes by
    the reader — handoff 0009); None when the event is unassigned or the
    trip/route is unknown, in which case mode-scoped computations bucket it
    as 'unknown' (never dropped, never guessed).
    """

    event_timestamp: datetime
    service_date: date
    passenger_event_id: str
    vehicle_id: str
    trip_id: str | None
    trip_stop_sequence: int | None
    event_type: str
    event_count: int | None
    source: str
    source_record_id: str
    mode: str | None = None

    def __post_init__(self) -> None:
        if (
            self.event_timestamp.tzinfo is None
            or self.event_timestamp.utcoffset() is None
        ):
            raise ValueError(
                f"PassengerEvent.event_timestamp must be timezone-aware UTC; "
                f"got naive datetime {self.event_timestamp!r} "
                f"(source_record_id={self.source_record_id!r})"
            )
        if self.event_count is not None and self.event_count < 0:
            # TIDES constrains event_count to minimum 0; a negative canonical
            # count is a bad row and is surfaced loudly, never coerced.
            raise ValueError(
                f"PassengerEvent.event_count must be >= 0 or None; got "
                f"{self.event_count!r} (source_record_id={self.source_record_id!r})"
            )


@dataclass(frozen=True)
class StopTime:
    """One canonical.stop_times row joined with its stop's coordinates
    (read contract: canonical.stop_times LEFT JOIN canonical.stops,
    migration 0019, handoff 0011).

    ``latitude``/``longitude`` are None when the stop is unknown or carries
    no coordinates (nullable per the GTFS spec for nodes/boarding areas) —
    pmt_v0 then fails loudly for the affected trip, never guesses a point.
    ``shape_dist_traveled`` is None when the feed omits the optional GTFS
    column (preserved NULL, migration 0019 — never fabricated); its UNITS
    are feed-defined per the GTFS spec, so consuming it requires an explicit
    unit conversion input (see headway_calc.pmt.compute_pmt).
    """

    trip_id: str
    stop_id: str
    stop_sequence: int
    latitude: float | None
    longitude: float | None
    shape_dist_traveled: float | None

    def __post_init__(self) -> None:
        if self.latitude is not None and not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(
                f"latitude {self.latitude!r} out of range [-90, 90] "
                f"(trip_id={self.trip_id!r}, stop_id={self.stop_id!r})"
            )
        if self.longitude is not None and not (
            -180.0 <= self.longitude <= 180.0
        ):
            raise ValueError(
                f"longitude {self.longitude!r} out of range [-180, 180] "
                f"(trip_id={self.trip_id!r}, stop_id={self.stop_id!r})"
            )
        if self.shape_dist_traveled is not None and not (
            self.shape_dist_traveled >= 0.0
        ):
            raise ValueError(
                f"shape_dist_traveled {self.shape_dist_traveled!r} must be "
                f">= 0 or None (trip_id={self.trip_id!r}, "
                f"stop_id={self.stop_id!r})"
            )


#: The demand_response_trip v0 vocabulary (canonical.dr_trips CHECK enums,
#: migration 0021 / handoff 0013).
DR_TOS_VALUES = ("DO", "PT", "TX", "TN")
DR_INTERRUPTIONS = ("none", "lunch", "fuel", "garage_return", "dispatch_return")


@dataclass(frozen=True)
class DrTrip:
    """One canonical demand-response trip (read contract: canonical.dr_trips,
    migration 0021, handoff 0013 — the demand_response_trip v0 wire contract
    normalized).

    One row per BOOKING: a shared ride is several DrTrips on the same
    vehicle with overlapping [pickup, dropoff] windows. ``pickup_timestamp``
    / ``dropoff_timestamp`` MUST be timezone-aware event time (for a
    no-show: arrival at / departure from the pickup point). ``tos`` selects
    the revenue rule (TX = passenger-onboard only, p. 129 as quoted in the
    tracker's DR section). Distances are Decimal (NUMERIC end to end) and
    None when UNMEASURED — never coalesced; the DR calcs flag the gap and
    never guess. ``source`` is the ingestion envelope source (``"dr"`` real,
    ``"dr_simulated"`` simulator, or a vendor label bound to the pushing
    machine key). ``source_record_id`` anchors lineage (ADR-0007).

    Structural contradictions (the migration-0021 CHECKs) raise here so a
    bad canonical row is surfaced loudly, never coerced — the transform
    quarantines them before canonical, so a raise means a broken pipeline.
    """

    pickup_timestamp: datetime
    service_date: date
    dr_trip_id: str
    vehicle_id: str
    tos: str
    dropoff_timestamp: datetime
    riders: int
    attendants_companions: int
    ada_related: bool
    sponsored: bool
    no_show: bool
    source: str
    source_record_id: str
    sponsor: str | None = None
    onboard_miles: Decimal | None = None
    pickup_odometer_miles: Decimal | None = None
    dropoff_odometer_miles: Decimal | None = None
    interruption_after: str = "none"
    request_timestamp: datetime | None = None
    dispatch_timestamp: datetime | None = None
    driver_shift_id: str | None = None
    dispatching_point_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("pickup_timestamp", self.pickup_timestamp),
            ("dropoff_timestamp", self.dropoff_timestamp),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    f"DrTrip.{name} must be timezone-aware; got naive datetime "
                    f"{value!r} (dr_trip_id={self.dr_trip_id!r})"
                )
        if self.dropoff_timestamp < self.pickup_timestamp:
            raise ValueError(
                f"DrTrip dropoff precedes pickup (dr_trip_id="
                f"{self.dr_trip_id!r}) — a contradiction the transform "
                f"quarantines; never repaired here"
            )
        if self.tos not in DR_TOS_VALUES:
            raise ValueError(
                f"DrTrip.tos must be one of {DR_TOS_VALUES}; got {self.tos!r} "
                f"(dr_trip_id={self.dr_trip_id!r})"
            )
        if self.interruption_after not in DR_INTERRUPTIONS:
            raise ValueError(
                f"DrTrip.interruption_after must be one of {DR_INTERRUPTIONS}; "
                f"got {self.interruption_after!r} (dr_trip_id={self.dr_trip_id!r})"
            )
        if self.riders < 0 or self.attendants_companions < 0:
            raise ValueError(
                f"DrTrip riders/attendants_companions must be >= 0 "
                f"(dr_trip_id={self.dr_trip_id!r})"
            )
        if self.no_show and (self.riders > 0 or self.attendants_companions > 0):
            raise ValueError(
                f"DrTrip no_show carries boardings (dr_trip_id="
                f"{self.dr_trip_id!r}) — Exhibit 36 (tracker DR section): a "
                f"no-show is revenue time but never a boarding"
            )
        for name, value in (
            ("onboard_miles", self.onboard_miles),
            ("pickup_odometer_miles", self.pickup_odometer_miles),
            ("dropoff_odometer_miles", self.dropoff_odometer_miles),
        ):
            if value is not None and value < 0:
                raise ValueError(
                    f"DrTrip.{name} must be >= 0 or None; got {value!r} "
                    f"(dr_trip_id={self.dr_trip_id!r})"
                )

    @property
    def persons(self) -> int:
        """Boardings on this booking: riders + non-employee
        attendants/companions (pp. 143-144 as quoted in the tracker — the
        employee rule is applied by the exporter per the wire contract)."""
        return self.riders + self.attendants_companions


@dataclass(frozen=True)
class OpsScheduledStop:
    """One scheduled stop of a trip, joined with its stop's coordinates and
    the trip's route/direction (read contract: canonical.stop_times LEFT
    JOIN canonical.stops LEFT JOIN canonical.trips — handoff 0014, the ops
    analytics schedule input).

    ``latitude``/``longitude`` None when the stop is unknown or carries no
    coordinates — the passage derivation then skips the stop LOUDLY (counted
    in its stats), never guesses a point. ``arrival_seconds``/
    ``departure_seconds`` are GTFS times as integer seconds after "noon
    minus 12 h" of the service day (migration 0019 convention), None when
    the feed omits them (non-timepoint rows) — a schedule time is never
    interpolated. ``route_id``/``direction_id`` None when the trip is
    unknown to canonical.trips (e.g. RT-only ADDED trips).
    """

    trip_id: str
    stop_id: str
    stop_sequence: int
    latitude: float | None
    longitude: float | None
    arrival_seconds: int | None
    departure_seconds: int | None
    route_id: str | None
    direction_id: int | None

    def __post_init__(self) -> None:
        if self.latitude is not None and not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(
                f"latitude {self.latitude!r} out of range [-90, 90] "
                f"(trip_id={self.trip_id!r}, stop_id={self.stop_id!r})"
            )
        if self.longitude is not None and not (
            -180.0 <= self.longitude <= 180.0
        ):
            raise ValueError(
                f"longitude {self.longitude!r} out of range [-180, 180] "
                f"(trip_id={self.trip_id!r}, stop_id={self.stop_id!r})"
            )


@dataclass(frozen=True)
class StopPassage:
    """One OBSERVED stop passage, derived deterministically from
    canonical.vehicle_positions × the trip's scheduled stops
    (headway_calc.passages, derivation derive_stop_passages — handoff 0014).

    An OPERATIONS observation, never an NTD input. ``observed_time`` is the
    event time of the closest-approach position; its measurement
    uncertainty is bounded by ``bounding_gap_seconds`` (the larger of the
    inter-position gaps around the closest approach — the derivation
    REFUSES a passage where that gap exceeds its documented tolerance, so
    every emitted passage carries supportable cadence). Scheduled seconds
    are carried through from OpsScheduledStop (None preserved).
    ``source_record_id`` is the raw record of the closest-approach position
    (lineage, ADR-0007).
    """

    trip_id: str
    vehicle_id: str
    route_id: str | None
    direction_id: int | None
    stop_id: str
    stop_sequence: int
    observed_time: datetime
    scheduled_arrival_seconds: int | None
    scheduled_departure_seconds: int | None
    bounding_gap_seconds: float
    distance_m: float
    source_record_id: str

    def __post_init__(self) -> None:
        if (
            self.observed_time.tzinfo is None
            or self.observed_time.utcoffset() is None
        ):
            raise ValueError(
                f"StopPassage.observed_time must be timezone-aware UTC; got "
                f"naive datetime {self.observed_time!r} "
                f"(trip_id={self.trip_id!r}, stop_id={self.stop_id!r})"
            )


@dataclass(frozen=True)
class OtpDetail:
    """Detail of one otp_v0 run (handoff 0014 — an OPERATIONS metric,
    category 'ops', never certifiable), persisted verbatim into
    computed.metric_values.detail (JSONB, migration 0010).

    - ``passages_considered`` — derived passages with a usable scheduled
      time; ``passages_unscheduled`` — derived passages skipped because the
      schedule row carries neither arrival nor departure seconds (never
      interpolated).
    - ``on_time_count`` / ``early_count`` / ``late_count`` — the window
      classification per OPS_DEFINITIONS.md: on time iff
      -early_tolerance_seconds <= deviation <= late_tolerance_seconds.
    - ``deviation_mean_seconds`` / ``deviation_median_seconds`` — summary
      of the signed deviations (strings — Decimal-safe).
    - ``early_tolerance_seconds`` / ``late_tolerance_seconds`` — the run's
      explicit window inputs, carried for provenance exactly like
      coverage_threshold.
    - ``agency_timezone`` — the feed-declared zone the schedule was
      anchored with (canonical.agencies, migration 0026).
    - ``derivation`` — the passage derivation's identity and refusal
      accounting (name, version, tolerances, per-reason refusal counts):
      the cadence evidence behind every figure.
    """

    passages_considered: int
    passages_unscheduled: int
    on_time_count: int
    early_count: int
    late_count: int
    deviation_mean_seconds: Decimal
    deviation_median_seconds: Decimal
    early_tolerance_seconds: int
    late_tolerance_seconds: int
    agency_timezone: str
    derivation: dict

    def to_dict(self) -> dict:
        return {
            "passages_considered": self.passages_considered,
            "passages_unscheduled": self.passages_unscheduled,
            "on_time_count": self.on_time_count,
            "early_count": self.early_count,
            "late_count": self.late_count,
            "deviation_mean_seconds": str(self.deviation_mean_seconds),
            "deviation_median_seconds": str(self.deviation_median_seconds),
            "early_tolerance_seconds": self.early_tolerance_seconds,
            "late_tolerance_seconds": self.late_tolerance_seconds,
            "agency_timezone": self.agency_timezone,
            "derivation": dict(self.derivation),
        }


@dataclass(frozen=True)
class HeadwayAdherenceDetail:
    """Detail of one headway_adherence_v0 run (handoff 0014 — an OPERATIONS
    metric, category 'ops', never certifiable), persisted verbatim into
    computed.metric_values.detail (JSONB).

    The v0 figure is the coefficient of variation of headway deviations,
    cvh = (population standard deviation of (observed − scheduled headway))
    / (mean scheduled headway), over consecutive OBSERVED passage pairs at
    the same (route, direction, stop) — the math is shown in
    OPS_DEFINITIONS.md. Pair exclusions are counted, never silent:

    - ``pairs_excluded_unscheduled`` — a pair member has no scheduled time;
    - ``pairs_excluded_inverted`` — non-positive scheduled or observed
      headway (overtaking / duplicate passages);
    - ``pairs_excluded_over_cap`` — scheduled headway over
      ``max_scheduled_headway_seconds`` (a service gap, not a headway).
    """

    pairs_counted: int
    pairs_excluded_unscheduled: int
    pairs_excluded_inverted: int
    pairs_excluded_over_cap: int
    stops_covered: int
    routes_covered: int
    mean_scheduled_headway_seconds: Decimal
    stddev_deviation_seconds: Decimal
    max_scheduled_headway_seconds: int
    derivation: dict

    def to_dict(self) -> dict:
        return {
            "pairs_counted": self.pairs_counted,
            "pairs_excluded_unscheduled": self.pairs_excluded_unscheduled,
            "pairs_excluded_inverted": self.pairs_excluded_inverted,
            "pairs_excluded_over_cap": self.pairs_excluded_over_cap,
            "stops_covered": self.stops_covered,
            "routes_covered": self.routes_covered,
            "mean_scheduled_headway_seconds": str(
                self.mean_scheduled_headway_seconds
            ),
            "stddev_deviation_seconds": str(self.stddev_deviation_seconds),
            "max_scheduled_headway_seconds": self.max_scheduled_headway_seconds,
            "derivation": dict(self.derivation),
        }


@dataclass(frozen=True)
class Finding:
    """A data-quality finding raised by a calculation.

    ``severity`` mirrors dq.issues.severity:

    - ``'blocking'`` — the calculation REFUSED to emit a value; the presence of
      any blocking finding on a CalcResult means value is None (never a guessed
      number). E.g. 0.1.0's 'telemetry_gap', 0.2.0's 'coverage_below_threshold'.
    - ``'warning'`` — documented and owned, but the figure stands. E.g. 0.2.0's
      'telemetry_gap_excluded': a gapped (vehicle_id, trip_id) group excluded
      from the summed figure, reported via coverage; 0.3.0's
      'layover_exceeds_max': an over-cap inter-trip interval not counted.
    - ``'info'`` — documented context only; the figure stands and nothing was
      excluded on account of the finding. E.g. 0.3.0's 'block_unavailable':
      NULL-block trips fell back to per-trip VRH grouping (documented
      undercount — layover time between those trips is not counted).

    ``source_record_ids`` identifies the raw records bounding/causing the
    finding. For an excluded group this is ALL of that group's records —
    excluded groups' records are cited by their finding instead of appearing in
    input_record_ids/lineage (handoff 0002, rule 5).
    """

    issue_type: str
    title: str
    description: str
    source_record_ids: tuple[str, ...] = field(default_factory=tuple)
    severity: str = SEVERITY_BLOCKING

    def __post_init__(self) -> None:
        if self.severity not in _ALLOWED_SEVERITIES:
            raise ValueError(
                f"Finding.severity must be one of {_ALLOWED_SEVERITIES}; got "
                f"{self.severity!r} (issue_type={self.issue_type!r})"
            )


#: 0.1.0 compatibility name: a BlockingIssue is a Finding whose severity
#: defaults to 'blocking'. Kept importable unchanged so 0.1.0 call sites (and
#: historical-submission recomputes) keep working bit-for-bit.
BlockingIssue = Finding


@dataclass(frozen=True)
class CoverageDetail:
    """Coverage detail of one calc-0.2.0 run (handoff 0002, rule 6).

    Persisted verbatim into computed.metric_values.detail (JSONB, migration
    0010). Ratios are Decimal, quantized by the calculation (0.0001,
    ROUND_HALF_EVEN — an engineering convention, documented, pre-verification);
    ``to_dict`` renders every Decimal as a string so JSON never coerces a
    reported ratio through binary float.
    """

    coverage: Decimal
    total_groups: int
    excluded_groups: int
    clean_position_share: Decimal
    gap_threshold_seconds: float
    coverage_threshold: Decimal

    def to_dict(self) -> dict:
        return {
            "coverage": str(self.coverage),
            "total_groups": self.total_groups,
            "excluded_groups": self.excluded_groups,
            "clean_position_share": str(self.clean_position_share),
            "gap_threshold_seconds": self.gap_threshold_seconds,
            "coverage_threshold": str(self.coverage_threshold),
        }


@dataclass(frozen=True)
class BlockCoverageDetail(CoverageDetail):
    """Coverage detail of one calc-0.3.0 block-aware VRH run (handoff 0003).

    Same coverage machinery as CoverageDetail — groups are now VRH block
    groups (a vehicle's trips sharing a block_id, or per-trip fallbacks where
    block_id is NULL) — plus the run's ``layover_max_seconds`` (explicit
    input, default 1800 — an ENGINEERING PLACEHOLDER, not an FTA number) for
    provenance, exactly as gap_threshold_seconds is carried.
    """

    layover_max_seconds: float

    def to_dict(self) -> dict:
        detail = super().to_dict()
        detail["layover_max_seconds"] = self.layover_max_seconds
        return detail


@dataclass(frozen=True)
class TripExcisionCoverageDetail(BlockCoverageDetail):
    """Coverage detail of one calc-0.4.0 trip-excision VRH run (handoff 0004).

    Coverage returns to TRIP denomination: ``coverage`` is
    clean_trips/total_trips (directly comparable to 0.2.0's group coverage —
    a 0.2.0 group IS a trip). The inherited block-group fields keep their
    structural meaning: ``total_groups`` counts VRH block groups (blocks or
    per-trip fallbacks), ``excluded_groups`` counts groups whose EVERY trip
    was excised (contributing nothing), ``clean_position_share`` is the share
    of in-trip positions belonging to clean trips. New block statistics:

    - ``total_trips`` / ``trips_excised`` — the coverage numerator's
      complement: trips containing a within-trip gap > gap_threshold_seconds;
    - ``blocks_touched`` — non-NULL-block groups with at least one excised
      trip (per-trip fallback excisions show in trips_excised only);
    - ``layover_intervals_dropped`` — inter-trip intervals dropped because at
      least one bounding trip was excised (a layover interval counts only
      when BOTH bounding trips are clean).

    All three thresholds (gap_threshold_seconds, coverage_threshold,
    layover_max_seconds) are inherited provenance fields.
    """

    total_trips: int
    trips_excised: int
    blocks_touched: int
    layover_intervals_dropped: int

    def to_dict(self) -> dict:
        detail = super().to_dict()
        detail["total_trips"] = self.total_trips
        detail["trips_excised"] = self.trips_excised
        detail["blocks_touched"] = self.blocks_touched
        detail["layover_intervals_dropped"] = self.layover_intervals_dropped
        return detail


@dataclass(frozen=True)
class UptDetail:
    """Detail of one upt_v0 run (handoff 0005), persisted verbatim into
    computed.metric_values.detail (JSONB, migration 0010).

    - ``total_boardings_counted`` — the deterministic base count: sum of
      event_count over boarding events with a trip assignment (NULL counts
      contribute 0 and are warned, never guessed).
    - ``operated_trips`` / ``trips_with_events`` / ``missing_trips`` — the
      p. 146 missing-trip rule's inputs: operated trips are distinct trip_ids
      observed in canonical.vehicle_positions for the period; a missing trip
      is an operated trip with zero passenger events.
    - ``missing_share`` — missing/operated, quantized 0.0001 ROUND_HALF_EVEN
      for reporting (the threshold COMPARISON is exact, never the quantized
      value); Decimal("0") when nothing operated (degenerate period).
    - ``factor_applied`` — the FTA-sanctioned factor-up
      operated/(operated − missing) applied when missing_share <= the
      threshold, quantized 0.000001 ROUND_HALF_EVEN for reporting (the value
      itself is computed from the exact fraction); None when the run was
      blocked (share above the threshold: statistician workflow required).
    - ``source_mix`` — event counts per envelope source (ALWAYS present, the
      handoff-0005 simulated-data rule: a certifiable figure containing
      simulated records is a contradiction the DQ trail must make visible).
    - ``missing_trip_threshold`` (default 0.02 — a REAL FTA threshold, 2026
      NTD Policy Manual p. 146) and ``imbalance_threshold`` (default 0.10 —
      the p. 151 APC validation example) — the run's explicit inputs, carried
      for provenance exactly as the coverage thresholds are.
    - ``attestation`` (upt_v0 0.2.0, handoff 0019) — the statistician
      attestation provenance dict
      (headway_calc.attestation.AttestationContext.to_provenance_dict) when
      the figure was factored beyond the 2% threshold under a recorded,
      in-scope attestation; None otherwise. Emitted in ``to_dict`` ONLY when
      present, so every pre-0019 detail (and every non-attested run) is
      byte-identical to upt_v0 0.1.0's output.

    ``to_dict`` renders every Decimal as a string so JSON never coerces a
    reported ratio through binary float; source_mix keys are emitted sorted.
    """

    total_boardings_counted: int
    operated_trips: int
    trips_with_events: int
    missing_trips: int
    missing_share: Decimal
    factor_applied: Decimal | None
    source_mix: dict[str, int]
    missing_trip_threshold: Decimal
    imbalance_threshold: Decimal
    attestation: dict | None = None

    def to_dict(self) -> dict:
        detail = {
            "total_boardings_counted": self.total_boardings_counted,
            "operated_trips": self.operated_trips,
            "trips_with_events": self.trips_with_events,
            "missing_trips": self.missing_trips,
            "missing_share": str(self.missing_share),
            "factor_applied": (
                None if self.factor_applied is None else str(self.factor_applied)
            ),
            "source_mix": {k: self.source_mix[k] for k in sorted(self.source_mix)},
            "missing_trip_threshold": str(self.missing_trip_threshold),
            "imbalance_threshold": str(self.imbalance_threshold),
        }
        if self.attestation is not None:
            detail["attestation"] = dict(self.attestation)
        return detail


@dataclass(frozen=True)
class PmtDetail:
    """Detail of one pmt_v0 run (handoff 0011), persisted verbatim into
    computed.metric_values.detail (JSONB, migration 0010).

    - ``passenger_miles_counted`` — the deterministic pre-factor base: the
      sum over VALID trips of (running load × segment distance), quantized
      0.01 mile ROUND_HALF_EVEN (the vrm_v0 mile convention).
    - ``operated_trips`` / ``trips_with_events`` / ``missing_trips`` — the
      p. 146 missing-trip inputs, exactly upt_v0's vocabulary: operated =
      distinct trip_ids observed in canonical.vehicle_positions; missing =
      operated with zero passenger events.
    - ``valid_trips`` / ``invalid_trips`` — trips with events that passed /
      failed the p. 151 validity checks (imbalance, negative load) plus the
      pmt-specific data-sufficiency checks; ``invalid_trip_reasons`` counts
      each invalid trip once under its FIRST failing reason in the
      documented priority order (see headway_calc.pmt).
    - ``missing_or_invalid_share`` — (missing + invalid operated trips) /
      operated, quantized 0.0001 ROUND_HALF_EVEN for reporting (the p. 146
      threshold COMPARISON is exact, never the quantized value).
    - ``factor_applied`` — operated/(operated − missing − invalid_operated),
      quantized 0.000001 for reporting; None when the run was blocked.
    - ``distance_source_segments`` — segments priced from GTFS
      ``shape_dist_traveled`` deltas vs stop-to-stop haversine (the
      DOCUMENTED DIVERGENCE — straight-line understates path distance;
      flagged on every figure it touches via the
      'haversine_distance_fallback' info finding).
    - ``shape_dist_unit_miles`` — the explicit miles-per-unit conversion
      input for shape_dist_traveled (feed-defined units per the GTFS spec);
      None when not supplied (shape data then unusable — never guessed).
    - ``source_mix`` and both thresholds — exactly as UptDetail carries
      them (simulated-data rule + threshold provenance).
    - ``attestation`` (pmt_v0 0.2.0, handoff 0019) — exactly as UptDetail
      carries it: the statistician attestation provenance dict when the
      figure was factored beyond the 2% threshold under a recorded,
      in-scope attestation; None otherwise, and emitted ONLY when present
      (pre-0019 details stay byte-identical).

    ``to_dict`` renders every Decimal as a string; dict keys are emitted
    sorted.
    """

    passenger_miles_counted: Decimal
    operated_trips: int
    trips_with_events: int
    valid_trips: int
    invalid_trips: int
    missing_trips: int
    invalid_trip_reasons: dict[str, int]
    missing_or_invalid_share: Decimal
    factor_applied: Decimal | None
    distance_source_segments: dict[str, int]
    shape_dist_unit_miles: Decimal | None
    source_mix: dict[str, int]
    missing_trip_threshold: Decimal
    imbalance_threshold: Decimal
    attestation: dict | None = None

    def to_dict(self) -> dict:
        detail = {
            "passenger_miles_counted": str(self.passenger_miles_counted),
            "operated_trips": self.operated_trips,
            "trips_with_events": self.trips_with_events,
            "valid_trips": self.valid_trips,
            "invalid_trips": self.invalid_trips,
            "missing_trips": self.missing_trips,
            "invalid_trip_reasons": {
                k: self.invalid_trip_reasons[k]
                for k in sorted(self.invalid_trip_reasons)
            },
            "missing_or_invalid_share": str(self.missing_or_invalid_share),
            "factor_applied": (
                None if self.factor_applied is None else str(self.factor_applied)
            ),
            "distance_source_segments": {
                k: self.distance_source_segments[k]
                for k in sorted(self.distance_source_segments)
            },
            "shape_dist_unit_miles": (
                None
                if self.shape_dist_unit_miles is None
                else str(self.shape_dist_unit_miles)
            ),
            "source_mix": {k: self.source_mix[k] for k in sorted(self.source_mix)},
            "missing_trip_threshold": str(self.missing_trip_threshold),
            "imbalance_threshold": str(self.imbalance_threshold),
        }
        if self.attestation is not None:
            detail["attestation"] = dict(self.attestation)
        return detail


@dataclass(frozen=True)
class VomsDetail:
    """Detail of one voms_v0 run (handoff 0009), persisted verbatim into
    computed.metric_values.detail (JSONB, migration 0010).

    - ``days_observed`` — service days (UTC calendar dates of position time —
      the documented v0 day convention) with at least one in-trip position.
    - ``days_in_period`` — calendar days in the half-open [period_start,
      period_end) run period; when ``days_observed`` is lower the calc emits
      the 'voms_partial_observation' warning (the max can only be understated
      by missing days, never overstated).
    - ``peak_day`` — the EARLIEST day (ISO date string) attaining the maximum
      distinct-vehicle count (deterministic tie-break); None when no day was
      observed. Lineage covers this day's in-trip position records.
    - ``per_day_counts`` — summary of the per-day distinct-vehicle counts:
      ``{"min": int, "max": int, "mean": str}`` (mean is a Decimal quantized
      0.0001 ROUND_HALF_EVEN, rendered as a string so JSON never coerces it
      through binary float; min/max are exact integer counts). All three are
      None when no day was observed.
    """

    days_observed: int
    days_in_period: int
    peak_day: str | None
    per_day_counts: dict

    def to_dict(self) -> dict:
        return {
            "days_observed": self.days_observed,
            "days_in_period": self.days_in_period,
            "peak_day": self.peak_day,
            "per_day_counts": dict(self.per_day_counts),
        }


@dataclass(frozen=True)
class DrServiceDetail:
    """Detail of one dr_vrh_v0 run (handoff 0013), persisted verbatim into
    computed.metric_values.detail (JSONB, migration 0010).

    - ``vehicle_days`` / ``vehicle_days_counted`` / ``vehicle_days_excluded``
      — (vehicle_id, service_date) groups seen / summed / excluded for a
      contradiction (mixed TOS, or an interruption marked while a passenger
      was still onboard) — each exclusion is its own warning finding.
    - ``trips_counted`` / ``no_show_trips`` — bookings in the counted
      groups; no-shows are revenue time (Exhibit 36) and appear in both.
    - ``revenue_spans`` — spans after breaking vehicle-days at interruption
      markers (p. 129); for TX groups, merged passenger-onboard intervals.
    - ``interruption_breaks`` — span breaks by marker type.
    - ``tos_mix`` — counted trips per type of service; ``source_mix`` —
      trips per envelope source (ALWAYS present: the simulated-data rule).
    """

    vehicle_days: int
    vehicle_days_counted: int
    vehicle_days_excluded: int
    trips_counted: int
    no_show_trips: int
    revenue_spans: int
    interruption_breaks: dict[str, int]
    tos_mix: dict[str, int]
    source_mix: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "vehicle_days": self.vehicle_days,
            "vehicle_days_counted": self.vehicle_days_counted,
            "vehicle_days_excluded": self.vehicle_days_excluded,
            "trips_counted": self.trips_counted,
            "no_show_trips": self.no_show_trips,
            "revenue_spans": self.revenue_spans,
            "interruption_breaks": {
                k: self.interruption_breaks[k]
                for k in sorted(self.interruption_breaks)
            },
            "tos_mix": {k: self.tos_mix[k] for k in sorted(self.tos_mix)},
            "source_mix": {k: self.source_mix[k] for k in sorted(self.source_mix)},
        }


@dataclass(frozen=True)
class DrVrmDetail(DrServiceDetail):
    """Detail of one dr_vrm_v0 run — DrServiceDetail plus the distance
    accounting (handoff 0013):

    - ``distance_sources`` — revenue spans priced by whole-span odometer
      delta ('span_odometer') vs the onboard-sum path ('onboard_sum'); on
      that path (dr_vrm_v0 0.1.1) each non-TX MERGED onboard window priced
      by its boundary odometer delta additionally counts as
      'window_odometer'.
    - ``unmeasured_empty_legs`` — inter-passenger empty-travel legs (revenue
      per Exhibit 36) with no odometer pair: contributed 0 and were warned —
      a DOCUMENTED UNDERCOUNT, never an interpolated distance.
    - ``missing_onboard_distances`` — counted trips with no usable onboard
      distance (no odometer pair, no onboard_miles): contributed 0, warned.
    - ``tx_summed_overlap_intervals`` — TX merged onboard intervals holding
      more than one booking priced by SUMMING per-booking distances (no
      boundary odometer pair): a possible OVERCOUNT of shared segments,
      warned (p. 129 counts vehicle miles with a passenger onboard once).
    - ``shared_overlap_windows_summed`` (dr_vrm_v0 0.1.1) — non-TX merged
      onboard windows holding more than one overlapping booking priced by
      SUMMING per-booking distances (no boundary odometer pair): a possible
      OVERCOUNT of the shared segment, warned
      ('dr_shared_distance_summed'). Defaults to 0 so the retained 0.1.0
      path (which never merges windows) constructs the same detail shape.
    """

    distance_sources: dict[str, int]
    unmeasured_empty_legs: int
    missing_onboard_distances: int
    tx_summed_overlap_intervals: int
    shared_overlap_windows_summed: int = 0

    def to_dict(self) -> dict:
        detail = super().to_dict()
        detail["distance_sources"] = {
            k: self.distance_sources[k] for k in sorted(self.distance_sources)
        }
        detail["unmeasured_empty_legs"] = self.unmeasured_empty_legs
        detail["missing_onboard_distances"] = self.missing_onboard_distances
        detail["tx_summed_overlap_intervals"] = self.tx_summed_overlap_intervals
        detail["shared_overlap_windows_summed"] = self.shared_overlap_windows_summed
        return detail


@dataclass(frozen=True)
class DrUptDetail:
    """Detail of one dr_upt_v0 run (handoff 0013), persisted verbatim into
    computed.metric_values.detail (JSONB).

    Splits per the manual pp. 143-144 (quoted in the tracker's DR section):
    ``ada_related_upt`` is included in the total and NEVER in the sponsored
    split; ``sponsored_upt`` is included in the total;
    ``sponsored_by_sponsor`` breaks the sponsored split down by the sponsor
    label. ``ada_sponsored_conflicts`` counts trips flagged BOTH (each is a
    warning; counted in the ADA split only). ``no_show_trips`` carry revenue
    time but ZERO boardings — the Exhibit 36 asymmetry.
    """

    upt: int
    riders: int
    attendants_companions: int
    ada_related_upt: int
    sponsored_upt: int
    sponsored_by_sponsor: dict[str, int]
    ada_sponsored_conflicts: int
    no_show_trips: int
    trips_counted: int
    tos_mix: dict[str, int]
    source_mix: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "upt": self.upt,
            "riders": self.riders,
            "attendants_companions": self.attendants_companions,
            "ada_related_upt": self.ada_related_upt,
            "sponsored_upt": self.sponsored_upt,
            "sponsored_by_sponsor": {
                k: self.sponsored_by_sponsor[k]
                for k in sorted(self.sponsored_by_sponsor)
            },
            "ada_sponsored_conflicts": self.ada_sponsored_conflicts,
            "no_show_trips": self.no_show_trips,
            "trips_counted": self.trips_counted,
            "tos_mix": {k: self.tos_mix[k] for k in sorted(self.tos_mix)},
            "source_mix": {k: self.source_mix[k] for k in sorted(self.source_mix)},
        }


@dataclass(frozen=True)
class DrVomsDetail:
    """Detail of one dr_voms_v0 run (handoff 0013).

    - ``unique_vehicles`` — distinct vehicles with any revenue-service
      interval in the period; ``peak_vehicles`` — the reported maximum
      SIMULTANEOUS count (Exhibits 38 + 40: 'at any one time');
      ``peak_start`` — the first instant the maximum is attained (ISO,
      deterministic tie-break).
    - ``includes_atypical_days`` — always True: DR VOMS 'INCLUDES atypical
      service' (Exhibit 38 as quoted in the tracker) — the OPPOSITE of
      voms_v0's non-DR atypical-day exclusion divergence.
    """

    unique_vehicles: int
    peak_vehicles: int
    peak_start: str | None
    vehicle_days: int
    includes_atypical_days: bool
    tos_mix: dict[str, int]
    source_mix: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "unique_vehicles": self.unique_vehicles,
            "peak_vehicles": self.peak_vehicles,
            "peak_start": self.peak_start,
            "vehicle_days": self.vehicle_days,
            "includes_atypical_days": self.includes_atypical_days,
            "tos_mix": {k: self.tos_mix[k] for k in sorted(self.tos_mix)},
            "source_mix": {k: self.source_mix[k] for k in sorted(self.source_mix)},
        }


@dataclass(frozen=True)
class DrPmtDetail:
    """Detail of one dr_pmt_v0 run (handoff 0013): passenger-onboard
    distance sums × persons — no load-profile reconstruction (the handoff's
    'no load-profile path').

    - ``trips_counted`` / ``trips_excluded_missing_distance`` — completed
      bookings priced / excluded because no onboard distance was measurable
      (each exclusion warned; a distance is never guessed).
    - ``persons_counted`` — riders + attendants/companions on priced trips.
    - ``distance_sources`` — trips priced from an odometer pair vs the
      exported onboard_miles value.
    """

    passenger_miles_counted: Decimal
    trips_counted: int
    trips_excluded_missing_distance: int
    persons_counted: int
    no_show_trips: int
    distance_sources: dict[str, int]
    tos_mix: dict[str, int]
    source_mix: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "passenger_miles_counted": str(self.passenger_miles_counted),
            "trips_counted": self.trips_counted,
            "trips_excluded_missing_distance": self.trips_excluded_missing_distance,
            "persons_counted": self.persons_counted,
            "no_show_trips": self.no_show_trips,
            "distance_sources": {
                k: self.distance_sources[k] for k in sorted(self.distance_sources)
            },
            "tos_mix": {k: self.tos_mix[k] for k in sorted(self.tos_mix)},
            "source_mix": {k: self.source_mix[k] for k in sorted(self.source_mix)},
        }


@dataclass(frozen=True)
class ServiceDayOverride:
    """One agency-declared service-day override (app.service_day_overrides,
    migration 0031; handoff 0020) — the audited input of the daytype_v0
    classification.

    - ``assigned_day_type`` — the holiday reassignment (2026 NTD Policy
      Manual p. 156: "report holiday service under the day that most closely
      reflects the service" — REGULATORY_TRACKER.md, "Verified — Days
      Operated and day-type schedules"): 'weekday' | 'saturday' | 'sunday',
      or None (the date keeps its day-of-week schedule type).
    - ``atypical`` — the agency-declared atypical-day flag (v0: declared
      only, never auto-detected).
    - ``reason`` — required plain-language reason; an override without one
      would be an unexplainable calendar change.
    - ``updated_by`` / ``updated_at`` — the row's audit attribution (the
      app.settings pattern); carried into every consuming figure's detail
      JSONB so the declaration's provenance rides the figure permanently.

    A row that neither reassigns nor flags is meaningless and refused (the
    migration-0031 CHECK, re-asserted here for fake/test inputs).
    """

    service_date: date
    assigned_day_type: str | None
    atypical: bool
    reason: str
    updated_by: str
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.assigned_day_type is not None and self.assigned_day_type not in DAY_TYPES:
            raise ValueError(
                f"ServiceDayOverride.assigned_day_type must be one of "
                f"{DAY_TYPES} or None; got {self.assigned_day_type!r} "
                f"({self.service_date.isoformat()})"
            )
        if self.assigned_day_type is None and not self.atypical:
            raise ValueError(
                f"ServiceDayOverride for {self.service_date.isoformat()} "
                f"neither reassigns a day type nor flags the day atypical — "
                f"a meaningless override row (migration-0031 CHECK)."
            )
        if not self.reason or not self.reason.strip():
            raise ValueError(
                f"ServiceDayOverride for {self.service_date.isoformat()} "
                f"carries no reason — every calendar declaration must be "
                f"explainable."
            )

    def to_provenance_dict(self) -> dict:
        """JSON-safe snapshot for detail JSONB: the full declaration rides
        every figure computed under it (provenance, not a lookup)."""
        return {
            "service_date": self.service_date.isoformat(),
            "assigned_day_type": self.assigned_day_type,
            "atypical": self.atypical,
            "reason": self.reason,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class DaysOperatedDetail:
    """Detail of one daytype_days_operated_v0 result (handoff 0020) — one
    day type's Days Operated count with its full classification provenance.

    Counts and date lists are OBSERVATION-DERIVED (dates with at least one
    in-trip vehicle position): ``unobserved_dates`` are the day type's dates
    with no in-trip telemetry — the observed-lower-bound caveat carried by
    the 'daytype_days_unobserved' warning. ``overrides_applied`` snapshots
    every app.service_day_overrides row that shaped this day type's dates
    (ServiceDayOverride.to_provenance_dict). ``atypical_flags_declared``
    states whether ANY atypical declaration exists in the whole period —
    False means "all days typical" is a stated fact, never an assumption.
    """

    day_type: str
    daytype_version: str
    days_in_period_of_type: int
    operated_dates: tuple[str, ...]
    operated_typical_dates: tuple[str, ...]
    operated_atypical_dates: tuple[str, ...]
    unobserved_dates: tuple[str, ...]
    atypical_dates: tuple[str, ...]
    overrides_applied: tuple[dict, ...]
    atypical_flags_declared: bool

    def to_dict(self) -> dict:
        return {
            "day_type": self.day_type,
            "daytype_version": self.daytype_version,
            "days_in_period_of_type": self.days_in_period_of_type,
            "days_operated": len(self.operated_dates),
            "days_operated_typical": len(self.operated_typical_dates),
            "days_operated_atypical": len(self.operated_atypical_dates),
            "operated_dates": list(self.operated_dates),
            "operated_typical_dates": list(self.operated_typical_dates),
            "operated_atypical_dates": list(self.operated_atypical_dates),
            "unobserved_dates": list(self.unobserved_dates),
            "atypical_dates": list(self.atypical_dates),
            "overrides_applied": [dict(o) for o in self.overrides_applied],
            "atypical_flags_declared": self.atypical_flags_declared,
        }


@dataclass(frozen=True)
class DaytypeUptAvgDetail:
    """Detail of one daytype_upt_avg_v0 result (handoff 0020) — one
    (day type, split) average with the complete per-day accounting.

    - ``split`` — 'typical' or 'atypical' (atypical splits exist only where
      the agency declared atypical days; ``atypical_flags_declared`` False
      STATES that every day was typical).
    - ``per_day`` — one JSON-safe dict per operated day of the split:
      {date, value, blocked, boardings_counted, operated_trips,
      missing_trips, factor_applied[, attestation]} — the day-level upt_v0
      evidence the average is built from (present on blocked results too).
    - ``sum_upt`` / ``average`` — the exact whole-boarding sum over the
      split's days and the reported mean (0.01 ROUND_HALF_EVEN, engineering
      convention); None when the result refused.
    - ``source_mix`` — event counts per envelope source aggregated over the
      split's days (the handoff-0005 simulated-data rule).
    """

    day_type: str
    split: str
    daytype_version: str
    days_in_period_of_type: int
    days_operated: int
    dates: tuple[str, ...]
    per_day: tuple[dict, ...]
    sum_upt: str | None
    average: str | None
    source_mix: dict[str, int]
    missing_trip_threshold: Decimal
    imbalance_threshold: Decimal
    overrides_applied: tuple[dict, ...]
    atypical_dates: tuple[str, ...]
    atypical_flags_declared: bool

    def to_dict(self) -> dict:
        return {
            "day_type": self.day_type,
            "split": self.split,
            "daytype_version": self.daytype_version,
            "days_in_period_of_type": self.days_in_period_of_type,
            "days_operated": self.days_operated,
            "dates": list(self.dates),
            "per_day": [dict(d) for d in self.per_day],
            "sum_upt": self.sum_upt,
            "average": self.average,
            "source_mix": {k: self.source_mix[k] for k in sorted(self.source_mix)},
            "missing_trip_threshold": str(self.missing_trip_threshold),
            "imbalance_threshold": str(self.imbalance_threshold),
            "overrides_applied": [dict(o) for o in self.overrides_applied],
            "atypical_dates": list(self.atypical_dates),
            "atypical_flags_declared": self.atypical_flags_declared,
        }


@dataclass(frozen=True)
class CalcResult:
    """The output of one calculation run.

    ``value`` is a Decimal (never float) — or None when ``blocking_issues`` is
    non-empty: a calculation never emits a certifiable value over an unresolved
    gap. The invariant binds BLOCKING findings only: ``warnings`` (severity
    'warning', e.g. 0.2.0's excluded-group findings) and ``infos`` (severity
    'info', e.g. 0.3.0's 'block_unavailable' fallback documentation) coexist
    with a value.
    ``input_record_ids`` lists the source_record_ids actually consumed by the
    figure, in deterministic order — these feed lineage.edges (one edge per
    id); records of excluded groups appear ONLY in their warning findings.
    ``detail`` carries the 0.2.0 coverage detail (a BlockCoverageDetail for
    0.3.0 block-aware VRH; an UptDetail for upt_v0, handoff 0005; a
    VomsDetail for voms_v0, handoff 0009; a PmtDetail for pmt_v0, handoff
    0011; the Dr* details for the DR calcs, handoff 0013; None for 0.1.0
    results).
    """

    value: Decimal | None
    unit: str
    calc_name: str
    calc_version: str
    input_record_ids: tuple[str, ...]
    blocking_issues: tuple[Finding, ...]
    warnings: tuple[Finding, ...] = ()
    infos: tuple[Finding, ...] = ()
    detail: (
        CoverageDetail
        | UptDetail
        | VomsDetail
        | PmtDetail
        | DrServiceDetail
        | DrUptDetail
        | DrVomsDetail
        | DrPmtDetail
        | OtpDetail
        | HeadwayAdherenceDetail
        | DaysOperatedDetail
        | DaytypeUptAvgDetail
        | None
    ) = None

    def __post_init__(self) -> None:
        if self.blocking_issues and self.value is not None:
            raise ValueError(
                "CalcResult invariant violated: a result with blocking issues "
                "must have value=None (never a guessed number)"
            )
        if self.value is not None and not isinstance(self.value, Decimal):
            raise TypeError(
                f"CalcResult.value must be Decimal or None, got {type(self.value).__name__}"
            )
        for finding in self.blocking_issues:
            if finding.severity != SEVERITY_BLOCKING:
                raise ValueError(
                    f"CalcResult.blocking_issues must all carry severity "
                    f"'{SEVERITY_BLOCKING}'; got {finding.severity!r} "
                    f"(issue_type={finding.issue_type!r})"
                )
        for finding in self.warnings:
            if finding.severity != SEVERITY_WARNING:
                raise ValueError(
                    f"CalcResult.warnings must all carry severity "
                    f"'{SEVERITY_WARNING}'; got {finding.severity!r} "
                    f"(issue_type={finding.issue_type!r})"
                )
        for finding in self.infos:
            if finding.severity != SEVERITY_INFO:
                raise ValueError(
                    f"CalcResult.infos must all carry severity "
                    f"'{SEVERITY_INFO}'; got {finding.severity!r} "
                    f"(issue_type={finding.issue_type!r})"
                )
