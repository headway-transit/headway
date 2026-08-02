"""ID-token validation and JWKS rotation (handoff 0046, design point 5).

These run against the REAL verifier with REAL RSA keys — the fake provider
in conftest mints genuinely signed RS256 tokens — so a test that passes here
is a statement about the cryptography, not about a stub agreeing with itself.

Every check in this file is one that has been the root cause of a real
relying-party compromise somewhere. The positive case is one test; the rest
are the ways a token gets refused.
"""

from __future__ import annotations

import base64
import datetime as dt
import json

import jwt as pyjwt
import pytest

from conftest import UTC, _rsa_key
from headway_api import oidc


@pytest.fixture
def config(fake_idp):
    return oidc.ProviderConfig(
        discovery_url=fake_idp.discovery_url,
        client_id=fake_idp.client_id,
        client_secret=fake_idp.client_secret,
        redirect_uri="https://headway.example.gov/auth/callback",
        is_enabled=True,
    )


def _validate(token, config, metadata, *, nonce="the-nonce", now=None):
    return oidc.validate_id_token(
        token, config, metadata, expected_nonce=nonce, now=now
    )


# ---------------------------------------------------------------------------
# The one that must pass
# ---------------------------------------------------------------------------


def test_a_genuine_token_validates(fake_idp, config, oidc_metadata):
    token = fake_idp.id_token(nonce="the-nonce", groups=["stewards", "finance"])
    claims = _validate(token, config, oidc_metadata)
    assert claims.issuer == fake_idp.issuer
    assert claims.subject == "idp-subject-0001"
    assert claims.username == "sso.steward"
    assert claims.groups == ("stewards", "finance")


# ---------------------------------------------------------------------------
# Signature and algorithm
# ---------------------------------------------------------------------------


def test_a_token_signed_by_a_key_the_provider_does_not_publish_is_refused(
    fake_idp, config, oidc_metadata
):
    """The core claim of the whole flow: only the provider can mint a session."""
    forged = pyjwt.encode(
        {
            "iss": fake_idp.issuer,
            "sub": "attacker",
            "aud": fake_idp.client_id,
            "exp": int((dt.datetime.now(UTC) + dt.timedelta(minutes=5)).timestamp()),
            "iat": int(dt.datetime.now(UTC).timestamp()),
            "nonce": "the-nonce",
            "preferred_username": "attacker",
            "groups": ["stewards"],
        },
        _rsa_key("an-attackers-own-key"),
        algorithm="RS256",
        headers={"kid": fake_idp.signing_kid},  # claims to be the real key
    )
    with pytest.raises(oidc.OidcError) as exc:
        _validate(forged, config, oidc_metadata)
    assert "signature did not verify" in exc.value.reason


