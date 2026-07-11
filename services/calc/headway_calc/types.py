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

    def to_dict(self) -> dict:
        return {
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
    VomsDetail for voms_v0, handoff 0009; None for 0.1.0 results).
    """

    value: Decimal | None
    unit: str
    calc_name: str
    calc_version: str
    input_record_ids: tuple[str, ...]
    blocking_issues: tuple[Finding, ...]
    warnings: tuple[Finding, ...] = ()
    infos: tuple[Finding, ...] = ()
    detail: CoverageDetail | UptDetail | VomsDetail | None = None

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
