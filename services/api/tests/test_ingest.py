"""The authenticated ingest endpoint: content-addressing, the EXACT v0
envelope (validated against the actual contract schema file), store-before-
produce ordering, malformed-still-landed, the 32 MiB cap, loud 503 when
unconfigured, and the per-key rate limit."""

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from conftest import FakeWebhookSender, machine_header

from headway_api import __version__
from headway_api.app import create_app
from headway_api.machine_auth import RateLimiter
from headway_api.routers import ingest

CONTRACT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "raw-record-envelope.v0.schema.json"
)

VALID_CSV = (
    b"passenger_event_id,service_date,event_timestamp,trip_stop_sequence,"
    b"event_type,vehicle_id\n"
    b"pe-1,2026-06-01,2026-06-01T08:00:00Z,1,Passenger boarded,veh-42\n"
)


@pytest.fixture
def ingest_key(fake_db):
    _, full_key = fake_db.add_api_key(
        name="simulator key",
        scopes=("ingest:tides",),
        source_label="tides_simulated",
    )
    return full_key


def _post(client, key, body=VALID_CSV, extra_headers=None, query=""):
    headers = machine_header(key)
    headers.update(extra_headers or {})
    return client.post(
        "/ingest/tides/passenger-events" + query, content=body, headers=headers
    )


def test_happy_path_lands_produces_and_audits(
    client, fake_db, ingest_key, fake_store, fake_producer
):
    r = _post(client, ingest_key)
    assert r.status_code == 202
    record_id = hashlib.sha256(VALID_CSV).hexdigest()
    assert r.json() == {"record_id": record_id, "parse_status": "ok"}
    # Exact bytes at the content-addressed key (tides.go layout).
    key = f"raw/tides/{record_id}.csv"
    assert fake_store.objects == {key: VALID_CSV}
    # One envelope on the contract topic, keyed by record_id.
    assert len(fake_producer.produced) == 1
    topic, msg_key, value = fake_producer.produced[0]
    assert topic == "raw.tides.passenger_events"
    assert msg_key == record_id.encode()
    envelope = json.loads(value)
    assert envelope["payload"] == key
    assert envelope["payload_encoding"] == "object_ref"
    assert envelope["connector"] == "headway-api-ingest"
    assert envelope["connector_version"] == __version__
    assert envelope["content_type"] == "text/csv"
    # Successful key use audited at endpoint level, actor key:<prefix>.
    events = [e for e in fake_db.audit_events if e["action"] == "ingest"]
    assert len(events) == 1
    assert events[0]["actor"].startswith("key:hwk_")
    assert events[0]["subject_id"] == record_id
    detail = json.loads(events[0]["detail"])
    assert detail["parse_status"] == "ok"
    assert detail["source"] == "tides_simulated"


def test_envelope_validates_against_the_actual_contract_schema(
    client, ingest_key, fake_producer
):
    _post(client, ingest_key)
    schema = json.loads(CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
    envelope = json.loads(fake_producer.produced[0][2])
    jsonschema.validate(
        envelope, schema, format_checker=jsonschema.FormatChecker()
    )
    assert envelope["envelope_version"] == 0


def test_source_is_the_keys_label_and_client_supplied_source_is_ignored(
    client, ingest_key, fake_producer
):
    # A client claiming to be the real 'tides' feed (header AND query) must
    # be ignored: the envelope source is ALWAYS the key's bound source_label.
    _post(
        client,
        ingest_key,
        extra_headers={"X-Headway-Source": "tides", "Source": "tides"},
        query="?source=tides",
    )
    envelope = json.loads(fake_producer.produced[0][2])
    assert envelope["source"] == "tides_simulated"


def test_store_before_produce_ordering(client, ingest_key, ingest_call_log):
    _post(client, ingest_key)
    assert [c[0] for c in ingest_call_log] == ["store.put", "producer.produce"]


def test_malformed_csv_still_stored_and_produced(
    client, fake_db, ingest_key, fake_store, fake_producer
):
    body = b"wrong,columns\n1,2\n"
    r = _post(client, ingest_key, body=body)
    assert r.status_code == 202
    assert r.json()["parse_status"] == "malformed"
    record_id = hashlib.sha256(body).hexdigest()
    # Landed AND produced — flagged, never dropped (Guardrail 7).
    assert fake_store.objects == {f"raw/tides/{record_id}.csv": body}
    envelope = json.loads(fake_producer.produced[0][2])
    assert envelope["parse_status"] == "malformed"
    assert "passenger_event_id" in envelope["parse_error"]
    # Still schema-valid.
    schema = json.loads(CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(envelope, schema)
    events = [e for e in fake_db.audit_events if e["action"] == "ingest"]
    assert json.loads(events[0]["detail"])["parse_status"] == "malformed"


def test_body_over_32_mib_is_413(client, ingest_key, fake_store, fake_producer):
    r = _post(client, ingest_key, body=b"x" * (32 * 1024 * 1024 + 1))
    assert r.status_code == 413
    assert "32 MiB" in r.json()["detail"]
    assert fake_store.objects == {}
    assert fake_producer.produced == []


def test_empty_body_is_422(client, ingest_key, fake_store):
    r = _post(client, ingest_key, body=b"")
    assert r.status_code == 422
    assert fake_store.objects == {}


def test_unconfigured_ingest_is_a_loud_503_never_a_silent_accept(
    fake_db, settings, monkeypatch
):
    from fastapi.testclient import TestClient

    # Nothing injected AND nothing in the environment: the lifespan must
    # leave both seams None and the endpoint must refuse loudly.
    for var in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY", "KAFKA_BROKERS"):
        monkeypatch.delenv(var, raising=False)

    app = create_app(
        settings=settings,
        db=fake_db,
        object_store=None,
        producer=None,
        webhook_sender=FakeWebhookSender(),
    )
    _, full_key = fake_db.add_api_key()
    with TestClient(app) as client:
        r = _post(client, full_key)
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"]
    assert "Nothing was stored" in r.json()["detail"]


def test_rate_limit_429_with_retry_after(client, app, fake_db, ingest_key):
    app.state.machine_rate_limiter = RateLimiter(requests_per_minute=2)
    assert _post(client, ingest_key).status_code == 202
    assert _post(client, ingest_key).status_code == 202
    r = _post(client, ingest_key)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert "rate limit" in r.json()["detail"]
    # A different key has its own bucket.
    _, other_key = fake_db.add_api_key(name="other vendor")
    assert _post(client, other_key).status_code == 202


def test_rate_limit_refills_over_time():
    now = [0.0]
    limiter = RateLimiter(requests_per_minute=60, clock=lambda: now[0])
    for _ in range(60):
        assert limiter.try_acquire("k") is None
    retry_after = limiter.try_acquire("k")
    assert retry_after is not None and 0 < retry_after <= 1.0
    now[0] += 2.0  # 60/min == 1 token/sec
    assert limiter.try_acquire("k") is None


def test_header_check_matches_tides_connector_semantics():
    # BOM tolerated, column order irrelevant — exactly like tides.go.
    bom_csv = "\ufeff" + VALID_CSV.decode()
    assert ingest.check_tides_header(bom_csv.encode()) is None
    assert ingest.check_tides_header(b"") is not None
    missing = ingest.check_tides_header(b"passenger_event_id,service_date\n")
    assert "event_timestamp" in missing
