"""Resolve a vendor export's own trip identifiers against the agency's GTFS.

The first agency's APC export calls a trip ``"12 - 12WD - 21:30"`` — route,
pattern, start time, the way its schedulers say it — while the GTFS
``trip_id`` for the same trip is an opaque id. Until the two are joined,
passenger counts do not attach to operated trips and every UPT figure over
that data is blocked (handoff 0031).

**Everything agency-specific is configuration.** How the vendor's trip name
comes apart, which GTFS field each part matches, which column carries the
direction and what its values mean, and how the export dates a trip that runs
past midnight are all declared in
``adapters/<vendor>/<product>/resolution.v0.yaml``, validated against
``contracts/adapter-resolution.v0.schema.json`` with the same discipline as
the mapping spec. No agency's vocabulary appears in this module.

**Three outcomes, all explicit, none of them a guess:**

- ``resolved`` — exactly one scheduled trip matches. The canonical row's
  ``trip_id`` becomes that trip, and the vendor's own identifier is preserved
  alongside it in ``vendor_trip_ref``. It is never overwritten: it is the
  agency's vocabulary and the audit path back into their system.
- ``ambiguous`` — more than one scheduled trip matches. The row is NOT
  resolved and a finding names the candidates. Picking the first would be
  inventing a fact, and nothing downstream could tell.
- ``unmatched`` — no scheduled trip matches. A finding states what was
  parsed, what was searched, and (where it can) the one thing that would have
  made it match, so a human can see *why* rather than being told *that*.

The refusal case is deliberate too: while the resolution spec's direction
mapping is not confirmed by the agency, the resolver resolves NOTHING and
says so once per file. GTFS assigns no meaning to ``direction_id`` 0 and 1,
so which vendor value means which is an agency fact. Guessing it would attach
half the passenger counts to the wrong trip, and every number downstream
would look fine.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import jsonschema
import yaml

from ..model import SEVERITY_INFO, SEVERITY_WARNING, DQFinding
from ..schedule_index import DAY_SECONDS, ScheduleIndex
from .spec import MappingSpec

_DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "contracts"
_CONTRACTS_DIR = Path(os.environ.get("HEADWAY_CONTRACTS_DIR", _DEFAULT_CONTRACTS_DIR))

RESOLUTION_SCHEMA_PATH = _CONTRACTS_DIR / "adapter-resolution.v0.schema.json"

with open(RESOLUTION_SCHEMA_PATH, encoding="utf-8") as _f:
    RESOLUTION_SCHEMA: dict = json.load(_f)

_RESOLUTION_VALIDATOR = jsonschema.Draft202012Validator(RESOLUTION_SCHEMA)

#: The resolver's transform name in lineage.edges, suffixed with the source
#: label so an agency with two vendor feeds can tell them apart.
TRANSFORM_NAME_PREFIX = "resolve_trips"

#: Outcome vocabulary. These three strings are the canonical
#: passenger_events.trip_resolution CHECK values (migration 0036).
RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
UNMATCHED = "unmatched"

#: How many distinct vendor trip identifiers a finding names before it stops
#: enumerating. The TRUE total is always stated; the cap only bounds the
#: list, and the ids stay in the finding as the footnote, never the headline
#: (handoff 0029).
NAMED_CAP = 25


class ResolutionSpecError(Exception):
    """A resolution spec failed validation. Carries every violation found."""

    def __init__(self, path: Path | str, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(
            f"resolution spec {path} is invalid ({len(errors)} problem(s)): "
            + "; ".join(errors)
        )


@dataclass(frozen=True)
class DirectionRule:
    """The vendor's direction vocabulary mapped onto GTFS direction_id."""

    from_column: str
    confirmed: bool
    values: dict[str, int]
    confirmed_by: Optional[str] = None
    confirmed_on: Optional[str] = None
    unconfirmed_reason: Optional[str] = None


