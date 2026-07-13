# Handoff: platform/ntd roles → transform, calc, backend, frontend — Ops analytics v0: headway adherence + on-time performance (READY, not yet launched)

## Context
The platform is named Headway and does not yet measure headway. GTFS-RT trip updates are ingested as raw records but never normalized (feature-gap report #8, "data already held"); vehicle_positions + (since migration 0019) canonical stops/stop_times give scheduled AND observable actual stop passage. These are OPERATIONS metrics, not NTD reported figures — a new honesty boundary this handoff must draw explicitly.

## Design (binding)
1. **Honesty boundary first:** ops metrics are NOT regulatory figures. They must be persisted with `category='ops'` (or equivalent) such that they can NEVER appear in the certification cockpit, the MR-20/S&S packages, or /public/metrics/certified. Their receipts cite an industry basis (TCRP Transit Capacity and Quality of Service Manual definitions — quote what we can verify from public sources; if a definition cannot be verified from a source ON FILE or fetchable, state the metric is a Headway operational definition, versioned, with the formula shown), never an FTA manual page. No new REGULATORY_TRACKER rows — instead a parallel `services/calc/OPS_DEFINITIONS.md` with the same quote-or-own-it discipline.
2. **Canonical trip_updates (migration 0022 + transform):** normalize GTFS-RT TripUpdate stop-time events (predictions with timestamps, per trip/stop_sequence, feed timestamp preserved — predictions are PREDICTIONS; label them so) with lineage, replay fixtures. Live-replay the raw MBTA trip_update records already in MinIO/Kafka.
3. **Observed stop passages:** derive actual arrival/passage events from vehicle_positions proximity to canonical stops per trip (deterministic, versioned derivation with documented geometry tolerance; store as a derived canonical table or calc-internal — smallest honest design wins; document the choice). MBTA position cadence limits precision — measure and report the observed inter-position gap distribution before choosing tolerances; refuse per-stop OTP where cadence can't support it (the gap-policy discipline applies to ops metrics too).
4. **Calcs (ops-labeled, versioned like everything else):** `otp_v0` — % of observed timepoint passages within a CONFIGURABLE window (default from a verifiable public basis if one exists; else Headway-defined default, clearly labeled, per-agency app.settings knob with provenance like coverage_threshold); `headway_adherence_v0` — observed vs scheduled headway per route/stop/period (headway CV or excess wait time; pick ONE well-defined v0 formula, show the math in OPS_DEFINITIONS.md). Goldens hand-worked; property tests.
5. **API/UI:** ops metrics served under an /ops or metrics category distinction; dashboard cards (route-level OTP, headway adherence over time) using the existing chart components + dataviz palette discipline; every ops figure visually distinct from NTD figures (badge: "Operations metric — not an NTD reported figure"); SIMULATED/coverage caveats as usual.
6. **Live verification:** end-to-end against the MBTA data already held; report real OTP/adherence numbers (or honest refusals with the cadence evidence).

## Outputs
Migration + normalizer live-replayed, derivation + two calcs with goldens, OPS_DEFINITIONS.md, API/UI surfacing, live numbers, suites green, evidence here.

## Open Questions
- TCRP TCQSM quotes: fetch/verify public excerpts or own the definitions — decide at implementation, document either way.
- Excess wait time vs headway CV as the v1 second formula.
- Prediction-accuracy metrics (trip_update predictions vs observed passages) — natural v1 once both tables exist.

## Response — transform/calc/backend (2026-07-13)

Contract accepted and implemented for design points 1–4 plus the API half
of point 5. UI (dashboard cards, badges) is the frontend agent's half; the
API shapes it needs are below. Deviations from the letter of this handoff
are listed at the end of this section; live evidence follows in
"Outputs — backend evidence".

**What landed (all in the working tree, no commits):**

1. **Honesty boundary (design point 1)** — migration
   `db/migrations/0024_ops_metric_category.sql`:
   `computed.metric_values.category` (`'ntd'` default | `'ops'`, closed
   CHECK vocabulary) + the structural guarantee
   `metric_values_ops_never_certified` — `CHECK (NOT (category='ops' AND
   certification_status='certified'))`, i.e. a certified ops figure is
   UNREPRESENTABLE; `dq.issues.category` (ops findings never gate
   certification — the boundary in the other direction, see deviations);
   the two OTP window knobs seeded into app.settings. Category is stamped
   by `headway_calc.persist` FROM THE CALC REGISTRY (`category_for_calc`),
   never from a caller argument. Hard `category='ntd'` WHERE clauses on
   every certifiable read path: `headway_calc/mr20.py`,
   `services/api/.../routers/public.py`, plus the certify route's
   plain-language 409 for ops ids and its `AND category='ntd'` UPDATE
   guard. `services/calc/OPS_DEFINITIONS.md` created with the
   quote-or-own-it discipline: the TCQSM 3rd Edition on-time window and
   both cvh formulations were FETCHED AND VERIFIED from the TRB public PDF
   (verbatim quotes, pp. 5-28/5-29/5-30/5-92, URL + verification date in
   the file); the passage derivation, pairing rules, minimum samples and
   all tolerances are explicitly Headway-owned, versioned, formulas shown.
   NO new REGULATORY_TRACKER rows.

2. **Canonical trip_updates (design point 2)** — migration
   `0025_trip_updates.sql` (hypertable on `feed_timestamp`; COALESCEd
   natural key `(trip_id, feed_timestamp, source_record_id,
   stop_sequence, stop_id)` per the migration-0023 replay discipline) +
   transform `normalize_gtfs_rt_trip_updates` 0.1.0
   (`headway_transform/trip_updates.py`): one row per (TripUpdate,
   StopTimeUpdate) + a trip-level row for no-stop-event updates (CANCELED
   is data); PREDICTIONS LABELED AS PREDICTIONS (`predicted_*` columns,
   frame header timestamp required or the frame quarantines whole;
   delay-only events keep the delay, never a derived time); per-entity
   quarantine, in-frame duplicate keys kept-first + warned; ON CONFLICT
   writer + transform-scoped dq dedupe keys. Consumer + `__main__` route
   the (already-registered) `raw.gtfs_rt.trip_updates` topic.

3. **Observed stop passages (design point 3)** — CALC-INTERNAL derivation
   (`headway_calc/passages.py`, `derive_stop_passages` 0.1.0), NOT a new
   canonical table: the smallest honest design (no second derived-table
   writer/replay surface; lineage flows positions→figure; the choice is
   documented in OPS_DEFINITIONS.md). Deterministic, versioned; the MBTA
   inter-position gap distribution was MEASURED FIRST (full table in
   OPS_DEFINITIONS.md and below) and the tolerances chosen from it:
   closest-approach passage within 100 m (p50 movement between distinct
   reports = 104 m), bounding gap ≤ 120 s (> p99 = 99 s), endpoint
   closest-approaches refused; every refusal counted per reason and
   carried inside every ops figure's `detail.derivation` plus one routed
   `ops_passage_derivation_summary` finding — the per-stop OTP refusal
   the handoff requires is structural.

4. **Calcs (design point 4)** — `headway_calc/ops.py`: `otp_v0` 0.1.0
   (percent inside the CONFIGURABLE window; `otp_early_tolerance_seconds`
   / `otp_late_tolerance_seconds` app.settings knobs seeded 60/300 from
   the VERIFIED TCQSM window, provenance recorded per run exactly like
   coverage_threshold; agency timezone FEED-DECLARED via
   canonical.agencies/migration 0026 + gtfs_static 0.4.0 agency.txt
   parsing — blocking refusal when absent/ambiguous, never guessed) and
   `headway_adherence_v0` 0.1.0 (ONE formula: cvh = population stdev of
   (observed − scheduled headway) / mean scheduled headway over
   consecutive observed pairs at the same route/direction/stop — the
   TCQSM Example-3 formulation, math in OPS_DEFINITIONS.md). Both run
   fleet-wide + per route (`scope='route:<route_id>'`, minimum samples,
   thin routes reported loudly). Goldens hand-worked
   (`tests/golden/ops_v0/BASIS.md`); Hypothesis properties (derivation
   accounting identity + permutation determinism; OTP exact share/count
   partition; cvh ≥ 0, = 0 iff exact). Runner: separate
   `run_ops_period` + CLI `--ops` (ops and NTD figures never share a
   run), same two-transaction fail-loudly-first design, findings routed
   with `category='ops'`.

5. **API (point 5, backend half)** — `MetricValue`/`PublicMetricValue`
   carry `category` on every row; `/metrics/values` and
   `/machine/metrics` accept `?category=ntd|ops` (shared query — the two
   cannot drift); the public certified endpoint hard-excludes ops;
   certify refuses ops ids at 409 with plain language BEFORE the DB CHECK
   would fire. `openapi.json` regenerated (31 paths; the CI drift gate
   passes on the regenerated file). **For the frontend agent:** badge on
   `category === "ops"` with "Operations metric — not an NTD reported
   figure"; note that the TCQSM quotes live in
   `services/calc/OPS_DEFINITIONS.md`, NOT in REGULATORY_TRACKER.md, so
   `web/scripts/extract-quotes.mjs` does NOT extract them today — decide
   whether to extend the extractor to OPS_DEFINITIONS.md or hand-copy the
   two quote blocks; the ops receipt should render the
   `detail.derivation` refusal accounting (it is the cadence evidence
   behind every figure).

**Suites (before → after, all green, 2026-07-13):** transform 83 → 102;
calc 442 → 496; api 196 → 202; db static 21 → 24; tests/integration 5 → 6
(run TODAY against a real throwaway TimescaleDB, see evidence); ingestion
Go suite untouched and re-verified green (`go build/vet/test` ok).

**Deviations from the handoff's letter (reported, not silently absorbed):**

- **"Trip_update records already held" was FALSE on this box.** Kafka's
  `raw.gtfs_rt.trip_updates` end offset was 0 — the ingestion stack had
  never been given a TripUpdates URL (feature-gap #8 evidently described
  the missing normalizer against an assumed feed). Fixed by CONFIG ONLY:
  set `GTFS_RT_TRIP_UPDATES_URL=https://cdn.mbta.com/realtime/TripUpdates.pb`
  in deploy/compose/.env and restarted the ingestion container (no Go
  changes); 113 real MBTA frames were produced during this session and
  103 live-replayed (all frames held at replay start). The URL was then
  RE-BLANKED (comment in .env explains): normalized volume measured at
  ~1.1 GB/hour (25,210 stop-time predictions per 30 s frame) with no
  retention/rollup policy — leaving it on unattended would fill the demo
  box in days. Re-enabling is one env var; see open questions.
- **Migration numbering:** the handoff's "migration 0022" landed as
  0024/0025/0026 (0022/0023 were claimed by the 2026-07-13 hardening
  pass).
- **canonical.agencies (migration 0026 + gtfs_static 0.4.0)** is scope
  the handoff did not name: otp_v0 needs the agency timezone to anchor
  GTFS schedule times, and the honest source is the feed's own
  agency.txt (never a config guess). Smallest addition that keeps
  provenance.
- **dq.issues.category** is also beyond the letter: without it, an ops
  blocking finding (e.g. an OTP cadence refusal) would freeze FEDERAL
  certification via the v0 "any open blocking issue refuses" gate — ops
  contaminating the regulatory workflow in the reverse direction. Only
  `category='ntd'` issues gate certification now; ops findings remain
  owned, workflowed dq rows.
- **Ops runs are a separate runner entry point** (`--ops` /
  `run_ops_period`) rather than a branch inside `run_period`: the
  category boundary applied to orchestration — no code path interleaves
  ops and NTD persistence.
- **The live certify attempt on the real ops id returned the GENERIC
  blocking-issue 409** (32 pre-existing open NTD blocking issues gate
  first, by design); the ops-specific 409 message is proven by the
  real-Postgres integration test (ran today) and unit tests.
- **Derived passages are calc-internal** (no `canonical.stop_passages`
  table) — the handoff allowed either; choice documented.

## Outputs — backend evidence (2026-07-13, live Compose stack)

**1. The measured MBTA inter-position gap distribution (design point 3 —
measured BEFORE choosing tolerances).** Live canonical.vehicle_positions,
2,238,739 within-trip consecutive gaps over [2026-07-09, 2026-07-11):

```
percentiles (s):  p10=0  p25=24  p50=30  p75=34  p90=45  p95=59  p99=99   max=87,220
share of gaps:    >60s = 4.02%   >120s = 0.70%   >300s = 0.21%
duplicate vehicle timestamps (same report re-polled): 12.36%
movement between distinct reports: p50 = 104 m, p90 = 364 m
```

→ tolerances: bounding gap ≤ 120 s (> p99; passage-time uncertainty
≤ ±60 s against a 360 s window), stop radius 100 m (≈ p50 movement),
endpoint refusal. Full rationale: services/calc/OPS_DEFINITIONS.md.

**2. Migrations 0024–0026 applied live** (`db/migrate.py`):

```
applying 0024_ops_metric_category.sql ... ok
applying 0025_trip_updates.sql ... ok
applying 0026_agencies.sql ... ok
```

psql (separate connection): `category` column NOT NULL default 'ntd';
constraint `metric_values_ops_never_certified` present; ops knobs seeded
(`otp_early_tolerance_seconds=60`, `otp_late_tolerance_seconds=300`,
integer).

**3. Live trip_updates ingestion + replay (design point 2), real MBTA
data.** Ingestion (config change only) produced real frames — first frame
measured at 1,274 entities / 25,210 stop-time updates / 746,409 bytes.
Replay of ALL 103 frames held at replay start, through the consumer path
(`process_message` + `DbWriter`, one commit per frame, fresh consumer
group), 1,311 s:

```
canonical.trip_updates: 2,530,502 rows from 103 frames, 2,075 distinct trips,
  predictions spanning 2026-07-13 15:01:47Z .. 15:54:46Z
trip_schedule_relationship: SCHEDULED 2,468,460 / ADDED 36,161 / CANCELED 25,881
trip-level rows (no stop events — cancellations as data): 46
lineage: 2,530,502 edges (exactly one per row), transform
  normalize_gtfs_rt_trip_updates 0.1.0
```

Replay idempotency demonstrated live: the first two frames re-delivered
through `process_message` a second time —

```
before redelivery: rows=50487 edges=50487 raw_records=2
after  redelivery: rows=50487 edges=50487 raw_records=2   → ZERO NEW ROWS: True
```

(scoped by source_record_id because the transform CONTAINER — rebuilt
from this tree and started, it had not been running on this box — was
concurrently landing new frames.)

**4. canonical.agencies populated from the live MBTA static feed**
(newest raw.gtfs_static.feed message replayed whole through the consumer
path at normalize_gtfs_static 0.4.0, committed in 1,162 s):

```
1|MBTA|America/New_York
3|Cape Cod Regional Transit Authority|America/New_York
(2 agency lineage edges; ONE distinct timezone → OTP anchor resolved)
```

**5. LIVE OPS RUN — real MBTA OTP + headway adherence** (`python -m
headway_calc.runner --ops --period-start 2026-07-01 --period-end
2026-08-01`, thresholds from app.settings — tolerance_sources both
`"settings"`):

```
positions_loaded      2,268,231      schedule_rows_loaded  626,239
passages_derived        535,756      persisted 345 rows, blocked 0
derivation (derive_stop_passages 0.1.0):
  occurrences 29,697 (1,600 skipped <3 positions)
  duplicate timestamps collapsed 276,757
  trips observed 26,635 — 4,260 without schedule (RT-only ADDED trips /
    feed drift; counted, never guessed)
  stop-events considered 692,465 → derived 535,756
  REFUSED: not_reached 131,384 · endpoint_unbounded 21,445 · cadence_gap 3,880
    (the cadence evidence; also routed as ops_passage_derivation_summary)

otp_v0 0.1.0 (window −60 s…+300 s, TCQSM-cited, from settings):
  agency OTP = 54.10 %   (on time 289,826 / early 94,663 / late 151,267;
  deviation mean +179.66 s, median +143.00 s; tz America/New_York)
  per-route rows: 172 (min 20 passages). Samples: route:1 44.16 ·
  route:39 49.31 · route:66 46.70 · route:Green-B 44.65 · route:Red 24.25
  (schedule-window OTP reads structurally low on high-frequency subway —
  exactly why headway adherence is the paired metric)

headway_adherence_v0 0.1.0 (cvh):
  agency cvh = 0.3010   (pairs 494,457 over 7,146 stops / 172 routes;
  mean scheduled headway 1742.47 s; stdev of deviations 524.52 s;
  excluded pairs counted: inverted 20,143 · over-cap 10,020)
  per-route rows: 171 (min 10 pairs). Samples: route:1 0.5135 ·
  route:66 0.4476 · route:Red 0.3973 · route:105 0.0918
  routes below min sample (reported, not served): {'171': 19, 'CapeFlyer': 11}
```

psql from a separate connection: 345 computed.metric_values rows, ALL
`category='ops'`, ALL `certification_status='uncertified'`; the agency
OTP row carries 4,368 lineage edges to raw records and its detail JSONB
carries the full derivation accounting; the two run-level ops findings
(`ops_passage_derivation_summary`, `ops_routes_below_min_sample`) are in
dq.issues with `category='ops'`.

**6. Certifiable-path exclusion — live, by attack:**

```sql
UPDATE computed.metric_values SET certification_status='certified'
 WHERE category='ops' AND scope='agency' AND metric='otp';
-- ERROR: new row ... violates check constraint "metric_values_ops_never_certified"
INSERT ... category='ops', certification_status='certified' ...
-- ERROR: same constraint
```

- `POST /certifications` with the real ops id (certifier login): HTTP 409
  (the generic open-blocking-issue gate fires first — 32 open NTD
  blocking issues predate this wave; the count query is now
  `AND category='ntd'`, verified live: blocking issues by category =
  `ntd|32`, ops|0). The ops-specific 409 ("operations metrics … can never
  be certified") is pinned by tests/integration (ran TODAY against a real
  throwaway TimescaleDB with migrations 0001–0026: **6 passed**, incl.
  INSERT/UPDATE attack + certify 409 + ops-blocking-never-gates + public
  exclusion) and by the unit suites.
- `GET /public/metrics/certified` (live, unauthenticated): 2 rows served
  (the certified vrm/vrh), `categories: ['ntd']`, **no ops metric or
  category present** — while 345 ops rows sit in the same table for the
  same period.
- `python -m headway_calc.mr20 --month 2026-07` over the EXACT period of
  the 345 ops rows: package contains **no** "otp", **no**
  "headway_adherence", **no** "ops", and not the ops metric_value_id —
  zero contamination.
- `GET /metrics/values?category=ops` (live, authenticated): 173 otp rows
  (agency + 172 routes) each carrying `"category": "ops"` and the full
  detail for the frontend badge/receipt; `?category=ntd` and the
  vocabulary-422 verified live; the restarted API serves the regenerated
  31-path spec with `category` on MetricValue/PublicMetricValue.

**7. Housekeeping / state left behind:** live API restarted on this tree
with its environment preserved (session secret intact; /branding and
/public/metrics/certified re-verified 200). Transform container rebuilt
from this tree and RUNNING (it was not before) — it is draining the
vehicle_positions/static backlog steady-state. TripUpdates poller
disabled again after evidence capture (see deviations; one env var to
re-enable). Kafka retains all 113 produced trip_updates frames; frames
103–112 land whenever the transform group reaches them.

**Open questions added by this response:**

- trip_updates retention/rollup policy (Platform Architect): ~1.1 GB/hour
  normalized at MBTA scale. Options: continuous aggregate of predictions
  (e.g. latest-per-stop), Timescale retention on raw chunks, or
  ingest-side sampling — pick one before re-enabling the poller
  long-term.
- Prediction-accuracy v1 (the handoff's natural v1) now has both tables:
  103 frames of predictions overlapping ~1 h of positions (2026-07-13
  15:01–15:55Z) already exist to prototype against.
- Frontend: OPS_DEFINITIONS.md quote surfacing (extractor currently reads
  only REGULATORY_TRACKER.md) — see point 5 note above.

## Outputs — frontend evidence (2026-07-13, live Vite :5173 → API :8000)

Design point 5's UI half, delivered against the backend's API shapes above.
All in the working tree, no commits.

**1. The badge, everywhere ops appears.** New `OpsBadge` component
(`web/src/components/OpsBadge.tsx`): "Operations metric — not an NTD
reported figure", verbatim per this handoff — text + gauge icon + info
tokens + 2px border, never color alone; keyed on `category === "ops"`
(`isOps()` in `web/src/detail.ts`; `MetricValue.category` added to
`web/src/api/types.ts`, optional so pre-0024 APIs still render). Rendered
on every ops row in the /metrics table, in every ops receipt's story line,
and on both ops dashboard cards. NTD figures unchanged (pinned by tests +
live check). The boundary also runs the OTHER direction: the certify
cockpit now requests `GET /metrics/values?category=ntd` (the server's own
filter), so an ops figure never appears beside a signature checkbox —
belt on top of the API's 409 and the DB CHECK.

**2. Ops quote surfacing — the namespacing choice (documented here and in
the extractor header).** `web/scripts/extract-quotes.mjs` now ALSO parses
`services/calc/OPS_DEFINITIONS.md` into the SAME
`web/src/regulatory/quotes.json`, under **namespaced `ops:<calc_name>`
keys** with their own shape (`{verified: [{quote, citation}],
headway_owned: [{name, version, summary, formula, reference}]}`). Chosen
over a parallel opsQuotes.json because the CI drift gate (ci.yml)
regenerates and diffs exactly quotes.json — a second file would sit
OUTSIDE the gate and could drift silently; the `ops:` prefix keeps the
FTA namespace unmixed (`quotes.ts` filters `ops:` keys out of the FTA
lookup; new `web/src/regulatory/opsQuotes.ts` is the only reader of the
ops keys — the two namespaces are pinned mutually unresolvable by tests).
Extraction discipline unchanged: TCQSM blockquotes copied
character-for-character (wrap-joining only); citation-only cleanups
(italics, `ibid.` expansion to the already-named manual title, dropping
the "Fetched and verified…" provenance sentence) are enumerated in the
script header; every structural surprise is a hard extraction failure.
Regeneration is idempotent and the committed quotes.json equals the
regenerated one — the gate diff is clean (60 added lines, zero changed
FTA lines). Extracted: otp_v0 2 verified TCQSM quotes (pp. 5-29/5-28) + 2
Headway-owned definitions; headway_adherence_v0 3 verified (pp. 5-30/5-92
×2) + 2 owned (the shared derive_stop_passages definition attaches to
both calcs — it is the derivation inside every ops figure's
detail.derivation).

Ops receipts (`web/src/components/Receipt.tsx`): heading **"The industry
basis inside this number"** (never the FTA heading) → the verbatim TCQSM
quotes in the existing QuoteFigure (solid accent rule) → **"Headway's own
definitions in this number"** → each owned definition as a labeled
`Headway-owned definition` chip + name/version + lead paragraph + the
formula block verbatim + the OPS_DEFINITIONS.md pointer, on a DASHED info
rule — shape-distinct from quoted rules, not just color-distinct, and
never inside a blockquote. Missing basis renders the loud alert, never
silence. The receipt's detail section renders the full
`detail.derivation` accounting in plain language
(`derivationLines`/`refusalLines` in detail.ts + ~30 new ops detail
templates in copy.ts): "131384 passages refused: the vehicle was never
observed within 100 meters of the stop" / "21445 … edge of the observed
window" / "3880 passages refused: cadence too sparse — position reports
around the stop were more than 120 seconds apart", every number verbatim.

**3. Dashboard cards** (`web/src/views/DashboardView.tsx`, new
"Operations metrics" section below the NTD grid, same date-range slice as
everything under the filter row): route-level OTP and cvh cards built on
the existing ChartCard + TimeSeriesChart with the validated `--series-*`
tokens (OTP = slot 1, cvh = slot 2; color follows the entity). Each card:
the OpsBadge; the latest agency figure VERBATIM ("54.10% of observed
passages were on time, agency-wide." / "Agency-wide headway adherence
(cvh): 0.3010."); OTP's on-time/early/late breakdown (289826/94663/151267)
and the configured window read from the figure's own detail (60 s/300 s);
cvh ships the RAW value + formula reference — OPS_DEFINITIONS.md defines
no interpretation bands ("Headway serves the number, never a grade"), so
none were invented — plus the counted pair exclusions (20143 inverted ·
10020 over-cap · 0 unscheduled); the derivation's refusal accounting
under its own "Refused by the derivation (counted per reason)" heading —
shown, never hidden; the agency figure over time as the chart (one point
today — honest; it grows with future ops runs); and the table view
listing agency + all 172 route rows verbatim, each with its provenance
link. No client-side arithmetic anywhere: every displayed figure is the
API's string.

**4. Suites / gates (before → after):**

```
web/ vitest        116 → 128 passed (22 files; new: src/test/ops.test.tsx ×7,
                   src/test/opsQuotes.test.ts ×5; quotes.test.ts updated for
                   the ops namespace + ops fixtures)
axe                0 violations in every new test (expectNoAxeViolations —
                   metrics table with badges, both ops receipts, dashboard
                   with ops cards)
check:contrast     all pairs AA — 6 new entries registered (ops badge border/
                   dashed rule, badge icon on info bg, formula text; light +
                   dark; all reuse already-validated token values)
lint (oxlint)      clean
build (tsc -b + vite)  clean — dist/assets/index-CkWOkXGD.js 498.74 kB
quotes             regeneration idempotent; FTA entries byte-identical
```

**5. LIVE verification — headless Chrome (puppeteer-core) against the
running API, house pattern: real login as `dsteward` through the form,
SPA navigation only** (Vite :5173 with `VITE_API_BASE_URL=
http://127.0.0.1:8000`; origin must be `http://localhost:5173` — the
API's CORS allowlist names localhost, not 127.0.0.1; the API served the
real 345 category=ops rows from the backend's ops run above):

```
signed in as dsteward
PASS  ops agency OTP row found with badge            (54.10, /metrics)
PASS  receipt story carries the ops badge
PASS  industry-basis heading (and NO FTA heading)
PASS  TCQSM window quote verbatim ("1 min early to 5 min late")
PASS  p. 5-29 TCQSM citation
PASS  Headway-owned definitions labeled + distinct (otp_v0 0.1.0 with
      formula + derive_stop_passages 0.1.0, outside any blockquote)
PASS  refusal accounting shown (all three reasons: 131384 / 21445 / 3880)
PASS  walk-to-raw-records link present
PASS  NTD row + receipt (vrh_v0 16326.89 h) carry NO ops badge, keep the
      FTA rule heading — non-contamination in the UI layer
PASS  OTP card: badge + live 54.10% + breakdown + refusals
PASS  cvh card: badge + live 0.3010 + formula reference + exclusions
PASS  OTP card table view: agency + 172 route-level rows (=173 rows)
CLICKTHROUGH PASSED — no page errors
```

Screenshots in the session scratchpad: `shot-ops-otp-receipt.png`,
`shot-ops-otp-rule-section.png` (quote vs owned-definition distinction),
`shot-ntd-receipt-no-ops-badge.png`, `shot-ops-dashboard-cards.png`
(route table), `shot-ops-dashboard-chartview.png`,
`shot-ops-dashboard-dark.png` (both themes eyeballed — badge, chart,
refusal list legible in each).

**Deviations / notes:**

- **quotes.json now carries two shapes** (FTA arrays + ops bundles) under
  one gate — the deliberate trade documented above and in the extractor
  header. If the file's dual role ever grates, splitting it requires
  extending the ci.yml drift gate first (out of this role's scope —
  .github untouched).
- The metric/unit label maps gained `otp`/`headway_adherence` and
  `percent`/`ratio`; the shared derivation definition renders on BOTH ops
  receipts by design (it is each figure's `detail.derivation`).
- `ops_routes_below_min_sample` / `ops_passage_derivation_summary`
  findings already surface through the existing /dq queue
  (dq.issues rows) — no new UI room was needed for them; the per-figure
  refusal accounting is on the cards and receipts as required.
- Housekeeping: Vite dev server left running on :5173 against the live
  API for the maintainer's click-through (`VITE_API_BASE_URL=http://127.0.0.1:8000`).
