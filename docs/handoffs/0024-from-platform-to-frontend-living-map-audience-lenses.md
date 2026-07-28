# Handoff: platform → frontend — The living map + audience lenses (the showpiece wave, frontend half)

## Context
Project lead direction (2026-07-21): take the UI to the next level — make people *want*
to use it. Handoff 0023 (backend half — read its evidence section before starting) ships
the data: `/ops/vehicles/latest`, `/geometry/stops`, `/geometry/routes` (schematic,
self-labeled), `/metrics/history` (bucketed, verbatim), and sub-second DQ counts. This
wave is the visible payoff: the first screen that *draws* the transit system, and the
dashboard learning to speak to boards, executives, and ops supervisors at their own
altitude. Inspiration (Domo-class polish), never imitation — and never at the cost of an
honesty surface.

## Design (binding)

1. **`/map` — the living system view.** MapLibre GL JS (BSD-3 — verify the license and
   satisfy the CI license gate) rendering ONLY self-hosted data: stops and schematic
   route lines from the /geometry endpoints, live vehicles from `/ops/vehicles/latest`
   polled at the endpoint's documented interval. **No external tile/font/sprite requests
   of any kind** — the no-phone-home posture extends to maps; the background is a styled
   solid/water-tone canvas, and the network tab must prove zero third-party requests.
   - The schematic honesty is VISIBLE: a legend line stating route lines are schematic
     (straight lines between stops), mirroring the endpoint's `geometry_kind`.
   - Vehicle affordances: hover/click → popover with route/trip context, position age
     ("as of Ns ago"), and the SIMULATED badge whenever the source row carries the flag.
   - A staleness chip that degrades honestly: "Live — as of HH:MM:SS" while fresh; when
     the feed goes quiet, say so plainly ("no positions in the last N min") — never fake
     motion, never interpolate positions.
   - Ops boundary on the surface itself: the map is badged as operational insight (reuse
     OpsBadge/precedent from 0014), never certified figures.
   - Motion rules from 0021 stand: `prefers-reduced-motion` means markers jump, not
     glide; nothing bad-news ever animates cutely.
   - Empty state teaches (0021 pattern): no vehicles in window → what that means and how
     an agency gets its first dot on the map.
   - Nav placement + a tour step if it fits the existing 5-step tour without bloating it
     (your call; record it).

2. **Audience lenses on the dashboard.** A period selector (day / week / month / quarter)
   driven by `/metrics/history`'s bucket param — **grouping and framing only, never
   client-side arithmetic**: every figure shown is a persisted figure verbatim, deltas
   only via the existing server-computed `/metrics/compare`. Three named presets that are
   just lens configurations (and say so): **Board** (quarter grouping, certified figures
   emphasized), **Executive** (month), **Operations** (day, ops cards forward). Sparkline
   trends on KPI cards where history exists — points are real figures, each clickable to
   its receipt; gaps render as gaps (a missing month is visible absence, not
   interpolation).

3. **Cash in the speed.** Handoff 0021 deviation 2 consumed `/dq/issues/counts`
   per-status-only because of the ~5s query. With 0023's fix live, consume the counts
   properly on /today and /dq, delete the workaround, and re-measure /today first paint
   (budget stands: under 1s; record the number).

4. **Honest scope:** no historical playback/time-scrub (v1 — Open Questions); no
   geocoding/search-the-map; no OTP coloring of vehicles (prediction-accuracy work is
   its own increment); no layout upheaval of existing views; no changes outside `web/`
   (+ this handoff file + docs screenshots if you capture them).

## Outputs
Tests (component + interaction; axe green; contrast pairs pass) + full web suite green;
`npm run build` clean; live click-through in headless Chrome through real login as at
least two roles (map interactions: popover, staleness chip, legend; dashboard: all three
presets + bucket switching + receipt-from-sparkline), screenshots captured; network-tab
proof of zero external requests on /map; /today first-paint re-measurement; evidence
appended here. No commits — the orchestrator integrates and commits.

