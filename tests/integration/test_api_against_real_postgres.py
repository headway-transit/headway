"""Integration tests: the Headway API against a REAL PostgreSQL/TimescaleDB.

Standing protection for the 2026-07-10 autocommit bug class (see conftest.py
and services/api/headway_api/db.py): every assertion about persisted state is
made through a SEPARATE psycopg connection (`observer`), never through the
app's own connection — a write that only the app's connection can see is a
failure, exactly the failure mode that shipped 201-with-no-row.

Skips entirely (with a clear reason) unless HEADWAY_IT_ADMIN_URL is set.
"""

from __future__ import annotations

import os
import secrets

import pytest

# tests/integration is not a package (no __init__.py); pytest puts this
# directory on sys.path, so the sibling conftest imports as a plain module.
from conftest import ADMIN_URL_ENV, SKIP_REASON, TEST_SESSION_SECRET, login

pytestmark = pytest.mark.skipif(
    not os.environ.get(ADMIN_URL_ENV, "").strip(), reason=SKIP_REASON
)


# ---------------------------------------------------------------------------
# Seeding helpers — all through the observer (outside-the-app) connection.
# ---------------------------------------------------------------------------


def seed_metric_value(observer, *, metric="vrm", unit="miles", value="1234.5") -> str:
    row = observer.execute(
        "INSERT INTO computed.metric_values "
        "(metric, unit, period_start, period_end, value, calc_name, calc_version) "
        "VALUES (%s, %s, '2026-01-01', '2026-01-31', %s, 'calc_vrm', '0.2.0') "
        "RETURNING metric_value_id",
        (metric, unit, value),
    ).fetchone()
    return str(row[0])


def seed_blocking_issue(observer, *, title="gap in vehicle positions") -> str:
    row = observer.execute(
        "INSERT INTO dq.issues (issue_type, severity, title, description) "
        "VALUES ('gap', 'blocking', %s, 'integration-test blocking issue') "
        "RETURNING issue_id",
        (title,),
    ).fetchone()
    return str(row[0])


def seed_raw_record(observer) -> str:
    record_id = secrets.token_hex(32)  # 64 lowercase hex chars, like SHA-256
    observer.execute(
        "INSERT INTO raw.records (record_id, source, connector, "
        "connector_version, content_type, payload_encoding, fetched_at, "
        "parse_status) VALUES (%s, 'integration-test', 'it-connector', "
        "'0.0.1', 'application/octet-stream', 'object_ref', now(), 'ok')",
        (record_id,),
    )
    return record_id


def count(observer, sql: str, params=()) -> int:
    return observer.execute(sql, params).fetchone()[0]


# ---------------------------------------------------------------------------
# Baseline: seed a user, log in, resolve nothing.
# ---------------------------------------------------------------------------