@dataclass(frozen=True)
class ResolutionSpec:
    """A validated resolution.v0.yaml, ready for the resolver."""

    path: str
    source_label: str
    target_contract: str
    #: Where the vendor identifier is read from: a mapped target field, or a
    #: raw source column. Exactly one is set (schema-enforced).
    vendor_field: Optional[str]
    vendor_column: Optional[str]
    separator: str
    components: tuple[str, ...]
    strip_components: bool
    route_component: str
    route_gtfs_field: str
    start_component: str
    start_format: str
    direction: DirectionRule
    service_field: str
    service_day_rollover: str
    stop_column: Optional[str]
    stop_match_order: tuple[str, ...]
    #: SHA-256 (first 12 hex chars) of the spec file's exact bytes — the
    #: content-addressed config version stamped into resolution lineage.
    spec_sha12: str
    raw: dict = field(repr=False)

    def required_source_columns(self) -> set[str]:
        """Raw vendor columns this spec reads (added to the file's checks)."""
        needed = {self.direction.from_column}
        if self.vendor_column:
            needed.add(self.vendor_column)
        if self.stop_column:
            needed.add(self.stop_column)
        return needed

    @property
    def transform_name(self) -> str:
        return f"{TRANSFORM_NAME_PREFIX}:{self.source_label}"


def load_resolution_spec(
    path: Path | str, mapping: Optional[MappingSpec] = None
) -> ResolutionSpec:
    """Load one resolution.v0.yaml: schema-validate, then semantic checks.

    ``mapping`` is the sibling mapping spec; when given, the cross-spec
    checks run too (label agreement, referenced target fields actually
    mapped, referenced source columns actually declared). Raises
    ResolutionSpecError listing EVERY violation — a resolution spec is never
    partially accepted, because a half-understood join key is how a
    passenger count ends up on the wrong trip.
    """
    path = Path(path)
    spec_bytes = path.read_bytes()
    try:
        document = yaml.safe_load(spec_bytes)
    except yaml.YAMLError as exc:
        raise ResolutionSpecError(path, [f"not valid YAML: {exc}"]) from exc

    if isinstance(document, dict):
        document = _dates_to_strings(document)
    schema_errors = sorted(
        _RESOLUTION_VALIDATOR.iter_errors(document), key=lambda e: list(e.path)
    )
    if schema_errors:
        raise ResolutionSpecError(
            path,
            [
                f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
                for err in schema_errors
            ],
        )
    assert isinstance(document, dict)

    problems: list[str] = []
    trip = document["trip"]
    parse = trip["parse"]
    match = trip["match"]
    components = tuple(parse["components"])

    for clause, key in (("route", "component"), ("start_time", "component")):
        referenced = match[clause][key]
        if referenced not in components:
            problems.append(
                f"trip/match/{clause}/{key}: {referenced!r} is not one of the "
                f"parsed components {list(components)} — the join key can "
                "only match on something the parse produced"
            )

    start_format = match["start_time"]["format"]
    if "%H" not in start_format or "%M" not in start_format:
        problems.append(
            f"trip/match/start_time/format: {start_format!r} carries no %H "
            "and %M — a scheduled start time is matched to the minute, and a "
            "format that cannot express one would match by accident"
        )

    direction_doc = match["direction"]
    values = direction_doc.get("values") or {}
    if direction_doc["confirmed"] and not values:
        problems.append(
            "trip/match/direction: confirmed is true but no values are "
            "mapped — a confirmed direction convention must say what the "
            "vendor's values mean"
        )

    stop_doc = document.get("stop")

    if mapping is not None:
        if document["source_label"] != mapping.source_label:
            problems.append(
                f"source_label {document['source_label']!r} does not match the "
                f"sibling mapping spec's {mapping.source_label!r} — a "
                "resolution spec configures exactly the adapter it sits next "
                "to; resolving one vendor's rows with another's key is never "
                "attempted"
            )
        if document["target_contract"] != mapping.target_contract:
            problems.append(
                f"target_contract {document['target_contract']!r} does not "
                f"match the mapping spec's {mapping.target_contract!r}"
            )
        mapped_targets = {fd.target for fd in mapping.fields}
        for emission in mapping.emissions:
            mapped_targets.update(fd.target for fd in emission.effective_fields)
        for where, referenced in (
            ("trip/vendor_identifier/from_field", trip["vendor_identifier"].get("from_field")),
            ("trip/match/service/from_field", match["service"]["from_field"]),
        ):
            if referenced and referenced not in mapped_targets:
                problems.append(
                    f"{where}: {referenced!r} is not a target field the "
                    f"mapping spec {mapping.path} maps — resolution reads the "
                    "mapped record, so an unmapped field is always absent"
                )
        if not mapping.header:
            declared = set(mapping.columns)
            reads = {direction_doc["from_column"]}
            if trip["vendor_identifier"].get("from_column"):
                reads.add(trip["vendor_identifier"]["from_column"])
            if stop_doc:
                reads.add(stop_doc["from_column"])
            unresolvable = sorted(reads - declared)
            if unresolvable:
                problems.append(
                    "reads source column(s) "
                    + ", ".join(repr(c) for c in unresolvable)
                    + " that the mapping spec's declared positional columns "
                    "do not contain (headerless format — positions are "
                    "declared, never guessed)"
                )

    if problems:
        raise ResolutionSpecError(path, problems)

    return ResolutionSpec(
        path=str(path),
        source_label=document["source_label"],
        target_contract=document["target_contract"],
        vendor_field=trip["vendor_identifier"].get("from_field"),
        vendor_column=trip["vendor_identifier"].get("from_column"),
        separator=parse["separator"],
        components=components,
        strip_components=parse.get("strip", True),
        route_component=match["route"]["component"],
        route_gtfs_field=match["route"].get("gtfs_field", "route_short_name"),
        start_component=match["start_time"]["component"],
        start_format=start_format,
        direction=DirectionRule(
            from_column=direction_doc["from_column"],
            confirmed=bool(direction_doc["confirmed"]),
            values={str(k): int(v) for k, v in values.items()},
            confirmed_by=direction_doc.get("confirmed_by"),
            confirmed_on=direction_doc.get("confirmed_on"),
            unconfirmed_reason=direction_doc.get("unconfirmed_reason"),
        ),
        service_field=match["service"]["from_field"],
        service_day_rollover=match["service"]["service_day_rollover"],
        stop_column=(stop_doc or {}).get("from_column"),
        stop_match_order=tuple((stop_doc or {}).get("match_order") or ()),
        spec_sha12=hashlib.sha256(spec_bytes).hexdigest()[:12],
        raw=document,
    )