def test_alg_none_is_refused_before_a_key_is_even_chosen(fake_idp, config, oidc_metadata):
    """The oldest JWT forgery there is. It must not survive the header check."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({
            "iss": fake_idp.issuer, "sub": "attacker",
            "aud": fake_idp.client_id, "nonce": "the-nonce",
            "exp": 99999999999, "iat": 1,
        }).encode()
    ).decode().rstrip("=")
    with pytest.raises(oidc.OidcError) as exc:
        _validate(f"{header}.{payload}.", config, oidc_metadata)
    assert "'none' is not accepted" in exc.value.reason
    assert "asymmetric algorithms only" in exc.value.reason


def test_hs256_signed_with_the_public_key_is_refused(fake_idp, config, oidc_metadata):
    """Algorithm confusion: the provider's PUBLIC key, which anybody can
    fetch, used as an HMAC secret. Refusing every symmetric algorithm at the
    header is the only reliable defence."""
    from cryptography.hazmat.primitives import serialization

    public_pem = _rsa_key(fake_idp.signing_kid).public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # PyJWT refuses to ENCODE this (it knows the trick), so the forgery is
    # assembled by hand — exactly as an attacker would, since they are not
    # using our library either.
    import hashlib
    import hmac

    def b64u(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    header = b64u(json.dumps(
        {"alg": "HS256", "typ": "JWT", "kid": fake_idp.signing_kid}
    ).encode())
    payload = b64u(json.dumps({
        "iss": fake_idp.issuer, "sub": "attacker",
        "aud": fake_idp.client_id, "nonce": "the-nonce",
        "exp": int((dt.datetime.now(UTC) + dt.timedelta(minutes=5)).timestamp()),
        "iat": int(dt.datetime.now(UTC).timestamp()),
        "preferred_username": "attacker",
    }).encode())
    signature = b64u(hmac.new(
        public_pem, f"{header}.{payload}".encode("ascii"), hashlib.sha256
    ).digest())
    forged = f"{header}.{payload}.{signature}"
    with pytest.raises(oidc.OidcError) as exc:
        _validate(forged, config, oidc_metadata)
    assert "'HS256' is not accepted" in exc.value.reason


ALLOWED = oidc.ALLOWED_ID_TOKEN_ALGORITHMS


def test_the_algorithm_allow_list_holds_no_symmetric_algorithm():
    assert not any(a.startswith("HS") for a in ALLOWED)
    assert "none" not in ALLOWED
    assert "RS256" in ALLOWED


# ---------------------------------------------------------------------------
# iss / aud
# ---------------------------------------------------------------------------


def test_a_wrong_issuer_is_refused(fake_idp, config, oidc_metadata):
    token = fake_idp.id_token(nonce="the-nonce", iss="https://evil.example.com")
    with pytest.raises(oidc.OidcError) as exc:
        _validate(token, config, oidc_metadata)
    assert "issuer does not match" in exc.value.reason


def test_a_wrong_audience_is_refused(fake_idp, config, oidc_metadata):
    """A token minted for a DIFFERENT application at the same provider — the
    classic way one tenant's app is used to sign into another's."""
    token = fake_idp.id_token(nonce="the-nonce", aud="some-other-application")
    with pytest.raises(oidc.OidcError) as exc:
        _validate(token, config, oidc_metadata)
    assert "audience is not this Headway client" in exc.value.reason


def test_multiple_audiences_require_azp_to_name_this_client(
    fake_idp, config, oidc_metadata
):
    bad = fake_idp.id_token(
        nonce="the-nonce",
        aud=[fake_idp.client_id, "another-app"],
        azp="another-app",
    )
    with pytest.raises(oidc.OidcError) as exc:
        _validate(bad, config, oidc_metadata)
    assert "authorized party is not this Headway client" in exc.value.reason

    good = fake_idp.id_token(
        nonce="the-nonce",
        aud=[fake_idp.client_id, "another-app"],
        azp=fake_idp.client_id,
    )
    assert _validate(good, config, oidc_metadata).subject == "idp-subject-0001"


# ---------------------------------------------------------------------------
# exp / iat and the STATED clock skew
# ---------------------------------------------------------------------------


def test_an_expired_token_is_refused(fake_idp, config, oidc_metadata):
    now = dt.datetime.now(UTC)
    token = fake_idp.id_token(
        nonce="the-nonce",
        exp=int((now - dt.timedelta(minutes=10)).timestamp()),
        iat=int((now - dt.timedelta(minutes=15)).timestamp()),
    )
    with pytest.raises(oidc.OidcError) as exc:
        _validate(token, config, oidc_metadata)
    assert "expired" in exc.value.reason
    assert "skew tolerance 120s" in exc.value.reason


def test_a_token_just_inside_the_skew_tolerance_is_accepted(
    fake_idp, config, oidc_metadata
):
    """The tolerance is a stated number, not a library default nobody can
    name: 120 seconds by default, configurable per provider."""
    now = dt.datetime.now(UTC)
    token = fake_idp.id_token(
        nonce="the-nonce",
        exp=int((now - dt.timedelta(seconds=60)).timestamp()),
        iat=int((now - dt.timedelta(minutes=5)).timestamp()),
    )
    assert _validate(token, config, oidc_metadata).subject == "idp-subject-0001"


def test_the_skew_tolerance_is_configurable_and_zero_means_zero(
    fake_idp, config, oidc_metadata
):
    strict = oidc.ProviderConfig(
        discovery_url=config.discovery_url,
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri=config.redirect_uri,
        clock_skew_seconds=0,
    )
    now = dt.datetime.now(UTC)
    token = fake_idp.id_token(
        nonce="the-nonce",
        exp=int((now - dt.timedelta(seconds=1)).timestamp()),
        iat=int((now - dt.timedelta(minutes=5)).timestamp()),
    )
    with pytest.raises(oidc.OidcError):
        _validate(token, strict, oidc_metadata)


def test_a_token_issued_far_in_the_future_is_refused(fake_idp, config, oidc_metadata):
    """Skew works in both directions, and a token issued 'later' than the
    tolerance is not a clock problem."""
    now = dt.datetime.now(UTC)
    token = fake_idp.id_token(
        nonce="the-nonce",
        iat=int((now + dt.timedelta(minutes=30)).timestamp()),
        exp=int((now + dt.timedelta(minutes=40)).timestamp()),
    )
    with pytest.raises(oidc.OidcError) as exc:
        _validate(token, config, oidc_metadata, now=now)
    assert "issued in the future" in exc.value.reason


# ---------------------------------------------------------------------------
# nonce and sub
# ---------------------------------------------------------------------------


def test_a_replayed_token_from_another_sign_in_is_refused(
    fake_idp, config, oidc_metadata
):
    """The nonce binds a token to THIS sign-in. Without it, an ID token
    captured from one session is a valid credential for another."""
    token = fake_idp.id_token(nonce="a-different-sign-ins-nonce")
    with pytest.raises(oidc.OidcError) as exc:
        _validate(token, config, oidc_metadata, nonce="the-nonce")
    assert "nonce did not match" in exc.value.reason


def test_a_token_with_no_nonce_is_refused(fake_idp, config, oidc_metadata):
    from conftest import ABSENT

    token = fake_idp.id_token(nonce=ABSENT)
    with pytest.raises(oidc.OidcError) as exc:
        _validate(token, config, oidc_metadata)
    assert "nonce did not match" in exc.value.reason


def test_a_token_with_no_subject_is_refused(fake_idp, config, oidc_metadata):
    """`sub` is what makes a federated signature resolvable years later. A
    token without one cannot produce an accountable session."""
    from conftest import ABSENT

    token = fake_idp.id_token(nonce="the-nonce", sub=ABSENT)
    with pytest.raises(oidc.OidcError) as exc:
        _validate(token, config, oidc_metadata)
    assert "sub" in exc.value.reason


def test_a_token_with_no_username_claim_is_refused(fake_idp, config, oidc_metadata):
    from conftest import ABSENT

    token = fake_idp.id_token(
        nonce="the-nonce", username=ABSENT, preferred_username=ABSENT,
        email=ABSENT,
    )
    with pytest.raises(oidc.OidcError) as exc:
        _validate(token, config, oidc_metadata)
    assert "carries no username" in exc.value.reason


def test_the_subject_is_never_used_as_a_username(fake_idp, config, oidc_metadata):
    """An Entra ID subject is an opaque GUID. Nobody can recognise
    themselves in an audit trail full of GUIDs, so the subject is recorded
    ALONGSIDE a username and never in place of one."""
    from conftest import ABSENT

    token = fake_idp.id_token(
        nonce="the-nonce", sub="00000000-1111-2222-3333-444444444444",
        username=ABSENT, preferred_username=ABSENT, email="sso.official@example.gov",
    )
    claims = _validate(token, config, oidc_metadata)
    assert claims.username == "sso.official@example.gov"
    assert claims.subject == "00000000-1111-2222-3333-444444444444"


# ---------------------------------------------------------------------------
# JWKS key rotation — the failure that looks like "SSO is down"
# ---------------------------------------------------------------------------


def test_a_rotated_signing_key_is_picked_up_without_a_restart(
    fake_idp, config, oidc_metadata
):
    """The whole reason keys are cached WITH REFRESH rather than pinned. The
    provider rotates on its own schedule and does not announce it."""
    assert _validate(
        fake_idp.id_token(nonce="the-nonce"), config, oidc_metadata
    ).subject
    fetches_before = fake_idp.jwks_fetches

    fake_idp.rotate_signing_key("key-2026-b")
    claims = _validate(fake_idp.id_token(nonce="the-nonce"), config, oidc_metadata)

    assert claims.subject == "idp-subject-0001"
    assert fake_idp.jwks_fetches > fetches_before, (
        "the unknown kid must trigger exactly one refetch — a pinned key "
        "would have failed here"
    )


def test_the_jwks_is_cached_and_not_refetched_for_every_sign_in(
    fake_idp, config, oidc_metadata
):
    for _ in range(5):
        _validate(fake_idp.id_token(nonce="the-nonce"), config, oidc_metadata)
    assert fake_idp.jwks_fetches == 1


def test_an_unknown_kid_cannot_be_used_to_hammer_the_provider(
    fake_idp, config, oidc_metadata
):
    """Refresh-on-miss is rate limited, or a stream of invented `kid` values
    turns Headway into an amplifier pointed at the provider's JWKS."""
    _validate(fake_idp.id_token(nonce="the-nonce"), config, oidc_metadata)
    baseline = fake_idp.jwks_fetches

    forged = pyjwt.encode(
        {
            "iss": fake_idp.issuer, "sub": "x", "aud": fake_idp.client_id,
            "nonce": "the-nonce", "exp": 99999999999, "iat": 1,
        },
        _rsa_key("attacker"),
        algorithm="RS256",
        headers={"kid": "invented-kid"},
    )
    for _ in range(20):
        with pytest.raises(oidc.OidcError):
            _validate(forged, config, oidc_metadata)
    assert fake_idp.jwks_fetches - baseline == 1


