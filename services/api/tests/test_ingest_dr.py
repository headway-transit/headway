"""The authenticated DR trips ingest endpoint (handoff 0013): the same
connector discipline as the TIDES path — content-addressing, the EXACT v0
envelope validated against the contract schema, store-before-produce,
malformed-still-landed, key-bound source label, scope deny-by-default."""

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from conftest import auth_header, machine_header

from headway_api.routers import ingest

CONTRACT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "raw-record-envelope.v0.schema.json"
)

VALID_CSV = (
    b"dr_trip_id,service_date,vehicle_id,mode,tos,pickup_timestamp,"
    b"dropoff_timestamp,riders,attendants_companions,ada_related,sponsored,"
    b"no_show\n"
    b"drt-1,2026-07-14,van-1,DR,DO,2026-07-14T13:00:00Z,"
    b"2026-07-14T13:20:00Z,1,0,true,false,false\n"
)


@pytest.fixture
def dr_key(fake_db):
    _, full_key = fake_db.add_api_key(
        name="dr simulator key",
        scopes=("ingest:dr",),
        source_label="dr_simulated",
    )
    return full_key


def _post(client, key, body=VALID_CSV, extra_headers=None, query=""):
    headers = machine_header(key)
    headers.update(extra_headers or {})
    return client.post("/ingest/dr/trips" + query, content=body, headers=headers)


def test_happy_path_lands_produces_and_audits(
    client, fake_db, dr_key, fake_store, fake_producer
):
    r = _post(client, dr_key)
    assert r.status_code == 202
    record_id = hashlib.sha256(VALID_CSV).hexdigest()
    assert r.json() == {"record_id": record_id, "parse_status": "ok"}
    # Exact bytes at the content-addressed key (dr.go layout).
    key = f"raw/dr/{record_id}.csv"
    assert fake_store.objects == {key: VALID_CSV}
    # One envelope on the contract topic, keyed by record_id.
    assert len(fake_producer.produced) == 1
    topic, msg_key, value = fake_producer.produced[0]
    assert topic == "raw.dr.trips"
    assert msg_key == record_id.encode()
    envelope = json.loads(value)
    assert envelope["payload"] == key
    assert envelope["payload_encoding"] == "object_ref"
    assert envelope["connector"] == "headway-api-ingest"
    assert envelope["content_type"] == "text/csv"
    # Envelope validates against the actual wire contract schema.
    schema = json.loads(CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(envelope, schema, format_checker=jsonschema.FormatChecker())
    # Successful key use audited at endpoint level, actor key:<prefix>.
    events = [e for e in fake_db.audit_events if e["action"] == "ingest"]
    assert len(events) == 1
    assert events[0]["actor"].startswith("key:hwk_")
    detail = json.loads(events[0]["detail"])
    assert detail["topic"] == "raw.dr.trips"
    assert detail["source"] == "dr_simulated"


def test_source_is_the_keys_label_and_client_supplied_source_is_ignored(
    client, dr_key, fake_producer
):
    # A client claiming to be the real 'dr' feed (header AND query) must be
    # ignored: the envelope source is ALWAYS the key's bound source_label.
    _post(
        client,
        dr_key,
        extra_headers={"X-Headway-Source": "dr", "Source": "dr"},
        query="?source=dr",
    )
    envelope = json.loads(fake_producer.produced[0][2])
    assert envelope["source"] == "dr_simulated"


def test_store_before_produce_ordering(client, dr_key, ingest_call_log):
    _post(client, dr_key)
    assert [c[0] for c in ingest_call_log] == ["store.put", "producer.produce"]


def test_malformed_csv_still_stored_and_produced(
    client, dr_key, fake_store, fake_producer
):
    body = b"wrong,columns\n1,2\n"
    r = _post(client, dr_key, body=body)
    assert r.status_code == 202
    assert r.json()["parse_status"] == "malformed"
    record_id = hashlib.sha256(body).hexdigest()
    # Landed AND produced — flagged, never dropped (Guardrail 7).
    assert fake_store.objects == {f"raw/dr/{record_id}.csv": body}
    envelope = json.loads(fake_producer.produced[0][2])
    assert envelope["parse_status"] == "malformed"
    assert "demand_response_trip header check failed" in envelope["parse_error"]
    assert "dr_trip_id" in envelope["parse_error"]
    # Still schema-valid.
    schema = json.loads(CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(envelope, schema)


def test_tides_scope_cannot_push_dr_trips(client, fake_db, fake_producer):
    """Deny-by-default across ingest families: an ingest:tides key holds no
    ingest:dr permission."""
    _, tides_key = fake_db.add_api_key(
        name="tides key", scopes=("ingest:tides",), source_label="tides_simulated"
    )
    r = _post(client, tides_key)
    assert r.status_code == 403
    assert "ingest:dr" in r.json()["detail"]
    assert fake_producer.produced == []


def test_dr_scope_cannot_push_tides(client, fake_db, dr_key, fake_producer):
    r = client.post(
        "/ingest/tides/passenger-events",
        content=b"anything",
        headers=machine_header(dr_key),
    )
    assert r.status_code == 403
    assert "ingest:tides" in r.json()["detail"]
    assert fake_producer.produced == []


def test_empty_body_is_422(client, dr_key, fake_store):
    r = _post(client, dr_key, body=b"")
    assert r.status_code == 422
    assert fake_store.objects == {}


def test_header_check_matches_dr_connector_semantics():
    # BOM tolerated, column order irrelevant — exactly like dr.go.
    bom_csv = "﻿" + VALID_CSV.decode()
    assert ingest.check_dr_header(bom_csv.encode()) is None
    assert ingest.check_dr_header(b"") is not None
    missing = ingest.check_dr_header(b"dr_trip_id,service_date\n")
    assert "tos" in missing and "no_show" in missing


def test_issuing_dr_ingest_key_requires_source_label(client, fake_db):
    """The machine-keys issuance rule generalizes to ingest:dr (handoff
    0013): every ingest key must be bound to a source label."""
    r = client.post(
        "/machine/keys",
        json={"name": "dr vendor", "scopes": ["ingest:dr"]},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    assert "source label" in r.json()["detail"]
    r = client.post(
        "/machine/keys",
        json={
            "name": "dr simulator",
            "scopes": ["ingest:dr"],
            "source_label": "dr_simulated",
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201
    assert r.json()["scopes"] == ["ingest:dr"]
    assert r.json()["source_label"] == "dr_simulated"