def _dates_to_strings(value: object) -> object:
    """Normalize YAML 1.1 date scalars to ISO strings (see spec.py)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _dates_to_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dates_to_strings(v) for v in value]
    return value


@dataclass(frozen=True)
class TripNameParse:
    """Outcome of parsing ONE vendor trip name per a spec's parse rules.

    This is the parse half of :meth:`TripResolver.resolve_trip`, split out
    so other consumers of the same vendor vocabulary — the block-label
    derivation (handoff 0038) joins the agency's trip->block export through
    exactly this parse — reuse the resolver's reading of a trip name instead
    of reimplementing it. One parse, one meaning: 'route - pattern - start'
    comes apart the same way everywhere.

    ``reason`` is empty on success and otherwise carries the plain-language
    explanation resolve_trip has always reported (what split how, what was
    assumed: nothing).
    """

    parsed: Optional[dict[str, str]]
    start_seconds: Optional[int]
    reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.reason

    @property
    def parsed_text(self) -> str:
        return ", ".join(f"{k} {v!r}" for k, v in (self.parsed or {}).items())


def parse_trip_name(spec: ResolutionSpec, vendor_ref: str) -> TripNameParse:
    """Parse a vendor trip name exactly as the spec declares — nothing more.

    Splits on the declared separator into the declared components, strips
    when declared, and reads the start-time component with the declared
    format. No matching happens here: the result is the parsed components
    plus the start time as GTFS service-day seconds, or a stated reason.
    """
    parts = vendor_ref.split(spec.separator)
    if spec.strip_components:
        parts = [p.strip() for p in parts]
    if len(parts) != len(spec.components):
        return TripNameParse(
            parsed=None,
            start_seconds=None,
            reason=(
                f"the trip name splits on {spec.separator!r} into "
                f"{len(parts)} part(s), but this agency's trip names are "
                f"configured as {len(spec.components)}: "
                f"{', '.join(spec.components)}. Nothing was assumed about "
                "which part is which"
            ),
        )
    parsed = dict(zip(spec.components, parts))
    parsed_text = ", ".join(f"{k} {v!r}" for k, v in parsed.items())

    raw_start = parsed[spec.start_component]
    try:
        start = datetime.strptime(raw_start, spec.start_format)
    except ValueError:
        return TripNameParse(
            parsed=parsed,
            start_seconds=None,
            reason=(
                f"the start time {raw_start!r} in the trip name does not "
                f"read as {spec.start_format!r} (parsed: {parsed_text})"
            ),
        )
    return TripNameParse(
        parsed=parsed,
        start_seconds=start.hour * 3600 + start.minute * 60 + start.second,
    )


@dataclass(frozen=True)
class TripOutcome:
    """What resolution decided about ONE vendor row's trip identity."""

    status: str  # RESOLVED | AMBIGUOUS | UNMATCHED
    vendor_ref: str
    trip_id: Optional[str] = None
    candidates: tuple[str, ...] = ()
    #: Plain-language subject in the AGENCY's vocabulary — route, time,
    #: direction, date — for the finding's headline (handoff 0029).
    subject: str = ""
    #: Why it did not resolve, and what was searched. Empty when resolved.
    reason: str = ""


