"""Normalizer: raw.telematics.vehicle_stats -> canonical.vehicle_telematics_days.

Handoff 0028. Parses ONE fleet-telematics API response page (the vendor's own
JSON bytes, landed content-addressed by the connector) into
`CanonicalTelematicsDay` rows per migration 0034, column-for-column, with one
LineageEdge per row back to the page's record_id and a DQFinding for every
gap, contradiction and unmapped series — never a silent skip.

=========================== THE HONESTY WALL ===========================
TELEMATICS DISTANCE IS NOT REVENUE MILES. ENGINE TIME IS NOT REVENUE HOURS.
An odometer delta includes deadhead, personal use, maintenance travel and
everything else the vehicle did. This module lands MEASURED VEHICLE MOVEMENT
and nothing else: it computes no NTD figure, and nothing in services/calc/
reads its output. Turning these measurements into a reportable vanpool
figure requires the FTA vanpool rules quoted verbatim into
services/calc/REGULATORY_TRACKER.md by the NTD Compliance role plus an
agency-declared statement of which vehicle-days were revenue service — a
separate, compliance-gated wave (handoff 0028, Open Questions).
========================================================================

The only arithmetic here is `last recorded reading - first recorded reading`
for a cumulative counter, with BOTH endpoints stored alongside the result, so
the subtraction is auditable and reversible. Migration 0034 enforces that
structurally: a stored value that is not exactly the difference of the two
stored readings is rejected by the database.

Nothing is interpolated, extrapolated or repaired:

- fewer than two readings in a day  -> value NULL, endpoints kept, finding;
- a cumulative counter that went BACKWARDS (a reset, or a replaced gateway
  -- the vendor documents `gpsDistanceMeters` as counting "since the gateway
  was installed") -> value NULL, endpoints kept, finding;
- a gap between readings -> `max_sample_gap_seconds` stored on the row and a
  finding when it exceeds the declared threshold. Movement inside the gap is
  never apportioned across it;
- a vehicle with no ECU odometer coverage (the vendor documents that
  `obdOdometerMeters` "will be omitted" without diagnostic coverage) -> a
  finding. A GPS figure is NEVER promoted into the ECU basis.

Measurement bases are kept DISTINCT: one row per (vehicle, service date,
measure, basis). Substituting one basis for another is not expressible.

Service dates are LOCAL wall dates, so they need the agency's DECLARED
timezone. It is never guessed: with no declared zone this normalizer writes
ZERO rows and raises a blocking finding (the adapter-framework
declared-timezone rule, applied to telematics).

Source labels are fail-closed (handoff 0015 rule): the envelope source must
be one of the labels REGISTERED in contracts/fleet-telematics.v0.schema.json
(`source_system` enum, loaded from the checked-in contract at import so this
module cannot drift from it). An unregistered label refuses the whole page —
raw record retained, blocking finding, zero canonical rows. Simulated data
carries the `_simulated` label verbatim into every row's `source` column and
stays permanently distinguishable in provenance (handoff 0005 rule).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time as time_of_day, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .model import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    DQFinding,
    LineageEdge,
)

TRANSFORM_NAME = "normalize_telematics_vehicle_days"
TRANSFORM_VERSION = "0.1.0"

TOPIC = "raw.telematics.vehicle_stats"
OUTPUT_KIND = "canonical.vehicle_telematics_days"
INPUT_KIND = "raw.records"

# The contract file IS the contract (ADR-0006): loaded from disk at import,
# exactly as envelope.py does, so the registered source labels and the
# measure/basis vocabulary here can never drift from the checked-in schema.
_DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
_CONTRACTS_DIR = Path(os.environ.get("HEADWAY_CONTRACTS_DIR", _DEFAULT_CONTRACTS_DIR))
_CONTRACT_PATH = _CONTRACTS_DIR / "fleet-telematics.v0.schema.json"

with open(_CONTRACT_PATH, encoding="utf-8") as _f:
    TELEMATICS_CONTRACT: dict = json.load(_f)

_PROPS = TELEMATICS_CONTRACT["properties"]
#: Registered telematics source labels (contract `source_system` enum).
REGISTERED_SOURCES: frozenset[str] = frozenset(_PROPS["source_system"]["enum"])
MEASURES: frozenset[str] = frozenset(_PROPS["measure"]["enum"])
BASES: frozenset[str] = frozenset(_PROPS["basis"]["enum"])

# --------------------------------------------------------------------------
# Samsara vehicle-stat series -> contract (measure, basis, unit).
#
# Every entry is read from the vendor's PUBLISHED OpenAPI document, never
# from memory:
#   https://developers.samsara.com/openapi/samsara-api.json
#   info.version 2025-10-23 (OpenAPI 3.0.1), retrieved 2026-07-29,
#   sha256 2ed9a10c736189354662585f50ea6a756b73d5fecb6663b2ee122fdca994730e
#
# All five are cumulative counters in the vendor's own words, so they land as
# reading_kind 'cumulative_counter'. Spec quotes:
#   obdOdometerMeters      "Number of meters the vehicle has traveled
#                           according to the on-board diagnostics."
#   gpsOdometerMeters      "…according to the GPS calculations and the
#                           manually-specified odometer reading."
#   gpsDistanceMeters      "…since the gateway was installed, based on GPS
#                           calculations."
#   obdEngineSeconds       "Number of seconds the vehicle's engine has been
#                           on according to the on-board diagnostics."
#   syntheticEngineSeconds "The cumulative number of seconds the engine has
#                           run estimated based on when the engine is
#                           running." -> an ESTIMATE, kept on its own basis
#                           and never promoted to ecu_engine_time.
# --------------------------------------------------------------------------
SAMSARA_SERIES: dict[str, tuple[str, str, str]] = {
    "obdOdometerMeters": ("distance", "ecu_odometer", "meters"),
    "gpsOdometerMeters": ("distance", "gps_odometer", "meters"),
    "gpsDistanceMeters": ("distance", "gps_distance", "meters"),
    "obdEngineSeconds": ("engine_time", "ecu_engine_time", "seconds"),
    "syntheticEngineSeconds": ("engine_time", "estimated_engine_time", "seconds"),
}

#: basis -> unit, derived from SAMSARA_SERIES so the two cannot disagree.
SAMSARA_SERIES_UNIT: dict[str, str] = {
    basis: unit for (_measure, basis, unit) in SAMSARA_SERIES.values()
}

READING_KIND_CUMULATIVE = "cumulative_counter"

#: Vendor response keys that are vehicle identity, not a stat series.
_IDENTITY_KEYS = frozenset({"id", "name", "externalIds"})

# --------------------------------------------------------------------------
# Thresholds below are HEADWAY OPERATIONAL DEFAULTS for surfacing suspicious
# measurements to a human. They are NOT vendor limits and NOT regulatory
# thresholds — no published Samsara or FTA document states them. They change
# nothing about what is stored: the measured value is always kept as
# measured; crossing a threshold only raises a data-quality issue.
# --------------------------------------------------------------------------
#: ~1000 statute miles by one vehicle in one service day.
DEFAULT_IMPLAUSIBLE_DAILY_DISTANCE_METERS = Decimal("1609344")
#: Six hours between consecutive readings on a day that recorded movement.
DEFAULT_SAMPLE_GAP_WARNING_SECONDS = 6 * 3600
#: How many examples an aggregated finding names before saying "and N more".
_MAX_EXAMPLES = 10


@dataclass(frozen=True)
class CanonicalTelematicsDay:
    """One canonical.vehicle_telematics_days row (migration 0034)."""

    window_start: datetime  # TIMESTAMPTZ NOT NULL (hypertable time)
    window_end: datetime  # TIMESTAMPTZ NOT NULL
    service_date: date  # DATE NOT NULL
    vehicle_id: str  # TEXT NOT NULL
    vehicle_label: str | None
    measure: str  # 'distance' | 'engine_time'
    basis: str  # see migration 0034 CHECK
    unit: str  # 'meters' | 'seconds'
    reading_kind: str  # 'cumulative_counter' | 'period_total'
    value: Decimal | None  # NUMERIC — NULL means UNMEASURED, never 0
    first_reading_at: datetime | None
    first_reading_value: Decimal | None
    last_reading_at: datetime | None
    last_reading_value: Decimal | None
    sample_count: int
    max_sample_gap_seconds: int | None
    polled_at: datetime  # envelope fetched_at
    source: str  # registered label, verbatim
    source_record_id: str  # TEXT NOT NULL REFERENCES raw.records

    @property
    def output_id(self) -> str:
        """Natural key rendered as text for lineage.edges.output_id."""
        return (
            f"{self.vehicle_id}|{self.service_date.isoformat()}"
            f"|{self.measure}|{self.basis}|{self.source_record_id}"
        )


def rfc3339(value: datetime) -> str:
    """Render a timezone-aware datetime as RFC 3339 in UTC with a 'Z'."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(raw: object) -> datetime | None:
    """An ISO 8601 timestamp WITH an offset, or None.

    The vendor's spec declares stat timestamps as "UTC timestamp in RFC 3339
    format"; a naive timestamp is never given a guessed zone.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _parse_reading(raw: object) -> Decimal | None:
    """A non-negative numeric reading as an exact Decimal, or None.

    JSON floats arrive as Decimal via json.loads(parse_float=Decimal), so a
    double-typed vendor value stays exact end to end — never binary float.
    """
    if isinstance(raw, bool):  # bool is an int subclass; never a reading
        return None
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, int):
        value = Decimal(raw)
    else:
        return None
    if not value.is_finite() or value < 0:
        return None
    return value


def _day_window(service_date: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) of a local service day in the declared zone.

    Day length is whatever the zone says (23 or 25 hours across a DST
    transition) — never assumed to be 24. Raises ValueError when a local
    midnight does not exist in the zone (a spring-forward at midnight): the
    day boundary is genuinely undefined there and Headway refuses to move it
    silently.
    """
    for boundary in (service_date, service_date + timedelta(days=1)):
        candidate = datetime.combine(boundary, time_of_day(0, 0), tzinfo=zone)
        roundtrip = candidate.astimezone(timezone.utc).astimezone(zone)
        if roundtrip.replace(tzinfo=None) != datetime.combine(
            boundary, time_of_day(0, 0)
        ):
            raise ValueError(
                f"local midnight of {boundary.isoformat()} does not exist in "
                f"{zone.key} (a daylight-saving transition at midnight); the "
                "service-day boundary is undefined and is never moved silently"
            )
    start = datetime.combine(service_date, time_of_day(0, 0), tzinfo=zone)
    end = datetime.combine(
        service_date + timedelta(days=1), time_of_day(0, 0), tzinfo=zone
    )
    return start, end


