"""A signed-in account is not an unlimited account.

Until now every rate limit in this API covered a machine key or one of the two
unauthenticated surfaces. A signed-in human session could issue requests as
fast as the box would answer them — including an ``auditor``, which is the one
role this installation deliberately hands to someone outside the agency, and
which handoff 0047 pointed at the most expensive endpoint in the product.

Two limits, because there are two different threats:

- **Per account, everywhere** — a script using one account as a load
  generator. Sized for a UI, not a person.
- **Per account, the evidence bundle alone** — one request there costs 142 MB
  of peak allocation and 4.3 seconds (tests/bench_evidence_cost.py). The
  blanket limit would still allow 600 of those a minute.
"""

from __future__ import annotations

import pytest

from conftest import add_auditor, auth_header

from headway_api.app import Settings, _positive_int_env
from headway_api.machine_auth import RateLimiter


PROBE = "/metrics/values"


def test_one_account_cannot_use_itself_as_a_load_generator(app, client, fake_db):
    app.state.human_rate_limiter = RateLimiter(requests_per_minute=2)
    headers = auth_header(fake_db, "vera")

    assert client.get(PROBE, headers=headers).status_code == 200
    assert client.get(PROBE, headers=headers).status_code == 200
    refused = client.get(PROBE, headers=headers)
    assert refused.status_code == 429
    # A refusal that does not say when to come back is a refusal the client
    # answers by retrying immediately.
    assert int(refused.headers["Retry-After"]) >= 1


def test_one_account_running_out_does_not_touch_anybody_else(app, client, fake_db):
    """The failure this must not reproduce: a shared bucket, where whoever
    spends it first locks out the rest of the agency."""
    app.state.human_rate_limiter = RateLimiter(requests_per_minute=2)
    vera = auth_header(fake_db, "vera")
    stella = auth_header(fake_db, "stella")

    for _ in range(2):
        assert client.get(PROBE, headers=vera).status_code == 200
    assert client.get(PROBE, headers=vera).status_code == 429
    assert client.get(PROBE, headers=stella).status_code == 200


def test_the_bucket_is_the_ACCOUNT_not_the_address(app, fake_db):
    """Keying an authenticated surface on the address would merge everyone
    behind one office router AND let one account multiply itself by moving.
    A signed-in caller has a name; the name is what is bounded."""
    from fastapi.testclient import TestClient

    app.state.human_rate_limiter = RateLimiter(requests_per_minute=2)
    headers = auth_header(fake_db, "vera")
    desk = TestClient(app, client=("203.0.113.10", 50000))
    laptop = TestClient(app, client=("203.0.113.99", 50000))

    assert desk.get(PROBE, headers=headers).status_code == 200
    assert desk.get(PROBE, headers=headers).status_code == 200
    # Same account, different address — the allowance does not reset.
    assert laptop.get(PROBE, headers=headers).status_code == 429


def test_an_auditor_is_bounded_like_everyone_else(app, client, fake_db):
    """The role handed to an outside party is the one that most needs a
    ceiling, and it is not special-cased in either direction."""
    add_auditor(fake_db)
    app.state.human_rate_limiter = RateLimiter(requests_per_minute=1)
    headers = auth_header(fake_db, "audra")

    assert client.get(PROBE, headers=headers).status_code == 200
    assert client.get(PROBE, headers=headers).status_code == 429


def test_the_limit_is_enforced_at_the_choke_point_so_it_cannot_be_routed_around(
    app, client, fake_db
):
    """It sits in ``get_current_identity``, which every authenticated endpoint
    resolves through — so an endpoint added later is covered by construction
    rather than by remembering. Spend the allowance on one endpoint; a
    completely different one is refused too."""
    app.state.human_rate_limiter = RateLimiter(requests_per_minute=1)
    headers = auth_header(fake_db, "vera")

    assert client.get(PROBE, headers=headers).status_code == 200
    assert client.get("/dq/issues", headers=headers).status_code == 429
    assert client.get("/sources/status", headers=headers).status_code == 429


def test_an_app_without_the_limiter_is_unlimited(app, client, fake_db):
    """Matches how every other control here tolerates a bare test app: a
    fixture that predates a control must exercise the logic under test, not
    fail on the control."""
    del app.state.human_rate_limiter
    headers = auth_header(fake_db, "vera")
    for _ in range(5):
        assert client.get(PROBE, headers=headers).status_code == 200


