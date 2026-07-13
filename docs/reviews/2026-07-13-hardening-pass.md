# Hardening pass — 2026-07-13

Three adversarial reviews (correctness, security/robustness, cross-wave consistency) over
462bbfc..e6f8310 (S&S, PMT+sampling, DR waves), commissioned before the ops-analytics wave
and before real agency data arrives. 25 findings; fixes batched by tree below, each with
regression tests pinning the reviewers' reproduced scenarios.

Also in this pass: index/perf check on migrations 0019–0021 (healthy — PMT access rides the
stop_times pkey at ~2ms/200 trips; no action) and Platform Architect ratification of the
`raw.dr.trips` topic (recorded in handoff 0013).

## Top findings (fixed in this pass)
- dr_voms double-counts a vehicle at touching span instants and across overlapping
  vehicle-days (CONFIRMED — counts intervals, not vehicles).
- dr_vrm double-counts overlapping shared-ride onboard windows for non-TX (CONFIRMED).
- File-drop connectors ingest partially-copied files as complete records (CONFIRMED —
  silent truncation of real exports; no stability guard).
- Simulated data can land as real via file-drop default source labels (provenance gap).
- HTTP ingest buffers unbounded bodies before its size check; file-drop and GTFS zip
  paths equally unbounded (DoS class).
- One crafted CSV row (oversized field / NUL) aborts a whole file's canonical batch;
  unterminated quote silently swallows following rows (CONFIRMED at parser level).
- Transform replay not idempotent for lineage.edges / dq.issues despite README claim.
- Stale stop_times from superseding GTFS feeds would feed phantom PMT geometry.
- Client-suppliable sampling draw seeds recorded without provenance (federal-evidence gap).
- openapi.json stale (DR route missing); per-service README verification sections stale;
  extract-quotes two-list growth + retirable fallback; quote-figure JSX duplicated 4×.

## Fix evidence (appended per batch)

### Batch A — calc (DR semantics + consistency)

Scope: services/calc/ + tests/golden/dr_v0. No commits — working tree only.

