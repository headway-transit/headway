# Handoff: ntd-compliance-engineer → backend, frontend, ntd-compliance — Safety & Security module v0

## Context
S&S definitions verified 2026-07-12 (tracker, "Verified — Safety & Security reporting"; 2026 S&S Policy Manual pp. 3–19 quoted). Unlike every prior metric, S&S events are NOT derivable from telemetry — the source is structured **manual entry with validation** (chartered in the Ingestion role since day one, never built) plus future CAD/incident connectors. v0 delivers the entry workflow, threshold auto-classification, and the two recurring artifacts (S&S-50 monthly summary; S&S-40 due-date tracking).

## Design (binding)
1. **Schema (migration 0017):** `safety.events` — event_id UUID PK; occurred_at TIMESTAMPTZ NOT NULL; mode TEXT NOT NULL; type_of_service TEXT; event_category TEXT (collision/derailment/fire/evacuation/security/assault/cyber/other — enum per manual vocabulary); narrative TEXT NOT NULL; location TEXT; counts: fatalities INT DEFAULT 0, injuries INT DEFAULT 0 (immediate-transport definition), property_damage_usd NUMERIC, serious_injury BOOLEAN (rail criteria), substantial_damage BOOLEAN (rail), towed BOOLEAN, evacuation_life_safety BOOLEAN, assault_on_worker BOOLEAN, involves_transit_vehicle BOOLEAN, involves_second_rail_vehicle BOOLEAN, grade_crossing BOOLEAN; entered_by TEXT NOT NULL; entered_at; superseded_by UUID NULL (corrections are append-only — a corrected event points at its replacement; originals never deleted — audit discipline). Plus `safety.event_classifications` written ONLY by the classifier (below): event_id, classification ('major'|'non_major'|'not_reportable'), thresholds_met TEXT[], classifier_version, classified_at.
2. **The classifier is calc-discipline code** (services/calc, new `sscls_v0` 0.1.0, tracker row): pure deterministic function events→classification implementing Exhibit 5 EXACTLY as quoted in the tracker (mode-dependent: rail vs non-rail thresholds; $25,000 damage; injury=immediate transport; rail serious-injury criteria; collision/evacuation/derailment/runaway rules; predominant-use is agency-supplied mode, documented). Goldens: the manual's own Examples 4A–4H as fixtures (Scenario A → major (2 injuries); B → rail-collision auto-reportable; G → cyber major; etc. — hand-worked against the quoted solutions). Any event meeting ≥1 threshold = ONE report (p. 14).
3. **API (Backend):** POST /safety/events (role data_steward+; validation plain-language; audited; runs classifier synchronously and returns classification + thresholds_met + plain-language explanation); GET /safety/events (filters incl. classification, month); corrections via POST /safety/events/{id}/supersede (new event row + link; audited). **Due-date surfacing:** GET /safety/deadlines — computed: per open major event, S&S-40 due date (occurred_at + 30 days, quote-cited); per month/mode, S&S-50 due end of following month (Exhibit 3), INCLUDING zero-event months (the trap the manual warns about — "even if no event occurs").
4. **S&S-50 generator (calc, like mr20.py):** `ss50.py --month YYYY-MM` — per mode/TOS: non-major event counts (injury-threshold events, non-major fires, assaults-on-worker incl. no-injury assaults), plus explicit zero-rows for operated modes with no events; NOT-REPORTABLE banner + citations, per-cell provenance (event_ids). S&S-40 detail export per major event (JSON with every threshold's supporting fields).
5. **UI (Frontend):** /safety — event entry form (plain language per field: "Was anyone taken directly from the scene for medical care?" not "injury threshold"; progressive disclosure of rail-only fields when mode is rail); events list with classification chips + thresholds-met receipts (quote + citation via the tracker-extract pattern in web/scripts/extract-quotes.mjs — extend it to the S&S section); a deadlines panel ("S&S-40 for event X due in N days"; "S&S-50 for June: due July 31 — includes 3 modes with zero events"). Axe + keyboard + contrast as always.
6. **Honest scope:** no NTD-portal e-filing (format unverified); CR/AR safety-event exclusions and per-mode nuances beyond Exhibit 1's table are flagged in output, not silently applied; cyber events enterable (category 'cyber') citing Scenario G.

## Outputs
Migration 0017 + classifier w/ Example-4 goldens + API + ss50 generator + UI, suites green, tracker row for sscls_v0, evidence appended here.

## Open Questions
- Full S&S-40 form field enumeration (manual pp. 20+ detail per-threshold sub-forms) — v0 captures the threshold-supporting fields above; the complete form walk is v1 (owner: NTD role, read pp. 20–40 next).
- CAD/incident-system connector for automated event intake — Ingestion roadmap.

## Outputs — backend evidence

Backend + calc deliverables (migration 0017; sscls_v0 0.1.0 classifier;
safety API; ss50 generator + ss40 export) built 2026-07-12. All regulatory
facts implemented ONLY as quoted in `services/calc/REGULATORY_TRACKER.md`,
"Verified — Safety & Security reporting (verified 2026-07-12)"; the new
sscls_v0 tracker row records the documented interpretations and open items.

### Suites (before → after)

```
$ cd services/calc && python3 -m pytest tests/ -q        # before: 245 passed
277 passed, 4 skipped in 12.34s
$ cd services/api  && python3 -m pytest tests/ -q        # before: 136 passed
152 passed, 1 warning in 3.64s
$ cd db && python3 -m pytest test_migrations_static.py -q  # before: 15 passed
17 passed in 0.13s
$ cd services/transform && python3 -m pytest tests/ -q   # untouched, still green
49 passed in 0.19s
$ cd services/ai && python3 -m pytest tests/ -q && python3 -m headway_ai.regression
109 passed in 0.18s
grounding regression gate: PASS — 6/6 fixture verdicts matched
```

The 4 calc skips are deliberate: Example 4 scenarios C/D/F/H goldens cannot
be hand-worked without regulatory facts not yet quoted in the tracker (open
question below).

### Migration 0017 — applied live and inspected via a SEPARATE psql connection

```
$ PGHOST=127.0.0.1 PGUSER=headway PGPASSWORD=*** PGDATABASE=headway python3 db/migrate.py
applying 0017_safety_events.sql ... ok
applied 1 migration(s)

$ sg docker -c "docker exec headway-timescaledb-1 psql -U headway -d headway -c '\d safety.events'"
 event_id  | uuid  | not null | gen_random_uuid()   (… 21 columns as designed …)
Check constraints: events_event_category_check (8 categories),
  events_fatalities_check, events_injuries_check,
  events_no_self_supersede, events_property_damage_usd_check
Triggers: events_append_only BEFORE DELETE OR UPDATE … FOR EACH ROW
safety.event_classifications: major_iff_thresholds_met CHECK
  ((classification = 'major') = (cardinality(thresholds_met) > 0)),
  event_classifications_append_only trigger (BEFORE DELETE OR UPDATE)
schema_migrations: 0017_safety_events.sql | 2026-07-12 13:02:24+00
```

Append-only proven by attack (all inside rolled-back transactions; both
tables count 0 afterwards):

```
DELETE FROM safety.events …
ERROR:  safety.events is append-only: DELETE rejected. Corrections supersede …
UPDATE safety.events SET narrative = 'rewritten' …
ERROR:  safety.events is append-only: the only permitted UPDATE is setting
        superseded_by once, with every other column unchanged. …
UPDATE safety.events SET superseded_by = <replacement> …   → UPDATE 1 (permitted, once)
INSERT INTO safety.event_classifications (… 'major', '{}' …)
ERROR:  … violates check constraint "major_iff_thresholds_met"
```

### Live API run — the autocommit-phantom-write check

The dev API was restarted with the new code (the running uvicorn predated
this work; note: the original 127.0.0.1:8000 process was stopped and
restarted from the same source tree with equivalent env — a fresh
HEADWAY_SESSION_SECRET was generated, so pre-existing session tokens are
invalid; live verification itself ran against a second instance on :8001,
since torn down). Login as `dsteward` (data_steward), then:

```
$ curl -X POST http://127.0.0.1:8001/safety/events … {"occurred_at":"2026-07-08T14:30:00Z",
  "mode":"bus","type_of_service":"DO","event_category":"collision", …,"injuries":2,
  "property_damage_usd":"18000.00","involves_transit_vehicle":true}
HTTP 201
{"event_id":"9c31d3ba-5247-4566-8cfc-330ca750f63c", … "classification":"major",
 "thresholds_met":["injury_immediate_transport"],
 "explanations":[{… "plain_language":"2 person(s) were taken directly from the scene
   for medical care.","citation":"Exhibit 5, p. 16 — 'Immediate transport away from
   the scene for medical attention for one or more persons.' (… REGULATORY_TRACKER.md …)"}],
 "classifier_version":"sscls_v0 0.1.0","audit_event_id":520}
```

Verified from a SEPARATE psql connection (docker exec — never the API's own
connection; this is exactly the 2026-07-10 autocommit bug class check):

```
safety.events:              9c31d3ba-… | 2026-07-08 14:30:00+00 | bus | collision | 2 | 18000.00 | dsteward
safety.event_classifications: 2 | 9c31d3ba-… | major | {injury_immediate_transport} | sscls_v0 0.1.0
audit.events:               520 | dsteward | safety_event_create | 9c31d3ba-…
```

Also exercised live: a non-major assault-on-worker entry (201, non_major,
basis citation "'Assaults on a transit worker do not require an injury…'");
GET /safety/events with month/mode/classification filters; supersede
(damage reassessed $18,000 → $31,000: replacement classified major with
["injury_immediate_transport","property_damage_25k"], original's
superseded_by set — psql-confirmed; second supersede on the same original
→ 409 with the append-only message); GET /safety/deadlines?month=2026-07 —
the S&S-40 row lists ONLY the unsuperseded replacement (due 2026-08-07 =
occurred_at + 30 days, Exhibit 2 p. 4) and the S&S-50 rows cover the REAL
operated modes derived from live canonical telemetry (bus, rail, subway,
tram, unknown — the handoff-0009 derivation), zero-event modes included,
all due 2026-08-31.

### ss50 generator against real data

```
$ python -m headway_calc.ss50 --month 2026-07
form S&S-50, due_date 2026-08-31, reportable false, NOT-REPORTABLE banner,
citations [ss50_scope, ss50_timing, cr_ar_nuance],
caveats [not_reportable_preview, cr_ar_not_applied, tos_attribution, superseded_excluded],
operated_modes [bus, rail, subway, tram, unknown],
cells: (bus, DO) assaults_on_worker {count 1, without_injury 1,
        event_ids [16e320be-f684-4402-904d-cbef7e120624]};
       explicit zero rows for (rail|subway|tram|unknown, unknown TOS),
excluded: major [fbb6ea0c-…], superseded [9c31d3ba-…], unclassified [].

$ python -m headway_calc.ss50 --ss40-event fbb6ea0c-2510-40de-bd9a-2f243945c5a8
form S&S-40, due 2026-08-07 (Exhibit 2 p. 4 citation), classification major,
thresholds [{injury_immediate_transport: {injuries: 2}},
            {property_damage_25k: {property_damage_usd: "31000.00"}}], notes [].
```

The three LIVE-VERIFICATION events remain in the dev database by design —
safety.events is append-only (their narratives are prefixed
"LIVE-VERIFICATION handoff 0010").

### Deviations from the handoff letter (with reasons) / open questions

1. **Runaway-train rule NOT implemented.** The binding schema captures no
   runaway field and the tracker quotes no condition — implementing one
   would mean a regulatory fact from memory. Owner: NTD role (quote p. 17,
   then a schema/classifier increment).
2. **Evacuation and derailment thresholds carry a PENDING-quote caveat in
   their citations**: the conditions are encoded by the handoff's own field
   (`evacuation_life_safety`) and category vocabulary (`derailment`), but
   the tracker records the p. 17 rules only as "verbatim rules on file".
   Owner: NTD role — extract the quotes; the sscls_v0 tracker row lists this.
3. **Injury/damage thresholds are gated NON-RAIL** per the tracker labels
   "(non-rail/ferry)" and "(non-rail)": a rail immediate-transport injury
   not meeting the rail serious-injury criteria classifies non_major
   (S&S-50 injury-threshold event). This interpretation must be confirmed
   against Exhibit 5's layout (owner: NTD role).
4. **Example 4 goldens cover A/B/E/G only** (the outcomes documented in the
   tracker/handoff); C/D/F/H are pytest skips naming the missing quotes —
   never invented.
5. **No tow-away threshold**: `towed` is captured as a supporting field for
   the rail substantial-damage determination only, pending a verbatim quote.
6. **GET /safety/deadlines treats every unsuperseded major event as open**
   (stated in `ss40_note`): v0 has no submission tracking; mark-as-submitted
   is a future increment.
7. **CR/AR nuance flagged, not applied** (per design point 6): the
   Headway-mode ↔ NTD CR/AR mapping is an unresolved agency-level question;
   ss50 output carries the cr_ar_not_applied caveat.
8. **UI (design point 5) not built here** — frontend scope; nothing under
   web/ was touched. `services/api/openapi.json` was regenerated and now
   carries the three /safety paths for the web team.

## Outputs — frontend evidence

**Delivered (design point 5):** the `/safety` route (`web/src/views/SafetyView.tsx`,
route in `web/src/App.tsx`, nav in `web/src/components/Layout.tsx`), typed against
`services/api/headway_api/routers/safety.py`'s request/response models EXACTLY
(`web/src/api/types.ts` — SafetyEventRequest/SafetySupersedeRequest/
SafetyEventCreated/SafetyEventSuperseded/SafetyEventRecord/
SafetyClassificationResult/Ss40Deadline/Ss50Deadline/SafetyDeadlines; endpoints in
`web/src/api/client.ts`; field-level parity checked against the live
`/openapi.json` export). Three rooms:

1. **Deadlines panel** (`GET /safety/deadlines`): S&S-40 per open major event and
   the S&S-50 per-mode rows INCLUDING zero-event rows ("0 events — the summary is
   still due"), each timing rule shown as the VERBATIM tracker quote + citation
   (extract-quotes pattern), the API's `ss40_note` shown verbatim, urgency as
   text + distinct icon shape + color (never color alone). The only client-side
   date math is days-until-the-API-served-due-date (presentation urgency).
2. **Entry form** (`POST /safety/events`, data_steward+ — UX gate only, API
   enforces): plain-language questions ("Was anyone taken directly from the scene
   for medical care? How many people?" — never "injury threshold"); rail-only
   questions (serious-injury criteria, substantial damage, second rail vehicle,
   grade crossing, and the derailment category) disclosed ONLY when the picked
   mode is in the classifier's own rail set (`sscls.RAIL_MODES` vocabulary —
   tram/subway/rail/cable_tram/funicular/monorail); client-side validation
   mirroring the contract (required fields, whole counts, decimal damage,
   timezone-carrying occurred_at) with API refusals still shown verbatim;
   `property_damage_usd` is a decimal STRING end to end. On submit the returned
   verdict renders as a **classification receipt**: chip + the classifier's
   `summary` and per-threshold `plain_language`/`citation` VERBATIM + the
   verified manual quote per token from `src/regulatory/quotes.json`
   (token→snippet map in `web/src/regulatory/safetyRules.ts`); unknown tokens
   and unmapped quotes are stated loudly, never hidden; `classifier_version`
   ("sscls_v0 0.1.0") displayed verbatim, never parsed.
3. **Events list** (`GET /safety/events`): classification chips
   (major=danger/octagon, non-major=warning/triangle, not-reportable=info/circle
   — text + icon + color), per-event thresholds receipts (aria-expanded
   toggles), a LOUD state for a record with no classification on file, and the
   **supersede flow** (`POST /safety/events/{id}/supersede` with its REQUIRED
   audit `reason`): the original stays on the page struck (`<s>`), tagged
   "Corrected — see the replacement", and anchor-linked to its replacement —
   never hidden.

**Honest scope (design point 6):** a banner on every visit — alpha, not
certified for submission, no NTD e-filing (format unverified), CR/AR nuances
flagged in output rather than silently applied.

**extract-quotes extended** (`web/scripts/extract-quotes.mjs`): now also slices
"Verified — Safety & Security reporting" (→ `sscls_v0`) and — required to make
the script run at all against the current tracker — "Verified — Monthly
Ridership form MR-20" (→ `voms_v0`; the voms_v0 table row previously failed the
script's own loud gate, a pre-existing breakage since handoff 0009). Handles the
S&S section's `**Label (page):**` bullet shape; unwraps the tracker's `**`
markdown emphasis inside quotes (the only in-quote cleanup — one pre-existing
vrh_v0 quote shipped with literal `**No**` and is now clean); text after a
bullet's `NOTE:` (tracker meta-commentary about the manual's wording, e.g. the
"cybersecurity" zero-hit lesson) is never extracted as a quote. Current output:
`sscls_v0: 25, upt_v0: 8, voms_v0: 4, vrh_v0: 10, vrm_v0: 10` — all previously
shipped upt/vrm quotes byte-identical. After the NTD role added the p. 17
verbatim quotes, the token map gained rail_to_rail_collision /
evacuation_life_safety / derailment; rail_serious_injury and
rail_substantial_damage remain deliberately unmapped (tracker summaries, not
quotations) and their receipts state the gap.

**Verification (all at the working tree, 2026-07-12):**

- `npm test -- --run`: **17 files, 95 tests, all passing** (85 pre-existing +
  8 new in `src/test/safety.test.tsx` + 2 new in `src/test/quotes.test.ts`).
  Safety tests cover: deadlines urgency + zero-event rows + verbatim citations;
  viewer read-only gating; rail-only progressive disclosure incl. category
  clearing; client-side refusal with zero API calls; contract-exact POST body
  (damage string, no rail fields for bus, timezone timestamp); the rich receipt
  (summary/explanations verbatim + quote + citation + re-fetch after write);
  non-major S&S-50 basis with the assault quote; unknown-token loudness; the
  supersede flow (required reason refused empty client-side; original struck +
  linked; single Correct button); verbatim 422 surfacing. quotes tests pin the
  S&S-40/S&S-50/injury quotes character-for-character against the tracker and
  require every snippet in `safetyRules.ts` to resolve.
- Every safety view test asserts **zero axe-core violations**; keyboard paths
  exercised (Enter on aria-expanded toggles, aria-pressed patterns reused).
- `npm run check:contrast`: all token pairs PASS (safety chips/urgency reuse
  existing AA-verified pairs only; no new pairs added).
- `npm run lint` (oxlint): clean. `npm run build` (tsc -b + vite): clean —
  dist/assets/index-D4y2zgt8.js 409.23 kB (gzip 124.34 kB).

**LIVE click-through — real browser against the running API** (headless Chrome
via puppeteer-core driving the Vite dev server at :5173 →
`VITE_API_BASE_URL=http://127.0.0.1:8000`, signed in as `dsteward` through the
login form, SPA navigation only — the in-memory token survives):

```
signed in as dsteward
banner, deadlines quotes+citations, sections: present
backend-seeded supersede chain renders struck+linked: { struck: true,
  tag: 'Corrected — see the replacement',
  link: '#event-b58a4eac-f98e-4fc8-965a-201db7fd593e' }
event recorded; live classification receipt verified
correction recorded; original struck + linked, never hidden
deadlines re-read from the API: open majors listed with urgency; the
  corrected-to-non-major event owes none
keyboard: receipt toggle focusable and Enter-operable
CLICKTHROUGH PASSED — no page errors
```

Flow verified end to end: entry form (bus collision, 1 person transported) →
201 with live verdict `major` / `injury_immediate_transport` → receipt showed
"Decided by classifier sscls_v0 0.1.0", the classifier's sentences verbatim,
and the Exhibit 5 p. 16 quote + citation → events list re-read (backend's
LIVE-VERIFICATION events and supersede chain rendered; original struck+linked)
→ corrected the new event through the form (injuries→0, required reason) →
original struck + linked, replacement present → deadlines re-read: the
superseded original and its non-major replacement owe no S&S-40, the open
2026-07-02 majors do, with urgency text. Direct API exercise additionally
captured: POST /safety/events 201 (`bf5df996-…`, audit_event_id 525) with the
exact UI body shape. Six full-page screenshots captured at each station
(session scratchpad, `shot-1…6*.png`).

**Contract points reconciled while the backend was built in parallel** (for the
orchestrator to note; all now aligned with the shipped router — no open
divergence):

1. **Mode vocabulary** is Headway's canonical transform map
   (bus/tram/subway/rail/ferry/…), NOT NTD MR-20 codes — the UI's mode select
   and its rail-disclosure set mirror `sscls.RAIL_MODES` exactly.
2. **`classifier_version` is the combined string** "sscls_v0 0.1.0" — displayed
   verbatim, never parsed (per coordinator confirmation).
3. **List records are FLAT and nullable** (no explanations/summary on
   GET /safety/events): list receipts render token→label+quote only; the rich
   prose receipt appears on entry/supersede responses. If a later increment
   serves explanations on the list, the receipt component already renders them.
4. **Supersede requires `reason`** — mirrored client-side as a required field
   with plain-language refusal.
5. **Non-major ⇒ empty thresholds_met** (DB CHECK 'major' ⇔ thresholds non-empty);
   S&S-50 scope arrives as `non_major_basis` and gets its own receipt section
   with the p. 3 assault quote.
6. **Deadlines**: `ss50` rows carry no type_of_service (mode-only in v0) and a
   `zero_event` flag; `ss40_note`/citations are API strings shown verbatim.

**Known gaps / next increments (frontend):** manual screen-reader pass still
pending (as for every view — tracked in web/README.md); rail
serious-injury/substantial-damage receipts await verbatim Exhibit 5 rail-row
quotes in the tracker (they state the gap today); deadline month navigation
(the API accepts ?month=) not yet surfaced — the panel shows the API's default
current month; classification/month/mode list filters (API supports them) not
yet surfaced in the UI. Migration 0018 (runaway_train / evacuation-to-ROW
capture booleans) landed in the DB during this round but is NOT yet exposed by
the API's SafetyEventCreate/Record models (verified against the live
/openapi.json — zero hits); when the backend extends the contract, the form's
rail-only fieldset is where those two questions belong.

