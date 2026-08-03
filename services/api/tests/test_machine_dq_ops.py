"""Machine reads of the data-quality queue and the operations surface
(handoff 0039): the read:dq / read:ops consumers.

The precedent is test_machine_read.py (GET /machine/metrics, read:metrics).
Pinned here per design points 2, 3, 6:

- scope grant serves the SAME rows/shape as the human endpoint (mirror, not
  fork) — byte-identical response for the same data;
- deny-by-default: a key without the scope is a 403, audited, no-leak; a
  revoked key is a 401, audited; a human session token is a 401 (credential
  separation); read:dq does not imply read:ops and neither implies
  read:metrics;
- every successful read is audited with actor key:<prefix>;
- the per-key rate limit applies;
- the ops response keeps its `truncated` field and staleness note;
- sensitivity does not relax — source_record_ids stays OFF the machine list
  and rides only on the per-issue detail, exactly as for the human surface.
"""

import datetime as dt
import json

import pytest

from conftest import auth_header, machine_header

from headway_api.machine_auth import RateLimiter


@pytest.fixture
def dq_key(fake_db):
    _, full_key = fake_db.add_api_key(
        name="dq reader", scopes=("read:dq",), source_label=None
    )
    return full_key


@pytest.fixture
def ops_key(fake_db):
    _, full_key = fake_db.add_api_key(
        name="ops reader", scopes=("read:ops",), source_label=None
    )
    return full_key


# ---------------------------------------------------------------------------
# read:dq — list / counts / detail mirror the human endpoints verbatim
# ---------------------------------------------------------------------------


def test_dq_list_matches_the_human_endpoint_byte_for_byte(client, fake_db, dq_key):
    fake_db.add_dq_issue(
        severity="blocking", status="open", title="Coverage below threshold"
    )
    fake_db.add_dq_issue(severity="warning", status="owned")
    machine = client.get("/machine/dq/issues", headers=machine_header(dq_key))
    human = client.get("/dq/issues", headers=auth_header(fake_db, "vera"))
    assert machine.status_code == 200
    assert machine.json() == human.json()


def test_dq_list_does_not_leak_source_record_ids(client, fake_db, dq_key):
    # Sensitivity/provenance boundary (handoff 0030): the list row NEVER
    # carries source_record_ids, machine or human — it lives on the detail
    # endpoint only. A machine key does not change that.
    fake_db.add_dq_issue(source_record_ids=["rec-a", "rec-b"])
    r = client.get("/machine/dq/issues", headers=machine_header(dq_key))
    (row,) = r.json()["issues"]
    assert "source_record_ids" not in row


def test_dq_list_keyset_pagination_and_total(client, fake_db, dq_key):
    base = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)
    for i in range(3):
        fake_db.add_dq_issue(created_at=base + dt.timedelta(minutes=i))
    first = client.get(
        "/machine/dq/issues", params={"limit": 2}, headers=machine_header(dq_key)
    ).json()
    assert first["total"] == 3
    assert first["has_more"] is True
    assert len(first["issues"]) == 2
    second = client.get(
        "/machine/dq/issues",
        params={"limit": 2, "cursor": first["next_cursor"]},
        headers=machine_header(dq_key),
    ).json()
    assert len(second["issues"]) == 1
    assert second["has_more"] is False


def test_dq_list_bad_filter_is_422(client, dq_key):
    r = client.get(
        "/machine/dq/issues",
        params={"severity": "catastrophic"},
        headers=machine_header(dq_key),
    )
    assert r.status_code == 422
    assert "severity" in r.json()["detail"]


def test_dq_counts_matches_the_human_endpoint(client, fake_db, dq_key):
    fake_db.add_dq_issue(severity="blocking", status="open")
    fake_db.add_dq_issue(severity="warning", status="open")
    fake_db.add_dq_issue(severity="info", status="resolved")
    machine = client.get(
        "/machine/dq/issues/counts", headers=machine_header(dq_key)
    )
    human = client.get(
        "/dq/issues/counts", headers=auth_header(fake_db, "vera")
    )
    assert machine.status_code == 200
    assert machine.json() == human.json()
    assert machine.json()["total"] == 3


