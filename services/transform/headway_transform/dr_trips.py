"""Normalizer: raw.dr.trips -> canonical.dr_trips (handoff 0013, DR module v0).

Parses one demand_response_trip v0 CSV file (stdlib csv; wire contract:
contracts/demand-response-trip.v0.schema.json + demand-response-trip.v0.md)
into CanonicalDrTrip dataclasses per migration 0021, column-for-column, with
one LineageEdge per row back to the file's content-addressed record_id, and
a DQFinding for every row that could not be normalized — never a silent
skip.

Regulatory field semantics are pointers to services/calc/REGULATORY_TRACKER.md
("Verified — Demand Response / on-demand reporting", 2026 NTD Full Reporting
Policy Manual pp. 33, 37-39, 129-139, 143-144) — verify against current
published guidance before extending, never from memory.

Contradictions are quarantined, never repaired (fail loudly): a dropoff
before its pickup, a decreasing odometer pair, a sponsored trip without a
sponsor label (or a sponsor label on an unsponsored trip), and a no-show
carrying boardings (Exhibit 36 as quoted in the tracker: a no-show is
revenue time but never a boarding) are all malformed rows. Missing OPTIONAL
values stay NULL — an unmeasured distance is a flagged gap downstream, never
a fabricated 0.

Simulated-data rule (handoff 0005, binding; applied to DR by handoff 0013):
the envelope source ('dr' | 'dr_simulated' | a vendor label bound to a
machine key) is carried verbatim into every row's source column so simulated
records stay permanently distinguishable in provenance.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from .model import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    DQFinding,
    LineageEdge,
)
from .row_guard import field_problems, iter_rows

TRANSFORM_NAME = "normalize_dr_trips"
# 0.1.1: per-row parse quarantine (2026-07-13 hardening pass) — a crafted
# row (oversized field / NUL byte / stray quote) becomes ONE malformed_dr_trip
# finding; the rest of the file still normalizes.
TRANSFORM_VERSION = "0.1.1"

TOPIC = "raw.dr.trips"
OUTPUT_KIND = "canonical.dr_trips"
INPUT_KIND = "raw.records"

# The contract's "required" list (demand-response-trip.v0.schema.json).
REQUIRED_FIELDS = (
    "dr_trip_id",
    "service_date",
    "vehicle_id",
    "mode",
    "tos",
    "pickup_timestamp",
    "dropoff_timestamp",
    "riders",
    "attendants_companions",
    "ada_related",
    "sponsored",
    "no_show",
)

TOS_VALUES = frozenset({"DO", "PT", "TX", "TN"})
DISTANCE_SOURCES = frozenset({"odometer", "gps"})
INTERRUPTIONS = frozenset({"none", "lunch", "fuel", "garage_return", "dispatch_return"})


@dataclass(frozen=True)
class CanonicalDrTrip:
    """One canonical.dr_trips row (handoff 0013 / migration 0021)."""

    pickup_timestamp: datetime  # TIMESTAMPTZ NOT NULL (hypertable time)
    service_date: date  # DATE NOT NULL
    dr_trip_id: str  # TEXT NOT NULL
    vehicle_id: str  # TEXT NOT NULL
    tos: str  # TEXT NOT NULL — DO|PT|TX|TN
    request_timestamp: datetime | None
    dispatch_timestamp: datetime | None
    dropoff_timestamp: datetime  # TIMESTAMPTZ NOT NULL, >= pickup
    pickup_lat: float | None
    pickup_lon: float | None
    dropoff_lat: float | None
    dropoff_lon: float | None
    onboard_miles: Decimal | None  # NUMERIC — NULL preserved, never 0
    distance_source: str | None  # 'odometer' | 'gps'
    pickup_odometer_miles: Decimal | None
    dropoff_odometer_miles: Decimal | None
    riders: int  # INTEGER NOT NULL >= 0
    attendants_companions: int  # INTEGER NOT NULL >= 0 (non-employee rule at source)
    ada_related: bool
    sponsored: bool
    sponsor: str | None  # required iff sponsored
    no_show: bool
    interruption_after: str  # enum, default 'none'
    driver_shift_id: str | None
    dispatching_point_id: str | None
    source: str  # envelope source ('dr' | 'dr_simulated' | vendor label)
    source_record_id: str  # TEXT NOT NULL REFERENCES raw.records

    @property
    def output_id(self) -> str:
        """Natural key rendered as text for lineage.edges.output_id."""
        return (
            f"{self.dr_trip_id}|{rfc3339(self.pickup_timestamp)}"
            f"|{self.source_record_id}"
        )


def rfc3339(dt: datetime) -> str:
    """Render a timezone-aware datetime as RFC 3339 in UTC with a 'Z' suffix."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _cell(row: dict[str, str], name: str) -> str:
    """A stripped row value ('' for an absent column)."""
    return (row.get(name) or "").strip()


