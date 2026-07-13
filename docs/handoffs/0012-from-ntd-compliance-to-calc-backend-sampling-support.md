# Handoff: ntd-compliance-engineer → calc, backend, frontend — NTD sampling support v0 (queued behind handoff 0011)

## Context
The 2009 NTD Sampling Manual is verified on file (tracker: "Verified — NTD Sampling Manual"). This unblocks the sampling tier for agencies WITHOUT full APC coverage — the counterpart to pmt_v0's 100%-count path (handoff 0011, in flight; DO NOT start this build until 0011's calc work lands — same files).

## Design (binding)
1. **`sampling_v0` calc module (services/calc, tracker row):**
   - Plan selector: (mode, TOS, unit, efficiency option, frequency) → required annual + per-period sample size, verbatim from Tables 43.01–43.07 (quote per cell at implementation; the annual totals are already in the tracker). Eligibility rules §41.01/41.03 encoded as plain-language guidance, not silent logic.
   - APTL estimator per §83: sample APTL = sample total PMT ÷ sample total UPT (ratio of totals; a test MUST pin the §83.05(b) ban — average-of-ratios input shape rejected or never computable by construction); annual PMT = 100% UPT expansion factor × sample APTL; by type-of-service-day variants.
   - Sample drawer: deterministic, seeded, WITHOUT replacement (§63.03) from a provided service-unit list (trip IDs / vehicle-days). Seed recorded for reproducibility; the RNG procedure documented (any random method qualifies per §63.03 — cite it).
2. **Persistence/API (backend):** sampling plans as first-class records (mode/TOS/unit/option/frequency/required size/selected units/seed/status), sample measurements entry (per selected unit: UPT, PMT observed — manual ride-check data), progress tracking (units measured vs required — the manual forbids undersampling; oversampling only if random), and the §83 estimate endpoint producing a PMT figure with estimation provenance (labeled as sampled estimate, never conflated with computed PMT; simulated/manual-entry caveats per house style). Documentation-retention note: ≥3 years (2026 manual p. 150) surfaced in the UI copy.
3. **UI (frontend):** /sampling — plan wizard (pick mode/TOS/option/frequency → required size with the table citation), drawn-sample worksheet (the list to hand a ride checker), measurement entry, progress meter, and the estimate receipt (expansion factor × sample APTL with both quoted).
4. **Honest scope:** template plans (Section 50 spreadsheets), Base-option estimation (Section 70), and grouping option deferred — each needs more verbatim quoting at implementation; statistician-certification (§57) is a workflow fact stated in copy, not a feature.

## Outputs
sampling_v0 + goldens (incl. a hand-worked §83 APTL example), API + UI, suites green, tracker row, evidence here.

## Open Questions
- Per-period sample-size cells (quarterly/monthly/weekly breakdowns) — quote verbatim from Tables 43.01–43.07 during implementation.
- Base option (Section 70) and route-grouping (Subsection 63/83 grouped variants) — v1.
- APC benchmarking workbook (2026 manual checklist 1–18) — separate feature, natural successor.

## Response — calc + backend engineer (2026-07-12)

Contract accepted; design points 1 and 2 delivered (point 3, /sampling UI,
is the parallel frontend session's, coding against the regenerated
`services/api/openapi.json` — 9 new `/sampling/*` paths). Handoff 0011's
calc work had landed before this build started (queue condition satisfied).

**Delivered:**

- **`sampling_v0` 0.1.0** (`services/calc/headway_calc/sampling.py`, tracker
  row + two new tracker quote sections): plan selector over ALL 48 cells of
  Tables 43.01/43.03/43.05/43.07 (each cell quoted verbatim in the tracker's
  new "Sampling plan tables — implementation quotes (sampling_v0)" section
  and pinned one-for-one in `tests/test_golden_sampling.py`; §41.01/§41.03
  eligibility as plain-language guidance strings); §83 APTL estimator
  (ratio of totals; per-unit APTL structurally nonexistent — see deviations
  note 5 on how the ban is enforced); seeded deterministic
  without-replacement drawer (§63.03(b) "any other method": SHA-256
  keyed-hash ordering; seed recorded; prefix-consistent, which makes random
  oversampling sound). Goldens hand-worked in
  `tests/golden/sampling_v0/BASIS.md`.
