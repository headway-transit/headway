# Handoff: ntd-compliance-engineer → ingestion, transform, calc, backend, frontend — Demand Response / on-demand module v0 (queued behind handoffs 0011 + 0012)

## Context
DR definitions verified 2026-07-12 (tracker: "Verified — Demand Response / on-demand reporting"). Every fixed-route urban operator legally runs ADA complementary paratransit, so DR reporting is a mandatory report section for the whole target market; on-demand microtransit (Via-class TNC/TX contracts) reports under the same mode with TOS-specific rules. DR data originates in dispatch platforms, NOT GTFS-RT — this module adds Headway's second data-source family. DO NOT start this build until handoffs 0011 (PMT, in flight) and 0012 (sampling, queued) have landed — shared files in services/calc.

## Design (binding)
1. **Wire contract (contracts/, ADR-0006 discipline):** `demand_response_trip` record — trip_id, vehicle_id, mode (DR), tos (DO|PT|TX|TN), request/dispatch/pickup/dropoff timestamps, pickup/dropoff locations, odometer or GPS distance for the passenger-onboard segment(s), passengers (riders, attendants_companions — non-employee rule), ada_related flag, sponsored flag (+ sponsor label), no_show flag, interruption markers (lunch/fuel/garage-return), driver-shift/dispatching-point references for deadhead legs. Versioned, documented, vendor-neutral; a Via-style CSV export maps onto it as the worked example in docs (adapter code optional, docs mandatory).
2. **Intake (ingestion/backend):** reuse the TIDES pattern — file-drop connector + authenticated machine-API push (`POST /ingest/dr/trips`), content-addressed raw records, envelope wire contract, store-before-produce. Simulator (tools/, like tides-simulator) generating spec-valid dispatch days incl. no-shows, interruptions, multi-passenger shared rides, defect-injection flags. SIMULATED source labeling rules identical to TIDES.
3. **Canonical (migration 002x + transform):** canonical.dr_trips (+ segments if needed for TX passenger-onboard-only accounting), per-row lineage.
4. **Calcs (services/calc, each with tracker rows + goldens from the quoted rules):**
   - `dr_vrh/dr_vrm v0`: Exhibit 36 semantics — revenue span from first pickup to last dropoff per vehicle-day, BROKEN by garage/dispatch returns and lunch/fuel interruptions; empty travel between consecutive passengers = revenue; no-show trips = revenue; deadhead legs per the six quoted leg types; TX variant: passenger-onboard time/distance only; TX/TN/VP report no deadhead. Goldens: every Exhibit 36 row as a fixture; a hand-worked vehicle-day.
   - `dr_upt v0`: riders + non-employee attendants/companions; ADA-related split (included in total, never sponsored); sponsored split (included in total). No-shows are NOT boardings (revenue time yes, UPT no — the asymmetry deserves an explicit golden).
   - `dr_voms v0`: max simultaneous vehicles in revenue service INCLUDING atypical days (divergence from voms_v0's non-DR exclusion — do not reuse blindly). Golden: Exhibit 40 Happy Transit (6 unique, 4 simultaneous → 4).
   - DR PMT: passenger-onboard distance sums from the wire contract's distances (feeds pmt_v0's persistence/mode scoping; no load-profile reconstruction needed).
5. **API/UI:** trips land in existing metrics/receipt surfaces; one DR-specific UI affordance only — the mode/TOS badge and TX/TN rule callouts on receipts (quote-extract pattern; extend section map for the DR tracker section). Honest-scope banners: no vendor integrations shipped, wire contract + simulator only.
6. **Honest scope:** shared-vehicle multi-agency rule and PT full-cost/buyer-reports rules are documented guidance (copy + docs), not silent logic; TX "voucher programs are not public transportation" surfaced as an intake validation hint.

## Outputs
Wire contract + docs, intake path live-verified (simulator → machine API → canonical via psql), four calcs with Exhibit-36/40 goldens, live end-to-end DR figures (or honest refusals) from a simulated dispatch day, suites green, tracker rows, evidence here.

## Open Questions
- Real vendor adapters (Via Connect export field mapping first) — needs a real export sample; ROADMAP.
- GTFS-Flex service-description ingestion (D5) — complementary, separate increment.
- DR-specific dashboard views (response times, shared-ride rate) — ops analytics tier, after OTP/headway-adherence wave.

