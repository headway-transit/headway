"""Deriving the agency's block names from their trip->block export
(handoff 0038).

WHY THIS MODULE EXISTS
----------------------
Findings that group trips by block (handoff 0029) can only show the block
identifier the schedule feed carries — for the first agency, an opaque UUID.
The word on their run board is an operational name like ``225-4``, and the
agency has now supplied the source that connects the two: a trip->block
export of ``TripName,BlockName`` rows in their own vocabulary. TripName is
the same ``route - pattern - start`` key the handoff-0031 trip resolution
already parses, so TripName -> GTFS trip -> ``trips.block_id`` lands the
``block_id -> BlockName`` mapping the headway_calc.subjects module recorded
as its open gap.

THE RULES
---------
1. **The parse is the resolver's parse, reused.** A trip name comes apart
   via :func:`headway_transform.adapters.resolution.parse_trip_name` with
   the agency's own ``resolution.v0.yaml`` parse rules — one parse, one
   meaning, nothing reimplemented. The resolution spec's *direction*
   confirmation gate is not involved: that gate is about assigning
   passenger counts to a trip, and deriving a block name neither needs a
   direction (route + start is the join key here) nor touches
   ``confirmed`` (handoff 0038 explicitly leaves it false).
2. **Match, ambiguous, unmatched — counted honestly, never guessed.** A row
   matches when every scheduled trip sharing its (route short name, first
   scheduled departure) key carries ONE block_id. More than one distinct
   block_id — including a candidate with no block at all — is ambiguous;
   zero candidates is unmatched; a trip name the parse cannot read is
   unparseable. Each non-matching row is reported with its stated reason.
3. **Conflicts are refused, not resolved.** If two rows land different
   labels on the same feed block_id, that block_id is EXCLUDED from the
   mapping and reported. Picking one would invent a fact.
4. **The mapping file never enters the repo.** This module reads whatever
   path it is given; committed fixtures are synthetic twins (handoff 0016
   discipline). Loaded rows carry provenance: source file + sha256, the
   resolution config's content hash, the tool, the timestamp.

Pure by construction: :func:`derive_block_labels` takes rows and scheduled
trips and returns a result. The database touches live in
:func:`load_scheduled_trips` (read) and :func:`load_block_labels` (write),
both over any DB-API 2.0 connection, so tests inject fakes and the CLI in
``tools/block-labels`` stays thin.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .adapters.resolution import ResolutionSpec, parse_trip_name

#: Row-outcome vocabulary (mirrors the 0031 resolver's, plus the parse
#: failure case a two-column mapping file can exhibit).
MATCHED = "matched"
AMBIGUOUS = "ambiguous"
UNMATCHED = "unmatched"
UNPARSEABLE = "unparseable"

#: How many example rows a report names per non-matching outcome. The true
#: counts are always stated; the cap only bounds the enumeration (the
#: handoff-0029 house style).
REPORT_SAMPLE_CAP = 10


class MappingFileError(Exception):
    """The mapping file is not the shape the loader was promised."""


@dataclass(frozen=True)
class MappingRow:
    """One line of the agency's trip->block export."""

    line_no: int
    trip_name: str
    block_name: str


@dataclass(frozen=True)
class TripWithBlock:
    """One scheduled trip flattened to what this derivation joins on."""

    trip_id: str
    route_short_name: Optional[str]
    first_departure_seconds: Optional[int]
    block_id: Optional[str]


