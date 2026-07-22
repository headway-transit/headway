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
    body = {
        "metric_value_ids": [mv_id],
        "attestation": "January figures are correct.",
        # The signing ceremony's typed identity (handoff 0019).
        "signer_full_name": "Cora Integration",
        "signer_title": "Certifying Official",
    }
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
# Demonstration of the bug class (documentation-by-test), pool era. The
# pre-pool demo forced the app's single connection to autocommit=False and
# showed a 200 response whose write no other connection would ever see. That
# exact failure is now closed BY CONSTRUCTION: psycopg_pool's connection()
# context applies `with conn:` semantics on return, so a cleanly finished
# request commits even if the connection was left autocommit=False, and an
# exception mid-request produces an error status, never a 2xx-with-no-row
# (verified against psycopg_pool 3.3.1 source in handoff 0023's CI follow-up).
#
# What the configure-hook fence (_configure_pooled_connection) still governs
# is WHEN a write commits: at write time (fence present) versus at
# connection-return time (fence lost). Deferred commit is a real hazard, not
# a nicety — it breaks store-before-produce ordering (handoff 0006: the
# Kafka produce happens mid-handler, after the row is believed durable), and
# it lets a later failure in the same request silently erase an "already
# done" write. This demo pins all of that at the pool level, using the
# production hook itself for the fenced half.
# ---------------------------------------------------------------------------


def test_demo_autocommit_fence_governs_when_writes_commit(migrated_db, observer):
    from psycopg_pool import ConnectionPool

    import headway_api.db as db_module

    def audit_count(action: str) -> int:
        return count(
            observer,
            "SELECT count(*) FROM audit.events WHERE actor = 'fence.demo' "
            "AND action = %s",
            (action,),
        )

    def insert_event(conn, action: str) -> None:
        conn.execute(
            "INSERT INTO audit.events (actor, action, detail) "
            "VALUES ('fence.demo', %s, '{}')",
            (action,),
        )

    # --- Fence LOST: writes are deferred to connection return. ------------
    unfenced = ConnectionPool(
        migrated_db,
        min_size=1,
        max_size=1,
        configure=lambda conn: None,  # the lost fence
        open=True,
    )
    try:
        with unfenced.connection() as conn:
            insert_event(conn, "unfenced_write")
            # Mid-request (the moment a handler would produce to Kafka or
            # fire a webhook): the row is NOT yet visible to anyone else.
            assert audit_count("unfenced_write") == 0, (
                "Without the fence the write should be externally invisible "
                "until the connection returns to the pool; if it is visible, "
                "this demo no longer models the deferred-commit hazard."
            )
        # Clean return commits — the old 2xx-with-no-row class is closed by
        # construction, the write was delayed, not lost.
        assert audit_count("unfenced_write") == 1

        # But a failure later in the same request erases the whole request's
        # work, including writes the handler believed were already durable:
        with pytest.raises(RuntimeError, match="later failure"):
            with unfenced.connection() as conn:
                insert_event(conn, "unfenced_lost")
                raise RuntimeError("later failure in the same request")
        assert audit_count("unfenced_lost") == 0  # silently rolled back
    finally:
        unfenced.close()

    # --- Fence PRESENT (the production hook): done means done. ------------
    fenced = ConnectionPool(
        migrated_db,
        min_size=1,
        max_size=1,
        configure=db_module._configure_pooled_connection,
        open=True,
    )
    try:
        with fenced.connection() as conn:
            insert_event(conn, "fenced_write")
            # Visible AT WRITE TIME, from a separate connection.
            assert audit_count("fenced_write") == 1
        # And a later failure in the same request cannot un-write it:
        with pytest.raises(RuntimeError, match="later failure"):
            with fenced.connection() as conn:
                insert_event(conn, "fenced_survives")
                raise RuntimeError("later failure in the same request")
        assert audit_count("fenced_survives") == 1
    finally:
        fenced.close()


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


