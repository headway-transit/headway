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

## Outputs — evidence (Backend + Frontend engineer, 2026-08-01) — THE REVIEW QUEUE

**Scope delivered:** design points 4 + 5's missing half — the human-in-the-loop
**review queue** and the loop it closes. The 2026-07-31 wave EMITTED pending
boardings and held them out of the figure; nothing could answer them, so they
were held forever and the figure could never be completed. That dead end is
now closed end to end: the calculation hands undecided boardings to a queue, a
data steward classifies each one **and must write down why**, and the next run
reads the decision back and carries the person, the timestamp and their words
verbatim into the figure's receipt.

SCOPED OUT and untouched: the detour-flag contract field (still deferred, as
in the 0.3.0 evidence), the reconciliation report (open question), and
anything on the map (Track D's lane).

### What shipped, by layer

1. **Migration 0040 — `dq.boarding_revenue_reviews`.** One row per boarding
   the calculation held PENDING, carrying the frozen context a reviewer
   decides on (service date, timestamp, vehicle, boarding count, the
   calculation's own reason, which calc version flagged it and over which
   period) and the slot the decision goes into. **The justification note is
   required by the schema, not merely by the form**: `CHECK
   boarding_review_decision_complete` moves verdict/justification/author/time
   together, and `CHECK boarding_review_justification_not_blank` rejects a
   whitespace-only note. "Classified with no reason" is not a state this
   database can hold. Partial indexes serve the two reads (pending queue by
   `(event_timestamp, passenger_event_id)`; classified history by
   `(service_date, …)`), so the queue pages by keyset at scale exactly as the
   DQ queue does (handoff 0030).

2. **Calc — upt_v0 0.4.0 closes the loop.** `compute_upt` gains
   `boarding_reviews` (passenger_event_id → recorded verdict). A held boarding
   with a decision is counted ('revenue', its raw record entering lineage) or
   excluded ('non_revenue', cited by its finding), with ONE info finding
   `boarding_classified_by_review` quoting the justification verbatim; the
   detail's `revenue_classification` block gains `human_revenue_boardings`,
   `human_non_revenue_boardings` and `human_classifications` (who, when, why,
   per decision), **frozen at compute time**. Undecided boardings are held
   exactly as 0.3.0 held them and are emitted as `CalcResult.review_items`,
   which the runner UPSERTs into the queue inside the fail-loudly-FIRST
   findings transaction — a boarding held out of a figure with nobody able to
   release it is the failure this wave exists to prevent, so the hand-over is
   durable no matter what happens to the value phase. New pure module
   `headway_calc/boarding_reviews.py` owns both ends (persist + load).
   **0.3.0 retained runnable as `compute_upt_v0_3_0`**, byte-for-byte, so a
   figure certified under 0.3.0 recomputes identically whatever has been
   decided since.

   Three arithmetic/honesty decisions, each pinned by test:
   - **Human-counted boardings are added AFTER the p. 146 factor-up, never
     multiplied by it.** The factor accounts for TRIPS whose APC data is
     missing; a no-run boarding is not a trip and never entered the operated
     denominator, so scaling a human-confirmed head count by it would report
     riders nobody observed (worked example in the test: 100 × 50/49 → 102,
     +100 human = **202**; multiplying would give 204).
   - **The double-count guard is untouched** — `operated_trips`,
     `trips_with_events`, `missing_trips`, `missing_share` and
     `factor_applied` are byte-identical with and without decisions.
   - **A blocked run stays blocked.** A classification is not a statistician's
     approval; it does not cure the p. 146 refusal.

3. **API — `services/api/headway_api/routers/revenue_review.py`.**
   `GET /revenue-review/boardings` (keyset cursor, `status=pending|classified`,
   default 50, hard cap 200, whole-queue `total`),
   `GET /revenue-review/boardings/counts` (rows AND boardings — the number
   actually missing from the figure is not the number of rows),
   `GET /revenue-review/boardings/{id}`, and
   `POST /revenue-review/boardings/{id}/classify`. Built on the DQ resolution
   workflow's patterns and wired INTO it: classifying closes the boarding's
   open `boarding_pending_revenue_review` finding in the same transaction with
   a resolution text built server-side from the decision, so the two trails
   can never tell different stories.

4. **Authz + audit.** Reading is `require_authenticated`; classifying is
   `require_at_least("data_steward")` — the same bar as resolving a DQ issue,
   because this IS a DQ resolution that happens to change what the next figure
   counts. Every classification writes `audit.events` action
   `boarding_revenue_classify` **inside the same transaction**, and the
   justification is IN the audit detail (an auditor reading `audit.events`
   alone can see why, without joining anywhere), alongside
   `figure_recomputed: false` so nobody later reads the event as the moment a
   number changed.

5. **Refusals, all without a bypass.**
   - Blank or missing note → 422 with an example of a real one. No
     "classify anyway".
   - Already classified → 409 naming who decided and when.
   - Unknown verdict → 422 that names the safe answer: leave it in the queue,
     where undecided already means excluded.
   - **Certified period → 409.** If the boarding's service date falls inside a
     period whose UPT figure is already certified, Headway refuses outright:
     somebody signed their name to that number and it must keep meaning what
     it meant. Re-opening and re-certifying is a deliberate certifying-official
     act. Nothing is written on any refusal (transaction rolls back).

6. **UI — `web/src/views/RevenueReviewView.tsx`, route `/revenue-review`, nav
   "Boardings to review".** Written for a transit operations manager: no
   sentence on the screen says "unassigned", "revenue_classification" or
   "passenger event" — it says *"These riders were counted by a bus while
   nobody was logged into a run."* Each row shows the vehicle by its fleet
   number, the riders at stake, the service day, the calculation's own reason,
   and — deliberately — **"No suggestion. Headway will not guess this one"**
   rather than a nudge. "Route and run: None — that is exactly why this
   boarding is here" turns an empty field into the explanation. The decision is
   two labelled radios with plain-language guidance plus a **required** note,
   and the recompute warning sits AT the moment of deciding with a link
   straight to Compute figures. Empty state is inviting ("Nothing is waiting on
   you"). Server-side keyset paging; the header cards are the server's
   whole-queue counts and say so.

7. **The receipt (design point 2).** `web/src/detail.ts` gains
   `revenueSplit()`; `web/src/components/Receipt.tsx` renders **"Judgment calls
   behind this number"** — per decision, the verdict, the vehicle and time, who
   decided and when, and their justification **verbatim** — followed by the
   honest note that these were read when the figure was computed and that later
   decisions apply to the next run. Every other surface that lists detail gets
   plain sentences for the split (auto-excluded, human-counted, human-excluded,
   still-held + the exclude-until-classified policy).

### Test totals (captured, not inferred)

- api: `cd services/api && python -m pytest -q` → **520 passed** (was 498;
  +22 in `tests/test_revenue_review.py`).
- calc: `cd services/calc && python -m pytest -q` → **679 passed** (was 660;
  +19 in `tests/test_boarding_review_loop.py`; five existing `0.3.0` version
  assertions updated to `0.4.0`).
- web: `cd web && npm test` → **352 passed / 42 files** (was 337; +15 in
  `src/test/revenueReview.test.tsx`, including three receipt tests). Every new
  view test runs the axe gate.
- web: `npm run build` → clean (tsc -b + vite build).
- migrations static: `python -m pytest -q db/test_migrations_static.py` →
  **30 passed**.
- `services/api/openapi.json` regenerated: 75 paths, +4 for this router.

### Live verification (real Postgres/TimescaleDB on this box, 2026-08-01)

Not a fake connection — the compose stack's `headway-timescaledb-1`, which was
at migration 0039.

- **Migration 0040 applied** to the live database; table, both partial indexes,
  the FK to `dq.issues` and all four CHECKs present (`\d` output captured).
- **The schema refuses a reasonless decision, live:** a verdict with a
  whitespace note → `boarding_review_justification_not_blank`; a verdict with
  no note at all → `boarding_review_decision_complete`. Both rejected by
  Postgres, not by application code.
- **Calc round trip, live:** `persist_review_items` wrote a pending row;
  re-running UPSERTed it (idempotent); `load_boarding_reviews` returned `{}`
  while undecided and the full `HumanBoardingVerdict` after a decision; and
  **re-running after the decision wrote 0 rows and left the human verdict
  untouched** — the UPSERT's own `WHERE verdict IS NULL` proven against real
  SQL.
- **API against the live database** (uvicorn on :8099): pending queue, counts,
  classify (200, audit row written), second attempt (409 naming the first
  decider), blank note (422), viewer POST (403) with viewer GET still 200, and
  the **certified-period refusal (409)** exercised by inserting a certified
  `upt` metric value covering the boarding's service date — after which
  `verdict` was still NULL and no audit row existed. The temporary certified
  figure was deleted afterwards.
- **Audit row, read back from `audit.events`:** actor `rev.steward`, action
  `boarding_revenue_classify`, subject `dq.boarding_revenue_reviews` /
  `live-pe-3684-1510`, detail carrying the verdict, the full justification,
  the suggested verdict, the vehicle, the count, the source record,
  `classified_by_role: data_steward` and `figure_recomputed: false`.
- **End-to-end through the browser** against that live API: signed in as a
  data steward, opened /revenue-review, filled the decision form, saved, and
  watched the row move from "Waiting on a decision" to "Decided so far" with
  the note attributed — screenshots below.

### Screenshots (`docs/images/handoff-0040/`, live data, light + dark)

- `review-queue-light.png` / `review-queue-dark.png` — the queue.
- `decide-form-light.png` / `decide-form-dark.png` — the decision, with the
  required note and the recompute warning in place.
- `justification-required-light.png` — the note refusing to be skipped.
- `decided-light.png` / `decided-dark.png` — decided boardings with who, when
  and why, and the toast confirming the figure moves on the next run.
- `receipt-judgments-light.png` / `receipt-judgments-dark.png` — "Judgment
  calls behind this number" inside "explain this number", above the verbatim
  FTA quote.

### NTD tracker

`services/calc/REGULATORY_TRACKER.md` gains the upt_v0 **0.4.0** row and the
"Verified — revenue classification of boardings" section is updated to record
that the review queue closes the pending path. **No new regulatory claim is
made**: the manual still says nothing about telling prep from a catch-up bus,
and Headway still does not infer it — it records who decided, when, and on
what grounds.

### Deferred / noted

- **Detour-flag surfacing** stays deferred (needs a
  `canonical.passenger_events` contract field), exactly as in the 0.3.0
  evidence.
- **Reviewer qualifications** are not modelled. Headway gates at data-steward
  and records the role in the audit event; it claims nothing beyond that. If
  the receiving form ever needs a stated reviewer competency (the p. 146
  statistician precedent), that is a new decision, not an inference from this
  wave.
- **No CSS was added.** `web/src/styles.css` was deliberately not touched
  (Track D's settled tokens). The queue consumes existing classes (`.card`,
  `.issue-list`, `.summary-cards`, `.dq-chips`, `.dq-pager`, `.dq-showing`,
  `.banner`, `.alert`, `.field-hint`, `.figure`). Two container hooks
  (`.receipt-judgments`, `.judgment-list`) carry no styles today and inherit
  base element styling; if the design owner wants them treated, that is a
  styles.css change for whoever owns that file.
- **A boarding whose finding predates this wave** cannot be classified: it has
  no queue row. Re-running the calculation over the period raises it again and
  puts it in the queue — stated rather than silently worked around.

---

## External adversarial review — findings fixed (2026-08-01)

The session diff went through a **different model family** (via `agy`) using
`tools/review-pack/build.py`. Five findings came back; each was verified against
live code before acting, because an external "confirmed" is a hypothesis, not a
verdict. **Four were real and are fixed here; one was refuted by measurement.**

### REFUTED — DST spring-forward does not drop riders

The review argued `revenue_window.scheduled_instant` used wall-clock addition,
so on a spring-forward day a 24:00:00 GTFS time would land an hour early and
end-of-service catch-up boardings would be auto-excluded. **Tested rather than
reasoned about:** for `America/Los_Angeles` on 2026-03-08, wall-clock addition
and elapsed-from-anchor agree exactly at 08:00, 23:00, 24:00 and 26:00 (24:00 →
2026-03-09 07:00 UTC under both). The renderings are also correct in local
terms: 08:00 → 08:00 local, 24:00 → midnight the next day. The two readings
diverge only for a time strictly *before* the transition (01:00), where the
current behaviour — 01:00 local — is the practical GTFS meaning. A nonexistent
local time (02:30) resolves to 03:30 local rather than erroring. No fix made;
the claimed exploit does not occur.

### F5 (highest impact) — a total APC outage CRASHED instead of refusing

`upt.py`'s p. 146 attested factor-up divides by `operated - missing`. When every
operated trip is missing that divisor is **exactly zero**, so a 100% outage with
a governing statistician attestation on file raised `decimal.DivisionByZero`.
The whole platform's rule is to refuse loudly and say why; this was a crash in
the exact case the rule exists for. Factoring up needs observed trips to scale
FROM — with none observed there is nothing to scale, and no attestation can
conjure one. The branch is now guarded by `trips_with_events_count > 0`, so the
case falls to the existing refusal, which already speaks to a total outage
("start with the feed rather than the trips"). Pinned by two tests: the outage
refuses, and a *partial* outage with an attestation still factors up — the
guard must not disarm the path it protects.

### F4 — the "schema-enforced" justification was bypassable by invisible text

Handoff 0040 stated the required justification is enforced **in the schema**.
It was not. `btrim(justification)` with one argument removes the SPACE
character only, and Python's `str.strip()` does not treat U+200B as whitespace
— so a justification consisting solely of a zero-width space satisfied **both**
layers and landed a verdict with an unreadable reason. **Proven in real
Postgres** on a disposable container: the 0040 constraint returned `INSERT 0 1`
for a zero-width space; the new one rejects it, while real prose and NULL still
insert. Fixed in two places: **migration 0041** trims zero-width and
non-breaking characters before the non-empty test, and the API's validator now
drops Unicode categories Cf/Cc wholesale so a future invisible codepoint cannot
reopen the hole. A real note that merely *contains* an invisible character (a
paste out of a word processor) still works — it is cleaned, not rejected.

### F2 — an unclassified boarding vanished without a word (upt_v0 0.5.0)

A boarding with no trip **and** no `revenue_classification` at all (NULL, not
`'unassigned'`) reached none of the three split buckets and was skipped in
silence, so the split stopped accounting for every boarding. The live cause is
real and not hypothetical: **every `passenger_events` row written before
migration 0039 has `revenue_classification = NULL`**, as does anything an older
adapter emits.

The **figure is unchanged** — such a boarding is not counted under 0.4.0 or
0.5.0, because with no classification there is no basis to call it revenue and
inventing one would put a guess into a reported number. What changes is that
the omission now announces itself: one warning finding
(`boarding_unclassified_no_run`) naming the vehicle, time and count, plus an
`unclassified_no_run_boardings` key stated **outside** the three split counts —
it is the set the split could not account for, not a fourth bucket of it.

**A regression this caught in passing.** The first cut of the fix leaked
backwards: the retained-version wrappers delegate to the same `compute_upt` and
only relabel `calc_version`, so 0.1.0–0.4.0 began emitting the new warning and
detail key — breaking byte-identical recomputation for anything certified under
them. That is the audit guarantee, and it was found by running the suite rather
than by reading the diff. The version boundary is now expressed **as code**: a
private `_report_unclassified` flag that every retained wrapper passes `False`.
`compute_upt_v0_4_0` was added as a retained runnable (0.4.0 shipped earlier the
same day), and the byte-identity test was rewritten to assert the thing that
actually matters — the retained runnable reproduces 0.2.0 exactly, while the
current version is free to say MORE about the same number, never to report a
different one.

### Suites after the fixes

calc **681**, api **522**, transform 237, web 411, migrations 30 — all green;
openapi/quotes drift gates clean.
