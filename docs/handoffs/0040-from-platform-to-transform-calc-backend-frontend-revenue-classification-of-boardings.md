# Handoff: platform → transform+calc+backend+frontend — Revenue classification of boardings (no-run detection + human-in-the-loop review)

## Context

A live diagnostic with the partner agency's ITS manager (2026-07-31, over a real
full-day APC export) cracked open a real ridership-accuracy problem — and turned it
into one of the strongest "explain this number" features on the roadmap.

**The finding.** ~3.3% of the export's boardings sit on rows that carry **no run
assignment at all** — trip, route, stop, direction and stop-sequence are all NULL.
The APC counter fired on a vehicle at a moment the system had it tied to no trip.
Plotted against real assigned ridership by hour, these "ghost" boardings cluster
hard at the **start of the service day** (the pre-service hour has ~3x more ghost
than real boardings) and the **end** (after the last trip, ghost boardings with zero
real ones), and are sparse through midday. The ITS manager identified them
immediately: **drivers and staff boarding during prep, pull-out and pull-in** —
dropping items off, prepping the bus, maintenance — while the vehicle is moving with
the APC on but not logged into a run.

**The reframe.** A vehicle not logged into a run **is not in revenue service**, so
these boardings are **not unlinked passenger trips**. Excluding them is not a hack —
it is the NTD-correct treatment. This **inverts** the earlier plan (which was to
count all unassigned boardings so Headway's total matched the agency's raw APC
total): the agency's raw total is the one that is inflated, by counting non-revenue
prep activity. Headway's value is to separate real ridership from prep-time noise
**with the receipts to prove it**, so the reported figure is defensible.

**Detours are NOT the cause, and need no fix.** The export's detour flag is used
correctly: detour-flagged boardings — including riders picked up at the temporary
stops that stand in for a detoured route — carry a **full trip and stop** and count
as normal ridership. Detour handling is already right; the only opportunity is to
**surface** the flag so an analyst can see which ridership occurred during a detour.

**The residual.** A small set of no-run boardings occur mid-service (a handful of
rows on one or two specific vehicles, larger-than-usual counts). These fit neither
prep nor detour — genuinely ambiguous, and the poster child for **a human should
look at this one**.

**Supersedes / relates:**
- Replaces the earlier "count off-designated-stop boardings toward UPT" direction —
  the diagnostic showed those rows are non-revenue prep, not off-stop riders.
- The same rows are why the adapter currently quarantines on NULL `PatternPointRank`
  (a loud but lossy ~3.3% drop). This wave changes that quarantine into
  classification.
- Header-tolerance for these exports already shipped (`skip_optional_header`,
  2026-07-31); the confirmed DirectionKey→direction_id mapping also shipped.

## Design (binding)

1. **Stop quarantining no-run boardings; emit them for classification.** A boarding
   whose row resolves to no run (the fully-unassigned case) is emitted as a
   passenger event marked with an explicit assignment/revenue **status** — never
   silently dropped and never silently counted. Additive contract change on
   `tides_passenger_events` (a `revenue_classification` / assignment-status field);
   the normal assigned path is unchanged.

2. **Derive revenue-service windows from the GTFS schedule Headway already ingests.**
   The first and last scheduled trip per route/service define the revenue window — no
   new ingestion. This is a **corroborating** signal, not the sole rule: the primary
   discriminator is the **no-run assignment itself** (only a few ghosts fall strictly
   before the first trip; most are interspersed but still unassigned).

3. **Auto-classify the clear cases**, so humans only ever see the genuinely ambiguous:
   - no-run **and** outside the revenue window (prep / pull-in) → suggested
     **non-revenue**, reason recorded, excluded from UPT;
   - detour-flagged with full attribution → **revenue**, tagged "during detour"
     (counts, surfaced);
   - normal assigned → **revenue**.