Nothing under `db/`, `services/` was modified by this role; the handoff's
design sections are untouched. Not committed (per instruction).

### Correction round — S&S addenda 1+2 folded in (2026-07-12, backend evidence)

The tracker's "S&S addendum — verbatim rules for sscls" (pp. 17–22, second
pass) and "S&S addendum 2 — damage + injury definitions verbatim"
(pp. 21–27, third pass) were implemented as **sscls_v0 0.1.1** (tracker
version row added; the 0.1.0 row stands unedited with a dated superseding
note; 0.1.0 retained runnable as `classify_event_v0_1_0` with its
single-injury Other-Safety-Event bug pinned by test).

What changed (each cited verbatim in code and tracker row):
p. 22 Other Safety Events exception (the 0.1.0 BUG FIX — single-injury
Other events are S&S-50, two or more injuries are major, any mode); rail
collision injury threshold at ONE injury (Example 4C); non-rail
`collision_towaway`; `rail_collision_grade_crossing`;
`rail_collision_vehicle_contact_assault` (no injury needed on rail);
`runaway_train` and `rail_evacuation_to_row` (migration 0018 booleans);
derailment/evacuation citations now verbatim (former PENDING caveats
cleared); rail serious injury verbatim p. 21 — automatically reportable,
transport NOT required (Example 6C rail-vs-bus asymmetry golden); rail
collision tow-away IS substantial damage (Example 7C, mechanical); p. 25
substantial-damage exclusions + property-damage summing (Example 7A) and
p. 20/22 fatality/injury exclusions surfaced as API field hints, never
silent logic. Goldens now cover ALL EIGHT Example 4 scenarios plus
6C/6E/6F/7C — zero skips.

