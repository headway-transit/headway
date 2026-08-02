"""The `auditor` role: reads everything, changes nothing (handoff 0046).

The role exists so an auditor can be given the reach an audit needs without
being given the ability to alter what they are auditing. These tests are
mostly NEGATIVE, because the interesting claim is not "an auditor can read
the figures" — it is "an auditor cannot do any of the other 30 things every
other role can do", and that claim has to hold for endpoints nobody has
written yet.

Three enforcement points, tested separately so a regression in one is not
masked by another:

1. ``auditor`` is off the rank ladder, so ``require_at_least`` fails it.
2. Unsafe HTTP methods are refused at the authentication choke point.
3. Content sensitivity is evaluated at VIEWER breadth — migration 0028's
   rider-location withholding is not waived for an auditor.
"""

from __future__ import annotations

import datetime as dt
import json
import re

import pytest

from conftest import UTC, add_auditor, auth_header
from headway_api import authz


# ---------------------------------------------------------------------------
# 1. Off the ladder, by construction
# ---------------------------------------------------------------------------


def test_auditor_is_not_a_rung_on_the_rank_ladder():
    """The structural claim the whole role rests on. If someone ever adds
    `auditor` to ROLE_RANK, every rank gate silently starts admitting it —
    so the absence is asserted, not assumed."""
    assert "auditor" not in authz.ROLE_RANK
    assert "auditor" in authz.READ_ONLY_ROLES
    assert "auditor" in authz.ALL_ROLES


@pytest.mark.parametrize("minimum", ["viewer", "data_steward", "report_preparer"])
def test_auditor_satisfies_no_rank_requirement(minimum):
    """Including `viewer`. A rank gate is a WRITE gate in this codebase, and
    an auditor writes nothing — not even at the bottom rung."""
    from fastapi import HTTPException

    dependency = authz.require_at_least(minimum)
    identity = _identity("auditor")
    with pytest.raises(HTTPException) as exc:
        dependency(identity)
    assert exc.value.status_code == 403
    assert "read Headway but cannot change anything" in exc.value.detail


def test_unknown_role_is_refused_rather_than_ranked():
    """Deny-by-default for a role name this build does not know — never a
    guessed rank, never a default of viewer."""
    from fastapi import HTTPException

    dependency = authz.require_at_least("viewer")
    with pytest.raises(HTTPException) as exc:
        dependency(_identity("regional_overseer"))
    assert exc.value.status_code == 403
    assert "not one this version of Headway recognizes" in exc.value.detail


def _identity(role: str):
    from headway_api.auth import Identity

    return Identity(sub="u-1", username="someone", role=role)


# ---------------------------------------------------------------------------
# 2. Reads everything readable
# ---------------------------------------------------------------------------


def test_auditor_reads_the_figures_and_their_receipts(client, fake_db):
    add_auditor(fake_db)
    fake_db.add_metric_value(metric="vrm")
    r = client.get("/metrics/values", headers=auth_header(fake_db, "audra"))
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_auditor_reads_the_dq_queue_and_the_certifications(client, fake_db):
    add_auditor(fake_db)
    for path in ("/dq/issues", "/certifications", "/settings", "/calc/runs"):
        r = client.get(path, headers=auth_header(fake_db, "audra"))
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"


def test_auditor_reads_the_audit_trail_and_a_data_steward_cannot(client, fake_db):
    """The one read surface that is NARROWER than `require_authenticated`.
    The trail names what every person did; a steward has no need of it to do
    their job, and an auditor has no purpose without it."""
    add_auditor(fake_db)
    fake_db.audit_events.append({
        "event_id": 1, "at": dt.datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        "actor": "cora", "action": "certify",
        "subject_kind": "cert.certifications", "subject_id": "c-1",
        "detail": {"metric_value_ids": ["m-1"]},
    })
    fake_db._next_event_id = 2

    ok = client.get("/audit/events", headers=auth_header(fake_db, "audra"))
    assert ok.status_code == 200
    assert ok.json()["events"][0]["actor"] == "cora"
    assert ok.json()["events"][0]["action"] == "certify"

    admin = client.get("/audit/events", headers=auth_header(fake_db, "cora"))
    assert admin.status_code == 200

    for username in ("stella", "petra", "vera"):
        denied = client.get("/audit/events", headers=auth_header(fake_db, username))
        assert denied.status_code == 403
        assert "cannot read Headway's audit trail" in denied.json()["detail"]


