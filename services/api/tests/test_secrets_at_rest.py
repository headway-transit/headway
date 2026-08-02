"""Encryption at rest for configuration secrets (handoff 0046).

The OIDC client secret has to be usable, so it cannot be hashed. That makes
these the properties worth pinning: it round-trips, a tampered ciphertext is
caught rather than mangled, a ciphertext cannot be moved between columns, the
key never lives beside the ciphertext, and with no key the code REFUSES
rather than falling back to plaintext.
"""

from __future__ import annotations

import base64

import pytest

from headway_api import secrets_at_rest as sar

KEY = bytes.fromhex("11" * 32)
OTHER_KEY = bytes.fromhex("22" * 32)
AD = sar.AD_OIDC_CLIENT_SECRET


def test_round_trip():
    stored = sar.encrypt("provider-issued-secret", associated_data=AD, key=KEY)
    assert sar.decrypt(stored, associated_data=AD, key=KEY) == "provider-issued-secret"


def test_the_plaintext_never_appears_in_the_stored_form():
    stored = sar.encrypt("hunter2-but-longer", associated_data=AD, key=KEY)
    assert "hunter2" not in stored
    assert stored.startswith("v1.aesgcm.")


def test_each_encryption_uses_a_fresh_nonce():
    """Nonce reuse is the one way to break AES-GCM badly. Two encryptions of
    the same value must not produce the same ciphertext."""
    a = sar.encrypt("same", associated_data=AD, key=KEY)
    b = sar.encrypt("same", associated_data=AD, key=KEY)
    assert a != b
    assert sar.decrypt(a, associated_data=AD, key=KEY) == "same"
    assert sar.decrypt(b, associated_data=AD, key=KEY) == "same"


def test_a_tampered_ciphertext_is_caught_loudly():
    """Authenticated encryption, so an altered value fails instead of
    decrypting into plausible garbage that would look like a wrong secret."""
    stored = sar.encrypt("provider-issued-secret", associated_data=AD, key=KEY)
    raw = bytearray(base64.urlsafe_b64decode(stored[len("v1.aesgcm."):]))
    raw[-1] ^= 0x01
    tampered = "v1.aesgcm." + base64.urlsafe_b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(sar.SecretDecryptionFailed) as exc:
        sar.decrypt(tampered, associated_data=AD, key=KEY)
    assert "enter the secret again" in str(exc.value)


def test_the_wrong_key_fails_rather_than_returning_something():
    stored = sar.encrypt("provider-issued-secret", associated_data=AD, key=KEY)
    with pytest.raises(sar.SecretDecryptionFailed):
        sar.decrypt(stored, associated_data=OTHER_KEY, key=OTHER_KEY)


def test_a_ciphertext_cannot_be_moved_to_a_different_column():
    """Associated data binds a ciphertext to WHAT it is, so a value lifted
    out of the client-secret column and pasted elsewhere fails to decrypt
    rather than silently becoming a different secret."""
    stored = sar.encrypt("provider-issued-secret", associated_data=AD, key=KEY)
    with pytest.raises(sar.SecretDecryptionFailed):
        sar.decrypt(stored, associated_data=b"webhook.signing_secret", key=KEY)


def test_malformed_stored_values_fail_without_echoing_the_value():
    for bad in ("", "plaintext-secret", "v1.aesgcm.!!!not-base64!!!", "v1.aesgcm.AAAA"):
        with pytest.raises(sar.SecretDecryptionFailed) as exc:
            sar.decrypt(bad, associated_data=AD, key=KEY)
        assert "plaintext-secret" not in str(exc.value)


def test_no_key_configured_refuses_instead_of_storing_plaintext(monkeypatch):
    """The whole point: with nowhere safe to put it, Headway does not put it
    anywhere. There is no fallback to a plaintext column."""
    monkeypatch.delenv(sar.ENV_KEY, raising=False)
    monkeypatch.delenv(sar.ENV_KEY_FILE, raising=False)
    with pytest.raises(sar.SecretKeyUnavailable) as exc:
        sar.encrypt("provider-issued-secret", associated_data=AD)
    message = str(exc.value)
    assert "nowhere safe to keep this secret" in message
    assert "HEADWAY_SECRET_ENCRYPTION_KEY" in message


def test_key_from_environment():
    key = sar.load_key({sar.ENV_KEY: "ab" * 32})
    assert key == bytes.fromhex("ab" * 32)


def test_a_malformed_key_is_refused_and_never_echoed():
    with pytest.raises(sar.SecretKeyUnavailable) as exc:
        sar.load_key({sar.ENV_KEY: "not-hex-at-all"})
    assert "not-hex-at-all" not in str(exc.value)
    assert "hexadecimal" in str(exc.value)

    with pytest.raises(sar.SecretKeyUnavailable) as exc:
        sar.load_key({sar.ENV_KEY: "abcd"})
    assert "64 hexadecimal characters" in str(exc.value)


def test_key_file_is_generated_once_at_0600_and_reused(tmp_path):
    """The 'generated at first use' path for a bare deployment — the same
    shape as the Ed25519 signing key, so an operator learns one pattern."""
    path = tmp_path / "at-rest.key"
    first = sar.load_key({sar.ENV_KEY_FILE: str(path)})
    assert path.exists()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    second = sar.load_key({sar.ENV_KEY_FILE: str(path)})
    assert first == second


def test_environment_variable_wins_over_the_key_file(tmp_path):
    path = tmp_path / "at-rest.key"
    path.write_text("cd" * 32 + "\n")
    key = sar.load_key({sar.ENV_KEY: "ab" * 32, sar.ENV_KEY_FILE: str(path)})
    assert key == bytes.fromhex("ab" * 32)


def test_key_available_reports_honestly(tmp_path):
    assert sar.key_available({}) is False
    assert sar.key_available({sar.ENV_KEY: "ab" * 32}) is True