def test_baseline_login_reads_empty_and_audit_is_visible_outside(
    api_client, observer, seed_user
):
    seed_user("vera.it", "viewer-pass-1", "viewer")
    headers = login(api_client, "vera.it", "viewer-pass-1")

    resp = api_client.get("/metrics/values", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []

    resp = api_client.get("/dq/issues", params={"status": "open"}, headers=headers)
    assert resp.status_code == 200
    assert all(i["owner"] != "vera.it" for i in resp.json())  # resolved nothing

    # The login audit event must be visible from OUTSIDE the app's
    # connection: first teeth of the autocommit regression.
    assert (
        count(
            observer,
            "SELECT count(*) FROM audit.events WHERE actor = %s AND action = 'login'",
            ("vera.it",),
        )
        == 1
    )


# ---------------------------------------------------------------------------
# THE REGRESSION: certify blocked -> resolve -> certify, all state asserted
# through the separate connection. This test MUST fail if
# headway_api/db.py ever loses autocommit=True — the API would still return
# 201, but none of these rows would be visible to the observer.
# ---------------------------------------------------------------------------


def test_certification_flow_persists_visibly_outside_the_app(
    api_client, observer, seed_user
):
    mv_id = seed_metric_value(observer)
    issue_id = seed_blocking_issue(observer)
    seed_user("cora.it", "certifier-pass-1", "certifying_official")
    headers = login(api_client, "cora.it", "certifier-pass-1")

    # 1. Blocking DQ issue open -> certification refused with 409.
    body = {"metric_value_ids": [mv_id], "attestation": "January figures are correct."}
    resp = api_client.post("/certifications", json=body, headers=headers)
    assert resp.status_code == 409, resp.text
    assert "blocking" in resp.json()["detail"]
    # Nothing persisted by the refusal (observer's view):
    assert (
        count(
            observer,
            "SELECT count(*) FROM cert.certifications WHERE %s = ANY(metric_value_ids)",
            (mv_id,),
        )
        == 0
    )
    assert observer.execute(
        "SELECT certification_status FROM computed.metric_values "
        "WHERE metric_value_id = %s",
        (mv_id,),
    ).fetchone() == ("uncertified",)

    # 2. Resolve the blocking issue via the API (certifying_official ranks
    #    above data_steward).
    resp = api_client.post(
        f"/dq/issues/{issue_id}/resolve",
        json={"resolution": "Gap explained: depot Wi-Fi outage, data recovered."},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # 3. Certify -> 201.
    resp = api_client.post("/certifications", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    cert = resp.json()
    cert_id = cert["certification_id"]

    # 4. THE POINT — assert via the SEPARATE connection (the psql-equivalent
    #    that caught the live bug):
    row = observer.execute(
        "SELECT metric_value_ids::text[], certified_by, attestation "
        "FROM cert.certifications WHERE certification_id = %s",
        (cert_id,),
    ).fetchone()
    assert row is not None, (
        "The API returned 201 but the certification row is NOT visible from "
        "a separate connection — the 2026-07-10 uncommitted-transaction bug "
        "is back (headway_api/db.py lifespan must open with autocommit=True)."
    )
    assert row[0] == [mv_id]
    assert row[1] == "cora.it"
    assert row[2] == body["attestation"]

    assert observer.execute(
        "SELECT certification_status FROM computed.metric_values "
        "WHERE metric_value_id = %s",
        (mv_id,),
    ).fetchone() == ("certified",)

    assert (
        count(
            observer,
            "SELECT count(*) FROM audit.events "
            "WHERE action = 'dq_resolve' AND subject_id = %s",
            (issue_id,),
        )
        == 1
    )
    assert (
        count(
            observer,
            "SELECT count(*) FROM audit.events "
            "WHERE action = 'certify' AND subject_id = %s",
            (cert_id,),
        )
        == 1
    )

    # The resolved issue itself, observed externally:
    assert observer.execute(
        "SELECT status FROM dq.issues WHERE issue_id = %s", (issue_id,)
    ).fetchone() == ("resolved",)


# ---------------------------------------------------------------------------
# Demonstration of the bug class (documentation-by-test): force the app's
# connection back to autocommit=False and show that the API reports success
# while a separate connection sees NOTHING. If this test ever flakes, mark it
# xfail — the primary regression is the positive-path test above.
# ---------------------------------------------------------------------------


def test_demo_lost_autocommit_makes_api_writes_invisible_externally(
    migrated_db, observer, seed_user, monkeypatch
):
    import psycopg

    from fastapi.testclient import TestClient

    from headway_api.app import create_app

    seed_user("trap.it", "trap-pass-1", "viewer")

    real_connect = psycopg.connect

    def connect_without_autocommit(conninfo="", **kwargs):
        kwargs["autocommit"] = False  # re-create the pre-fix condition
        return real_connect(conninfo, **kwargs)

    monkeypatch.setenv("HEADWAY_DATABASE_URL", migrated_db)
    monkeypatch.setenv("HEADWAY_SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.setattr(psycopg, "connect", connect_without_autocommit)

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/auth/login", json={"username": "trap.it", "password": "trap-pass-1"}
        )
        # The API believes everything worked...
        assert resp.status_code == 200
        # ...but the login audit event is trapped in a never-committed
        # implicit transaction: invisible to any other connection.
        assert (
            count(
                observer,
                "SELECT count(*) FROM audit.events WHERE actor = %s",
                ("trap.it",),
            )
            == 0
        ), (
            "With autocommit=False the write should be invisible externally; "
            "if it is visible, this demo no longer models the bug class."
        )
    # Connection closed (lifespan shutdown): the implicit transaction rolled
    # back, so the write is gone forever, not merely delayed.
    assert (
        count(
            observer,
            "SELECT count(*) FROM audit.events WHERE actor = %s",
            ("trap.it",),
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Immutability triggers are live in the real database.
# ---------------------------------------------------------------------------


def test_immutability_triggers_reject_update_and_delete(migrated_db, observer):
    import psycopg

    record_id = seed_raw_record(observer)
    observer.execute(
        "INSERT INTO audit.events (actor, action, detail) "
        "VALUES ('it-test', 'it_probe', '{}')"
    )

    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        observer.execute(
            "UPDATE raw.records SET source = 'tampered' WHERE record_id = %s",
            (record_id,),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        observer.execute(
            "DELETE FROM raw.records WHERE record_id = %s", (record_id,)
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        observer.execute(
            "UPDATE audit.events SET actor = 'rewritten' WHERE action = 'it_probe'"
        )

    # The rejected statements changed nothing.
    assert observer.execute(
        "SELECT source FROM raw.records WHERE record_id = %s", (record_id,)
    ).fetchone() == ("integration-test",)
    assert (
        count(
            observer,
            "SELECT count(*) FROM audit.events WHERE actor = 'rewritten'",
        )
        == 0
    )


# ---------------------------------------------------------------------------
# "Explain this number": lineage traversal over really-seeded edges.
# ---------------------------------------------------------------------------


def test_lineage_endpoint_returns_seeded_provenance_tree(
    api_client, observer, seed_user
):
    mv_id = seed_metric_value(observer, metric="vrh", unit="hours", value="87.25")
    raw_1 = seed_raw_record(observer)
    raw_2 = seed_raw_record(observer)
    canonical_id = f"vp-batch-{secrets.token_hex(4)}"

    edges = [
        ("computed.metric_values", mv_id, "calc_vrh", "0.2.0",
         "canonical.vehicle_positions", canonical_id),
        ("canonical.vehicle_positions", canonical_id, "transform_vp", "1.0.0",
         "raw.records", raw_1),
        ("canonical.vehicle_positions", canonical_id, "transform_vp", "1.0.0",
         "raw.records", raw_2),
    ]
    for edge in edges:
        observer.execute(
            "INSERT INTO lineage.edges (output_kind, output_id, transform_name, "
            "transform_version, input_kind, input_id) VALUES (%s, %s, %s, %s, %s, %s)",
            edge,
        )

    seed_user("lena.it", "lineage-pass-1", "viewer")
    headers = login(api_client, "lena.it", "lineage-pass-1")

    resp = api_client.get(f"/metrics/values/{mv_id}/lineage", headers=headers)
    assert resp.status_code == 200, resp.text
    tree = resp.json()

    assert tree["kind"] == "computed.metric_values"
    assert tree["id"] == mv_id
    assert tree["transform_name"] == "calc_vrh"
    assert tree["transform_version"] == "0.2.0"
    assert len(tree["inputs"]) == 1

    canonical = tree["inputs"][0]
    assert canonical["kind"] == "canonical.vehicle_positions"
    assert canonical["id"] == canonical_id
    assert canonical["transform_name"] == "transform_vp"

    leaves = sorted(canonical["inputs"], key=lambda n: n["id"])
    assert [n["id"] for n in leaves] == sorted([raw_1, raw_2])
    for leaf in leaves:
        assert leaf["kind"] == "raw.records"
        assert leaf["transform_name"] is None  # raw records are leaves
        assert leaf["inputs"] == []

    # And the seeded metric value itself is served (value as exact string).
    resp = api_client.get("/metrics/values", params={"metric": "vrh"}, headers=headers)
    assert resp.status_code == 200
    values = {v["metric_value_id"]: v for v in resp.json()}
    assert values[mv_id]["value"] == "87.25"
    assert values[mv_id]["unit"] == "hours"
