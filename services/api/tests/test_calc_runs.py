"""Calc runs dispatched from the UI (handoff 0026 / migration 0033).

Covers: the authz matrix (POST is data_steward OR ABOVE — the recorded
decision includes report_preparer; reads are any signed-in role), period
validation, the single-flight 409 that names the live run, the staleness
reconcile + presentation, the refused-vs-failed status mapping (refusal is
first-class), audit rows, and the execute_run lifecycle driven synchronously
with a fake subprocess.
"""

from __future__ import annotations

import datetime as dt
import json

from conftest import auth_header

from headway_api.routers import calc_runs as cr

UTC = dt.timezone.utc

PERIOD = {"period_start": "2026-06-01", "period_end": "2026-07-01"}


def _report(metrics, **overrides):
    """A minimal-but-faithful RunReport.to_dict() shape (headway_calc.runner)."""
    persisted = sum(1 for m in metrics if m.get("persisted"))
    blocked = len(metrics) - persisted
    report = {
        "period_start": "2026-06-01",
        "period_end": "2026-07-01",
        "period_convention": "half-open [period_start, period_end), UTC",
        "gap_threshold_seconds": 300.0,
        "coverage_threshold": "0.95",
        "layover_max_seconds": 1800.0,
        "missing_trip_threshold": "0.02",
        "imbalance_threshold": "0.10",
        "threshold_sources": {"coverage_threshold": "settings"},
        "positions_loaded": 120000,
        "passenger_events_loaded": 0,
        "operated_trips_loaded": 4200,
        "stop_times_loaded": 0,
        "dr_trips_loaded": 0,
        "attestations_loaded": 0,
        "per_mode": False,
        "run_info_ids": [],
        "persisted_count": persisted,
        "blocked_count": blocked,
        "routed_issue_count": 0,
        "routed_blocking_count": sum(
            len(m.get("routed_blocking_ids", [])) for m in metrics
        ),
        "routed_warning_count": 0,
        "routed_info_count": 0,
        "metrics": metrics,
    }
    report.update(overrides)
    return report


def _metric(persisted=True, **overrides):
    m = {
        "calc_name": "vrm_v0",
        "calc_version": "0.2.0",
        "metric": "vrm",
        "unit": "miles",
        "scope": "agency",
        "value": "1234.567" if persisted else None,
        "metric_value_id": "mv-1" if persisted else None,
        "persisted": persisted,
        "coverage": "0.97" if persisted else "0.91",
        "detail": {"coverage": "0.97"},
        "routed_blocking_ids": [] if persisted else ["dq-1", "dq-2"],
        "routed_warning_ids": [],
        "routed_info_ids": [],
        "blocking_issue_count": 0 if persisted else 2,
        "warning_count": 0,
        "info_count": 0,
    }
    m.update(overrides)
    return m


# ------------------------------------------------------------- authz matrix


def test_viewer_cannot_start_a_run(client, fake_db, fake_calc_launcher):
    r = client.post(
        "/calc/runs", json=PERIOD, headers=auth_header(fake_db, "vera")
    )
    assert r.status_code == 403
    assert "data steward" in r.json()["detail"]
    assert fake_db.calc_runs == {}
    assert fake_calc_launcher.launched == []
    assert not any(
        e["action"] == "calc_run_requested" for e in fake_db.audit_events
    )


