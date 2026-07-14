"""Load and validate vendor adapter mapping specs (mapping.v0.yaml).

The checked-in JSON Schema — ``contracts/adapter-mapping.v0.schema.json`` — is
the contract for the spec format itself (ADR-0006 pattern: the schema file IS
the contract, loaded from disk so this module can never drift from it without
failing loudly). On top of the schema, this module enforces the checks a JSON
Schema cannot express:

- the declared ``timezone`` must resolve in the IANA database (zoneinfo);
- ``source_label`` must be ``<vendor>_<product>`` — with the mandatory
  ``_simulated`` suffix if and only if provenance declares synthetic fixtures
  (handoff-0005 binding rule, applied to adapters by handoff 0015);
- every field referenced by a ``local_date_of`` derivation must be a mapped
  datetime target field.

Provenance rule (handoff 0015 Addendum, BINDING): a spec's provenance block
references the agency-provided SAMPLE it was verified against (or declares
synthetic fixtures, reference adapters only) — never vendor documentation.
The schema makes any other provenance shape unrepresentable.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jsonschema
import yaml

# Same contract-directory resolution as headway_transform.envelope: repo-root
# contracts/ by default, HEADWAY_CONTRACTS_DIR for installed deployments.
_DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "contracts"
_CONTRACTS_DIR = Path(os.environ.get("HEADWAY_CONTRACTS_DIR", _DEFAULT_CONTRACTS_DIR))

MAPPING_SCHEMA_PATH = _CONTRACTS_DIR / "adapter-mapping.v0.schema.json"
DR_SCHEMA_PATH = _CONTRACTS_DIR / "demand-response-trip.v0.schema.json"

with open(MAPPING_SCHEMA_PATH, encoding="utf-8") as _f:
    MAPPING_SCHEMA: dict = json.load(_f)

with open(DR_SCHEMA_PATH, encoding="utf-8") as _f:
    DR_CONTRACT_SCHEMA: dict = json.load(_f)

_MAPPING_VALIDATOR = jsonschema.Draft202012Validator(MAPPING_SCHEMA)
DR_CONTRACT_VALIDATOR = jsonschema.Draft202012Validator(DR_CONTRACT_SCHEMA)

TARGET_TIDES = "tides_passenger_events"
TARGET_DR = "demand_response_trip"

#: The ``_simulated`` source-label suffix marking synthetic/simulated data
#: (handoff 0005 binding rule).
SIMULATED_SUFFIX = "_simulated"


class SpecError(Exception):
    """A mapping spec failed validation. Carries every violation found."""

    def __init__(self, path: Path | str, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(
            f"mapping spec {path} is invalid ({len(errors)} problem(s)): "
            + "; ".join(errors)
        )


@dataclass(frozen=True)
class Filter:
    """One row-filter predicate (applied before mapping, in spec order)."""

    column: str
    op: str  # equals | not_equals | in | not_in | not_empty
    value: str | None
    values: tuple[str, ...]
    reason: str

    def keeps(self, row: dict) -> bool:
        """True when the row passes this predicate (i.e. is kept)."""
        cell = (row.get(self.column) or "").strip()
        if self.op == "equals":
            return cell == self.value
        if self.op == "not_equals":
            return cell != self.value
        if self.op == "in":
            return cell in self.values
        if self.op == "not_in":
            return cell not in self.values
        if self.op == "not_empty":
            return cell != ""
        raise AssertionError(f"unreachable filter op {self.op!r}")  # schema-guarded


@dataclass(frozen=True)
class FieldDef:
    """One target-field mapping definition (exactly one kind per the schema)."""

    target: str
    kind: str  # 'from' | 'const' | 'derived'
    source: str | None = None  # 'from'
    coerce: str = "string"
    format: str | None = None
    values: dict | None = None  # enum_map
    true_values: tuple[str, ...] = ()
    false_values: tuple[str, ...] = ()
    unit_from: str | None = None
    unit_to: str | None = None
    const: object = None  # 'const'
    derived: str | None = None  # 'derived': local_date_of | concat
    of: str | None = None
    sources: tuple[str, ...] = ()
    separator: str = ":"


@dataclass(frozen=True)
class MappingSpec:
    """A validated mapping.v0.yaml, ready for the engine."""

    path: str
    vendor: str
    product: str
    source_label: str
    target_contract: str
    encoding: str
    delimiter: str
    quotechar: str
    skip_leading_rows: int
    timezone_name: str
    filters: tuple[Filter, ...]
    fields: tuple[FieldDef, ...]
    synthetic: bool
    #: SHA-256 (first 12 hex chars) of the spec file's exact bytes — the
    #: content-addressed spec version stamped into adapter lineage edges.
    spec_sha12: str
    raw: dict = field(repr=False)

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def source_columns(self) -> set[str]:
        """Every source column the spec reads (for the header check)."""
        needed: set[str] = {f.column for f in self.filters}
        for fd in self.fields:
            if fd.kind == "from":
                assert fd.source is not None
                needed.add(fd.source)
            elif fd.kind == "derived" and fd.derived == "concat":
                needed.update(fd.sources)
        return needed


def _dates_to_strings(value: object) -> object:
    """Normalize YAML 1.1 date/datetime scalars to ISO strings.

    yaml.safe_load parses unquoted ``2026-07-13`` into datetime.date, which
    the JSON-Schema string checks would reject; spec authors should not have
    to know that quirk, so dates are canonicalized before validation.
    """
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _dates_to_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dates_to_strings(v) for v in value]
    return value


def _build_field(target: str, doc: dict) -> FieldDef:
    if "from" in doc:
        unit = doc.get("unit") or {}
        return FieldDef(
            target=target,
            kind="from",
            source=doc["from"],
            coerce=doc.get("coerce", "string"),
            format=doc.get("format"),
            values=doc.get("values"),
            true_values=tuple(doc.get("true_values") or ()),
            false_values=tuple(doc.get("false_values") or ()),
            unit_from=unit.get("from"),
            unit_to=unit.get("to"),
        )
    if "const" in doc:
        return FieldDef(target=target, kind="const", const=doc["const"])
    return FieldDef(
        target=target,
        kind="derived",
        derived=doc["derived"],
        of=doc.get("of"),
        sources=tuple(doc.get("sources") or ()),
        separator=doc.get("separator", ":"),
    )


def load_spec(path: Path | str) -> MappingSpec:
    """Load one mapping.v0.yaml: schema-validate, then semantic checks.

    Raises SpecError with EVERY violation found — a spec is never partially
    accepted or silently defaulted.
    """
    path = Path(path)
    spec_bytes = path.read_bytes()
    try:
        document = _dates_to_strings(yaml.safe_load(spec_bytes))
    except yaml.YAMLError as exc:
        raise SpecError(path, [f"not valid YAML: {exc}"]) from exc

    schema_errors = sorted(
        _MAPPING_VALIDATOR.iter_errors(document), key=lambda e: list(e.path)
    )
    if schema_errors:
        details = [
            f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
            for err in schema_errors
        ]
        raise SpecError(path, details)
    assert isinstance(document, dict)

    problems: list[str] = []

    tz_name = document["timezone"]
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        problems.append(
            f"timezone {tz_name!r} does not resolve in the IANA database — "
            "the timezone is declared, never guessed"
        )

    vendor, product = document["vendor"], document["product"]
    label = document["source_label"]
    synthetic = bool(document["provenance"]["verified_against"].get("synthetic"))
    expected = f"{vendor}_{product}"
    if synthetic:
        if label != expected + SIMULATED_SUFFIX:
            problems.append(
                f"source_label {label!r} must be {expected + SIMULATED_SUFFIX!r}: "
                "synthetic fixtures require the _simulated suffix so simulated "
                "data stays permanently distinguishable in provenance "
                "(handoff 0005 binding rule)"
            )
    elif label != expected:
        problems.append(
            f"source_label {label!r} must be '<vendor>_<product>' = {expected!r} "
            "(the _simulated suffix is reserved for synthetic-provenance specs)"
        )

    fields = tuple(
        _build_field(target, doc) for target, doc in document["fields"].items()
    )
    datetime_targets = {
        fd.target for fd in fields if fd.kind == "from" and fd.coerce == "datetime"
    }
    for fd in fields:
        if fd.kind == "derived" and fd.derived == "local_date_of":
            if fd.of not in datetime_targets:
                problems.append(
                    f"fields/{fd.target}: local_date_of references {fd.of!r}, "
                    "which is not a datetime-coerced mapped target field"
                )
        if fd.kind == "from" and (fd.unit_from or fd.unit_to):
            if fd.coerce not in ("decimal", "number"):
                problems.append(
                    f"fields/{fd.target}: unit conversion requires coerce "
                    f"decimal or number, not {fd.coerce!r}"
                )

    if problems:
        raise SpecError(path, problems)

    source_format = document["source_format"]
    csv_opts = source_format.get("csv") or {}
    filters = tuple(
        Filter(
            column=f["column"],
            op=f["op"],
            value=f.get("value"),
            values=tuple(f.get("values") or ()),
            reason=f["reason"],
        )
        for f in document.get("filters") or ()
    )

    return MappingSpec(
        path=str(path),
        vendor=vendor,
        product=product,
        source_label=label,
        target_contract=document["target_contract"],
        encoding=source_format.get("encoding", "utf-8-sig"),
        delimiter=csv_opts.get("delimiter", ","),
        quotechar=csv_opts.get("quotechar", '"'),
        skip_leading_rows=csv_opts.get("skip_leading_rows", 0),
        timezone_name=tz_name,
        filters=filters,
        fields=fields,
        synthetic=synthetic,
        spec_sha12=hashlib.sha256(spec_bytes).hexdigest()[:12],
        raw=document,
    )