def test_audit_trail_filters_and_pages_without_skipping_rows(client, fake_db):
    """Keyset pagination, because an audit trail that skips a row while new
    rows are being written is worse than no audit trail."""
    add_auditor(fake_db)
    for i in range(1, 6):
        fake_db.audit_events.append({
            "event_id": i, "at": dt.datetime(2026, 8, 1, 10, i, tzinfo=UTC),
            "actor": "cora" if i % 2 else "stella", "action": "certify",
            "subject_kind": None, "subject_id": None, "detail": {},
        })
    headers = auth_header(fake_db, "audra")

    page = client.get("/audit/events?limit=2", headers=headers).json()
    assert [e["event_id"] for e in page["events"]] == [5, 4]
    assert page["next_cursor"] == 4

    nxt = client.get(
        f"/audit/events?limit=2&before_event_id={page['next_cursor']}",
        headers=headers,
    ).json()
    assert [e["event_id"] for e in nxt["events"]] == [3, 2]

    only_cora = client.get("/audit/events?actor=cora", headers=headers).json()
    assert {e["actor"] for e in only_cora["events"]} == {"cora"}


def test_reading_the_audit_trail_is_itself_recorded_in_the_audit_trail(
    client, fake_db
):
    """Every other content read in this API records that it happened, and this
    is the read that most needs to.

    The trail names every actor and every action across the installation. An
    oversight surface that can be swept invisibly lets the reviewed party
    watch the reviewer, and lets a reviewer scope a search that nobody can
    later reconstruct. So the recorded event carries the FILTERS and the
    number of rows — enough to tell a scoped lookup from a sweep of the whole
    installation — and never the rows themselves, which are already in the
    table being read.
    """
    add_auditor(fake_db)
    for i in range(1, 4):
        fake_db.audit_events.append({
            "event_id": i, "at": dt.datetime(2026, 8, 1, 10, i, tzinfo=UTC),
            "actor": "cora", "action": "certify",
            "subject_kind": "cert.certifications", "subject_id": f"c-{i}",
            "detail": {"attestation": "June figures are accurate."},
        })
    fake_db._next_event_id = 4

    read = client.get(
        "/audit/events?actor=cora&action=certify&limit=25",
        headers=auth_header(fake_db, "audra"),
    )
    assert read.status_code == 200
    assert len(read.json()["events"]) == 3

    written = [e for e in fake_db.audit_events if e["action"] == "audit_trail_read"]
    assert len(written) == 1, "one read, one record — no more and no fewer"
    assert written[0]["actor"] == "audra"
    assert written[0]["subject_kind"] == "audit.events"

    detail = _as_dict(written[0]["detail"])
    assert detail["filters"] == {"actor": "cora", "action": "certify"}
    assert detail["limit"] == 25
    assert detail["returned"] == 3
    assert detail["paged"] is False

    # Never the rows. Copying what was read into the record of the reading
    # doubles the trail's size on every sweep and duplicates content that is
    # already one row away.
    serialized = json.dumps(detail)
    assert "June figures are accurate." not in serialized
    for i in range(1, 4):
        assert f"c-{i}" not in serialized


def test_an_unfiltered_sweep_is_distinguishable_from_a_scoped_lookup(
    client, fake_db
):
    """What the recorded filters are FOR: 'who read what' is only a useful
    question if a targeted lookup and a wholesale export look different
    afterwards."""
    add_auditor(fake_db)
    client.get("/audit/events", headers=auth_header(fake_db, "audra"))
    detail = _as_dict(
        [e for e in fake_db.audit_events if e["action"] == "audit_trail_read"][0]
        ["detail"]
    )
    assert detail["filters"] == {}
    assert detail["limit"] == 100  # audit_trail.DEFAULT_LIMIT


