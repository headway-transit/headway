# Handoff: platform → backend+frontend — Run calculations from the UI (UAT wave 2)

## Context
First-agency UAT, day 2 (2026-07-28 evening): the empty metrics page teaches "run
`python -m headway_calc.runner --period-start <start> --period-end <end>`" and the ITS
manager asked, legitimately, why there is no button. Two real findings: (1) the CLI
line is developer-shaped — on an agency compose install there is no host Python and no
documented calc invocation at all (the calc wheel ships INSIDE the api image since the
v0.2.0-alpha release-gate fix); (2) computing figures is an application-domain action
inside the platform's own trust boundary — unlike self-update (deliberately refused, a
web session must never replace the software it runs in), a calc run is role-gated,
audited, DB-scoped work the server can and should do on request. This wave builds it.

## Design (binding)

1. **Migration 0033 — `computed.calc_runs`**: run_id, requested_by, requested_at,
   period_start, period_end, status (`queued|running|succeeded|refused|failed`),
   started_at, finished_at, summary JSONB (per-calc outcome: figures persisted /
   refusal with its blocking DQ issue ids / error), runner stdout tail TEXT (bounded).
   Append-only-ish: status transitions via UPDATE are fine, but rows are never deleted;
   no trigger theatrics needed — this is operational bookkeeping, not evidence.
2. **API**:
   - `POST /calc/runs` (data_steward and certifying_official; report_preparer if the
     role files support it — read them and record the decision): body = period_start,
     period_end (ISO dates, validated period_start < period_end, bounded window ≤ 1
     year). Creates the row, launches the runner **as a subprocess of the api process**
     (`python -m headway_calc.runner ...` — same interpreter environment; the wheel is
     bundled), captures output, updates the row. **Single-flight**: a second POST while
     one is queued/running gets a 409 naming the live run — plain language, no queue
     pretensions in v0. Audited (`calc_run_requested`).
   - `GET /calc/runs` (viewer+; newest first, bounded) and `GET /calc/runs/{id}`.
   - The runner's honest outcomes are FIRST-CLASS: a run whose calcs all refused is
     status `refused`, not `failed` — refusal is the product working. Per-calc detail
     in summary: which figures persisted (ids), which calcs refused and WHY (the
     blocking dq.issue ids so the UI can link straight to /dq), which errored.
   - Runner flags: default run = the standard calc set exactly as the CLI default; no
     new calc logic, no new knobs — the API is a *dispatcher*, figures verbatim.
3. **Frontend**:
   - A **Calculations room** (`/calc-runs`, nav for the authorized roles; name it in
     plain words — "Compute figures") with: a period picker (month presets + custom
     range), the Run button (aria-busy while a run is live; the 409 single-flight
     message verbatim at the control), and the run history — each run showing status,
     duration, and its per-calc outcomes: persisted figures LINK to the metrics page /
     receipts; refusals render the refusal reason and LINK to the exact DQ issues.
     Poll while a run is live; reduced-motion/no-cute-animation rules stand (a
     refusal or failure arrives plainly).
   - **The empty metrics page replaces its CLI line** with: the button (for authorized
     roles) routing to the Calculations room, or, for viewers, plain words saying who
     can compute figures. The developer CLI line moves to a code-comment/docs, not a
     user surface.
   - First-run teaching moment: when a run ends `refused`, the UI says — in the house
     voice — that refusals with reasons are Headway working as designed, and walks the
     user to the DQ queue.
4. **Honest scope**: no scheduling (nightly runs = roadmap; record it), no per-calc
   selection UI in v0 (the default set only; record), no cancel (record; the
   single-flight 409 names the running run and its start time), no progress percentage
   (honest "running since HH:MM:SS" only — never a fake bar).

