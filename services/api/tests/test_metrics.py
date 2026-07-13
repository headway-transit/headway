"""Computed-value reads: Decimal-safe strings, filters, and the
"explain this number" lineage tree — for human sessions AND (handoff 0006
follow-up) read:metrics machine keys, with one generic 401 for every
authentication failure on the dual-credential endpoint."""

import datetime as dt
import json
from decimal import Decimal

from conftest import auth_header, machine_header

from headway_api.machine_auth import RateLimiter


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


# ---------------------------------------------------------------------------
# Dual-credential lineage (handoff 0006 follow-up): a read:metrics machine
# key traverses lineage too; human sessions unchanged; every authentication
# failure is ONE generic 401 that never reveals which credential type the
# endpoint expected.
# ---------------------------------------------------------------------------


def _seed_lineage(fake_db):
    """A canned three-level tree: figure -> canonical position -> raw record."""
    mv = fake_db.add_metric_value()
    mvid = mv["metric_value_id"]
    fake_db.add_edge("computed.metric_values", mvid, "vrm_v0", "0.1.0",
                     "canonical.vehicle_positions", "veh1|2026-06-01T00:00:00Z")
    fake_db.add_edge("canonical.vehicle_positions", "veh1|2026-06-01T00:00:00Z",
                     "gtfsrt_normalize", "0.2.0", "raw.records", "aa" * 32)
    return mvid


def _read_key(fake_db):
    _, full_key = fake_db.add_api_key(
        name="dashboard reader", scopes=("read:metrics",), source_label=None
    )
    return full_key


def test_machine_key_traverses_lineage_and_is_audited(client, fake_db):
    mvid = _seed_lineage(fake_db)
    r = client.get(f"/metrics/values/{mvid}/lineage",
                   headers=machine_header(_read_key(fake_db)))
    assert r.status_code == 200
    tree = r.json()
    assert tree["kind"] == "computed.metric_values"
    assert tree["id"] == mvid
    assert tree["transform_name"] == "vrm_v0"
    (pos,) = tree["inputs"]
    assert pos["kind"] == "canonical.vehicle_positions"
    (raw,) = pos["inputs"]
    assert raw["kind"] == "raw.records"
    assert raw["inputs"] == []
    # Same tree a human session gets — the two paths cannot drift.
    human = client.get(f"/metrics/values/{mvid}/lineage",
                       headers=auth_header(fake_db, "vera"))
    assert human.json() == tree
    # Machine path audited: actor key:<prefix>, the id only, never figures.
    events = [e for e in fake_db.audit_events
              if e["action"] == "machine_read_lineage"]
    assert len(events) == 1
    assert events[0]["actor"].startswith("key:hwk_")
    assert events[0]["subject_id"] == mvid
    assert "lineage" in json.loads(events[0]["detail"])["path"]


def test_ingest_only_key_lineage_403_scope_denied_and_audited(client, fake_db):
    mvid = _seed_lineage(fake_db)
    _, ingest_key = fake_db.add_api_key(
        name="simulator key", scopes=("ingest:tides",),
        source_label="tides_simulated",
    )
    r = client.get(f"/metrics/values/{mvid}/lineage",
                   headers=machine_header(ingest_key))
    assert r.status_code == 403
    assert "read:metrics" in r.json()["detail"]
    events = [e for e in fake_db.audit_events
              if e["action"] == "machine_scope_denied"]
    assert len(events) == 1
    assert json.loads(events[0]["detail"])["required_scope"] == "read:metrics"


def test_revoked_key_lineage_generic_401_still_audited(client, fake_db):
    mvid = _seed_lineage(fake_db)
    _, revoked_key = fake_db.add_api_key(
        name="old reader", scopes=("read:metrics",), revoked=True
    )
    r = client.get(f"/metrics/values/{mvid}/lineage",
                   headers=machine_header(revoked_key))
    assert r.status_code == 401
    # The wire response is generic — identical to a no-credential 401; the
    # audit trail keeps the real reason.
    no_credential = client.get(f"/metrics/values/{mvid}/lineage")
    assert r.json()["detail"] == no_credential.json()["detail"]
    events = [e for e in fake_db.audit_events
              if e["action"] == "machine_auth_failed"]
    assert len(events) == 1
    assert json.loads(events[0]["detail"])["reason"] == "key revoked"


