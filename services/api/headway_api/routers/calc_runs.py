"""Calculation runs dispatched from the UI (handoff 0026).

First-agency UAT surfaced that the only way to compute figures was a
developer-shaped CLI line — and an agency compose install has no host Python
at all (the calc wheel ships inside the api image). Computing figures is a
role-gated, audited, DB-scoped application action inside the platform's own
trust boundary, so this router dispatches the SAME deterministic runner the
CLI runs::

    python -m headway_calc.runner --period-start <start> --period-end <end>

as a **subprocess of the api process** (same interpreter, same environment —
the wheel is bundled), records the run in ``computed.calc_runs`` (migration
0033), and serves the runner's own report verbatim. THE API IS A DISPATCHER:
no calculation logic, no new knobs, figures verbatim — the default run is the
CLI's default calc set exactly (vrm/vrh/upt/pmt + the DR calcs whenever the
period holds dr_trips), and every number in a run summary is the runner's own
string.

Honest outcomes are FIRST-CLASS (handoff 0026 design 2): a run whose
calculations ALL refused to emit a figure (blocking DQ findings — e.g.
coverage below the agency's threshold) is status ``refused``, not ``failed``
— refusal is the product working. The per-calc summary names which figures
persisted (their computed.metric_values ids) and which calcs refused WITH the
blocking dq.issues ids, so the UI links straight to the exact issues.

Subprocess care (binding, handoff 0026):

- The runner may take minutes, so it runs on a **background thread** — no
  request handler ever blocks for the duration. POST returns 202 with the
  queued row.
- Every status transition is written to the database, so a browser refresh
  or an API restart shows the truth.
- **Staleness** (recorded choice): if the API dies mid-run the row would
  claim queued/running forever. A live row whose ``started_at`` (or
  ``requested_at`` while still queued) is older than ``STALE_AFTER_SECONDS``
  (2 hours — generously beyond any observed run, which takes minutes) is
  presented as stale in plain words on every read, stops blocking new runs,
  and is reconciled to ``failed`` (summary records the staleness, audited
  ``calc_run_marked_stale``) the next time someone starts a run. Staleness is
  judged against the API's clock; the 2-hour bound dwarfs any plausible
  clock skew.
- **Single-flight** (v0, no queue pretensions): at most one live run. The
  guarantee is STRUCTURAL — migration 0033's partial unique index means two
  racing POSTs cannot both insert a live row; the loser's INSERT .. ON
  CONFLICT DO NOTHING returns no row and becomes the same 409 that names the
  live run. No cancel endpoint in v0 (recorded); the row records the runner
  PID + start time for honest manual recovery of a hung run.

Authorization (recorded decision, handoff 0026 design 2): POST is
``data_steward`` **or above**, which includes ``report_preparer`` and
``certifying_official`` via the documented escalating hierarchy for read and
stewardship actions (headway_api.authz). Computing figures is stewardship —
it produces the computed truth preparers and certifiers work from — and the
separation-of-duties wall applies to CERTIFYING figures, not to computing
them. Reads are any signed-in role.

Honest scope (v0, recorded): no scheduling (nightly runs are the natural
v1), no per-calc selection, no cancel, no progress percentage — a live run
shows "running since HH:MM:SS" only, never a fake bar.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
import uuid
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, model_validator

from ..audit import write_event
from ..auth import Identity
from ..authz import require_at_least, require_authenticated
from ..db import get_db

router = APIRouter(tags=["calc-runs"])

#: Bounded request window: one year (leap-year inclusive). The runner itself
#: has no window limit, but an API-dispatched run is an interactive action —
#: a multi-year backfill belongs to an operator at a shell, deliberately.
MAX_WINDOW_DAYS = 366

#: After this long without finishing, a queued/running row is presented as
#: stale ("state unknown") and stops blocking new runs. Recorded choice: the
#: live runner takes minutes; 2 hours is generously beyond that, and an API
#: crash mid-run is the only way a row gets this old while live.
STALE_AFTER_SECONDS = 2 * 60 * 60

#: Bounded stdout/stderr capture (migration 0033 stdout_tail). The structured
#: outcome lives in summary; the tail exists to explain failures.
STDOUT_TAIL_CHARS = 8_000
STDERR_TAIL_CHARS = 4_000

#: The list endpoint's bounds.
LIST_DEFAULT_LIMIT = 50
LIST_MAX_LIMIT = 200

UTC = dt.timezone.utc


# ---------------------------------------------------------------------- SQL

_RUN_COLUMNS = (
    "run_id, requested_by, requested_at, period_start, period_end, status, "
    "started_at, finished_at, runner_pid, summary, stdout_tail"
)

_SELECT_LIVE_RUN = (
    "SELECT run_id, requested_by, requested_at, period_start, period_end, "
    "status, started_at FROM computed.calc_runs "
    "WHERE status IN ('queued', 'running') "
    "ORDER BY requested_at DESC LIMIT 1"
)

#: ON CONFLICT DO NOTHING (no target) absorbs the partial unique index
#: calc_runs_single_flight: the racing loser gets NO row back and turns into
#: the 409 that names the winner — never a second live run.
_INSERT_RUN = (
    "INSERT INTO computed.calc_runs (requested_by, period_start, period_end) "
    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING "
    "RETURNING run_id, requested_at"
)

_MARK_STALE_FAILED = (
    "UPDATE computed.calc_runs SET status = 'failed', finished_at = now(), "
    "summary = %s WHERE run_id = %s AND status IN ('queued', 'running') "
    "RETURNING run_id"
)

_MARK_RUNNING = (
    "UPDATE computed.calc_runs SET status = 'running', started_at = now(), "
    "runner_pid = %s WHERE run_id = %s AND status = 'queued' "
    "RETURNING run_id, started_at"
)

_MARK_FINISHED = (
    "UPDATE computed.calc_runs SET status = %s, finished_at = now(), "
    "summary = %s, stdout_tail = %s "
    "WHERE run_id = %s AND status IN ('queued', 'running') "
    "RETURNING run_id, finished_at"
)

_SELECT_RUNS = (
    f"SELECT {_RUN_COLUMNS} FROM computed.calc_runs "
    "ORDER BY requested_at DESC, run_id LIMIT %s"
)

_SELECT_ONE_RUN = (
    f"SELECT {_RUN_COLUMNS} FROM computed.calc_runs WHERE run_id = %s"
)


# ------------------------------------------------------------------- models


class CalcRunRequest(BaseModel):
    """One dispatch request: the half-open period only. No calc selection,
    no threshold knobs — the runner resolves thresholds exactly as the CLI
    does (explicit flag > audited app.settings row > code default; here
    there are no explicit flags, so the audited settings govern)."""

    period_start: dt.date
    period_end: dt.date

    @model_validator(mode="after")
    def _validate_window(self) -> "CalcRunRequest":
        if self.period_start >= self.period_end:
            raise ValueError(
                "The period start must be before the period end. Headway "
                "computes figures over a half-open period: the start date "
                "is included, the end date is not — for June 2026, use "
                "2026-06-01 to 2026-07-01."
            )
        if (self.period_end - self.period_start).days > MAX_WINDOW_DAYS:
            raise ValueError(
                "That period is longer than one year. Headway runs "
                "calculations up to one year at a time from this page — "
                "for a longer backfill, run each year separately."
            )
        return self


class CalcRunCreated(BaseModel):
    run_id: str
    status: str  # 'queued'
    requested_by: str
    requested_at: dt.datetime
    period_start: dt.date
    period_end: dt.date
    note: str
    audit_event_id: int


class CalcRunRecord(BaseModel):
    """One run, verbatim from computed.calc_runs, plus the read-time
    staleness presentation (stale/stale_note) — the honest answer when the
    API cannot know a run's state anymore."""

    run_id: str
    requested_by: str
    requested_at: dt.datetime
    period_start: dt.date
    period_end: dt.date
    status: str
    started_at: Optional[dt.datetime]
    finished_at: Optional[dt.datetime]
    runner_pid: Optional[int]
    #: The per-calc outcome map built VERBATIM from the runner's RunReport
    #: (see summarize_report). Null while the run has not finished.
    summary: Optional[dict]
    stdout_tail: Optional[str]
    #: Wall-clock seconds from started_at to finished_at — timestamps'
    #: difference, never a figure. Null until both ends exist.
    duration_seconds: Optional[float]
    #: True when a queued/running row exceeded STALE_AFTER_SECONDS: its real
    #: state is unknown (the API likely restarted mid-run).
    stale: bool
    stale_note: Optional[str]


