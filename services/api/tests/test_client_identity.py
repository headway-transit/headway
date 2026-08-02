"""Who a request came from — and why believing a header is the dangerous part.

The bug this closes: every per-caller control in the API keyed on
``request.client.host``, which behind the LAN profile's Caddy is one address
for the whole office. One shared audit-throttle bucket, one shared rate-limit
allowance, and an audit trail that recorded the proxy for everybody.

The bug it must not open: ``X-Forwarded-For`` is written by whoever is
talking to you. An API that believes it unconditionally is worse off than one
that ignores it — every caller picks a fresh bucket per request and no limit
means anything. So most of what is tested here is REFUSAL to believe it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from headway_api import client_identity
from headway_api.machine_auth import RateLimiter
from headway_api.client_identity import (
    UNKNOWN,
    InvalidTrustedProxy,
    client_address,
    networks,
    parse_trusted_proxies,
    resolve,
)

PROXY = "172.18.0.9"
TRUSTED = networks(("172.18.0.0/16",))
REAL_CLIENT = "203.0.113.77"


# ---------------------------------------------------------------------------
# The header is only ever read from someone we were told to trust
# ---------------------------------------------------------------------------


def test_an_unconfigured_installation_ignores_the_header_entirely():
    """The default is EMPTY trust, and it must be airtight: with no proxy
    configured, a caller who sends the header gets their own address anyway.
    This is the case that makes the feature safe to ship on by default."""
    assert resolve(REAL_CLIENT, "1.2.3.4", ()) == REAL_CLIENT


def test_an_untrusted_peer_cannot_speak_for_anyone_else():
    """A middlebox we were not told about is just a caller. Its claims about
    a third party are decoration, not evidence."""
    assert resolve("198.51.100.4", f"{REAL_CLIENT}, 198.51.100.4", TRUSTED) == (
        "198.51.100.4"
    )


def test_a_trusted_proxy_is_believed():
    assert resolve(PROXY, REAL_CLIENT, TRUSTED) == REAL_CLIENT


def test_a_trusted_peer_with_no_header_is_itself():
    assert resolve(PROXY, None, TRUSTED) == PROXY
    assert resolve(PROXY, "", TRUSTED) == PROXY


# ---------------------------------------------------------------------------
# Right to left — the part that is easy to get backwards
# ---------------------------------------------------------------------------


def test_entries_the_caller_prepended_are_ignored():
    """THE attack. A proxy APPENDS the peer it actually saw, so the rightmost
    entry is the only one it vouched for. A caller who sends
    ``X-Forwarded-For: <someone else>`` has it forwarded on with their own
    address appended to the right — reading left to right reads exactly the
    part they control, and lets them mint a bucket per request."""
    forged = f"9.9.9.9, 8.8.8.8, {REAL_CLIENT}"
    assert resolve(PROXY, forged, TRUSTED) == REAL_CLIENT


def test_several_of_our_own_proxies_are_walked_past():
    """Two hops inside the trust boundary: keep walking left until something
    is not ours. That first non-ours entry is the caller."""
    chain = f"{REAL_CLIENT}, 172.18.0.4, 172.18.0.9"
    assert resolve(PROXY, chain, TRUSTED) == REAL_CLIENT


def test_a_chain_made_only_of_our_own_proxies_falls_back_to_the_peer():
    """Health checks and internal calls: nothing outside ever appeared, so
    the caller IS one of ours. Not an error, and not 'unknown'."""
    assert resolve(PROXY, "172.18.0.4, 172.18.0.9", TRUSTED) == PROXY


def test_an_absurdly_long_chain_is_not_walked():
    """A forwarded chain longer than a deployment is someone paying us to
    parse. The peer address is used and the walk stops."""
    chain = ", ".join(["9.9.9.9"] * (client_identity.MAX_FORWARDED_HOPS + 1))
    assert resolve(PROXY, chain, TRUSTED) == PROXY


# ---------------------------------------------------------------------------
# One caller must not be able to hold several buckets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    [
        "203.0.113.77",
        "203.0.113.77:51234",
        " 203.0.113.77 ",
    ],
)
def test_one_address_spelled_several_ways_is_one_bucket(spelling):
    """A rate limit keyed on a string is only a rate limit if the string is
    canonical. A port is not identity — two connections from one machine are
    one caller."""
    assert resolve(PROXY, spelling, TRUSTED) == REAL_CLIENT


@pytest.mark.parametrize(
    "spelling", ["[2001:db8::1]:443", "2001:db8::1", "2001:0db8:0000::0001"]
)
def test_ipv6_is_normalized_too(spelling):
    assert resolve(PROXY, spelling, TRUSTED) == "2001:db8::1"


def test_garbage_in_the_chain_does_not_become_an_identity():
    """An unparseable entry is skipped rather than used as a bucket key —
    otherwise free-text in a header is a free bucket."""
    assert resolve(PROXY, f"not-an-ip, {REAL_CLIENT}", TRUSTED) == REAL_CLIENT
    assert resolve(PROXY, "not-an-ip", TRUSTED) == PROXY


# ---------------------------------------------------------------------------
# Absent and unusual peers
# ---------------------------------------------------------------------------


def test_no_peer_at_all_is_the_string_the_audit_trail_already_contains():
    assert resolve(None, None, TRUSTED) == UNKNOWN


def test_a_non_ip_peer_is_returned_verbatim_and_reads_no_header():
    """Starlette's TestClient presents 'testclient'. It cannot be checked
    against the trusted set, so the header stays unread — a bucket key only
    has to be stable and unforgeable."""
    assert resolve("testclient", REAL_CLIENT, TRUSTED) == "testclient"


# ---------------------------------------------------------------------------
# Configuration refuses loudly
# ---------------------------------------------------------------------------


def test_trusted_proxies_parses_addresses_and_cidrs():
    assert parse_trusted_proxies("172.18.0.0/16, 10.0.0.5") == (
        "172.18.0.0/16",
        "10.0.0.5",
    )
    assert parse_trusted_proxies("") == ()
    assert parse_trusted_proxies(None) == ()


def test_a_typo_refuses_at_startup_rather_than_trusting_nothing_quietly():
    """The failure mode being prevented: an operator configures a proxy, sees
    no error, and believes per-client limits are in force when every request
    is still bucketed as the proxy."""
    with pytest.raises(InvalidTrustedProxy) as excinfo:
        parse_trusted_proxies("172.18.0.0/16, 10.0.0..5")
    assert "10.0.0..5" in str(excinfo.value)
    assert "sharing one rate-limit bucket" in str(excinfo.value)


# ---------------------------------------------------------------------------
# End to end: the actual bug
# ---------------------------------------------------------------------------


def _client(app, peer: str) -> TestClient:
    return TestClient(app, client=(peer, 50000))


def test_two_people_behind_one_proxy_no_longer_share_one_allowance(
    app, fake_db, settings
):
    """THE BUG. Before this, everyone in the office arrived as Caddy's
    container address, so whoever spent the public allowance first locked out
    the rest of the agency."""
    app.state.trusted_proxy_networks = TRUSTED
    app.state.public_rate_limiter = RateLimiter(requests_per_minute=2)

    alice = _client(app, PROXY)
    headers_alice = {"X-Forwarded-For": "203.0.113.10"}
    headers_bob = {"X-Forwarded-For": "203.0.113.20"}

    # Alice spends the whole allowance.
    assert alice.get("/branding", headers=headers_alice).status_code == 200
    assert alice.get("/branding", headers=headers_alice).status_code == 200
    assert alice.get("/branding", headers=headers_alice).status_code == 429

    # Bob is a different person and still has his own.
    assert alice.get("/branding", headers=headers_bob).status_code == 200


def test_a_caller_cannot_mint_a_fresh_bucket_by_forging_the_header(app, fake_db):
    """The regression that would make this worse than before it existed: if a
    forged header picked the bucket, every request would get a new one and the
    limit would be decorative."""
    app.state.trusted_proxy_networks = TRUSTED
    app.state.public_rate_limiter = RateLimiter(requests_per_minute=2)

    attacker = _client(app, PROXY)
    # Same real client (appended on the right by the proxy), different forged
    # values on the left every time.
    for attempt, status in enumerate((200, 200, 429, 429)):
        headers = {"X-Forwarded-For": f"10.{attempt}.{attempt}.{attempt}, 198.51.100.9"}
        assert attacker.get("/branding", headers=headers).status_code == status


def test_an_unconfigured_app_is_unaffected_end_to_end(app, fake_db):
    """No trusted proxies: the header is not read, so a caller sending one
    shares the peer's bucket exactly as before this module existed."""
    app.state.trusted_proxy_networks = ()
    app.state.public_rate_limiter = RateLimiter(requests_per_minute=2)

    caller = _client(app, "198.51.100.4")
    for attempt, status in enumerate((200, 200, 429)):
        headers = {"X-Forwarded-For": f"10.{attempt}.{attempt}.{attempt}"}
        assert caller.get("/branding", headers=headers).status_code == status


def test_client_address_reads_app_state_and_tolerates_its_absence(app):
    """Matches how the limiter and throttle already tolerate a bare test app:
    no configuration means the peer address."""

    class _Req:
        def __init__(self, application, peer, headers):
            self.app = application
            self.client = type("C", (), {"host": peer})()
            self.headers = headers

    app.state.trusted_proxy_networks = TRUSTED
    assert client_address(_Req(app, PROXY, {"x-forwarded-for": REAL_CLIENT})) == (
        REAL_CLIENT
    )

    del app.state.trusted_proxy_networks
    assert client_address(_Req(app, PROXY, {"x-forwarded-for": REAL_CLIENT})) == PROXY