4. **Route the residual to a human-in-the-loop review queue**, built on the existing
   DQ resolution workflow (handoffs 0029/0030 — owners, status, notes). Unclassified
   boardings surface with full context (vehicle, time, count, why flagged). The
   analyst marks each **revenue / non-revenue** and **writes a justification note**
   (who, when, why — e.g. "unit's counter double-fired during layover, confirmed with
   dispatch"). That note becomes part of the figure's receipt: "explain this number"
   now includes the human judgment calls, auditable.

5. **UPT excludes non-revenue-classified boardings.** The metric detail records the
   split — revenue / excluded-non-revenue / pending-review — and links the human
   justifications. **Pending-review boardings are held out of a certifiable figure
   until classified** (a boarding of unknown revenue status must not silently inflate
   or deflate a certified number); the default-until-reviewed policy is stated, not
   assumed. Do not let excluded boardings participate in the missing-trip factor
   (no double-count).

6. **Surface the detour flag** on ridership for transparency (analysts can see
   detour-time boardings even though they already count).

7. **Handle supplemental / catch-up service and deadhead** — the ITS manager
   flagged that dispatch routinely sends an **extra bus** to recover a route that has
   fallen behind (e.g. a 7th block covering one trip so the late buses catch up), and
   **deadheads** the late bus (running empty) to reposition it. Verified against a real
   day: **no double-counting risk** — no exact scheduled trip was served by two
   physical vehicles, so a rider always boards one bus and is counted once; extra
   buses spread the same riders across vehicles, they don't inflate the total. The
   supplemental vendor "tripper" flag was **unpopulated** in the observed export, so it
   cannot be relied on to identify catch-up buses. The real risk is the **opposite —
   under-count**: a catch-up bus dispatch runs **without a formal trip assignment**
   appears as a *mid-service no-run boarding* (the ambiguous residual in point 4), and
   the prep-window default would wrongly exclude those **real** riders. This is exactly
   why point 4's HITL review is load-bearing and cannot be a pure time rule: only a
   human who knows the day's dispatch decisions can tell a catch-up bus (revenue) from
   a maintenance/prep event (non-revenue). **Deadhead** movement is non-revenue like
   prep — any counts recorded while a bus is deadheading exclude with that reason.

7. **NTD verification (quote-or-own-it):** quote the FTA revenue-service / UPT
   definition into `services/calc/REGULATORY_TRACKER.md` before this governs a
   certified figure — the exclusion of non-revenue boardings must rest on the
   manual's own words, not our inference.

## Outputs

Additive contract change + adapter change (no-quarantine → status) + schedule-window
derivation + calc classification/exclusion + the review-queue UI with justification
notes + detour-flag surfacing; tests at every layer; NTD tracker quote; evidence.
A wave of this size decomposes into sub-waves (contract+adapter first, then
schedule/calc, then the review UI) — sequence them, keep each green.

## Open Questions

- **Default policy for pending-review boardings** — exclude-until-classified (the
  conservative, recommended default) vs include-with-flag? Agency-configurable?
- **Root-causing the mid-service residual** — a specific vehicle's counter firing
  off-run is also a maintenance signal; worth its own DQ finding to the fleet team?
- **Revenue window edge cases** — a route with no schedule (shouldn't happen for
  fixed route), and service that spans midnight (ties into the still-unconfirmed
  service-day rollover in `resolution.v0.yaml`).
- **Reconciliation reporting** — a view that shows the agency the *difference*
  between their raw APC total and Headway's revenue-only total, with the excluded
  non-revenue and the human notes, so the correction is transparent (this is the
  "over-reporting" conversation, made defensible rather than accusatory).

## Outputs — evidence (Data + Transform + Calc + NTD engineer, 2026-07-31)

**Scope delivered:** the BACKEND FOUNDATION — design points 1–5, 7 (contract +
adapter + schedule window + calc classification/exclusion + tracker quote +
tests). SCOPED OUT and untouched: the human-in-the-loop review-queue UI, the
frontend, the reconciliation report (later sub-waves). The residual PENDING
boardings are EMITTED and recorded here; nothing resolves them yet.

### What shipped, by layer

1. **Additive contract change (design point 1).** `canonical.passenger_events`
   gains a nullable `revenue_classification` (migration 0039; CHECK IN
   ('assigned','unassigned')) — the transform's assignment STATUS, never the
   revenue verdict. Additive on the same TIDES-compatible contract: the
   normalizer relaxes the TIDES `trip_stop_sequence` minimum-1 requirement
   ONLY for an 'unassigned' row (a no-run boarding has no stop-sequence), so a
   no-run event lands with trip/sequence NULL instead of quarantining. Every
   pre-0040 row and first-party TIDES feed keeps NULL and reads unchanged.
   Files: `db/migrations/0039_*.sql`, `tides_passenger_events.py` (dataclass +
   normalizer), `writer.py` (INSERT column).

2. **Adapter — stop quarantining, emit for classification (design point 2).**
   New declarative `unassigned` block on the mapping spec
   (`contracts/adapter-mapping.v0.schema.json`): a spec-declared `when`
   predicate identifies a no-run row, `drop_fields` names the run-identity
   fields absent on it, and the engine emits it as an 'unassigned' passenger
   event (drops trip/stop, stamps the status, skips trip resolution) instead
   of filtering/quarantining it. Normal assigned rows are stamped 'assigned',
   path otherwise unchanged. The TripSpark Streets mapping's old
   `TripName not_empty` FILTER (which dropped the ~3.3% ghost boardings) is
   replaced by this block. Files: `adapters/{engine.py,spec.py}`,
   `adapters/tripspark/streets/mapping.v0.yaml`, the schema.

3. **Schedule-derived revenue window (design point 3).** New pure module
   `headway_calc/revenue_window.py` + reader `load_revenue_window_seconds`:
   per operated service date, [first scheduled departure, last scheduled
   arrival] over that day's operated trips' `canonical.stop_times`, anchored
   to UTC through the single agency timezone (GTFS "noon − 12 h" DST-immune
   convention). CORROBORATING only — the primary discriminator is the no-run
   assignment itself. Multiple/zero agency timezones ⇒ no window ⇒ conservative
   hold-pending.

4. **Calc auto-classify + UPT exclusion (design points 4–5) — upt_v0 0.3.0.**
   `revenue_classification == 'unassigned'` boardings are split: OUTSIDE the
   window ⇒ suggested NON-REVENUE, EXCLUDED from UPT (warning
   `boarding_excluded_non_revenue`); INSIDE the window or no-window ⇒ held
   PENDING human review (warning `boarding_pending_revenue_review` + run-level
   info `boardings_pending_revenue_review`). The detail carries the split
   `{revenue_boardings, excluded_non_revenue_boardings,
   pending_review_boardings, pending_review_policy}`. **Default policy:
   exclude-until-classified** (stated on the finding + in the detail) — a
   boarding of unknown revenue status is held OUT of the certifiable figure.
   Detour boardings are 'assigned' (full trip+stop) and count as revenue
   UNCHANGED (surfacing the detour flag needs a contract field not yet carried
   — deferred, documented). Retained runnable: `compute_upt_v0_2_0`,
   `compute_upt_v0_1_0` (both strip the status ⇒ historical recompute is
   byte-for-byte). Threaded through runner/preview/mode. Files:
   `upt.py`, `types.py` (PassengerEvent + UptDetail), `reader.py`, `runner.py`,
   `mode.py`.

### The double-count guard (critical — proven, not asserted)

A no-run boarding has `trip_id` NULL, so it enters NEITHER the counted UPT base
NOR the operated/missing-trip denominators — the p. 146 missing-trip factor is
byte-identical with and without the ghost boardings present. Pinned by
`test_excluded_boardings_do_not_distort_missing_trip_factor` (asserts
`operated_trips`, `trips_with_events`, `missing_trips`, `missing_share`,
`factor_applied` and the reported value are all identical across a run with and
without excluded + pending ghosts) and by the runner integration test
(`test_no_run_boardings_classified_through_runner`: operated 1, missing 0,
factor 1.000000 with a ghost present).

### FTA definition quoted (quote-or-own-it, design point 7)

`services/calc/REGULATORY_TRACKER.md` gains the upt_v0 0.3.0 row and a new
section "Verified — revenue classification of boardings (handoff 0040)". The
exclusion rests on the manual's OWN words, already quoted verbatim in the
tracker and re-tied there: **p. 128 Revenue Service** ("A transit vehicle is in
revenue service when it is providing public transportation and is available to
carry passengers") + **p. 143** ("Employees or contractors on transit agency
business are not passengers") + **p. 129 Deadhead** ("operate closed door and
do not carry passengers … Leaving or returning to the garage or yard facility …
When the driver does not have the duty to carry passengers"). The section also
states what the manual does NOT say — no rule distinguishes prep from a
catch-up bus — and that Headway therefore does not infer it (window
auto-excludes only the unambiguous outside-window prep; everything else is held
for a human).

### Tests at every layer (design point 7)

- **Contract/normalizer** (`services/transform/tests/test_tides_passenger_events.py`,
  +5 tests): assigned/unassigned status carried; no-run row normalizes with
  NULL trip+sequence; an assigned row missing a sequence still quarantines
  (relaxation gated on status); unrecognised classification is a finding;
  absent classification stays NULL (pre-0040 byte-identical).
- **Adapter** (`services/transform/tests/test_adapters.py`, +4 tests; 2 existing
  tests updated to the new behavior): the no-run row is emitted 'unassigned'
  with trip/seq dropped; deterministic; `drop_fields` must reference a mapped
  field (refused at load); the block is rejected on a DR target. Fixture
  `stop_visits.csv.expected.json` updated (mapped 3→4, filtered 4→3, emitted
  4→5).
- **Calc** (`services/calc/tests/test_upt_revenue_classification.py`, +10
  tests): window boundaries; the three-way split; the double-count guard;
  pending exclude-until-classified; byte-for-byte 0.2.0 for an unclassified
  feed; retained versions ignore classification; NULL-count no-run warned.
  Reader tests (+4): classification loaded; pre-0039 42703 fallback;
  window-seconds mapping; pre-0019 42P01 empty. Runner integration (+1).
  Existing version-string assertions updated 0.2.0→0.3.0 where the default
  path bumped.

### Test totals (captured, not inferred)

- calc: `cd services/calc && pytest -q` → **635 passed**.
- transform: `cd services/transform && pytest -q` → **237 passed**.
- api: `cd services/api && pytest -q` → **498 passed** (unaffected; regression
  check).
- migrations static: `pytest -q db/test_migrations_static.py` → **30 passed**.
- adapter harness (`validate_all`): **OK** — tripspark_streets + 3 reference
  adapters green with the new `unassigned` block.

### Live verification (MBTA, on this box)

- Migration 0039 applied to the live `headway` DB (was at 38, now 39):
  `revenue_classification` present (nullable TEXT) + CHECK constraint present.
  204,536 existing rows read back with classification NULL (backward
  compatible).
- Live reader over [2026-07-09, 2026-07-14): 204,524 passenger events loaded
  through the new SELECT (all classification None); revenue-window derivation
  produced 5 service-date windows from real `canonical.stop_times`; single
  agency timezone `America/New_York` ⇒ windows build.
- Live `compute_upt` 0.3.0 over that period: value None, blocking
  `apc_missing_trips_above_fta_threshold` (74.91% missing — the pre-existing
  simulated-data situation, unchanged), NO `revenue_classification` split key
  in the detail (all events unclassified ⇒ byte-identical to 0.2.0). Confirms
  the change is inert on a pre-0040 feed.

### Deviations / notes

- **Detour flag surfacing (design point 6)** is partial by necessity: detour
  boardings already count (they are 'assigned' with full attribution), but
  surfacing the flag on ridership needs a `canonical.passenger_events` contract
  field the export's `IsDetour` column is not yet mapped into — deferred, not
  built (avoids a second contract change outside this wave's core).
- **Revenue window day convention** is the UTC-date convention (voms_v0
  precedent), and no window derives when the agency declares multiple
  timezones — both documented in the tracker as verify-before-reportable
  items. On the live 2-agency DB the multi-tz case would hold everything
  pending; the single-agency MBTA path derives windows correctly.

### Files changed

New: `db/migrations/0039_passenger_event_revenue_classification.sql`,
`services/calc/headway_calc/revenue_window.py`,
`services/calc/tests/test_upt_revenue_classification.py`.
Modified — transform: `adapters/engine.py`, `adapters/spec.py`,
`tides_passenger_events.py`, `writer.py`, `adapters/tripspark/streets/mapping.v0.yaml`,
`adapters/tripspark/streets/fixtures/stop_visits.csv.expected.json`,
`contracts/adapter-mapping.v0.schema.json`, `tests/test_adapters.py`,
`tests/test_tides_passenger_events.py`, `tests/test_writer.py`.
Modified — calc: `headway_calc/upt.py`, `headway_calc/types.py`,
`headway_calc/reader.py`, `headway_calc/runner.py`, `headway_calc/mode.py`,
`REGULATORY_TRACKER.md`, `tests/conftest.py`, `tests/test_reader.py`,
`tests/test_runner.py`, `tests/test_runner_per_mode.py`,
`tests/test_golden_mode.py`, `tests/test_upt_attestation.py`.