# ------------------------------------------------- runner-report summarizing
#
# Pure functions, unit-tested directly. Every value they place in a summary
# is the runner's OWN JSON value (figures verbatim); they select and label,
# never compute.


def summarize_report(report: dict) -> dict:
    """The bounded per-calc outcome map stored in calc_runs.summary.

    Selected VERBATIM from the runner's RunReport JSON: which figures
    persisted (computed.metric_values ids), which calcs refused and WHY (the
    blocking dq.issues ids — the UI links straight to them), plus the
    run-level counts and threshold context a reader needs to understand a
    refusal. The full coverage detail is deliberately NOT copied here: it
    already lives durably on the metric row / DQ issue the runner wrote.

    Per-calc outcomes are ``persisted`` or ``refused`` only — a runner-level
    error aborts the whole run and is recorded as run status ``failed``
    (with stderr in stdout_tail), never invented per calc.
    """
    metrics = []
    for m in report.get("metrics", []):
        metrics.append(
            {
                "calc_name": m.get("calc_name"),
                "calc_version": m.get("calc_version"),
                "metric": m.get("metric"),
                "unit": m.get("unit"),
                "scope": m.get("scope"),
                "outcome": "persisted" if m.get("persisted") else "refused",
                "value": m.get("value"),
                "metric_value_id": m.get("metric_value_id"),
                "coverage": m.get("coverage"),
                "blocking_issue_ids": list(m.get("routed_blocking_ids", [])),
                "warning_issue_ids": list(m.get("routed_warning_ids", [])),
                "info_issue_ids": list(m.get("routed_info_ids", [])),
            }
        )
    return {
        "runner": "python -m headway_calc.runner (default NTD calc set)",
        "period_start": report.get("period_start"),
        "period_end": report.get("period_end"),
        "period_convention": report.get("period_convention"),
        "persisted_count": report.get("persisted_count"),
        "blocked_count": report.get("blocked_count"),
        "routed_blocking_count": report.get("routed_blocking_count"),
        "routed_warning_count": report.get("routed_warning_count"),
        "routed_info_count": report.get("routed_info_count"),
        "coverage_threshold": report.get("coverage_threshold"),
        "threshold_sources": report.get("threshold_sources"),
        "positions_loaded": report.get("positions_loaded"),
        "passenger_events_loaded": report.get("passenger_events_loaded"),
        "operated_trips_loaded": report.get("operated_trips_loaded"),
        "dr_trips_loaded": report.get("dr_trips_loaded"),
        "metrics": metrics,
    }