@dataclass(frozen=True)
class RowOutcome:
    """What the derivation decided about ONE mapping row."""

    row: MappingRow
    status: str  # MATCHED | AMBIGUOUS | UNMATCHED | UNPARSEABLE
    block_id: Optional[str] = None
    #: The distinct block_ids the candidates carried (ambiguous case);
    #: None stands for a candidate trip with no block in the feed.
    candidate_block_ids: tuple[Optional[str], ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class BlockLabelConflict:
    """One feed block_id that two rows tried to label differently."""

    block_id: str
    labels: tuple[str, ...]
    row_line_nos: tuple[int, ...]


@dataclass(frozen=True)
class DerivationResult:
    """Everything one derivation run decided, with nothing hidden."""

    #: The mapping that survived every check: (block_id, block_label,
    #: supporting row count), deterministically ordered by block_label.
    mapping: tuple[tuple[str, str, int], ...]
    outcomes: tuple[RowOutcome, ...]
    conflicts: tuple[BlockLabelConflict, ...]
    counts: dict[str, int] = field(default_factory=dict)

    def summary_lines(self) -> list[str]:
        """The human report: true totals first, capped samples after."""
        total = len(self.outcomes)
        lines = [
            f"mapping rows: {total}",
            f"  matched:     {self.counts.get(MATCHED, 0)} "
            "(row's route+start key names exactly one feed block)",
            f"  ambiguous:   {self.counts.get(AMBIGUOUS, 0)}",
            f"  unmatched:   {self.counts.get(UNMATCHED, 0)}",
            f"  unparseable: {self.counts.get(UNPARSEABLE, 0)}",
            f"block labels derived: {len(self.mapping)} "
            f"(from {sum(n for _, _, n in self.mapping)} matched rows)",
            f"label conflicts (block_id excluded): {len(self.conflicts)}",
        ]
        for status, heading in (
            (AMBIGUOUS, "ambiguous rows"),
            (UNMATCHED, "unmatched rows"),
            (UNPARSEABLE, "unparseable rows"),
        ):
            sample = [o for o in self.outcomes if o.status == status]
            if not sample:
                continue
            lines.append(
                f"{heading} (first {min(len(sample), REPORT_SAMPLE_CAP)} "
                f"of {len(sample)}):"
            )
            for outcome in sample[:REPORT_SAMPLE_CAP]:
                lines.append(
                    f"  line {outcome.row.line_no}: "
                    f"{outcome.row.trip_name!r} -> {outcome.row.block_name!r}"
                    f" — {outcome.reason}"
                )
        for conflict in self.conflicts:
            lines.append(
                f"conflict: feed block {conflict.block_id} was given "
                f"{len(conflict.labels)} different labels "
                f"({', '.join(repr(label) for label in conflict.labels)}; "
                f"lines {', '.join(str(n) for n in conflict.row_line_nos)}) "
                "— excluded from the mapping, never picked between"
            )
        return lines


def read_mapping_csv(path: Path | str) -> tuple[list[MappingRow], str]:
    """Read a two-column ``TripName,BlockName`` CSV; returns (rows, sha256).

    utf-8 with an optional BOM (the shape the agency's export arrived in).
    An optional first row reading exactly ``TripName,BlockName`` is treated
    as a header and skipped. Any row that is not exactly two columns fails
    the WHOLE file loudly — a half-read mapping would silently drop labels.
    Blank values are kept and reported by the derivation, never dropped
    here: this function reads, it does not judge.
    """
    path = Path(path)
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig")
    rows: list[MappingRow] = []
    problems: list[str] = []
    for line_no, parts in enumerate(csv.reader(text.splitlines()), start=1):
        if not parts:
            continue  # a fully blank line carries nothing to misread
        if len(parts) != 2:
            problems.append(
                f"line {line_no}: {len(parts)} column(s), expected exactly "
                "2 (TripName,BlockName)"
            )
            continue
        if line_no == 1 and parts == ["TripName", "BlockName"]:
            continue
        rows.append(
            MappingRow(
                line_no=line_no,
                trip_name=parts[0].strip(),
                block_name=parts[1].strip(),
            )
        )
    if problems:
        shown = problems[:REPORT_SAMPLE_CAP]
        raise MappingFileError(
            f"{path} is not a two-column TripName,BlockName file "
            f"({len(problems)} bad line(s); first {len(shown)}): "
            + "; ".join(shown)
        )
    return rows, sha256


def derive_block_labels(
    spec: ResolutionSpec,
    rows: Iterable[MappingRow],
    trips: Iterable[TripWithBlock],
) -> DerivationResult:
    """Join mapping rows to feed blocks through the resolver's own parse.

    The join key is (route short name, first scheduled departure) across the
    WHOLE schedule — deliberately without service day or direction: the
    mapping file carries neither, and the key only has to name one BLOCK,
    not one trip. Several scheduled trips may share the key (weekday and
    Saturday variants); the row still matches when they all agree on the
    block. The moment they do not — two distinct block_ids, or a candidate
    with no block at all — the row is ambiguous and says so.
    """
    by_key: dict[tuple[str, int], list[TripWithBlock]] = {}
    for trip in trips:
        if trip.route_short_name is None or trip.first_departure_seconds is None:
            continue  # not addressable by a route+start key; never a candidate
        by_key.setdefault(
            (trip.route_short_name, trip.first_departure_seconds), []
        ).append(trip)

    outcomes: list[RowOutcome] = []
    for row in rows:
        if not row.block_name:
            outcomes.append(
                RowOutcome(
                    row=row,
                    status=UNPARSEABLE,
                    reason=(
                        "the row carries no block name at all, so there is "
                        "nothing to map — reported rather than invented"
                    ),
                )
            )
            continue
        name_parse = parse_trip_name(spec, row.trip_name)
        if not name_parse.ok:
            outcomes.append(
                RowOutcome(row=row, status=UNPARSEABLE, reason=name_parse.reason)
            )
            continue
        assert name_parse.parsed is not None
        assert name_parse.start_seconds is not None
        route_value = name_parse.parsed[spec.route_component]
        candidates = by_key.get((route_value, name_parse.start_seconds), [])
        if not candidates:
            outcomes.append(
                RowOutcome(
                    row=row,
                    status=UNMATCHED,
                    reason=(
                        f"no scheduled trip on route {route_value!r} has a "
                        "first departure at "
                        f"{name_parse.parsed[spec.start_component]!r} — the "
                        "export names a trip the loaded schedule does not"
                    ),
                )
            )
            continue
        block_ids = sorted(
            {c.block_id for c in candidates}, key=lambda b: (b is None, b or "")
        )
        if len(block_ids) == 1 and block_ids[0] is not None:
            outcomes.append(
                RowOutcome(row=row, status=MATCHED, block_id=block_ids[0])
            )
        elif block_ids == [None]:
            outcomes.append(
                RowOutcome(
                    row=row,
                    status=UNMATCHED,
                    reason=(
                        f"{len(candidates)} scheduled trip(s) share this "
                        "route and start, but none carries a block in the "
                        "feed — there is no feed block to attach the name to"
                    ),
                )
            )
        else:
            outcomes.append(
                RowOutcome(
                    row=row,
                    status=AMBIGUOUS,
                    candidate_block_ids=tuple(block_ids),
                    reason=(
                        f"{len(candidates)} scheduled trip(s) share this "
                        f"route and start across {len(block_ids)} different "
                        "feed blocks"
                        + (
                            " (one of them with no block at all)"
                            if None in block_ids
                            else ""
                        )
                        + " — which block the name belongs to cannot be told "
                        "from route and start alone, so nothing was picked"
                    ),
                )
            )

    # Aggregate matched rows into the mapping, refusing conflicts.
    labels_by_block: dict[str, dict[str, list[int]]] = {}
    for outcome in outcomes:
        if outcome.status != MATCHED:
            continue
        assert outcome.block_id is not None
        labels_by_block.setdefault(outcome.block_id, {}).setdefault(
            outcome.row.block_name, []
        ).append(outcome.row.line_no)

    mapping: list[tuple[str, str, int]] = []
    conflicts: list[BlockLabelConflict] = []
    for block_id, labels in labels_by_block.items():
        if len(labels) == 1:
            ((label, line_nos),) = labels.items()
            mapping.append((block_id, label, len(line_nos)))
        else:
            conflicts.append(
                BlockLabelConflict(
                    block_id=block_id,
                    labels=tuple(sorted(labels)),
                    row_line_nos=tuple(
                        sorted(n for nos in labels.values() for n in nos)
                    ),
                )
            )
    mapping.sort(key=lambda entry: (entry[1], entry[0]))
    conflicts.sort(key=lambda c: c.block_id)

    counts = {
        status: sum(1 for o in outcomes if o.status == status)
        for status in (MATCHED, AMBIGUOUS, UNMATCHED, UNPARSEABLE)
    }
    return DerivationResult(
        mapping=tuple(mapping),
        outcomes=tuple(outcomes),
        conflicts=tuple(conflicts),
        counts=counts,
    )


#: canonical.trips + route short name + the trip's first scheduled
#: departure (lowest stop_sequence — the schedule_index definition) + the
#: feed's block_id. The 0031 SELECT with block_id added; same LATERAL, same
#: deterministic ORDER BY.
SELECT_TRIPS_WITH_BLOCKS_SQL = (
    "SELECT t.trip_id, r.short_name, f.departure_seconds, t.block_id "
    "FROM canonical.trips AS t "
    "LEFT JOIN canonical.routes AS r ON r.route_id = t.route_id "
    "LEFT JOIN LATERAL ("
    "SELECT st.departure_seconds FROM canonical.stop_times AS st "
    "WHERE st.trip_id = t.trip_id "
    "ORDER BY st.stop_sequence LIMIT 1) AS f ON TRUE "
    "ORDER BY t.trip_id"
)

#: Upsert: a reloaded mapping file refreshes labels in place. Existing
#: findings are untouched by design — labels were frozen onto
#: dq.issues.subject_context at persistence time (handoff 0029/0038).
UPSERT_BLOCK_LABEL_SQL = (
    "INSERT INTO canonical.block_labels "
    "(block_id, block_label, source, derivation, loaded_at, loaded_by) "
    "VALUES (%s, %s, %s, %s, now(), %s) "
    "ON CONFLICT (block_id) DO UPDATE SET "
    "block_label = EXCLUDED.block_label, "
    "source = EXCLUDED.source, "
    "derivation = EXCLUDED.derivation, "
    "loaded_at = EXCLUDED.loaded_at, "
    "loaded_by = EXCLUDED.loaded_by"
)


def load_scheduled_trips(connection: Any) -> list[TripWithBlock]:
    """Read every scheduled trip's join facts through a DB-API connection."""
    cursor = connection.cursor()
    try:
        cursor.execute(SELECT_TRIPS_WITH_BLOCKS_SQL)
        return [
            TripWithBlock(
                trip_id=trip_id,
                route_short_name=short_name,
                first_departure_seconds=(
                    None if departure is None else int(departure)
                ),
                block_id=block_id,
            )
            for trip_id, short_name, departure, block_id in cursor.fetchall()
        ]
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            close()


def load_block_labels(
    connection: Any,
    result: DerivationResult,
    *,
    source: str,
    derivation: str,
    loaded_by: str,
) -> int:
    """Upsert the derived mapping; returns the row count written.

    Does NOT commit — transaction control belongs to the caller (the tool),
    so a dry run and a real run share every line of code up to the commit.
    """
    rows = [
        (block_id, label, source, derivation, loaded_by)
        for block_id, label, _count in result.mapping
    ]
    if not rows:
        return 0
    cursor = connection.cursor()
    try:
        cursor.executemany(UPSERT_BLOCK_LABEL_SQL, rows)
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            close()
    return len(rows)