# ---------------------------------------------------------------------------
# 3. Changes nothing — the method-level ban
# ---------------------------------------------------------------------------


WRITE_ATTEMPTS = [
    ("POST", "/dq/issues/i-1/resolve", {"resolution": "x", "note": "y"}),
    ("POST", "/certifications", {"metric_value_ids": ["m-1"], "attestation": "x"}),
    ("POST", "/users", {"username": "new.person", "role": "viewer", "password": "abcd1234"}),
    ("POST", "/calc/runs", {"period_start": "2026-06-01", "period_end": "2026-07-01"}),
    ("PUT", "/settings/gap_threshold_seconds", {"value": "90"}),
    ("POST", "/machine/keys", {"name": "k", "scopes": ["read:metrics"]}),
    ("POST", "/safety/events", {}),
    ("POST", "/attestations", {}),
    ("DELETE", "/machine/keys/k-1", None),
    ("PUT", "/auth/oidc/config", {}),
    ("POST", "/auth/oidc/mappings", {"claim_value": "g", "headway_role": "viewer"}),
]


@pytest.mark.parametrize("method,path,body", WRITE_ATTEMPTS)
def test_auditor_cannot_write_anywhere(client, fake_db, method, path, body):
    """Every state-changing endpoint, refused at the ONE choke point every
    authenticated request passes through — so this holds for endpoints that
    do not exist yet, written by people who have never heard of this role."""
    add_auditor(fake_db)
    r = client.request(
        method, path, json=body, headers=auth_header(fake_db, "audra")
    )
    assert r.status_code == 403, f"{method} {path} -> {r.status_code}"
    assert "change nothing" in r.json()["detail"]


def test_auditor_is_refused_the_read_shaped_posts_too(client, fake_db):
    """`/sandbox/preview` computes a what-if and `/raw/records/{id}/verify`
    raises a data-quality finding on a mismatch. Both are POSTs, both are
    outside "reads everything, changes nothing", and refusing by METHOD with
    no allow-list is what makes that guarantee hold without maintenance."""
    add_auditor(fake_db)
    headers = auth_header(fake_db, "audra")
    preview = client.post(
        "/sandbox/preview",
        json={
            "period_start": "2026-06-01",
            "period_end": "2026-07-01",
            "proposed": {"gap_threshold_seconds": "90"},
        },
        headers=headers,
    )
    assert preview.status_code == 403
    verify = client.post("/raw/records/abc/verify", headers=headers)
    assert verify.status_code == 403


# ---------------------------------------------------------------------------
# 3b. The same claim, made about EVERY route rather than a hand-written list
# ---------------------------------------------------------------------------
#
# WRITE_ATTEMPTS above is a list somebody maintains, which means it is a list
# somebody forgets. The guarantee this role rests on is "an auditor cannot do
# any of the things every other role can do", including the ones written after
# this file was. That claim can only be tested by asking the application which
# routes it has.

#: The two families of route an auditor's token is not the right question for.
#: Deliberately explicit and deliberately short — every entry here is a route
#: this sweep stops covering, so adding one should feel expensive.
ROUTES_NOT_REACHED_BY_A_SESSION_TOKEN = {
    # The sign-in surface itself. These take NO session token (that is the
    # point of them), so `get_current_identity` — the choke point that refuses
    # unsafe methods for a read-only role — never runs. An auditor calling
    # /auth/login gets the ordinary login response, not a 403.
    "/auth/login",
    "/auth/oidc/start",
    "/auth/oidc/callback",
    # Machine-key ingest. These authenticate with an `hw_` API key through
    # machine_auth, not with a person's session at all, so a session token of
    # any role is refused there as "not a machine key" rather than by role.
    "/ingest/tides/passenger-events",
    "/ingest/dr/trips",
}

