"""Encryption at rest for configuration secrets (handoff 0046).

WHAT THIS IS FOR
----------------
The OIDC client secret is a credential the agency's identity provider issued
to Headway. It has to be *usable* (the API presents it at the token endpoint
on every sign-in), so it cannot be hashed like a password or an API key —
Headway must be able to get the original value back. That leaves encryption,
and encryption is only worth the name if the key lives somewhere the
ciphertext does not.

So the shape here is deliberately the SAME as the Ed25519 signing key
(``signing.py``, migration 0030): the key is 32 bytes sourced from the
environment or a 0600 secret file, generated at first use if absent, and it
is never in the database and never in this repository. A key stored beside
the ciphertext it protects is not encryption, it is filing.

THE ALGORITHM
-------------
AES-256-GCM (``cryptography``, pyca — "Apache-2.0 OR BSD-3-Clause", ADR-0001
tier 2 permissive, already a dependency for Ed25519). GCM is authenticated:
it detects a tampered ciphertext instead of returning plausible garbage, so
a secret altered in the database fails loudly rather than causing a sign-in
failure nobody can explain.

Every encryption uses a fresh 12-byte random nonce, stored with the
ciphertext. Nonce reuse is the one way to break GCM badly, and generating it
per call from ``os.urandom`` makes reuse impossible in practice.

Stored form — a self-describing string, so a future key rotation or
algorithm change can be told apart from today's values without guessing::

    v1.aesgcm.<urlsafe-base64(nonce || ciphertext || tag)>

ASSOCIATED DATA binds a ciphertext to WHAT it is. The OIDC client secret is
encrypted with associated data ``"oidc.client_secret"``, so a ciphertext
lifted out of that column and pasted into a different one fails to decrypt
rather than silently becoming a different secret.

NEVER LOGGED, NEVER SERVED
--------------------------
No function here puts plaintext, ciphertext, or the key into an exception
message. The refusal messages name what to do, never what was found. The
API never serves a stored secret back to any caller — a written secret is
show-once and the admin screen reports only whether one is set.

REFUSAL, NOT DEGRADATION
------------------------
With no key configured, ``encrypt`` raises and the calling endpoint answers
a plain-language 503. Headway never stores a secret in the clear because
encryption was unavailable — that is exactly the "fail loudly" guardrail
applied to configuration.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENV_KEY = "HEADWAY_SECRET_ENCRYPTION_KEY"
ENV_KEY_FILE = "HEADWAY_SECRET_ENCRYPTION_KEY_FILE"

#: AES-256 -> a 32-byte key -> 64 hexadecimal characters.
_KEY_HEX_LENGTH = 64
_NONCE_BYTES = 12

_FORMAT_PREFIX = "v1.aesgcm."

#: Associated data for the OIDC client secret — binds the ciphertext to the
#: column it belongs in.
AD_OIDC_CLIENT_SECRET = b"oidc.client_secret"


class SecretKeyUnavailable(RuntimeError):
    """No at-rest encryption key is configured (or it is malformed).

    Callers must refuse the action in plain language. A secret is never
    stored unencrypted because the key was missing.
    """


class SecretDecryptionFailed(RuntimeError):
    """A stored secret could not be decrypted.

    Either the at-rest key changed (rotated, or a different key file is
    mounted) or the stored value was altered. Both are loud: the caller
    reports that the secret must be re-entered, and NEVER silently proceeds
    with an empty or partial credential.
    """


def _key_from_hex(key_hex: str, source: str) -> bytes:
    key_hex = key_hex.strip()
    if len(key_hex) != _KEY_HEX_LENGTH:
        raise SecretKeyUnavailable(
            f"The at-rest encryption key in {source} must be exactly "
            f"{_KEY_HEX_LENGTH} hexadecimal characters (a 32-byte AES-256 "
            f"key, e.g. from `openssl rand -hex 32`); found {len(key_hex)} "
            f"characters. The key itself is never logged."
        )
    try:
        return bytes.fromhex(key_hex)
    except ValueError as exc:
        raise SecretKeyUnavailable(
            f"The at-rest encryption key in {source} is not valid "
            f"hexadecimal. Generate one with `openssl rand -hex 32`. The key "
            f"itself is never logged."
        ) from exc


def load_key(environ=os.environ) -> bytes:
    """Load (or first-use-generate) the at-rest encryption key.

    Precedence, highest first — the same two sources, in the same order, as
    the Ed25519 signing key, so an operator learns one pattern:

    1. ``HEADWAY_SECRET_ENCRYPTION_KEY`` — 64 hex characters in the
       environment (the Docker Compose path, written by the installer into
       ``deploy/compose/.env`` beside HEADWAY_SESSION_SECRET);
    2. ``HEADWAY_SECRET_ENCRYPTION_KEY_FILE`` — a path holding those 64 hex
       characters, GENERATED at first use (``os.urandom(32)``, mode 0600) if
       it does not exist.

    Neither set -> ``SecretKeyUnavailable``, and the caller refuses.
    """
    key_hex = environ.get(ENV_KEY, "").strip()
    if key_hex:
        return _key_from_hex(key_hex, f"the {ENV_KEY} environment variable")
    key_file = environ.get(ENV_KEY_FILE, "").strip()
    if not key_file:
        raise SecretKeyUnavailable(
            f"Headway has nowhere safe to keep this secret, so it refuses to "
            f"keep it at all. Set {ENV_KEY} (64 hex characters, e.g. "
            f"`openssl rand -hex 32` — the installer writes this into "
            f"deploy/compose/.env) or {ENV_KEY_FILE} (a secret-file path, "
            f"generated on first use if absent), then try again. The key "
            f"lives only in the environment or that file — never in the "
            f"database and never in the Headway repository."
        )
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="ascii") as fh:
            return _key_from_hex(fh.read(), f"the key file {key_file!r}")
    key = os.urandom(32)
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(key.hex() + "\n")
    return key


def encrypt(plaintext: str, *, associated_data: bytes, key: bytes | None = None) -> str:
    """Encrypt ``plaintext`` for storage. Returns the ``v1.aesgcm.…`` string.

    ``associated_data`` binds the ciphertext to its purpose (see the module
    docstring). Raises ``SecretKeyUnavailable`` when no key is configured —
    the caller must refuse rather than store anything.
    """
    if key is None:
        key = load_key()
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), associated_data)
    blob = base64.urlsafe_b64encode(nonce + sealed).decode("ascii")
    return _FORMAT_PREFIX + blob


def decrypt(stored: str, *, associated_data: bytes, key: bytes | None = None) -> str:
    """Decrypt a stored value. Raises ``SecretDecryptionFailed`` loudly.

    A wrong key and a tampered ciphertext are indistinguishable here by
    design (that is what an authenticated cipher gives you); the refusal
    message covers both honestly rather than guessing which happened.
    """
    if key is None:
        key = load_key()
    if not stored.startswith(_FORMAT_PREFIX):
        raise SecretDecryptionFailed(
            "This stored secret is not in a format this version of Headway "
            "can read. Please enter it again on the configuration screen."
        )
    try:
        raw = base64.urlsafe_b64decode(stored[len(_FORMAT_PREFIX):].encode("ascii"))
    except Exception as exc:  # malformed base64 — never echo the value
        raise SecretDecryptionFailed(
            "This stored secret is damaged and cannot be read. Please enter "
            "it again on the configuration screen."
        ) from exc
    if len(raw) <= _NONCE_BYTES:
        raise SecretDecryptionFailed(
            "This stored secret is damaged and cannot be read. Please enter "
            "it again on the configuration screen."
        )
    nonce, sealed = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, sealed, associated_data).decode("utf-8")
    except (InvalidTag, ValueError) as exc:
        raise SecretDecryptionFailed(
            "Headway could not decrypt a stored secret. Either the "
            "installation's encryption key has changed since it was saved, "
            "or the stored value was altered. Please enter the secret again "
            "on the configuration screen. Nothing was assumed or guessed."
        ) from exc


def key_available(environ=os.environ) -> bool:
    """Is an at-rest key configured? Used to tell an admin BEFORE they type a
    secret that Headway has nowhere to put it — a 503 after the fact is a
    worse experience than a warning before."""
    try:
        load_key(environ)
    except SecretKeyUnavailable:
        return False
    return True


def get_key(app) -> bytes:
    """The app-cached at-rest key (loaded at first use, like the signer).
    Tests inject ``app.state.secret_key`` directly."""
    key = getattr(app.state, "secret_key", None)
    if key is None:
        key = load_key()
        app.state.secret_key = key
    return key
