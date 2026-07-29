"""Fleet-telematics normalizer (handoff 0028): vendor JSON pages built
in-test from the PUBLISHED Samsara response schema, plus contract
conformance, the consumer routing and the writer insert for the
raw.telematics.vehicle_stats path.

Every fixture below is SYNTHETIC and clearly labelled as such. No live
Samsara account was ever contacted; the shapes are taken from the vendor's
published OpenAPI document (VehicleStatsListResponse / paginationResponse /
VehicleStats*WithDecoration), version 2025-10-23, retrieved 2026-07-29.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest

from conftest import FakeConnection, make_envelope_dict

from headway_transform import consumer
from headway_transform.telematics_vehicle_days import (
    REGISTERED_SOURCES,
    TRANSFORM_NAME,
    TRANSFORM_VERSION,
    CanonicalTelematicsDay,
    normalize,
)
from headway_transform.writer import DbWriter

RECORD_ID = "ab" * 32
TZ = "America/New_York"
POLLED_AT = "2026-07-21T09:00:00Z"

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "contracts" / "fleet-telematics.v0.schema.json"
)
with open(CONTRACT_PATH, encoding="utf-8") as _f:
    CONTRACT = json.load(_f)
CONTRACT_VALIDATOR = jsonschema.Draft202012Validator(CONTRACT)


def page(*vehicles: dict, has_next: bool = False, cursor: str = "") -> bytes:
    """One VehicleStatsListResponse page, per the vendor's published schema."""
    return json.dumps(
        {
            "data": list(vehicles),
            "pagination": {"endCursor": cursor, "hasNextPage": has_next},
        }
    ).encode("utf-8")


def vehicle(vehicle_id: str = "281474977075805", name: str = "Van 7", **series) -> dict:
    entry: dict = {"id": vehicle_id, "name": name}
    entry.update(series)
    return entry


def samples(*pairs: tuple[str, object]) -> list[dict]:
    return [{"time": t, "value": v} for t, v in pairs]


def as_contract_record(row: CanonicalTelematicsDay) -> dict:
    """Render a canonical row as a fleet_telematics_vehicle_day record."""

    def ts(value: datetime | None) -> str | None:
        return None if value is None else value.isoformat()

    doc = {
        "vehicle_id": row.vehicle_id,
        "service_date": row.service_date.isoformat(),
        "window_start": ts(row.window_start),
        "window_end": ts(row.window_end),
        "measure": row.measure,
        "basis": row.basis,
        "unit": row.unit,
        "reading_kind": row.reading_kind,
        "sample_count": row.sample_count,
        "source_system": row.source,
    }
    if row.vehicle_label is not None:
        doc["vehicle_label"] = row.vehicle_label
    if row.value is not None:
        doc["value"] = format(row.value, "f")
    if row.first_reading_at is not None:
        doc["first_reading_at"] = ts(row.first_reading_at)
        doc["first_reading_value"] = format(row.first_reading_value, "f")
    if row.last_reading_at is not None:
        doc["last_reading_at"] = ts(row.last_reading_at)
        doc["last_reading_value"] = format(row.last_reading_value, "f")
    if row.max_sample_gap_seconds is not None:
        doc["max_sample_gap_seconds"] = row.max_sample_gap_seconds
    return doc


def assert_contract_conformant(rows: list[CanonicalTelematicsDay]) -> None:
    for row in rows:
        errors = sorted(
            CONTRACT_VALIDATOR.iter_errors(as_contract_record(row)),
            key=lambda e: list(e.path),
        )
        assert not errors, (
            f"row {row.output_id} violates fleet-telematics.v0.schema.json: "
            + "; ".join(e.message for e in errors)
        )


