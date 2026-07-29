# Handoff: platform → backend+frontend — The DQ queue at scale

## Context
Measured during handoff 0029's live verification, on the real queue: **`GET /dq/issues`
returns 97,782 rows ≈ 900 MB in 18 seconds and freezes the browser tab.** 86% of that
payload is `source_record_ids` — provenance arrays nobody reads in a list view. This is
pre-existing (not 0029's doing) and it is now the binding constraint on the most-used
operational screen in the product.

It has not bitten the first partner agency yet only because their queue is young. It
will. A steward's queue is the screen they live in, and a screen that cannot be opened
is a screen that teaches people the product is slow.

Related, already shipped: `/dq/issues/counts` is fast (33–49 ms, handoff 0023) and
`GET /dq/issues/{id}` exists (handoff 0026), so the pieces a paginated list needs are
in place.

## Design (binding)

1. **Bound the list, always.** `GET /dq/issues` gains pagination — `limit` (default a
   sane page, documented; hard maximum enforced) and a stable ordering with either
   `offset` or a keyset cursor (your call; keyset is better on a growing queue, and the
   ordering must be deterministic and total so pages cannot drop or duplicate rows).
   An unbounded request must become impossible, not merely discouraged. Response states
   the total (the counts endpoint is already fast) and whether more remain.
2. **Provenance leaves the list.** `source_record_ids` is not returned by the list
   endpoint; it is served by the existing per-issue detail endpoint. State the change in
   the endpoint docstring and README: the ids are not gone, they moved to where they are
   actually used. Check every existing consumer (web, client library, notebooks,
   exports) before removing, and fix any that read it from the list.
3. **The UI paginates honestly.** `/dq` loads a page at a time — the house pattern for
   caps applies: what is shown, what remains, and no pretending the visible rows are the
   whole queue. Filters and the summary cards keep working against the server counts,
   which already reflect the WHOLE queue rather than the loaded page (that distinction
   must be visible in the copy — a filtered count that silently meant "of what's
   loaded" would be exactly the kind of quiet lie this project refuses).
4. **Measure it, before and after,** against the live queue: payload bytes, server time,
   time to interactive on `/dq`. Record all three in the evidence. The target is a page
   that opens in well under a second on the real 97k-issue queue.
5. **Honest scope:** no change to what a finding *says* (0029 just shipped that), no
   change to severity/status semantics, no new filters, no infinite-scroll cleverness if
   simple paging serves — this is about making the queue usable at real volume.

## Outputs
API tests incl. pagination edges (first/last page, beyond-the-end, cap enforcement,
stable ordering under concurrent inserts if feasible) + full suite green; openapi
regenerated; every consumer of the removed list field checked and fixed; web tests +
axe + contrast green; before/after measurements against the live queue; evidence
appended here. No commits — the orchestrator integrates.

## Open Questions
- Server-side sort options (severity, age) once paging exists.
- Whether the exports/workbook paths need the same treatment at volume.

## Outputs — evidence
(appended by the implementing agent)

### Response — backend + frontend (2026-07-29)

Contract accepted and shipped in full. Everything below was measured against
the LIVE queue (host uvicorn 127.0.0.1:8000, live TimescaleDB, 98,497 dq.issues
rows — grown from 0029's 97,782 while calc runs kept landing) and the live
Vite dev server, real logins, nothing stubbed.

---

#### 1. The pagination design, and why

**Keyset cursor over `(created_at, issue_id)` ascending, not offset.** The
reasons are the queue's own shape:

- `created_at` alone is neither deterministic nor total: the live queue holds
  98,497 rows across only **31 distinct `created_at` values** (findings land
  in batches when a run routes them), so ties of thousands of rows would
  order arbitrarily and offset pages could drop or duplicate rows between
  requests. `issue_id` is the primary key, so `(created_at, issue_id)` gives
  exactly one successor for any row — the ordering is total.
- The queue GROWS while a steward reads it. A keyset page is anchored to the
  last row *served*, so a finding raised mid-walk can neither push an unread
  row past the reader nor serve one twice; ascending order means new findings
  append past the end and page positions hold steady. Pinned by test
  (`test_rows_inserted_behind_the_reader_do_not_shift_the_page`) and proven
  on the live queue (below).
- The cursor is opaque (base64url of `iso8601|uuid`), produced only by the
  endpoint. An unreadable cursor is a **422 in plain words, never a silent
  reset to page one** — quietly re-serving page one would make a walker
  believe it had seen rows it never received.

**Bounds are enforced, not advertised**: `limit` defaults to 50, hard maximum
200 via FastAPI `ge=1, le=200` — anything outside is 422, *refused not
clamped*, because a clamped `limit=100000` would look like it had returned
everything. There is no parameter value that returns the whole queue.

**Response states the whole truth**: `issues` (the page), `total` (whole
queue under the same filters, counted by the DB in 19–35 ms), `limit`,
`has_more` (from fetching limit+1 rows — cannot disagree with the page),
`next_cursor`.

**`severity` joined `status` as a server-side filter** (the one new query
parameter this wave added). Not a new *feature* — /dq's severity cards have
filtered since 0017 — but the filter had to move to where the rows are: with
one page loaded, client-side filtering would filter the PAGE, putting a card
reading "8,824 blocking" above two visible rows.

**Provenance moved to where it is used.** `source_record_ids` measured
**716 MB of the 850 MB** whole-queue response — 11,483,487 identifiers, up to
34,835 on a single issue — for a list view that only ever joined them into a
string. The list rows (`DqIssueSummary`) no longer carry the field;
`GET /dq/issues/{id}` (`DqIssue`) serves the **complete, untruncated** array.
Docstrings and the service README state the move in both places: the ids are
not gone, they moved to where they are used.

**`/dq/issues/counts` stays the one whole-queue tally** and gained
`resolution_minutes_total` (summed in the same single GROUP BY scan), because
the /dq header's "documented effort" line used to be summed client-side from
the fully downloaded queue — a page-sum would have silently become "effort on
the 50 issues you can see".

#### 2. Measurements — before and after, live queue

**Before** (measured this wave, immediately prior to the change, same live DB):

```
GET /dq/issues            -> 200, 891,839,608 bytes (850 MB), 17.5 s
                             (ttfb 17.0 s, 98,497 rows)
browser (0029 evidence)   -> ~18 s download, tab freeze, renderer crash
payload composition       -> source_record_ids 716 MB (86%), descriptions
                             79 MB (9%), subject_context 478 KB (0.05%)
```

**After** (same host, same DB, API restarted with env restored byte-for-byte):

| Measure | Value |
| --- | --- |
| `GET /dq/issues` default page (50 rows) | **58,296 bytes**, 85–133 ms total (3 runs) |
| `GET /dq/issues?limit=200` (max page) | 232,437 bytes, ~96 ms |
| `GET /dq/issues/counts` (now incl. effort sum) | 168 bytes, 30–54 ms |
| `GET /dq/issues/{id}` — the WORST issue (34,835 raw-record ids) | 2,335,046 bytes, 31 ms ttfb |
| Full live walk: 200 pages × limit=200 = **40,000 rows** | **0 repeats, 0 gaps**; per-page first 115 ms, median 90 ms, p95 111 ms, page 200 (row ~40,000) **82 ms** — keyset stays flat with depth |
| Unbounded request | **impossible**: limit 201 / 100000 / 0 / −1 / 999999999 all 422 |

Payload reduction on the default screen: **891,839,608 → 58,296 bytes
(15,299× smaller)**; server time 17.5 s → ~0.1 s.

**Time-to-interactive on /dq** (headless system Chrome via playwright-core,
real dsteward login through live Vite, live 98,497-row queue; interactive =
whole-queue summary cards AND the first page of issue cards painted):

| Run | Cards painted | Fully interactive |
| --- | --- | --- |
| First visit (SPA nav) | 274–552 ms | **772–1,371 ms** |
| Revisit (leave and return) | — | 857–1,303 ms |
| Next page paints in | — | 308–698 ms |

Before: the tab froze for the length of an ~18 s / 850 MB download and the
renderer crashed (0029 evidence, deviation 4) — there was no
time-to-interactive to measure, which is the point. The target ("opens in
well under a second on the real queue") is met for the header and first
paint; the full first page lands at ~0.8–1.4 s on the dev-server build.
Note tokens are memory-only by design, so "cold reload" of /dq lands on
/login — SPA navigation is the real steward path and is what was measured.

#### 3. The UI paginates honestly (design point 3)

- The summary cards remain the SERVER's whole-queue counts, and the copy now
  says so **in words** directly beneath them: *"These counts cover all
  98,497 issues in the queue, not just the page shown below."* (live text,
  screenshot `docs/images/handoff-0030/dq-page-1-live.png`).
- The page line states range, total and how to continue: *"Showing issues
  1–50 of 98,497 in the queue. The rest are still there — use Next to read
  on, or the cards above to narrow it."* Filtered form says "…of N that
  match".
- Plain **Next/Previous buttons** (no infinite scroll — design point 5's
  "simple paging serves"); Previous walks back through cursors the client
  already holds; edges disable with the state visible; page loads announce
  via a polite `role="status"`.
- Severity cards and status filters reset the walk to page one — a cursor is
  a position in one ordering, and carrying it across a different filter
  would drop the reader mid-queue.
- **One honesty bug found BY the live click-through and fixed in-wave** (the
  0029 pre-line tradition): the range line was numbered by the page the user
  had *clicked to*, so during the fetch it briefly read "51–100" above rows
  1–50. The displayed index now rides in the same state update as the rows
  (`view.{page,index}`), so the line can never get ahead of the list.
- Source records: each card carries a collapsed disclosure ("Source records:
  the raw data behind this finding") that fetches `GET /dq/issues/{id}` on
  first open — verified live: **0 per-issue requests before opening, 1
  after**, 1,314 B for the opened finding. A run-level finding renders "cites
  no individual raw records"; a load failure is a stated alert with a retry,
  never a quiet "no records". Screenshot
  `dq-source-records-disclosure.png`.

#### 4. Every consumer of the removed list field, checked and fixed

Checked by grep across the whole repo (`source_record_ids`, `/dq/issues`,
`dq_issues`) and by reading each hit:

| Consumer | What it did | Fix |
| --- | --- | --- |
| `web` /dq (`DqView`) | rendered `issue.source_record_ids` from list rows | on-demand disclosure via `GET /dq/issues/{id}` (above) |
| `web` /dashboard (`DashboardView`) | downloaded the WHOLE queue to tally unresolved status×severity, sliced by date client-side | reads `GET /dq/issues/counts?status=open|owned` (the same tallies /dq and /today use); the date filter no longer pretends to slice the card — stated in words (`copy.dashboard.dq.wholeQueueNote`) whenever a date filter is active |
| `web` /certify (`CertifyView`) | downloaded the whole queue to count open blocking issues | reads the two counts calls; blocking = open+owned `by_severity.blocking` (same composition as before, server-counted) |
| `web` /today (`TodayView`) | already counts-only (0021) — a test pins `/dq/issues` is never called | unchanged |
| `clients/python` | `dq_issues()` returned the full list incl. `source_record_ids`; `frames.dq_issues_frame` had the column | `dq_issues()` returns `DqIssuePage`; new `iter_dq_issues()` walks pages lazily; new `dq_issue(id)` serves the complete provenance array; frame drops the column and its docstring says where the ids went; `DqIssueCounts.resolution_minutes_total` added |
| `notebooks/03-dq-triage.ipynb` | `frames.dq_issues_frame(hw.dq_issues())` + prose describing ids on the list | cell now walks `iter_dq_issues()`; prose points at `dq_issue(issue_id)` |
| `tests/integration/test_api_against_real_postgres.py` | iterated the list response | reads `["issues"]` (scope note: one consumer fix outside the named paths — it is the API's own integration suite and would otherwise be red) |
| `exports` / workbook paths | **never consumed `/dq/issues`** (verified by grep: `exports.py` touches dq only in prose; certification gate uses its own SQL count) | none needed |
| `ds-bundle/_ds_bundle.js` | stale comment mentions counting client-side from the full list | generated design-system artifact owned by the ds-sync pipeline — NOT hand-edited; recorded for its owner |

#### 5. Test counts (every suite touched)

| Suite | Command | Result |
| --- | --- | --- |
| api | `pytest -q` (services/api) | **418 passed** (was 404; +14 in `tests/test_dq.py`: default bound; cap refusal in every direction incl. 0/−1; full-walk exactly-once over 137 rows sharing ONE created_at; last-page edge at an exact multiple; beyond-the-end cursor honest empty page; unreadable cursor 422; concurrent-insert page stability; provenance relocation; server-side severity filter + combination + unknown-severity 422; whole-queue effort sum; counts/page agreement; auth) |
| web | `npx vitest run` | **274 passed / 37 files** (was 272; dq.test rewritten for pages: range line, whole-queue cards wording, Next/Previous/edges/back, on-demand provenance incl. failure+retry and the run-level null) |
| web types | `npx tsc --noEmit -p tsconfig.app.json` | clean (note: bare `tsc --noEmit` at the web root is a NO-OP — `tsconfig.json` has `files: []` + references; earlier waves' "tsc clean" via the bare form proved nothing) |
| web contrast | `npm run check:contrast` | **87/87 token pairs PASS** |
| clients/python | `pytest -q` | **40 passed** (was 37; +3: page walk without gap or repeat, detail provenance array, frame accepts the iterator) |
| live a11y | axe-core run IN the page on live /dq | **0 violations, 0 incomplete — light AND dark** (`clickthrough-log.txt`) |

`openapi.json` regenerated: OpenAPI 3.1.0, **63 paths** (unchanged count;
schemas `DqIssuePage` + `DqIssueSummary` added, `limit` bounds visible in the
contract, `DqIssue` keeps `source_record_ids` on the by-id response only).

Keyboard path verified live: Tab reaches the pager, Enter on "Next page"
advances (click-through log); disclosure `<summary>` keeps the house focus
ring (0029's verification, markup unchanged).

#### 6. Ops note (environment action, nothing in the repo)

The live API (host uvicorn, 127.0.0.1:8000, `--factory
headway_api.app:create_app`) was restarted ONCE for the backend change, the
0029 procedure exactly: environment captured from `/proc/<pid>/environ`
before the kill and restored **byte-for-byte** (verified identical
post-restart — all 71 vars including `HEADWAY_SESSION_SECRET`,
`HEADWAY_SIGNING_KEY`, `HEADWAY_DATABASE_URL`, `HEADWAY_CORS_ORIGINS`, the
four `S3_*`). **A session token issued BEFORE the restart returned 200
after it** — no live session invalidated. Vite (localhost:5173) untouched.
The API is LEFT RUNNING (new pid recorded in the scratchpad).

#### 7. Deviations and open items (recorded, not silently absorbed)

1. **"Before" time-to-interactive is 0029's observation** (frozen tab,
   renderer crash at ~18 s), not a fresh stopwatch number: the unbounded
   endpoint no longer exists to re-measure in a browser, and re-freezing a
   tab to time a crash would prove nothing new. The before **payload and
   server time** WERE re-measured fresh this wave (850 MB / 17.5 s, above).
2. **The two open questions stand**: server-side sort options (severity,
   age) now slot naturally into the paged endpoint; the exports/workbook
   paths did not need this treatment (they never read this endpoint) but
   their own volume behaviour was not measured here.
3. **`ds-bundle/_ds_bundle.js`** carries a stale comment describing the
   pre-0023 client-side counting; it is a generated artifact of the ds-sync
   pipeline and was left for its owner.
4. **Scope note**: two consumer fixes sit outside the strictly named paths —
   `tests/integration/test_api_against_real_postgres.py` (the API's own
   integration suite, response-shape read) and `notebooks/03-dq-triage.ipynb`
   (named as a consumer class by this handoff's design point 2). Both
   minimal, both consumer fixes, neither a feature.
5. **Effort chip on the live box currently hides**: the live queue's 279
   resolved rows carry no recorded `resolution_minutes`, so
   `resolution_minutes_total` is 0 and the "≈N hours of documented work"
   chip (correctly) does not render. The behaviour with recorded minutes is
   pinned by unit test on both sides.

**Untouched, as scoped:** `services/calc/`, `services/transform/`,
`services/ingestion/`, `db/migrations/`, `install/`, `deploy/`, `.github/`
(the transform/contracts/0036 changes visible in `git status` are the
concurrent 0031 wave's, not this one's). **No commits** — the tree is left
for the orchestrator.

Screenshots + browser log: `docs/images/handoff-0030/` —
`dq-page-1-live.png`, `dq-page-2-live.png`,
`dq-source-records-disclosure.png`, `dq-dark-theme.png`,
`clickthrough-log.txt`.