## Response — ingestion/transform/calc/backend (2026-07-13)

Design points 1–4 and the API portion of 5 accepted and delivered; web/ is
untouched (frontend agent's scope). Deviations from the letter of the design,
with reasons:

1. **DR PMT is its own calc version (`dr_pmt_v0` 0.1.0) feeding the existing
   `pmt` metric persistence** (`persist._METRIC_BY_CALC_NAME` maps it to
   `pmt`) rather than literally invoking `pmt_v0` — pmt_v0's surface is
   stop-sequence load profiles; the DR path is onboard-distance sums per the
   design's own "no load-profile reconstruction needed". The persistence,
   mode scoping and metric surfaces are shared exactly as designed.
2. **No `canonical.dr_segments` table.** The design offered "+ segments if
   needed for TX passenger-onboard-only accounting" — not needed: TX onboard
   hours are the union of per-booking [pickup, dropoff] windows and TX miles
   come from the per-booking onboard fields / boundary odometer pairs. The
   reasoning is documented in migration 0021's header; revisit only if a
   vendor exports sub-trip onboard segments.
3. **The wire contract adds optional `pickup_odometer_miles` /
   `dropoff_odometer_miles`** beyond the listed fields: Exhibit 36 prices
   empty inter-passenger travel as REVENUE miles, and odometer pairs are the
   only vendor-neutral way to measure it (and whole revenue spans) exactly.
   Without them dr_vrm contributes 0 for those legs and warns
   (`dr_distance_unmeasured` — documented undercount, never interpolated).
4. **No DR thresholds exist** — deliberately. No completeness threshold is
   quoted in the tracker's DR section, and borrowing the p. 146 100%-count
   rule from the UPT context would be a regulatory number from the wrong
   context. The DR calcs therefore NEVER block; every gap is a warning with
   its direction stated (undercount/overcount), and "threshold provenance"
   for DR rows is this recorded absence (tracker rows dr_*_v0). The existing
   runner knobs and their provenance are unchanged.
5. **DR figures compute on every runner path** (not only `--per-mode`):
   they are inherently mode-level (dispatch data, not the GTFS-RT fleet), so
   they persist under scope `mode:DR` + `mode:DR:tos:<tos>` whenever the
   period holds `canonical.dr_trips` rows — and NEVER under `agency`.
   `mode:DR` uses the NTD mode code (the wire contract's vocabulary); the
   GTFS-derived scopes use the transform's lowercase names (`mode:bus`), so
   the namespaces cannot collide.
6. **Topic `raw.dr.trips` added to `contracts/topics.v0.md`** (+ the compose
   bootstrap-kafka list) under this handoff's binding design point 2.
   Topics are Platform Architect governance — flagging for ratification;
   the registry row cites this handoff.
7. **TOS partition is vehicle-day-granular** (`headway_calc.dr.
   partition_by_tos`): a MIXED-TOS vehicle-day is contradictory (the TOS
   selects the revenue rule) and is excluded with a warning at mode level;
   the partition keeps such a day WHOLE in every TOS bucket it touches so
   each per-TOS figure re-detects and re-excludes it — per-TOS values are
   exactly the mode figure's decomposition (property-tested).
8. **Design point 6 honest scope**: shared-vehicle rule, PT full-cost/buyer
   criteria and the TX voucher rule are documented guidance in
   `contracts/demand-response-trip.v0.md` (docs mandatory ✓); the voucher
   intake-validation surface beyond docs is UI copy (frontend's slice).

Open item for the NTD role: unmarked garage/dispatch returns silently
inflate a revenue span — the interruption markers' completeness is a vendor
onboarding requirement (recorded in the dr_vrh_v0 tracker row).

## Outputs — backend evidence (2026-07-13)

**Deliverables landed** (no commits — working tree only, per instruction):
wire contract `contracts/demand-response-trip.v0.schema.json` + docs with
the worked Via-style CSV mapping (`demand-response-trip.v0.md`); topic
`raw.dr.trips` registered; Go file-drop connector
`services/ingestion/connectors/dr/` + `DR_DROP_DIR`/`DR_SOURCE` wiring;
machine push `POST /ingest/dr/trips` (scope `ingest:dr`, source-label
binding generalized to all ingest scopes); simulator `tools/dr-simulator/`
(shared rides, no-shows, lunch/fuel/garage interruptions, 4 defect flags);
migration `db/migrations/0021_dr_trips.sql` (hypertable + contract CHECKs);
transform `headway_transform/dr_trips.py` (+ writer/consumer/`__main__`);
calcs `headway_calc/dr.py` (dr_vrh/dr_vrm/dr_upt/dr_voms/dr_pmt 0.1.0 +
by-TOS) with 5 tracker rows; runner/persist/reader wiring; goldens
`tests/golden/dr_v0/` (fixture + expected + hand-worked BASIS.md: every
Exhibit 36 row as table pin AND behavioral scenario; the full hand-worked
vehicle-day; Exhibit 40 Happy Transit 6-unique/4-simultaneous → 4; the
explicit no-show revenue-yes/UPT-zero golden).

**Suites (before → after this increment):**

```
services/calc       406 → 436 passed   (pytest -q)
services/api        179 → 188 passed
services/transform   58 →  66 passed
db static            20 →  21 passed
tools/dr-simulator    – →  14 passed   (new)
tools/tides-simulator  9 →   9 passed
services/ai         109 → 109 passed   (untouched)
Go ingestion: go build ./... && go vet ./... && go test ./... -count=1
  → all ok incl. new connectors/dr (26 test funcs total, was 20)
web/: git status --porcelain web/ → 0 changes (untouched)
```

**Migration live-applied + psql-verified (separate docker-exec connection):**

```
$ python3 db/migrate.py            # PG* env
applying 0021_dr_trips.sql ... ok
$ docker exec headway-timescaledb-1 psql -U headway -d headway -c \
    "SELECT filename FROM schema_migrations ORDER BY filename DESC LIMIT 1"
 0021_dr_trips.sql | 2026-07-13 07:39:43+00
\d canonical.dr_trips → hypertable on pickup_timestamp; unique index
(dr_trip_id, pickup_timestamp, source_record_id); CHECKs: tos enum,
dropoff>=pickup, sponsor iff sponsored, no-show-zero-boardings, NUMERIC
distances >= 0.
```

**Live end to end — simulator → BOTH intake paths → Kafka → transform →
canonical → runner → API:**

1. Simulator (SIMULATED data): day 2026-07-14, seed 42, defect injection
   `--negative-duration-share 0.04 --missing-distance-share 0.04
   --ada-sponsored-conflict-share 0.03` → 48 rows / 6 vehicles (DO:3, PT:2,
   TX:1); day 2026-07-15, seed 43, clean → 49 rows.
2. Topic created (`kafka-topics.sh --create raw.dr.trips`, now also in the
   compose bootstrap list).
3. **File drop** (day 1): `headway-ingest` with `DR_DROP_DIR=…`
   `DR_SOURCE=dr_simulated` against live Kafka (127.0.0.1:29092) + MinIO:
   `record_id 3cd0f7d58f2225f90e6d4d4c88494fbeb9d0244e6940ce56ae582aa49cb0ceaa`
   landed at `raw/dr/<id>.csv`, produced to `raw.dr.trips`, file moved to
   `processed/`.
4. **Machine push** (day 2): demo API restarted with its env preserved from
   `/proc/<pid>/environ` (session secret survives — demo sessions intact)
   plus the S3/KAFKA ingest seams. `certifier` login → `POST /machine/keys`
   issued key `hwk_CZnZe-Oz…` (scopes `["ingest:dr"]`, source_label
   `dr_simulated`; issuance refuses ingest keys without a source label) →
   `POST /ingest/dr/trips` → 202
   `{"record_id":"74c010a70d3025ec2366a666a3a2b7641e0b0660d69479e2d9b504336e0f67e2","parse_status":"ok"}`
   — equal to `sha256sum` of the pushed file (content addressing proven).
5. **Transform** (the real library path — `KafkaMessageSource` →
   `consumer.run_loop` → `DbWriter` over psycopg + MinIO fetcher, scoped to
   `raw.dr.trips` under a dedicated consumer group):
   `processed 2 raw.dr.trips message(s)`.
6. **Canonical psql-verified (separate connection):**

```
    source    | service_date | trips | no_shows | interruptions | vehicles | tos_kinds
 dr_simulated | 2026-07-14   |    46 |        2 |             6 |        6 |         3
 dr_simulated | 2026-07-15   |    49 |        7 |             5 |        6 |         3
 dr_lineage_edges: 95   (one per canonical row)
 raw.records: 3cd0f7d5… headway-dr / 74c010a7… headway-api-ingest, both
 source=dr_simulated, parse_status=ok
 dq.issues: malformed_dr_trip warning ×2  ← the two injected
 negative-duration rows QUARANTINED (48 dropped-file rows − 2 = 46 landed;
 fail loudly, never repaired)
```

7. **Runner** (`python -m headway_calc.runner --period-start 2026-07-14
   --period-end 2026-07-16`): `dr_trips_loaded: 95`, 24 persisted, 0
   blocked, 12 warnings + 20 infos routed. **Live DR figures (SIMULATED —
   every row carries the `simulated_source_data` info finding and
   `source_mix {"dr_simulated": …}` in its detail; NOT certifiable):**

```
 metric |     scope      |  value  | calc_name  | version
 vrh    | mode:DR        |   24.63 | dr_vrh_v0  | 0.1.0
 vrh    | mode:DR:tos:DO |   13.06 |            |    (13.06+8.48+3.09 = 24.63 ✓)
 vrh    | mode:DR:tos:PT |    8.48 |
 vrh    | mode:DR:tos:TX |    3.09 |
 vrm    | mode:DR        |  517.42 | dr_vrm_v0  |    (274.52+184.81+58.09 ✓)
 upt    | mode:DR        |     204 | dr_upt_v0  |    (97+74+33 ✓)
 voms   | mode:DR        |       6 | dr_voms_v0 |    (DO 3 / PT 2 / TX 1)
 pmt    | mode:DR        | 1112.23 | dr_pmt_v0  |    (523.63+427.89+160.71 ✓)
```

   psql-verified from a separate connection: the 20 `mode:DR%` rows above in
   `computed.metric_values`; 36 lineage edges metric→raw records; DQ routing:
   `dr_distance_unmeasured` ×4, `dr_onboard_distance_missing` ×4,
   `dr_ada_sponsored_conflict` ×2, `dr_tx_shared_distance_summed` ×2
   (warnings), `simulated_source_data` ×20 (info — one per persisted DR row).
8. **API serves them**: `GET /metrics/values?metric=vrh&period_start=
   2026-07-14&period_end=2026-07-16` returns the four DR scopes with values,
   calc identity and the source_mix detail; `GET /metrics/values/{id}/lineage`
   walks the mode:DR vrh figure to BOTH content-addressed raw records
   (file-drop 3cd0f7d5… and machine-push 74c010a7…) via `dr_vrh_v0`.

## Outputs — frontend evidence (2026-07-13)

Design point 5's UI slice delivered — UI-surfacing only (web/ exclusively;
db/, services/, contracts/, tools/ untouched by this pass). No commits —
working tree only, per instruction.

**Deliverables:**

1. **Quote extraction** (`web/scripts/extract-quotes.mjs`): the tracker's
   "Verified — Demand Response / on-demand reporting" section is mapped to
   ALL FIVE dr calc versions (`dr_vrh_v0`, `dr_vrm_v0`, `dr_upt_v0`,
   `dr_voms_v0`, `dr_pmt_v0` — the exact names in the tracker's new table
   rows); quotes.json regenerated: 12 verbatim, page-cited quotes per dr
   calc (p. 33 mode definition, pp. 37–39 TOS taxonomy incl. the voucher
   rule, p. 129 revenue-time + TX onboard-only rules, p. 130 dispatching
   point + no-deadhead-TOS, Exhibit 36 no-show row, Exhibits 38+40 VOMS
   atypical inclusion, pp. 143–144 UPT rules, p. 131 shared-vehicle,
   p. 139 scheduled service). The DR section's `Source:` line is unbolded
   (every other quote-bearing section bolds the manual name); rather than
   edit the calc role's file, the extractor gained a documented fallback
   for the exact `Source: <manual>, printed pp. …` shape — anything else
   still fails loudly.
2. **DR receipts** (`web/src/regulatory/drRules.ts` — the
   safetyRules/samplingRules pattern — + `components/DrScopeBadge.tsx`,
   `Receipt.tsx`, `MetricsView.tsx`, copy.ts, styles.css):
   - **Mode/TOS badge** on every `mode:DR` / `mode:DR:tos:*` figure, in the
     metrics table row (DR rows must never look like fleet rows — the table
     has no scope column) and on the receipt story: "Demand response (DR)"
     plus the plain-language TOS label — Directly operated (DO), Purchased
     transportation (PT), Taxi (TX), Transportation Network Company (TN);
     whole-mode figures read "All types of service"; unknown TOS codes fall
     back to the raw code. Info tokens (AA-verified pair, both themes).
   - **Rule callouts** ahead of the receipt's full quote list, each a
     plain-language lead-in + the VERBATIM quote + page cite, resolved via
     quoteContaining (absence renders the loud ruleMissing alert, and the
     test suite pins every callout×TOS combination resolvable): TX
     vrh/vrm/voms → the p. 129 onboard-only rule; TX/TN vrh/vrm → the
     p. 130 no-deadhead rule; vrh/vrm (mode, DO, PT, TN) → the Exhibit 36
     no-show-is-revenue rule; voms (all DR scopes) → the Exhibits 38+40
     atypical-day INCLUSION. Deliberate reading of the design: TX vrh/vrm
     receipts do NOT carry the no-show callout — under TX the onboard-only
     rule replaces the span semantics (a no-show contributes nothing), so
     quoting the no-show row there would state the wrong rule.
   - `pmt` metric + `passenger_miles` unit display labels added (dr_pmt_v0
     feeds the existing pmt metric; the code previously fell back raw).
3. **SIMULATED badges — verified, not rebuilt**: every live DR row carries
   `source_mix {"dr_simulated": …}` in detail, so isSimulated() lights the
   existing badge in the table and the receipt flags section untouched —
   asserted in tests and observed live.

**Suites (before → after this increment):**

```
web/ vitest        106 → 113 passed (19 files; new: src/test/dr.test.tsx ×6,
                   quotes.test.ts +1 DR verbatim/resolution test)
axe                0 violations in every new test (expectNoAxeViolations)
check:contrast     all pairs AA (2 new non-text pairs registered for the
                   callout border: #1d4e89/#ffffff, #a8c7f0/#161b22)
lint (oxlint)      clean
build (tsc -b + vite)  clean — dist/assets/index-PPTaSKOu.js 481.71 kB
```

**LIVE click-through — real browser against the running API** (headless
Chrome via puppeteer-core, Vite dev server :5173 →
`VITE_API_BASE_URL=http://127.0.0.1:8000`; house pattern: real login as
`dsteward` through the form, SPA navigation only — the in-memory token
survives; the API served the 20 `mode:DR%` rows from the backend's runner
evidence above):

```
signed in as dsteward
SPA-navigated to /metrics; table rendered
TX VRH row found: { drBadge: true, tosBadge: true, simulated: true }  (3.09 h)
TX VRH receipt: storyBadges, txOnboardQuote + p. 129 cite,
  noDeadheadQuote + p. 130 cite, noShowCalloutAbsent, simulatedFlag,
  sourceMixLine (dr_simulated), walkLink — all true; 2 dr-callouts
mode:DR VOMS receipt: atypical intro + verbatim Exhibits 38+40 quote +
  citation, mode badge — all true
keyboard: Details toggle focusable, Enter closes
CLICKTHROUGH PASSED — no page errors
```

Screenshots `shot-dr-tx-vrh-receipt*.png`, `shot-dr-voms-receipt.png` in
the session scratchpad.

**Notes for the NTD role (contract nits, no action blocking):**
- Bolding the DR section's `Source:` manual name in the tracker would let
  the extractor's fallback retire (one-line tracker edit, calc role's call).
- Two DR citations carry the tracker's parenthetical annotations verbatim
  in the page ref ("pp. 134–135, verbatim classifications"; "pp. 143–144,
  quoted in PMT section context") — extraction ships the pageRef verbatim
  by design; move the annotations outside the parens if cleaner cites are
  wanted.
- DR detail keys (no_show_trips, revenue_spans, tos_mix,
  interruption_breaks, …) render via the raw-but-tidy fallback ("no show
  trips: 3") — honest by convention; plain-language templates for the DR
  detail vocabulary are a small follow-up. An empty `interruption_breaks`
  renders as "{}".
- The honest-scope banner duty from the design ("no vendor integrations
  shipped, wire contract + simulator only") is carried by the SIMULATED
  badge + flags meaning on every DR figure (all DR rows are
  simulator-sourced today); a dedicated DR page with its own banner does
  not exist yet — that surface belongs to the deferred ops-analytics tier.