def elapsed_hours(row: CanonicalTelematicsDay) -> float:
    """Real elapsed hours of a row's service-day window.

    Both boundaries are converted to UTC first: subtracting two datetimes
    that share a tzinfo OBJECT is wall-clock arithmetic in Python and would
    report every day as 24 hours, hiding exactly the DST behaviour under
    test.
    """
    start = row.window_start.astimezone(timezone.utc)
    end = row.window_end.astimezone(timezone.utc)
    return (end - start).total_seconds() / 3600


def run(payload: bytes, *, source: str = "samsara", tz: str | None = TZ, **kwargs):
    return normalize(payload, RECORD_ID, source, POLLED_AT, tz, **kwargs)


# --------------------------------------------------------------------------
# Happy path + contract conformance
# --------------------------------------------------------------------------


def test_happy_path_one_row_per_measure_and_basis() -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T10:00:00Z", 14010293),
                ("2026-07-20T14:00:00Z", 14051293),
            ),
            gpsDistanceMeters=samples(
                ("2026-07-20T10:00:05Z", 81029.591434899),
                ("2026-07-20T14:00:05Z", 81070.591434899),
            ),
        )
    )
    rows, edges, findings = run(payload)

    assert [f.issue_type for f in findings] == []
    assert len(rows) == 2
    assert_contract_conformant(rows)

    by_basis = {row.basis: row for row in rows}
    ecu = by_basis["ecu_odometer"]
    assert ecu.measure == "distance"
    assert ecu.unit == "meters"
    assert ecu.reading_kind == "cumulative_counter"
    assert ecu.service_date == date(2026, 7, 20)
    assert ecu.vehicle_id == "281474977075805"
    assert ecu.vehicle_label == "Van 7"
    assert ecu.sample_count == 2
    assert ecu.max_sample_gap_seconds == 4 * 3600
    assert ecu.source == "samsara"
    assert ecu.source_record_id == RECORD_ID
    assert ecu.polled_at == datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)

    # The ONLY arithmetic: last recorded reading minus first recorded
    # reading, with both endpoints stored alongside it.
    assert ecu.first_reading_value == Decimal(14010293)
    assert ecu.last_reading_value == Decimal(14051293)
    assert ecu.value == ecu.last_reading_value - ecu.first_reading_value
    assert ecu.value == Decimal(41000)

    # A double-typed vendor value stays EXACT (never binary float).
    gps = by_basis["gps_distance"]
    assert gps.first_reading_value == Decimal("81029.591434899")
    assert gps.value == Decimal("41.000000000")
    assert gps.value == gps.last_reading_value - gps.first_reading_value

    # One lineage edge per row, anchored to the raw record.
    assert len(edges) == 2
    for edge in edges:
        assert edge.output_kind == "canonical.vehicle_telematics_days"
        assert edge.transform_name == TRANSFORM_NAME
        assert edge.transform_version == TRANSFORM_VERSION
        assert edge.input_kind == "raw.records"
        assert edge.input_id == RECORD_ID
    assert {e.output_id for e in edges} == {r.output_id for r in rows}


def test_service_day_window_is_the_declared_local_day() -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T12:00:00Z", 1000),
                ("2026-07-20T13:00:00Z", 2000),
            )
        )
    )
    [row], _edges, _findings = run(payload)
    # 2026-07-20 in America/New_York is UTC-4.
    assert row.window_start == datetime.fromisoformat("2026-07-20T00:00:00-04:00")
    assert row.window_end == datetime.fromisoformat("2026-07-21T00:00:00-04:00")
    assert elapsed_hours(row) == 24
    assert row.first_reading_at >= row.window_start
    assert row.last_reading_at < row.window_end


def test_dst_days_are_not_assumed_to_be_24_hours() -> None:
    # Fall-back: 2026-11-01 is a 25-hour local day.
    fall_back = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-11-01T10:00:00Z", 1000),
                ("2026-11-01T14:00:00Z", 2000),
            )
        )
    )
    [row], _e, _f = run(fall_back)
    assert row.service_date == date(2026, 11, 1)
    assert elapsed_hours(row) == 25

    # Spring-forward: 2026-03-08 is a 23-hour local day.
    spring = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-03-08T12:00:00Z", 1000),
                ("2026-03-08T16:00:00Z", 2000),
            )
        )
    )
    [row], _e, _f = run(spring)
    assert row.service_date == date(2026, 3, 8)
    assert elapsed_hours(row) == 23


