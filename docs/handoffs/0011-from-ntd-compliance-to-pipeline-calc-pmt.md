# Handoff: ntd-compliance-engineer → ingestion/transform, backend, ntd-compliance — Passenger Miles Traveled v0

## Context
PMT is the largest NTD number Headway doesn't compute (research report #1). Definitions verified 2026-07-12: tracker section "Verified — Passenger Miles Traveled" (2026 Full Reporting Manual pp. 143–155). The regulatory chain: PMT = sum of distances each passenger traveled (p. 145); 100%-count discipline shares UPT's 2% factor-up rule; the APC scale-up method (pp. 151–152) uses the exact trip-validity checks upt_v0 already implements. TIDES passenger_events (boardings/alightings per trip_stop_sequence) already flow live — what's missing is GEOMETRY: canonical has no stops/stop_times, so per-segment distances don't exist yet.

## Design (binding)
1. **Migration 0019 + transform increment:** canonical.stops (stop_id, name, lat, lon, source lineage) and canonical.stop_times (trip_id, stop_id, stop_sequence, arrival/departure, shape_dist_traveled NULLABLE — preserve NULL, never fabricate) normalized from the GTFS static feed already ingested, with per-row lineage edges like every other normalizer. Replay-fixture tests per transform house style. Live-verify against the MBTA static feed (counts + spot-checked rows via psql).
2. **pmt_v0 calc (services/calc, 0.1.0, tracker row):** per mode/TOS over a period —
   - Per trip: running load by stop_sequence from passenger_events (boardings − alightings, cumulative), × segment distance between consecutive stops. Distance source precedence: GTFS shape_dist_traveled deltas when present; else haversine stop-to-stop (DOCUMENTED DIVERGENCE — understates path distance; flag on every figure it touches). Load must never go negative (existing upt_v0 validation vocabulary).
   - Trip validity: reuse upt_v0's checks (imbalance >10%, negative load) — the manual itself cites them (p. 151, quoted). Invalid/missing trips count against the p. 146 2% factor-up rule exactly as upt_v0 does; beyond 2% → REFUSE with the statistician-approval citation (never silently factor).
   - Goldens: hand-worked multi-stop load-profile fixtures + the Exhibit 44 worked example verbatim (ATL 4.71 × 13,400,000 = 63,114,000 and the per-schedule rows) for the estimator below.
   - **Average-trip-length estimator (Exhibit 44):** given a mandatory-year PMT+UPT pair and current-year UPT, produce estimated PMT per schedule type — a pure function with its own provenance label (estimation method cited), never conflated with computed PMT.
3. **Persistence/API/runner:** wire pmt_v0 into the runner (per-mode scoping like MR-20 metrics), persist with full lineage + threshold provenance; figures from TIDES-simulated sources carry the simulated caveat exactly as UPT does. Existing generic metrics endpoints/UI receipts should surface it without bespoke UI work — verify one PMT figure renders a Receipt end to end (quote extraction: extend the web extract-quotes section map for the PMT tracker section — ONE minimal web change allowed for that mapping only).
4. **Honest scope:** FB once-only rule and DR/VP UPT nuances documented, not silently applied; sampling-plan templates BLOCKED on the 2009 NTD Sampling Manual (not on file — flagged in tracker); APC certification workbook (checklist 1–18) is its own future feature; D-10 form language recorded as reference only.