## Outputs
API tests (authz matrix, single-flight 409, refused-vs-failed status mapping, audit
rows) + full suite green; migration 0033 applied live; openapi regenerated; web tests +
axe + contrast green; build clean; live verification: a REAL run against the live MBTA
data through the new endpoint (expect real refusals given current coverage — that IS
the demo), click-through as steward (run → watch → refusal → DQ link) and viewer
(read-only surface); evidence appended here. No commits — the orchestrator integrates.

## Open Questions
- Scheduled runs (nightly cron container or API-side scheduler) — the natural v1.
- Per-calc selection + per-mode params in the UI once the default-set story is proven.
- Cancel/timeout policy for a hung runner (v0 records PID + start; document manual
  recovery honestly in the run room if a run is stuck).

## Response (backend+frontend — accepting, with recorded decisions)

Contract accepted and built as specified. Decisions the handoff asked to be
recorded:

1. **report_preparer may POST /calc/runs** — included via the documented
   escalating role hierarchy (`headway_api/authz.py`: viewer < data_steward <
   report_preparer < certifying_official for read/stewardship actions).
   Computing figures is stewardship — it produces the computed truth the
   preparer and certifier work from — and the separation-of-duties wall
   applies to CERTIFYING figures, not computing them. Enforced as
   `require_at_least("data_steward")`; pinned by tests for all four roles.
2. **Refused-vs-succeeded mapping** — from the runner's own counts, never
   re-derived: exit 0 + every calc blocked → `refused` (first-class); exit 0
   + ≥1 figure persisted → `succeeded`, with any refusals riding along
   per-calc in the summary (the live July run is exactly this honest-mixed
   case). Nonzero exit / unreadable report / spawn failure → `failed` with a
   plain-language reason and the bounded output tail.
3. **Single-flight is structural, not best-effort** — migration 0033 adds a
   partial unique index (`calc_runs_single_flight` on a constant expression
   `WHERE status IN ('queued','running')`), so two racing POSTs cannot both
   insert a live row no matter how they interleave; the loser's
   `INSERT .. ON CONFLICT DO NOTHING` returns no row and becomes the same
   409 that names the winner. The 409 names run id, period, requester, and
   "queued/running since HH:MM:SS UTC" — no queue pretensions.