def test_dq_detail_serves_full_provenance_like_the_human_endpoint(
    client, fake_db, dq_key
):
    issue = fake_db.add_dq_issue(source_record_ids=["rec-1", "rec-2", "rec-3"])
    machine = client.get(
        f"/machine/dq/issues/{issue['issue_id']}", headers=machine_header(dq_key)
    )
    human = client.get(
        f"/dq/issues/{issue['issue_id']}", headers=auth_header(fake_db, "vera")
    )
    assert machine.status_code == 200
    assert machine.json() == human.json()
    # The complete, untruncated provenance array is HERE (and only here).
    assert machine.json()["source_record_ids"] == ["rec-1", "rec-2", "rec-3"]


def test_dq_detail_unknown_id_is_404(client, dq_key):
    r = client.get(
        "/machine/dq/issues/not-a-uuid", headers=machine_header(dq_key)
    )
    assert r.status_code == 404


def test_dq_blocking_for_period_is_the_queue_filtered(client, fake_db, dq_key):
    # "What's blocking my July figures?" — the blocking DQ queue, filtered to
    # blocking+open, is the machine-readable answer (handoff 0039 design
    # point 4: the calc-runs refusal story is these findings).
    fake_db.add_dq_issue(severity="blocking", status="open", title="APC gap")
    fake_db.add_dq_issue(severity="warning", status="open")
    r = client.get(
        "/machine/dq/issues",
        params={"severity": "blocking", "status": "open"},
        headers=machine_header(dq_key),
    )
    assert r.status_code == 200
    (row,) = r.json()["issues"]
    assert row["severity"] == "blocking"
    assert row["title"] == "APC gap"


# ---------------------------------------------------------------------------
# read:ops — the live vehicle snapshot mirrors the human endpoint verbatim
# ---------------------------------------------------------------------------


def test_ops_vehicles_matches_the_human_endpoint(client, fake_db, ops_key):
    fake_db.add_vehicle_position(vehicle_id="bus-1")
    fake_db.add_vehicle_position(vehicle_id="bus-2")
    machine = client.get(
        "/machine/ops/vehicles/latest", headers=machine_header(ops_key)
    )
    human = client.get(
        "/ops/vehicles/latest", headers=auth_header(fake_db, "vera")
    )
    assert machine.status_code == 200
    # as_of is the database clock at query time (differs between two calls);
    # everything else is the same snapshot. Compare with as_of/age normalized.
    def _norm(body):
        body = dict(body)
        body.pop("as_of")
        for v in body["vehicles"]:
            v.pop("age_seconds")
        return body

    assert _norm(machine.json()) == _norm(human.json())


def test_ops_response_keeps_the_truncated_field_and_note(client, fake_db, ops_key):
    fake_db.add_vehicle_position(vehicle_id="bus-1")
    r = client.get(
        "/machine/ops/vehicles/latest", headers=machine_header(ops_key)
    )
    body = r.json()
    # The `truncated` field is load-bearing count honesty — it MUST be present
    # on the machine response exactly as on the human one.
    assert body["truncated"] is False
    assert body["category"] == "ops"
    assert "ops_note" in body


def test_ops_stale_feed_gets_the_staleness_note_never_empty_fleet(
    client, fake_db, ops_key
):
    # A position outside the window: the response is an explained staleness
    # state, never a silent empty fleet (fail-loudly, handoff 0023).
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    fake_db.add_vehicle_position(vehicle_id="bus-1", time=old)
    r = client.get(
        "/machine/ops/vehicles/latest",
        params={"max_age_seconds": 60},
        headers=machine_header(ops_key),
    )
    body = r.json()
    assert body["vehicles"] == []
    assert body["newest_position_at"] is not None
    assert "stale" in body["note"]