def test_samples_bucket_into_local_service_days_not_utc_days() -> None:
    # 2026-07-21T02:00Z is 2026-07-20 22:00 in the declared zone.
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-21T01:00:00Z", 1000),
                ("2026-07-21T02:00:00Z", 1500),
                ("2026-07-21T12:00:00Z", 3000),
                ("2026-07-21T13:00:00Z", 3200),
            )
        )
    )
    rows, _edges, _findings = run(payload)
    by_date = {row.service_date: row for row in rows}
    assert set(by_date) == {date(2026, 7, 20), date(2026, 7, 21)}
    assert by_date[date(2026, 7, 20)].value == Decimal(500)
    assert by_date[date(2026, 7, 21)].value == Decimal(200)
    assert_contract_conformant(rows)


# --------------------------------------------------------------------------
# Bases stay distinct; the vendor's documented failure modes surface
# --------------------------------------------------------------------------


def test_missing_ecu_odometer_is_flagged_and_never_substituted() -> None:
    payload = page(
        vehicle(
            "veh-no-ecu",
            "Van 9",
            gpsDistanceMeters=samples(
                ("2026-07-20T10:00:00Z", 1000),
                ("2026-07-20T18:00:00Z", 41000),
            ),
        )
    )
    rows, _edges, findings = run(payload)

    # Exactly one row, on the GPS basis. Nothing was promoted into the ECU
    # basis to fill the hole.
    assert [row.basis for row in rows] == ["gps_distance"]
    types = [f.issue_type for f in findings]
    assert "telematics_ecu_odometer_absent" in types
    finding = next(f for f in findings if f.issue_type == "telematics_ecu_odometer_absent")
    assert finding.severity == "warning"
    assert "veh-no-ecu" in finding.description
    assert "substitute" in finding.description
    assert finding.source_record_ids == [RECORD_ID]


def test_two_bases_that_disagree_both_land() -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T10:00:00Z", 100000),
                ("2026-07-20T14:00:00Z", 140000),
            ),
            gpsDistanceMeters=samples(
                ("2026-07-20T10:00:00Z", 5000),
                ("2026-07-20T14:00:00Z", 51000),
            ),
        )
    )
    rows, _edges, findings = run(payload)
    values = {row.basis: row.value for row in rows}
    assert values == {"ecu_odometer": Decimal(40000), "gps_distance": Decimal(46000)}
    # Disagreement is preserved, not reconciled, averaged or hidden.
    assert findings == []


def test_counter_regression_leaves_value_null_and_keeps_endpoints() -> None:
    # The vendor documents gpsDistanceMeters as counting "since the gateway
    # was installed": a replaced gateway restarts it.
    payload = page(
        vehicle(
            gpsDistanceMeters=samples(
                ("2026-07-20T10:00:00Z", 900000),
                ("2026-07-20T18:00:00Z", 120),
            )
        )
    )
    [row], _edges, findings = run(payload)

    assert row.value is None, "a contradiction is surfaced, never repaired"
    assert row.first_reading_value == Decimal(900000)
    assert row.last_reading_value == Decimal(120)
    assert row.sample_count == 2
    assert_contract_conformant([row])

    finding = next(f for f in findings if f.issue_type == "telematics_counter_regression")
    assert finding.severity == "warning"
    assert "never repaired" in finding.description