Suites (after the correction round; every suite green):

```
services/calc: 294 passed          (was 277 + 4 skips; +17, skips eliminated)
services/api:  154 passed          (was 152; +2: runaway field flow, p. 22 fix through the endpoint)
db static:      18 passed          (was 17; +1 for migration 0018)
transform 49 / ai 109 + grounding gate PASS — untouched, still green
```

Migration 0018 live (separate psql connection):

```
$ python3 db/migrate.py
applying 0018_safety_runaway_evacuation.sql ... ok
$ docker exec headway-timescaledb-1 psql … information_schema.columns …
 evacuation_to_rail_row | boolean | false | NO
 runaway_train          | boolean | false | NO
schema_migrations: 0018_safety_runaway_evacuation.sql | 2026-07-12 18:29:38+00
(all 13 pre-0018 events backfilled false/false — honest: the fields did not exist)
```

Live API round 2 (running instance on 127.0.0.1:8000, new code; verified
from a separate psql connection afterwards — event + classification +
audit rows all present, classifier_version 'sscls_v0 0.1.1'):

```
POST subway 'other' + runaway_train=true            → 201 major {runaway_train}
   (citation: the p. 17 verbatim runaway definition; audit 550)
POST bus 'other' + injuries=1 (slip, EMS transport) → 201 non_major,
   basis other_safety_event_single_injury, citation p. 22 'reported on the
   Non-Major Summary Report' (audit 551) — the 0.1.0 bug class, now fixed
POST tram collision + towed=true, no injuries       → 201 major
   {rail_substantial_damage} via Example 7C (audit 552)
```