# ---------------------------------------------------------------------------
# deny-by-default: scope grant/deny, generic 401, credential separation
# ---------------------------------------------------------------------------


def test_dq_scope_does_not_grant_ops(client, fake_db, dq_key):
    fake_db.add_vehicle_position()
    r = client.get(
        "/machine/ops/vehicles/latest", headers=machine_header(dq_key)
    )
    assert r.status_code == 403
    assert "read:ops" in r.json()["detail"]
    events = [
        e for e in fake_db.audit_events if e["action"] == "machine_scope_denied"
    ]
    assert len(events) == 1
    assert events[0]["actor"].startswith("key:hwk_")
    assert json.loads(events[0]["detail"])["required_scope"] == "read:ops"


def test_repeated_scope_denials_coalesce_to_one_audit_row(client, fake_db, dq_key):
    """F1 (external adversarial review): rejected requests never reach the
    in-body rate limiter, yet each auth/scope failure writes to audit.events —
    a write-amplification DoS. A flood of identical out-of-scope calls from one
    client must still return 403 every time but write the audit row ONCE."""
    fake_db.add_vehicle_position()
    for _ in range(6):
        r = client.get(
            "/machine/ops/vehicles/latest", headers=machine_header(dq_key)
        )
        assert r.status_code == 403  # never suppressed to the caller
    events = [
        e for e in fake_db.audit_events if e["action"] == "machine_scope_denied"
    ]
    assert len(events) == 1  # six failures, one audit write


def test_failure_audit_throttle_coalesces_counts_and_bounds_memory():
    """Unit-level: the throttle records the first failure per (bucket, reason)
    per window, suppresses the rest, folds the suppressed count into the next
    recorded event, keeps distinct buckets independent, and bounds memory."""
    from headway_api.machine_auth import FailureAuditThrottle

    now = [1000.0]
    t = FailureAuditThrottle(window_seconds=60.0, clock=lambda: now[0])
    assert t.on_failure("1.2.3.4", "unknown_key") == 0  # first: recorded
    assert t.on_failure("1.2.3.4", "unknown_key") is None  # suppressed
    assert t.on_failure("1.2.3.4", "unknown_key") is None  # suppressed
    assert t.on_failure("1.2.3.4", "revoked_key") == 0  # different reason
    assert t.on_failure("5.6.7.8", "unknown_key") == 0  # different IP
    now[0] += 61.0  # window rolls over
    assert t.on_failure("1.2.3.4", "unknown_key") == 2  # 2 were suppressed

    bounded = FailureAuditThrottle(window_seconds=60.0, max_buckets=8, clock=lambda: 0.0)
    for i in range(100):
        bounded.on_failure(f"ip-{i}", "unknown_key")
    assert len(bounded._last) <= 8


def test_ops_scope_does_not_grant_dq(client, fake_db, ops_key):
    r = client.get("/machine/dq/issues", headers=machine_header(ops_key))
    assert r.status_code == 403
    assert "read:dq" in r.json()["detail"]


def test_read_metrics_key_does_not_grant_dq_or_ops(client, fake_db):
    _, metrics_key = fake_db.add_api_key(
        name="metrics only", scopes=("read:metrics",), source_label=None
    )
    assert (
        client.get(
            "/machine/dq/issues", headers=machine_header(metrics_key)
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/machine/ops/vehicles/latest", headers=machine_header(metrics_key)
        ).status_code
        == 403
    )


def test_ingest_key_is_403_on_dq_and_audited(client, fake_db):
    _, ingest_key = fake_db.add_api_key(
        name="simulator", scopes=("ingest:tides",), source_label="tides_simulated"
    )
    r = client.get("/machine/dq/issues", headers=machine_header(ingest_key))
    assert r.status_code == 403
    assert "read:dq" in r.json()["detail"]