def test_single_sample_day_is_unmeasured_never_zero() -> None:
    payload = page(
        vehicle(obdOdometerMeters=samples(("2026-07-20T10:00:00Z", 14010293)))
    )
    [row], _edges, findings = run(payload)

    assert row.value is None, "one reading cannot measure a difference"
    assert row.value != Decimal(0)
    assert row.sample_count == 1
    assert row.max_sample_gap_seconds is None
    assert row.first_reading_value == row.last_reading_value == Decimal(14010293)
    assert_contract_conformant([row])

    finding = next(
        f for f in findings if f.issue_type == "telematics_insufficient_samples"
    )
    assert finding.severity == "info"
    assert "rather than assumed to be zero" in finding.description


def test_long_gap_with_movement_is_flagged_and_never_interpolated() -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T06:00:00Z", 1000),
                ("2026-07-20T20:00:00Z", 61000),
            )
        )
    )
    [row], _edges, findings = run(payload)

    assert row.max_sample_gap_seconds == 14 * 3600
    assert row.value == Decimal(60000)
    finding = next(f for f in findings if f.issue_type == "telematics_sample_gap")
    assert finding.severity == "warning"
    assert "never spread across it" in finding.description


def test_gap_threshold_is_configurable_and_quiet_below_it() -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T06:00:00Z", 1000),
                ("2026-07-20T08:00:00Z", 61000),
            )
        )
    )
    _rows, _edges, findings = run(payload, sample_gap_warning_seconds=3 * 3600)
    assert "telematics_sample_gap" not in [f.issue_type for f in findings]

    _rows, _edges, findings = run(payload, sample_gap_warning_seconds=600)
    assert "telematics_sample_gap" in [f.issue_type for f in findings]


def test_implausible_distance_is_flagged_but_the_value_is_kept_as_measured() -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T06:00:00Z", 0),
                ("2026-07-20T07:00:00Z", 9000000),
            )
        )
    )
    [row], _edges, findings = run(payload)

    assert row.value == Decimal(9000000), "the measured value is never capped"
    finding = next(
        f for f in findings if f.issue_type == "telematics_implausible_distance"
    )
    assert finding.severity == "warning"
    # Honest about where the threshold comes from.
    assert "not a vendor or regulatory limit" in finding.description


def test_engine_time_lands_on_its_own_measure_and_estimates_stay_labelled() -> None:
    payload = page(
        vehicle(
            obdEngineSeconds=samples(
                ("2026-07-20T10:00:00Z", 9723103),
                ("2026-07-20T14:00:00Z", 9730303),
            ),
            syntheticEngineSeconds=samples(
                ("2026-07-20T10:00:00Z", 9800000),
                ("2026-07-20T14:00:00Z", 9808000),
            ),
        )
    )
    rows, _edges, findings = run(payload)
    assert findings == []
    by_basis = {row.basis: row for row in rows}
    assert set(by_basis) == {"ecu_engine_time", "estimated_engine_time"}
    for row in rows:
        assert row.measure == "engine_time"
        assert row.unit == "seconds"
    # The estimate is never promoted onto the ECU basis.
    assert by_basis["ecu_engine_time"].value == Decimal(7200)
    assert by_basis["estimated_engine_time"].value == Decimal(8000)
    assert_contract_conformant(rows)


# --------------------------------------------------------------------------
# Fail-closed refusals
# --------------------------------------------------------------------------


def test_unregistered_source_label_refuses_the_whole_page() -> None:
    payload = page(
        vehicle(obdOdometerMeters=samples(("2026-07-20T10:00:00Z", 1000)))
    )
    rows, edges, findings = run(payload, source="samsara_prod")

    assert rows == [] and edges == []
    [finding] = findings
    assert finding.issue_type == "unregistered_telematics_source"
    assert finding.severity == "blocking"
    assert "zero canonical rows" in finding.description
    assert finding.source_record_ids == [RECORD_ID]


def test_registered_labels_come_from_the_checked_in_contract() -> None:
    assert REGISTERED_SOURCES == frozenset(
        CONTRACT["properties"]["source_system"]["enum"]
    )
    assert "samsara" in REGISTERED_SOURCES
    assert "samsara_simulated" in REGISTERED_SOURCES