def classify_status(summary: dict) -> str:
    """The refused-vs-succeeded mapping over a clean (exit 0) run, from the
    runner's own counts: EVERY calc refused → ``refused`` (first-class — the
    guardrail held); at least one figure persisted → ``succeeded`` (any
    refusals ride along in the summary, visible per calc)."""
    persisted = summary.get("persisted_count") or 0
    blocked = summary.get("blocked_count") or 0
    if persisted == 0 and blocked > 0:
        return "refused"
    return "succeeded"


def bounded_tail(stdout: str, stderr: str) -> str:
    """The bounded stdout_tail: the END of each stream (the RunReport JSON's
    tail / the traceback's end are the informative parts), labeled."""
    parts = []
    if stdout:
        clipped = stdout[-STDOUT_TAIL_CHARS:]
        prefix = "" if clipped == stdout else "[...clipped...]\n"
        parts.append(f"--- stdout (tail) ---\n{prefix}{clipped}")
    if stderr:
        clipped = stderr[-STDERR_TAIL_CHARS:]
        prefix = "" if clipped == stderr else "[...clipped...]\n"
        parts.append(f"--- stderr (tail) ---\n{prefix}{clipped}")
    return "\n".join(parts)


# ------------------------------------------------------- subprocess plumbing


def _default_connect():
    """The background thread's OWN database connection — never the request's
    (the request connection returns to the pool when the response is sent),
    and never a pool slot held for minutes. autocommit matches the pool's
    discipline (db.py): transaction() blocks are genuine BEGIN/COMMIT."""
    import psycopg

    dsn = os.environ.get("HEADWAY_DATABASE_URL")
    if not dsn:
        raise RuntimeError("HEADWAY_DATABASE_URL is not set")
    return psycopg.connect(dsn, autocommit=True)


