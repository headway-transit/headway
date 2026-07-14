"""Vendor adapter framework v0 (handoff 0015): spec, registry, engine, harness.

The reference adapter (adapters/_reference/acme/*) is used as the primary
test bed — the same fixtures the adapters/validate harness runs in CI — plus
synthetic tmp-path specs for the refusal paths.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from conftest import FakeConnection, envelope_json

from headway_transform import consumer
from headway_transform.adapters import (
    AdapterRegistry,
    RegistryError,
    SpecError,
    load_spec,
    run_adapter,
)
from headway_transform.adapters.engine import _coerce
from headway_transform.adapters.harness import validate_all
from headway_transform.adapters.spec import FieldDef
from headway_transform.writer import DbWriter

REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTERS_DIR = REPO_ROOT / "adapters"
RIDELOG_DIR = ADAPTERS_DIR / "_reference" / "acme" / "ridelog"
PARAVAN_DIR = ADAPTERS_DIR / "_reference" / "acme" / "paravan"

RIDELOG_SPEC = RIDELOG_DIR / "mapping.v0.yaml"
PARAVAN_SPEC = PARAVAN_DIR / "mapping.v0.yaml"


def _run(spec_path: Path, fixture: Path):
    spec = load_spec(spec_path)
    data = fixture.read_bytes()
    record_id = hashlib.sha256(data).hexdigest()
    return spec, run_adapter(spec, data, record_id, spec.source_label)


MINIMAL_TIDES_SPEC = """\
mapping_spec_version: 0
vendor: testvendor
product: testproduct
source_label: testvendor_testproduct_simulated
target_contract: tides_passenger_events
source_format:
  kind: csv
timezone: America/New_York
fields:
  passenger_event_id: {from: Id}
  service_date: {derived: local_date_of, of: event_timestamp}
  event_timestamp: {from: When, coerce: datetime, format: "%Y-%m-%d %H:%M:%S %z"}
  trip_stop_sequence: {from: Seq, coerce: integer}
  event_type:
    from: Kind
    coerce: enum_map
    values: {"ON": "Passenger boarded"}
  vehicle_id: {from: Bus}
provenance:
  verified_against: {synthetic: true}
  verification_date: "2026-07-13"
