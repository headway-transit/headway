"""Adapter engine: execute one mapping spec over one vendor file.

Given a validated MappingSpec and the ORIGINAL vendor bytes (already landed as
a content-addressed raw record), the engine produces contract-conformant
records and their canonical rows, with the same guarantees as the first-party
normalizers:

- **per-row quarantine** (row_guard patterns): a structurally hostile row, a
  failed coercion, an unmapped enum value, an ambiguous/nonexistent local
  time, or a contract-validation failure becomes ONE reasoned DQ finding —
  the row is quarantined, never dropped silently, and never aborts the file;
- **filters are visible**: rows excluded by a declared filter predicate are
  counted and surfaced as an aggregated info finding carrying the filter's
  reason;
- **the target contract's own validation runs on every mapped record**:
  demand_response_trip records are validated against
  contracts/demand-response-trip.v0.schema.json AND the dr_trips normalizer's
  cross-field rules; tides_passenger_events records run through the
  tides_passenger_events normalizer whose constraints were verified against
  the published TIDES spec. The engine reuses those normalizers per-row (a
  one-row contract CSV per record) so contract semantics live in exactly one
  place and every canonical row is built by the same code path as first-party
  data;
- **lineage**: every canonical row carries the normalizer's lineage edge to
  the raw vendor record PLUS an adapter edge (transform_name
  ``adapter:<source_label>``, transform_version = the mapping spec's content
  hash) — "explain this number" can name the exact spec version that mapped
  the row;
- **determinism**: same file bytes + same spec bytes => byte-identical
  output, so Kafka redelivery re-derives identical rows/edges/findings and
  the migration-0023 idempotent writes add nothing new.

Timezones are DECLARED, never guessed: naive timestamps are localized to the
spec's IANA zone, and a wall time that is ambiguous (DST fall-back) or
nonexistent (DST spring-forward) in that zone quarantines the row.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timezone
from decimal import Context, Decimal, InvalidOperation, localcontext
from typing import Optional

from .. import dr_trips, tides_passenger_events
from ..model import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    DQFinding,
    LineageEdge,
)
from ..row_guard import field_problems, iter_rows
from .spec import DR_CONTRACT_VALIDATOR, TARGET_DR, TARGET_TIDES, FieldDef, MappingSpec

#: Exact distance conversion factors to statute miles. 1 international mile =
#: 1609.344 m exactly (NIST SP 811 Appendix B — verify against the published
#: handbook, never memory). Division under Decimal's default 28-digit context
#: is deterministic.
_MILES_DIVISORS = {
    "kilometers": Decimal("1.609344"),
    "meters": Decimal("1609.344"),
    "miles": Decimal("1"),
}

#: Contract CSV column order for the one-row serializations handed to the
#: contract normalizers. TIDES columns per the fields the verified normalizer
#: reads (tides_passenger_events.py); DR columns per
#: contracts/demand-response-trip.v0.schema.json properties.
_TIDES_COLUMNS = (
    "passenger_event_id",
    "service_date",
    "event_timestamp",
    "trip_stop_sequence",
    "event_type",
    "vehicle_id",
    "trip_id_performed",
    "event_count",
)
_DR_COLUMNS = (
    "dr_trip_id",
    "service_date",
    "vehicle_id",
    "mode",
    "tos",
    "request_timestamp",
    "dispatch_timestamp",
    "pickup_timestamp",
    "dropoff_timestamp",
    "pickup_lat",
    "pickup_lon",
    "dropoff_lat",
    "dropoff_lon",
    "onboard_miles",
    "distance_source",
    "pickup_odometer_miles",
    "dropoff_odometer_miles",
    "riders",
    "attendants_companions",
    "ada_related",
    "sponsored",
    "sponsor",
    "no_show",
    "interruption_after",
    "driver_shift_id",
    "dispatching_point_id",
)


@dataclass
class AdapterRunResult:
    """Everything one adapter run produced, with full row accounting."""

    source_label: str
    target_contract: str
    record_id: str
    #: Contract-conformant mapped records (JSON-typed dicts), in file order.
    records: list[dict] = dc_field(default_factory=list)
    #: Canonical rows built by the target contract's normalizer.
    passenger_events: list = dc_field(default_factory=list)
    dr_trips: list = dc_field(default_factory=list)
    edges: list[LineageEdge] = dc_field(default_factory=list)
    findings: list[DQFinding] = dc_field(default_factory=list)
    total_rows: int = 0
    mapped_count: int = 0
    quarantined_count: int = 0
    filtered_count: int = 0
    #: True when a file-level defect (undecodable bytes, missing source
    #: columns) blocked the whole file before row accounting began.
    file_refused: bool = False

    def accounted(self) -> bool:
        """Every vendor row is mapped, filtered, or quarantined — nothing else."""
        return self.total_rows == (
            self.mapped_count + self.filtered_count + self.quarantined_count
        )


def rfc3339(dt: datetime) -> str:
    """RFC 3339 in UTC with a 'Z' suffix (matches the normalizers' rendering)."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _localize(naive: datetime, spec: MappingSpec) -> tuple[Optional[datetime], Optional[str]]:
    """Attach the spec's declared timezone to a naive wall-clock time.

    Returns (aware_datetime, None) or (None, problem). Ambiguous (DST
    fall-back) and nonexistent (DST spring-forward) wall times are problems —
    the engine never picks a side of a DST transition silently.
    """
    tz = spec.timezone
    dt0 = naive.replace(tzinfo=tz)
    roundtrip = dt0.astimezone(timezone.utc).astimezone(tz)
    if roundtrip.replace(tzinfo=None) != naive:
        return None, (
            f"local time {naive.isoformat()} does not exist in "
            f"{spec.timezone_name} (DST spring-forward gap); the timezone "
            "is declared, never guessed — row quarantined"
        )
    dt1 = naive.replace(tzinfo=tz, fold=1)
    if dt0.utcoffset() != dt1.utcoffset():
        return None, (
            f"local time {naive.isoformat()} is ambiguous in "
            f"{spec.timezone_name} (DST fall-back repeats it at two UTC "
            "offsets); the timezone is declared, never guessed — row "
            "quarantined"
        )
    return dt0, None


def _coerce(
    fd: FieldDef, raw: str, spec: MappingSpec, problems: list[str]
) -> object:
    """Apply one 'from' field's coercion to a non-empty stripped cell value.

    Returns the JSON-typed value (datetime fields return aware datetimes;
    serialization happens at record build). Appends to problems and returns
    None on failure — the row is quarantined with every problem found.
    """
    label = f"{fd.target} <- column {fd.source!r}"
    if fd.coerce == "string":
        return raw
    if fd.coerce == "integer":
        try:
            return int(raw)
        except ValueError:
            problems.append(f"{label}: {raw!r} is not an integer")
            return None
    if fd.coerce in ("decimal", "number"):
        if fd.coerce == "decimal":
            try:
                value = Decimal(raw)
            except InvalidOperation:
                problems.append(f"{label}: {raw!r} is not a decimal number")
                return None
        else:
            try:
                value = Decimal(str(float(raw)))
            except (ValueError, InvalidOperation):
                problems.append(f"{label}: {raw!r} is not a number")
                return None
        if fd.unit_from and fd.unit_to:
            # Explicit 28-digit context: unit conversion must be
            # deterministic regardless of any ambient decimal context.
            with localcontext(Context(prec=28)):
                value = value / _MILES_DIVISORS[fd.unit_from]
        if fd.coerce == "number":
            return float(value)
        return format(value, "f")
    if fd.coerce == "boolean":
        lowered = raw.lower()
        if lowered in (v.lower() for v in fd.true_values):
            return True
        if lowered in (v.lower() for v in fd.false_values):
            return False
        problems.append(
            f"{label}: {raw!r} is in neither true_values {list(fd.true_values)} "
            f"nor false_values {list(fd.false_values)} — never guessed"
        )
        return None
    if fd.coerce == "date":
        fmt = fd.format or "%Y-%m-%d"
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            problems.append(f"{label}: {raw!r} does not match date format {fmt!r}")
            return None
    if fd.coerce == "datetime":
        assert fd.format is not None  # schema-required
        try:
            parsed = datetime.strptime(raw, fd.format)
        except ValueError:
            problems.append(
                f"{label}: {raw!r} does not match datetime format {fd.format!r}"
            )
            return None
        if parsed.tzinfo is None:
            aware, problem = _localize(parsed, spec)
            if problem:
                problems.append(f"{label}: {problem}")
                return None
            return aware
        return parsed
    if fd.coerce == "enum_map":
        assert fd.values is not None  # schema-required
        if raw in fd.values:
            return fd.values[raw]
        problems.append(
            f"{label}: source value {raw!r} has no entry in the spec's "
            "enum_map values — vendor vocabulary is mapped explicitly, "
            "never guessed"
        )
        return None
    raise AssertionError(f"unreachable coercion {fd.coerce!r}")  # schema-guarded


def _map_row(
    spec: MappingSpec, row: dict, problems: list[str]
) -> dict[str, object]:
    """Map one kept vendor row to a typed contract record (may add problems)."""
    typed: dict[str, object] = {}

    for fd in spec.fields:
        if fd.kind == "from":
            raw = (row.get(fd.source) or "").strip()
            if raw == "":
                continue  # absent — never coalesced; contract validation decides
            value = _coerce(fd, raw, spec, problems)
            if value is not None:
                typed[fd.target] = value
        elif fd.kind == "const":
            typed[fd.target] = fd.const

    for fd in spec.fields:
        if fd.kind != "derived":
            continue
        if fd.derived == "concat":
            parts = [(row.get(col) or "").strip() for col in fd.sources]
            joined = fd.separator.join(parts)
            if joined.replace(fd.separator, "") != "":
                typed[fd.target] = joined
        elif fd.derived == "local_date_of":
            base = typed.get(fd.of)
            if isinstance(base, datetime):
                typed[fd.target] = base.astimezone(spec.timezone).date().isoformat()
            # absent/failed base: leave absent; contract validation decides
    return typed


def _json_record(typed: dict[str, object]) -> dict:
    """The JSON-typed contract record (datetimes rendered RFC 3339 UTC)."""
    return {
        k: rfc3339(v) if isinstance(v, datetime) else v for k, v in typed.items()
    }


def _cell(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _contract_csv(columns: tuple[str, ...], record: dict) -> bytes:
    """Serialize ONE contract record as a one-row contract CSV (deterministic)."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    writer.writerow([_cell(record[c]) if c in record else "" for c in columns])
    return out.getvalue().encode("utf-8")


def run_adapter(
    spec: MappingSpec, file_bytes: bytes, record_id: str, source: str
) -> AdapterRunResult:
    """Execute one mapping spec over one vendor file's original bytes.

    ``record_id`` is the content address of ``file_bytes`` (the raw record
    the connector landed); ``source`` is the envelope source label and must
    be the label the spec is registered under — the caller (registry lookup)
    guarantees it, and the engine refuses a mismatch rather than mislabel
    provenance.
    """
    if source != spec.source_label:
        raise ValueError(
            f"envelope source {source!r} does not match the spec's registered "
            f"source_label {spec.source_label!r} — refusing to mislabel provenance"
        )

    result = AdapterRunResult(
        source_label=source,
        target_contract=spec.target_contract,
        record_id=record_id,
    )

    def _quarantine(index: int, problems: list[str]) -> None:
        result.quarantined_count += 1
        result.findings.append(
            DQFinding(
                issue_type="adapter_row_quarantined",
                severity=SEVERITY_WARNING,
                title=(
                    f"Vendor row could not be mapped by adapter {source}"
                ),
                description=(
                    f"Record {record_id}, vendor data row {index} "
                    f"(adapter {source}, spec {spec.spec_sha12}): "
                    + "; ".join(problems)
                    + ". Row quarantined, not dropped silently."
                ),
                source_record_ids=[record_id],
            )
        )

    def _refuse_file(issue_type: str, description: str) -> AdapterRunResult:
        result.file_refused = True
        result.findings.append(
            DQFinding(
                issue_type=issue_type,
                severity=SEVERITY_BLOCKING,
                title=f"Vendor file refused by adapter {source}",
                description=description,
                source_record_ids=[record_id],
            )
        )
        return result

    try:
        text = file_bytes.decode(spec.encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        return _refuse_file(
            "undecodable_payload",
            f"Record {record_id}: payload does not decode as the spec's "
            f"declared encoding {spec.encoding!r}: {exc}. File not mapped; "
            "raw record retained, nothing dropped.",
        )

    stream = io.StringIO(text, newline="")
    for _ in range(spec.skip_leading_rows):
        stream.readline()
    reader = csv.DictReader(
        stream, delimiter=spec.delimiter, quotechar=spec.quotechar
    )

    header = reader.fieldnames or []
    missing = sorted(spec.source_columns() - {(h or "").strip() for h in header})
    if missing:
        return _refuse_file(
            "adapter_source_mismatch",
            f"Record {record_id}: the file's header is missing source "
            f"column(s) {', '.join(repr(m) for m in missing)} that mapping "
            f"spec {spec.vendor}/{spec.product}@{spec.spec_sha12} reads. "
            "The file does not match the registered export format; nothing "
            "was mapped and the raw record is retained (fail loudly, never "
            "a guessed column).",
        )

    filtered_by: dict[int, int] = {}

    for index, row, parse_error in iter_rows(reader):
        result.total_rows += 1

        if parse_error is not None:
            _quarantine(index, [f"CSV parse error: {parse_error}"])
            continue
        guard = field_problems(row)
        if guard:
            _quarantine(index, guard)
            continue

        kept = True
        for f_idx, flt in enumerate(spec.filters):
            if not flt.keeps(row):
                filtered_by[f_idx] = filtered_by.get(f_idx, 0) + 1
                result.filtered_count += 1
                kept = False
                break
        if not kept:
            continue

        problems: list[str] = []
        typed = _map_row(spec, row, problems)
        if problems:
            _quarantine(index, problems)
            continue

        record = _json_record(typed)

        if spec.target_contract == TARGET_DR:
            schema_errors = sorted(
                DR_CONTRACT_VALIDATOR.iter_errors(record),
                key=lambda e: list(e.path),
            )
            if schema_errors:
                _quarantine(
                    index,
                    [
                        "contract validation "
                        "(demand-response-trip.v0.schema.json): "
                        + "; ".join(
                            f"{'/'.join(str(p) for p in err.path) or '<record>'}: "
                            f"{err.message}"
                            for err in schema_errors
                        )
                    ],
                )
                continue
            csv_bytes = _contract_csv(_DR_COLUMNS, record)
            rows, edges, findings = dr_trips.normalize(csv_bytes, record_id, source)
        else:
            assert spec.target_contract == TARGET_TIDES
            csv_bytes = _contract_csv(_TIDES_COLUMNS, record)
            rows, edges, findings = tides_passenger_events.normalize(
                csv_bytes, record_id, source
            )

        if findings or not rows:
            # The contract normalizer (the verified contract validation)
            # rejected the mapped record — quarantine THIS vendor row with
            # the normalizer's own reasons, never land a nonconforming row.
            _quarantine(
                index,
                [
                    "target contract validation rejected the mapped record: "
                    + " | ".join(f.description for f in findings)
                ],
            )
            continue

        result.mapped_count += 1
        result.records.append(record)
        if spec.target_contract == TARGET_DR:
            result.dr_trips.extend(rows)
        else:
            result.passenger_events.extend(rows)
        result.edges.extend(edges)
        for row_obj in rows:
            result.edges.append(
                LineageEdge(
                    output_kind=edges[0].output_kind,
                    output_id=row_obj.output_id,
                    transform_name=f"adapter:{source}",
                    transform_version=spec.spec_sha12,
                    input_kind="raw.records",
                    input_id=record_id,
                )
            )

    for f_idx, count in sorted(filtered_by.items()):
        flt = spec.filters[f_idx]
        result.findings.append(
            DQFinding(
                issue_type="adapter_rows_filtered",
                severity=SEVERITY_INFO,
                title=f"Adapter {source} filtered vendor rows by declared predicate",
                description=(
                    f"Record {record_id}: {count} row(s) excluded by mapping-"
                    f"spec filter #{f_idx + 1} ({flt.column} {flt.op}"
                    + (
                        f" {flt.value!r}"
                        if flt.value is not None
                        else (f" {list(flt.values)}" if flt.values else "")
                    )
                    + f"): {flt.reason}. Declared exclusion, counted and "
                    "recorded — never a silent drop."
                ),
                source_record_ids=[record_id],
            )
        )

    if result.total_rows == 0 and not result.file_refused:
        result.findings.append(
            DQFinding(
                issue_type="empty_vendor_file",
                severity=SEVERITY_INFO,
                title=f"Vendor file for adapter {source} contains no data rows",
                description=(
                    f"Record {record_id}: the file has no data rows (header "
                    "only, or empty). Nothing mapped; recorded so an empty "
                    "delivery is visible, not silent."
                ),
                source_record_ids=[record_id],
            )
        )

    return result