def _default_spawn(argv: list[str]):
    """Start the runner subprocess. Returns (pid, collect) where collect()
    blocks until exit and returns (exit_code, stdout, stderr). The
    environment is inherited unchanged — the runner reads the SAME
    HEADWAY_DATABASE_URL the API uses (one agency, one database, ADR-0004)."""
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def collect() -> tuple[int, str, str]:
        out, err = proc.communicate()
        return proc.returncode, out or "", err or ""

    return proc.pid, collect


def execute_run(
    run_id: str,
    period_start: dt.date,
    period_end: dt.date,
    *,
    connect: Callable = _default_connect,
    spawn: Callable = _default_spawn,
) -> None:
    """The background-thread body: spawn the runner, record every status
    transition in computed.calc_runs, and store the summarized outcome.

    Every path ends in a terminal row (succeeded/refused/failed) EXCEPT a
    database outage, which nothing here could record anyway — that is
    exactly the case the staleness presentation covers honestly.

    Injectable seams (tests): ``connect`` yields the thread's own DB
    connection; ``spawn`` starts the subprocess.
    """
    try:
        conn = connect()
    except Exception:
        # No database, nothing recordable; the stale bound surfaces this
        # run as "state unknown" rather than letting it claim to be live.
        return
    try:
        argv = [
            sys.executable,
            "-m",
            "headway_calc.runner",
            "--period-start",
            period_start.isoformat(),
            "--period-end",
            period_end.isoformat(),
        ]
        try:
            pid, collect = spawn(argv)
        except Exception as exc:
            _finish(
                conn,
                run_id,
                "failed",
                {
                    "error": (
                        "The calculation runner could not be started: "
                        f"{exc}"
                    )
                },
                "",
            )
            return
        with conn.transaction():
            conn.execute(_MARK_RUNNING, (pid, run_id))
        try:
            exit_code, stdout, stderr = collect()
        except Exception as exc:
            _finish(
                conn,
                run_id,
                "failed",
                {
                    "error": (
                        "The calculation runner was started but its output "
                        f"could not be collected: {exc}"
                    )
                },
                "",
            )
            return
        tail = bounded_tail(stdout, stderr)
        if exit_code != 0:
            status = "failed"
            summary = {
                "error": (
                    "The calculation runner stopped with an error (exit "
                    f"code {exit_code}) before it could finish. No figure "
                    "was invented to cover the gap; the output tail below "
                    "says what happened."
                ),
                "exit_code": exit_code,
            }
        else:
            try:
                report = json.loads(stdout)
                summary = summarize_report(report)
                status = classify_status(summary)
            except ValueError:
                status = "failed"
                summary = {
                    "error": (
                        "The calculation runner exited cleanly but its "
                        "report could not be read. Nothing about the run's "
                        "outcome is assumed; the output tail below holds "
                        "what it printed."
                    )
                }
        _finish(conn, run_id, status, summary, tail)
    except Exception as exc:  # pragma: no cover — last-resort recording
        try:
            _finish(
                conn,
                run_id,
                "failed",
                {"error": f"The run dispatcher hit an unexpected error: {exc}"},
                "",
            )
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _finish(conn, run_id: str, status: str, summary: dict, tail: str) -> None:
    with conn.transaction():
        conn.execute(_MARK_FINISHED, (status, json.dumps(summary), tail, run_id))