## Open Questions
- Time-scrub playback (yesterday's service replayed on the map) — the natural v1 demo
  feature once retention policy lands.
- True street geometry pending shapes.txt ingestion (0023 Open Questions) — the legend
  line simply gets better.
- Per-mode dark brand variants (standing queue item) — separate small wave.
- Map screenshot into README hero once the view exists.

## Outputs — evidence

### Response — frontend-engineer (2026-07-22 → 2026-07-28, at commit `ba25f1e` + this working tree)

Contract accepted; all four design points implemented, everything below
verified against the live vite dev server (`localhost:5173`), the live API
(`127.0.0.1:8000`, handoff-0023 code) and the live compose TimescaleDB.
NOTE ON DATES: this wave's verification spanned several days of wall time;
the live vehicle feed's staleness grew from ~15 h to ~157+ h during it
(transform rebalance loop — see "Environment honesty"). Both timestamps in
the transcript below are real.

**What shipped (all under `web/`):**

1. **`/map` — the living system view** (`src/views/MapView.tsx`, code-split
   via `React.lazy` so /today never pays for MapLibre). MapLibre GL JS
   6.0.0 rendering ONLY self-hosted data: stops + schematic route lines
   from `/geometry/*`, vehicles from `/ops/vehicles/latest` polled every
   20 s (inside the endpoint's documented 15–30 s band). Inline style with
   NO tile sources, NO `glyphs`, NO `sprite`, and no symbol layers — there
   is nothing for MapLibre to fetch (proof below). Legend renders the
   server's `geometry_note` VERBATIM (the schematic honesty is visible);
   OpsBadge + the envelope's `ops_note` verbatim on the surface; staleness
   chip is live only while `as_of − newest_position_at ≤ 300 s` (server
   timestamps both) and otherwise states the quiet duration plainly with
   the server's own note verbatim beside it; a labeled window selector
   (5 min / 1 h / 24 h → `max_age_seconds`) shows last-known positions
   without ever faking freshness; per-vehicle detail panel (dot click or
   list row) with route/trip context, verbatim `age_seconds`, source label
   and the SIMULATED badge whenever the row carries the flag; an
   accessible vehicle list table (cap 100, stated in the house render-cap
   voice); teaching empty states for no-geometry and no-vehicles; caps/
   truncation notes verbatim. Nav: "Live map" beside Today.
2. **Audience lenses on /dashboard** (`DashboardView.tsx` + new
   `components/charts/Sparkline.tsx` + `reports/buckets.ts`). A lens bar
   with three named presets — **Board** (quarter, certified leading),
   **Executive** (month, the default), **Operations** (day, ops cards
   forward) — that are stated to be, and are, LENS CONFIGURATIONS only:
   they set `/metrics/history`'s `bucket` param and the section order,
   never a number; the server's `grouping_note` renders verbatim under the
   bar. Hero tiles carry sparkline trends where history exists: every
   point is a persisted figure (a real `<button>` whose accessible name
   carries the verbatim value/period/status), one click from the full
   house Receipt; a calendar bucket with no figure BREAKS the line and the
   absence is stated in words ("N buckets … drawn as a gap, never filled
   in"); certified points differ by shape + words, never color alone;
   point cap 60, stated. Deltas remain exclusively `/metrics/compare`.
3. **Speed cashed in** (design point 3). /today: the 0021 per-status-only
   workaround is DELETED — open + owned (unresolved severity split) plus
   ONE unfiltered whole-queue counts call for the steward's status totals
   (was 4 calls). /dq: the queue-at-a-glance cards now consume
   `GET /dq/issues/counts` (3 calls, milliseconds) and paint the moment
   they land while the 41k-row list downloads beside them, and are
   REFETCHED (server-recounted, never client-adjusted) after every
   resolve/attest. First-paint re-measurement below.

**License gate (MapLibre GL JS):** verified from the installed package —
`maplibre-gl 6.0.0, license: BSD-3-Clause` — and through the real gate:
`python3 scripts/license_gate.py --ecosystem node` →
**“161 deps: 161 pass (5 via reviewed allowlist), 0 fail — LICENSE GATE:
PASS”**, with the entire new chain permissive (maplibre-gl BSD-3-Clause;
@maplibre/* ISC/MIT/(MIT OR Apache-2.0); @mapbox/* ISC/BSD; earcut/kdbush/
potpack/quickselect/tinyqueue ISC; pbf BSD-3-Clause; gl-matrix,
murmurhash-js MIT). No allowlist entry needed. `web/README.md` dependency
table updated.

**Gates (all green, run 2026-07-28):**

```
npx vitest run          → 34 files, 223 tests, all pass
                          (was 32/210 — +13: map.test.tsx 8, lens.test.tsx 5;
                           dq/today tests updated for the counts consumption)
npm run lint            → oxlint, no findings
npm run check:contrast  → 87/87 PASS — "All token pairs meet WCAG 2.1 AA."
                          (+6 registered pairs: map route/stop/vehicle marks vs
                           the water-tone canvas, both themes — SC 1.4.11 ≥3:1:
                           4.09/5.13/5.73 light, 3.19/7.33/8.30 dark)
npm run build           → tsc -b && vite build, clean:
   dist/assets/index-*.js               619.26 kB │ gzip 172.93 kB  (≈ 0021's 606 kB)
   dist/assets/MapView-*.js             938.01 kB │ gzip 244.47 kB  (loaded only on /map)
   dist/assets/maplibre-gl-worker-*.js  467.52 kB                   (worker chunk)
```

Axe is asserted in every new test (map: overlay states, list, panel, both
chip states; lens: bar + sparkline + open receipt), same helper gate as the
whole suite; jsdom cannot run WebGL, so maplibre is a spy double in unit
tests and the canvas behavior was verified live (below).

**Live click-through** (headless Chrome via playwright-core + system
google-chrome 149, real logins as `dsteward` and `certifier`; screenshots +
full transcript in `docs/images/handoff-0024/`, log
`clickthrough-log.txt`):

- **/map, fully live (dsteward + certifier):** stops (9,618 with
  coordinates) and 372 schematic route lines drawn from the live
  `/geometry/*` responses — the whole MBTA system, self-hosted
  (`dsteward-map-quiet-live.png`, `certifier-map-live.png`,
  `certifier-map-dark.png` — the theme toggle repaints the canvas from the
  dark tokens live). Staleness chip: `"No vehicle positions in the last
  157 h 29 min"` with the server's note verbatim beneath ("…the feed is
  stale or service is not running, not an empty fleet.") and the teaching
  first-dot line. The 24 h window honestly returns `"0 vehicles"` — by
  click-through time the feed was OLDER than the API's 86400 s window cap,
  so the UI's refusal to show dots is the correct behavior, captured as
  evidence (`dsteward-map-24h-live.png`).
- **ZERO-EXTERNAL-REQUESTS PROOF:** every request during the whole /map
  session was logged from the browser: **17 requests, origins
  {localhost:5173, localhost:8000} only; EXTERNAL requests (tiles, fonts,
  sprites, anything): 0** — for BOTH roles' sessions. API endpoints
  touched on /map: `/geometry/routes, /geometry/stops, /metrics/compare*,
  /ops/vehicles/latest` (*compare fires from the briefing shell nav, not
  the map). The MapView style is inline with no glyph/sprite URLs, pinned
  additionally by the unit test "makes ONLY same-origin API requests".
- **Renderer proof with REPLAYED REAL rows (loudly labeled):** because no
  real position is younger than the API's 24 h cap anymore, the dot/popover
  interactions were proven by intercepting ONLY `/ops/vehicles/latest`
  with **2,057 real `canonical.vehicle_positions` rows** (read-only SQL,
  the same latest-per-vehicle shape the endpoint serves, TRUE ages
  566,594–1,647,025 s, source labels from `raw.records` — nothing
  fabricated, nothing written). Geometry, auth, app code and the MapLibre
  renderer stayed fully live. Results (`dsteward-map-dots-replay.png`,
  `…-vehicle-panel-replay.png`, `…-canvas-click-replay.png`): 2,057 dots
  over the schematic network; the chip STAYS QUIET beside the dots
  (ages are true — the map never fakes liveness); list cap line "first 100
  of 2,057" stated; list row → detail panel (route/trip context, verbatim
  age_seconds 746,844, `Source feed: gtfs_rt`); **canvas click on the dot
  reopens the popover panel: true** (selection ring shown).
- **Motion rules, proven live both ways** (camera spy on the real map):
  with motion allowed the list-select camera call is `["easeTo"]` (glide);
  under CDP-emulated `prefers-reduced-motion: reduce` (matchMedia=true)
  the same interaction calls `["jumpTo"]` — reduced = instant
  (`dsteward-map-reduced-motion-replay.png`). Vehicle DOTS never tween in
  either mode — deviation note 2 below.
- **/dashboard lenses (certifier):** Executive (month) default with
  sparklines on the hero tiles (`certifier-dashboard-executive.png`);
  Board press → `/metrics/history?bucket=quarter` fired
  (`…-board.png`); Operations press → section order becomes
  `["Operations metrics", "Unlinked passenger trips over time"]` — ops
  cards FORWARD, an order change only (`…-operations.png`); hand-picked
  Week → the Operations preset unpresses (`aria-pressed=false`) and
  `?bucket=week` fired — full live request sequence
  `month | quarter | day | week` recorded. **Sparkline → receipt, one
  click, live figures verbatim:** pressing a VRM point opened the full
  house Receipt reading `"160835.49 miles — Vehicle Revenue Miles (VRM),
  2026-07-01 to 2026-08-01." / "Covers 90.61% of vehicle-trips; 2768
  excluded and documented."` (`certifier-dashboard-spark-receipt.png`) —
  byte-identical to the figure handoff 0023's history evidence quoted.
- **/dq speed (dsteward):** queue-at-a-glance cards (server counts)
  visible **291 ms** after the nav click; the unpaginated 41k-row list
  finished at 11.7 s beside them (`dsteward-dq-counts-first.png` shows the
  cards + list skeleton). Server-side counts latencies re-measured this
  wave: unfiltered 22.8 ms, status=open 18.0 ms (curl total).
- **/today first paint (re-measurement, 0021 method — SPA nav /metrics →
  /today, live API):** **50.9 ms to the first painted frame** (budget
  < 1 s — met ~20×; measured 23.5–50.9 ms across three runs). Full data
  settle: 5.3–10.3 s wall across runs — no longer the DQ counts (now
  ~30 ms): the remaining driver is `GET /safety/deadlines` at ~3.0 s
  server-side (measured 2026-07-22), doubled by React StrictMode's dev
  double-fetch. Recorded as a backend follow-up, not smuggled into scope.
  `dsteward-today-settled.png`.

**Decisions the handoff left to this role (recorded):**

1. **No new tour step.** The five-step tour teaches one thesis (receipt →
   quote → lineage) and lands on "every number can prove itself"; a map
   step would either interrupt that arc or dangle after its finale, and
   the map is one nav click away with its own teaching surfaces. Recorded
   as the "your call" outcome — revisit if a v2 tour ever themes on
   "where to see today's service".
2. **Vehicle dots JUMP for everyone; only the camera glides.** The feed
   reports every ~30 s. Tweening a dot between two reports would draw
   positions no vehicle ever reported — interpolation wearing a costume —
   so dot movement is a jump on new data in BOTH motion modes (the 0021
   letter constrains what reduced motion must be, not what full motion
   must add). The one animation kept is the camera ease on list-select,
   gated to `jumpTo` under reduced motion (proven live above).
3. **`preserveDrawingBuffer: true`** on the map canvas so screenshots
   (agency evidence packs, this project's own click-throughs) capture the
   drawn map instead of a blank canvas; cost is one retained framebuffer.
   A dev-only `window.__headwayMap` handle exists for click-through
   verification (`import.meta.env.DEV` — absent from the production
   bundle).
4. **MapLibre worker URL pinned explicitly.** Found live: MapLibre v6
   guesses its worker as a sibling `maplibre-gl-worker.mjs` of its bundle
   — a file a bundled app never serves — and the failure mode is a SILENT
   stall (sources never parse; no error event; blank map). Fixed with the
   exported `setWorkerUrl` + vite's `?worker&url` bundling, which emits
   the worker as a first-party asset (dist/assets/maplibre-gl-worker-*.js)
   served from this installation — no external request, dev and prod
   alike. Verified live in both modes.

**Environment honesty (ops actions taken, none in the repo):**

- The API had been left running without `HEADWAY_CORS_ORIGINS`, so the
  browser (localhost:5173) could not call it. Restarted the SAME uvicorn
  command with the SAME env (`HEADWAY_SESSION_SECRET` preserved — no
  session invalidation beyond the restart itself) plus
  `HEADWAY_CORS_ORIGINS=http://localhost:5173,http://localhost:4173`. It
  is LEFT RUNNING that way on 127.0.0.1:8000.
- The transform consumer was still rebalance-looping (join → 5 min →
  "Heartbeat poll expired, leaving group" → rejoin, generations 1153 →
  1271 observed). One `docker restart headway-transform-1` was attempted
  (2026-07-23): the loop resumed identically — the fix is transform-side
  (max poll interval / batch commit), OUT of this handoff's scope and
  flagged loudly here. Consequence: `max(time)` in canonical positions
  stayed 2026-07-22T02:58:36Z all wave, which is why the live map's
  quiet-chip state is the star of the live evidence and the dot
  interactions required the labeled replay.
- After multi-day idle, the API's pooled connections went stale and the
  first two requests returned 500 (`psycopg.OperationalError: server
  closed the connection unexpectedly`) before the pool recycled and
  recovered on its own. Backend note: consider `check=ConnectionPool.
  check_connection` (or equivalent) so an idle-broken connection is never
  handed to a request.
- The vite dev server is left running on localhost:5173
  (`VITE_API_BASE_URL=http://localhost:8000`); the diagnostic `vite
  preview` on 4173 was stopped.

**Honest scope — not done / not proven:**

- **Live vehicle dots through the real endpoint were NOT captured**: the
  feed aged past the API's 86400 s window cap mid-wave (transform loop
  above). The dot/popover/badge behaviors are pinned by the 8-test
  map suite (mocked maplibre) and by the labeled replay click-through
  (real renderer, real rows, intercepted response). When the transform
  recovers, the same page goes live with zero frontend changes.
- **The per-vehicle SIMULATED badge live**: no simulated position rows
  exist in the live table (0023 finding stands); the badge is pinned by
  unit test in the list AND the detail panel (`map.test.tsx`).
- `GET /dq/issues` (unpaginated 41k list) still costs ~10–12 s end to end
  on /dq — 0023's recorded backend follow-up; this wave made the header
  independent of it, not the list itself.
- /today full-settle is now bounded by `GET /safety/deadlines` (~3 s
  server-side) — backend follow-up, recorded above.
- Manual screen-reader pass remains the standing gap noted in
  `web/README.md`; keyboard paths were exercised in the automated
  interaction tests (arrow-key chart reader, sparkline buttons, map list
  and panel controls, aria-pressed groups).
- `services/` (beyond the two process restarts described), `db/`,
  `install/`, `deploy/`, `.github/` untouched. `git status` shows exactly:
  modified `web/*` (16 files), new `web/src/views/MapView.tsx`,
  `web/src/components/charts/Sparkline.tsx`, `web/src/reports/buckets.ts`,
  `web/src/test/map.test.tsx`, `web/src/test/lens.test.tsx`, new
  `docs/images/handoff-0024/` (14 screenshots + click-through log), and
  this handoff file. No commits, per the wave's rule.
