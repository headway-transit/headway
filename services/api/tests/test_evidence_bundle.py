"""The evidence bundle: what an auditor takes away (handoff 0047, design 5).

The claims worth testing here are not "the endpoint returns 200". They are:

1. The bundle is COMPLETE for what it claims to cover — certification, signed
   bytes, verdict, every figure verbatim, every figure's lineage, every
   raw-record leaf's label and digest, a manifest.
2. It is HONEST about what it does not contain — a withheld record is named,
   with the server's refusal verbatim, and its payload is nowhere in the file.
3. It is ROLE-SENSITIVE and says so — the same certification produces
   different withheld lists for a steward and for an auditor, on purpose.
4. Its seal is REPRODUCIBLE — an auditor with the downloaded file and no
   Headway installation can recompute ``bundle_sha256`` and detect an edit.
5. Taking evidence out of the building is on the record, and the record does
   not become a copy of what it refused.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import hashlib
import json
from decimal import Decimal

import pytest

from conftest import UTC, add_auditor, auth_header

from headway_api import raw_payloads
from headway_api.routers import evidence
from headway_api.signing import canonical_bytes

# The bytes behind the withheld record. A distinctive rider home address: if
# any part of it reaches the response, the assertion that finds it is not
# subtle.
DR_PAYLOAD = (
    b"trip_id,pickup_lat,pickup_lon,dropoff_lat,dropoff_lon\n"
    b"dr-1,42.35991117,-71.05988117,42.36112233,-71.06033445\n"
)
DR_OBJECT_KEY = "raw/dr/2026-06-01/trips.csv"

OPEN_RECORD_ID = "a" * 64
DR_RECORD_ID = "b" * 64


def _seed(fake_db, fake_store, *, with_dr=True):
    """One certified figure whose lineage bottoms out in two raw records: an
    ordinary GTFS-Realtime frame and a demand-response trip file."""
    mv = fake_db.add_metric_value(
        metric="vrm", unit="miles", value=Decimal("12003.75")
    )
    mvid = mv["metric_value_id"]
    fake_db.add_edge(
        "computed.metric_values", mvid, "vrm_v0", "0.1.0",
        "canonical.vehicle_positions", "veh1|2026-06-01T00:00:00Z",
    )
    fake_db.add_edge(
        "canonical.vehicle_positions", "veh1|2026-06-01T00:00:00Z",
        "gtfsrt_normalize", "0.2.0", "raw.records", OPEN_RECORD_ID,
    )
    fake_db.add_raw_record(
        record_id=OPEN_RECORD_ID,
        source="gtfs_rt",
        connector="headway-gtfs-rt",
        payload_encoding="base64",
    )
    if with_dr:
        fake_db.add_edge(
            "computed.metric_values", mvid, "vrm_v0", "0.1.0",
            "canonical.dr_trips", "dr-trip-1",
        )
        fake_db.add_edge(
            "canonical.dr_trips", "dr-trip-1", "dr_normalize", "0.1.0",
            "raw.records", DR_RECORD_ID,
        )
        fake_db.add_raw_record(
            record_id=DR_RECORD_ID,
            source="dr",
            connector="headway-dr",
            content_type="text/csv",
            payload_encoding="object_ref",
            payload_ref=DR_OBJECT_KEY,
        )
        fake_store.objects[DR_OBJECT_KEY] = DR_PAYLOAD
    return mv


def _certify(client, fake_db, mv):
    r = client.post(
        "/certifications",
        json={
            "metric_value_ids": [mv["metric_value_id"]],
            "attestation": "I certify these June 2026 figures are accurate.",
            "signer_full_name": "Cora Certifier",
            "signer_title": "Chief Executive Officer",
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201, r.text
    return r.json()["certification_id"]


@pytest.fixture
def certified(client, fake_db, fake_store):
    mv = _seed(fake_db, fake_store)
    return mv, _certify(client, fake_db, mv)


def _dr_refusal():
    """The server's OWN refusal for the seeded demand-response record, taken
    from the production classifier — never re-typed here, so a reworded
    refusal fails the verbatim assertion instead of quietly passing it."""
    now = dt.datetime.now(UTC)
    return raw_payloads.classify(
        raw_payloads.RawRecord(
            record_id=DR_RECORD_ID,
            source="dr",
            connector="headway-dr",
            connector_version="0.1.0",
            content_type="text/csv",
            payload_encoding="object_ref",
            payload_ref=DR_OBJECT_KEY,
            fetched_at=now,
            landed_at=now,
            parse_status="ok",
            parse_error=None,
        )
    )


# ---------------------------------------------------------------------------
# 1. The shape
# ---------------------------------------------------------------------------


def test_bundle_carries_certification_figures_lineage_and_leaves(
    client, fake_db, certified
):
    mv, certification_id = certified
    r = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200, r.text
    bundle = r.json()

    assert bundle["bundle_type"] == "headway-evidence-bundle"
    assert bundle["bundle_version"] == 1

    # The certification: signed bytes, the signature block, and the SERVER's
    # verdict — not a claim the bundle makes about itself.
    cert = bundle["certification"]
    assert cert["certification_id"] == certification_id
    assert cert["certified_by"] == "cora"
    assert cert["signed"] is True
    assert cert["signer_full_name"] == "Cora Certifier"
    assert cert["canonical_document"] and cert["signature"]
    assert cert["verification"]["verdict"] == "verified"
    assert cert["verification"]["verified"] is True
    # The parsed document is the same bytes, not a second rendering of them.
    assert json.loads(cert["canonical_document"]) == cert["document"]

    # The figure: verbatim, with its receipt and its lineage.
    assert len(bundle["figures"]) == 1
    figure = bundle["figures"][0]
    assert figure["metric_value_id"] == mv["metric_value_id"]
    assert figure["metric"] == "vrm"
    assert figure["unit"] == "miles"
    assert figure["value"] == "12003.75"
    assert figure["receipt"]["receipt_sha256"] == figure["receipt_sha256"]
    assert figure["matches_signed_document"] is True
    assert figure["signed_receipt_sha256"] == figure["receipt_sha256"]
    assert figure["lineage"]["kind"] == "computed.metric_values"
    assert figure["lineage_error"] is None
    assert figure["raw_record_ids"] == sorted([OPEN_RECORD_ID, DR_RECORD_ID])

    # The leaves: id (= digest), label, classification.
    by_id = {r_["record_id"]: r_ for r_ in bundle["raw_records"]}
    assert set(by_id) == {OPEN_RECORD_ID, DR_RECORD_ID}
    open_record = by_id[OPEN_RECORD_ID]
    assert open_record["content_address"]["digest"] == OPEN_RECORD_ID
    assert open_record["content_address"]["algorithm"] == "sha-256"
    assert open_record["connector"] == "headway-gtfs-rt"
    assert open_record["sensitivity"]["classification"] == "internal"
    assert open_record["contents_included"] is False

    assert bundle["gaps"] == []


def test_the_figure_value_is_a_string_never_a_float(client, fake_db, certified):
    """A reported figure is NUMERIC in the database and a string in JSON. The
    bundle is the one place the number leaves the building, so a float here
    would be a rounding error somebody submits to the FTA."""
    _, certification_id = certified
    body = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "cora"),
    ).text
    figure = json.loads(body)["figures"][0]
    assert isinstance(figure["value"], str)
    assert isinstance(figure["receipt"]["value"], str)
    assert '"value": 12003.75' not in body and '"value":12003.75' not in body


def test_the_bundle_lineage_is_the_same_walk_the_explain_endpoint_serves(
    client, fake_db, certified
):
    """Reuse, asserted. If the bundle ever grew its own walk, an auditor's
    file and the 'explain this number' screen could disagree about a figure's
    provenance — and there would be no way to tell which was right."""
    mv, certification_id = certified
    headers = auth_header(fake_db, "cora")
    bundle = client.get(
        f"/certifications/{certification_id}/evidence", headers=headers
    ).json()
    walk = client.get(
        f"/metrics/values/{mv['metric_value_id']}/lineage", headers=headers
    ).json()
    assert bundle["figures"][0]["lineage"] == walk


# ---------------------------------------------------------------------------
# 2. An auditor can fetch it
# ---------------------------------------------------------------------------


def test_an_auditor_can_fetch_the_evidence_bundle(client, fake_db, certified):
    """The whole point of the surface. It is a GET, so the read-only role's
    method ban at the authentication choke point never bites it."""
    add_auditor(fake_db)
    _, certification_id = certified
    r = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "audra"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["generated_for"]["role"] == "auditor"
    assert r.json()["generated_for"]["username"] == "audra"


def test_the_bundle_is_never_served_without_a_verified_session(
    client, fake_db, certified
):
    """There is no unauthenticated endpoint. A bundle is the most complete
    view of a filing this API produces; it is not the one place authorization
    gets relaxed."""
    _, certification_id = certified
    anonymous = client.get(f"/certifications/{certification_id}/evidence")
    assert anonymous.status_code == 401
    assert "not signed in" in anonymous.json()["detail"]

    forged = client.get(
        f"/certifications/{certification_id}/evidence",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert forged.status_code == 401
    assert not [
        e for e in fake_db.audit_events
        if e["action"] == "evidence_bundle_generated"
    ]


def test_a_bundle_for_a_certification_that_does_not_exist_says_so_plainly(
    client, fake_db
):
    add_auditor(fake_db)
    r = client.get(
        "/certifications/00000000-0000-0000-0000-000000000000/evidence",
        headers=auth_header(fake_db, "audra"),
    )
    assert r.status_code == 404
    assert "No certification with that id exists" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 3. Withholding: named, verbatim, and nowhere in the file
# ---------------------------------------------------------------------------


def test_withheld_record_is_named_with_its_reason_and_its_payload_is_absent(
    client, fake_db, fake_store, certified
):
    """Rider-location withholding is not waived for an auditor: a paratransit
    pickup point is a rider's home address, and an ADA trip record discloses
    disability status by existing. So the bundle names the record, carries
    its label and
    its digest — exactly what raw_payloads promises the reader — and carries
    none of its bytes."""
    add_auditor(fake_db)
    _, certification_id = certified
    r = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "audra"),
    )
    assert r.status_code == 200
    body = r.text
    bundle = r.json()

    assert len(bundle["withheld"]) == 1
    item = bundle["withheld"][0]
    assert item["kind"] == "raw_record_contents"
    assert item["id"] == DR_RECORD_ID
    assert item["classification"] == "rider_location"
    assert item["minimum_role"] == "data_steward"
    # VERBATIM — the server's own words, character for character.
    assert item["reason"] == _dr_refusal().refusal

    # The label and the seal survive; only the contents are withheld.
    dr = {x["record_id"]: x for x in bundle["raw_records"]}[DR_RECORD_ID]
    assert dr["content_address"]["digest"] == DR_RECORD_ID
    assert dr["sensitivity"]["readable_by_this_account"] is False
    assert dr["sensitivity"]["refusal"] == _dr_refusal().refusal

    # And the payload appears NOWHERE in the response — not decoded, not
    # base64, not in a note, not in the manifest.
    assert DR_PAYLOAD.decode() not in body
    assert base64.b64encode(DR_PAYLOAD).decode() not in body
    for fragment in ("42.35991117", "-71.05988117", "dropoff_lat", "dr-1,"):
        assert fragment not in body, fragment


def test_the_bundle_is_role_sensitive_and_says_who_it_was_made_for(
    client, fake_db, certified
):
    """Two roles, one certification, two legitimately different withheld
    lists. The bundle records which account it was made for, so a reader who
    was handed the file can never mistake 'withheld from that account' for
    'not in Headway'."""
    add_auditor(fake_db)
    _, certification_id = certified

    auditor = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "audra"),
    ).json()
    steward = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "stella"),
    ).json()

    assert [w["id"] for w in auditor["withheld"]] == [DR_RECORD_ID]
    assert steward["withheld"] == []
    assert steward["manifest"]["withheld_count"] == 0
    assert auditor["manifest"]["withheld_count"] == 1

    dr_for_steward = {
        x["record_id"]: x for x in steward["raw_records"]
    }[DR_RECORD_ID]
    assert dr_for_steward["sensitivity"]["readable_by_this_account"] is True
    assert dr_for_steward["sensitivity"]["refusal"] is None

    assert auditor["generated_for"]["role"] == "auditor"
    assert steward["generated_for"]["role"] == "data_steward"
    assert "another account may receive the same certification" in (
        auditor["withholding_note"]
    )


def test_a_viewer_is_withheld_the_same_records_as_an_auditor(
    client, fake_db, certified
):
    """The auditor reads at VIEWER breadth for content sensitivity. Asserting
    the two match keeps that equivalence from drifting."""
    add_auditor(fake_db)
    _, certification_id = certified
    viewer = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "vera"),
    ).json()
    auditor = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "audra"),
    ).json()
    assert [w["id"] for w in viewer["withheld"]] == [
        w["id"] for w in auditor["withheld"]
    ]


# ---------------------------------------------------------------------------
# 4. The seal
# ---------------------------------------------------------------------------


def _recompute(document: dict) -> str:
    """What an auditor does with the downloaded file and no Headway: delete
    the one field, canonicalize, hash. Exactly the recipe printed on the
    bundle."""
    working = copy.deepcopy(document)
    del working["manifest"]["bundle_sha256"]
    return hashlib.sha256(canonical_bytes(working)).hexdigest()


def test_bundle_sha256_is_reproducible_from_the_served_document(
    client, fake_db, certified
):
    """The claim the whole manifest rests on. This recomputes from the
    RESPONSE BODY as parsed by the client — not from any server-side object —
    because that is all an auditor will have."""
    add_auditor(fake_db)
    _, certification_id = certified
    document = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "audra"),
    ).json()

    assert _recompute(document) == document["manifest"]["bundle_sha256"]
    # The recipe is stated on the bundle, precisely enough to follow.
    manifest = document["manifest"]
    assert manifest["excluded_field"] == "manifest.bundle_sha256"
    assert manifest["canonicalization"] == evidence.CANONICALIZATION
    assert "sort_keys=True" in manifest["canonicalization"]
    assert "SHA-256" in manifest["bundle_sha256_recipe"]


def test_editing_the_bundle_after_download_breaks_its_hash(
    client, fake_db, certified
):
    """A hash nobody can recompute is decoration; a hash that does not change
    when the document does is worse. One edited digit, one broken seal — and
    deleting the withheld list, the edit a bundle's own honesty invites, is
    caught too."""
    add_auditor(fake_db)
    _, certification_id = certified
    document = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "audra"),
    ).json()
    assert document["withheld"], "the withheld-removal edit needs something to remove"
    sealed = document["manifest"]["bundle_sha256"]

    tampered = copy.deepcopy(document)
    tampered["figures"][0]["value"] = "12003.76"
    assert _recompute(tampered) != sealed

    dropped = copy.deepcopy(document)
    dropped["withheld"] = []
    assert _recompute(dropped) != sealed


def test_the_manifest_names_every_artifact_with_its_digest(
    client, fake_db, certified
):
    _, certification_id = certified
    bundle = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "cora"),
    ).json()
    manifest = bundle["manifest"]
    artifacts = {a["artifact"]: a for a in manifest["artifacts"]}
    assert manifest["artifact_count"] == len(manifest["artifacts"])

    # The signed bytes, hashed as bytes.
    signed = artifacts["certification.canonical_document"]
    assert signed["sha256"] == hashlib.sha256(
        bundle["certification"]["canonical_document"].encode("utf-8")
    ).hexdigest()

    # Every figure's receipt and lineage.
    figure = bundle["figures"][0]
    mvid = figure["metric_value_id"]
    assert artifacts[f"figure:{mvid}:receipt"]["sha256"] == figure["receipt_sha256"]
    assert artifacts[f"figure:{mvid}:lineage"]["sha256"] == figure["lineage_sha256"]

    # Every raw-record leaf: the digest IS the id, which is why the bytes do
    # not have to be here.
    for record_id in (OPEN_RECORD_ID, DR_RECORD_ID):
        entry = artifacts[f"raw_record:{record_id}"]
        assert entry["sha256"] == record_id
        assert entry["kind"] == "raw_record_bytes"

    # Every artifact says where it lives and exactly what its hash covers.
    for entry in manifest["artifacts"]:
        assert entry["location"] and entry["digest_of"]


def test_the_receipt_hash_is_recomputable_from_the_served_receipt(
    client, fake_db, certified
):
    """The receipt is served WHOLE — including its own hash key — so a reader
    does not need a list of which fields to pick."""
    _, certification_id = certified
    figure = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "cora"),
    ).json()["figures"][0]
    receipt = copy.deepcopy(figure["receipt"])
    claimed = receipt.pop("receipt_sha256")
    assert hashlib.sha256(canonical_bytes(receipt)).hexdigest() == claimed


# ---------------------------------------------------------------------------
# 5. On the record, without becoming a copy of what it refused
# ---------------------------------------------------------------------------


def test_generating_a_bundle_is_audited_and_never_logs_withheld_content(
    client, fake_db, certified
):
    add_auditor(fake_db)
    _, certification_id = certified
    r = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "audra"),
    )
    assert r.status_code == 200

    events = [
        e for e in fake_db.audit_events
        if e["action"] == "evidence_bundle_generated"
    ]
    assert len(events) == 1, "one bundle, one record"
    event = events[0]
    assert event["actor"] == "audra"
    assert event["subject_kind"] == "cert.certifications"
    assert event["subject_id"] == certification_id

    detail = json.loads(event["detail"]) if isinstance(event["detail"], str) else event["detail"]
    assert detail["generated_for_role"] == "auditor"
    assert detail["figure_count"] == 1
    assert detail["raw_record_count"] == 2
    assert detail["withheld_count"] == 1
    assert detail["withheld_record_ids"] == [DR_RECORD_ID]
    assert detail["withheld_classifications"] == ["rider_location"]
    assert detail["verification_verdict"] == "verified"
    assert detail["bundle_sha256"] == r.json()["manifest"]["bundle_sha256"]

    # The record of a refusal must not become a copy of the thing refused —
    # neither the payload nor the refusal prose belongs in the audit row.
    serialized = json.dumps(detail)
    assert "42.35991117" not in serialized
    assert "pickup and dropoff coordinates" not in serialized
    assert "12003.75" not in serialized  # nor the figures themselves


def test_the_bundle_never_changes_a_figure_a_certification_or_a_record(
    client, fake_db, certified
):
    """It is a GET, and it stays one. The only row it writes is its own audit
    record."""
    mv, certification_id = certified
    before = copy.deepcopy(fake_db.certifications)
    client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "cora"),
    )
    assert fake_db.certifications == before
    assert mv["certification_status"] == "certified"
    assert fake_db.tx_log[-1] == "commit"


# ---------------------------------------------------------------------------
# 6. Gaps: drawn as gaps, never as absence
# ---------------------------------------------------------------------------


def test_a_figure_without_lineage_is_a_named_gap_not_a_blank_bundle(
    client, fake_db, fake_store
):
    """Fail loudly, without taking the rest of the evidence down with it. The
    server's own message is carried verbatim on the figure AND in gaps."""
    mv = fake_db.add_metric_value(metric="vrh", unit="hours")
    certification_id = _certify(client, fake_db, mv)
    bundle = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "cora"),
    ).json()

    figure = bundle["figures"][0]
    assert figure["lineage"] is None
    assert figure["lineage_sha256"] is None
    assert "no recorded lineage" in figure["lineage_error"]
    gap = [g for g in bundle["gaps"] if g["kind"] == "lineage_unavailable"][0]
    assert gap["id"] == mv["metric_value_id"]
    assert gap["detail"] == figure["lineage_error"]
    # The certification itself is still fully served.
    assert bundle["certification"]["verification"]["verdict"] == "verified"