- **Migration 0020** (`sampling.plans` / `sampling.draws` /
  `sampling.measurements`, all append-only by trigger, proven by attack
  live) + **API** (`headway_api/routers/sampling.py`): options/requirements
  lookups, plan creation (selector-computed sizes, selector version
  recorded), per-period seeded draws, measurement entry restricted to drawn
  units with supersede corrections, progress with the unmeasured-unit
  worksheet, and the §83 estimate endpoint (undersampling refusal with the
  p. 149 citation; sampled-estimate provenance label; manual-entry caveat;
  `computed.metric_values` never written). Documentation-retention ≥3 years
  (2026 manual p. 150) surfaced in plan/draw/measurement/progress/estimate
  copy (`RETENTION_NOTE`).

**Deviations / design decisions (reported, not silently absorbed):**

1. **Draws are per-period child records (`sampling.draws`), not single
   `selected_units`/`seed` columns on the plan row** as the design sentence
   listed. The ready-to-use plans require one random-selection act per
   period over that period's expected-service list (§43.01(d): sample size
   is stated per "the relevant period for each frequency"; §63.07(b)(2):
   the unit list "is for the period corresponding to the sampling
   frequency"). A single annual draw would not have been the published
   plan. The plan's seed(s) and selected units are first-class and fully
   recorded — one row per period, unique per (plan, period_label).
2. **Unit ids must be unique across a plan's periods** (the draw endpoint
   refuses a frame that repeats ids from earlier draws, directing agencies
   to period-qualified ids — the manual's own serial-number scheme encodes
   the day, §63.09). This keeps "one active observation per unit"
   well-defined across the year.
3. **Grouped-APTL plans are not creatable** (422 with the §43.05(a)
   citation); the grouped cells ARE encoded, quoted, pinned, and readable
   via `GET /sampling/requirements`. Matches the handoff's honest scope.
4. **Base-option plans ARE creatable** (plan/draw/measure/progress all
   work — the plan documentation tier is option-independent), but the
   estimate endpoint refuses them citing the Section 70 deferral.
5. **The §83.05(b) ban** is enforced the strongest way available: the
   estimator's input shape is per-unit (UPT, PMT) observation pairs and no
   per-unit ratio is computed, accepted, or exposed anywhere
   (`test_average_of_ratios_is_unconstructible_by_shape`), the §83.05(a)/(b)
   sentences are pinned verbatim, and a Hypothesis merge-invariance
   property (splitting any unit's totals never changes the APTL — true of
   ratio-of-totals, false of average-of-ratios) proves the computed
   quantity algebraically.
6. **The 100% UPT expansion factor is a caller-supplied input** with an
   explicit caveat (cross-check against certified UPT), not auto-joined to
   `computed.metric_values` — wiring it to a certified upt_v0 figure is a
   natural v1 (open question below).
7. **Estimate endpoint requires `report_preparer` or above** (entry
   endpoints require `data_steward`) — the handoff named no role; estimate
   generation is a report-preparation act.
8. **Migration 0020 was amended once during this increment** (superseded_by
   FK made `DEFERRABLE INITIALLY DEFERRED`) after the FIRST live
   walkthrough exposed a supersede ordering bug (below). 0020 had never
   been committed or shipped, so the sampling schema was dropped and 0020
   re-applied in corrected form rather than minting 0021; audit rows from
   the aborted first walkthrough remain in `audit.events` (append-only —
   correctly so).
9. **A manual-printed table inconsistency was found and kept as printed:**
   Table 43.07, One-Way Car Trips, Base Option, weekly prints 6/week vs
   288/year (6 × 52 = 312). Both cells encoded verbatim, pinned as
   `MANUAL_PRINTED_ANOMALY`, documented in the tracker — never "corrected"
   by arithmetic.