def test_a_key_the_provider_signs_with_but_does_not_publish_is_refused(
    fake_idp, config, oidc_metadata
):
    """Rotation handled is not rotation trusted: a kid that is genuinely
    absent from the published JWKS stays refused."""
    fake_idp.rotate_signing_key("secret-unpublished-key", publish=False)
    with pytest.raises(oidc.OidcError) as exc:
        _validate(fake_idp.id_token(nonce="the-nonce"), config, oidc_metadata)
    assert "unknown key id" in exc.value.reason


def test_a_symmetric_key_in_the_jwks_is_never_selected(
    fake_idp, config, oidc_metadata, monkeypatch
):
    """Defence in depth behind the algorithm allow-list: even if a provider
    published an `oct` key, it can never be chosen."""
    keys = fake_idp.jwks()["keys"] + [
        {"kty": "oct", "use": "sig", "alg": "HS256", "kid": "sym", "k": "AAAA"}
    ]
    assert oidc._select_key(keys, "sym", "HS256") is None


# ---------------------------------------------------------------------------
# Discovery: TLS, the issuer guard, and PKCE support
# ---------------------------------------------------------------------------


def test_http_discovery_urls_are_refused_except_on_loopback():
    with pytest.raises(oidc.OidcConfigurationError) as exc:
        oidc.validate_discovery_url(
            "http://idp.example.gov/.well-known/openid-configuration"
        )
    assert "refuses to fetch identity-provider configuration over an" in exc.value.public_message
    # Loopback is allowed so a developer can run a Keycloak on their machine.
    oidc.validate_discovery_url(
        "http://localhost:8080/realms/x/.well-known/openid-configuration"
    )
    oidc.validate_discovery_url(
        "https://login.microsoftonline.com/tenant-id/v2.0/.well-known/openid-configuration"
    )


