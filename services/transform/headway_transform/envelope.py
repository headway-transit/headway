"""Parse and validate raw-record envelopes (contracts/raw-record-envelope.v0.schema.json).

The schema file itself is the contract (ADR-0006): it is loaded from disk at
import time and validated with jsonschema, so this module can never drift
from the checked-in contract without failing loudly.

An invalid envelope raises EnvelopeValidationError — a typed error the
consumer catches to quarantine the message as a dq.issues row. It is never
silently dropped.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from pathlib import Path

import jsonschema

# Resolve the contract file relative to the repo root
# (services/transform/headway_transform/envelope.py -> repo root is parents[3]).
# HEADWAY_CONTRACTS_DIR overrides for deployments where the package is
# installed away from the repo checkout.
_DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
_CONTRACTS_DIR = Path(os.environ.get("HEADWAY_CONTRACTS_DIR", _DEFAULT_CONTRACTS_DIR))
_SCHEMA_PATH = _CONTRACTS_DIR / "raw-record-envelope.v0.schema.json"

with open(_SCHEMA_PATH, encoding="utf-8") as _f:
    ENVELOPE_SCHEMA: dict = json.load(_f)

_VALIDATOR = jsonschema.Draft202012Validator(ENVELOPE_SCHEMA)


class EnvelopeValidationError(Exception):
    """Raised when a message is not a valid raw-record envelope v0.

    Carries every schema violation (not just the first) so the resulting
    dq.issues row describes the whole failure.
    """

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class PayloadDecodeError(Exception):
    """Raised when an envelope's payload cannot be decoded as declared."""


@dataclass(frozen=True)
class Envelope:
    """A validated raw-record envelope v0 (field semantics per the schema)."""

    envelope_version: int
    record_id: str
    source: str
    connector: str
    connector_version: str
    fetched_at: str
    content_type: str
    payload_encoding: str  # 'base64' | 'object_ref'
    payload: str
    parse_status: str  # 'ok' | 'malformed'
    parse_error: str | None = None
    agency_id: str | None = None
    feed_url: str | None = None

    def decode_payload(self) -> bytes:
        """Return the raw payload bytes for a base64-encoded envelope.

        object_ref payloads live in the object store; fetching them is the
        caller's job (an object fetcher), so calling this on an object_ref
        envelope is a programming error surfaced loudly.
        """
        if self.payload_encoding != "base64":
            raise PayloadDecodeError(
                f"payload_encoding is {self.payload_encoding!r}; "
                "decode_payload() only applies to base64 envelopes"
            )
        try:
            return base64.b64decode(self.payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PayloadDecodeError(f"payload is not valid base64: {exc}") from exc


def validate_envelope(document: object) -> Envelope:
    """Validate a decoded JSON document against the envelope contract.

    Returns a typed Envelope on success; raises EnvelopeValidationError with
    all violations on failure. Never returns a partial/defaulted envelope.
    """
    errors = sorted(_VALIDATOR.iter_errors(document), key=lambda e: list(e.path))
    if errors:
        details = [
            f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
            for err in errors
        ]
        raise EnvelopeValidationError(
            f"envelope failed contract validation ({len(details)} violation(s)): "
            + "; ".join(details),
            errors=details,
        )
    assert isinstance(document, dict)  # guaranteed by schema "type": "object"
    return Envelope(
        envelope_version=document["envelope_version"],
        record_id=document["record_id"],
        source=document["source"],
        connector=document["connector"],
        connector_version=document["connector_version"],
        fetched_at=document["fetched_at"],
        content_type=document["content_type"],
        payload_encoding=document["payload_encoding"],
        payload=document["payload"],
        parse_status=document["parse_status"],
        parse_error=document.get("parse_error"),
        agency_id=document.get("agency_id"),
        feed_url=document.get("feed_url"),
    )


def parse_envelope(raw: bytes | str) -> Envelope:
    """Parse a Kafka message value (JSON bytes) into a validated Envelope.

    Malformed JSON is an EnvelopeValidationError too: the consumer must
    quarantine it, not crash or drop it.
    """
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EnvelopeValidationError(
            f"message value is not valid JSON: {exc}"
        ) from exc
    return validate_envelope(document)