#: GET/HEAD/OPTIONS: what "reads everything" means.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Substituted for `{path_parameters}`. A 403 must be decided by the role gate
#: BEFORE any lookup, so the value only has to be syntactically plausible —
#: but it is made plausible per-parameter anyway, because a 422 from a type
#: coercion would hide the very thing this test is asking about.
PATH_PARAMETER_DUMMIES = {"service_date": "2026-06-01"}
DEFAULT_PATH_PARAMETER = "00000000-0000-0000-0000-000000000000"


def _walk_routes(routes):
    """Every ``(path, methods)`` the app can serve, wrappers unwrapped.

    FastAPI 0.139 keeps an included router as a ``_IncludedRouter`` entry in
    ``app.routes`` rather than flattening its routes into it, so this recurses
    through those. Asking the app rather than listing paths by hand is the
    whole point: an endpoint added next year is covered on the day it is
    written, by someone who has never read this file.
    """
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from _walk_routes(included.routes)
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            yield path, methods


def _unsafe_routes(app):
    found = set()
    for path, methods in _walk_routes(app.routes):
        if path in ROUTES_NOT_REACHED_BY_A_SESSION_TOKEN:
            continue
        for method in set(methods) - SAFE_METHODS:
            found.add((method, path))
    return sorted(found)


def test_the_route_walk_really_finds_the_write_surface(app):
    """A guard on the guard below. If the walk ever stops seeing routes — a
    FastAPI upgrade changing how included routers are stored would do it —
    the sweep would pass with nothing to check, which is the one way a test
    like this fails silently."""
    found = _unsafe_routes(app)
    assert len(found) >= 30, found
    assert ("POST", "/certifications") in found
    assert ("PUT", "/settings/{setting_key}") in found
    assert ("DELETE", "/webhooks/{subscription_id}") in found
    # And the skip list is doing what it says, no more.
    assert ("POST", "/auth/login") not in found
    assert ("POST", "/ingest/dr/trips") not in found


def test_an_auditor_is_refused_every_unsafe_route_this_app_has(client, app, fake_db):
    """The whole write surface, swept.

    Any 403 here comes from ``auth.get_current_identity`` — before routing has
    decided whether the record exists, before a body is validated, before an
    endpoint runs. So a 404 or a 422 from one of these is not a cosmetic
    difference: it means the request got PAST the role gate, and the reason it
    changed nothing was the dummy id rather than the auditor's role. Every
    offender is collected and reported together, because the second one is
    worth knowing about while fixing the first.
    """
    add_auditor(fake_db)
    headers = auth_header(fake_db, "audra")
    offenders = []
    for method, path in _unsafe_routes(app):
        concrete = re.sub(
            r"\{([^}]+)\}",
            lambda m: PATH_PARAMETER_DUMMIES.get(
                m.group(1).split(":")[0], DEFAULT_PATH_PARAMETER
            ),
            path,
        )
        response = client.request(method, concrete, headers=headers)
        if response.status_code != 403:
            offenders.append((method, path, response.status_code, response.text[:120]))
    assert not offenders, offenders


def test_auditor_write_refusal_is_403_not_404_and_never_leaks_the_path(
    client, fake_db
):
    """The refusal happens BEFORE routing decides whether the thing exists,
    so an auditor cannot use write attempts to enumerate records."""
    add_auditor(fake_db)
    real = client.post(
        "/dq/issues/does-not-exist/resolve",
        json={"resolution": "x", "note": "y"},
        headers=auth_header(fake_db, "audra"),
    )
    assert real.status_code == 403


def test_auditor_cannot_certify_even_though_it_reads_certifications(client, fake_db):
    """The guardrail that has no bootstrap exception: certifying is
    certifying_official and nothing else, from any authentication path."""
    add_auditor(fake_db)
    mv = fake_db.add_metric_value()
    r = client.post(
        "/certifications",
        json={
            "metric_value_ids": [mv["metric_value_id"]],
            "attestation": "I attest",
            "signer_full_name": "Test Auditor",
            "signer_title": "Auditor",
        },
        headers=auth_header(fake_db, "audra"),
    )
    assert r.status_code == 403
    assert not fake_db.certifications


