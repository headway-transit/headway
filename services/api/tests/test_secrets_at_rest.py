"""Encryption at rest for configuration secrets (handoff 0046).

The OIDC client secret has to be usable, so it cannot be hashed. That makes
these the properties worth pinning: it round-trips, a tampered ciphertext is
caught rather than mangled, a ciphertext cannot be moved between columns, the
key never lives beside the ciphertext, and with no key the code REFUSES
rather than falling back to plaintext.
"""

from __future__ import annotations

import base64
import os
import re

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


def test_an_operator_supplied_key_file_is_read_never_regenerated(tmp_path):
    """The mounted-secret shape: the file was put there by someone else, and
    Headway's job is to read it.

    Overwriting it — or generating a second key beside it — would strand every
    secret already encrypted under the first one, with no way back and no
    error at the moment it happened.
    """
    path = tmp_path / "operator.key"
    path.write_text("ab" * 32 + "\n")
    before = path.read_bytes()

    first = sar.load_key({sar.ENV_KEY_FILE: str(path)})
    second = sar.load_key({sar.ENV_KEY_FILE: str(path)})
    assert first == second == bytes.fromhex("ab" * 32)
    assert path.read_bytes() == before, "the key file must not be rewritten"


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="running as root, which ignores the directory permission this tests",
)
def test_a_key_file_that_cannot_be_created_is_a_refusal_not_an_oserror(tmp_path):
    """A read-only mount is the ORDINARY shape of a Docker or Kubernetes
    secret, not a bug.

    Every caller of this module already handles ``SecretKeyUnavailable`` by
    refusing the action in plain language. A bare ``PermissionError`` escaping
    from here instead becomes a 500 from deep in the crypto layer — the same
    outcome for the user, minus the sentence telling an operator what to do
    about it.
    """
    directory = tmp_path / "read-only-mount"
    directory.mkdir()
    path = directory / "at-rest.key"
    directory.chmod(0o500)
    try:
        with pytest.raises(sar.SecretKeyUnavailable) as exc:
            sar.load_key({sar.ENV_KEY_FILE: str(path)})
    finally:
        # Restored regardless, or pytest cannot clean up its own tmp_path.
        directory.chmod(0o700)

    message = str(exc.value)
    assert "cannot create the at-rest encryption key file" in message
    assert "read-only mount" in message
    assert "openssl rand -hex 32" in message
    # A key WAS generated in memory before the write failed. None of it, and
    # nothing else key-shaped, may appear in a message that will be logged.
    assert re.search(r"[0-9a-fA-F]{32,}", message) is None
    assert not path.exists()


def test_key_available_reports_honestly(tmp_path):
    assert sar.key_available({}) is False
    assert sar.key_available({sar.ENV_KEY: "ab" * 32}) is True


def test_key_available_never_creates_the_key_file_it_reports_on(tmp_path):
    """A GET on the admin screen asks this question. A read that MINTS a
    persistent encryption key as a side effect is a read that changed the
    installation — and the key it minted would then be the one every secret in
    the database is encrypted under, created by somebody loading a page.

    Worse, on a deployment that generates into an ephemeral container path,
    the key created by rendering a screen is gone at the next restart, taking
    the stored secret with it.
    """
    path = tmp_path / "not-generated-yet.key"
    assert sar.key_available({sar.ENV_KEY_FILE: str(path)}) is True
    assert not path.exists(), (
        "asking whether a key is available must never create one"
    )
    # Asked twice, still nothing — no "first call is free" loophole either.
    assert sar.key_available({sar.ENV_KEY_FILE: str(path)}) is True
    assert not path.exists()


def test_key_available_answers_false_rather_than_raising_on_a_broken_setup(
    tmp_path,
):
    """This function exists to render the "no secret storage" banner. A
    configuration so broken that it throws must still produce that banner, not
    a 500 on the screen that was going to explain the problem."""
    # A directory that is not there: the key could not be generated at first
    # use either, so "yes, it will work" would be a lie told one screen early.
    assert sar.key_available(
        {sar.ENV_KEY_FILE: str(tmp_path / "no-such-directory" / "at-rest.key")}
    ) is False

    # A file that is there and is not a key.
    malformed = tmp_path / "malformed.key"
    malformed.write_text("this is not a 64-character hexadecimal string")
    assert sar.key_available({sar.ENV_KEY_FILE: str(malformed)}) is False

    # And the same for a malformed value in the environment variable.
    assert sar.key_available({sar.ENV_KEY: "not-hex-at-all"}) is False
    assert sar.key_available({sar.ENV_KEY: "abcd"}) is False