## Outputs
Migration 0019 + transform normalizer live-verified, pmt_v0 with goldens incl. Exhibit 44, runner/persistence wiring, one live PMT figure computed against real MBTA static geometry + TIDES passenger events (or an honest REFUSE with the gap receipt if coverage doesn't clear — either outcome is a valid live verification), suites green, tracker version row, evidence appended here.

## Open Questions
- 2009 NTD Sampling Manual acquisition (project lead) → unlocks FTA-approved sampling templates tier.
- APC scale-up grouping schemes (p. 151 "group similar vehicle trips") — v1 design with agency-configurable grouping.
- APC benchmarking workbook (checklist items 1–18) — research report #2, natural next wave.
- Shape-based distance via shapes.txt polyline interpolation (upgrade from stop-to-stop haversine fallback).

## Response — pipeline + calc + backend engineer (2026-07-12)

Contract accepted and delivered: migration 0019 (live-applied, psql-verified),
transform `normalize_gtfs_static` 0.3.0 (live-run over the ingested MBTA feed,
counts + spot checks below), `pmt_v0` 0.1.0 + the Exhibit 44 estimator
(goldens incl. the manual's verbatim worked example; tracker row added),
runner/persistence wiring with per-mode scoping and threshold provenance, the
ONE web change (extract-quotes mapping for the PMT tracker section), and the
live end-to-end run. **The live PMT result is an HONEST REFUSAL in every
scope** — the gap receipts are quoted in the evidence and, per this handoff's
own terms, that is a valid live verification; the two data gaps it exposed
are new open questions below.

### Deviations from the letter (reported, per house rule)
1. **`canonical.stop_times` times are stored as INTEGER seconds**
   (`arrival_seconds`/`departure_seconds`, GTFS "noon minus 12 h"
   convention) — GTFS times exceed 24:00:00, so TIMESTAMPTZ/TIME cannot
   hold them; NULL (valid on non-timepoint rows) is preserved.
2. **pmt_v0's blocking finding reuses upt_v0's issue_type**
   `apc_missing_trips_above_fta_threshold` — it is the SAME p. 146 rule;
   the description distinguishes the missing vs invalid split and names the
   raising calc.
3. **The runner exposes no `--shape-dist-unit-miles` flag.** The GTFS spec
   leaves shape_dist units feed-defined, so `compute_pmt` takes the
   conversion as an explicit argument, but a per-feed unit is an agency
   config concern, not a per-run flag — left as an open question (moot for
   MBTA, which omits the column entirely; the run uses the flagged
   haversine fallback).
4. **One throwaway web test** (`pmt-receipt-verify.test.tsx`) was created
   to prove the Receipt renders the pmt_v0 quotes, run green, and DELETED —
   the permanent web change remains exactly the extract-quotes mapping (+
   the regenerated `quotes.json` it produces).
5. **vrm/vrh fleet-scope figures blocked for the verification period** —
   coverage below the 0.95 threshold on [2026-07-09, 2026-07-10) (routed
   `coverage_below_threshold` receipts; pre-existing behavior of that
   period's telemetry, unrelated to this handoff's changes; upt reproduced
   its previously persisted 238100 exactly).

### New open questions (from the live refusal)
- **TIDES `trip_stop_sequence` is ORDINAL, not GTFS `stop_sequence`**
  (verified 2026-07-12 against TIDES-transit/TIDES
  `spec/passenger_events.schema.json`, main branch: "The actual order of
  stops visited within a performed trip. The values must start at 1 and
  must be consecutive along the trip"; the GTFS-referencing field is
  `scheduled_stop_sequence`). canonical.passenger_events (migration 0012)
  does not carry `scheduled_stop_sequence`/`stop_id`, so pmt_v0 can place
  events only where the schedule numbers stops consecutively from 1 — on
  MBTA that holds for most bus trips and NO rail/subway trips (their
  stop_sequences run 1, 10, 20, …), which pmt_v0 refuses rather than
  guesses. Closure: a migration + transform + simulator increment carrying
  TIDES `scheduled_stop_sequence` (and/or `stop_id`) onto
  canonical.passenger_events. Owner: data/transform roles (simulator:
  ingestion).
- **Per-agency shape_dist unit knob** (see deviation 3). Owner: NTD +
  backend roles.
- The tracker's PMT-section note that the sampling tier is BLOCKED on the
  2009 NTD Sampling Manual is now stale (the manual is on file, tracker
  "Verified — NTD Sampling Manual") — left un-edited per the
  coordinator's instruction; sampling work is queued as handoff 0012.

## Outputs — evidence

All commands run 2026-07-12 on the live dev box (Python 3.12.3; compose
stack: timescaledb/kafka/minio/etc. healthy). Nothing committed or pushed.

### 1. Migration 0019 — applied live, verified via separate psql

```
$ cd db && PGHOST=127.0.0.1 PGUSER=headway PGPASSWORD=*** PGDATABASE=headway python3 migrate.py
applying 0019_stops_stop_times.sql ... ok
applied 1 migration(s)

$ docker exec headway-timescaledb-1 psql -U headway -d headway -c '\d canonical.stops' -c '\d canonical.stop_times'
              Table "canonical.stops"
 stop_id TEXT NOT NULL (PK) | name TEXT | latitude DOUBLE PRECISION (nullable) | longitude DOUBLE PRECISION (nullable)
              Table "canonical.stop_times"
 trip_id TEXT NOT NULL | stop_id TEXT NOT NULL | stop_sequence INTEGER NOT NULL |
 arrival_seconds INTEGER (nullable) | departure_seconds INTEGER (nullable) |
 shape_dist_traveled DOUBLE PRECISION (nullable)
 PK (trip_id, stop_sequence); INDEX stop_times_stop_id_idx

$ docker exec ... psql ... -c "SELECT filename, applied_at FROM public.schema_migrations WHERE filename LIKE '0019%';"
 0019_stops_stop_times.sql | 2026-07-12 22:42:01.678464+00
```

### 2. Transform 0.3.0 — live replay of the ingested MBTA static feed

Replayed the content-addressed record
`48dc427161314d54c9eb10138bd630202dfc15f30d8923815dc7a0b86ffa7817`
(payload fetched from MinIO by its raw.records `payload_ref`) through
`gtfs_static.normalize` + `DbWriter` with the consumer's one-commit
transaction boundary:

```
normalized in 28.5s: routes=403 trips=112578 stops=10309 stop_times=3077103 edges=3200393 findings=0
... stop_times upserted in ~350s; 3,200,393 lineage edges inserted in 298.8s; COMMITTED
```

Verified from a SEPARATE psql connection (actual counts):

```
 stops | stop_times | st_edges | stop_edges | v030_edges
 10309 |    3077103 |  3077103 |      10309 |    3200393
```

Spot checks (against the zip's own rows): trip `76389111` seq 1/2/16 →
stop_ids 2444/1059/29001, `10:40:00` → `arrival_seconds` 38400,
`10:56:00` → 39360; stop `2444` = "Western Ave @ Green St"
(42.365266, −71.105242); `node-123-platform` (generic node) stored with
NULL coordinates — 691 such stops, matching the file's 691 coordinate-less
rows; `SELECT count(*) ... WHERE shape_dist_traveled IS NOT NULL` → **0**
(MBTA omits the column; nothing fabricated).

### 3. Test suites (before → after)

```
services/calc      python3 -m pytest tests/ -q   294 → 319 passed
services/transform python3 -m pytest tests/ -q    49 →  58 passed
db                 python3 -m pytest test_migrations_static.py -q  18 → 19 passed
services/api       python3 -m pytest tests/ -q   154 → 154 passed (no API change needed — generic endpoints)
web                npm test -- --run               95 →  95 passed; npm run lint clean; npm run build clean
```

New calc coverage: `tests/golden/pmt_v0/` (BASIS.md + fixture + expected —
hand-worked shape-delta and haversine load profiles, the blocked case
pinning the reason priority and the unoperated-trips-don't-count rule, the
exactly-2% factor-up case, and the **Exhibit 44 worked example VERBATIM**:
60,000,000/12,750,000 → 4.71; 4.71 × 13,400,000 = **63,114,000**; 5.0 ×
10,500,000 = 52,500,000; 3.5 × 2,100,000 = 7,350,000; 4.0 × 800,000 =
3,200,000), `test_pmt.py` (distance precedence, feed-defined-unit
discipline, zero-load identity, degenerate inputs, estimator refusals),
`test_properties_pmt.py` (Hypothesis: order-independence/determinism,
exact p. 146 threshold line, factor bounds, detail-count consistency), and
runner tests updated for the fourth default metric + a geometry
pass-through test.

### 4. Quote extraction (the one web change)

```
$ cd web && npm run extract:quotes
extract-quotes: wrote src/regulatory/quotes.json (pmt_v0: 18, sscls_v0: 39, upt_v0: 8, voms_v0: 4, vrh_v0: 10, vrm_v0: 10)
```

A throwaway render test (created, run, deleted — deviation 4) proved a
Receipt for a `pmt_v0` figure renders the p. 145 definition quote
character-for-character with its citation:

```
✓ renders the p. 145 PMT definition quote, verbatim, on a pmt_v0 Receipt
Test Files 1 passed / Tests 1 passed
```

### 5. LIVE end-to-end run — the honest refusal, with receipts

```
$ cd services/calc && HEADWAY_DATABASE_URL=postgresql://headway:***@127.0.0.1:5432/headway \
    python3 -m headway_calc.runner --period-start 2026-07-09 --period-end 2026-07-10 --per-mode
loaded: 733,312 positions | 111,568 passenger events | 9,123 operated trips | 216,235 stop_times rows
threshold_sources: all four knobs "settings" (migration-0014 rows), imbalance_threshold "default"
persisted: 14  blocked: 16  routed dq issues: 11,054
```

**PMT outcomes (value | missing_or_invalid_share | receipt):**

| scope | outcome | counted (pre-factor) | share vs 0.02 | why |
|---|---|---|---|---|
| agency | **REFUSED** | 140,770.39 mi over 5,785 valid trips | 0.3659 (91 missing + 3,247 invalid of 9,123) | see receipt below |
| mode:bus | REFUSED | 140,388.65 mi over 5,764 valid trips | 0.1339 (70 + 821 of 6,655) | imbalance 130, negative load 73, unplaceable 618 |
| mode:rail | REFUSED | 0.00 | 1.0000 (1 + 206 of 207) | ALL events unplaceable (ordinal vs 1,10,20,… numbering) |
| mode:subway | REFUSED | 0.00 | 1.0000 (0 + 267 of 267) | same |
| mode:tram | REFUSED | 381.73 mi over 21 valid trips | 0.9692 (9 + 652 of 682) | mostly unplaceable |
| mode:unknown | REFUSED | 0.00 | 1.0000 (11 + 1,301 of 1,312) | RT ADDED trips: no schedule → geometry_unavailable |

All counted segments were haversine-priced (`distance_source_segments:
{haversine: 61137, shape_dist_traveled: 0}` fleet-wide — MBTA has no
shape_dist; the `haversine_distance_fallback` info finding was routed).
Every consuming scope also carries the `simulated_source_data` info (all
111,568 events are `tides_simulated`). Sanity anchors: upt agency
reproduced its previously persisted **238,100** exactly; voms agency 984.

**The agency-scope gap receipt (dq.issues
`ad0412e7-e917-4a09-9bdc-6c151c4eb5ed`, verified via separate psql AND
served by the live API):**

> Missing-or-invalid trip share 0.3659 exceeds the FTA 2% threshold: 91
> missing + 3247 invalid of 9123 operated trips
>
> 91 of 9123 operated trips (observed in canonical.vehicle_positions) have
> zero passenger events and 3247 more failed the pp. 151-152 validity
> checks (their load profiles were discarded): missing-data share 0.3659
> exceeds the threshold of 0.02. Per the 2026 NTD Policy Manual p. 146,
> 'if the vehicle trips with missing data exceed 2 percent of total trips,
> agencies must have a qualified statistician approve the factoring method
> used to account for the missing percentage' — a human workflow, so the
> calculation refuses to emit a value (0.02 is the FTA threshold, not an
> engineering placeholder). Missing/invalid trip_ids: 76389382, … (3318
> more). Raised by calculation pmt_v0 version 0.1.0 for period
> [2026-07-09, 2026-07-10) (half-open, UTC). The calculation refused to
> emit a value over this unresolved gap; no computed.metric_values row was
> written.

Separate-psql verification of the persisted refusal state:

```
SELECT count(*) FROM computed.metric_values WHERE metric='pmt';           --> 0
dq rows raised by pmt_v0 in the run:
 apc_missing_trips_above_fta_threshold | blocking |    6   (agency + 5 modes)
 pmt_invalid_trip_excluded             | warning  | 6494   (one per excluded trip, records cited)
 haversine_distance_fallback           | info     |    3
 simulated_source_data                 | info     |    6
```

Live API (uvicorn against the live DB, session-authenticated as the
`dsteward` demo user): `GET /metrics/values?metric=pmt` → `[]` (honest
empty — nothing persisted, nothing invented); `GET /dq/issues?status=open`
serves all six blocking receipts with the full statistician citation (the
agency one quoted above, retrieved through the endpoint).

**Root cause of the rail/subway refusals is a real data-model gap, not a
calc bug** (verified against the TIDES spec, see New open questions):
MBTA schedules number rail/subway stops 1, 10, 20, … while TIDES
`trip_stop_sequence` is ordinal 1, 2, 3, … — pmt_v0 refuses to guess the
mapping. The bus-mode refusal is the simulated events' own imbalance/
negative-load defects plus the 2% line — exactly the pp. 151–152 discard
discipline doing its job on synthetic data.
