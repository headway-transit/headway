"""The native OIDC relying party (ADR-0011, handoff 0046).

Headway talks to the agency's identity provider directly — Entra ID, Google,
Okta, or a Keycloak running the optional profile — instead of putting a
second JVM beside Kafka on a small agency's single box. That means this
module owns security-critical code, so every decision in it is written down
next to the code that makes it.

THE FLOW: AUTHORIZATION CODE + PKCE. NOTHING ELSE.
--------------------------------------------------
The implicit flow is not implemented and cannot be selected. PKCE (RFC 7636)
is always applied, with S256, including for confidential clients: the code
verifier never leaves the API, so an authorization code intercepted in the
browser redirect is useless to whoever intercepted it.

WHAT IS CHECKED ON THE WAY BACK IN
----------------------------------
Each of these has been the root cause of a real-world relying-party
compromise, which is why each is explicit here rather than left to a
library's defaults:

* **Signature, against the provider's JWKS.** Fetched over TLS, cached, and
  refreshed on an unrecognized ``kid`` — see the rotation note below.
* **Algorithm allow-list.** Only asymmetric algorithms are accepted. ``none``
  is refused, and so is every HMAC algorithm: an ``HS256`` token verified
  with a *public* key as the HMAC secret is the classic algorithm-confusion
  forgery, and the only reliable defence is to never let a symmetric
  algorithm reach the verifier.
* **``iss``** must equal the issuer in the discovery document, exactly.
* **``aud``** must contain the configured client id; when several audiences
  are present, ``azp`` must be this client (OIDC Core 3.1.3.7).
* **``exp`` / ``iat``** with a STATED, configurable clock-skew tolerance
  (default 120 seconds). ``iat`` far in the future is refused too — skew
  works in both directions and a token issued "later" than the tolerance is
  not a clock problem.
* **``nonce``** must equal the one this API generated for this sign-in.
  Without it, an ID token minted for another sign-in can be replayed here.
* **``sub``** must be present. It is the only identifier a provider promises
  never to reuse, and it is what makes a federated signature resolvable
  years later.

JWKS KEY ROTATION
-----------------
Providers rotate signing keys on their own schedule and do not announce it.
A relying party that pins one key works until the morning it does not, and
the failure looks like "SSO is down" with nothing in the logs to explain it.
So keys are CACHED WITH REFRESH: the JWKS is re-fetched when its TTL expires,
and immediately when a token arrives with a ``kid`` the cache has not seen —
which is exactly what a rotation looks like from here. That refresh-on-miss
is rate limited (``_MIN_REFRESH_INTERVAL``), because otherwise a stream of
tokens carrying invented ``kid`` values turns into a stream of requests at
the provider's JWKS endpoint, with Headway as the amplifier.

TLS AND THE INSPECTING PROXY
----------------------------
Discovery and JWKS are fetched over TLS, and there is NO option anywhere to
turn verification off. That is not an oversight to be fixed by a flag: this
integration is the one that fails in the field, and the field workaround for
a certificate error is always to disable verification.

Agencies routinely terminate and re-sign TLS at the perimeter, so those
documents arrive signed by a corporate CA no container trust store has heard
of. The supported answer is ``ca_bundle_path``: a PEM bundle the admin points
at, checked for existence and readability when it is saved, so the failure
happens on the configuration screen with a message that says what to do —
not at 8am on a Monday for a member of staff who only wanted to sign in.

FAILURE MESSAGES
----------------
Every sign-in failure returns ONE generic message. It never says whether an
account exists, whether the account was mapped, or which check failed. The
specific reason goes to the audit trail, where an administrator can read it
and an attacker cannot. This matches the existing local-login behaviour
exactly (``auth.py``).
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import jwt
from jwt import PyJWK

#: The ONLY algorithms an ID token may be signed with. Asymmetric only —
#: see the module docstring on algorithm confusion. ``none`` is absent, and
#: so is every ``HS*``.
ALLOWED_ID_TOKEN_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
)

#: Scopes requested. ``openid`` is mandatory; ``profile`` and ``email`` carry
#: the username claim. Group claims come from the provider's own
#: configuration (Entra ID group claims, Keycloak client scopes) rather than
#: a scope Headway can name portably.
DEFAULT_SCOPES = ("openid", "profile", "email")

#: How long a started sign-in may take before its state row expires. Long
#: enough for a password + MFA prompt, short enough that an abandoned
#: authorization request is not a lingering credential.
LOGIN_STATE_TTL_SECONDS = 10 * 60

#: Discovery/JWKS cache lifetime.
_DISCOVERY_TTL_SECONDS = 3600.0
_JWKS_TTL_SECONDS = 3600.0

#: Floor between JWKS refetches triggered by an unrecognized ``kid``. Without
#: it, forged ``kid`` values turn this API into an amplifier pointed at the
#: provider.
_MIN_REFRESH_INTERVAL = 30.0

#: Response/network budget. A provider that hangs must not hang Headway.
_HTTP_TIMEOUT_SECONDS = 10.0

#: A discovery document must be an HTTPS URL. The single exception is
#: loopback, so a developer can point at a Keycloak on their own machine —
#: it is not reachable from anywhere else, so it leaks nothing.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

#: The ONE message every failed federated sign-in returns. It never
#: distinguishes "no such user", "not mapped", "expired token" or "bad
#: signature" — the audit trail keeps the difference.
GENERIC_LOGIN_FAILURE = (
    "Headway could not sign you in with single sign-on. If you have just "
    "been given access, it may not have taken effect yet. Please try again, "
    "and if it keeps failing ask your Headway administrator to check the "
    "single sign-on configuration — the reason for this failure is recorded "
    "in Headway's audit trail."
)


class OidcError(Exception):
    """A sign-in could not be completed.

    ``reason`` is the specific, technical cause and goes ONLY to the audit
    trail. ``public_message`` is what the caller sees, and defaults to the
    single generic refusal.
    """

    def __init__(self, reason: str, *, public_message: str = GENERIC_LOGIN_FAILURE,
                 detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.public_message = public_message
        self.detail = detail or {}


class OidcConfigurationError(OidcError):
    """The provider configuration itself is wrong or unusable.

    Raised by the admin-facing test action, where the SPECIFIC message is the
    point: an administrator configuring OIDC needs to know exactly what
    failed. This class is never used on the sign-in path, where messages stay
    generic.
    """

    def __init__(self, message: str, *, detail: Optional[dict] = None):
        super().__init__(message, public_message=message, detail=detail)


# ---------------------------------------------------------------------------
# The HTTP seam
# ---------------------------------------------------------------------------


class HttpxOidcClient:
    """The real HTTP client: httpx, TLS verified, no redirects followed on
    the token endpoint, bounded timeout.

    ``ca_bundle_path`` is handed straight to httpx's ``verify``, which
    accepts a PEM bundle path. No code path in this module ever disables
    certificate verification — there is deliberately no setting, no flag and
    no environment variable that can, so there is nothing for a frustrated
    operator to find at 8am. A test greps this module to keep it that way.
    """

    def __init__(self, ca_bundle_path: str | None = None):
        self.ca_bundle_path = ca_bundle_path

    def _client(self):
        import httpx

        verify: Any = True
        if self.ca_bundle_path:
            verify = self.ca_bundle_path
        return httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS, verify=verify,
                            follow_redirects=False)

    def get_json(self, url: str) -> dict:
        import httpx

        try:
            with self._client() as client:
                response = client.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise OidcConfigurationError(_network_message(url, exc)) from exc
        if response.status_code != 200:
            raise OidcConfigurationError(
                f"{url} answered HTTP {response.status_code}. Headway expected "
                f"200 with a JSON document. Check that the address is exactly "
                f"the one your identity provider publishes."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise OidcConfigurationError(
                f"{url} answered something that is not JSON. This is usually "
                f"a sign-in page or an error page from a proxy standing "
                f"between Headway and your identity provider."
            ) from exc

    def post_form(self, url: str, data: dict, *, auth: tuple[str, str] | None = None) -> dict:
        import httpx

        try:
            with self._client() as client:
                response = client.post(
                    url,
                    data=data,
                    auth=auth,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise OidcError(f"token endpoint unreachable: {type(exc).__name__}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise OidcError(
                f"token endpoint returned non-JSON (HTTP {response.status_code})"
            ) from exc
        if response.status_code != 200:
            # The provider's own error CODE is safe to record (it is about
            # the request, not about the user); its description is not
            # echoed to the caller.
            raise OidcError(
                f"token endpoint refused the code exchange: "
                f"HTTP {response.status_code} {body.get('error', 'unknown_error')}"
            )
        return body

    def post_form_probe(self, url: str, data: dict, *,
                        auth: tuple[str, str] | None = None) -> tuple[int, dict]:
        """Like ``post_form`` but returns the status instead of raising.

        Used ONLY by the admin test action, which learns what it needs from
        the provider's error code (see ``probe_client_credentials``).
        """
        import httpx

        try:
            with self._client() as client:
                response = client.post(
                    url, data=data, auth=auth,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise OidcConfigurationError(_network_message(url, exc)) from exc
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}


def _network_message(url: str, exc: Exception) -> str:
    """Plain-language network failure, written for the admin screen.

    A certificate failure gets its own paragraph because it is the single
    most common way this integration fails, and because the temptation it
    creates (turn verification off) is the one thing an administrator must
    not do.
    """
    name = type(exc).__name__
    text = str(exc)
    if "certificate" in text.lower() or "SSL" in name or "ssl" in text.lower():
        return (
            f"Headway could not verify the security certificate of {url}. "
            f"This almost always means your network inspects encrypted "
            f"traffic (a TLS-inspecting proxy or firewall) and re-signs it "
            f"with your organisation's own certificate authority, which "
            f"Headway does not yet trust. Ask your network administrator for "
            f"that authority's certificate file, put it on the Headway "
            f"server, and enter its path in 'Certificate authority file' "
            f"below. Headway will not turn certificate checking off, because "
            f"that would let anyone on the network impersonate your identity "
            f"provider."
        )
    return (
        f"Headway could not reach {url} ({name}). Check that the Headway "
        f"server can reach your identity provider — a firewall rule, a "
        f"proxy, or DNS is the usual cause — and that the address is exactly "
        f"the one your provider publishes."
    )


# ---------------------------------------------------------------------------
# Provider configuration + discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderConfig:
    """The configured provider, with the client secret already decrypted.

    Built per request from ``auth.oidc_provider``. The secret exists only
    inside the request that needs it; nothing here is ever serialized into a
    response or an audit record.
    """

    discovery_url: str
    client_id: str
    client_secret: str | None
    redirect_uri: str
    groups_claim: str = "groups"
    username_claim: str = "preferred_username"
    clock_skew_seconds: int = 120
    ca_bundle_path: str | None = None
    button_label: str = "Sign in with single sign-on"
    is_enabled: bool = False


def validate_discovery_url(url: str) -> None:
    """HTTPS, or loopback for development. Raises OidcConfigurationError."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise OidcConfigurationError(
            "The discovery address must start with https:// — it is the "
            "address of your identity provider's configuration document, "
            "usually ending in /.well-known/openid-configuration."
        )
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise OidcConfigurationError(
            "The discovery address must use https://, not http://. Headway "
            "refuses to fetch identity-provider configuration over an "
            "unencrypted connection, because anyone on the network could "
            "replace it and take over every sign-in. (http:// is allowed "
            "only for localhost, so a developer can test against a provider "
            "on the same machine.)"
        )
    if not parsed.netloc:
        raise OidcConfigurationError(
            "That does not look like a web address. Your identity provider "
            "publishes a discovery address ending in "
            "/.well-known/openid-configuration — paste that here."
        )