def test_simulated_source_is_carried_verbatim() -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T10:00:00Z", 1000),
                ("2026-07-20T11:00:00Z", 2000),
            )
        )
    )
    [row], _edges, _findings = run(payload, source="samsara_simulated")
    assert row.source == "samsara_simulated"
    assert_contract_conformant([row])


def test_undeclared_timezone_refuses_the_page() -> None:
    payload = page(
        vehicle(obdOdometerMeters=samples(("2026-07-20T10:00:00Z", 1000)))
    )
    for tz in (None, "", "   "):
        rows, edges, findings = run(payload, tz=tz)
        assert rows == [] and edges == []
        [finding] = findings
        assert finding.issue_type == "telematics_timezone_undeclared"
        assert finding.severity == "blocking"
        assert "never guesses a timezone" in finding.description


def test_unresolvable_timezone_refuses_the_page() -> None:
    payload = page(
        vehicle(obdOdometerMeters=samples(("2026-07-20T10:00:00Z", 1000)))
    )
    rows, _edges, findings = run(payload, tz="Mars/Olympus_Mons")
    assert rows == []
    [finding] = findings
    assert finding.issue_type == "telematics_timezone_unresolvable"
    assert finding.severity == "blocking"


def test_unusable_fetched_at_refuses_the_page() -> None:
    payload = page(
        vehicle(obdOdometerMeters=samples(("2026-07-20T10:00:00Z", 1000)))
    )
    rows, _edges, findings = normalize(
        payload, RECORD_ID, "samsara", "2026-07-21T09:00:00", TZ
    )
    assert rows == []
    [finding] = findings
    assert finding.issue_type == "telematics_fetched_at_unusable"
    assert finding.severity == "blocking"


# --------------------------------------------------------------------------
# Malformed input is quarantined, never dropped
# --------------------------------------------------------------------------


def test_undecodable_payload_is_blocking_and_lands_nothing() -> None:
    rows, edges, findings = run(b"{not json")
    assert rows == [] and edges == []
    [finding] = findings
    assert finding.issue_type == "undecodable_payload"
    assert finding.severity == "blocking"


def test_page_without_data_list_is_blocking() -> None:
    rows, _edges, findings = run(json.dumps({"pagination": {}}).encode())
    assert rows == []
    [finding] = findings
    assert finding.issue_type == "malformed_telematics_page"
    assert finding.severity == "blocking"


def test_bad_samples_are_quarantined_while_good_ones_land() -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=[
                {"time": "2026-07-20T10:00:00Z", "value": 1000},
                {"time": "2026-07-20T11:00:00", "value": 1500},  # naive: no offset
                {"time": "not-a-time", "value": 1600},
                {"time": "2026-07-20T12:00:00Z", "value": -5},  # negative
                {"time": "2026-07-20T13:00:00Z", "value": "lots"},  # not numeric
                {"time": "2026-07-20T14:00:00Z", "value": 4000},
                "not-an-object",
            ]
        )
    )
    [row], _edges, findings = run(payload)

    assert row.sample_count == 2, "only the readable samples count"
    assert row.value == Decimal(3000)
    finding = next(
        f for f in findings if f.issue_type == "malformed_telematics_sample"
    )
    assert finding.severity == "warning"
    assert "quarantined, not dropped silently" in finding.description
    assert "never guessed" in finding.description


def test_vehicle_without_an_id_is_skipped_loudly() -> None:
    payload = page(
        {"name": "No id", "obdOdometerMeters": samples(("2026-07-20T10:00:00Z", 1))},
        vehicle(obdOdometerMeters=samples(("2026-07-20T10:00:00Z", 1000))),
    )
    rows, _edges, findings = run(payload)
    assert len(rows) == 1
    finding = next(
        f for f in findings if f.issue_type == "malformed_telematics_sample"
    )
    assert "never invented" in finding.description