4. **Staleness choice (recorded)**: a queued/running row whose `started_at`
   (or `requested_at` while queued) is older than **2 hours** — generously
   beyond the observed run time of minutes — presents `stale: true` plus a
   plain-words note ("state is unknown; the server was most likely
   restarted…") on every read, stops blocking new runs, and is reconciled to
   `failed` (summary records the staleness; audited `calc_run_marked_stale`)
   the next time someone POSTs. Judged against the API clock; the 2-hour
   bound dwarfs plausible skew.
5. **The CLI line left THREE user surfaces, not one** — the handoff names
   the metrics empty state, but /dashboard and /today carried the identical
   `python -m headway_calc.runner` line (handoff 0021's teaching empty
   states), and "the developer CLI line moves to a code-comment/docs, not a
   user surface" cannot hold with two copies left standing. All three now
   show the Compute-figures door (authorized roles) or plain words about who
   computes (viewers). The CLI invocation lives on in a code comment
   (web/src/copy.ts) and services/api/README.md.
6. **One addition beyond the letter of the design: `GET /dq/issues/{id}`**
   (viewer+). The binding requirement "refusals … LINK to the exact DQ
   issues" cannot be met through the existing list endpoint: after the live
   July run the queue holds 97,056 issues and `GET /dq/issues` serves
   **877 MB of JSON in ~16 s** (measured; the browser then has to parse it —
   the first click-through attempt timed out at 60 s). The deep-link target
   `/dq?issue=<id>` now fetches the one finding directly (~0.1 s live) and
   renders it above the queue; an unknown id shows the server's 404 words.
   Same read-authz as the list; no new write surface; in the README matrix,
   openapi regenerated, tested (route-order pin included so
   `/dq/issues/counts` still wins).
7. **Empty-period behavior is the calc library's, served verbatim**: a run
   over a month with no canonical data (June 2026 live) persists honest
   zeros with coverage 1.0000 — the runner's real, documented output. The
   dispatcher does not editorialize it into a refusal; figures verbatim.
8. **Honest v0 scope** (stated on the page itself, copy.calcRuns.scopeNote):
   no scheduling (nightly runs = roadmap), no per-calc selection, no cancel
   (row records runner PID + start for manual recovery), no progress
   percentage — a live run shows "Running since HH:MM:SS UTC" only, polled
   every 5 s, nothing animated.

## Outputs — evidence

### What was built

- **Migration** `db/migrations/0033_calc_runs.sql` — `computed.calc_runs`
  (run_id, requested_by/at, half-open period CHECK, status vocabulary CHECK
  `queued|running|succeeded|refused|failed`, started/finished_at with a
  finished-iff-terminal CHECK, runner_pid, summary JSONB, bounded
  stdout_tail), the structural single-flight partial unique index, and the
  newest-first index. UPDATE transitions allowed, no deletes, no append-only
  trigger (operational bookkeeping, not evidence — per the handoff).
- **API** `services/api/headway_api/routers/calc_runs.py` —
  `POST /calc/runs` (data_steward+, audited `calc_run_requested` in the same
  transaction as the row, 202, post-commit background-thread launch of
  `sys.executable -m headway_calc.runner --period-start … --period-end …`
  with NO other flags — the CLI default set exactly; thresholds therefore
  resolve settings-row > code-default, and the run report records their
  provenance), `GET /calc/runs` (viewer+, newest first, limit ≤ 200),
  `GET /calc/runs/{id}`. The thread opens its OWN psycopg connection (never
  the request's, never a pool slot held for minutes), records
  running(+PID) → terminal in the DB so a refresh or API restart shows the
  truth, captures bounded stdout/stderr tails (8k/4k chars), and builds the
  summary VERBATIM from the runner's RunReport JSON: per calc+scope —
  persisted (value, unit, metric_value_id, coverage) or refused
  (blocking/warning/info dq.issue ids). Injectable seams (`connect`,
  `spawn`, `app.state.calc_run_launcher`) keep tests subprocess-free.
  Plus `GET /dq/issues/{issue_id}` in routers/dq.py (decision 6).
- **Web** `web/src/views/CalcRunsView.tsx` (route `/calc-runs`, nav
  "Compute figures" for data_steward+; viewers get the read-only surface
  with plain words): month presets (last 12, default = previous month) +
  custom half-open range; the Run control uses aria-disabled (never native
  disabled) with the reason always visible at the control and aria-busy
  while starting; the 409/422/refusal messages render VERBATIM; the run
  history shows status as text (+ per-status plain-language explanation),
  requested-by/at, "Running since HH:MM:SS UTC" (no bar, no percentage,
  nothing animated; 5 s poll), duration in words, per-calc outcome tables
  with figures verbatim + links (persisted → /metrics + the lineage
  receipt; refused → `/dq?issue=<id>` per exact blocking finding), the
  refused-run teaching block in the house voice, failed-run reasons with
  the output tail behind a disclosure, and the server's staleness note
  verbatim. DqView gained the linked-finding section (direct fetch).
  Empty states on /metrics, /dashboard, /today swapped the CLI line for the
  door / plain words (decision 5).

### Test + build evidence (all captured from real runs)

- API: `pytest tests/ -q` → **400 passed** (was 370 pre-wave; +26 calc-run
  tests incl. the four-role authz matrix, unauthenticated 401s, period
  validation, single-flight 409s incl. the lost-race path, stale reconcile +
  presentation, refused-vs-failed-vs-succeeded mapping, verbatim summary
  with blocking-issue ids, bounded-tail clipping, and the full execute_run
  lifecycle against a fake subprocess; +4 dq deep-link tests incl. the
  route-order pin).
- OpenAPI regenerated (`scripts/export_openapi.py`): **63 paths**, now incl.
  `/calc/runs`, `/calc/runs/{run_id}`, `/dq/issues/{issue_id}`. README authz
  matrix updated for all three.
- Web: `vitest run` → **257 passed / 36 files** (incl. calcRuns.test.tsx:
  refusal-first-class rendering with exact-issue links + teaching block +
  zero `role=alert` on a finished refusal, verbatim 409 at the control with
  aria-disabled + no `<progress>` element anywhere, stale note verbatim,
  viewer read-only, failed-run disclosure, 5 s poll-to-terminal, month
  helpers; dq.test.tsx deep-link direct-fetch + 404-verbatim; updated
  emptyStates/today tests pin that `python -m headway_calc.runner` appears
  on NO user surface). axe (jest-axe/axe-core) green on the new room in
  steward, live-run, and viewer states; `tsc -b` clean; `oxlint` clean;
  `npm run check:contrast` — all token pairs AA; `npm run build` clean.
  Known flaky noted: the pre-existing dq attest dialog test failed once
  under full-suite parallel load (timing), passes alone repeatedly and in
  the final full run — not touched by this wave's logic.

### Live verification (host uvicorn 127.0.0.1:8000, live TimescaleDB, real MBTA data)

- Migration applied via db/migrate.py (PG* env): `applying
  0033_calc_runs.sql ... ok — applied 1 migration(s)`;
  `schema_migrations` shows `0033_calc_runs.sql`.
- API restarted with the handoff-0025 env (HEADWAY_SESSION_SECRET
  regenerated via openssl; HEADWAY_SIGNING_KEY, HEADWAY_DATABASE_URL
  key-value form, HEADWAY_CORS_ORIGINS, S3_*).
- **The real run** (as dsteward through the new endpoint), July 2026
  (`[2026-07-01, 2026-08-01)` — the period the live GTFS-RT data covers):
  run `8397d9ef-1b5f-4e67-b069-b000ab535f91`, 202 → running (PID recorded)
  → **succeeded in 222 s**, inputs 15,016,508 vehicle positions / 204,534
  passenger events / 83,167 operated trips / 108 dr_trips. Outcome, exactly
  as predicted by the handoff — **the honest refusals ARE the demo**:
  - **All four fleet NTD calcs REFUSED**: vrm_v0 + vrh_v0 at coverage
    **0.8860 below the agency's audited 0.95 threshold** ("Only 166596 of
    188040 (vehicle_id, trip_id) groups are free of telemetry gaps >
    300s…"), upt_v0 + pmt_v0 on `apc_missing_trips_above_fta_threshold`.
    Each refusal carries its blocking dq.issues id in the run summary;
    all four ids verified present in dq.issues (severity blocking, open).
  - **20 Demand Response figures persisted** (mode:DR + per-TOS scopes,
    e.g. dr_vrm_v0 616.31 miles). Spot-verified: summary
    metric_value_id `3cfe8089-…` → computed.metric_values row (vrm,
    mode:DR, 616.31, dr_vrm_v0) with 3 lineage.edges rows.
  - Threshold provenance in the summary: all four settings-seeded knobs
    `"settings"`, imbalance `"default"` — the audited app.settings row
    governed, no API knob existed to bypass it.
- **Single-flight live**: a second POST during the run → 409 verbatim: *"A
  calculation run is already in progress: run 8397d9ef-… over 2026-07-01 to
  2026-08-01, requested by dsteward, running since 20:43:43 UTC. Headway
  runs one calculation at a time in this version…"*. (Same behavior
  captured earlier against the first dispatch at 20:25:19.)
- **Authz/validation live**: viewer (real `vread` account, created live via
  the audited POST /users) POST → 403 naming the required role; viewer GET
  → 200; unauthenticated → 401; start ≥ end → 422 with the half-open
  teaching sentence; 18-month window → 422 "longer than one year".
- **Audit rows verified by query** (audit.events): 990 + 1024 + 1028
  `calc_run_requested` (actor dsteward, period in detail), 1022 the manual
  recovery below, 1026 the vread user creation.
- **A REAL crash-mid-run occurred and the design held**: the first July
  dispatch (run `11572906-…`, 20:25:19) lost its host when the Claude Code
  process running the whole session exited — the API died, the runner
  subprocess (recorded PID 2530040) died with it having written nothing
  (verified: 0 dq.issues, 0 metric_values after 20:25). The row honestly
  claimed `running`; the recorded runner_pid let an operator verify the
  process was gone; because the 2-hour staleness bound had not yet elapsed,
  the documented v0 **manual recovery** was exercised: the row was marked
  failed via SQL with the truth in `summary` (nothing computed, nothing
  lost) and an audit.events row (1022) records the act. The failed card
  renders that reason verbatim in the room (visible in the full-history
  screenshot). The automatic path (stale presentation after 2 h +
  auto-reconcile on next POST, audited) is pinned by tests.
- **June 2026 run** (`c5fd9c94-…`, no canonical data in the period): the
  calc library persisted honest zeros (0.00 miles/hours/trips, coverage
  1.0000) in 0.3 s — its real behavior, served verbatim (decision 7).
- `GET /dq/issues/{id}` live: 0.111 s for the vrm blocking finding, vs
  16.3 s / 877,235,553 bytes for the whole-queue list (97,056 issues) —
  the measurement behind decision 6. (The 41k→97k queue growth is this
  run's own 50,640 routed warnings + 4,766 infos — the runner's real DQ
  output over 13 days of partial-coverage data; recorded as more fuel for
  the standing "queue list needs pagination" backend follow-up.)
- The known idle-pool 500 flake was not observed this wave.

### Click-through (headless system Chrome via playwright-core, real logins, live stack — docs/images/handoff-0026/)

SPA-only navigation (the in-memory session signs out on full reload —
documented walking-skeleton behavior); first-visit tour dismissed.

- `steward-today-nav.png` — dsteward signed in; "Compute figures" in the nav.
- `steward-calc-runs-room.png` — the room: intro (never computes here),
  refusal-is-designed line, period picker, armed Run button, honest-scope
  note.
- `steward-calc-runs-history-full.png` — the full history: the June
  zeros run, the July run's per-calc table (4 refusals with coverage
  0.8860 + "Open blocking finding 1" links beside 20 persisted DR figures
  with metrics/receipt links), and the manually-recovered failed run with
  its recorded reason.
