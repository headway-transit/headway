"""The raw-record inspector (handoff 0035): label, integrity, window, bytes.

The bar these tests hold: an auditor must be able to open the last link in
the chain of custody, see what it is, look inside it, and press a button that
proves the bytes are unaltered — and every failure of that must be loud,
named, and impossible to mistake for a pass.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import hashlib
import io
import json
import zipfile

import pytest

from conftest import auth_header

from headway_api import raw_payloads
from headway_api.app import Settings, create_app
from fastapi.testclient import TestClient


# --------------------------------------------------------------- fixtures


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gtfs_rt_frame(
    *,
    header_timestamp: int = 1785451084,
    vehicles: int = 3,
) -> bytes:
    """A REAL GTFS-Realtime FeedMessage built with the pinned bindings —
    the same library the transform service normalizes with. Not a
    hand-rolled byte string: a preview that decoded a fixture the spec
    would reject would prove nothing."""
    from google.transit import gtfs_realtime_pb2

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.incrementality = gtfs_realtime_pb2.FeedHeader.FULL_DATASET
    feed.header.timestamp = header_timestamp
    for i in range(vehicles):
        entity = feed.entity.add()
        entity.id = f"y{1860 + i}"
        vehicle = entity.vehicle
        vehicle.vehicle.id = f"y{1860 + i}"
        vehicle.vehicle.label = str(1860 + i)
        vehicle.trip.trip_id = f"7667800{i}"
        vehicle.trip.route_id = "18"
        vehicle.position.latitude = 42.3053 + i / 1000
        vehicle.position.longitude = -71.0589 - i / 1000
        vehicle.position.bearing = 225.0
        vehicle.timestamp = header_timestamp - 26
        vehicle.current_status = gtfs_realtime_pb2.VehiclePosition.IN_TRANSIT_TO
    return feed.SerializeToString()


DR_CSV = (
    b"dr_trip_id,service_date,vehicle_id,mode,tos,pickup_timestamp,"
    b"dropoff_timestamp,riders,attendants_companions,ada_related,sponsored,"
    b"no_show,pickup_lat,pickup_lon\n"
    b"T-1,2026-06-01,VAN-3,DR,DO,2026-06-01T09:02:00Z,2026-06-01T09:31:00Z,"
    b"1,0,true,false,false,39.7392,-104.9903\n"
)

TIDES_CSV = (
    b"passenger_event_id,service_date,trip_id,stop_id,event_timestamp,"
    b"boarding,alighting\n"
    b"PE-1,2026-06-01,T-77,STOP-3,2026-06-01T09:02:00Z,4,1\n"
    b"PE-2,2026-06-01,T-77,STOP-4,2026-06-01T09:07:00Z,2,3\n"
)

VENDOR_CSV = b"BookingRef|RunDate|Van|SvcType|PUTime\nB-1|01/06/2026|V3|D|01/06/2026 09:02\n"


def seed_gtfs_rt(db, stream, *, payload: bytes | None = None, **overrides):
    payload = payload if payload is not None else gtfs_rt_frame()
    record = db.add_raw_record(
        record_id=sha256(payload),
        source="gtfs_rt",
        connector="headway-gtfs-rt",
        content_type="application/x-protobuf",
        payload_encoding="base64",
        payload_ref=None,
        **overrides,
    )
    stream.messages[record["record_id"]] = payload
    return record


def seed_object(db, store, *, data: bytes, key: str, **overrides):
    record = db.add_raw_record(
        record_id=sha256(data),
        payload_encoding="object_ref",
        payload_ref=key,
        **overrides,
    )
    store.objects[key] = data
    return record


def seed_dr(db, store, data: bytes = DR_CSV):
    return seed_object(
        db,
        store,
        data=data,
        key=f"raw/dr/{sha256(data)}.csv",
        source="dr_simulated",
        connector="headway-dr",
        connector_version="0.2.0",
        content_type="text/csv",
    )


def seed_tides(db, store, data: bytes = TIDES_CSV):
    return seed_object(
        db,
        store,
        data=data,
        key=f"raw/tides/{sha256(data)}.csv",
        source="tides_simulated",
        connector="headway-tides",
        content_type="text/csv",
    )


def seed_vendor(db, store, data: bytes = VENDOR_CSV):
    return seed_object(
        db,
        store,
        data=data,
        key=f"raw/vendor/{sha256(data)}.csv",
        source="acme_paravan_simulated",
        connector="headway-vendor-file",
        content_type="text/csv",
    )


def seed_zip(db, store):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("stops.txt", "stop_id,stop_name\n1,Main St\n")
    data = buffer.getvalue()
    return seed_object(
        db,
        store,
        data=data,
        key=f"raw/gtfs_static/{sha256(data)}.zip",
        source="gtfs_static",
        connector="headway-gtfs-static",
        content_type="application/zip",
    )


# ------------------------------------------------------------------- authz


class TestAuthorization:
    def test_every_endpoint_refuses_an_unauthenticated_caller(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        rid = record["record_id"]
        for method, path in (
            ("GET", f"/raw/records/{rid}"),
            ("POST", f"/raw/records/{rid}/verify"),
            ("GET", f"/raw/records/{rid}/payload"),
            ("GET", f"/raw/records/{rid}/download"),
        ):
            response = client.request(method, path)
            assert response.status_code == 401, (method, path)

    @pytest.mark.parametrize(
        "username", ["vera", "stella", "petra", "cora"]
    )
    def test_label_and_verify_are_open_to_every_signed_in_role(
        self, client, fake_db, fake_store, username
    ):
        """Including the broadest read role, and including for a payload
        whose CONTENTS are withheld from it: a hash discloses nothing, and
        an auditor is never told that proving integrity is above their pay
        grade."""
        record = seed_dr(fake_db, fake_store)
        rid = record["record_id"]
        headers = auth_header(fake_db, username)
        assert client.get(f"/raw/records/{rid}", headers=headers).status_code == 200
        verify = client.post(f"/raw/records/{rid}/verify", headers=headers)
        assert verify.status_code == 200
        assert verify.json()["result"] == "match"

    def test_an_unknown_record_id_is_a_plain_language_404(self, client, fake_db):
        response = client.get(
            "/raw/records/" + "0" * 64, headers=auth_header(fake_db, "vera")
        )
        assert response.status_code == 404
        assert "No raw record with that id" in response.json()["detail"]


# ------------------------------------------------------------------- label


class TestLabel:
    def test_label_serves_the_registry_row_verbatim(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        body = client.get(
            f"/raw/records/{record['record_id']}",
            headers=auth_header(fake_db, "vera"),
        ).json()

        assert body["record_id"] == record["record_id"]
        assert body["source"] == "tides_simulated"
        assert body["simulated"] is True
        assert body["connector"] == "headway-tides"
        assert body["connector_version"] == "0.1.0"
        assert body["content_type"] == "text/csv"
        assert body["payload_encoding"] == "object_ref"
        assert body["parse_status"] == "ok"
        assert body["parse_error"] is None
        assert body["content_address"]["algorithm"] == "sha-256"
        assert body["content_address"]["digest"] == record["record_id"]
        # Size is MEASURED from the store, not stored in the registry.
        assert body["stored_bytes"]["status"] == "available"
        assert body["stored_bytes"]["size_bytes"] == len(TIDES_CSV)
        assert body["stored_bytes"]["object_key"] == record["payload_ref"]
        assert body["stored_bytes"]["location"] == "object_store"

    def test_malformed_record_serves_its_parse_error_never_a_placeholder(
        self, client, fake_db, fake_envelope_stream
    ):
        record = seed_gtfs_rt(
            fake_db,
            fake_envelope_stream,
            payload=b"not-a-feed-message",
            parse_status="malformed",
            parse_error="gtfs-realtime FeedMessage parse failed: proto: "
            "cannot parse invalid wire-format data",
        )
        body = client.get(
            f"/raw/records/{record['record_id']}",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["parse_status"] == "malformed"
        assert "invalid wire-format data" in body["parse_error"]

    def test_inline_payload_states_where_the_bytes_are_and_does_not_read_them(
        self, client, fake_db, fake_envelope_stream, ingest_call_log
    ):
        record = seed_gtfs_rt(fake_db, fake_envelope_stream)
        body = client.get(
            f"/raw/records/{record['record_id']}",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["stored_bytes"]["location"] == "ingest_envelope_stream"
        assert body["stored_bytes"]["object_key"] is None
        assert body["stored_bytes"]["size_bytes"] is None
        assert body["stored_bytes"]["status"] == "measured_on_open"
        # The label must stay cheap: a lineage trail can bottom out in
        # dozens of these.
        assert fake_envelope_stream.lookups == []

    def test_object_store_outage_degrades_to_an_honest_label(
        self, fake_db, settings, fake_store, fake_producer, fake_webhook_sender,
        test_signer, fake_calc_launcher
    ):
        """Open question 1 of the handoff, answered: metadata without
        payload. The record's identity does not depend on the store being
        up, so the label still serves — with the outage stated."""

        class UnreachableStore:
            def stat(self, key):
                raise ConnectionError("connection refused")

            def stream(self, key, chunk_size=1):
                raise ConnectionError("connection refused")

        record = seed_object(
            fake_db, fake_store, data=TIDES_CSV,
            key="raw/tides/x.csv", source="tides_simulated",
            connector="headway-tides", content_type="text/csv",
        )
        app = create_app(
            settings=settings, db=fake_db, object_store=fake_store,
            producer=fake_producer, webhook_sender=fake_webhook_sender,
            calc_run_launcher=fake_calc_launcher,
            raw_payload_reader=raw_payloads.CompositeRawPayloadReader(
                raw_payloads.ObjectStorePayloadReader(UnreachableStore()), None
            ),
        )
        app.state.signer = test_signer
        with TestClient(app) as client:
            body = client.get(
                f"/raw/records/{record['record_id']}",
                headers=auth_header(fake_db, "vera"),
            )
            assert body.status_code == 200
            stored = body.json()["stored_bytes"]
            assert stored["status"] == "unavailable"
            assert "could not reach the object store" in stored["note"]

    def test_missing_object_is_named_missing_on_the_label(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        fake_store.objects.clear()
        stored = client.get(
            f"/raw/records/{record['record_id']}",
            headers=auth_header(fake_db, "vera"),
        ).json()["stored_bytes"]
        assert stored["status"] == "missing"
        assert "not in the object store" in stored["note"]


# --------------------------------------------------------------- integrity


class TestVerify:
    def test_match_is_200_with_both_digests_and_the_size_it_read(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        response = client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["result"] == "match"
        assert body["algorithm"] == "sha-256"
        assert body["expected_digest"] == record["record_id"]
        assert body["actual_digest"] == record["record_id"]
        assert body["size_bytes"] == len(TIDES_CSV)
        assert body["read_from"] == "object_store"
        assert body["dq_issue_id"] is None
        assert "unaltered" in body["headline"]

    def test_mismatch_is_409_loud_and_raises_a_blocking_dq_issue(
        self, client, fake_db, fake_store
    ):
        """The alarm. A tampered or corrupted payload must be impossible to
        mistake for a pass — by status code, by wording, and by landing in
        the steward's queue rather than only on one person's screen."""
        record = seed_tides(fake_db, fake_store)
        # One byte changed in the store; the registry row is untouched.
        fake_store.objects[record["payload_ref"]] = TIDES_CSV.replace(b"4,1", b"9,1")

        response = client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "stella"),
        )
        assert response.status_code == 409
        body = response.json()
        assert body["result"] == "mismatch"
        assert body["expected_digest"] == record["record_id"]
        assert body["actual_digest"] != record["record_id"]
        assert body["actual_digest"] == sha256(
            fake_store.objects[record["payload_ref"]]
        )
        assert "MISMATCH" in body["headline"]
        assert "unproven" in body["detail"]

        issue = fake_db.dq_issues[body["dq_issue_id"]]
        assert issue["issue_type"] == "raw_record_integrity_mismatch"
        assert issue["severity"] == "blocking"
        assert issue["status"] == "open"
        assert issue["source_record_ids"] == [record["record_id"]]

    def test_repeated_mismatch_verifies_do_not_pile_up_duplicate_findings(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        fake_store.objects[record["payload_ref"]] = b"tampered"
        headers = auth_header(fake_db, "stella")
        first = client.post(f"/raw/records/{record['record_id']}/verify", headers=headers)
        second = client.post(f"/raw/records/{record['record_id']}/verify", headers=headers)
        assert first.status_code == second.status_code == 409
        assert first.json()["dq_issue_id"] == second.json()["dq_issue_id"]
        assert len(fake_db.dq_issues) == 1

    def test_missing_object_is_404_a_named_verdict_and_its_own_finding(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        fake_store.objects.clear()
        response = client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "stella"),
        )
        assert response.status_code == 404
        body = response.json()
        assert body["result"] == "missing"
        assert body["reason"] == "object_missing"
        assert body["actual_digest"] is None
        issue = fake_db.dq_issues[body["dq_issue_id"]]
        assert issue["issue_type"] == "raw_record_payload_missing"
        assert issue["severity"] == "blocking"

    def test_expired_stream_window_is_410_and_is_not_treated_as_a_defect(
        self, client, fake_db, fake_envelope_stream
    ):
        """A GTFS-Realtime frame that has aged out of the broker's retention
        window is a deployment setting, not a data-quality finding — so it
        is said plainly and NO issue is raised."""
        record = seed_gtfs_rt(fake_db, fake_envelope_stream)
        fake_envelope_stream.messages.clear()
        response = client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 410
        body = response.json()
        assert body["result"] == "unavailable"
        assert body["reason"] == "not_retained"
        assert body["dq_issue_id"] is None
        assert "no longer retains" in body["detail"]
        assert fake_db.dq_issues == {}

    def test_verify_over_the_envelope_stream_matches_the_content_address(
        self, client, fake_db, fake_envelope_stream
    ):
        record = seed_gtfs_rt(fake_db, fake_envelope_stream)
        body = client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["result"] == "match"
        assert body["read_from"] == "ingest_envelope_stream"

    def test_unconfigured_storage_refuses_with_503_never_a_false_pass(
        self, fake_db, settings, fake_producer, fake_webhook_sender,
        test_signer, fake_calc_launcher
    ):
        record = fake_db.add_raw_record(
            record_id="a" * 64, payload_encoding="object_ref",
            payload_ref="raw/tides/a.csv", content_type="text/csv",
            source="tides_simulated", connector="headway-tides",
        )
        app = create_app(
            settings=settings, db=fake_db, object_store=None,
            producer=fake_producer, webhook_sender=fake_webhook_sender,
            calc_run_launcher=fake_calc_launcher,
            raw_payload_reader=raw_payloads.CompositeRawPayloadReader(None, None),
        )
        app.state.signer = test_signer
        with TestClient(app) as client:
            response = client.post(
                f"/raw/records/{record['record_id']}/verify",
                headers=auth_header(fake_db, "vera"),
            )
        assert response.status_code == 503
        assert response.json()["result"] == "unavailable"
        assert response.json()["reason"] == "not_configured"

    def test_every_verdict_is_audited_with_its_result(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "stella"),
        )
        fake_store.objects[record["payload_ref"]] = b"tampered"
        client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "stella"),
        )
        events = [
            e for e in fake_db.audit_events if e["action"] == "raw_record_verify"
        ]
        results = [json.loads(e["detail"])["result"] for e in events]
        assert results == ["match", "mismatch"]
        assert {e["actor"] for e in events} == {"stella"}
        assert {e["subject_kind"] for e in events} == {"raw.records"}
        assert {e["subject_id"] for e in events} == {record["record_id"]}


# ------------------------------------------------------------------ window


class TestGtfsRealtimePreview:
    def test_a_frame_decodes_to_its_real_vehicles(
        self, client, fake_db, fake_envelope_stream
    ):
        record = seed_gtfs_rt(fake_db, fake_envelope_stream)
        response = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["decoder"] == "gtfs_realtime"
        assert body["read_from"] == "ingest_envelope_stream"
        feed = body["gtfs_realtime"]
        assert feed["decoded"] is True
        assert feed["gtfs_realtime_version"] == "2.0"
        assert feed["incrementality"] == "FULL_DATASET"
        assert feed["header_timestamp"] == 1785451084
        assert feed["header_timestamp_utc"].endswith("Z")
        assert feed["entity_count"] == 3
        assert feed["entity_kinds"]["vehicle"] == 3
        first = feed["entities"][0]
        assert first["kind"] == "vehicle_position"
        assert first["vehicle_id"] == "y1860"
        assert first["vehicle_label"] == "1860"
        assert first["route_id"] == "18"
        assert first["trip_id"] == "76678000"
        assert first["latitude"] == pytest.approx(42.3053, abs=1e-4)
        assert first["longitude"] == pytest.approx(-71.0589, abs=1e-4)
        assert first["current_status"] == "IN_TRANSIT_TO"
        # Absent optional fields stay absent — never a zero, never a guess.
        assert first["occupancy_status"] is None
        assert first["stop_id"] is None

    def test_entity_cap_is_enforced_and_stated_with_the_true_total(
        self, client, fake_db, fake_envelope_stream
    ):
        record = seed_gtfs_rt(
            fake_db, fake_envelope_stream, payload=gtfs_rt_frame(vehicles=60)
        )
        body = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert len(body["gtfs_realtime"]["entities"]) == raw_payloads.MAX_ENTITIES
        assert body["gtfs_realtime"]["entity_count"] == 60
        assert body["truncated"] is True
        assert "first 25 of 60 entities" in body["truncation_note"]
        assert body["caps"]["max_entities"] == raw_payloads.MAX_ENTITIES

    def test_an_undecodable_frame_says_so_and_blames_the_feed_not_the_copy(
        self, client, fake_db, fake_envelope_stream
    ):
        record = seed_gtfs_rt(
            fake_db, fake_envelope_stream, payload=b"\xff\xff not a feed \xff",
            parse_status="malformed",
            parse_error="gtfs-realtime FeedMessage parse failed",
        )
        body = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["gtfs_realtime"]["decoded"] is False
        assert "not a readable GTFS-Realtime feed message" in body["gtfs_realtime"]["decode_error"]
        assert "exactly what arrived" in body["gtfs_realtime"]["decode_error"]

    def test_preview_refuses_when_the_bytes_are_no_longer_retained(
        self, client, fake_db, fake_envelope_stream
    ):
        record = seed_gtfs_rt(fake_db, fake_envelope_stream)
        fake_envelope_stream.messages.clear()
        response = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 410
        assert "no longer retains" in response.json()["detail"]


class TestTextPreview:
    def test_contract_csv_shows_the_files_own_header_and_first_rows(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        body = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["decoder"] == "delimited_text"
        assert body["delimited"]["readable"] is True
        assert body["delimited"]["header"][0] == "passenger_event_id"
        assert "the file's own first row" in body["delimited"]["header_source"]
        assert body["delimited"]["rows"][0][0] == "PE-1"
        assert body["delimited"]["rows"][1][0] == "PE-2"
        assert body["caps"]["max_rows"] == raw_payloads.MAX_TEXT_ROWS
        # A file that fits inside the cap is NOT reported as truncated — a
        # "showing the first 2 rows" note on a 2-row file would imply rows
        # that do not exist.
        assert body["delimited"]["complete"] is True
        assert body["truncated"] is False
        assert body["truncation_note"] == (
            "This is the whole file: a header row and 2 data rows, exactly "
            "as stored."
        )

    def test_row_cap_is_enforced(self, client, fake_db, fake_store):
        rows = b"".join(
            f"PE-{i},2026-06-01,T-77,STOP-3,2026-06-01T09:02:00Z,1,0\n".encode()
            for i in range(80)
        )
        record = seed_tides(fake_db, fake_store, data=TIDES_CSV.splitlines(True)[0] + rows)
        body = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert len(body["delimited"]["rows"]) == raw_payloads.MAX_TEXT_ROWS
        assert body["truncated"] is True

    def test_vendor_export_shows_lines_verbatim_and_names_no_columns(
        self, client, fake_db, fake_store
    ):
        """Never guessed: what a vendor export's columns mean is defined only
        by its registered mapping spec, which the API does not hold."""
        record = seed_vendor(fake_db, fake_store)
        body = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "stella"),
        ).json()
        assert body["decoder"] == "text"
        assert body["delimited"] is None
        assert body["text"]["lines"][0].startswith("BookingRef|RunDate")
        assert "does not know this file's column names" in body["truncation_note"]

    def test_bytes_that_are_not_utf8_are_not_mangled_into_a_preview(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store, data=b"id,name\n1,\xff\xfe\n")
        body = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["delimited"]["readable"] is False
        assert "not valid UTF-8" in body["delimited"]["note"]


class TestUndecodedPreview:
    def test_an_unknown_type_states_what_it_is_and_offers_the_bytes(
        self, client, fake_db, fake_store
    ):
        record = seed_zip(fake_db, fake_store)
        body = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["decoder"] == "none"
        assert body["undecoded"]["content_type"] == "application/zip"
        assert body["gtfs_realtime"] is body["delimited"] is body["text"] is None
        assert body["size_bytes"] > 0
        assert "download" in body["download_note"]
        assert "no reader for application/zip" in body["truncation_note"]


# ------------------------------------------------------------- sensitivity


class TestSensitivity:
    def test_paratransit_payload_is_withheld_from_the_broadest_read_role(
        self, client, fake_db, fake_store
    ):
        record = seed_dr(fake_db, fake_store)
        for path in ("payload", "download"):
            response = client.get(
                f"/raw/records/{record['record_id']}/{path}",
                headers=auth_header(fake_db, "vera"),
            )
            assert response.status_code == 403, path
            detail = response.json()["detail"]
            assert "rider home and destination addresses" in detail
            assert "prove its bytes are unaltered" in detail

    @pytest.mark.parametrize("username", ["stella", "petra", "cora"])
    def test_paratransit_payload_opens_for_the_roles_allowed_coordinates(
        self, client, fake_db, fake_store, username
    ):
        record = seed_dr(fake_db, fake_store)
        body = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, username),
        )
        assert body.status_code == 200
        assert body.json()["delimited"]["header"][-2:] == ["pickup_lat", "pickup_lon"]

    def test_a_vendor_export_is_gated_fail_closed(
        self, client, fake_db, fake_store
    ):
        """A vendor export can be a paratransit booking file — the reference
        acme/paravan spec targets demand_response_trip — and the raw-record
        index does not record which contract a label maps to."""
        record = seed_vendor(fake_db, fake_store)
        response = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 403
        assert "vendor export" in response.json()["detail"]

    def test_the_label_states_the_rule_and_whether_this_caller_may_look(
        self, client, fake_db, fake_store
    ):
        record = seed_dr(fake_db, fake_store)
        viewer = client.get(
            f"/raw/records/{record['record_id']}",
            headers=auth_header(fake_db, "vera"),
        ).json()["sensitivity"]
        assert viewer["classification"] == "rider_location"
        assert viewer["minimum_role"] == "data_steward"
        assert viewer["preview_allowed"] is False
        assert "migration 0028" in viewer["reason"]
        assert viewer["refusal"]

        steward = client.get(
            f"/raw/records/{record['record_id']}",
            headers=auth_header(fake_db, "stella"),
        ).json()["sensitivity"]
        assert steward["preview_allowed"] is True
        assert steward["refusal"] is None

    def test_operational_records_are_open_to_any_signed_in_role(
        self, client, fake_db, fake_envelope_stream
    ):
        record = seed_gtfs_rt(fake_db, fake_envelope_stream)
        body = client.get(
            f"/raw/records/{record['record_id']}",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["sensitivity"]["classification"] == "internal"
        assert body["sensitivity"]["minimum_role"] == "viewer"
        assert body["sensitivity"]["preview_allowed"] is True

    def test_a_dr_file_landed_through_the_machine_api_is_classified_by_its_key(
        self, client, fake_db, fake_store
    ):
        """The machine-ingest connector name lands BOTH TIDES and DR files,
        so the object-key prefix is what separates them."""
        record = seed_object(
            fake_db, fake_store, data=DR_CSV,
            key=f"raw/dr/{sha256(DR_CSV)}.csv",
            source="dr_simulated", connector="headway-api-ingest",
            content_type="text/csv",
        )
        response = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 403


# --------------------------------------------------------------- the bytes


class TestDownload:
    def test_download_serves_the_exact_bytes_with_the_content_address(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        response = client.get(
            f"/raw/records/{record['record_id']}/download",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 200
        assert response.content == TIDES_CSV
        assert sha256(response.content) == record["record_id"]
        assert response.headers["x-headway-record-id"] == record["record_id"]
        assert response.headers["x-headway-content-address"] == (
            f"sha-256:{record['record_id']}"
        )
        assert record["record_id"] + ".csv" in response.headers["content-disposition"]
        assert response.headers["content-type"].startswith("text/csv")

    def test_download_of_an_inline_payload_round_trips_the_frame(
        self, client, fake_db, fake_envelope_stream
    ):
        payload = gtfs_rt_frame()
        record = seed_gtfs_rt(fake_db, fake_envelope_stream, payload=payload)
        response = client.get(
            f"/raw/records/{record['record_id']}/download",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.content == payload
        assert base64.b64encode(response.content)  # bytes, not a rendering
        assert response.headers["content-type"].startswith("application/x-protobuf")

    def test_missing_bytes_refuse_loudly_rather_than_serving_an_empty_file(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        fake_store.objects.clear()
        response = client.get(
            f"/raw/records/{record['record_id']}/download",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 404
        assert "not in the object store" in response.json()["detail"]


# ------------------------------------------------------------------- audit


class TestAudit:
    def test_every_look_inside_is_recorded(self, client, fake_db, fake_store):
        record = seed_tides(fake_db, fake_store)
        headers = auth_header(fake_db, "stella")
        client.get(f"/raw/records/{record['record_id']}/payload", headers=headers)
        client.get(f"/raw/records/{record['record_id']}/download", headers=headers)
        actions = [
            e["action"] for e in fake_db.audit_events
            if e["subject_id"] == record["record_id"]
        ]
        assert actions == [
            "raw_record_payload_preview",
            "raw_record_download",
        ]

    def test_reading_the_label_is_not_audited_like_every_other_signed_in_get(
        self, client, fake_db, fake_store
    ):
        record = seed_tides(fake_db, fake_store)
        client.get(
            f"/raw/records/{record['record_id']}",
            headers=auth_header(fake_db, "vera"),
        )
        assert fake_db.audit_events == []

    def test_a_refused_look_writes_no_audit_row_because_nothing_was_read(
        self, client, fake_db, fake_store
    ):
        record = seed_dr(fake_db, fake_store)
        client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        )
        assert [
            e for e in fake_db.audit_events
            if e["action"] == "raw_record_payload_preview"
        ] == []


# ----------------------------------------------- durable landing (handoff 0036)


def rescue_key(record) -> str:
    """The deterministic key gtfsrt.ObjectKey / the backfill tool write to."""
    return f"raw/gtfs_rt/{record['record_id']}.pb"


class TestBase64ObjectStoreFallback:
    """Handoff 0036 design point 5: a base64 row's bytes are resolved from
    the object store at the DETERMINISTIC key first (re-hash on read), then
    the bounded envelope-stream lookup, then the honest 410. The row itself
    is never touched — legacy rows keep payload_encoding='base64' forever."""

    def test_rescued_bytes_verify_from_the_object_store_without_a_broker_lookup(
        self, client, fake_db, fake_envelope_stream, fake_store
    ):
        payload = gtfs_rt_frame()
        record = seed_gtfs_rt(fake_db, fake_envelope_stream, payload=payload)
        # The backfill landed the bytes at the derived key; the broker has
        # since aged the message out entirely.
        fake_store.objects[rescue_key(record)] = payload
        fake_envelope_stream.messages.clear()

        body = client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["result"] == "match"
        assert body["read_from"] == "object_store"
        assert body["actual_digest"] == record["record_id"]
        # No broker lookup happened at all — the store answered first.
        assert fake_envelope_stream.lookups == []

    def test_the_object_store_is_checked_before_the_broker(
        self, client, fake_db, fake_envelope_stream, fake_store
    ):
        payload = gtfs_rt_frame()
        record = seed_gtfs_rt(fake_db, fake_envelope_stream, payload=payload)
        fake_store.objects[rescue_key(record)] = payload  # both hold the bytes

        body = client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["result"] == "match"
        assert body["read_from"] == "object_store"
        assert fake_envelope_stream.lookups == []

    def test_rescued_preview_decodes_from_the_object_store(
        self, client, fake_db, fake_envelope_stream, fake_store
    ):
        payload = gtfs_rt_frame(vehicles=2)
        record = seed_gtfs_rt(fake_db, fake_envelope_stream, payload=payload)
        fake_store.objects[rescue_key(record)] = payload
        fake_envelope_stream.messages.clear()

        response = client.get(
            f"/raw/records/{record['record_id']}/payload",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["read_from"] == "object_store"
        assert body["gtfs_realtime"]["decoded"] is True

    def test_rescued_download_byte_fidelity(
        self, client, fake_db, fake_envelope_stream, fake_store
    ):
        payload = gtfs_rt_frame()
        record = seed_gtfs_rt(fake_db, fake_envelope_stream, payload=payload)
        fake_store.objects[rescue_key(record)] = payload
        fake_envelope_stream.messages.clear()

        response = client.get(
            f"/raw/records/{record['record_id']}/download",
            headers=auth_header(fake_db, "stella"),
        )
        assert response.status_code == 200
        assert response.content == payload
        assert sha256(response.content) == record["record_id"]

    def test_a_corrupt_object_at_the_derived_key_is_rehashed_and_never_served(
        self, client, fake_db, fake_envelope_stream, fake_store
    ):
        """Re-hash on read: an object at the content-addressed key whose
        bytes do NOT hash to the record id is not this record — the reader
        skips it and the broker fallback serves the real bytes."""
        payload = gtfs_rt_frame()
        record = seed_gtfs_rt(fake_db, fake_envelope_stream, payload=payload)
        fake_store.objects[rescue_key(record)] = payload + b"tampered"

        body = client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "vera"),
        ).json()
        assert body["result"] == "match"
        assert body["read_from"] == "ingest_envelope_stream"
        assert len(fake_envelope_stream.lookups) == 1

    def test_corrupt_object_and_expired_broker_is_still_the_honest_410(
        self, client, fake_db, fake_envelope_stream, fake_store
    ):
        payload = gtfs_rt_frame()
        record = seed_gtfs_rt(fake_db, fake_envelope_stream, payload=payload)
        fake_store.objects[rescue_key(record)] = b"not the record's bytes"
        fake_envelope_stream.messages.clear()

        response = client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 410
        body = response.json()
        assert body["result"] == "unavailable"
        assert body["reason"] == "not_retained"
        assert body["dq_issue_id"] is None

    def test_unrescued_and_expired_is_410_naming_both_places_checked(
        self, client, fake_db, fake_envelope_stream, fake_store
    ):
        record = seed_gtfs_rt(fake_db, fake_envelope_stream)
        fake_envelope_stream.messages.clear()

        response = client.post(
            f"/raw/records/{record['record_id']}/verify",
            headers=auth_header(fake_db, "vera"),
        )
        assert response.status_code == 410
        body = response.json()
        assert body["reason"] == "not_retained"
        assert "object store" in body["detail"]
        assert "no longer retains" in body["detail"]
        # Still deliberately NOT a finding (0035 ruling stands).
        assert body["dq_issue_id"] is None
        assert fake_db.dq_issues == {}

    def test_rescued_bytes_serve_even_with_no_broker_configured(
        self, fake_db, settings, fake_store, fake_producer,
        fake_webhook_sender, test_signer, fake_calc_launcher
    ):
        """After backfill, an installation can answer for a legacy base64
        record from the store alone — no KAFKA_BROKERS needed."""
        from headway_api.app import create_app

        payload = gtfs_rt_frame()
        record = fake_db.add_raw_record(
            record_id=sha256(payload),
            source="gtfs_rt",
            connector="headway-gtfs-rt",
            content_type="application/x-protobuf",
            payload_encoding="base64",
            payload_ref=None,
        )
        fake_store.objects[rescue_key(record)] = payload
        reader = raw_payloads.CompositeRawPayloadReader(
            raw_payloads.ObjectStorePayloadReader(fake_store), None
        )
        application = create_app(
            settings=settings,
            db=fake_db,
            object_store=fake_store,
            producer=fake_producer,
            webhook_sender=fake_webhook_sender,
            calc_run_launcher=fake_calc_launcher,
            raw_payload_reader=reader,
        )
        application.state.signer = test_signer
        with TestClient(application) as client:
            body = client.post(
                f"/raw/records/{record['record_id']}/verify",
                headers=auth_header(fake_db, "vera"),
            ).json()
        assert body["result"] == "match"
        assert body["read_from"] == "object_store"

    def test_store_only_installation_says_it_checked_the_store_when_bytes_are_gone(
        self, fake_db, settings, fake_store, fake_producer,
        fake_webhook_sender, test_signer, fake_calc_launcher
    ):
        from headway_api.app import create_app

        record = fake_db.add_raw_record(
            record_id="c" * 64,
            source="gtfs_rt",
            connector="headway-gtfs-rt",
            content_type="application/x-protobuf",
            payload_encoding="base64",
            payload_ref=None,
        )
        reader = raw_payloads.CompositeRawPayloadReader(
            raw_payloads.ObjectStorePayloadReader(fake_store), None
        )
        application = create_app(
            settings=settings,
            db=fake_db,
            object_store=fake_store,
            producer=fake_producer,
            webhook_sender=fake_webhook_sender,
            calc_run_launcher=fake_calc_launcher,
            raw_payload_reader=reader,
        )
        application.state.signer = test_signer
        with TestClient(application) as client:
            response = client.post(
                f"/raw/records/{record['record_id']}/verify",
                headers=auth_header(fake_db, "vera"),
            )
        assert response.status_code == 410
        assert "object store" in response.json()["detail"]

    def test_derived_key_scheme_is_pinned(self):
        record = raw_payloads.RawRecord(
            record_id="a" * 64,
            source="gtfs_rt",
            connector="headway-gtfs-rt",
            connector_version="0.2.0",
            content_type="application/x-protobuf",
            payload_encoding="base64",
            payload_ref=None,
            fetched_at=dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc),
            landed_at=dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc),
            parse_status="ok",
            parse_error=None,
        )
        assert raw_payloads.derived_object_key(record) == (
            "raw/gtfs_rt/" + "a" * 64 + ".pb"
        )
        # No scheme for other sources: never guess an address.
        tides = dataclasses.replace(record, source="tides_simulated")
        assert raw_payloads.derived_object_key(tides) is None