def validate_ca_bundle_path(path: str | None) -> None:
    """A configured trust store must exist and be readable NOW.

    Checked when the configuration is saved rather than at the next sign-in,
    so a typo is a message on the screen the admin is looking at instead of
    an outage tomorrow.
    """
    if not path:
        return
    if not os.path.isfile(path):
        raise OidcConfigurationError(
            f"There is no file at '{path}' on the Headway server. The "
            f"certificate authority file must be a PEM file that exists on "
            f"the server itself (not on your own computer), and the Headway "
            f"API must be able to read it. If Headway runs in a container, "
            f"the file must be mounted into that container."
        )
    if not os.access(path, os.R_OK):
        raise OidcConfigurationError(
            f"The file '{path}' exists but Headway is not allowed to read "
            f"it. Give the Headway service read permission on that file, "
            f"then test again."
        )


@dataclass
class _CacheEntry:
    value: Any
    fetched_at: float


class ProviderMetadata:
    """Discovery document + JWKS, cached, with rotation handled.

    One instance lives on ``app.state.oidc_metadata`` for the process. It is
    keyed by discovery URL, so changing the configured provider on the admin
    screen invalidates nothing by hand — a different URL is a different
    entry, and the old one ages out.
    """

    def __init__(self, http_factory=None, clock=time.monotonic):
        # A factory, because the CA bundle is per-configuration and the real
        # client holds it. Tests pass a factory returning their fake.
        self._http_factory = http_factory or (lambda ca: HttpxOidcClient(ca))
        self._clock = clock
        self._discovery: dict[str, _CacheEntry] = {}
        self._jwks: dict[str, _CacheEntry] = {}
        self._last_forced_refresh: dict[str, float] = {}

    def http(self, config: ProviderConfig):
        return self._http_factory(config.ca_bundle_path)

    # -- discovery ---------------------------------------------------------

    def discovery(self, config: ProviderConfig, *, force: bool = False) -> dict:
        """The provider's discovery document, cached for an hour.

        The ISSUER IS CHECKED AGAINST THE ADDRESS IT CAME FROM. A discovery
        document that names a different issuer than the URL it was served
        from is either a misconfiguration or an issuer-confusion attack, and
        the two are indistinguishable from here, so both are refused.
        """
        url = config.discovery_url
        entry = self._discovery.get(url)
        now = self._clock()
        if entry is not None and not force and (now - entry.fetched_at) < _DISCOVERY_TTL_SECONDS:
            return entry.value
        document = self.http(config).get_json(url)
        _validate_discovery_document(document, url)
        self._discovery[url] = _CacheEntry(document, now)
        return document

    # -- JWKS --------------------------------------------------------------

    def signing_key(self, config: ProviderConfig, kid: str | None, alg: str) -> PyJWK:
        """The key for ``kid``, refetching the JWKS if it is not cached.

        This is the rotation path: a provider that has rotated its signing
        key sends a ``kid`` this cache has never seen, so the cache refetches
        once (subject to ``_MIN_REFRESH_INTERVAL``) and finds it. No key is
        ever pinned.
        """
        jwks_uri = self.discovery(config).get("jwks_uri")
        if not jwks_uri:
            raise OidcConfigurationError(
                "Your identity provider's configuration document does not "
                "say where its signing keys are published (no 'jwks_uri'), "
                "so Headway cannot check that a sign-in really came from it."
            )
        keys = self._jwks_keys(config, jwks_uri)
        key = _select_key(keys, kid, alg)
        if key is not None:
            return key
        # Unknown kid: this is what a key rotation looks like from here.
        now = self._clock()
        last = self._last_forced_refresh.get(jwks_uri, 0.0)
        if (now - last) < _MIN_REFRESH_INTERVAL:
            raise OidcError(
                f"id_token signed by unknown key id {kid!r}; JWKS refresh "
                f"rate-limited"
            )
        self._last_forced_refresh[jwks_uri] = now
        keys = self._jwks_keys(config, jwks_uri, force=True)
        key = _select_key(keys, kid, alg)
        if key is None:
            raise OidcError(f"id_token signed by unknown key id {kid!r}")
        return key

    def _jwks_keys(self, config: ProviderConfig, jwks_uri: str, *, force: bool = False) -> list[dict]:
        entry = self._jwks.get(jwks_uri)
        now = self._clock()
        if entry is not None and not force and (now - entry.fetched_at) < _JWKS_TTL_SECONDS:
            return entry.value
        document = self.http(config).get_json(jwks_uri)
        keys = document.get("keys")
        if not isinstance(keys, list) or not keys:
            raise OidcConfigurationError(
                f"Your identity provider published no signing keys at "
                f"{jwks_uri}, so Headway cannot verify that a sign-in came "
                f"from it."
            )
        self._jwks[jwks_uri] = _CacheEntry(keys, now)
        return keys

    def forget(self, discovery_url: str) -> None:
        """Drop cached documents for one provider — used when the admin saves
        a new configuration, so a test action never reports on stale data."""
        self._discovery.pop(discovery_url, None)