def test_steward_starts_a_run_audited_and_launched(
    client, fake_db, fake_calc_launcher
):
    r = client.post(
        "/calc/runs", json=PERIOD, headers=auth_header(fake_db, "stella")
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["requested_by"] == "stella"
    assert body["period_start"] == "2026-06-01"
    assert body["period_end"] == "2026-07-01"
    # The row is durable and queued.
    run = fake_db.calc_runs[body["run_id"]]
    assert run["status"] == "queued"
    # Audited in the same transaction (calc_run_requested).
    events = [
        e for e in fake_db.audit_events if e["action"] == "calc_run_requested"
    ]
    assert len(events) == 1
    assert events[0]["actor"] == "stella"
    assert events[0]["subject_id"] == body["run_id"]
    detail = json.loads(events[0]["detail"])
    assert detail["period_start"] == "2026-06-01"
    assert body["audit_event_id"] == events[0]["event_id"]
    # The background launcher got exactly this run.
    assert fake_calc_launcher.launched == [
        (body["run_id"], dt.date(2026, 6, 1), dt.date(2026, 7, 1))
    ]


def test_report_preparer_may_start_a_run_recorded_decision(client, fake_db):
    """Handoff 0026: report_preparer is included via the documented
    escalating hierarchy — computing figures is stewardship, and the
    separation-of-duties wall applies to certifying, not computing."""
    r = client.post(
        "/calc/runs", json=PERIOD, headers=auth_header(fake_db, "petra")
    )
    assert r.status_code == 202


def test_certifying_official_may_start_a_run(client, fake_db):
    r = client.post(
        "/calc/runs", json=PERIOD, headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 202


def test_unauthenticated_is_rejected(client, fake_db):
    assert client.post("/calc/runs", json=PERIOD).status_code == 401
    assert client.get("/calc/runs").status_code == 401
    fake_db.add_calc_run()
    run_id = next(iter(fake_db.calc_runs))
    assert client.get(f"/calc/runs/{run_id}").status_code == 401


def test_any_signed_in_role_reads_runs(client, fake_db):
    run = fake_db.add_calc_run()
    r = client.get("/calc/runs", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    assert [row["run_id"] for row in r.json()] == [run["run_id"]]
    one = client.get(
        f"/calc/runs/{run['run_id']}", headers=auth_header(fake_db, "vera")
    )
    assert one.status_code == 200
    assert one.json()["requested_by"] == "stella"


# --------------------------------------------------------------- validation


def test_period_start_must_precede_end(client, fake_db):
    r = client.post(
        "/calc/runs",
        json={"period_start": "2026-07-01", "period_end": "2026-06-01"},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 422
    messages = " ".join(item["msg"] for item in r.json()["detail"])
    assert "start date is included, the end date is not" in messages
    assert fake_db.calc_runs == {}


def test_window_bounded_to_one_year(client, fake_db):
    r = client.post(
        "/calc/runs",
        json={"period_start": "2025-01-01", "period_end": "2026-06-01"},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 422
    messages = " ".join(item["msg"] for item in r.json()["detail"])
    assert "longer than one year" in messages


def test_malformed_date_is_422(client, fake_db):
    r = client.post(
        "/calc/runs",
        json={"period_start": "June 2026", "period_end": "2026-07-01"},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 422


# ------------------------------------------------------------- single-flight


def test_second_post_while_queued_409_names_the_live_run(
    client, fake_db, fake_calc_launcher
):
    first = client.post(
        "/calc/runs", json=PERIOD, headers=auth_header(fake_db, "stella")
    )
    assert first.status_code == 202
    second = client.post(
        "/calc/runs",
        json={"period_start": "2026-05-01", "period_end": "2026-06-01"},
        headers=auth_header(fake_db, "cora"),
    )
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert first.json()["run_id"] in detail
    assert "stella" in detail
    assert "queued since" in detail
    assert "one calculation at a time" in detail
    # Only the first run exists; only one launch happened.
    assert len(fake_db.calc_runs) == 1
    assert len(fake_calc_launcher.launched) == 1


def test_second_post_while_running_409_says_running_since(client, fake_db):
    started = dt.datetime.now(UTC) - dt.timedelta(minutes=5)
    fake_db.add_calc_run(status="running", started_at=started)
    r = client.post(
        "/calc/runs", json=PERIOD, headers=auth_header(fake_db, "stella")
    )
    assert r.status_code == 409
    assert (
        f"running since {started.strftime('%H:%M:%S')} UTC"
        in r.json()["detail"]
    )


def test_insert_conflict_race_is_a_409(client, fake_db, monkeypatch):
    """The lost-race path: the live-run SELECT sees nothing, but the INSERT
    hits the partial unique index (ON CONFLICT DO NOTHING → no row)."""
    real_execute = fake_db.execute
    calls = {"n": 0}

    def execute(sql, params=None):
        q = " ".join(sql.split())
        if (
            q.startswith("SELECT run_id, requested_by")
            and "WHERE status IN ('queued', 'running')" in q
        ):
            calls["n"] += 1
            if calls["n"] == 1:
                # The pre-insert check races: the rival's row is not yet
                # visible to this SELECT, but IS there when the INSERT hits
                # the partial unique index.
                from conftest import FakeCursor

                fake_db.add_calc_run(requested_by="petra")
                return FakeCursor([])
        return real_execute(sql, params)

    monkeypatch.setattr(fake_db, "execute", execute)
    r = client.post(
        "/calc/runs", json=PERIOD, headers=auth_header(fake_db, "stella")
    )
    assert r.status_code == 409
    assert "petra" in r.json()["detail"]


def test_stale_live_run_is_reconciled_and_does_not_block(
    client, fake_db, fake_calc_launcher
):
    stale = fake_db.add_calc_run(
        status="running",
        requested_at=dt.datetime.now(UTC) - dt.timedelta(hours=4),
        started_at=dt.datetime.now(UTC) - dt.timedelta(hours=4),
    )
    r = client.post(
        "/calc/runs", json=PERIOD, headers=auth_header(fake_db, "stella")
    )
    assert r.status_code == 202
    # The dead run was reconciled honestly: failed, staleness recorded.
    assert fake_db.calc_runs[stale["run_id"]]["status"] == "failed"
    assert fake_db.calc_runs[stale["run_id"]]["summary"]["stale"] is True
    assert "never reported finishing" in (
        fake_db.calc_runs[stale["run_id"]]["summary"]["error"]
    )
    # Audited (calc_run_marked_stale) alongside the new request's audit row.
    actions = [e["action"] for e in fake_db.audit_events]
    assert "calc_run_marked_stale" in actions
    assert "calc_run_requested" in actions
    # And the new run launched.
    assert len(fake_calc_launcher.launched) == 1


def test_stale_running_row_presents_as_stale_on_read(client, fake_db):
    fake_db.add_calc_run(
        status="running",
        started_at=dt.datetime.now(UTC) - dt.timedelta(hours=3),
    )
    fresh = fake_db.add_calc_run(
        status="succeeded",
        requested_at=dt.datetime.now(UTC) - dt.timedelta(minutes=10),
        started_at=dt.datetime.now(UTC) - dt.timedelta(minutes=9),
        finished_at=dt.datetime.now(UTC) - dt.timedelta(minutes=5),
        summary={"persisted_count": 1, "blocked_count": 0, "metrics": []},
    )
    rows = client.get(
        "/calc/runs", headers=auth_header(fake_db, "vera")
    ).json()
    by_status = {r["status"]: r for r in rows}
    assert by_status["running"]["stale"] is True
    assert "state is unknown" in by_status["running"]["stale_note"]
    assert by_status["succeeded"]["stale"] is False
    assert by_status["succeeded"]["stale_note"] is None
    # Duration is the timestamps' difference (4 minutes), never invented.
    assert by_status["succeeded"]["run_id"] == fresh["run_id"]
    assert abs(by_status["succeeded"]["duration_seconds"] - 240) < 5


# ------------------------------------------------- list/detail presentation


def test_list_is_newest_first_and_bounded(client, fake_db):
    old = fake_db.add_calc_run(
        status="succeeded",
        requested_at=dt.datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
        started_at=dt.datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
        finished_at=dt.datetime(2026, 7, 1, 9, 2, tzinfo=UTC),
        summary={"persisted_count": 4, "blocked_count": 0, "metrics": []},
    )
    new = fake_db.add_calc_run(
        status="refused",
        requested_at=dt.datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
        started_at=dt.datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
        finished_at=dt.datetime(2026, 7, 20, 9, 3, tzinfo=UTC),
        summary={"persisted_count": 0, "blocked_count": 4, "metrics": []},
    )
    rows = client.get(
        "/calc/runs", headers=auth_header(fake_db, "vera")
    ).json()
    assert [r["run_id"] for r in rows] == [new["run_id"], old["run_id"]]
    limited = client.get(
        "/calc/runs?limit=1", headers=auth_header(fake_db, "vera")
    ).json()
    assert [r["run_id"] for r in limited] == [new["run_id"]]


def test_unknown_and_malformed_run_ids_are_404(client, fake_db):
    r = client.get(
        "/calc/runs/00000000-0000-0000-0000-000000000000",
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 404
    r = client.get(
        "/calc/runs/not-a-uuid", headers=auth_header(fake_db, "vera")
    )
    assert r.status_code == 404
    assert "No calculation run with that id" in r.json()["detail"]


# ------------------------------------- status mapping + summary (pure units)


def test_classify_all_refused_is_refused_not_failed():
    summary = cr.summarize_report(
        _report([_metric(persisted=False) for _ in range(4)])
    )
    assert cr.classify_status(summary) == "refused"


def test_classify_any_persisted_is_succeeded():
    summary = cr.summarize_report(
        _report([_metric(), _metric(persisted=False)])
    )
    assert cr.classify_status(summary) == "succeeded"


def test_summary_is_verbatim_and_links_blocking_issues():
    report = _report(
        [
            _metric(),
            _metric(
                persisted=False,
                calc_name="vrh_v0",
                calc_version="0.4.0",
                metric="vrh",
                unit="hours",
                routed_blocking_ids=["issue-a"],
            ),
        ]
    )
    summary = cr.summarize_report(report)
    assert summary["persisted_count"] == 1
    assert summary["blocked_count"] == 1
    assert summary["coverage_threshold"] == "0.95"
    persisted, refused = summary["metrics"]
    assert persisted["outcome"] == "persisted"
    assert persisted["value"] == "1234.567"  # the runner's string, verbatim
    assert persisted["metric_value_id"] == "mv-1"
    assert refused["outcome"] == "refused"
    assert refused["value"] is None
    assert refused["blocking_issue_ids"] == ["issue-a"]


def test_bounded_tail_clips_and_labels():
    tail = cr.bounded_tail("x" * 20_000, "e" * 10_000)
    assert len(tail) < cr.STDOUT_TAIL_CHARS + cr.STDERR_TAIL_CHARS + 200
    assert "--- stdout (tail) ---" in tail
    assert "--- stderr (tail) ---" in tail
    assert "[...clipped...]" in tail
    assert cr.bounded_tail("short", "") == "--- stdout (tail) ---\nshort"


# ----------------------------------------------- execute_run lifecycle (fake)


def _run_lifecycle(fake_db, run, exit_code, stdout, stderr="", pid=4242):
    def spawn(argv):
        # The dispatcher invokes the CLI default set: no extra flags.
        assert argv[1:] == [
            "-m",
            "headway_calc.runner",
            "--period-start",
            run["period_start"].isoformat(),
            "--period-end",
            run["period_end"].isoformat(),
        ]
        return pid, lambda: (exit_code, stdout, stderr)

    cr.execute_run(
        run["run_id"],
        run["period_start"],
        run["period_end"],
        connect=lambda: fake_db,
        spawn=spawn,
    )
    return fake_db.calc_runs[run["run_id"]]


def test_execute_run_success(fake_db):
    run = fake_db.add_calc_run()
    report = _report([_metric() for _ in range(4)])
    row = _run_lifecycle(fake_db, run, 0, json.dumps(report))
    assert row["status"] == "succeeded"
    assert row["runner_pid"] == 4242
    assert row["started_at"] is not None
    assert row["finished_at"] is not None
    assert row["summary"]["persisted_count"] == 4
    assert "--- stdout (tail) ---" in row["stdout_tail"]


def test_execute_run_all_refused_is_refused(fake_db):
    run = fake_db.add_calc_run()
    report = _report([_metric(persisted=False) for _ in range(4)])
    row = _run_lifecycle(fake_db, run, 0, json.dumps(report))
    assert row["status"] == "refused"
    assert row["summary"]["blocked_count"] == 4
    assert row["summary"]["metrics"][0]["blocking_issue_ids"] == [
        "dq-1",
        "dq-2",
    ]


def test_execute_run_nonzero_exit_is_failed_with_tail(fake_db):
    run = fake_db.add_calc_run()
    row = _run_lifecycle(
        fake_db, run, 3, "", "Traceback (most recent call last): boom"
    )
    assert row["status"] == "failed"
    assert "exit code 3" in row["summary"]["error"]
    assert "boom" in row["stdout_tail"]


def test_execute_run_unreadable_report_is_failed(fake_db):
    run = fake_db.add_calc_run()
    row = _run_lifecycle(fake_db, run, 0, "this is not json")
    assert row["status"] == "failed"
    assert "could not be read" in row["summary"]["error"]


def test_execute_run_spawn_failure_is_failed(fake_db):
    run = fake_db.add_calc_run()

    def spawn(argv):
        raise OSError("no such interpreter")

    cr.execute_run(
        run["run_id"],
        run["period_start"],
        run["period_end"],
        connect=lambda: fake_db,
        spawn=spawn,
    )
    row = fake_db.calc_runs[run["run_id"]]
    assert row["status"] == "failed"
    assert "could not be started" in row["summary"]["error"]