**1. dr_voms double-count (CONFIRMED) — FIXED, dr_voms_v0 0.1.1.**
`headway_calc/dr.py`: the simultaneity sweep now counts DISTINCT VEHICLES
covering an instant (per-vehicle covering-interval counts; the concurrency
counter moves only on a vehicle's 0→1 / 1→0 transitions), never concurrent
intervals — per the tracker quote "the largest number of vehicles in revenue
service at any one time" (Exhibits 38+40). Both reproduced triggers pinned as
named regression tests (`tests/test_dr.py`):
- `test_voms_touching_spans_same_vehicle_counts_once_at_lunch_boundary` —
  same vehicle, spans [8:00,12:00]+[12:00,14:00] touching at 12:00 → VOMS 1
  (0.1.0: 2, pinned via the retained function);
- `test_voms_midnight_crossing_across_vehicle_days_counts_once` — service
  date D trip 23:00→01:30 overlapping D+1's 01:00 pickup, same vehicle →
  VOMS 1 with vehicle_days still 2 (the grouping is intact; dedup is at the
  sweep). 0.1.0: 2.
House convention followed (the sscls precedent): 0.1.0 retained runnable as
`compute_dr_voms_v0_1_0` with the bug documented in its docstring; tracker
0.1.0 row carries a dated superseding note, new 0.1.1 row added.

**2. dr_vrm shared-ride double-count (CONFIRMED) — FIXED, dr_vrm_v0 0.1.1.**
Non-TX onboard-sum path now MERGES overlapping-or-touching booking windows
before pricing (`_merge_onboard_windows` + `_price_onboard_window`): a merged
window prices by its boundary odometer delta where available (new
`window_odometer` distance source — exact for shared rides), else by the
per-booking sum WITH the new `dr_shared_distance_summed` warning (the overlap
warning previously gated to TX; possible OVERCOUNT, never silent). Empty
inter-passenger legs are the gaps between merged windows (counting unchanged;
non-overlapping days price byte-identically to 0.1.0). Detail adds
`shared_overlap_windows_summed` (types.py DrVrmDetail, default 0). Regression
tests: `test_vrm_do_shared_ride_overlap_priced_once_via_window_odometer`
(2 passengers × 10 mi same window + odometer boundary → window priced ONCE;
0.1.0 gave 25.00, 0.1.1 gives 15.00 on the 3-booking day) and
`test_vrm_do_shared_ride_overlap_never_summed_silently` (the reviewer's exact
DO scenario with NO odometer readings → the sum stands but is WARNED —
distances are never guessed, so 10.00 is unconstructible there; 0.1.0's
silent 20.00 pinned via the retained function). 0.1.0 retained runnable as
`compute_dr_vrm_v0_1_0` (values reproduce exactly; note: its detail dict now
also carries `shared_overlap_windows_summed: 0` via the dataclass default — a
shape addition, no value change). Tracker: dated superseding note on the
0.1.0 row + new 0.1.1 row.
**dr_vrh verified UNAFFECTED** (it prices interval durations end−start, no
per-booking summing) — no vrh version bump; pinned by
`test_vrh_unaffected_by_shared_ride_overlap`.

**3. calc-side shape_dist guard (transform fix is another batch).**
`headway_calc/pmt.py`: non-finite shape_dist values/deltas rejected
defensively via `math.isfinite` — a non-finite endpoint is not a usable shape
delta (falls to the flagged haversine fallback exactly like a negative delta;
with no coordinates the trip is invalid with the established vocabulary,
`geometry_incomplete`), plus a belt-and-suspenders non-finite check on the
computed leg and trip miles. NaN was already structurally refused by
StopTime validation (NaN >= 0 is False); +inf was NOT — before this guard it
priced a segment at infinity. Test:
`tests/test_pmt.py::test_non_finite_shape_dist_rejected_defensively` (inf
with coordinates → finite haversine figure; inf without → excluded
`geometry_incomplete`; NaN → ValueError at the type boundary).

**4. Consistency batch.**
- REGULATORY_TRACKER.md: the three blank lines splitting the calc version
  GFM table deleted — the table is one contiguous block (lines 11–31), now
  including the two new 0.1.1 rows. No "Source:" line touched.
- `headway_calc/__init__.py`: pmt exports added (compute_pmt,
  compute_pmt_by_mode, PmtDetail, StopTime, load_trip_geometries) plus the
  retained DR functions; inventory docstring now names compute_pmt 0.1.0 and
  the DR versions; NOTE added that sampling/sscls stay module-scoped because
  they never write computed.metric_values.
- `_cli.py` runner argparse description and `runner.py` module docstring now
  name ALL current runner calcs (vrm/vrh/upt/pmt + per-mode voms + the five
  DR calcs with their scopes/versions).
- `tests/conftest.py`: SAMPLING_GOLDEN_DIR + `sampling_golden_expected`
  session fixture added; `test_golden_sampling.py` now builds its
  collection-time EXPECTED from SAMPLING_GOLDEN_DIR and every
  non-parametrized test uses the fixture.

**Verification (full calc suite, live repo):**
```
$ cd services/calc && python3 -m pytest tests/ -q
442 passed in 14.46s        (was 436 before this batch; +6 named tests)
```
Golden updates: tests/golden/dr_v0/expected.json pins dr_vrm_v0/dr_voms_v0 at
0.1.1 (values unchanged on the golden dispatch day — its overlaps were
span-odometer-priced; detail gains shared_overlap_windows_summed: 0);
test_runner_dr.py pins the per-calc version map.

**5. Live re-run — simulated DR period, figures old→new (append-only).**
`python3 -m headway_calc.runner --period-start 2026-07-14 --period-end
2026-07-16` against the live Compose TimescaleDB (95 dr_trips loaded, 24
persisted, 0 blocked, 14 warnings + 20 infos routed). psql-verified from a
separate connection: the original 20 DR rows stand untouched; 20 NEW rows
appended (12 at 0.1.0, 8 at 0.1.1 → 40 total for the period; version
breakdown query: 0.1.0 = 32, 0.1.1 = 8). Old → new per metric (scope
mode:DR unless noted):

| metric | old (0.1.0) | new | change |
|---|---|---|---|
| vrm | 517.42 | **512.75 (0.1.1)** | **−4.67 mi** — DO shared-ride double-counts removed (tos:DO 274.52 → 269.85, same −4.67; PT/TX unchanged). New detail: window_odometer ×3, shared_overlap_windows_summed 1; `dr_shared_distance_summed` routed ×2 (mode + DO scopes, psql-verified in dq.issues). |
| voms | 6 | 6 (0.1.1) | unchanged — the simulated dataset has no touching-span or midnight-crossing overlaps (tos splits 3/2/1 unchanged); the fix's effect is pinned by the unit regressions instead. |
| vrh | 24.63 | 24.63 (0.1.0) | unchanged (verified unaffected) |
| upt | 204 | 204 (0.1.0) | unchanged |
| pmt | 1112.23 | 1112.23 (0.1.0) | unchanged |

Expected direction confirmed: VRM dropped where the double-count existed;
nothing else moved. Old rows were NOT deleted or rewritten — the
version-stamped re-computation stands beside them (new calc version = new
rows).

### Batch D — web convergence (2026-07-13, frontend)

Scope: `web/` + one single-line edit in `services/calc/REGULATORY_TRACKER.md`
(line 403, the DR section's Source line — manual name bolded to the tracker's
own convention; nothing else on the line or in the file touched).

**1. extract-quotes convergence (`web/scripts/extract-quotes.mjs`).**
With the DR Source line bolded, the unbolded-Source fallback regex was dead
and is deleted (the S&S addenda's unbolded sub-`Source:` lines were never the
fallback's match — the section-level bolded line matches first, and still
does). The two parallel per-section lists (the `isQuoteSection` heading
allowlist + `calcNamesForHeading`) converged: `isQuoteSection` is now the
generic `line.startsWith("## Verified")` sweep and `calcNamesForHeading` is
the single remaining list, generic `calc <name>`-in-heading parser first —
a future "## Verified …" section naming its calc in the heading is
zero-config; an unmappable swept heading still fails hard. Verified against
the tracker: the sweep hits exactly the seven quote sections and none of
"## Divergence analysis", "## Mode scoping", "## Open verification items".
The reviewer's NOTE-guard trap is now a comment at the guard: a future
verbatim quote CONTAINING "NOTE:" would be silently truncated — the guard
needs a quote-aware boundary before such a bullet lands.

Acceptance proof — regenerated quotes.json is byte-identical to the
pre-refactor file:

```
$ node scripts/extract-quotes.mjs
extract-quotes: wrote …/web/src/regulatory/quotes.json (dr_pmt_v0: 12, dr_upt_v0: 12, dr_voms_v0: 12, dr_vrh_v0: 12, dr_vrm_v0: 12, pmt_v0: 19, sampling_v0: 19, sscls_v0: 39, upt_v0: 8, voms_v0: 4, vrh_v0: 10, vrm_v0: 10)
$ diff src/regulatory/quotes.json <pre-refactor snapshot>; echo "diff exit: $?"
diff exit: 0
$ sha256sum both → 46116522e0c706465658ac17125abb30e0ad04a7f059eceac9bff014e6d36a35 (identical)
```

**2. Shared QuoteFigure (`web/src/components/QuoteFigure.tsx`).** The
quote-figure JSX duplicated 4× (Receipt.tsx's `QuoteFigure`, SafetyView's
`ManualQuote` + `TokenQuote`, SamplingView's `ManualQuote`) is one component
converging on Receipt.tsx's shape — markup and class names unchanged. A
missing quote renders the caller's stated absence: loud `class="alert"` by
default; explicit `variant="gap"` (muted `threshold-quote-missing`) only for
the known-unquoted-token case (SafetyView's TokenQuote), with the WHY in
comments at both the component and the call site: tokens the tracker
knowingly has no verbatim quote for (today only `non_major_fire`) appear on
every receipt that meets them, so a loud alert would cry wolf — the gap is
stated, never blank, never a false alarm. All four call sites migrated;
new `src/test/quoteFigure.test.tsx` pins the three states (figure /
loud alert / muted gap) with axe checks.

**3. Mode-label dedupe (`web/src/copy.ts`).** One shared `ntdModeLabels`
NTD-code map; `copy.report.mr20.modeLabels` uses it as-is and
`copy.sampling.modeLabels` spreads it with the single Table 41.01 override
(`VP: "Commuter vanpool (VP)"`), cross-linked comments both ways. Both maps
are lookup-only (selects enumerate API-served vocabularies), so the union is
behavior-safe. `copy.safety.modeLabels` deliberately untouched — a different
namespace (the transform's lowercase GTFS route_type→mode vocabulary), now
saying so explicitly.

**4. `web/README.md`.** Stale verification section (10 files / 51 tests,
3-calc extract-quotes sample) replaced with a dated 2026-07-13 entry and the
real regenerated numbers; the Regulatory-quotes section now describes the
converged "## Verified" sweep.

**Verification bar (all green, 2026-07-13):**

```
npm test -- --run      Test Files 20 passed (20) / Tests 116 passed (116)  [was 19/113 pre-batch; +1 file/+3 tests for QuoteFigure]
                       (every view test asserts zero axe-core violations — maintained)
npm run lint           clean (oxlint)
npm run build          clean (tsc -b + vite; 1318 modules)
npm run check:contrast all 49 token pairs PASS — "All token pairs meet WCAG 2.1 AA."
quotes.json            byte-identical after refactor (diff exit 0, sha256 match above)
```

### Batch C — API caps, provenance, drift gates (2026-07-13, backend)

Scope: `services/api/` + `.github/workflows/ci.yml` + `db/migrations/0022`
(number taken after checking the directory immediately before writing and
again before applying — 0021 was the highest; no competing 0022 existed).

**1. Streaming body cap (DoS class).** `routers/ingest.py` no longer calls
`await request.body()` before the size check (which buffered an unbounded
push whole). `read_body_capped()` reads `request.stream()` incrementally and
refuses with 413 the moment the running total exceeds `MAX_BODY_BYTES`,
keeping the overflowing chunk out of the buffer — the process never
materializes more than 32 MiB. A `Content-Length` header already over the
cap is refused before reading any bytes (an unparseable header proves
nothing and falls through to the incremental count). The 413 message is
byte-identical to the previous contract. Both ingest routes share the fix
(one helper).

**2. Field bounds.** Every free-text request field bound for an unbounded
TEXT column in the safety/sampling routers now has a cap with a
plain-language 422 (nothing saved on refusal): safety narrative 20,000,
location 1,000, mode / type_of_service 50, supersede reason 5,000; sampling
plan type_of_service 50, draw period_label 100, seed 200, service-unit ids
500, measurement unit_id 500, notes 10,000, supersede reason 5,000; the
decimal-string fields (observed_pmt, 100% UPT counts) are length-capped at
50 before parsing. Closed-vocabulary fields (event_category, mode/unit/
option/frequency via the calc selector, service_day_type) were already
bounded by their vocabularies.

**3. Draw seed provenance (federal-evidence gap).** Migration
**0022_draw_seed_source.sql**: `sampling.draws.seed_source TEXT CHECK (IN
('client','generated'))`, NULLABLE with no backfill — draws is append-only
(0020 trigger) and pre-0022 rows genuinely did not record which case
occurred; NULL honestly means "drawn before provenance was captured".
Schema inspection first: draws has no metadata JSON column, so the column
addition was the smallest honest change. The API records seed_source on
every draw (row + audit detail + list/create responses), and the method
text no longer implies cryptographic randomness for caller seeds: the
drawer's DRAW_METHOD (which conditions its §63.03(b)(1) claim on a
cryptographically random seed) now carries a per-seed_source provenance
note — 'generated' states Headway's CSPRNG premise holds; 'client' states
the randomness rests on how the caller produced the seed and Headway cannot
vouch for it.

**4. UTC month convention surfaced.** `/safety/deadlines` responses carry
`period_convention` — the exact string `headway_calc.ss50` already declares
("half-open [period_start, period_end), UTC, on occurred_at") — plus a
plain-language `period_note` (UTC bucketing explained for an operations
manager). `GET /safety/events` records each carry the same
`period_convention` (the response is a bare array consumed by the live web
app, so the convention travels per record — an envelope object would have
broken the deployed consumer; deviation noted below).

**5. Parameterized empty-body 422.** The shared ingest helper takes
`csv_label`; the DR route's empty-body message now names the
demand_response_trips CSV (it used to tell DR callers to send a TIDES
file). TIDES message unchanged.

**6. openapi.json + README.** Spec regenerated: OpenAPI 3.1.0, **31 paths**
(was 30 committed with `/ingest/dr/trips` missing; 18 claimed by the stale
README line). README endpoint table gains the `/ingest/dr/trips` row; the
"18 paths" line corrected; dated verification entry added with the real
counts.

**7. CI drift gates.** New `drift-gates` job in `ci.yml` (first-party
actions only, existing job style): (a) `python3 scripts/export_openapi.py`
+ `git diff --exit-code services/api/openapi.json`; (b) `node
web/scripts/extract-quotes.mjs` + `git diff --exit-code
web/src/regulatory/quotes.json` — the two drift classes this pass caught.
The quotes gate is written against the script path only (Batch D owns the
script's internals); no web regeneration was run locally as part of this
batch's verification. Workflow validated with `yaml.safe_load` (all 10
jobs parse; drift-gates needs/if/steps confirmed).

**Verification evidence (all live, 2026-07-13):**

```
services/api$ python3 -m pytest tests/ -q
196 passed, 1 warning                       [was 188; +8 new, 1 renamed —
  streamed-oversized 413; read_body_capped aborts mid-stream (33 of 48
  offered 1-MiB chunks consumed, never past the cap); oversized
  Content-Length refused before reading; safety text bounds (over-cap 422
  saving nothing, at-cap 20,000-char narrative accepted 201); sampling draw
  bounds; seed_source 'generated' and 'client' (row + audit + list +
  method text); UTC month convention on deadlines + event records]

$ python3 -m pytest db/test_migrations_static.py -q
21 passed                                   [0022 numbered sequentially, no DROP/tenant_id]

Migration applied to the live TimescaleDB (db/migrate.py, DATABASE_URL from
the running API's environment):
  applying 0022_draw_seed_source.sql ... ok
Verified from a separate psycopg connection:
  column:      [('seed_source', 'text', 'YES')]
  check:       CHECK ((seed_source = ANY (ARRAY['client','generated'])))
  draws:       11 pre-existing rows, all seed_source NULL (honest history)

Live API restarted with the previous process's exact environment
(/proc/<pid>/environ snapshot → env dict; MinIO/Kafka/DB vars preserved),
then exercised with a temporary ingest key (inserted directly for the
check, deleted after — 0 leftover rows):
  48 MiB chunked POST (no Content-Length)  → HTTP 413, exact message
      "larger than the 32 MiB ingest limit"; curl aborted after
      ~36.2 MB sent of 50.3 MB — the server stopped reading mid-stream
  Content-Length: 67108864 (no body sent)  → HTTP 413 immediately
  157-byte valid TIDES CSV                 → HTTP 202 {record_id, "ok"};
      audit.events row confirmed from a separate connection
      (actor key:hwk_…, parse_status ok, bytes 157) — real MinIO + Kafka
  GET /openapi.json                        → 31 paths, /ingest/dr/trips present
  GET /branding                            → 200 (public shell payload intact)
  GET /public/metrics/certified            → 200, certified figures served
  GET /safety/deadlines (no auth)          → 401 (generic, route alive)
```

Deviations / notes:
- `/safety/events` gains `period_convention` per RECORD, not as a top-level
  field: the deployed response shape is a bare JSON array (the live web app
  consumes it), so a top-level field would have required a breaking
  envelope. Additive per-record field chosen instead; asserted by test.
- No live sampling draw was performed: sampling.plans/draws are append-only
  federal-evidence tables and a test draw would persist in the demo agency's
  history forever. seed_source is covered by the applied migration
  (psql-verified), the unit suite, and the regenerated spec.
- The integration suite (tests/integration) was not run here: it requires a
  superuser connection to a THROWAWAY PostgreSQL and this box's instance is
  the live demo database. CI's integration-postgres job runs it (the api/db
  path filter includes migration 0022 and the router changes).

### Batch B — intake robustness + idempotency (2026-07-13, pipeline)

Scope: `services/ingestion/` (Go), `services/transform/`,
`tools/{dr,tides}-simulator/`, migration `0023_replay_idempotency.sql`.

**1. Partial-file pickup (CONFIRMED finding) — fixed with a two-scan
stability guard.** The TIDES and DR file-drop scanners now rescan every
`POLL_INTERVAL` (new `Scanner.Run` loop; the connectors were one-shot) and
ingest a file only after it is seen with identical size AND mtime on two
consecutive scans — unchanged for a full scan interval. The
rename-into-place convention for agencies (write as `.tmp`, atomic
`rename(2)` when complete) is documented in `services/ingestion/README.md`
("File-drop robustness"). Regression tests
(`TestGrowingFileNotIngestedUntilStable`, both connectors) simulate a file
growing across scans and assert no ingest until stable, then exactly one.

LIVE mid-copy reproduction against the running stack (connector binary at
`POLL_INTERVAL=3s`, simulator CSV slow-written into `DR_DROP_DIR` in
512-byte chunks at ~1 chunk/s):

```
INFO file not yet stable; waiting one scan interval before ingest (partial-copy guard) file=demand_response_trips_2026-07-13.csv bytes=1024 seen_before=false
INFO file not yet stable; ... bytes=2560 seen_before=true
INFO file not yet stable; ... bytes=4096 seen_before=true
INFO file not yet stable; ... bytes=5130 seen_before=true
INFO demand_response_trips file landed and produced bytes=5130
     record_id=a043ba42922b2e1de0b3b74083550874ada05467a7c3dace552ac9ef42983e09
$ sha256sum demand_response_trips.csv   # the complete source file
a043ba42922b2e1de0b3b74083550874ada05467a7c3dace552ac9ef42983e09
```

Skipped on four consecutive scans while growing, landed exactly once when
stable, record_id = sha256 of the complete file, one Kafka message on
`raw.dr.trips` (topic dump), file moved to `processed/`.

**2. Simulated-source enforcement — fail closed + structural refusal.**
`DR_SOURCE`/`TIDES_SOURCE` defaults removed (connector version 0.2.0): a
drop dir with no source label is a plain-language startup refusal.
Live-verified:

```
ERROR fatal: DR_DROP_DIR is set but DR_SOURCE is not. Headway needs to know
what this drop directory carries and refuses to guess: set DR_SOURCE=dr (or
your vendor's label) for a real dispatch feed, or DR_SOURCE=dr_simulated for
simulator output — simulated data must never be recorded as real (Shared
Constraint 2: full provenance)
```

Simulators keep the structural `sim:` id prefix (now pinned by regression
tests in both simulator suites), and the scanners hard-refuse any file
carrying that marker under a non-`*_simulated` source label — moved to
`rejected/`, never landed (code comments cite Shared Constraint 2, full
provenance: "simulated data is permanently distinguishable in provenance").
Live-verified: the simulator CSV dropped with `DR_SOURCE=dr` →
`ERROR REFUSED demand_response_trips file (moved to rejected/, never
silently skipped) reason: 16 row(s) carry the simulator marker "sim:" but
the configured source label "dr" does not declare simulated data...`; file
preserved at `rejected/demand_response_trips_sneaky.csv`, zero messages
produced. Unit tests cover both sides (refusal under a real label; normal
ingest under `dr_simulated`/`tides_simulated`).

**3. Size caps (DoS class).** File-drop scanners: `DROP_MAX_FILE_BYTES`
(default 256 MiB), checked on `stat` before any read; oversize files move
to `rejected/` with the limit named in the error — never silent. GTFS
static fetch: `GTFS_STATIC_MAX_BYTES` (default 256 MiB) via
`io.LimitReader`; over-limit responses are refused, never truncated.
Transform object fetch (`__main__.py`): stream-counted against
`HEADWAY_MAX_OBJECT_BYTES` (default 256 MiB), aborting with
`ObjectTooLargeError`, which `run_loop` quarantines as a blocking
`transform_failure` finding carrying the message that names the limit.
GTFS zip decompression (`gtfs_static.py`): stream-counted per-member
(512 MiB) and whole-archive (2 GiB) budgets; exceeding either ABORTS the
feed with a blocking `transform_failure` finding naming the limit and zero
rows written. All tested with small limits injected (Go: 64-byte cap;
transform: 16-byte member / 100-byte total / 5-byte fetch caps).

**4. Per-row quarantine holes (CONFIRMED finding).** New
`headway_transform/row_guard.py` shared by the DR, TIDES and GTFS-static
normalizers; read loops restructured (`iter_rows`) so `csv.Error` raised
mid-iteration is caught per row and iteration continues (verified on
CPython 3.12). The reviewers' three reproduced inputs are pinned as
regressions against all three normalizers (`tests/test_hardening.py`):
oversized field → one finding naming "field larger than field limit
(131072)", other rows land; NUL cell → rejected at field level BEFORE
Postgres with a "NUL byte" finding, other rows land; stray/unterminated
quote → absorption detected via the multi-line-field profile, finding
counts the absorbed span ("N absorbed line(s) ... never silently
swallowed"), preceding rows land. Transform versions minted:
normalize_dr_trips 0.1.1, normalize_tides_passenger_events 0.1.1,
normalize_gtfs_static 0.3.1.

**5. Replay idempotency (README claim vs reality).** Pre-migration
duplicate inspection on the live database (psql, separate connection):

```
total_edges=6,632,038  duplicate_edge_rows=672,073
  (all transform-origin: canonical.trips 450,312 + vehicle_positions
   220,149 + routes 1,612 duplicate rows, from static/RT replays)
dq.issues: 35,398 rows, 6,911 exact-duplicate rows (calc/AI-origin types;
   deliberately NOT deleted — see migration comment)
```

Migration `0023_replay_idempotency.sql` (live-applied via `db/migrate.py`,
psql-verified from a separate connection): deleted the duplicate edges
keeping lowest edge_id, created `edges_natural_key_uq` UNIQUE on the full
six-column tuple (post-migration: `total_edges=5,960,001,
duplicate_edge_rows=0`), added nullable `dq.issues.dedupe_key` +
`issues_dedupe_key_uq` UNIQUE WHERE NOT NULL. No dq.issues rows deleted;
human-/AI-/calc-created issues keep dedupe_key NULL and can never be
deduplicated — only the transform writer populates it
(`transform:` + sha256 of issue_type|severity|title|description|sorted
record ids; None without a source-record anchor). Writer:
`lineage.edges` insert now `ON CONFLICT (…natural key…) DO NOTHING`;
`dq.issues` insert carries dedupe_key with
`ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING`.

LIVE double-delivery demonstration: the real `raw.dr.trips` message from
the mid-copy demo (record `a043ba42…`, 16 simulator rows incl. injected
defects) pulled from the topic and delivered TWICE through
`process_message` + `DbWriter` into the live database, counts read from a
separate psql connection each time:

```
before:            dr_rows=0   edges=0   findings=0  raw_records=0
after delivery 1:  dr_rows=13  edges=13  findings=3  raw_records=1
after delivery 2:  dr_rows=13  edges=13  findings=3  raw_records=1   (zero new rows)
```

The 3 findings are the injected-defect quarantines (malformed_dr_trip),
each carrying a `transform:…` dedupe_key. The transform README's
idempotency claim now matches reality and records that it previously did
not.

**6. Suites (all green, 2026-07-13).** Go ingestion: `go build ./... &&
go vet ./... && go test ./... -count=1` → ok across all packages, 37 tests
(was 25). Transform: `python3 -m pytest tests/ -q` → **83 passed** (was
66). Simulators: dr 15 passed (was 14), tides 10 passed (was 9). DB static
checks: **21 passed** (includes migrations 0022 + 0023).
`services/ingestion/README.md` (go-test block now lists `connectors/dr`;
new "File-drop robustness" section incl. the rename-into-place
convention), `services/transform/README.md` (dated verification entry,
corrected idempotency claim), and both simulator READMEs updated.

The Compose `ingestion` container was rebuilt from this tree and restarted:
startup logs show the periodic tides scanner (`dir=/data/tides-drop
source=tides_simulated interval=30s`) and the live MBTA static fetch landing
normally under the new 256 MiB cap (`feed landed and produced`).

Deviation note: the new migration landed as **0023** (not 0022) — Batch C
concurrently claimed 0022 (`0022_draw_seed_source.sql`).