def test_lineage_generic_401_never_leaks_expected_credential_type(client, fake_db):
    mvid = _seed_lineage(fake_db)
    _, revoked_key = fake_db.add_api_key(
        name="old reader", scopes=("read:metrics",), revoked=True
    )
    url = f"/metrics/values/{mvid}/lineage"
    failures = [
        client.get(url),  # no credential at all
        client.get(url, headers={"Authorization": "Bearer not-a-real-token"}),
        client.get(url, headers=machine_header("hwk_unknown-key-material")),
        client.get(url, headers=machine_header(revoked_key)),
    ]
    details = [r.json()["detail"] for r in failures]
    assert all(r.status_code == 401 for r in failures)
    # One identical, generic message for every failure mode...
    assert len(set(details)) == 1
    # ...that names neither credential type nor a next step specific to one.
    lowered = details[0].lower()
    for leak in ("machine", "api key", "session", "sign in", "hwk_"):
        assert leak not in lowered


def test_human_session_lineage_unchanged_no_rate_limit_no_audit(
    client, app, fake_db
):
    mvid = _seed_lineage(fake_db)
    # Even with the machine bucket exhausted, human sessions are untouched.
    app.state.machine_rate_limiter = RateLimiter(requests_per_minute=1)
    key = _read_key(fake_db)
    assert client.get(f"/metrics/values/{mvid}/lineage",
                      headers=machine_header(key)).status_code == 200
    assert client.get(f"/metrics/values/{mvid}/lineage",
                      headers=machine_header(key)).status_code == 429
    r = client.get(f"/metrics/values/{mvid}/lineage",
                   headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    # No machine-read audit for the human read; the machine one is audited.
    assert len([e for e in fake_db.audit_events
                if e["action"] == "machine_read_lineage"]) == 1


def test_lineage_rate_limit_429_with_retry_after_on_machine_path(
    client, app, fake_db
):
    mvid = _seed_lineage(fake_db)
    app.state.machine_rate_limiter = RateLimiter(requests_per_minute=2)
    headers = machine_header(_read_key(fake_db))
    url = f"/metrics/values/{mvid}/lineage"
    assert client.get(url, headers=headers).status_code == 200
    assert client.get(url, headers=headers).status_code == 200
    r = client.get(url, headers=headers)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert "rate limit" in r.json()["detail"]
    # It is the same per-key bucket the other machine endpoints spend from.
    assert client.get("/machine/metrics", headers=headers).status_code == 429


def test_every_row_carries_its_category_and_ops_is_filterable(client, fake_db):
    """Handoff 0014: ops metrics are served WITH an explicit category so
    the UI can badge them ("Operations metric — not an NTD reported
    figure"); ?category= slices on the boundary."""
    fake_db.add_metric_value(metric="vrm")
    ops = fake_db.add_metric_value(
        metric="otp",
        unit="percent",
        calc_name="otp_v0",
        calc_version="0.1.0",
        category="ops",
        value=Decimal("87.50"),
        detail={"on_time_count": 7, "early_tolerance_seconds": 60},
    )
    r = client.get("/metrics/values", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    by_metric = {row["metric"]: row for row in r.json()}
    assert by_metric["vrm"]["category"] == "ntd"
    assert by_metric["otp"]["category"] == "ops"
    assert by_metric["otp"]["value"] == "87.50"

    r_ops = client.get(
        "/metrics/values?category=ops", headers=auth_header(fake_db, "vera")
    )
    assert [row["metric_value_id"] for row in r_ops.json()] == [
        ops["metric_value_id"]
    ]
    r_ntd = client.get(
        "/metrics/values?category=ntd", headers=auth_header(fake_db, "vera")
    )
    assert [row["metric"] for row in r_ntd.json()] == ["vrm"]


def test_category_filter_validates_vocabulary(client, fake_db):
    r = client.get(
        "/metrics/values?category=secret", headers=auth_header(fake_db, "vera")
    )
    assert r.status_code == 422