def test_a_lineage_leaf_missing_from_the_index_is_a_finding(
    client, fake_db, fake_store
):
    """A raw record is supposed to be permanent. A trail that names one this
    installation does not have is a real finding, not a shorter list."""
    mv = fake_db.add_metric_value()
    fake_db.add_edge(
        "computed.metric_values", mv["metric_value_id"], "vrm_v0", "0.1.0",
        "raw.records", "c" * 64,
    )
    certification_id = _certify(client, fake_db, mv)
    bundle = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "cora"),
    ).json()

    assert bundle["raw_records"] == []
    gap = [g for g in bundle["gaps"] if g["kind"] == "raw_record_not_in_index"][0]
    assert gap["id"] == "c" * 64
    assert "supposed to be permanent" in gap["detail"]
    # The id is still in the walk: the digest is the evidence.
    assert bundle["figures"][0]["raw_record_ids"] == ["c" * 64]


def test_withheld_and_gaps_are_different_lists(client, fake_db, certified):
    """A privacy decision must never read as a data defect, or the reverse —
    either misreading produces a wrong finding against an agency."""
    add_auditor(fake_db)
    _, certification_id = certified
    bundle = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "audra"),
    ).json()
    assert bundle["withheld"] and not bundle["gaps"]
    assert "not an error and it is not a data gap" in bundle["withholding_note"]