"""


def _write_spec(tmp_path: Path, text: str = MINIMAL_TIDES_SPEC, fixture: bool = True) -> Path:
    adapter_dir = tmp_path / "testvendor" / "testproduct"
    adapter_dir.mkdir(parents=True)
    spec_path = adapter_dir / "mapping.v0.yaml"
    spec_path.write_text(text, encoding="utf-8")
    if fixture:
        fdir = adapter_dir / "fixtures"
        fdir.mkdir()
        (fdir / "sample.csv").write_text(
            "Id,When,Seq,Kind,Bus\n"
            "e1,2026-07-01 08:00:00 -0400,1,ON,42\n",
            encoding="utf-8",
        )
        (fdir / "sample.csv.expected.json").write_text(
            json.dumps({"total_rows": 1, "mapped": 1, "quarantined": 0, "filtered": 0}),
            encoding="utf-8",
        )
    return spec_path


# ---------------------------------------------------------------------------
# Spec loading + machine validation
# ---------------------------------------------------------------------------

def test_reference_specs_load_and_declare_features() -> None:
    ridelog = load_spec(RIDELOG_SPEC)
    assert ridelog.source_label == "acme_ridelog_simulated"
    assert ridelog.target_contract == "tides_passenger_events"
    assert ridelog.delimiter == ";" and ridelog.quotechar == "'"
    assert ridelog.skip_leading_rows == 2
    assert ridelog.synthetic is True
    paravan = load_spec(PARAVAN_SPEC)
    assert paravan.encoding == "cp1252" and paravan.delimiter == "|"


def test_spec_requires_timezone(tmp_path: Path) -> None:
    text = MINIMAL_TIDES_SPEC.replace("timezone: America/New_York\n", "")
    with pytest.raises(SpecError, match="timezone"):
        load_spec(_write_spec(tmp_path, text))


def test_spec_rejects_unresolvable_timezone(tmp_path: Path) -> None:
    text = MINIMAL_TIDES_SPEC.replace("America/New_York", "Mars/Olympus_Mons")
    with pytest.raises(SpecError, match="IANA"):
        load_spec(_write_spec(tmp_path, text))


def test_synthetic_provenance_requires_simulated_label(tmp_path: Path) -> None:
    text = MINIMAL_TIDES_SPEC.replace(
        "source_label: testvendor_testproduct_simulated",
        "source_label: testvendor_testproduct",
    )
    with pytest.raises(SpecError):
        load_spec(_write_spec(tmp_path, text))


def test_label_must_match_vendor_product(tmp_path: Path) -> None:
    text = MINIMAL_TIDES_SPEC.replace(
        "source_label: testvendor_testproduct_simulated",
        "source_label: othervendor_thing_simulated",
    )
    with pytest.raises(SpecError, match="source_label"):
        load_spec(_write_spec(tmp_path, text))


def test_spec_rejects_unknown_coercion_and_missing_required_field(tmp_path: Path) -> None:
    with pytest.raises(SpecError):
        load_spec(
            _write_spec(tmp_path, MINIMAL_TIDES_SPEC.replace("coerce: integer", "coerce: magic"))
        )
    # dropping a required target-contract field fails the per-contract check
    text = MINIMAL_TIDES_SPEC.replace("  vehicle_id: {from: Bus}\n", "")
    with pytest.raises(SpecError, match="vehicle_id"):
        load_spec(_write_spec(tmp_path / "b", text))


def test_provenance_shape_is_sample_or_synthetic_only(tmp_path: Path) -> None:
    text = MINIMAL_TIDES_SPEC.replace(
        "  verified_against: {synthetic: true}",
        '  verified_against: {manual: "Vendor Guide p. 12"}',
    )
    with pytest.raises(SpecError):
        load_spec(_write_spec(tmp_path, text))


def test_local_date_of_must_reference_datetime_field(tmp_path: Path) -> None:
    text = MINIMAL_TIDES_SPEC.replace(
        "{derived: local_date_of, of: event_timestamp}",
        "{derived: local_date_of, of: vehicle_id}",
    )
    with pytest.raises(SpecError, match="local_date_of"):
        load_spec(_write_spec(tmp_path, text))


# ---------------------------------------------------------------------------
# Registry: fail-closed registration
# ---------------------------------------------------------------------------

def test_reference_registry_loads_both_labels() -> None:
    registry = AdapterRegistry.load(ADAPTERS_DIR)
    assert "acme_ridelog_simulated" in registry.labels()
    assert "acme_paravan_simulated" in registry.labels()
    assert registry.lookup("acme_ridelog_simulated").product == "ridelog"
    assert registry.lookup("not_registered") is None


def test_registry_refuses_spec_without_fixture(tmp_path: Path) -> None:
    _write_spec(tmp_path, fixture=False)
    with pytest.raises(RegistryError, match="fixture"):
        AdapterRegistry.load(tmp_path)


def test_registry_refuses_duplicate_labels(tmp_path: Path) -> None:
    _write_spec(tmp_path)
    other = tmp_path / "testvendor" / "copy"
    shutil.copytree(tmp_path / "testvendor" / "testproduct", other)
    with pytest.raises(RegistryError, match="already registered"):
        AdapterRegistry.load(tmp_path)


def test_registry_refuses_broken_spec_loudly(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path)
    spec_path.write_text("mapping_spec_version: 0\n", encoding="utf-8")
    with pytest.raises(RegistryError):
        AdapterRegistry.load(tmp_path)


# ---------------------------------------------------------------------------
# Engine: the reference fixtures (the harness's own test bed)
# ---------------------------------------------------------------------------

def test_ridelog_fixture_full_accounting_and_reasons() -> None:
    spec, result = _run(RIDELOG_SPEC, RIDELOG_DIR / "fixtures" / "ridelog_mixed_day.csv")
    assert (result.total_rows, result.mapped_count, result.filtered_count,
            result.quarantined_count) == (11, 2, 2, 7)
    assert result.accounted()
    descriptions = "\n".join(f.description for f in result.findings)
    assert "'twelve' is not an integer" in descriptions
    assert "no entry in the spec's enum_map" in descriptions
    assert "does not exist in America/Chicago (DST spring-forward gap)" in descriptions
    assert "is ambiguous in America/Chicago (DST fall-back" in descriptions
    assert "missing required field(s) vehicle_id" in descriptions
    assert "violates the TIDES schema constraint minimum 1" in descriptions
    assert "absorbs following rows" in descriptions
    assert "excluded by mapping-spec filter #1" in descriptions
    # UTC conversion of the declared local timezone (CST is UTC-6).
    assert result.records[0]["event_timestamp"] == "2026-03-07T14:15:00Z"
    assert result.records[0]["passenger_event_id"] == "1207:00001"
    assert result.records[0]["service_date"] == "2026-03-07"
    # absent optional count stays absent (NULL downstream, never coalesced)
    assert "event_count" not in result.records[1]
    assert result.passenger_events[1].event_count is None


def test_paravan_fixture_full_accounting_and_reasons() -> None:
    spec, result = _run(PARAVAN_SPEC, PARAVAN_DIR / "fixtures" / "paravan_bookings.csv")
    assert (result.total_rows, result.mapped_count, result.filtered_count,
            result.quarantined_count) == (11, 3, 1, 7)
    descriptions = "\n".join(f.description for f in result.findings)
    # cross-field contract rules come from the dr_trips normalizer
    assert "precedes pickup_timestamp" in descriptions
    assert "no-show is revenue time but never a boarding" in descriptions
    assert "present on an unsponsored trip" in descriptions
    # JSON-Schema contract validation
    assert "demand-response-trip.v0.schema.json" in descriptions
    assert "-1 is less than the minimum" in descriptions
    # coercion refusals
    assert "'abc' is not a decimal number" in descriptions
    assert "'MAYBE' is in neither true_values" in descriptions
    first = result.records[0]
    assert first["mode"] == "DR" and first["distance_source"] == "odometer"
    assert first["tos"] == "DO"  # enum_map D -> DO
    # exact-Decimal km -> statute miles (5.2 / 1.609344)
    assert first["onboard_miles"].startswith("3.2311")
    assert first["driver_shift_id"] == "José M"  # cp1252 decoded as declared
    # America/Denver (MST, UTC-7) local -> UTC
    assert first["pickup_timestamp"] == "2026-03-07T15:05:00Z"
    no_show = result.records[1]
    assert no_show["no_show"] is True and no_show["riders"] == 0
    sponsored = result.records[2]
    assert sponsored["sponsored"] is True and sponsored["sponsor"] == "MEDICAID"


def test_lineage_carries_normalizer_and_adapter_edges() -> None:
    spec, result = _run(RIDELOG_SPEC, RIDELOG_DIR / "fixtures" / "ridelog_mixed_day.csv")
    assert len(result.edges) == 2 * len(result.passenger_events)
    adapter_edges = [e for e in result.edges if e.transform_name.startswith("adapter:")]
    assert len(adapter_edges) == len(result.passenger_events)
    for edge in adapter_edges:
        assert edge.transform_name == "adapter:acme_ridelog_simulated"
        assert edge.transform_version == spec.spec_sha12
        assert edge.input_kind == "raw.records"
        assert edge.input_id == result.record_id
    # every canonical row carries the ORIGINAL vendor file's record id
    assert all(r.source_record_id == result.record_id for r in result.passenger_events)
    assert all(r.source == "acme_ridelog_simulated" for r in result.passenger_events)


def test_deterministic_round_trip() -> None:
    _, first = _run(RIDELOG_SPEC, RIDELOG_DIR / "fixtures" / "ridelog_mixed_day.csv")
    _, second = _run(RIDELOG_SPEC, RIDELOG_DIR / "fixtures" / "ridelog_mixed_day.csv")
    assert first.records == second.records
    assert [repr(r) for r in first.passenger_events] == [
        repr(r) for r in second.passenger_events
    ]
    assert first.edges == second.edges
    assert [f.description for f in first.findings] == [
        f.description for f in second.findings
    ]


def test_empty_file_is_visible_not_silent() -> None:
    _, result = _run(RIDELOG_SPEC, RIDELOG_DIR / "fixtures" / "ridelog_empty_day.csv")
    assert result.total_rows == 0
    [finding] = result.findings
    assert finding.issue_type == "empty_vendor_file"


def test_header_mismatch_refuses_file() -> None:
    _, result = _run(RIDELOG_SPEC, RIDELOG_DIR / "fixtures" / "ridelog_wrong_export.csv")
    assert result.file_refused
    [finding] = result.findings
    assert finding.issue_type == "adapter_source_mismatch"
    assert finding.severity == "blocking"
    assert "'Cnt'" in finding.description and "'LocalTime'" in finding.description
    assert result.mapped_count == 0


def test_undecodable_bytes_refuse_file() -> None:
    spec = load_spec(PARAVAN_SPEC)  # declares cp1252; 0x81 is undefined in it
    result = run_adapter(spec, b"\x81\x81\x81", "ff" * 32, spec.source_label)
    assert result.file_refused
    [finding] = result.findings
    assert finding.issue_type == "undecodable_payload"
    assert finding.severity == "blocking"


def test_engine_refuses_source_label_mismatch() -> None:
    spec = load_spec(RIDELOG_SPEC)
    with pytest.raises(ValueError, match="mislabel provenance"):
        run_adapter(spec, b"x", "ab" * 32, "acme_paravan_simulated")


def test_datetime_with_explicit_offset_keeps_it(tmp_path: Path) -> None:
    spec = load_spec(_write_spec(tmp_path))
    fd = FieldDef(
        target="event_timestamp", kind="from", source="When",
        coerce="datetime", format="%Y-%m-%d %H:%M:%S %z",
    )
    problems: list[str] = []
    value = _coerce(fd, "2026-07-01 08:00:00 -0400", spec, problems)
    assert problems == []
    assert value.utcoffset().total_seconds() == -4 * 3600


def test_unit_conversion_is_exact(tmp_path: Path) -> None:
    spec = load_spec(_write_spec(tmp_path))
    fd = FieldDef(
        target="onboard_miles", kind="from", source="Km",
        coerce="decimal", unit_from="kilometers", unit_to="miles",
    )
    problems: list[str] = []
    assert _coerce(fd, "1.609344", spec, problems) == "1"
    fd_m = FieldDef(
        target="onboard_miles", kind="from", source="M",
        coerce="decimal", unit_from="meters", unit_to="miles",
    )
    assert _coerce(fd_m, "1609.344", spec, problems) == "1"
    assert problems == []


# ---------------------------------------------------------------------------
# Consumer wiring: fail-closed source labels on raw.vendor.files
# ---------------------------------------------------------------------------

def _vendor_envelope(payload: bytes, source: str) -> bytes:
    return envelope_json(
        payload,
        source=source,
        connector="headway-vendor-file",
        content_type="text/csv",
    )


def test_unregistered_source_label_refuses(fake_connection: FakeConnection) -> None:
    registry = AdapterRegistry.load(ADAPTERS_DIR)
    writer = DbWriter(fake_connection)
    consumer.process_message(
        writer,
        consumer.TOPIC_VENDOR_FILES,
        _vendor_envelope(b"a,b\n1,2\n", "tripspark_streets"),
        adapter_registry=registry,
    )
    # raw record retained; zero canonical writes; blocking refusal recorded
    assert len(fake_connection.sql_for("raw.records")) == 1
    assert fake_connection.sql_for("canonical.passenger_events") == []
    assert fake_connection.sql_for("canonical.dr_trips") == []
    [(sql, params)] = fake_connection.sql_for("dq.issues")
    assert params[0] == "unregistered_adapter_source"
    assert params[1] == "blocking"
    assert "REFUSED" in params[3] and "acme_ridelog_simulated" in params[3]


def test_missing_registry_refuses(fake_connection: FakeConnection) -> None:
    writer = DbWriter(fake_connection)
    consumer.process_message(
        writer,
        consumer.TOPIC_VENDOR_FILES,
        _vendor_envelope(b"a,b\n1,2\n", "acme_ridelog_simulated"),
        adapter_registry=None,
    )
    [(sql, params)] = fake_connection.sql_for("dq.issues")
    assert params[0] == "adapter_registry_unavailable"
    assert params[1] == "blocking"
    assert fake_connection.sql_for("canonical.passenger_events") == []


def test_registered_label_flows_to_canonical(fake_connection: FakeConnection) -> None:
    registry = AdapterRegistry.load(ADAPTERS_DIR)
    writer = DbWriter(fake_connection)
    payload = (RIDELOG_DIR / "fixtures" / "ridelog_mixed_day.csv").read_bytes()
    consumer.process_message(
        writer,
        consumer.TOPIC_VENDOR_FILES,
        _vendor_envelope(payload, "acme_ridelog_simulated"),
        adapter_registry=registry,
    )
    assert len(fake_connection.sql_for("raw.records")) == 1
    events = fake_connection.sql_for("canonical.passenger_events")
    assert len(events) == 2
    record_id = hashlib.sha256(payload).hexdigest()
    for _sql, params in events:
        assert params[-2] == "acme_ridelog_simulated"  # source column
        assert params[-1] == record_id  # source_record_id
    edges = fake_connection.sql_for("lineage.edges")
    assert len(edges) == 4  # normalizer + adapter edge per canonical row
    dq = fake_connection.sql_for("dq.issues")
    assert sum(1 for _s, p in dq if p[0] == "adapter_row_quarantined") == 7
    assert sum(1 for _s, p in dq if p[0] == "adapter_rows_filtered") == 1


def test_paravan_flows_to_dr_trips(fake_connection: FakeConnection) -> None:
    registry = AdapterRegistry.load(ADAPTERS_DIR)
    writer = DbWriter(fake_connection)
    payload = (PARAVAN_DIR / "fixtures" / "paravan_bookings.csv").read_bytes()
    consumer.process_message(
        writer,
        consumer.TOPIC_VENDOR_FILES,
        _vendor_envelope(payload, "acme_paravan_simulated"),
        adapter_registry=registry,
    )
    assert len(fake_connection.sql_for("canonical.dr_trips")) == 3
    assert len(fake_connection.sql_for("lineage.edges")) == 6


# ---------------------------------------------------------------------------
# Harness: green on the reference adapters, red on drift
# ---------------------------------------------------------------------------

def test_harness_green_on_reference_adapters() -> None:
    report = validate_all(ADAPTERS_DIR)
    assert report.ok, "\n".join(report.lines)


def test_harness_red_on_expected_count_drift(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path)
    expected = spec_path.parent / "fixtures" / "sample.csv.expected.json"
    expected.write_text(
        json.dumps({"total_rows": 1, "mapped": 0, "quarantined": 1, "filtered": 0}),
        encoding="utf-8",
    )
    report = validate_all(tmp_path)
    assert not report.ok
    assert any("expected counts mismatch" in line for line in report.lines)


def test_harness_red_on_missing_expected_file(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path)
    (spec_path.parent / "fixtures" / "sample.csv.expected.json").unlink()
    report = validate_all(tmp_path)
    assert not report.ok
    assert any("missing" in line and "expected.json" in line for line in report.lines)