def _examples(items: list[str]) -> str:
    shown = sorted(items)[:_MAX_EXAMPLES]
    text = ", ".join(shown)
    remaining = len(items) - len(shown)
    if remaining > 0:
        text += f", and {remaining} more"
    return text


def normalize(
    payload: bytes,
    record_id: str,
    source: str,
    polled_at: str,
    service_day_tz: str | None,
    implausible_daily_distance_meters: Decimal = (
        DEFAULT_IMPLAUSIBLE_DAILY_DISTANCE_METERS
    ),
    sample_gap_warning_seconds: int = DEFAULT_SAMPLE_GAP_WARNING_SECONDS,
) -> tuple[list[CanonicalTelematicsDay], list[LineageEdge], list[DQFinding]]:
    """Normalize one telematics API response page.

    Returns (rows, lineage_edges, dq_findings). Every emitted row has exactly
    one lineage edge (input = the page's record_id) and carries the envelope
    source verbatim. Every gap, contradiction and unmapped series becomes a
    DQFinding citing the record_id — the measurement is skipped from
    canonical or stored as NULL, but NEVER silently.
    """
    rows: list[CanonicalTelematicsDay] = []
    edges: list[LineageEdge] = []
    findings: list[DQFinding] = []

    def refuse(issue_type: str, title: str, description: str) -> tuple:
        findings.append(
            DQFinding(
                issue_type=issue_type,
                severity=SEVERITY_BLOCKING,
                title=title,
                description=description,
                source_record_ids=[record_id],
            )
        )
        return rows, edges, findings

    # --- fail-closed source label (handoff 0015 rule) ---------------------
    if source not in REGISTERED_SOURCES:
        return refuse(
            "unregistered_telematics_source",
            f"Telematics source label {source!r} is not registered",
            f"Record {record_id} carries source {source!r}, which is not one "
            "of the REGISTERED telematics labels ("
            + ", ".join(sorted(REGISTERED_SOURCES))
            + ", per contracts/fleet-telematics.v0.schema.json). Page "
            "REFUSED — raw record retained, zero canonical rows written. "
            "Registering a new label is a contracts change; an unregistered "
            "label is never interpreted by guesswork (fail closed), and a "
            "synthetic feed must carry a '_simulated' label so simulated "
            "data can never be recorded as real.",
        )

    # --- declared service-day timezone (never guessed) --------------------
    if not service_day_tz or not service_day_tz.strip():
        return refuse(
            "telematics_timezone_undeclared",
            "No service-day timezone declared for telematics",
            f"Record {record_id} could not be normalized: a service DATE is a "
            "local wall date, and Headway never guesses a timezone. Set "
            "HEADWAY_TELEMATICS_SERVICE_DAY_TZ to the agency's IANA zone "
            "(e.g. America/New_York) — the SAME zone the connector uses "
            "(SAMSARA_SERVICE_DAY_TZ). Raw record retained; zero canonical "
            "rows written.",
        )
    try:
        zone = ZoneInfo(service_day_tz.strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        return refuse(
            "telematics_timezone_unresolvable",
            "Declared telematics service-day timezone could not be resolved",
            f"Record {record_id}: HEADWAY_TELEMATICS_SERVICE_DAY_TZ="
            f"{service_day_tz!r} is not a resolvable IANA timezone ({exc}). "
            "Raw record retained; zero canonical rows written — a service "
            "date is never derived from a guessed zone.",
        )

    polled = _parse_timestamp(polled_at)
    if polled is None:
        return refuse(
            "telematics_fetched_at_unusable",
            "Telematics page has no usable fetch timestamp",
            f"Record {record_id}: envelope fetched_at {polled_at!r} is not an "
            "ISO 8601 timestamp with a UTC offset. Rows would have no "
            "polled_at, so restatements of the same service day could not be "
            "ordered. Raw record retained; zero canonical rows written.",
        )

    # --- the vendor page --------------------------------------------------
    try:
        document = json.loads(payload, parse_float=Decimal)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return refuse(
            "undecodable_payload",
            "Telematics page is not readable JSON",
            f"Record {record_id}: {exc}. Page was not normalized; raw record "
            "retained.",
        )
    if not isinstance(document, dict) or not isinstance(document.get("data"), list):
        return refuse(
            "malformed_telematics_page",
            "Telematics page does not match the documented response shape",
            f"Record {record_id}: the vendor's OpenAPI document marks `data` "
            "(a list of vehicles) as required on this response. It is absent "
            "or not a list, so no vehicle can be read. Page was not "
            "normalized; raw record retained, nothing dropped.",
        )

    sample_problems: list[str] = []
    unmapped_series: set[str] = set()
    vehicles_with_gps_distance: set[str] = set()
    vehicles_with_ecu_odometer: set[str] = set()
    # (vehicle_id, service_date, measure, basis) -> [(time, value)]
    buckets: dict[tuple[str, date, str, str], list[tuple[datetime, Decimal]]] = {}
    labels: dict[str, str | None] = {}

    for index, entry in enumerate(document["data"], start=1):
        if not isinstance(entry, dict):
            sample_problems.append(
                f"data[{index}] is not an object and was skipped"
            )
            continue
        vehicle_id = entry.get("id")
        if not isinstance(vehicle_id, str) or not vehicle_id.strip():
            sample_problems.append(
                f"data[{index}] has no usable vehicle `id` (the vendor "
                "declares it a string) and was skipped; a vehicle identity "
                "is never invented"
            )
            continue
        vehicle_id = vehicle_id.strip()
        label = entry.get("name")
        labels[vehicle_id] = label.strip() if isinstance(label, str) and label.strip() else None

        for key, raw_series in entry.items():
            if key in _IDENTITY_KEYS:
                continue
            if key not in SAMSARA_SERIES:
                unmapped_series.add(key)
                continue
            measure, basis, _unit = SAMSARA_SERIES[key]
            if not isinstance(raw_series, list):
                sample_problems.append(
                    f"vehicle {vehicle_id} series {key!r} is not a list and "
                    "was skipped"
                )
                continue
            for position, sample in enumerate(raw_series, start=1):
                if not isinstance(sample, dict):
                    sample_problems.append(
                        f"vehicle {vehicle_id} {key}[{position}] is not an "
                        "object"
                    )
                    continue
                when = _parse_timestamp(sample.get("time"))
                if when is None:
                    sample_problems.append(
                        f"vehicle {vehicle_id} {key}[{position}] has no ISO "
                        f"8601 timestamp with a UTC offset "
                        f"({sample.get('time')!r}); the zone is never guessed"
                    )
                    continue
                reading = _parse_reading(sample.get("value"))
                if reading is None:
                    sample_problems.append(
                        f"vehicle {vehicle_id} {key}[{position}] value "
                        f"{sample.get('value')!r} is not a non-negative number"
                    )
                    continue
                if basis == "gps_distance":
                    vehicles_with_gps_distance.add(vehicle_id)
                if basis == "ecu_odometer":
                    vehicles_with_ecu_odometer.add(vehicle_id)
                local_date = when.astimezone(zone).date()
                buckets.setdefault(
                    (vehicle_id, local_date, measure, basis), []
                ).append((when, reading))

    # --- one row per (vehicle, service date, measure, basis) --------------
    regressions: list[str] = []
    implausible: list[str] = []
    thin_days: list[str] = []
    gapped_days: list[str] = []
    undefined_boundaries: list[str] = []

    for (vehicle_id, service_date, measure, basis) in sorted(
        buckets, key=lambda k: (k[0], k[1], k[2], k[3])
    ):
        samples = sorted(buckets[(vehicle_id, service_date, measure, basis)])
        try:
            window_start, window_end = _day_window(service_date, zone)
        except ValueError as exc:
            undefined_boundaries.append(
                f"{vehicle_id} on {service_date.isoformat()} ({exc})"
            )
            continue

        first_at, first_value = samples[0]
        last_at, last_value = samples[-1]
        sample_count = len(samples)

        max_gap: int | None = None
        if sample_count >= 2:
            max_gap = max(
                int((b[0] - a[0]).total_seconds())
                for a, b in zip(samples, samples[1:])
            )

        value: Decimal | None = None
        if sample_count >= 2:
            if last_value < first_value:
                regressions.append(
                    f"{vehicle_id} {basis} on {service_date.isoformat()}: "
                    f"{first_value} -> {last_value}"
                )
            else:
                value = last_value - first_value

        if value is not None and measure == "distance" and (
            value > implausible_daily_distance_meters
        ):
            implausible.append(
                f"{vehicle_id} {basis} on {service_date.isoformat()}: "
                f"{value} meters"
            )
        if sample_count < 2:
            thin_days.append(
                f"{vehicle_id} {basis} on {service_date.isoformat()} "
                f"({sample_count} reading(s))"
            )
        if (
            value is not None
            and value > 0
            and max_gap is not None
            and max_gap > sample_gap_warning_seconds
        ):
            gapped_days.append(
                f"{vehicle_id} {basis} on {service_date.isoformat()}: "
                f"{max_gap} s between readings"
            )

        row = CanonicalTelematicsDay(
            window_start=window_start,
            window_end=window_end,
            service_date=service_date,
            vehicle_id=vehicle_id,
            vehicle_label=labels.get(vehicle_id),
            measure=measure,
            basis=basis,
            unit=SAMSARA_SERIES_UNIT[basis],
            reading_kind=READING_KIND_CUMULATIVE,
            value=value,
            first_reading_at=first_at,
            first_reading_value=first_value,
            last_reading_at=last_at,
            last_reading_value=last_value,
            sample_count=sample_count,
            max_sample_gap_seconds=max_gap,
            polled_at=polled,
            source=source,
            source_record_id=record_id,
        )
        rows.append(row)
        edges.append(
            LineageEdge(
                output_kind=OUTPUT_KIND,
                output_id=row.output_id,
                transform_name=TRANSFORM_NAME,
                transform_version=TRANSFORM_VERSION,
                input_kind=INPUT_KIND,
                input_id=record_id,
            )
        )

    # --- aggregated data-quality findings ---------------------------------
    if sample_problems:
        findings.append(
            DQFinding(
                issue_type="malformed_telematics_sample",
                severity=SEVERITY_WARNING,
                title="Some telematics readings could not be read",
                description=(
                    f"Record {record_id}: {len(sample_problems)} reading(s) or "
                    "vehicle entries were quarantined, not dropped silently — "
                    + _examples(sample_problems)
                    + ". Every other reading in the page still landed."
                ),
                source_record_ids=[record_id],
            )
        )

    if unmapped_series:
        findings.append(
            DQFinding(
                issue_type="telematics_unmapped_series",
                severity=SEVERITY_INFO,
                title="Telematics page carried series Headway does not map",
                description=(
                    f"Record {record_id} contained stat series "
                    + _examples(sorted(unmapped_series))
                    + " that this normalizer has no contract mapping for, so "
                    "they produced no canonical rows. The raw record retains "
                    "them byte-for-byte and can be replayed once a mapping is "
                    "added — nothing was lost."
                ),
                source_record_ids=[record_id],
            )
        )

    missing_ecu = sorted(vehicles_with_gps_distance - vehicles_with_ecu_odometer)
    if missing_ecu:
        findings.append(
            DQFinding(
                issue_type="telematics_ecu_odometer_absent",
                severity=SEVERITY_WARNING,
                title="No engine-computer odometer for some vehicles",
                description=(
                    f"Record {record_id}: {len(missing_ecu)} vehicle(s) "
                    "reported GPS-based distance but no odometer reading from "
                    "the vehicle's own engine computer — "
                    + _examples(missing_ecu)
                    + ". The vendor documents this as missing diagnostic "
                    "coverage for that vehicle. Headway records the GPS "
                    "figures under their own measurement basis and does NOT "
                    "substitute them for the engine-computer odometer; the "
                    "two are never treated as the same number."
                ),
                source_record_ids=[record_id],
            )
        )

    if regressions:
        findings.append(
            DQFinding(
                issue_type="telematics_counter_regression",
                severity=SEVERITY_WARNING,
                title="A telematics counter went backwards",
                description=(
                    f"Record {record_id}: {len(regressions)} vehicle-day "
                    "series ended LOWER than it started — "
                    + _examples(regressions)
                    + ". A running total cannot decrease, so this usually "
                    "means the tracking device was replaced or reconfigured "
                    "(the vendor documents GPS distance as counting since the "
                    "device was installed). Both readings are kept and the "
                    "distance is left blank: a contradiction is surfaced, "
                    "never repaired."
                ),
                source_record_ids=[record_id],
            )
        )

    if implausible:
        findings.append(
            DQFinding(
                issue_type="telematics_implausible_distance",
                severity=SEVERITY_WARNING,
                title="A one-day distance looks implausibly large",
                description=(
                    f"Record {record_id}: {len(implausible)} vehicle-day "
                    "series exceeded "
                    f"{implausible_daily_distance_meters} meters in one "
                    "service day — " + _examples(implausible) + ". This "
                    "threshold is a Headway review prompt for a person, not a "
                    "vendor or regulatory limit; the measured value is stored "
                    "exactly as measured and nothing is capped or corrected."
                ),
                source_record_ids=[record_id],
            )
        )

    if thin_days:
        findings.append(
            DQFinding(
                issue_type="telematics_insufficient_samples",
                severity=SEVERITY_INFO,
                title="Not enough readings to measure a day's movement",
                description=(
                    f"Record {record_id}: {len(thin_days)} vehicle-day series "
                    "had fewer than two readings — "
                    + _examples(thin_days)
                    + ". A running total needs two readings to measure a "
                    "difference, so the amount is left blank rather than "
                    "assumed to be zero. The reading that did arrive is kept."
                ),
                source_record_ids=[record_id],
            )
        )

    if gapped_days:
        findings.append(
            DQFinding(
                issue_type="telematics_sample_gap",
                severity=SEVERITY_WARNING,
                title="A long gap between readings on a day with movement",
                description=(
                    f"Record {record_id}: {len(gapped_days)} vehicle-day "
                    "series recorded movement across a gap longer than "
                    f"{sample_gap_warning_seconds} seconds between "
                    "consecutive readings — "
                    + _examples(gapped_days)
                    + ". The total between the two readings is measured, but "
                    "WHEN inside the gap the vehicle moved is unknown and is "
                    "never spread across it. Each row also carries its own "
                    "largest gap so this stays visible per record."
                ),
                source_record_ids=[record_id],
            )
        )

    if undefined_boundaries:
        findings.append(
            DQFinding(
                issue_type="telematics_service_day_boundary_undefined",
                severity=SEVERITY_WARNING,
                title="A service day has no defined start in the declared timezone",
                description=(
                    f"Record {record_id}: {len(undefined_boundaries)} "
                    "vehicle-day series fell on a date whose local midnight "
                    "does not exist in the declared timezone (a daylight-"
                    "saving change at midnight) — "
                    + _examples(undefined_boundaries)
                    + ". Those series were not written, because moving a "
                    "service-day boundary silently would change what the day "
                    "means. Raw record retained; replay after declaring how "
                    "the agency defines that day."
                ),
                source_record_ids=[record_id],
            )
        )

    if not document["data"]:
        findings.append(
            DQFinding(
                issue_type="empty_telematics_page",
                severity=SEVERITY_INFO,
                title="Telematics page contained no vehicles",
                description=(
                    f"Record {record_id}: the page's `data` list is empty. "
                    "Nothing normalized; recorded so an empty window is "
                    "visible, not silent."
                ),
                source_record_ids=[record_id],
            )
        )

    return rows, edges, findings