def test_a_discovery_document_naming_a_different_issuer_is_refused(
    fake_idp, config, oidc_metadata, fake_oidc_http
):
    """Issuer confusion. A copy-paste mistake and an impersonation attempt
    are indistinguishable from here, so both are refused."""
    original = fake_idp.discovery

    def lying_discovery():
        document = original()
        document["issuer"] = "https://someone-elses-idp.example.com"
        return document

    fake_idp.discovery = lying_discovery
    with pytest.raises(oidc.OidcConfigurationError) as exc:
        oidc_metadata.discovery(config, force=True)
    assert "belongs to a different identity provider" in exc.value.public_message
    assert "'common' address" in exc.value.public_message


def test_a_provider_without_s256_pkce_is_refused(fake_idp, config, oidc_metadata):
    original = fake_idp.discovery

    def no_pkce():
        document = original()
        document["code_challenge_methods_supported"] = ["plain"]
        return document

    fake_idp.discovery = no_pkce
    with pytest.raises(oidc.OidcConfigurationError) as exc:
        oidc_metadata.discovery(config, force=True)
    assert "does not support PKCE" in exc.value.public_message


def test_a_ca_bundle_path_is_checked_when_it_is_saved(tmp_path):
    """The TLS-inspecting-proxy story fails on the configuration screen, with
    a message that says what to do, rather than at 8am for a member of staff."""
    missing = tmp_path / "not-here.pem"
    with pytest.raises(oidc.OidcConfigurationError) as exc:
        oidc.validate_ca_bundle_path(str(missing))
    assert "There is no file at" in exc.value.public_message
    assert "mounted into that container" in exc.value.public_message

    present = tmp_path / "corp-ca.pem"
    present.write_text("-----BEGIN CERTIFICATE-----\n")
    oidc.validate_ca_bundle_path(str(present))
    oidc.validate_ca_bundle_path(None)