# ---------------------------------------------------------------------------
# The evidence bundle's own, much tighter bucket
# ---------------------------------------------------------------------------


def test_the_evidence_bundle_runs_out_long_before_the_blanket_limit(
    app, client, fake_db, fake_store
):
    """Its cost is measured, not assumed. The blanket limit is sized for UI
    chatter and would permit hundreds of 142 MB responses a minute."""
    from test_evidence_bundle import _certify, _seed

    mv = _seed(fake_db, fake_store)
    certification_id = _certify(client, fake_db, mv)

    app.state.human_rate_limiter = RateLimiter(requests_per_minute=600)
    app.state.evidence_rate_limiter = RateLimiter(requests_per_minute=2)
    headers = auth_header(fake_db, "cora")
    url = f"/certifications/{certification_id}/evidence"

    assert client.get(url, headers=headers).status_code == 200
    assert client.get(url, headers=headers).status_code == 200
    assert client.get(url, headers=headers).status_code == 429
    # The blanket allowance is untouched: an auditor who hit the bundle limit
    # can still read the rest of the product.
    assert client.get(PROBE, headers=headers).status_code == 200


def test_the_bundle_limit_is_charged_before_any_work_is_done(
    app, client, fake_db, fake_store
):
    """A limit taken AFTER the expensive part protects nothing. Charged before
    the certification is even looked up — so a refusal costs one dictionary
    lookup, and an unknown id is refused the same as a real one."""
    app.state.evidence_rate_limiter = RateLimiter(requests_per_minute=1)
    headers = auth_header(fake_db, "cora")
    unknown = "00000000-0000-0000-0000-000000000000"

    assert client.get(
        f"/certifications/{unknown}/evidence", headers=headers
    ).status_code == 404
    assert client.get(
        f"/certifications/{unknown}/evidence", headers=headers
    ).status_code == 429


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_a_zero_limit_refuses_every_request_instead_of_crashing(app, client, fake_db):
    """0 is a legitimate way to close a surface without a code change. Before
    the guard in RateLimiter it was a ZeroDivisionError — a configuration
    value turning a refusal into a 500."""
    app.state.human_rate_limiter = RateLimiter(requests_per_minute=0)
    refused = client.get(PROBE, headers=auth_header(fake_db, "vera"))
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) >= 1


def test_limits_are_tunable_from_the_environment(monkeypatch):
    monkeypatch.setenv("HEADWAY_HUMAN_REQUESTS_PER_MINUTE", "120")
    assert _positive_int_env("HEADWAY_HUMAN_REQUESTS_PER_MINUTE", 600) == 120


def test_an_unset_or_blank_limit_keeps_the_default(monkeypatch):
    monkeypatch.delenv("HEADWAY_HUMAN_REQUESTS_PER_MINUTE", raising=False)
    assert _positive_int_env("HEADWAY_HUMAN_REQUESTS_PER_MINUTE", 600) == 600
    monkeypatch.setenv("HEADWAY_HUMAN_REQUESTS_PER_MINUTE", "   ")
    assert _positive_int_env("HEADWAY_HUMAN_REQUESTS_PER_MINUTE", 600) == 600


@pytest.mark.parametrize("bad", ["lots", "-1", "12.5"])
def test_a_nonsense_limit_refuses_at_startup(monkeypatch, bad):
    """Silently coercing it would leave an operator believing they set a limit
    they did not set."""
    monkeypatch.setenv("HEADWAY_HUMAN_REQUESTS_PER_MINUTE", bad)
    with pytest.raises(ValueError):
        _positive_int_env("HEADWAY_HUMAN_REQUESTS_PER_MINUTE", 600)


def test_zero_is_accepted_because_it_means_something(monkeypatch):
    monkeypatch.setenv("HEADWAY_EVIDENCE_BUNDLE_REQUESTS_PER_MINUTE", "0")
    assert _positive_int_env("HEADWAY_EVIDENCE_BUNDLE_REQUESTS_PER_MINUTE", 10) == 0


def test_the_defaults_are_the_ones_the_reasoning_names():
    """Pinned so a future edit to either number has to come past this test and
    the comment that justifies it."""
    assert Settings.human_requests_per_minute == 600
    assert Settings.evidence_bundle_requests_per_minute == 10