def _validate_discovery_document(document: dict, url: str) -> None:
    issuer = document.get("issuer")
    if not issuer:
        raise OidcConfigurationError(
            f"The document at {url} is missing its 'issuer', so it is not an "
            f"OpenID Connect configuration document. Check the address with "
            f"your identity provider — it usually ends in "
            f"/.well-known/openid-configuration."
        )
    for required in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not document.get(required):
            raise OidcConfigurationError(
                f"Your identity provider's configuration document is missing "
                f"'{required}', so Headway cannot complete a sign-in with "
                f"it. This is a problem at the provider, not in Headway."
            )
    # Issuer-confusion guard: the document must belong to the address it came
    # from. Every mainstream provider satisfies this — Entra ID
    # (…/{tenant}/v2.0), Keycloak (…/realms/{realm}), Google, Okta — provided
    # a TENANT-SPECIFIC address is used. It is refused for the multi-tenant
    # Entra 'common' endpoint on purpose: that endpoint would admit any
    # Microsoft account anywhere, which is not what an agency means by
    # "our staff sign in with Entra ID".
    expected = issuer.rstrip("/") + "/.well-known/openid-configuration"
    if url.split("?")[0].rstrip("/") != expected:
        raise OidcConfigurationError(
            f"The configuration document at {url} says it belongs to a "
            f"different identity provider ('{issuer}'). Headway refuses this "
            f"because it cannot tell a copy-paste mistake apart from someone "
            f"impersonating your provider. Use the address your provider "
            f"publishes for YOUR organisation — for Microsoft Entra ID that "
            f"is the one containing your tenant id, not the shared "
            f"'common' address."
        )
    if "S256" not in (document.get("code_challenge_methods_supported") or ["S256"]):
        raise OidcConfigurationError(
            "Your identity provider says it does not support PKCE with "
            "SHA-256 (S256). Headway requires it and will not fall back to "
            "anything weaker."
        )