def test_there_is_no_way_to_turn_certificate_verification_off():
    """A grep-shaped assertion, deliberately. The field workaround for a
    certificate error is always to disable verification, so the option must
    not exist to be found."""
    import inspect

    source = inspect.getsource(oidc)
    for forbidden in ("verify=False", "verify = False", "verify=0", "CERT_NONE"):
        assert forbidden not in source, (
            f"{forbidden!r} appears in oidc.py — there must be no way to "
            f"disable TLS verification, not even one a reader could copy"
        )


def test_a_certificate_failure_explains_the_inspecting_proxy():
    class CertError(Exception):
        pass

    message = oidc._network_message(
        "https://idp.example.gov/.well-known/openid-configuration",
        CertError("certificate verify failed: unable to get local issuer certificate"),
    )
    assert "TLS-inspecting proxy" in message
    assert "Certificate authority file" in message
    assert "will not turn certificate checking off" in message


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------


def test_the_authorization_request_uses_code_plus_s256_and_random_values(
    fake_idp, config, oidc_metadata
):
    from urllib.parse import parse_qs, urlparse

    first = oidc.build_authorization_request(config, oidc_metadata)
    second = oidc.build_authorization_request(config, oidc_metadata)
    params = parse_qs(urlparse(first.authorization_url).query)

    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [oidc.code_challenge_for(first.code_verifier)]
    assert params["state"] == [first.state]
    assert params["nonce"] == [first.nonce]
    assert "openid" in params["scope"][0]
    # Never the verifier itself, which is the entire point of PKCE.
    assert first.code_verifier not in first.authorization_url
    # Nothing is derived from a counter or a timestamp.
    assert first.state != second.state
    assert first.nonce != second.nonce
    assert first.code_verifier != second.code_verifier
    assert first.browser_token != second.browser_token
    assert len(first.state) >= 32 and len(first.code_verifier) >= 43


def test_the_browser_token_is_stored_only_as_a_hash(fake_idp, config, oidc_metadata):
    started = oidc.build_authorization_request(config, oidc_metadata)
    assert started.browser_binding == oidc.hash_browser_token(started.browser_token)
    assert started.browser_token not in started.browser_binding


def test_group_claims_are_read_from_lists_and_bare_strings_only():
    assert oidc._groups_from({"groups": ["a", "b"]}, "groups") == ("a", "b")
    # A bare string is ONE group, never split — "Transit Finance" must not
    # become two groups the provider never sent.
    assert oidc._groups_from({"groups": "Transit Finance"}, "groups") == (
        "Transit Finance",
    )
    # Anything else yields nothing, which means no mapping matches, which
    # means refused. Deny-by-default even in the parser.
    assert oidc._groups_from({"groups": {"a": 1}}, "groups") == ()
    assert oidc._groups_from({}, "groups") == ()
    assert oidc._groups_from({"roles": ["a"]}, "groups") == ()