# ---------------------------------------------------------------------------
# 4. Rider privacy is not an auditor exception
# ---------------------------------------------------------------------------


def test_auditor_does_not_see_withheld_rider_locations(client, fake_db):
    """Migration 0028 withholds demand-response coordinates because a
    paratransit pickup point is a rider's home address, and the mere
    existence of an ADA trip record discloses disability status. Breadth of
    audit does not outrank that."""
    add_auditor(fake_db)
    record = fake_db.add_raw_record(
        connector="headway-dr", payload_ref="raw/dr/2026-06-01/trips.csv"
    )
    headers = auth_header(fake_db, "audra")

    label = client.get(f"/raw/records/{record['record_id']}", headers=headers)
    assert label.status_code == 200
    sensitivity = label.json()["sensitivity"]
    assert sensitivity["classification"] == "rider_location"
    assert sensitivity["preview_allowed"] is False
    assert "cannot open the contents" in sensitivity["refusal"]

    payload = client.get(
        f"/raw/records/{record['record_id']}/payload", headers=headers
    )
    assert payload.status_code == 403
    download = client.get(
        f"/raw/records/{record['record_id']}/download", headers=headers
    )
    assert download.status_code == 403


def test_auditor_does_not_see_unclassified_vendor_exports(client, fake_db):
    """The fail-closed case: a vendor export can be a paratransit booking
    file, so it is withheld from viewer-breadth roles, auditor included."""
    add_auditor(fake_db)
    record = fake_db.add_raw_record(connector="headway-vendor-file")
    r = client.get(
        f"/raw/records/{record['record_id']}/payload",
        headers=auth_header(fake_db, "audra"),
    )
    assert r.status_code == 403


def test_auditor_does_read_ordinary_operational_records(client, fake_db):
    """The role is not crippled: everything not classified as rider-adjacent
    is open to it, exactly as it is to a viewer."""
    add_auditor(fake_db)
    record = fake_db.add_raw_record(connector="headway-gtfs-rt")
    label = client.get(
        f"/raw/records/{record['record_id']}",
        headers=auth_header(fake_db, "audra"),
    )
    assert label.status_code == 200
    assert label.json()["sensitivity"]["preview_allowed"] is True


def test_may_read_sensitivity_is_deny_by_default_for_unknown_roles():
    assert authz.may_read_sensitivity("auditor", "viewer") is True
    assert authz.may_read_sensitivity("auditor", "data_steward") is False
    assert authz.may_read_sensitivity("viewer", "data_steward") is False
    assert authz.may_read_sensitivity("data_steward", "data_steward") is True
    assert authz.may_read_sensitivity("regional_overseer", "viewer") is False


# ---------------------------------------------------------------------------
# 5. The role is grantable locally, and the lockout fail-safe still holds
# ---------------------------------------------------------------------------


def test_an_admin_can_grant_and_revoke_the_auditor_role(client, fake_db):
    created = client.post(
        "/users",
        json={"username": "ext.auditor", "role": "auditor", "password": "abcd1234"},
        headers=auth_header(fake_db, "cora"),
    )
    assert created.status_code == 201
    assert created.json()["role"] == "auditor"
    assert fake_db.users["ext.auditor"]["role"] == "auditor"
    assert any(
        e["action"] == "user_created" and e["detail"]["role"] == "auditor"
        for e in fake_db.audit_events
        for e in [dict(e, detail=_as_dict(e["detail"]))]
    )


def test_demoting_the_last_certifying_official_to_auditor_is_still_refused(
    client, fake_db
):
    """`auditor` is a new way to strip the last admin's powers, so the
    migration-0032 fail-safe has to cover it too."""
    r = client.post(
        "/users/cora/role",
        json={"role": "auditor"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 409
    assert "last active certifying official" in r.json()["detail"]
    assert fake_db.users["cora"]["role"] == "certifying_official"


def _as_dict(detail):
    import json

    return json.loads(detail) if isinstance(detail, str) else detail