def test_the_raw_record_label_list_is_capped_and_says_so(
    client, fake_db, fake_store, monkeypatch
):
    """A single VRH figure can bottom out in over a thousand leaves. The cap
    bounds the LABELS; every leaf id is still in the walk, and the bundle
    states exactly how many labels it left out and where to get them."""
    monkeypatch.setattr(evidence, "MAX_RAW_RECORD_LABELS", 2)
    mv = fake_db.add_metric_value()
    for i in range(4):
        record_id = f"{i}" + "d" * 63
        fake_db.add_edge(
            "computed.metric_values", mv["metric_value_id"], "vrm_v0", "0.1.0",
            "raw.records", record_id,
        )
        fake_db.add_raw_record(record_id=record_id)
    certification_id = _certify(client, fake_db, mv)
    bundle = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "cora"),
    ).json()

    assert len(bundle["raw_records"]) == 2
    assert len(bundle["figures"][0]["raw_record_ids"]) == 4
    gap = [g for g in bundle["gaps"] if g["kind"] == "raw_record_labels_capped"][0]
    assert "labels the first 2" in gap["detail"]
    assert "GET /raw/records/{record_id}" in gap["detail"]


def test_a_figure_edited_since_signing_is_a_gap_the_bundle_names(
    client, fake_db, fake_store, certified
):
    """The certificate attests to the SIGNED values. If the stored row has
    moved since, the bundle says which figure and both hashes rather than
    quietly serving today's number under yesterday's signature."""
    mv, certification_id = certified
    mv["value"] = Decimal("99999.99")
    bundle = client.get(
        f"/certifications/{certification_id}/evidence",
        headers=auth_header(fake_db, "cora"),
    ).json()

    figure = bundle["figures"][0]
    assert figure["matches_signed_document"] is False
    assert figure["receipt_sha256"] != figure["signed_receipt_sha256"]
    gap = [
        g for g in bundle["gaps"] if g["kind"] == "figure_changed_since_signing"
    ][0]
    assert gap["id"] == mv["metric_value_id"]
    assert figure["signed_receipt_sha256"] in gap["detail"]