def test_revoked_dq_key_is_401_and_audited(client, fake_db):
    _, revoked = fake_db.add_api_key(
        name="old dq reader", scopes=("read:dq",), revoked=True
    )
    r = client.get("/machine/dq/issues", headers=machine_header(revoked))
    assert r.status_code == 401
    assert "revoked" in r.json()["detail"]
    events = [
        e for e in fake_db.audit_events if e["action"] == "machine_auth_failed"
    ]
    assert len(events) == 1
    assert json.loads(events[0]["detail"])["reason"] == "key revoked"


def test_human_session_token_is_401_on_machine_dq(client, fake_db):
    r = client.get("/machine/dq/issues", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 401
    assert "machine API key" in r.json()["detail"]


def test_human_session_token_is_401_on_machine_ops(client, fake_db):
    r = client.get(
        "/machine/ops/vehicles/latest", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 401
    assert "machine API key" in r.json()["detail"]


# ---------------------------------------------------------------------------
# every successful read is audited with actor key:<prefix>
# ---------------------------------------------------------------------------


def test_successful_dq_list_is_audited(client, fake_db, dq_key):
    fake_db.add_dq_issue()
    client.get(
        "/machine/dq/issues", params={"status": "open"}, headers=machine_header(dq_key)
    )
    events = [
        e for e in fake_db.audit_events if e["action"] == "machine_read_dq_issues"
    ]
    assert len(events) == 1
    assert events[0]["actor"].startswith("key:hwk_")
    detail = json.loads(events[0]["detail"])
    assert detail["filters"]["status"] == "open"
    assert detail["rows"] == 1


def test_successful_dq_counts_is_audited(client, fake_db, dq_key):
    fake_db.add_dq_issue()
    client.get("/machine/dq/issues/counts", headers=machine_header(dq_key))
    events = [
        e for e in fake_db.audit_events if e["action"] == "machine_read_dq_counts"
    ]
    assert len(events) == 1
    assert events[0]["actor"].startswith("key:hwk_")


def test_successful_dq_detail_is_audited_with_the_issue_id(client, fake_db, dq_key):
    issue = fake_db.add_dq_issue()
    client.get(
        f"/machine/dq/issues/{issue['issue_id']}", headers=machine_header(dq_key)
    )
    events = [
        e for e in fake_db.audit_events if e["action"] == "machine_read_dq_issue"
    ]
    assert len(events) == 1
    assert events[0]["subject_id"] == issue["issue_id"]


def test_successful_ops_read_is_audited(client, fake_db, ops_key):
    fake_db.add_vehicle_position()
    client.get("/machine/ops/vehicles/latest", headers=machine_header(ops_key))
    events = [
        e for e in fake_db.audit_events if e["action"] == "machine_read_ops_vehicles"
    ]
    assert len(events) == 1
    assert events[0]["actor"].startswith("key:hwk_")
    assert json.loads(events[0]["detail"])["truncated"] is False


# ---------------------------------------------------------------------------
# per-key rate limit
# ---------------------------------------------------------------------------


def test_dq_read_is_rate_limited_per_key(client, app, fake_db, dq_key):
    app.state.machine_rate_limiter = RateLimiter(requests_per_minute=1)
    headers = machine_header(dq_key)
    assert client.get("/machine/dq/issues", headers=headers).status_code == 200
    r = client.get("/machine/dq/issues", headers=headers)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


def test_ops_read_is_rate_limited_per_key(client, app, fake_db, ops_key):
    app.state.machine_rate_limiter = RateLimiter(requests_per_minute=1)
    headers = machine_header(ops_key)
    assert (
        client.get("/machine/ops/vehicles/latest", headers=headers).status_code
        == 200
    )
    r = client.get("/machine/ops/vehicles/latest", headers=headers)
    assert r.status_code == 429