- `steward-dq-linked-finding.png` — the refusal link landed on
  `/dq?issue=c8ee9323-…`: "Finding opened from a link" with the exact vrm
  coverage_below_threshold finding, full plain-language description,
  blocking badge, status open.
- `steward-metrics-after-run.png` — the metrics page the persisted-figure
  links land on.
- `viewer-today-nav.png` / `viewer-calc-runs-readonly.png` /
  `viewer-calc-runs-readonly-full.png` — real viewer (vread): no nav link,
  no Run button, the plain-words banner ("Starting a run is done by a data
  steward, report preparer, or certifying official"), full run history
  readable.

### Ops notes

- Live API restarted twice (this wave's code, then the dq deep-link
  endpoint); env exactly as handoff 0025 recorded + nothing new. Session
  secret regenerated each restart (existing browser sessions invalidate —
  demo users just sign in again).
- New demo account on the live box: `vread` / `demo-vread-2026` (viewer),
  created through the audited admin API for the read-only click-through.
- Vite restarted on :5173 (it had died with the same host exit).
- NOT certified: nothing was certified this wave; the four blocking
  findings stand open in /dq, which is the point.

### Open questions (carried forward)

- Nightly scheduled runs (v1), per-calc selection, cancel/timeout policy —
  unchanged from the handoff; the room's scope note states all three.
- DQ queue list pagination/summarization (pre-existing follow-up, now
  urgent at 97k rows / 877 MB — the deep-link endpoint covers the linked
  path but the full-queue download remains heavy).