def _thread_launcher(run_id: str, period_start: dt.date, period_end: dt.date) -> None:
    """Default launcher: a named daemon thread per run. Single-flight means
    at most one such thread is ever doing work."""
    thread = threading.Thread(
        target=execute_run,
        args=(run_id, period_start, period_end),
        name=f"calc-run-{run_id}",
        daemon=True,
    )
    thread.start()


# ------------------------------------------------------------- presentation


def _is_stale(
    status: str,
    requested_at: dt.datetime,
    started_at: Optional[dt.datetime],
    now: Optional[dt.datetime] = None,
) -> bool:
    if status not in ("queued", "running"):
        return False
    anchor = started_at if started_at is not None else requested_at
    now = now if now is not None else dt.datetime.now(UTC)
    return (now - anchor).total_seconds() > STALE_AFTER_SECONDS

STALE_NOTE = (
    "This run has been marked as started for more than {hours} hours "
    "without finishing — far longer than a run takes. The server was most "
    "likely restarted while it was running, so its real state is unknown. "
    "It no longer blocks starting a new run, and it will be recorded as "
    "failed the next time someone starts one. Check the data-quality queue "
    "and the metrics page to see what, if anything, it wrote before "
    "stopping."
)


def _stale_note() -> str:
    return STALE_NOTE.format(hours=STALE_AFTER_SECONDS // 3600)


def _record_from_row(row) -> CalcRunRecord:
    (
        run_id,
        requested_by,
        requested_at,
        period_start,
        period_end,
        status,
        started_at,
        finished_at,
        runner_pid,
        summary,
        stdout_tail,
    ) = row
    stale = _is_stale(status, requested_at, started_at)
    duration = None
    if started_at is not None and finished_at is not None:
        duration = (finished_at - started_at).total_seconds()
    return CalcRunRecord(
        run_id=str(run_id),
        requested_by=requested_by,
        requested_at=requested_at,
        period_start=period_start,
        period_end=period_end,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        runner_pid=runner_pid,
        summary=summary,
        stdout_tail=stdout_tail,
        duration_seconds=duration,
        stale=stale,
        stale_note=_stale_note() if stale else None,
    )


def _live_run_message(live_row) -> str:
    """The single-flight 409, in plain words, naming the live run — no queue
    pretensions in v0 (recorded honest scope)."""
    run_id, requested_by, requested_at, period_start, period_end, status, started_at = (
        str(live_row[0]),
        live_row[1],
        live_row[2],
        live_row[3],
        live_row[4],
        live_row[5],
        live_row[6],
    )
    if status == "running" and started_at is not None:
        since = (
            f"running since {started_at.astimezone(UTC).strftime('%H:%M:%S')} UTC"
        )
    else:
        since = (
            "queued since "
            f"{requested_at.astimezone(UTC).strftime('%H:%M:%S')} UTC"
        )
    return (
        "A calculation run is already in progress: run "
        f"{run_id} over {period_start.isoformat()} to "
        f"{period_end.isoformat()}, requested by {requested_by}, {since}. "
        "Headway runs one calculation at a time in this version — when it "
        "finishes, start yours from this page."
    )


# ---------------------------------------------------------------- endpoints


@router.post("/calc/runs", response_model=CalcRunCreated, status_code=202)
def start_calc_run(
    body: CalcRunRequest,
    request: Request,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> CalcRunCreated:
    """Dispatch one calculation run over a half-open period.

    data_steward OR ABOVE (report_preparer and certifying_official included
    — the recorded handoff-0026 decision; see the module docstring).
    Single-flight; audited ``calc_run_requested`` in the same transaction as
    the row. Returns 202: the runner may take minutes and runs in the
    background — poll GET /calc/runs/{run_id} (the row, not this response,
    is the truth).
    """
    with db.transaction():
        live = db.execute(_SELECT_LIVE_RUN).fetchone()
        if live is not None:
            if _is_stale(live[5], live[2], live[6]):
                # Reconcile the dead run honestly before starting a new one:
                # failed, with the staleness recorded — and audited.
                stale_id = str(live[0])
                db.execute(
                    _MARK_STALE_FAILED,
                    (
                        json.dumps(
                            {
                                "error": (
                                    "This run never reported finishing and "
                                    "was marked failed after exceeding the "
                                    f"{STALE_AFTER_SECONDS // 3600}-hour "
                                    "staleness bound. The server was most "
                                    "likely restarted while it ran; whatever "
                                    "it wrote before stopping (data-quality "
                                    "findings, figures) is durable and "
                                    "unaffected."
                                ),
                                "stale": True,
                            }
                        ),
                        stale_id,
                    ),
                )
                write_event(
                    db,
                    actor=identity.username,
                    action="calc_run_marked_stale",
                    subject_kind="computed.calc_runs",
                    subject_id=stale_id,
                    detail={
                        "reason": "exceeded staleness bound",
                        "stale_after_seconds": STALE_AFTER_SECONDS,
                    },
                )
            else:
                raise HTTPException(status_code=409, detail=_live_run_message(live))
        row = db.execute(
            _INSERT_RUN,
            (identity.username, body.period_start, body.period_end),
        ).fetchone()
        if row is None:
            # Lost the single-flight race to a concurrent request: the
            # partial unique index refused a second live row. Name the
            # winner, exactly like the ordinary 409.
            live = db.execute(_SELECT_LIVE_RUN).fetchone()
            raise HTTPException(
                status_code=409,
                detail=(
                    _live_run_message(live)
                    if live is not None
                    else (
                        "Another calculation run was started at the same "
                        "moment as yours. Only one runs at a time — check "
                        "the run list and start yours when it finishes."
                    )
                ),
            )
        run_id, requested_at = str(row[0]), row[1]
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="calc_run_requested",
            subject_kind="computed.calc_runs",
            subject_id=run_id,
            detail={
                "period_start": body.period_start.isoformat(),
                "period_end": body.period_end.isoformat(),
                "runner": "python -m headway_calc.runner (default calc set)",
            },
        )
    # STRICTLY POST-COMMIT: the queued row is durable before the subprocess
    # exists, so a crash between commit and launch leaves an honest queued
    # row that the staleness bound will surface — never a phantom run.
    launcher = getattr(request.app.state, "calc_run_launcher", None)
    if launcher is None:
        launcher = _thread_launcher
    launcher(run_id, body.period_start, body.period_end)
    return CalcRunCreated(
        run_id=run_id,
        status="queued",
        requested_by=identity.username,
        requested_at=requested_at,
        period_start=body.period_start,
        period_end=body.period_end,
        note=(
            "The calculation run was queued and is starting in the "
            "background. It can take several minutes; this page's run list "
            "shows its progress, and the outcome is recorded even if you "
            "leave. Refusals with reasons are a normal outcome: Headway "
            "never emits a certifiable figure over an unresolved data gap."
        ),
        audit_event_id=audit_event_id,
    )


@router.get("/calc/runs", response_model=list[CalcRunRecord])
def list_calc_runs(
    limit: int = Query(default=LIST_DEFAULT_LIMIT, ge=1, le=LIST_MAX_LIMIT),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[CalcRunRecord]:
    """Run history, newest first, bounded. Any signed-in role."""
    rows = db.execute(_SELECT_RUNS, (limit,)).fetchall()
    return [_record_from_row(r) for r in rows]


@router.get("/calc/runs/{run_id}", response_model=CalcRunRecord)
def get_calc_run(
    run_id: str,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> CalcRunRecord:
    """One run — the poll target while a run is live. Any signed-in role."""
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="No calculation run with that id exists.",
        )
    row = db.execute(_SELECT_ONE_RUN, (run_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No calculation run with that id exists.",
        )
    return _record_from_row(row)