def test_unmapped_series_is_recorded_not_silently_ignored() -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(("2026-07-20T10:00:00Z", 1000)),
            engineStates=[{"time": "2026-07-20T10:00:00Z", "value": "On"}],
            fuelPercents=[{"time": "2026-07-20T10:00:00Z", "value": 50}],
        )
    )
    _rows, _edges, findings = run(payload)
    finding = next(
        f for f in findings if f.issue_type == "telematics_unmapped_series"
    )
    assert finding.severity == "info"
    assert "engineStates" in finding.description
    assert "fuelPercents" in finding.description
    assert "nothing was lost" in finding.description


def test_empty_page_is_visible_not_silent() -> None:
    rows, _edges, findings = run(page())
    assert rows == []
    [finding] = findings
    assert finding.issue_type == "empty_telematics_page"
    assert finding.severity == "info"


def test_identity_keys_are_not_mistaken_for_series() -> None:
    payload = page(
        vehicle(
            externalIds={"payrollId": "ABFS18600"},
            obdOdometerMeters=samples(
                ("2026-07-20T10:00:00Z", 1000),
                ("2026-07-20T11:00:00Z", 2000),
            ),
        )
    )
    _rows, _edges, findings = run(payload)
    assert "telematics_unmapped_series" not in [f.issue_type for f in findings]


# --------------------------------------------------------------------------
# Writer + consumer wiring
# --------------------------------------------------------------------------


def test_writer_sql_matches_migration_0034(fake_connection: FakeConnection) -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T10:00:00Z", 1000),
                ("2026-07-20T14:00:00Z", 5000),
            )
        )
    )
    [row], _edges, _findings = run(payload)
    DbWriter(fake_connection).insert_telematics_days([row])

    [(sql, params)] = fake_connection.executed
    assert "INSERT INTO canonical.vehicle_telematics_days" in sql
    assert (
        "ON CONFLICT (vehicle_id, window_start, measure, basis, source_record_id)"
        in sql
    )
    assert "DO NOTHING" in sql
    assert "tenant" not in sql.lower()
    assert params == (
        row.window_start,
        row.window_end,
        date(2026, 7, 20),
        "281474977075805",
        "Van 7",
        "distance",
        "ecu_odometer",
        "meters",
        "cumulative_counter",
        Decimal(4000),
        row.first_reading_at,
        Decimal(1000),
        row.last_reading_at,
        Decimal(5000),
        2,
        4 * 3600,
        datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc),
        "samsara",
        RECORD_ID,
    )


def test_writer_preserves_null_value_for_an_unmeasured_day(
    fake_connection: FakeConnection,
) -> None:
    payload = page(
        vehicle(obdOdometerMeters=samples(("2026-07-20T10:00:00Z", 1000)))
    )
    [row], _edges, _findings = run(payload)
    DbWriter(fake_connection).insert_telematics_days([row])
    [(_sql, params)] = fake_connection.executed
    assert params[9] is None, "an unmeasured day must bind NULL, never 0"
    assert params[15] is None, "no gap without two samples"


def test_consumer_routes_object_ref_pages_through_the_normalizer(
    fake_connection: FakeConnection,
) -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T10:00:00Z", 1000),
                ("2026-07-20T14:00:00Z", 5000),
            )
        )
    )
    doc = make_envelope_dict(
        payload,
        source="samsara",
        connector="headway-samsara",
        content_type="application/json",
        payload_encoding="object_ref",
        payload="raw/telematics/deadbeef.json",
        fetched_at=POLLED_AT,
    )
    consumer.process_message(
        DbWriter(fake_connection),
        consumer.TOPIC_TELEMATICS_VEHICLE_STATS,
        json.dumps(doc).encode(),
        object_fetcher=lambda ref: payload,
        telematics_service_day_tz=TZ,
    )
    assert fake_connection.sql_for("raw.records")
    assert fake_connection.sql_for("canonical.vehicle_telematics_days")
    assert fake_connection.sql_for("lineage.edges")
    assert not fake_connection.sql_for("dq.issues")