# ---------------------------------------------------------------------------
# THE HONESTY BOUNDARY (handoff 0014 / migration 0024), against the REAL
# database: a persisted OPERATIONS figure cannot reach any certifiable
# path — the CHECK makes the certified-ops state unrepresentable, the
# certify route refuses it, and the public certified endpoint's hard
# WHERE excludes the category.
# ---------------------------------------------------------------------------


def seed_ops_metric_value(observer, *, value="87.50") -> str:
    row = observer.execute(
        "INSERT INTO computed.metric_values "
        "(metric, unit, period_start, period_end, value, calc_name, "
        "calc_version, category) "
        "VALUES ('otp', 'percent', '2026-07-01', '2026-08-01', %s, "
        "'otp_v0', '0.1.0', 'ops') RETURNING metric_value_id",
        (value,),
    ).fetchone()
    return str(row[0])


def test_ops_figure_structurally_excluded_from_certifiable_paths(
    api_client, observer, seed_user
):
    ops_id = seed_ops_metric_value(observer)
    ntd_id = seed_metric_value(observer, metric="vrm", value="111.5")

    # (a) The database itself refuses the certified-ops state — INSERT and
    # UPDATE both violate metric_values_ops_never_certified.
    with pytest.raises(Exception) as excinfo:
        observer.execute(
            "INSERT INTO computed.metric_values "
            "(metric, unit, period_start, period_end, value, calc_name, "
            "calc_version, category, certification_status) "
            "VALUES ('otp', 'percent', '2026-07-01', '2026-08-01', '1', "
            "'otp_v0', '0.1.0', 'ops', 'certified')"
        )
    assert "metric_values_ops_never_certified" in str(excinfo.value)
    with pytest.raises(Exception) as excinfo:
        observer.execute(
            "UPDATE computed.metric_values SET certification_status = "
            "'certified' WHERE metric_value_id = %s",
            (ops_id,),
        )
    assert "metric_values_ops_never_certified" in str(excinfo.value)

    # (b) The certify route refuses the ops id in plain language, before
    # any write.
    seed_user("cora.ops", "certifier-pass-1", "certifying_official")
    headers = login(api_client, "cora.ops", "certifier-pass-1")
    resp = api_client.post(
        "/certifications",
        json={
            "metric_value_ids": [ops_id],
            "attestation": "Attempting to certify an operations metric.",
            "signer_full_name": "Cora Integration",
            "signer_title": "Certifying Official",
        },
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert "operations metrics" in resp.json()["detail"]
    assert (
        count(
            observer,
            "SELECT count(*) FROM cert.certifications "
            "WHERE %s = ANY(metric_value_ids)",
            (ops_id,),
        )
        == 0
    )

    # (c) An open blocking OPS finding never gates NTD certification; the
    # certified NTD figure is served publicly, the ops figure never is.
    observer.execute(
        "INSERT INTO dq.issues (issue_type, severity, title, description, "
        "category) VALUES ('no_observed_passages', 'blocking', "
        "'OTP refused', 'integration-test ops refusal', 'ops')"
    )
    resp = api_client.post(
        "/certifications",
        json={
            "metric_value_ids": [ntd_id],
            "attestation": "January figures are correct.",
            "signer_full_name": "Cora Integration",
            "signer_title": "Certifying Official",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    resp = api_client.get("/public/metrics/certified")
    assert resp.status_code == 200
    served = {row["metric_value_id"] for row in resp.json()}
    assert ntd_id in served
    assert ops_id not in served
    assert all(row["category"] == "ntd" for row in resp.json())

    # (d) The ops figure IS served on the authenticated metrics surface,
    # explicitly categorized so the UI can badge it.
    resp = api_client.get(
        "/metrics/values", params={"category": "ops"}, headers=headers
    )
    assert resp.status_code == 200
    ops_rows = {row["metric_value_id"]: row for row in resp.json()}
    assert ops_rows[ops_id]["category"] == "ops"
    assert ops_rows[ops_id]["value"] == "87.50"