def _select_key(keys: list[dict], kid: str | None, alg: str) -> PyJWK | None:
    """Find the JWK for this token, refusing anything that is not a signing
    key for the (already allow-listed) algorithm."""
    candidates = []
    for jwk in keys:
        if jwk.get("use") not in (None, "sig"):
            continue
        if jwk.get("alg") is not None and jwk.get("alg") != alg:
            continue
        # A symmetric key must never be reachable from here — see the module
        # docstring on algorithm confusion.
        if jwk.get("kty") == "oct":
            continue
        if kid is not None and jwk.get("kid") is not None and jwk.get("kid") != kid:
            continue
        candidates.append(jwk)
    if not candidates:
        return None
    if kid is None and len(candidates) > 1:
        # Ambiguous: with several usable keys and no kid there is no way to
        # know which one the provider meant. Refusing is the honest answer.
        return None
    try:
        return PyJWK.from_dict(candidates[0])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Starting a sign-in: PKCE, state, nonce
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthorizationRequest:
    """Everything one started sign-in needs, split between what is stored
    server-side and what the browser is given."""

    authorization_url: str
    state: str
    nonce: str
    code_verifier: str
    #: Handed to the browser, kept in sessionStorage, and required back at
    #: the callback. Only its SHA-256 is stored (auth.oidc_login_states).
    browser_token: str
    browser_binding: str
    expires_at: dt.datetime


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def code_challenge_for(verifier: str) -> str:
    """PKCE S256 challenge (RFC 7636 §4.2)."""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def hash_browser_token(token: str) -> str:
    """SHA-256 hex. The token itself is never stored — possession is proved,
    not filed (the machine-API-key rule, migration 0013)."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def build_authorization_request(
    config: ProviderConfig,
    metadata: ProviderMetadata,
    *,
    now: Optional[dt.datetime] = None,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> AuthorizationRequest:
    """Generate state, nonce, PKCE verifier and the provider's URL.

    Every random value here is ``secrets.token_urlsafe(32)`` — 32 bytes of
    CSPRNG output, not a UUID and not a timestamp. ``state`` is unguessable
    so a forged callback cannot match a stored row; ``nonce`` is unguessable
    so an ID token cannot be minted to match one; the PKCE verifier is
    unguessable so an intercepted code cannot be redeemed.
    """
    document = metadata.discovery(config)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    browser_token = secrets.token_urlsafe(32)
    now = now or dt.datetime.now(dt.timezone.utc)
    params = {
        "response_type": "code",  # authorization code. never "token"/"id_token"
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge_for(code_verifier),
        "code_challenge_method": "S256",
    }
    endpoint = document["authorization_endpoint"]
    joiner = "&" if "?" in endpoint else "?"
    return AuthorizationRequest(
        authorization_url=f"{endpoint}{joiner}{urlencode(params)}",
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        browser_token=browser_token,
        browser_binding=hash_browser_token(browser_token),
        expires_at=now + dt.timedelta(seconds=LOGIN_STATE_TTL_SECONDS),
    )


# ---------------------------------------------------------------------------
# Finishing a sign-in: code exchange + ID-token validation
# ---------------------------------------------------------------------------


def exchange_code(
    config: ProviderConfig,
    metadata: ProviderMetadata,
    *,
    code: str,
    code_verifier: str,
) -> dict:
    """Redeem the authorization code at the token endpoint.

    Client authentication follows what the provider ADVERTISES, preferring
    ``client_secret_basic`` (the OIDC default) and falling back to
    ``client_secret_post``. A public client (no secret configured) sends
    none, which is safe only because PKCE is always on.
    """
    document = metadata.discovery(config)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
        "code_verifier": code_verifier,
    }
    auth = None
    if config.client_secret:
        supported = document.get("token_endpoint_auth_methods_supported") or [
            "client_secret_basic"
        ]
        if "client_secret_basic" in supported:
            auth = (config.client_id, config.client_secret)
        else:
            data["client_secret"] = config.client_secret
    tokens = metadata.http(config).post_form(
        document["token_endpoint"], data, auth=auth
    )
    if not tokens.get("id_token"):
        raise OidcError("token response carried no id_token")
    return tokens


@dataclass(frozen=True)
class VerifiedClaims:
    """A validated ID token, reduced to what Headway uses."""

    issuer: str
    subject: str
    username: str
    groups: tuple[str, ...]
    email: str | None
    raw: dict = field(repr=False, default_factory=dict)


def validate_id_token(
    id_token: str,
    config: ProviderConfig,
    metadata: ProviderMetadata,
    *,
    expected_nonce: str,
    now: Optional[dt.datetime] = None,
) -> VerifiedClaims:
    """Validate an ID token in full. Raises ``OidcError`` with a specific
    ``reason`` for the audit trail and the single generic public message.

    The order matters: the header's algorithm is allow-listed BEFORE a key is
    chosen, so a token asking to be verified with ``none`` or ``HS256`` never
    reaches a verifier at all.
    """
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.InvalidTokenError as exc:
        raise OidcError(f"id_token header unreadable: {type(exc).__name__}") from exc
    alg = header.get("alg")
    if alg not in ALLOWED_ID_TOKEN_ALGORITHMS:
        raise OidcError(
            f"id_token signing algorithm {alg!r} is not accepted "
            f"(asymmetric algorithms only)"
        )
    document = metadata.discovery(config)
    issuer = document["issuer"]
    key = metadata.signing_key(config, header.get("kid"), alg)
    skew = config.clock_skew_seconds
    try:
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=[alg],
            audience=config.client_id,
            issuer=issuer,
            leeway=skew,
            options={
                "require": ["exp", "iat", "iss", "aud", "sub"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise OidcError(f"id_token expired (skew tolerance {skew}s)") from exc
    except jwt.InvalidAudienceError as exc:
        raise OidcError("id_token audience is not this Headway client") from exc
    except jwt.InvalidIssuerError as exc:
        raise OidcError("id_token issuer does not match the provider") from exc
    except jwt.InvalidSignatureError as exc:
        raise OidcError("id_token signature did not verify") from exc
    except jwt.ImmatureSignatureError as exc:
        # iat (or nbf) further in the FUTURE than the tolerance. Skew works
        # in both directions; a token issued 'later' than we tolerate is not
        # a clock difference, it is a token we did not ask for.
        raise OidcError(
            f"id_token was issued in the future beyond the {skew}s clock "
            f"skew tolerance"
        ) from exc
    except jwt.MissingRequiredClaimError as exc:
        raise OidcError(f"id_token missing required claim: {exc}") from exc
    except jwt.InvalidTokenError as exc:
        raise OidcError(f"id_token rejected: {type(exc).__name__}") from exc

    # aud as a list requires azp to name this client (OIDC Core 3.1.3.7).
    audience = claims.get("aud")
    if isinstance(audience, list) and len(audience) > 1:
        if claims.get("azp") != config.client_id:
            raise OidcError(
                "id_token has multiple audiences and its authorized party "
                "is not this Headway client"
            )

    # Skew works both ways: a token issued further in the future than the
    # tolerance is not a clock difference.
    now = now or dt.datetime.now(dt.timezone.utc)
    issued_at = claims.get("iat")
    if isinstance(issued_at, (int, float)):
        if issued_at - now.timestamp() > skew:
            raise OidcError(
                f"id_token was issued in the future beyond the {skew}s clock "
                f"skew tolerance"
            )

    # The nonce binds this token to the sign-in THIS API started. Compared in
    # constant time, because it is a secret the browser round-tripped.
    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or not secrets.compare_digest(
        token_nonce, expected_nonce
    ):
        raise OidcError("id_token nonce did not match this sign-in")

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise OidcError("id_token has no usable subject")

    username = _username_from(claims, config.username_claim)
    if username is None:
        raise OidcError(
            f"id_token carries no username: neither the configured claim "
            f"'{config.username_claim}' nor a fallback was present"
        )

    return VerifiedClaims(
        issuer=issuer,
        subject=subject.strip(),
        username=username,
        groups=_groups_from(claims, config.groups_claim),
        email=claims.get("email") if isinstance(claims.get("email"), str) else None,
        raw=claims,
    )


def _username_from(claims: dict, username_claim: str) -> str | None:
    """The configured claim first, then the conventional fallbacks.

    The fallbacks exist because a provider that omits the configured claim
    otherwise produces "sign-in failed" with no clue; they are ordered from
    most to least human-meaningful, and the SUBJECT is never used as a
    username — an Entra ID subject is an opaque GUID, and a person cannot
    recognise themselves in an audit trail full of GUIDs.
    """
    for candidate in (username_claim, "preferred_username", "upn", "email"):
        value = claims.get(candidate)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _groups_from(claims: dict, groups_claim: str) -> tuple[str, ...]:
    """The group/role claim, normalized to a tuple of strings.

    Providers disagree about the shape: a JSON array (Entra ID, Keycloak,
    Okta) or a bare string when the user is in exactly one group. Both are
    read. A bare string is treated as ONE group value and is deliberately NOT
    split on whitespace — group names like "Transit Finance" are ordinary,
    and splitting them would invent two groups the provider never sent, one
    of which might accidentally match a mapping.

    Anything else yields NO groups, which means no mapping matches, which
    means the sign-in is refused. Deny-by-default, even in the parser.
    """
    value = claims.get(groups_claim)
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(
            str(item).strip()
            for item in value
            if isinstance(item, (str, int)) and str(item).strip()
        )
    return ()


# ---------------------------------------------------------------------------
# The admin test action's credential probe
# ---------------------------------------------------------------------------

#: What the token endpoint says when the CODE is bad but the CLIENT is fine.
_CODE_REJECTED_ERRORS = frozenset({"invalid_grant", "invalid_request"})
#: What it says when the CLIENT ID or SECRET is wrong.
_CLIENT_REJECTED_ERRORS = frozenset({"invalid_client", "unauthorized_client"})


def probe_client_credentials(
    config: ProviderConfig, metadata: ProviderMetadata
) -> tuple[bool, str]:
    """Prove the client id and secret actually work, without a browser.

    The admin screen's "test this configuration" button has to answer the
    question that matters — *will a sign-in work?* — before a member of staff
    finds out the hard way. Discovery and JWKS can both succeed while the
    client secret is a stale value from a rotation nobody told Headway about,
    and that failure only appears at the very last step of a real sign-in.

    So this deliberately redeems an authorization code that cannot possibly
    be valid, using the configured client credentials, and reads the
    provider's error code:

    * ``invalid_client`` / ``unauthorized_client`` -> the CREDENTIALS are
      wrong. This is the finding worth having.
    * ``invalid_grant`` (and friends) -> the credentials were ACCEPTED and
      only the fake code was refused. That is a pass.

    Sending a code that is certain to be rejected is a no-op at the provider:
    nothing is issued, nothing is consumed, no user is involved.
    """
    document = metadata.discovery(config)
    data = {
        "grant_type": "authorization_code",
        # Self-describing so it is obvious in a provider's logs what this was,
        # and deliberately PRODUCT-NAME-FREE: this string is sent to the
        # agency's identity provider and lands in THEIR logs, so it is an
        # externally visible identifier. Baking a product name into it would
        # leave stale names in a customer's audit records forever after a
        # rename, and there is no reason for the diagnostic value to depend
        # on what the product is called.
        "code": "sso-configuration-test-" + secrets.token_urlsafe(8),
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
        "code_verifier": secrets.token_urlsafe(64),
    }
    auth = None
    if config.client_secret:
        supported = document.get("token_endpoint_auth_methods_supported") or [
            "client_secret_basic"
        ]
        if "client_secret_basic" in supported:
            auth = (config.client_id, config.client_secret)
        else:
            data["client_secret"] = config.client_secret
    status, body = metadata.http(config).post_form_probe(
        document["token_endpoint"], data, auth=auth
    )
    error = str(body.get("error") or "")
    if error in _CLIENT_REJECTED_ERRORS or status in (401,):
        return False, (
            "Your identity provider rejected Headway's client id or client "
            "secret. Check the client id above, and enter the client secret "
            "again — if the secret was rotated at the provider, Headway still "
            "holds the old one. (Headway sent a deliberately invalid sign-in "
            "code to test this; no one was signed in.)"
        )
    if error in _CODE_REJECTED_ERRORS or status == 400:
        return True, (
            "Your identity provider accepted Headway's client id and client "
            "secret. (Headway proved this by sending a deliberately invalid "
            "sign-in code: the provider refused the code, which it can only "
            "do after accepting the credentials.)"
        )
    if status == 200:
        # Cannot happen with an invented code; if it does, something is very
        # wrong at the provider and pretending otherwise helps nobody.
        return False, (
            "Your identity provider accepted a sign-in code that Headway "
            "made up. That should be impossible, and Headway will not treat "
            "this provider as trustworthy. Please raise this with whoever "
            "administers it."
        )
    return False, (
        f"Your identity provider answered the sign-in step with HTTP {status}"
        + (f" ('{error}')" if error else "")
        + ". Headway could not confirm that its client id and client secret "
        "are correct. Check them with whoever registered Headway at the "
        "provider."
    )