def test_consumer_without_declared_timezone_writes_a_blocking_issue_and_no_rows(
    fake_connection: FakeConnection,
) -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T10:00:00Z", 1000),
                ("2026-07-20T14:00:00Z", 5000),
            )
        )
    )
    doc = make_envelope_dict(
        payload,
        source="samsara",
        connector="headway-samsara",
        content_type="application/json",
        payload_encoding="object_ref",
        payload="raw/telematics/deadbeef.json",
        fetched_at=POLLED_AT,
    )
    consumer.process_message(
        DbWriter(fake_connection),
        consumer.TOPIC_TELEMATICS_VEHICLE_STATS,
        json.dumps(doc).encode(),
        object_fetcher=lambda ref: payload,
        telematics_service_day_tz=None,
    )
    assert fake_connection.sql_for("raw.records"), "the raw record is retained"
    assert not fake_connection.sql_for("canonical.vehicle_telematics_days")
    issues = fake_connection.sql_for("dq.issues")
    assert issues and issues[0][1][0] == "telematics_timezone_undeclared"
    assert issues[0][1][1] == "blocking"


def test_consumer_without_an_object_fetcher_quarantines_loudly(
    fake_connection: FakeConnection,
) -> None:
    doc = make_envelope_dict(
        b"{}",
        source="samsara",
        connector="headway-samsara",
        content_type="application/json",
        payload_encoding="object_ref",
        payload="raw/telematics/deadbeef.json",
    )
    consumer.process_message(
        DbWriter(fake_connection),
        consumer.TOPIC_TELEMATICS_VEHICLE_STATS,
        json.dumps(doc).encode(),
        object_fetcher=None,
        telematics_service_day_tz=TZ,
    )
    issues = fake_connection.sql_for("dq.issues")
    assert issues and issues[0][1][0] == "object_ref_unavailable"
    assert not fake_connection.sql_for("canonical.vehicle_telematics_days")


def test_replayed_findings_share_a_dedupe_key() -> None:
    payload = page(
        vehicle(obdOdometerMeters=samples(("2026-07-20T10:00:00Z", 1000)))
    )
    _r1, _e1, first = run(payload)
    _r2, _e2, second = run(payload)
    assert [f.transform_dedupe_key() for f in first] == [
        f.transform_dedupe_key() for f in second
    ]
    assert all(f.transform_dedupe_key().startswith("transform:") for f in first)


def test_normalization_is_deterministic() -> None:
    payload = page(
        vehicle(
            obdOdometerMeters=samples(
                ("2026-07-20T14:00:00Z", 5000),
                ("2026-07-20T10:00:00Z", 1000),
            ),
            gpsDistanceMeters=samples(("2026-07-20T10:00:00Z", 20)),
        )
    )
    first = run(payload)
    second = run(payload)
    assert [r.output_id for r in first[0]] == [r.output_id for r in second[0]]
    assert first[0] == second[0]
    assert first[2] == second[2]


@pytest.mark.parametrize("basis", sorted(CONTRACT["properties"]["basis"]["enum"]))
def test_every_contract_basis_is_either_mapped_or_deliberately_reserved(
    basis: str,
) -> None:
    from headway_transform.telematics_vehicle_days import SAMSARA_SERIES

    mapped = {b for (_m, b, _u) in SAMSARA_SERIES.values()}
    # duty_status_time is deliberately unpopulated in this wave: the vendor's
    # HOS endpoints need a broader compliance scope and carry driver PII
    # (handoff 0028, "deliberately NOT implemented"). Every other basis must
    # have a mapping, or the contract carries a value nothing can produce.
    if basis == "duty_status_time":
        assert basis not in mapped
    else:
        assert basis in mapped