def normalize(
    csv_bytes: bytes, record_id: str, source: str
) -> tuple[list[CanonicalDrTrip], list[LineageEdge], list[DQFinding]]:
    """Normalize one demand_response_trips CSV file.

    Returns (rows, lineage_edges, dq_findings). Every emitted row has exactly
    one lineage edge (input = the file's record_id) and carries the envelope
    source verbatim; every row that cannot be normalized is a DQFinding
    ('malformed_dr_trip' citing the record_id and row number) — the row is
    skipped from canonical, but NEVER silently.
    """
    rows: list[CanonicalDrTrip] = []
    edges: list[LineageEdge] = []
    findings: list[DQFinding] = []

    try:
        # utf-8-sig: CSV exports commonly carry a BOM.
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        findings.append(
            DQFinding(
                issue_type="undecodable_payload",
                severity=SEVERITY_BLOCKING,
                title="demand_response_trips payload is not readable CSV text",
                description=(
                    f"Record {record_id}: {exc}. File was not normalized; "
                    "raw record retained."
                ),
                source_record_ids=[record_id],
            )
        )
        return rows, edges, findings

    def _malformed(index: int, problems: list[str]) -> DQFinding:
        return DQFinding(
            issue_type="malformed_dr_trip",
            severity=SEVERITY_WARNING,
            title="demand_response_trip row could not be normalized",
            description=(
                f"Record {record_id}, demand_response_trips row {index}: "
                + "; ".join(problems)
                + ". Row quarantined, not dropped silently."
            ),
            source_record_ids=[record_id],
        )

    row_count = 0
    reader = csv.DictReader(io.StringIO(text, newline=""))
    for index, row, parse_error in iter_rows(reader):
        row_count += 1

        # Per-row parse quarantine (2026-07-13 hardening pass): a csv-level
        # error (e.g. field over the size limit) or a structurally hostile
        # field (NUL byte; an unterminated quote's absorbed-line merge) is
        # ONE quarantined row — it can no longer abort the whole file.
        if parse_error is not None:
            findings.append(_malformed(index, [f"CSV parse error: {parse_error}"]))
            continue
        guard = field_problems(row)
        if guard:
            findings.append(_malformed(index, guard))
            continue

        problems: list[str] = []

        missing = [name for name in REQUIRED_FIELDS if not _cell(row, name)]
        if missing:
            problems.append(
                "missing required field(s) "
                + ", ".join(missing)
                + " (required per demand-response-trip.v0.schema.json)"
            )

        mode = _cell(row, "mode")
        if mode and mode != "DR":
            problems.append(
                f"mode {mode!r} is not 'DR' (this contract carries demand "
                "response only)"
            )

        tos = _cell(row, "tos")
        if tos and tos not in TOS_VALUES:
            problems.append(
                f"tos {tos!r} is not in the contract enum DO|PT|TX|TN"
            )

        def _timestamp(name: str) -> datetime | None:
            raw = _cell(row, name)
            if not raw:
                return None
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                problems.append(f"{name} {raw!r} is not an ISO 8601 datetime")
                return None
            if value.tzinfo is None:
                problems.append(
                    f"{name} {raw!r} carries no UTC offset (the contract "
                    "requires one); the timezone is never guessed"
                )
                return None
            return value

        pickup_timestamp = _timestamp("pickup_timestamp")
        dropoff_timestamp = _timestamp("dropoff_timestamp")
        request_timestamp = _timestamp("request_timestamp")
        dispatch_timestamp = _timestamp("dispatch_timestamp")
        if (
            pickup_timestamp is not None
            and dropoff_timestamp is not None
            and dropoff_timestamp < pickup_timestamp
        ):
            problems.append(
                f"dropoff_timestamp {rfc3339(dropoff_timestamp)} precedes "
                f"pickup_timestamp {rfc3339(pickup_timestamp)} — a "
                "contradiction, never repaired"
            )

        service_date: date | None = None
        raw_date = _cell(row, "service_date")
        if raw_date:
            try:
                service_date = date.fromisoformat(raw_date)
            except ValueError:
                problems.append(f"service_date {raw_date!r} is not an ISO 8601 date")

        def _int_field(name: str) -> int | None:
            raw = _cell(row, name)
            if not raw:
                return None  # required-ness already recorded above
            try:
                value = int(raw)
            except ValueError:
                problems.append(f"{name} {raw!r} is not an integer")
                return None
            if value < 0:
                problems.append(f"{name} {value} violates the contract minimum 0")
                return None
            return value

        riders = _int_field("riders")
        attendants = _int_field("attendants_companions")

        def _bool_field(name: str) -> bool | None:
            raw = _cell(row, name)
            if not raw:
                return None  # required-ness already recorded above
            lowered = raw.lower()
            if lowered == "true":
                return True
            if lowered == "false":
                return False
            problems.append(f"{name} {raw!r} is not the literal true or false")
            return None

        ada_related = _bool_field("ada_related")
        sponsored = _bool_field("sponsored")
        no_show = _bool_field("no_show")

        def _decimal_field(name: str) -> Decimal | None:
            raw = _cell(row, name)
            if not raw:
                return None
            try:
                value = Decimal(raw)
            except InvalidOperation:
                problems.append(f"{name} {raw!r} is not a decimal number")
                return None
            if value < 0:
                problems.append(f"{name} {value} violates the contract minimum 0")
                return None
            return value

        onboard_miles = _decimal_field("onboard_miles")
        pickup_odometer = _decimal_field("pickup_odometer_miles")
        dropoff_odometer = _decimal_field("dropoff_odometer_miles")
        if (
            pickup_odometer is not None
            and dropoff_odometer is not None
            and dropoff_odometer < pickup_odometer
        ):
            problems.append(
                f"dropoff_odometer_miles {dropoff_odometer} is less than "
                f"pickup_odometer_miles {pickup_odometer} — a decreasing "
                "odometer is a contradiction, never repaired"
            )

        def _float_field(name: str, low: float, high: float) -> float | None:
            raw = _cell(row, name)
            if not raw:
                return None
            try:
                value = float(raw)
            except ValueError:
                problems.append(f"{name} {raw!r} is not a number")
                return None
            if not low <= value <= high:
                problems.append(f"{name} {value} out of range [{low}, {high}]")
                return None
            return value

        pickup_lat = _float_field("pickup_lat", -90.0, 90.0)
        pickup_lon = _float_field("pickup_lon", -180.0, 180.0)
        dropoff_lat = _float_field("dropoff_lat", -90.0, 90.0)
        dropoff_lon = _float_field("dropoff_lon", -180.0, 180.0)

        distance_source = _cell(row, "distance_source") or None
        if distance_source is not None and distance_source not in DISTANCE_SOURCES:
            problems.append(
                f"distance_source {distance_source!r} is not in the contract "
                "enum odometer|gps"
            )

        interruption_after = _cell(row, "interruption_after") or "none"
        if interruption_after not in INTERRUPTIONS:
            problems.append(
                f"interruption_after {interruption_after!r} is not in the "
                "contract enum none|lunch|fuel|garage_return|dispatch_return"
            )

        sponsor = _cell(row, "sponsor") or None
        if sponsored is True and sponsor is None:
            problems.append(
                "sponsored is true but sponsor is empty (the contract "
                "requires the sponsoring program's label)"
            )
        if sponsored is False and sponsor is not None:
            problems.append(
                f"sponsor {sponsor!r} present on an unsponsored trip — a "
                "contradiction, never repaired"
            )

        if no_show is True and ((riders or 0) > 0 or (attendants or 0) > 0):
            problems.append(
                f"no_show is true but the row carries boardings (riders="
                f"{riders}, attendants_companions={attendants}) — Exhibit 36 "
                "as quoted in the tracker: a no-show is revenue time but "
                "never a boarding"
            )

        if problems:
            findings.append(_malformed(index, problems))
            continue

        assert (
            pickup_timestamp is not None
            and dropoff_timestamp is not None
            and service_date is not None
            and riders is not None
            and attendants is not None
            and ada_related is not None
            and sponsored is not None
            and no_show is not None
        )
        trip = CanonicalDrTrip(
            pickup_timestamp=pickup_timestamp,
            service_date=service_date,
            dr_trip_id=_cell(row, "dr_trip_id"),
            vehicle_id=_cell(row, "vehicle_id"),
            tos=tos,
            request_timestamp=request_timestamp,
            dispatch_timestamp=dispatch_timestamp,
            dropoff_timestamp=dropoff_timestamp,
            pickup_lat=pickup_lat,
            pickup_lon=pickup_lon,
            dropoff_lat=dropoff_lat,
            dropoff_lon=dropoff_lon,
            onboard_miles=onboard_miles,
            distance_source=distance_source,
            pickup_odometer_miles=pickup_odometer,
            dropoff_odometer_miles=dropoff_odometer,
            riders=riders,
            attendants_companions=attendants,
            ada_related=ada_related,
            sponsored=sponsored,
            sponsor=sponsor,
            no_show=no_show,
            interruption_after=interruption_after,
            driver_shift_id=_cell(row, "driver_shift_id") or None,
            dispatching_point_id=_cell(row, "dispatching_point_id") or None,
            source=source,
            source_record_id=record_id,
        )
        rows.append(trip)
        edges.append(
            LineageEdge(
                output_kind=OUTPUT_KIND,
                output_id=trip.output_id,
                transform_name=TRANSFORM_NAME,
                transform_version=TRANSFORM_VERSION,
                input_kind=INPUT_KIND,
                input_id=record_id,
            )
        )

    if row_count == 0:
        findings.append(
            DQFinding(
                issue_type="empty_dr_trips_file",
                severity=SEVERITY_INFO,
                title="demand_response_trips file contains no data rows",
                description=(
                    f"Record {record_id}: the CSV has no data rows (header "
                    "only, or empty file). Nothing normalized; recorded so "
                    "an empty delivery is visible, not silent."
                ),
                source_record_ids=[record_id],
            )
        )

    return rows, edges, findings