**Open questions (for NTD compliance / v1):**

- Wire the estimate's expansion factor to a certified upt_v0 figure
  (per-mode/TOS UPT join) instead of caller entry.
- Template plans (Sections 50–57), Base-option estimation (Section 70),
  grouped sampling/estimation (§43.05, §83.05(c)) — as already deferred.
- Statistician-certification (§57) workflow copy in the UI (frontend point 3).

## Outputs — backend evidence

All commands run 2026-07-12 on the live dev box (Python 3.12.3; compose
stack healthy). Nothing committed or pushed; `web/` untouched (parallel
frontend session owns it).

### 1. Migration 0020 — applied live, verified via separate psql

```
$ cd db && PGHOST=127.0.0.1 PGUSER=headway PGPASSWORD=*** PGDATABASE=headway python3 migrate.py
applying 0020_sampling_plans.sql ... ok
applied 1 migration(s)

$ docker exec headway-timescaledb-1 psql -U headway -d headway -c "SELECT filename, applied_at FROM public.schema_migrations WHERE filename LIKE '0020%';"
 0020_sampling_plans.sql | 2026-07-13 04:42:57.347314+00

$ ... -c '\dt sampling.*'
 sampling | draws        | table | headway
 sampling | measurements | table | headway
 sampling | plans        | table | headway

$ ... -c "SELECT conname, condeferrable, condeferred FROM pg_constraint WHERE conname = 'measurements_superseded_by_fkey';"
 measurements_superseded_by_fkey | t | t
```

(An initial 0020 without the deferrable FK was applied at 04:37Z; after the
live walkthrough exposed the supersede bug — deviation 8 — the never-shipped
schema was dropped, 0020 corrected, and re-applied at 04:42Z.)

Append-only proven by attack (all six rejected, separate psql connection):

```
UPDATE sampling.plans SET required_annual = 10;
ERROR:  sampling.plans is append-only: the only permitted UPDATE is the created -> active transition ...
DELETE FROM sampling.plans;
ERROR:  sampling.plans is append-only: DELETE rejected. Sampling documentation must be retained (2026 NTD Policy Manual p. 150: at least 3 years) ...
UPDATE sampling.draws SET selected_units = '{}';   → ERROR: sampling.draws is append-only: UPDATE rejected. A draw is a historical random-selection act ...
DELETE FROM sampling.draws WHERE period_label = '2026-Q1';   → ERROR (same trigger)
UPDATE sampling.measurements SET observed_upt = 999 WHERE superseded_by IS NULL;   → ERROR: ... the only permitted UPDATE is setting superseded_by once ...
DELETE FROM sampling.measurements;   → ERROR: ... Corrections supersede ... originals are never removed.
```

### 2. LIVE walkthrough — create plan → draw → measure → progress → estimate

New API code served by local uvicorn (port 8001) against the LIVE compose
TimescaleDB; real logins (`dsteward` data_steward for entry, `certifier`
for the estimate). Full transcript in the session; the actual outputs:

```
== GET /sampling/requirements -> 200
 required_per_period 12, required_annual 48, Table 43.01 ... 'Reporting 100% UPT (APTL Option)'

== POST /sampling/plans -> 201
 plan_id 442a2e30-98f0-4229-a9dd-6fd56d7444ca | DR / DO / vehicle_days / aptl / quarterly
 required 12 per quarter, 48 per year | selector_version "sampling_v0 0.1.0" | audit_event_id 619
 table_citation: Table 43.01 ... Vehicle days for a Quarter = 12; Total Sample Size for Year = 48.

== POST draws (one per quarter, frames of 30 vehicle-days each):
 2026-Q1 -> 201: selected 12, seed d6f9c5502e0b5f9670dee022a94a3ef1
 2026-Q2 -> 201: selected 12, seed 4ede804fd844bac5b0aeb8aacd238f61
 2026-Q3 -> 201: selected 12, seed 922422ce36f8f0e499ba744a875786db
 2026-Q4 -> 201: selected 14, seed 90893361123aa0f41fe3e2fcbe90b849, oversample 2 (flagged random, p. 149 note)
== reproducibility: recorded seed re-draws Q1 selection exactly: True
== duplicate-period draw -> 409 ("A sample was already drawn for period '2026-Q1' ...")

== estimate at 20 of 48 measurements -> 422 (undersampling refusal):
 "This plan requires 48 measured units for the year (Table 43.01 ...) but only 20 have
  observations on file. ... 'If a transit agency samples, they must follow the sampling
  technique exactly.' ... (2026 NTD Policy Manual, Full Reporting, p. 149 ...)"
== measurement for non-selected unit -> 422 ("not in this plan's drawn sample ...")

== all 50 measurements entered (48 required + 2 random oversample)
== supersede first measurement -> 201 (original 57cd2808… -> replacement c5e23ef3…, reason audited)

== GET progress -> 200
 units_selected 50, units_measured 50, undersampled false
 draws: (2026-Q1 12/12) (2026-Q2 12/12) (2026-Q3 12/12) (2026-Q4 14/14, oversample 2)

== POST estimate -> 200
 sample_size 50 | sample_total_upt 597 | sample_total_pmt "2266.75"
 sample_aptl "3.80" (= 2266.75 ÷ 597, ratio of totals, quantized 0.01)
 expansion_factor_upt "250000" | estimated_pmt "950000" (= 250000 × 3.80)
 by_service_day: Weekday 4.15 × 180000 = 747000 | Saturday 3.16 × 40000 = 126400 | Sunday 3.05 × 30000 = 91500
 method: "estimated — sampled average passenger trip length (APTL) method (FTA NTD Sampling
   Manual, March 31, 2009, Subsection 83) ... a sampled ESTIMATE, not a computed PMT measurement."
 caveats[0]: "... never stored as, a computed PMT measurement (computed.metric_values is untouched ...)"
 citations[0]: the §83.05(a) rule AND the §83.05(b) ban, verbatim
 audit_event_id 675
```

Rows confirmed from a SEPARATE psql connection:

```
$ docker exec headway-timescaledb-1 psql -U headway -d headway -c "SELECT ... FROM sampling.plans;" ...
 442a2e30-98f0-4229-a9dd-6fd56d7444ca | DR | DO | vehicle_days | aptl | quarterly | 12 | 48 | active | dsteward

 period_label | frame | selected | oversample_units | seed                             | drawer_version    | drawn_by
 2026-Q1      |    30 |       12 |                0 | d6f9c5502e0b5f9670dee022a94a3ef1 | sampling_v0 0.1.0 | dsteward
 2026-Q2      |    30 |       12 |                0 | 4ede804fd844bac5b0aeb8aacd238f61 | sampling_v0 0.1.0 | dsteward
 2026-Q3      |    30 |       12 |                0 | 922422ce36f8f0e499ba744a875786db | sampling_v0 0.1.0 | dsteward
 2026-Q4      |    30 |       14 |                2 | 90893361123aa0f41fe3e2fcbe90b849 | sampling_v0 0.1.0 | dsteward

 measurements 51 | active 50 | distinct units 50 | total_upt 597 | total_pmt 2266.75
 (the superseded pair: 2026-Q1/veh-04/day-1 observed_pmt 38.25 superseded=t → 40.00 superseded=f)

 audit.events WHERE action LIKE 'sampling%': sampling_plan_create 2, sampling_draw_create 8,
 sampling_measurement_create 100, sampling_measurement_supersede 1, sampling_estimate_generate 1
 (counts include the aborted first walkthrough — audit.events is append-only and correctly retains it;
  its sampling rows were dropped with the schema reset, deviation 8)

 SELECT count(*) FROM computed.metric_values WHERE calc_name LIKE 'sampling%';  →  0
```