ss50 generator against the live database (2026-07):

```
$ python -m headway_calc.ss50 --month 2026-07
bus/DO injury_events count 2 — event_ids include a059faaa-… (the live
slip event: single-injury Other Safety Event now correctly counted on the
Non-Major Summary); the runaway (8a450fef-…) and 7C tow-away (8de8a02f-…)
events appear under excluded.major_event_ids; zero rows for
rail/subway/tram/unknown.
$ python -m headway_calc.ss50 --ss40-event 8a450fef-…
major {runaway_train}, supporting_fields {runaway_train: true, mode:
subway}, due 2026-08-08 (occurred 2026-07-09 + 30 days), notes [].
```

Historical-verdict check (honesty): every live event whose LATEST
classification is 'sscls_v0 0.1.0' was reviewed against 0.1.1 — all are
bus collisions or a worker assault, none in the p. 22 Other-Safety-Event
class, so **no live verdict changes under 0.1.1** (one event, bf5df996-…,
would today additionally list collision_towaway among its thresholds —
classification unchanged 'major'). Batch re-classification of historical
events under a new classifier version remains a future increment
(append-only inserts through record_classification, the only writer).

Remaining open questions (tracker 0.1.1 row, owner NTD role): (1)
'hazmat'/'act_of_god' category vocabulary (entered as 'other' they would
wrongly get the two-injury exception — flagged in the API field hint);
(2) Exhibit 5 layout confirmation for the "(non-rail/ferry)"/"(non-rail)"
injury/damage grouping; (3) an "Involve an individual" capture field for
rail collisions (Example 4C arrives via the injury threshold in practice).

