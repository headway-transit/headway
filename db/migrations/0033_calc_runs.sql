-- 0033: computed.calc_runs — operational bookkeeping for calculation runs
-- dispatched from the API (handoff 0026).
--
-- WHY THIS TABLE EXISTS: first-agency UAT (day 2) surfaced that the only
-- documented way to compute figures was a developer-shaped CLI line on the
-- empty metrics page — and on an agency compose install there is no host
-- Python at all (the calc wheel ships inside the api image). Computing
-- figures is a role-gated, audited, DB-scoped application action inside the
-- platform's own trust boundary, so the API dispatches the SAME deterministic
-- runner (`python -m headway_calc.runner`) as a subprocess and records each
-- run here. The API remains a DISPATCHER: no calculation logic, figures
-- verbatim — the numbers still originate only in the calc library.
--
-- WHAT A ROW IS (and is not): one requested run and its lifecycle. This is
-- OPERATIONAL BOOKKEEPING, not evidence — the evidence of a run is what the
-- runner itself durably writes (dq.issues findings, computed.metric_values +
-- lineage.edges rows). Status transitions via UPDATE are therefore fine
-- (queued → running → succeeded|refused|failed), rows are simply never
-- deleted, and no append-only trigger is needed (deliberate contrast with
-- audit.events / cert.certifications; the handoff records this decision).
--
-- STATUS VOCABULARY (the honest-outcome mapping, handoff 0026 design 2):
--   queued     inserted, subprocess not yet started
--   running    subprocess started (started_at + runner_pid recorded)
--   succeeded  runner exited 0 and at least one figure persisted
--   refused    runner exited 0 and EVERY calculation refused to emit a
--              figure (blocking DQ findings — e.g. coverage below the
--              agency's threshold). Refusal is the product working, so it is
--              FIRST-CLASS and never conflated with 'failed'.
--   failed     the runner exited nonzero, produced unreadable output, or the
--              API marked a run stale (see below).
--
-- STALENESS (handoff 0026 subprocess care): if the API process dies mid-run,
-- the row must not claim 'running' forever. The API's chosen bound (recorded
-- here and in routers/calc_runs.py): a queued/running row whose
-- started_at — or requested_at while still queued — is older than 2 hours is
-- presented as stale ("state unknown" in plain words) on every read, stops
-- blocking new runs, and is reconciled to 'failed' (summary notes the
-- staleness, audited) the next time someone starts a run.
--
-- SINGLE-FLIGHT (v0, no queue pretensions): at most ONE live run at a time,
-- enforced STRUCTURALLY by the partial unique index below — two concurrent
-- POSTs cannot both insert a live row, no matter how they race. A second
-- request gets a 409 naming the live run.
--
-- summary JSONB: the per-calc outcome map the API builds VERBATIM from the
-- runner's own RunReport JSON (which figures persisted with their
-- computed.metric_values ids, which calcs refused with the blocking
-- dq.issues ids so the UI can link straight to /dq, which errored). Nullable:
-- a queued/running row has no outcome yet — never a fabricated one.
--
-- stdout_tail: the BOUNDED tail of the runner's stdout/stderr (the API caps
-- it before insert) — enough to explain a failure, never an unbounded log
-- dump into the database.

CREATE TABLE computed.calc_runs (
    run_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requested_by  TEXT NOT NULL,
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    period_start  DATE NOT NULL,
    period_end    DATE NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued'
        CONSTRAINT calc_runs_status_vocabulary
        CHECK (status IN ('queued', 'running', 'succeeded', 'refused', 'failed')),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    -- v0 records PID + start for honest manual recovery of a hung runner
    -- (handoff 0026 open question; no cancel endpoint yet by design).
    runner_pid    INTEGER,
    summary       JSONB,
    stdout_tail   TEXT,
    CONSTRAINT calc_runs_period_half_open CHECK (period_start < period_end),
    -- A terminal row states when it finished; a live row must not.
    CONSTRAINT calc_runs_finished_iff_terminal CHECK (
        (status IN ('succeeded', 'refused', 'failed')) = (finished_at IS NOT NULL)
    )
);

-- The structural single-flight guarantee: only one queued/running row can
-- exist. (An index on a constant expression, scoped by the WHERE clause.)
CREATE UNIQUE INDEX calc_runs_single_flight
    ON computed.calc_runs ((true))
    WHERE status IN ('queued', 'running');

-- The list endpoint reads newest first.
CREATE INDEX calc_runs_requested_at_idx
    ON computed.calc_runs (requested_at DESC);

COMMENT ON TABLE computed.calc_runs IS
    'Calculation runs dispatched from the API (handoff 0026): operational '
    'bookkeeping for python -m headway_calc.runner subprocesses. Status '
    'transitions are UPDATEs; rows are never deleted. The run''s evidence '
    'lives where the runner wrote it (dq.issues, computed.metric_values, '
    'lineage.edges); summary holds the per-calc outcome map verbatim from '
    'the runner''s RunReport. refused (every calc withheld its figure over '
    'blocking DQ findings) is a first-class outcome, distinct from failed.';
