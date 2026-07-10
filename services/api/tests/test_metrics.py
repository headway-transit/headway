"""Computed-value reads: Decimal-safe strings, filters, and the
"explain this number" lineage tree."""

import datetime as dt
from decimal import Decimal

from conftest import auth_header


def test_values_are_strings_never_floats(client, fake_db):
    fake_db.add_metric_value(value=Decimal("10452.123456789"))
    r = client.get("/metrics/values", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    (row,) = r.json()
    assert row["value"] == "10452.123456789"
    assert isinstance(row["value"], str)


def test_detail_jsonb_round_trips_verbatim(client, fake_db):
    """The detail column (migration 0010) is served exactly as persisted:
    ratio/factor strings stay strings, counts stay ints, source_mix intact."""
    detail = {
        "total_boardings_counted": 41567,
        "operated_trips": 9123,
        "trips_with_events": 9032,
        "missing_trips": 91,
        "missing_share": "0.0100",
        "factor_applied": "1.010075",
        "source_mix": {"tides": 41345, "tides_simulated": 222},
        "missing_trip_threshold": "0.02",
        "imbalance_threshold": "0.10",
    }
    fake_db.add_metric_value(
        metric="upt", unit="unlinked_passenger_trips",
        calc_name="upt_v0", calc_version="0.5.0",
        value=Decimal("41985.90"), detail=detail,
    )
    r = client.get("/metrics/values", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    (row,) = r.json()
    assert row["detail"] == detail
    assert isinstance(row["detail"]["factor_applied"], str)
    assert isinstance(row["detail"]["missing_share"], str)
    assert row["detail"]["source_mix"]["tides_simulated"] == 222


def test_detail_less_row_serves_empty_object(client, fake_db):
    fake_db.add_metric_value()  # detail defaults to {} (column default)
    r = client.get("/metrics/values", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    (row,) = r.json()
    assert row["detail"] == {}


def test_filter_by_metric_and_period(client, fake_db):
    fake_db.add_metric_value(metric="vrm", period_start=dt.date(2026, 5, 1),
                             period_end=dt.date(2026, 5, 31))
    june = fake_db.add_metric_value(metric="vrm",
                                    period_start=dt.date(2026, 6, 1),
                                    period_end=dt.date(2026, 6, 30))
    fake_db.add_metric_value(metric="vrh", unit="hours",
                             period_start=dt.date(2026, 6, 1),
                             period_end=dt.date(2026, 6, 30))
    r = client.get(
        "/metrics/values",
        params={"metric": "vrm", "period_start": "2026-06-01",
                "period_end": "2026-06-30"},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 200
    (row,) = r.json()
    assert row["metric_value_id"] == june["metric_value_id"]
    assert row["calc_name"] == "vrm_v0"
    assert row["certification_status"] == "uncertified"


def test_lineage_tree_from_metric_value_to_raw_records(client, fake_db):
    mv = fake_db.add_metric_value()
    mvid = mv["metric_value_id"]
    # calc read two canonical positions; each came from one raw record.
    fake_db.add_edge("computed.metric_values", mvid, "vrm_v0", "0.1.0",
                     "canonical.vehicle_positions", "veh1|2026-06-01T00:00:00Z")
    fake_db.add_edge("computed.metric_values", mvid, "vrm_v0", "0.1.0",
                     "canonical.vehicle_positions", "veh1|2026-06-01T00:00:30Z")
    fake_db.add_edge("canonical.vehicle_positions", "veh1|2026-06-01T00:00:00Z",
                     "gtfsrt_normalize", "0.2.0", "raw.records", "aa" * 32)
    fake_db.add_edge("canonical.vehicle_positions", "veh1|2026-06-01T00:00:30Z",
                     "gtfsrt_normalize", "0.2.0", "raw.records", "bb" * 32)

    r = client.get(f"/metrics/values/{mvid}/lineage",
                   headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    tree = r.json()
    assert tree["kind"] == "computed.metric_values"
    assert tree["id"] == mvid
    assert tree["transform_name"] == "vrm_v0"
    assert tree["transform_version"] == "0.1.0"
    assert len(tree["inputs"]) == 2
    for pos in tree["inputs"]:
        assert pos["kind"] == "canonical.vehicle_positions"
        assert pos["transform_name"] == "gtfsrt_normalize"
        assert len(pos["inputs"]) == 1
        raw = pos["inputs"][0]
        assert raw["kind"] == "raw.records"
        assert raw["transform_name"] is None  # raw records are the bottom
        assert raw["inputs"] == []
    raw_ids = {p["inputs"][0]["id"] for p in tree["inputs"]}
    assert raw_ids == {"aa" * 32, "bb" * 32}


def test_lineage_of_unknown_value_404(client, fake_db):
    r = client.get(
        "/metrics/values/00000000-0000-0000-0000-000000000000/lineage",
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 404


def test_figure_without_lineage_fails_loudly_not_empty_200(client, fake_db):
    mv = fake_db.add_metric_value()  # no edges recorded — a pipeline defect
    r = client.get(
        f"/metrics/values/{mv['metric_value_id']}/lineage",
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 500
    assert "no recorded lineage" in r.json()["detail"]