@dataclass(frozen=True)
class StopOutcome:
    """What resolution found out about ONE vendor row's stop identifier."""

    vendor_ref: str
    matched: bool
    matched_on: Optional[str] = None
    stop_ids: tuple[str, ...] = ()


class TripResolver:
    """One adapter's resolution spec bound to one schedule index."""

    def __init__(self, spec: ResolutionSpec, index: ScheduleIndex) -> None:
        self.spec = spec
        self.index = index

    # --- refusal --------------------------------------------------------

    @property
    def active(self) -> bool:
        """False while the agency has not confirmed the direction mapping."""
        return self.spec.direction.confirmed

    def refusal_finding(self, record_id: str, source: str) -> DQFinding:
        """The one finding a refusing resolver emits per file."""
        return DQFinding(
            issue_type="trip_resolution_not_confirmed",
            severity=SEVERITY_WARNING,
            title=(
                "Passenger counts are not being matched to scheduled trips "
                f"for {source} — one setting needs your confirmation"
            ),
            description=(
                "Headway can match this export's trips to your published "
                "schedule, but it will not start until you confirm which of "
                "the export's direction values means which direction in your "
                "GTFS feed. "
                + (self.spec.direction.unconfirmed_reason or "")
                + " Until then every row keeps the trip name your system "
                "gave it and nothing is matched — a direction guess would be "
                "right about half the time and would put passenger counts on "
                "the wrong trips without anything looking wrong. Confirm the "
                f"mapping in {self.spec.path} (column "
                f"{self.spec.direction.from_column!r}, field "
                "trip.match.direction) and re-run this file. "
                f"Record {record_id}, resolution config "
                f"{self.spec.spec_sha12}."
            ),
            source_record_ids=[record_id],
        )

    # --- resolution -----------------------------------------------------

    def resolve_trip(self, row: dict, record: dict) -> TripOutcome:
        """Resolve ONE vendor row's trip. Never picks among candidates."""
        spec = self.spec
        if spec.vendor_field:
            vendor_ref = str(record.get(spec.vendor_field) or "").strip()
        else:
            vendor_ref = (row.get(spec.vendor_column) or "").strip()

        if not vendor_ref:
            return TripOutcome(
                status=UNMATCHED,
                vendor_ref="",
                subject="a row with no trip name",
                reason=(
                    "the export row carries no trip identifier in "
                    + (
                        f"field {spec.vendor_field!r}"
                        if spec.vendor_field
                        else f"column {spec.vendor_column!r}"
                    )
                    + ", so there is nothing to match against the schedule"
                ),
            )

        # The one parse everything shares (handoff 0038 reuses it for the
        # block-label derivation): declared separator, declared components,
        # declared start-time format — never a guess about which part is
        # which.
        name_parse = parse_trip_name(spec, vendor_ref)
        if not name_parse.ok:
            return TripOutcome(
                status=UNMATCHED,
                vendor_ref=vendor_ref,
                subject=f"trip {vendor_ref!r}",
                reason=name_parse.reason,
            )
        parsed = name_parse.parsed
        assert parsed is not None and name_parse.start_seconds is not None
        parsed_text = name_parse.parsed_text

        route_value = parsed[spec.route_component]
        raw_start = parsed[spec.start_component]
        start_seconds = name_parse.start_seconds

        raw_direction = (row.get(spec.direction.from_column) or "").strip()
        if raw_direction not in spec.direction.values:
            return TripOutcome(
                status=UNMATCHED,
                vendor_ref=vendor_ref,
                subject=f"trip {vendor_ref!r}",
                reason=(
                    f"the export's {spec.direction.from_column} value "
                    f"{raw_direction or '(blank)'!r} is not one of the values "
                    "this agency's configuration maps ("
                    + ", ".join(
                        f"{k!r}→direction_id {v}"
                        for k, v in sorted(spec.direction.values.items())
                    )
                    + ") — a direction is mapped explicitly, never guessed"
                ),
            )
        direction_id = spec.direction.values[raw_direction]

        raw_service_date = str(record.get(spec.service_field) or "").strip()
        try:
            service_date = date.fromisoformat(raw_service_date)
        except ValueError:
            return TripOutcome(
                status=UNMATCHED,
                vendor_ref=vendor_ref,
                subject=f"trip {vendor_ref!r}",
                reason=(
                    f"the row's {spec.service_field} "
                    f"{raw_service_date or '(absent)'!r} is not a date, so "
                    "the trips scheduled that day cannot be looked up"
                ),
            )

        subject = (
            f"route {route_value}, {raw_start}, "
            f"direction {raw_direction} on {service_date.isoformat()}"
        )

        if not self.index.has_calendar():
            return TripOutcome(
                status=UNMATCHED,
                vendor_ref=vendor_ref,
                subject=subject,
                reason=(
                    "the schedule feed Headway holds defines no service days "
                    "at all (no calendar.txt and no calendar_dates.txt), so "
                    "nothing can say which trips ran on "
                    f"{service_date.isoformat()}"
                ),
            )

        services = self.index.active_services(service_date)
        if not services:
            return TripOutcome(
                status=UNMATCHED,
                vendor_ref=vendor_ref,
                subject=subject,
                reason=(
                    "your schedule feed lists no service at all running on "
                    f"{service_date.isoformat()} — the export covers a day "
                    "the loaded feed does not. Load the feed that was in "
                    "effect for that day"
                ),
            )

        candidates = self.index.candidates(
            services,
            spec.route_gtfs_field,
            route_value,
            start_seconds,
            direction_id,
        )
        rollover_note = ""
        if spec.service_day_rollover == "calendar_date":
            # DECLARED: the export dates a trip by the calendar date it ran
            # on, so a trip that started after midnight belongs to the
            # PREVIOUS service day and its GTFS start time is past 24:00:00.
            previous = service_date - timedelta(days=1)
            previous_services = self.index.active_services(previous)
            candidates = tuple(
                sorted(
                    set(candidates)
                    | set(
                        self.index.candidates(
                            previous_services,
                            spec.route_gtfs_field,
                            route_value,
                            start_seconds + DAY_SECONDS,
                            direction_id,
                        )
                    )
                )
            )
        elif not candidates:
            # NOT CONFIRMED: only the same-service-day reading is searched.
            # The other reading is probed for the FINDING only — so a human
            # sees the one thing that would have made it match, and can
            # confirm the convention instead of guessing at a symptom.
            previous = service_date - timedelta(days=1)
            would_match = self.index.candidates(
                self.index.active_services(previous),
                spec.route_gtfs_field,
                route_value,
                start_seconds + DAY_SECONDS,
                direction_id,
            )
            if would_match:
                rollover_note = (
                    f" A trip on the previous service day "
                    f"({previous.isoformat()}) scheduled to start at "
                    f"{(start_seconds + DAY_SECONDS) // 3600}:"
                    f"{(start_seconds % 3600) // 60:02d} WOULD match "
                    f"({len(would_match)} of them), which is what an "
                    "after-midnight trip looks like in GTFS. Headway did not "
                    "use it: whether this export dates after-midnight trips "
                    "by calendar date is not confirmed for this agency "
                    "(service_day_rollover in the resolution config)."
                )

        if len(candidates) == 1:
            return TripOutcome(
                status=RESOLVED,
                vendor_ref=vendor_ref,
                trip_id=candidates[0],
                candidates=candidates,
                subject=subject,
            )
        if len(candidates) > 1:
            return TripOutcome(
                status=AMBIGUOUS,
                vendor_ref=vendor_ref,
                candidates=candidates,
                subject=subject,
                reason=(
                    f"{len(candidates)} trips in your schedule share this "
                    "route, start time and direction on that service day, so "
                    "which one the counts belong to cannot be told from the "
                    "export"
                ),
            )
        return TripOutcome(
            status=UNMATCHED,
            vendor_ref=vendor_ref,
            subject=subject,
            reason=(
                "no trip in your schedule starts at that time on that route "
                f"and direction on {service_date.isoformat()} (searched "
                f"{len(services)} service(s) active that day; parsed from the "
                f"trip name as {parsed_text})." + rollover_note
            ),
        )

    def resolve_stop(self, row: dict) -> Optional[StopOutcome]:
        """Check ONE vendor row's stop identifier against the schedule.

        Returns None when the spec declares no stop clause. Nothing is
        written onto the row from this — the canonical passenger_events
        subset has no stop-identity column (handoff 0011's open gap) — it
        exists so a stop the schedule does not know becomes a finding
        instead of a silence.
        """
        spec = self.spec
        if not spec.stop_column:
            return None
        value = (row.get(spec.stop_column) or "").strip()
        if not value:
            return StopOutcome(vendor_ref="", matched=False)
        for field_name in spec.stop_match_order:
            hits = self.index.stop_exists(field_name, value)
            if hits:
                return StopOutcome(
                    vendor_ref=value,
                    matched=True,
                    matched_on=field_name,
                    stop_ids=hits,
                )
        return StopOutcome(vendor_ref=value, matched=False)


