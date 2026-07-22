# Handoff: platform → backend — Map data, period history, and speed (the showpiece wave, backend half)

## Context
Project lead direction (2026-07-21): take the UI to the next level — make people *want* to
use it. The frontend showpiece wave (handoff 0024, follows this one) needs three backend
capabilities that do not exist yet. This handoff builds them. The platform already holds
the raw material: `canonical.vehicle_positions` (live MBTA pings, lat/lon since wave 1),
`canonical.stops` (10,309 rows, handoff 0011), and a metric-history table full of persisted
figures — no endpoint has ever served any of it as geometry or as a period series.

## Design (binding)

1. **Speed first (handoff 0021's recorded finding).** `GET /dq/issues/counts` takes
   ~4.6–5s server-side over the live 41k-issue queue, and the API **serializes sibling
   requests** behind it (a concurrent request measured queuing, 0021 evidence). Diagnose
   honestly, then fix both halves:
   - The query: index / partial index / pre-aggregation — your call, but the counts
     endpoints must come in **under 300ms server-side against the live queue**, measured
     and recorded before/after. If you pre-aggregate, staleness must be bounded and
     stated (the Today home shows these numbers as "now").
   - The serialization: identify why siblings queue (sync handlers on one worker, a
     shared connection, whatever it truly is) and fix it so two concurrent requests
     overlap, **proven by a timed concurrent-request transcript**. Do not guess — measure,
     then change, then measure again. The fix must not weaken audit/authz semantics, and
     the full existing suite must stay green.

2. **`GET /ops/vehicles/latest`** — the live-map feed. Latest position per vehicle within
   a staleness window (`max_age_seconds` param, default 300), each row: vehicle id,
   lat/lon, timestamp, age_seconds, route/trip context where the position row carries it,
   and the source label (simulated-source rows keep their flag — the SIMULATED badge must
   be renderable per-vehicle). Top-level `as_of` timestamp. This is **ops category**:
   never certified, never gating certification, same boundary as handoff 0014 (restate it
   in the response envelope the way /ops endpoints already do, or the nearest equivalent).
   Auth: any authenticated session role (viewer+). No pagination (bounded by fleet size);
   cap + count honesty if a pathological feed exceeds a sane cap.

3. **Geometry endpoints for the map.**
   - `GET /geometry/stops` — GeoJSON FeatureCollection of canonical.stops (id, name,
     lat/lon). Bounded, cacheable (ETag or Last-Modified from max ingest time — your
     call, record it).
   - `GET /geometry/routes` — v0 is the **honest schematic**: per route, a polyline built
     from the ordered stop sequence of its most common trip pattern (straight lines
     between stops). The response must label itself schematic (e.g.
     `"geometry_kind": "schematic_stop_sequence"`) — we have never ingested shapes.txt
     and the map must not imply street-level geometry we don't have. shapes.txt ingestion
     is the recorded v1 increment (Open Questions), NOT this wave.

4. **`GET /metrics/history`** — the period-series endpoint for audience views. Persisted
   figures ONLY, verbatim, straight from the metric-values store: filterable by metric,
   mode, version; each point carries the metric_value id (receipt-linkable), period
   start/end, value, simulated/certification flags. A `bucket` param
   (`day|week|month|quarter`) assigns each figure a bucket key derived from its period —
   **grouping, never arithmetic**: the server must not sum, average, or otherwise invent
   numbers that no calc produced (a quarterly rollup is a calc's job — Open Questions).
   Ordering stable, window params (`from`/`to`), response bounded with cap honesty.

5. **Honest scope:** no websockets/SSE (the map polls; record the poll-interval guidance
   in the endpoint docstring); no tile serving or proxying (the frontend ships
   self-hosted data only — the no-phone-home posture extends to maps); no new calcs; no
   changes under `web/` (parallel/next wave owns it); ops/NTD boundary untouched.

## Outputs
New endpoint tests (authz matrix included) + full existing API suite green; live
verification against the running stack (real measured latencies before/after for finding
1 with a concurrent-request transcript; live vehicle rows if the positions poller is
current — if the live feed is stale, say so and verify with what exists, reporting data
age honestly); `openapi.json` regenerated (drift gate); README updates
(`services/api/README.md` verification section); migration(s) if any indexes/pre-aggregates
need them (next number: 0032); evidence appended here. No commits — the orchestrator
integrates and commits.

## Open Questions
- shapes.txt ingestion (transform + migration + backfill) for true street geometry —
  v1 of /geometry/routes.
- Quarterly/annual rollup figures as a proper calc (with receipts) so audience views can
  show true aggregates rather than grouped monthlies.
- Push transport (SSE) if polling ever measurably hurts; per-agency map center/zoom as a
  branding/settings row.

## Outputs — evidence
(appended by the implementing agent)

### Response — backend-engineer (2026-07-22, at commit `ba25f1e` + this working tree)

Contract accepted. All four design points implemented; everything below was
measured against the LIVE compose TimescaleDB (41,646-row dq.issues queue;
15,016,508-row canonical.vehicle_positions hypertable; 10,309 stops; 119,411
trips; 3,139,223 stop_times; 440 metric values).

**Environment honesty, first:** when this wave began, the compose `app`
profile (api + web containers) and any host uvicorn were NOT running — only
the infra containers (timescaledb, kafka, minio, ingestion, transform,
grafana, prometheus, apicurio) were up. I ran the API the way handoffs
0012/0020 did: host uvicorn on `127.0.0.1:8000` from `/home/daniel/venv`
against the live compose TimescaleDB — once on UNMODIFIED code for the
before-measurements, then restarted with this wave's code (restart recorded
here; only the API process was touched — no other compose service was
restarted or reconfigured). Because the previous API process was gone, its
in-memory session secret was unrecoverable; the restarted API uses a fresh
`HEADWAY_SESSION_SECRET`, so previously issued session tokens are invalid
and users must sign in again (tokens are 30-minute-lived anyway). For
measurement auth I created a temporary viewer account `wave23_probe`
directly in auth.users, and DELETED it after the measurements (its
login/login_failed audit events remain in the append-only trail, as they
should). The API was left RUNNING on 127.0.0.1:8000 with the new code for
the frontend wave (0024).

### 1. Speed: /dq/issues/counts before → after, and the serialization fix

**Diagnosis (measured, not guessed).** Two separate defects:

1. *The query wasn't the problem — the Python was.* `count_issues()`
   composed `list_issues()`: it fetched ALL rows (41,646) over the wire,
   built a Pydantic `DqIssue` per row, and counted in Python. The
   equivalent SQL count on the same live queue:

   ```
   headway=# SELECT severity, status, count(*) FROM dq.issues GROUP BY severity, status;
    info     | open     |  3586
    warning  | open     | 37749
    blocking | open     |    30
    blocking | resolved |   279
    blocking | attested |     2
   Time: 64.818 ms   (first run, cold; EXPLAIN ANALYZE Execution Time: 20.876 ms —
                      HashAggregate over a 41,646-row seq scan, 24 kB memory)
   ```

   ~21 ms in the database vs ~5 s in the endpoint ⇒ **no index, partial
   index, or pre-aggregation is warranted; migration 0032 was NOT created**
   (nothing schema-side was slow — recorded here as the "your call"
   decision). No pre-aggregation ⇒ **zero staleness**: every request counts
   the live rows, so the Today home's "now" stays now.

2. *Siblings queued on ONE shared psycopg3 connection.* The app held a
   single long-lived connection on `app.state.db`; handlers are sync (run
   in FastAPI's threadpool), and psycopg3 serializes concurrent `execute()`
   calls on one connection behind its lock — so any slow request head-of-
   line-blocked every sibling (0021 measured a sibling at 14 s).

**Fixes.**
- `count_issues` now issues `SELECT severity, status, count(*) FROM
  dq.issues [WHERE status = %s] GROUP BY severity, status` — the SAME table
  and SAME optional filter as `GET /dq/issues` (the 0017 cards-match-table
  guarantee holds: same WHERE, grouped not re-derived; unexpected vocabulary
  still surfaces under its own key). Counting rows is grouping, not figure
  arithmetic — no reported number is originated.
- Production now opens a `psycopg_pool.ConnectionPool` (min 2 / max 8,
  `HEADWAY_DB_POOL_MIN`/`_MAX` overridable) in the lifespan; `get_db` yields
  a pooled connection PER REQUEST. `psycopg-pool` is the same upstream as
  psycopg and was already pre-approved on `scripts/license_allowlist.toml`
  ("if/when the pool extra is enabled") — pyproject now uses
  `psycopg[binary,pool]`. Every pooled connection is configured
  `autocommit=True` via the pool's `configure` hook — the 2026-07-10
  phantom-write invariant, re-pinned by an updated
  `test_transaction_discipline` test at the new layer, plus a new test that
  an injected `app.state.db` (the whole unit suite) means no pool and
  unchanged behavior. Audit/authz semantics untouched: same dependency
  shape, same per-request `with db.transaction():` atomic write+audit
  blocks, now each on its own connection. Four handlers that called
  `get_db(request)` directly (public ×2, branding ×2) moved to
  `Depends(get_db)` — no behavior change.

**BEFORE (unmodified code, live 41,646-issue queue, curl total time):**

```
BEFORE counts unfiltered run1: total 5.911330s
BEFORE counts unfiltered run2: total 4.774456s
BEFORE counts unfiltered run3: total 4.884408s
BEFORE counts status=open run1: total 5.033712s
BEFORE counts status=open run2: total 4.342433s
BEFORE counts status=resolved ALONE: total 0.001501s   (281 rows — cheap)
--- serialization proof: fire A, then B 0.5 s later ---
BEFORE concurrent A (counts unfiltered):                total 4.974246s
BEFORE concurrent B (counts status=resolved, +0.5s):    total 3.724934s   ← 1.5 ms of work QUEUED ~3.7 s
```

**AFTER (this wave's code, same live queue, same probe user):**

```
AFTER counts unfiltered run1: total 0.036559s
AFTER counts unfiltered run2: total 0.049102s
AFTER counts unfiltered run3: total 0.032688s
AFTER counts status=open run1: total 0.020290s
AFTER counts status=open run2: total 0.031357s
served body: {"total":41646,"by_severity":{"blocking":311,"warning":37749,"info":3586},
              "by_status":{"open":41365,"owned":0,"resolved":279,"attested":2}}
              (cross-checked cell-for-cell against the psql GROUP BY above;
               open=41,365 matches 0021's recorded queue exactly)
```

Counts endpoint: **4.77–5.91 s → 33–49 ms** (curl-total, which bounds
server-side from above) — under the 300 ms requirement with ~8× margin.

**Concurrency proof AFTER (timed concurrent-request transcript).** The
unfiltered `GET /dq/issues` LIST still takes ~5.6 s (41k Pydantic rows —
out of this handoff's scope, honestly noted below), which makes it the
perfect slow sibling:

```
start 18:17:17.170 UTC
AFTER concurrent A (GET /dq/issues unfiltered, 41,646 rows): status 200 total 5.724151s
AFTER concurrent B (counts status=resolved, fired +0.5s):    status 200 total 0.013172s
AFTER concurrent C (counts unfiltered,      fired +0.7s):    status 200 total 0.022604s
```

B and C completed in 13/23 ms WHILE A had ~5 s left in flight — before the
fix the identical B shape queued 3.7 s. Two requests provably overlap.
`pg_stat_activity` showed 3 pooled client connections from the API during
the runs. Pooled writes verified real: a failed login through the running
API → `audit.events` row 902 (`wave23_probe`, `login_failed`) confirmed
from a separate psql connection (the autocommit-phantom-write check, now on
a pooled connection).

### 2. GET /ops/vehicles/latest (live)

Data-age honesty first: the canonical feed was STALE during verification —
the ingestion container was producing raw GTFS-RT frames every 30 s, but
the transform consumer was stuck in a Kafka rebalance loop ("Heartbeat poll
expired, leaving group" repeating), so `max(time)` in
canonical.vehicle_positions was `2026-07-22 02:58:36+00` (~15.3 h old).
That is a pipeline ops issue OUTSIDE this handoff's scope (no transform/
changes allowed); the endpoint's honesty path is exactly what it exercised:

```
GET /ops/vehicles/latest                       → 200 in 0.013s
  vehicle_count 0, category "ops", as_of 2026-07-22T18:17:37Z,
  newest_position_at 2026-07-22T02:58:36Z,
  note: "No vehicle has reported a position in the last 300 seconds. The
         newest position on record is 55141 seconds old — the feed is stale
         or service is not running, not an empty fleet."

GET /ops/vehicles/latest?max_age_seconds=86400 → 200 in 1.976s, 337,533 bytes
  1,002 real MBTA vehicles, total_in_window 1002, truncated false; sample:
  {'vehicle_id':'1702','latitude':41.8327...,'longitude':-71.4128...,
   'age_seconds':59824,'trip_id':'SouthBase-826224-881',
   'route_id':'CR-Providence','source':'gtfs_rt'}
  simulated rows in window: 0 (the live rows are all real-feed; the
  simulated flag is pinned by unit test on a 'tides_simulated' source row)
```

Query plan verified: ChunkAppend with time-index scans (the 300 s window
answers in ~13 ms; the deliberately pathological 24 h window costs ~2 s —
the default is the map path). DISTINCT ON (vehicle_id) … ORDER BY time DESC,
LIMIT cap+1, `count(DISTINCT vehicle_id)` only when truncated.

### 3. Geometry endpoints (live)

```
GET /geometry/stops → 200 in 0.105s, 1,447,124 bytes
  ETag "stops-bf26b2fcb5e005fac199ea127ec357f3", Cache-Control: private, max-age=300
  stop_count 9618, stops_without_coordinates 691 (9618+691 = 10,309 ✓ —
  the 691 are GTFS generic nodes/boarding areas, counted, never invented),
  sample feature: Point [-71.082754, 42.330957], {"stop_id":"1","name":"Washington St opp Ruggles St"}
GET /geometry/stops (If-None-Match) → 304 in 0.034s, 0 bytes
```

Cache-validator choice (recorded per the handoff's "your call"):
canonical.stops carries NO ingest-time column (static-feed rows are
upserted; provenance lives in lineage.edges, and a max() over the 30M-row
edges table is not a cheap validator), so the ETag is a strong CONTENT hash
over the served fields (stop_id, name, lat, lon; ~10k rows hashed in
milliseconds). It changes exactly when the served geometry would. The 304
saves serialization + 1.4 MB transfer; the row read still runs (recorded
honestly). Unit test proves: same content ⇒ same ETag ⇒ 304; moved stop ⇒
new ETag ⇒ 200.

```
GET /geometry/routes (cold)   → 200 in 3.644s, 266,019 bytes
  geometry_kind "schematic_stop_sequence" (collection AND every feature),
  route_count 372, routes_without_geometry 4, total_routes_with_trips 376,
  computed_at 2026-07-22T18:18:17Z, cache_ttl_seconds 900;
  sample: route "Red" (Red Line, mode subway): 17-stop pattern from 613
  trips, 17-point LineString, 0 missing coordinates
GET /geometry/routes (warm)   → 200 in 0.004s   (per-process cache)
GET /geometry/routes (If-None-Match) → 304 in 0.002s, 0 bytes
```

The pattern aggregation (most common trip pattern per route, deterministic
tie-break `trip_count DESC, stop_ids`) walks all 3.1M stop_times rows:
3.87 s in psql, 3.64 s end-to-end. An index cannot remove an
every-row aggregation and a materialized pre-aggregate would need transform-
side refresh (out of scope), so the honest fix is a per-process cache with
the staleness BOUNDED AND STATED IN THE RESPONSE (`computed_at`,
`cache_ttl_seconds` 900 — schedule geometry changes only when a new static
feed lands) — and with the pool, a cold 3.6 s compute no longer blocks any
sibling request. Migration 0032 not needed here either.

### 4. GET /metrics/history (live)

```
GET /metrics/history?metric=vrm&bucket=month → 200 in 0.007s
  bucket month | point_count 18 | total_matching 18 | truncated false
  2026-07: [('agency','160835.49','57e6c406…','uncertified',sim=False),
            ('mode:bus','114462.66',…), ('mode:rail','21333.17',…),
            ('agency','12794.92','b3ebdef6…','CERTIFIED',sim=False), …]
GET /metrics/history?metric=upt&bucket=quarter → 200 in 0.004s
  buckets: [('2026-Q3', 19 points)]; sample point VERBATIM:
  {'metric':'upt','scope':'agency','period_start':'2026-07-09',
   'period_end':'2026-07-10','value':'238100','calc_name':'upt_v0',
   'calc_version':'0.1.0','certification_status':'uncertified',
   'simulated':True,'category':'ntd'}
```

`'238100'` is byte-identical to the figure 0021's delta example quoted —
verbatim end to end. Buckets carry ONLY `{bucket_key, points}` (pinned by
test: no aggregate field exists for the server to have computed); every
point is the full metric-value row + the export surfaces' `simulated` label
(derived from detail.source_mix — a label, not a number). Filters: metric /
mode (= scope `mode:<mode>`) / exact scope / calc_version / from / to;
mode+scope together is a plain-language 422. Cap 5,000 points with
truncated + total_matching + note honesty.

### Tests, contract, gates

- `pytest tests/ -q` (services/api): **332 passed** (was 296) — 35 new
  tests across `test_ops_vehicles.py` (11), `test_geometry.py` (11),
  `test_history.py` (13), plus the transaction-discipline lifespan test
  replaced by two pool-invariant tests. Authz matrix per new endpoint:
  anonymous → 401 on all four; viewer (and, for /ops, every role) → 200;
  param-abuse 422s (max_age bounds, unknown bucket, mode+scope) covered.
- `openapi.json` regenerated: OpenAPI 3.1.0, **54 paths** (50 + the four
  new endpoints) — the drift gate input is current.
- FakeConn extended honestly (GROUP BY counts, DISTINCT ON latest-vehicle,
  stops/patterns, history filters + LIMIT); the fake's dq counts branch
  mirrors the real WHERE so the cards-match-table test still composes.
- `services/api/README.md`: endpoint table (+4 rows, counts row updated),
  Running section (pool + env vars), Verification status entry added.

### Honest scope — what was NOT live-verified / not done

- **Migration 0032 was not needed** — recorded rationale above (counts:
  the DB was already fast; vehicles: existing time index + chunk exclusion;
  routes: aggregation is cached, an index can't remove an every-row walk).
  `db/migrations/` is untouched.
- **The per-vehicle `simulated=true` path was proven by unit test only**:
  the live window's 1,002 rows are all real `gtfs_rt` rows (no simulated
  TIDES vehicle-position rows exist in the live table; the TIDES simulator
  feeds passenger_events, not positions).
- **The live vehicle feed was 15.3 h stale** during verification (transform
  consumer rebalance-looping — ops issue outside this handoff's scope, left
  untouched per the no-transform-changes rule; flagged here loudly). The
  endpoint's staleness honesty (note + newest_position_at) is exactly what
  a map user would see right now.
- **`GET /dq/issues` (the unfiltered 41k-row LIST) still takes ~5.6 s**
  server-side — Python/Pydantic row assembly. The handoff scoped the COUNTS
  endpoints (<300 ms: met) and the serialization (fixed: it no longer
  blocks anyone). Pagination of the list endpoint is a natural follow-up
  (would change the frontend contract; recorded, not smuggled in).
- **Truncation/cap paths** (vehicles > 5,000, stops > 50,000, routes >
  2,000, history > 5,000) were proven by unit test with lowered caps — the
  live data is smaller than every cap, honestly stated.
- The routes cache is **per-process** (matches the single-process uvicorn/
  container deployment); a multi-worker deployment would compute it once
  per worker — bounded, stated, acceptable.
- `web/`, `services/calc/`, `services/transform/`, `install/`, `deploy/`,
  `.github/` untouched, per scope. `git status` shows exactly:
  services/api/* (modified + new routers/tests), services/api/openapi.json,
  services/api/README.md, and this handoff file.