### 3. The live-verification catch (norm 1 upheld)

The FIRST live walkthrough failed at the supersede step with
`psycopg.errors.UniqueViolation: measurements_one_active_per_unit` — the
router inserted the replacement before linking the original, so two active
rows for one (plan, unit) existed mid-transaction. The unit-test fake had
masked it (it did not model the partial unique index). Fix: the
`superseded_by` FK is now DEFERRABLE INITIALLY DEFERRED and the router
links FIRST (API-generated replacement id), then inserts;
`tests/conftest.py`'s FakeConn now models the unique index honestly so a
regression fails in unit tests too.

### 4. Test suites (before → after)

```
services/calc      python3 -m pytest tests/ -q            319 → 406 passed
services/api       python3 -m pytest tests/ -q            154 → 179 passed
db                 python3 -m pytest test_migrations_static.py -q   19 → 20 passed
services/transform python3 -m pytest tests/ -q             58 → 58 passed (untouched)
services/ai        python3 -m pytest tests/ -q            109 → 109 passed (untouched)
services/ingestion go build && go vet && go test ./...    all ok (untouched)
web                not run — owned by the parallel frontend session (handoff 0012 point 3); no files under web/ touched here
```

### 5. Contract artifact

```
$ cd services/api && python3 scripts/export_openapi.py
Wrote services/api/openapi.json — OpenAPI 3.1.0, 30 paths: ... /sampling/measurements/{measurement_id}/supersede,
/sampling/options, /sampling/plans, /sampling/plans/{plan_id}, /sampling/plans/{plan_id}/draws,
/sampling/plans/{plan_id}/estimate, /sampling/plans/{plan_id}/measurements, /sampling/plans/{plan_id}/progress,
/sampling/requirements ...
```

Tracker: `sampling_v0 | 0.1.0` row added; new subsection "Sampling plan
tables — implementation quotes (sampling_v0)" quotes all four tables (and
§41.01/41.03/41.05/41.07(c), §63.03, §83.01/83.05/83.07) verbatim from the
PDF, re-verified at implementation 2026-07-12. `headway-calc` package
version bumped 0.5.0 → 0.6.0. READMEs (calc + api) updated with the new
module/endpoints and this verification record.

Honest pending note: `scripts/license_gate.py` reports 2 pre-existing
problems unrelated to this diff — the go-licenses scanner fails to produce
output on this box (environment/tooling; no Go code changed here), and the
`web` package itself resolves as `0.0.0/<none>` (the gitignored
`web/node_modules/web` self-symlink; web/ is the parallel session's
domain). This increment adds ZERO dependencies (sampling_v0 is stdlib-only;
the API reuses existing deps) and all 45 Python dependencies pass the gate.

## Outputs — frontend evidence (orchestrator-recorded)

The frontend build agent completed all work and reported "all gates green" but was terminated by a usage limit before appending its own evidence. The orchestrator re-ran every gate independently (2026-07-12 ~23:46):

- Files: `web/src/views/SamplingView.tsx` (wizard → worksheet → measurement entry → estimate receipt), `web/src/regulatory/samplingRules.ts`, `web/src/test/sampling.test.tsx`, plus route/nav/client/types/copy/extract-quotes integration.
- `npm test`: **18 files / 106 tests passed** (95 → 106; sampling tests assert zero axe violations per house pattern).
- `npm run build`: clean (465.04 kB JS, gzip 137.77 kB).
- `npm run check:contrast`: all token pairs meet WCAG 2.1 AA.
- extract-quotes: `sampling_v0` section mapped; quotes.json regenerated.
- Live API: all 9 `/sampling` routes served on 127.0.0.1:8000 (restarted by orchestrator with same session secret after the router landed).
- CAVEAT (honest): the agent's own live-vs-mock click-through status was not recovered from its final report; its tests run against typed mocks matching the shipped contract. A human live click-through of /sampling (login → wizard → worksheet → measurements → estimate receipt) remains PENDING and is queued for Daniel's next demo pass.
