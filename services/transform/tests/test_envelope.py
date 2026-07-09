"""Envelope validation against the real checked-in contract file."""

from __future__ import annotations

import json

import pytest

from headway_transform.envelope import (
    Envelope,
    EnvelopeValidationError,
    PayloadDecodeError,
    parse_envelope,
    validate_envelope,
)

from conftest import envelope_json, make_envelope_dict


def test_valid_envelope_round_trips() -> None:
    payload = b"hello raw bytes"
    envelope = parse_envelope(envelope_json(payload))
    assert isinstance(envelope, Envelope)
    assert envelope.envelope_version == 0
    assert envelope.source == "gtfs_rt"
    assert envelope.parse_status == "ok"
    assert envelope.decode_payload() == payload


def test_missing_required_field_raises_typed_error() -> None:
    doc = make_envelope_dict(b"x")
    del doc["record_id"]
    with pytest.raises(EnvelopeValidationError) as excinfo:
        validate_envelope(doc)
    assert "record_id" in str(excinfo.value)


def test_bad_record_id_pattern_rejected() -> None:
    doc = make_envelope_dict(b"x", record_id="NOT-A-SHA256")
    with pytest.raises(EnvelopeValidationError):
        validate_envelope(doc)


def test_unknown_envelope_version_rejected() -> None:
    doc = make_envelope_dict(b"x", envelope_version=1)
    with pytest.raises(EnvelopeValidationError):
        validate_envelope(doc)


def test_additional_properties_rejected() -> None:
    # No tenant_id anywhere (ADR-0004) — and the contract closes the object.
    doc = make_envelope_dict(b"x")
    doc["tenant_id"] = "should-not-exist"
    with pytest.raises(EnvelopeValidationError):
        validate_envelope(doc)


def test_invalid_json_is_a_validation_error_not_a_crash() -> None:
    with pytest.raises(EnvelopeValidationError):
        parse_envelope(b"this is not json{{")


def test_all_violations_reported_not_just_first() -> None:
    doc = make_envelope_dict(b"x", record_id="bad", parse_status="nope")
    with pytest.raises(EnvelopeValidationError) as excinfo:
        validate_envelope(doc)
    assert len(excinfo.value.errors) >= 2


def test_decode_payload_refuses_object_ref() -> None:
    doc = make_envelope_dict(
        b"x", payload_encoding="object_ref", payload="objects/some-key.zip"
    )
    envelope = validate_envelope(doc)
    with pytest.raises(PayloadDecodeError):
        envelope.decode_payload()


def test_parse_envelope_accepts_bytes_value() -> None:
    payload = b"\x01\x02"
    raw = json.dumps(make_envelope_dict(payload)).encode()
    assert parse_envelope(raw).decode_payload() == payload