def _cap(items: list[str]) -> tuple[list[str], int]:
    """The first NAMED_CAP items and the true total."""
    return sorted(items)[:NAMED_CAP], len(items)


def resolution_findings(
    spec: ResolutionSpec,
    source: str,
    record_id: str,
    trip_outcomes: list[TripOutcome],
    stop_outcomes: list[StopOutcome],
) -> list[DQFinding]:
    """Aggregate one file's outcomes into findings an agency can act on.

    Aggregated, never one finding per row: 1,000 identical findings help
    nobody (handoff 0029). Each finding leads with what the agency would
    recognise — route, time of day, direction, date — and keeps the internal
    ids as the footnote.
    """
    findings: list[DQFinding] = []
    total = len(trip_outcomes)
    if total == 0:
        return findings

    counts = {
        status: sum(1 for o in trip_outcomes if o.status == status)
        for status in (RESOLVED, AMBIGUOUS, UNMATCHED)
    }
    findings.append(
        DQFinding(
            issue_type="trip_resolution_summary",
            severity=SEVERITY_INFO,
            title=(
                f"{counts[RESOLVED]} of {total} passenger-count rows matched "
                "a scheduled trip"
            ),
            description=(
                f"Adapter {source}, record {record_id}: of {total} mapped "
                f"row(s), {counts[RESOLVED]} matched exactly one trip in your "
                f"schedule, {counts[AMBIGUOUS]} matched more than one, and "
                f"{counts[UNMATCHED]} matched none. Rows that did not match "
                "keep the trip name your system gave them and are counted "
                "here so the shortfall is visible at a glance rather than one "
                "row at a time. Resolution config "
                f"{Path(spec.path).name} {spec.spec_sha12}."
            ),
            source_record_ids=[record_id],
        )
    )

    by_ref: dict[str, TripOutcome] = {}
    row_counts: dict[str, int] = {}
    for outcome in trip_outcomes:
        if outcome.status == RESOLVED:
            continue
        by_ref.setdefault(outcome.vendor_ref, outcome)
        row_counts[outcome.vendor_ref] = row_counts.get(outcome.vendor_ref, 0) + 1

    for status, issue_type, headline in (
        (
            AMBIGUOUS,
            "trip_resolution_ambiguous",
            "Some passenger counts match more than one scheduled trip",
        ),
        (
            UNMATCHED,
            "trip_resolution_unmatched",
            "Some passenger counts match no scheduled trip",
        ),
    ):
        refs = [r for r, o in by_ref.items() if o.status == status]
        if not refs:
            continue
        named, distinct = _cap(refs)
        affected = sum(row_counts[r] for r in refs)
        lines = []
        for ref in named:
            outcome = by_ref[ref]
            line = (
                f"- {outcome.subject} ({row_counts[ref]} row(s)) — "
                f"{outcome.reason}"
            )
            if outcome.candidates:
                line += (
                    " Candidate scheduled trips: "
                    + ", ".join(outcome.candidates)
                    + "."
                )
            line += f" Your system calls it {ref!r}."
            lines.append(line)
        findings.append(
            DQFinding(
                issue_type=issue_type,
                severity=SEVERITY_WARNING,
                title=(
                    headline
                    + f" — {distinct} trip(s), {affected} row(s)"
                    + (
                        " (every row in this file)"
                        if affected == total
                        else ""
                    )
                ),
                description=(
                    f"Adapter {source}, record {record_id}: {affected} of "
                    f"{total} mapped row(s), across {distinct} distinct trip "
                    "name(s), "
                    + (
                        "matched more than one trip in your schedule. Headway "
                        "did not pick one — choosing would invent a fact, and "
                        "nothing downstream could tell. "
                        if status == AMBIGUOUS
                        else "matched no trip in your schedule. "
                    )
                    + (
                        f"Showing the first {len(named)} of {distinct}; the "
                        "count above is the true total. "
                        if distinct > len(named)
                        else ""
                    )
                    + "\n"
                    + "\n".join(lines)
                    + f"\nResolution config {Path(spec.path).name} "
                    f"{spec.spec_sha12}."
                ),
                source_record_ids=[record_id],
            )
        )

    missing_stops = sorted(
        {o.vendor_ref for o in stop_outcomes if not o.matched and o.vendor_ref}
    )
    if missing_stops:
        named = missing_stops[:NAMED_CAP]
        findings.append(
            DQFinding(
                issue_type="stop_resolution_unmatched",
                severity=SEVERITY_WARNING,
                title=(
                    f"{len(missing_stops)} stop code(s) in this export are "
                    "not in your schedule"
                ),
                description=(
                    f"Adapter {source}, record {record_id}: the export "
                    "reported passenger activity at "
                    f"{len(missing_stops)} stop code(s) that no stop in your "
                    "loaded schedule carries, checked against "
                    + " then ".join(spec.stop_match_order)
                    + ". "
                    + (
                        f"Showing the first {len(named)} of "
                        f"{len(missing_stops)}: "
                        if len(missing_stops) > len(named)
                        else ""
                    )
                    + ", ".join(named)
                    + ". The counts still land — nothing was dropped — but "
                    "these stops cannot be placed on your network, which "
                    "usually means the schedule feed is older than the stop "
                    "or the code was retired."
                ),
                source_record_ids=[record_id],
            )
        )
    blank_stops = sum(1 for o in stop_outcomes if not o.vendor_ref)
    if blank_stops:
        findings.append(
            DQFinding(
                issue_type="stop_resolution_unmatched",
                severity=SEVERITY_WARNING,
                title=(
                    f"{blank_stops} row(s) report passenger activity with no "
                    "stop code"
                ),
                description=(
                    f"Adapter {source}, record {record_id}: {blank_stops} "
                    f"mapped row(s) carry no value in "
                    f"{spec.stop_column!r}, so the stop they happened at "
                    "cannot be identified. The counts still land — nothing "
                    "was dropped — and the rows are reported here rather "
                    "than being quietly attributed to a nearby stop."
                ),
                source_record_ids=[record_id],
            )
        )
    return findings