`services/api/openapi.json` regenerated (SafetyEventCreate now carries
runaway_train, evacuation_to_rail_row, and the p. 20/21/22/25 plain-
language field hints). Nothing under web/ touched; nothing committed.

### Frontend closing pass (sscls_v0 0.1.1 contract, 2026-07-12)

Reconciled against the corrected backend contract and the tracker's two S&S
addendum subsections:

- **Migration-0018 fields surfaced.** `runaway_train` and
  `evacuation_to_rail_row` added to the typed contract
  (SafetyEventRequest/SafetyEventRecord) and to the form's rail-only
  fieldset as plain-language questions ("Did a rail vehicle move on its own
  (a runaway)?" / "Did people evacuate onto the rail right-of-way?") with
  p. 17 hints; sent only for rail modes, like the other rail answers.
- **Form hints updated from the new verified definitions**: fatality
  exclusions (p. 20), injury counting rule + exclusions (pp. 21–22),
  property-damage summing across all involved property + wreckage clearing
  (p. 25), substantial-damage exclusions (p. 25), and the tow-away rule
  (non-rail threshold condition / rail substantial-damage indicator,
  p. 17 / p. 27) on the previously hint-less `towed` checkbox.
- **extract-quotes**: the S&S bullet pattern now accepts trailing bold text
  after the page reference (`**Label (p. N) — note:**`), which the two
  CLASSIFIER-CRITICAL addendum bullets use; both `###` addendum subsections
  were already swept as part of the S&S section. Output now
  `sscls_v0: 39` quotes (upt/voms/vrh/vrm unchanged).
- **Every classifier token now maps to a verbatim quote + page cite**
  (`src/regulatory/safetyRules.ts`): added `injury_two_or_more`,
  `rail_serious_injury` (p. 21 — gap CLOSED), `rail_substantial_damage`
  (p. 25 — gap CLOSED), `rail_collision_grade_crossing`,
  `rail_collision_vehicle_contact_assault`, `collision_towaway`,
  `rail_evacuation_to_row`, `runaway_train`, `non_major_injury_event`,
  `other_safety_event_single_injury`. Deliberately unmapped (no quoted rule
  in the tracker): `non_major_fire` and the Scenario E category note — the
  loud unmapped-token fallback stays as the safety net, and
  `src/test/quotes.test.ts` fails the suite if any mapped snippet stops
  resolving. The receipt also now renders classifier NOTE explanations
  (tokens in `explanations` but not in `thresholds_met`, e.g. Scenario E)
  under "The classifier also noted" — verbatim, never dropped.
- `classifier_version` ("sscls_v0 0.1.1") displayed verbatim, never parsed.

**Re-verification:** `npm test -- --run` 17 files / 95 tests all passing
(axe gates included; rail-disclosure test extended to the two new fields);
oxlint 0 warnings; `npm run build` clean (417.75 kB JS, gzip 126.88 kB);
`npm run check:contrast` all pairs pass; extract-quotes
`sscls_v0: 39, upt_v0: 8, voms_v0: 4, vrh_v0: 10, vrm_v0: 10`.

**LIVE closing checks** (headless Chrome via the dev server → live API,
signed in as dsteward; screenshots `shot2-*.png` in the session scratchpad):

```
signed in; /safety open
(a) rail mode disclosed runaway + evacuation-to-ROW questions
(a) runaway_train=true → MAJOR receipt with the verbatim p. 17 runaway
    quote + citation ("Runaway Train — 2026 Safety & Security Policy
    Manual V1, p. 17, rail only, revenue vehicles")
(b) single-injury slip (other, non-rail) → NON-major receipt with the
    p. 22 Non-Major Summary Report quote + citation ("Other Safety Events
    exception — 2026 Safety & Security Policy Manual V1, p. 22")
CLOSING CHECKS PASSED — no page errors
```

Both live receipts showed "Decided by classifier sscls_v0 0.1.1". The
earlier open item "migration 0018 not yet exposed by the API" is closed by
this round. Still open for a future increment (unchanged): deadline month
navigation, list filters, `hazmat`/`act_of_god` category vocabulary (owner:
NTD role — the two-injury exception would wrongly apply to them as 'other';
the API field hint flags it). Not committed (per instruction).
