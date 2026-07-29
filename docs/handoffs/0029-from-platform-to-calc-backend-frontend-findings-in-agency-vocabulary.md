# Handoff: platform → calc+backend+frontend — Findings must speak the agency's vocabulary

## Context
First-agency UAT (ITS manager, 2026-07-29), on a real blocking finding: *"Looks good but
staff/users will need an easier way to know what exact block they are looking for that had
the issue."* He attached his agency's block list — `1-1`, `1-2`, … `123-4`, `225-4`,
`68-2` — the identifiers his dispatchers actually use. What Headway showed him instead was
a wall of opaque ids.

**The principle this establishes, beyond one issue type: a finding is addressed to a
person who has to go fix something. It must name the thing in the vocabulary that person
uses to find it.** Internal ids stay — they are the provenance — but they are the
footnote, not the headline. This applies to every finding, receipt and export, not just
the one in the screenshot.

### What was verified against the partner agency's LIVE feed (orchestrator, 2026-07-29)

Downloaded their published GTFS (`myride.bft.org/Static/google_transit.zip`, 2,704 trips):

| Field | Value in their feed | Usable as a human label? |
| --- | --- | --- |
| `trip_id` | `a42e79cb-d75b-43f4-a535-801e2211837a` | **No** — opaque UUID |
| `block_id` | `9a06b6cd-7646-4a5a-8390-32098f7e8e4c` (2,704/2,704 populated; **126 distinct**) | **No** — opaque UUID, though the count matches their 126 operational blocks |
| `route_id` / `route_short_name` | `42` / `42` (23 of 23 routes named) | **Yes** |
| `trip_headsign` | `4th Ave / Dayton Transfer Point` (2,704/2,704) | **Yes** |
| `stop_times` departure | first stop time per trip | **Yes** |

So: **the operational block names are not in the feed at all.** No display change alone can
turn `9a06b6cd…` into `225-4`. Two paths, and the wave must not pretend otherwise:

- **The agency's own fix (recommended, free, benefits everyone downstream):** their GTFS
  export emits the operational block name in `block_id`. That is a vendor export setting,
  not a Headway feature, and it makes every consumer — trip planners, their own analysts,
  us — speak dispatch's language.
- **The platform fallback (recorded, NOT built in this wave):** an agency-managed label
  map from feed `block_id` → operational name. Do not build it before asking whether the
  feed can simply carry the names; a mapping table is a permanent maintenance burden
  adopted to work around a one-line export change.

Everything else a dispatcher needs — route, headsign, time of day, and *which trips share a
block* — IS available today, and that is what this wave delivers.

## Design (binding)

1. **Findings carry structured subjects, not prose lists.** Today `upt_v0` formats up to 20
   raw trip ids into the description string (`_MISSING_TRIPS_NAMED`). Replace with a
   structured subject reference on `Finding` — a kind (`canonical.trips`,
   `canonical.vehicle_positions`, …) plus the id list — leaving the prose to say what
   happened, not to carry data. The calc stays pure: it emits ids, it does not query.
2. **Human labels are resolved once, at persistence, and frozen.** The runner (which
   already holds a repository) resolves subject ids to their agency-facing labels — route
   short name, headsign, first departure, block id — and stores them alongside the ids in
   a new structured column on `dq.issues` (migration 0035, additive JSONB). Frozen at
   write time so the finding reads the same in an audit years later; the ids remain so any
   reader can re-derive. **No label is invented**: a trip with no headsign shows no
   headsign, never a guess.
3. **Grouping is the feature.** 1,111 individually listed trips help nobody. The stored
   context groups affected trips **by block**, each group carrying: trip count, the
   route(s) involved, and the time span (first departure → last). A dispatcher recognizes
   "18 trips, Route 42, 06:14–14:22" as a block even when its id is a UUID. Cap what is
   materialized (a stated cap, house voice) and state the total.
4. **The all-affected case says so.** When every operated trip is affected — the live
   case, 1,111 of 1,111 — the finding leads with *"every operated trip in this period"*
   and the likely cause in plain words (no passenger-count data has arrived for this
   period), not with an enumeration. A 100% finding is a different sentence from a 3%
   finding.
5. **Frontend: readable first, forensic on demand.** `/dq` renders the grouped table —
   blocks, counts, routes, times — as the primary content. Raw ids move behind a
   disclosure ("technical detail", collapsed by default) that stays copyable for anyone
   working a ticket. Every affected-trip group links onward where a link exists. The
   verbatim regulatory quote and its page cite stay exactly as they are — that is the
   part that must never be softened.
6. **Honest scope.** No new calc math, no threshold changes, no re-running history: this
   is how findings are *expressed*. Existing issue rows without structured context must
   render exactly as they do today (no crash, no blank panel) — the migration is additive
   and the UI degrades gracefully. No agency block-label mapping (see above).

## Outputs
Calc: `Finding` subject refs + `upt_v0` updated (goldens/regressions adjusted, prose no
longer carrying id lists) and every other finding type reviewed for the same pattern —
fix the ones that are cheap, record the rest. Migration 0035 applied live. Runner
resolution with tests incl. the no-label and missing-trip-row cases. API serves the
context (openapi regenerated). Web: grouped rendering, disclosure, axe + contrast green,
tests. Live verification against the real MBTA-derived issue queue, and a re-run of the
UPT calc showing the new finding shape end to end. Evidence appended here. No commits —
the orchestrator integrates.

## Open Questions
- Agency-managed block-label mapping, IF the partner agency's feed cannot carry
  operational names (ask first).
- The same vocabulary treatment for exports and the monthly workbook.
- Whether `trip_id`-level detail should ever be shown by default, or only per block.

## Outputs — evidence
(appended by the implementing agent)

### Response — calc + backend + frontend (2026-07-29)

Contract accepted with two honest deviations, both stated below and neither
smuggled: **trip headsign does not exist in Headway** (so it is absent from
every context rather than invented), and **no onward link exists** for a
block, route or trip in the app today (so no link was fabricated). Everything
else in the Design section shipped.

---

#### 1. Calc — the subject reference (design points 1 and 6)

`Finding` gained `subject: SubjectRef | None`
(`services/calc/headway_calc/types.py`). A `SubjectRef` is a `kind` (the
canonical table) plus the **complete, never-truncated** list of that table's
primary keys. The calc emits ids; it never queries a database.

Two design decisions worth naming, because both were choices:

- **`subject` is not `source_record_ids`.** Source records are provenance —
  content-addressed raw feed messages, for the lineage graph. A subject is
  the operational thing a person has to go fix. They frequently share no rows
  at all: a missing trip has, by definition, no passenger-event record to
  cite, and it is exactly the trip a dispatcher must find. Folding one into
  the other would have broken lineage to make a display easier.
- **`SUBJECT_KINDS` is closed and checked against the resolver registry.** A
  kind without a resolver produces a finding nobody can label — the precise
  failure this mechanism exists to prevent — so `SUBJECT_KINDS` holds exactly
  the kinds `headway_calc.subjects` can resolve (today: `canonical.trips`),
  and a test asserts the two cannot drift.

**`upt_v0` prose freed of the id list.** `_MISSING_TRIPS_NAMED` is deleted.
The refusal now leads with plain words, and the all-affected case gets its
own opening sentence (design point 4). Live text below.

**Every other finding type reviewed.** Fixed (id list removed from prose,
subject added): `upt_v0` and `pmt_v0`
`apc_missing_trips_above_fta_threshold`; `_blocks.block_unavailable`;
`_blocks.telemetry_gap_excluded` (0.3.0 path). Subject added where the prose
was already id-free: `apc_null_count`, `apc_count_imbalance`,
`apc_negative_load`, `apc_missing_trips_attested_factor_up` (both metrics),
`pmt_invalid_trip_excluded`, `layover_exceeds_max` (both versions),
`telemetry_gap_excluded` (0.2.0 `_grouping` path and 0.4.0 `_blocks` path).

**Recorded, deliberately unchanged:**

| Finding | Why not | 
| --- | --- |
| `coverage_below_threshold` | About a run's coverage *ratio*, not identifiable rows. Every underlying exclusion already carries its own subject. |
| `daytype_average_over_refused_days` | Names DATES. A date already IS the agency's vocabulary. |
| DR findings (`dr_*`) | Name `dr_trip_id` / `vehicle_id` — the agency's OWN dispatch identifiers, not feed surrogates. A `canonical.dr_trips` resolver is a follow-up, not a gap. |
| `sampling_*`, `ops_*`, `unknown_mode_share`, `voms_partial_observation` | Carry no row ids at all (units, timezones, mode names, counts). |

#### 2. Migration 0035 — additive in both directions

`db/migrations/0035_dq_issue_subject_context.sql`: `dq.issues.subject_context
JSONB`, nullable, no default, no backfill, no index (nothing filters or joins
on it; an unused GIN index on a 97k-row table costs every insert for no
read). Applied live via the standard `db/migrate.py` path.

"Additive" is enforced in *both* directions, which is the part that mattered:
every pre-0035 row keeps NULL and renders exactly as before, **and**
`headway_calc.dq` probes for the column and falls back to the pre-0035
INSERT if a database has not been migrated yet — a display feature must never
be the reason a data-quality finding fails to land. Both directions pinned by
test.

```
$ PGHOST=… PGPORT=5432 PGUSER=headway PGDATABASE=headway python db/migrate.py
applying 0035_dq_issue_subject_context.sql ... ok
applied 1 migration(s)

 subject_context    | jsonb  |  |  |          <- \d dq.issues
 total | with_ctx
-------+----------
 97067 |        0                              <- every existing row NULL
```

#### 3. Runner resolution — resolved once, frozen, never invented

`services/calc/headway_calc/subjects.py` (impure by design, beside
`headway_calc.reader`; it never writes). `resolve_contexts` takes a whole
BATCH of findings and issues **one** label query — a single live VRH run
raises 66,286 findings, so a per-finding round trip would have made routing
slower than the calculation. A batch where no finding carries a subject
issues **no query at all**, so every pre-0029 call site is byte-identical.

Stored shape (`version` is the first key any reader checks):

```json
{"version":1,"kind":"canonical.trips","total":2307,"grouped_by":"block",
 "group_count":660,"group_cap":25,"trip_id_cap":20,
 "groups":[{"block_id":"L455-173","trip_count":4,
            "routes":[{"route_id":"442","short_name":"442","long_name":"…"},
                      {"route_id":"455","short_name":"455","long_name":"…"}],
            "route_count":2,"first_departure":"19:05","last_departure":"22:59",
            "trip_ids":["77167045","77167047","77167628","77167638"]}],
 "unmatched":{"trip_count":211,"trip_ids":["…"]}}
```

- **Grouping is the feature** (design point 3): by block, with trip count,
  routes and span, ordered by first scheduled departure — the dispatcher's
  day runs forwards. Caps STATED (`group_cap` 25, `trip_id_cap` 20) beside
  the true totals (`total`, `group_count`, `trip_count`).
- **No label invented** (design point 2): `block_id: null` when the feed
  carries none; `short_name: null` when the route has none; both departures
  `null` when nothing is scheduled; and a trip with no row in
  `canonical.trips` goes into its own `unmatched` bucket rather than being
  folded into a block it does not belong to.
- **GTFS service-day clock**: `24:31` means 00:31 the next morning of the
  same service day. Preserved, not wrapped — wrapping would silently move a
  trip to the wrong day — and the UI says so in words.

#### 4. What the live re-run produced

`python -m headway_calc.runner --period-start 2026-07-22 --period-end
2026-07-23` against the live compose TimescaleDB (real MBTA trips): 132,132
positions, 0 passenger events, 2,307 operated trips → 715 findings routed,
4 metrics blocked, **2.97 s total including all label resolution**.

```
              issue_type               | severity |  n  | ctx
---------------------------------------+----------+-----+-----
 telemetry_gap_excluded                | warning  | 564 | 564
 block_unavailable                     | info     | 146 | 146
 apc_missing_trips_above_fta_threshold | blocking |   2 |   2
 coverage_below_threshold              | blocking |   2 |   0   <- run-level, by design
 layover_exceeds_max                   | warning  |   1 |   1
```

**The new finding, rendered verbatim from the live row** (issue
`9896da03-8ec1-4ee8-a5d9-a4792f22df0c`):

> **No passenger counts arrived for any operated trip: all 2,307 trips in
> this period**
>
> Every operated trip in this period is affected — all 2,307 of the trips
> Headway saw running have no passenger counts at all. When the share is
> 100%, the cause is almost never the individual trips: it usually means no
> passenger-count data reached Headway for this period, so start with the
> feed rather than the trips. Check whether the automatic passenger counter
> feed (or the drop folder the counts arrive in) was delivering on these
> dates before working any trip individually.
>
> Headway cannot report Unlinked Passenger Trips for this period until that
> is settled. Per the 2026 NTD Policy Manual p. 146, 'if the vehicle trips
> with missing data exceed 2 percent of total trips, agencies must have a
> qualified statistician approve the factoring method used to account for the
> missing percentage' — a human decision, so the calculation refuses to emit
> a value rather than estimate one (0.02 is the FTA threshold, not an
> engineering placeholder). Either recover the missing counts, or record the
> statistician's approval as an attestation — the next run then factors up
> under it and the figure carries that approval permanently.
>
> All 2,307 affected trips travel with this finding as structured data, so
> they can be shown grouped by block with each block's route and time of day
> instead of as a wall of identifiers.
>
> Raised by calculation upt_v0 version 0.2.0 for period [2026-07-22,
> 2026-07-23) (half-open, UTC). The calculation refused to emit a value over
> this unresolved gap; no computed.metric_values row was written.

The verbatim FTA sentence and the page cite are byte-unchanged; a test pins
both strings.

**The dispatcher's table**, from the live row (first rows of 25 shown of 660
blocks, 211 trips unmatched):

```
 block    | trips | first–last  | routes
----------+-------+-------------+---------------------------------
 (none)   |  83   | 18:10–24:31 | Fairmount/Fitchburg/… (5 of 12)
 B800-29  |   1   | 18:15–19:21 | D
 B800-42  |   4   | 18:45–23:41 | D
 A57-42   |   3   | 18:52–20:49 | 57
 T64-16   |   2   | 18:56–20:28 | 64
 L455-173 |   4   | 19:05–22:59 | 442, 455
 C01-28   |   2   | 19:06–20:27 | 1
```

The same treatment lands on the highest-volume finding type: a
`telemetry_gap_excluded` warning titled *"vehicle G-10099 trip 76510047"* now
also carries **block B800-45, Green Line E, 19:48–20:42**.

#### 5. API

`DqIssue.subject_context` added to `GET /dq/issues` and
`GET /dq/issues/{id}`, served **verbatim** — the API never re-resolves or
fills in a label. `openapi.json` regenerated: OpenAPI 3.1.0, 63 paths (count
unchanged; one added property).

```
GET /dq/issues/9896da03-… -> 200
  ctx v1 total=2307 group_count=660 shown=25 unmatched=211
GET /dq/issues/c8aa6ac3-… -> 200   (a 2026-07-16 row)
  subject_context = None
```

#### 6. Frontend

`/dq` renders the grouped table as the primary content; raw ids moved into a
collapsed `<details>` ("Technical detail: trip identifiers") that stays
copyable. Screenshots in `docs/images/handoff-0029/`:
`dq-finding-plain-language.jpg`, `dq-blocks-grouped-table.jpg`,
`dq-technical-detail-disclosure.jpg`.

One UI bug found by the live click-through and fixed: finding descriptions
were rendering as one wall of text because HTML collapses the blank lines the
calc writes between paragraphs. `white-space: pre-line` on
`.issue-description` restores them — for every finding, old and new.

Verification, in Chrome against the live API and the live 97k queue:

- **axe-core 4.x run IN the page: 0 violations, 0 incomplete, 223
  colour-contrast nodes checked — light AND dark theme.**
- Keyboard: Tab reaches the disclosure summary (`:focus-visible` → 3 px solid
  outline, 2 px offset, the house ring), Enter opens it, identifiers appear.
- Semantics: real `<table>` with `<caption>`, 4 `<th scope="col">`, 25
  `<th scope="row">`.
- Graceful degradation live: deep-linking a 2026-07-16 finding renders with
  `hasSubjectPanel: false` and its unchanged title, severity, status, owner
  and description.
- `npm run check:contrast`: all 71 token pairs PASS.

#### 7. Test counts (every suite touched)

| Suite | Command | Result |
| --- | --- | --- |
| calc | `pytest -q` (services/calc) | **591 passed** (was 567; +24 `tests/test_subjects.py`) |
| api | `pytest -q` (services/api) | **404 passed** (was 400; +4 `tests/test_dq.py`) |
| db | `pytest -q test_migrations_static.py` | **30 passed** |
| web | `npx vitest run` | **272 passed / 37 files** (+9 `src/test/dqSubject.test.tsx`) |
| web types | `npx tsc --noEmit` | clean |
| web contrast | `npm run check:contrast` | 71/71 PASS |

The two cases the handoff named explicitly are pinned:
`test_trip_with_no_block_no_route_name_and_no_schedule_shows_nothing`
(no-label) and `test_trip_with_no_row_in_canonical_trips_is_reported_as_unmatched`
(missing trip row). Graceful degradation is pinned on both sides:
`test_a_pre_0035_database_still_records_every_finding` (calc),
`test_pre_migration_rows_serve_subject_context_as_null` (API), and
`renders a finding WITHOUT a subject exactly as it did before migration 0035`
(web, with axe).

#### 8. Deviations and open items (recorded, not silently absorbed)

1. **Trip headsign does not exist in Headway.** The handoff lists it as a
   resolvable label, but `canonical.trips` has no headsign column and the
   transform never maps one — `grep -r headsign` over the whole repo hits
   nothing outside this handoff. Adding it is a canonical-model change in
   `services/transform/` (explicitly out of this wave's scope). Absent
   renders as absent; nothing was invented. **Recommended next:** a
   `canonical.trips.trip_headsign` column + transform mapping, then one line
   in `subjects.py`.
2. **No onward link exists** for a block, route or trip. Design point 5 says
   "links onward where a link exists" — the app has no per-block, per-route
   or per-trip route, and `/map` takes no filter parameter. No link was
   fabricated. Recorded as the natural companion to a future
   `/map?route=` or `/trips/:id`.
3. **Blockless trips form ONE group.** 83 trips across 12 routes land in the
   single "No block in the schedule feed" bucket, which is correct (they have
   no block) but coarse. Sub-grouping them by route would be more actionable
   and would invent nothing — deliberately not built, because the handoff
   binds grouping to block and this deserves its own decision.
4. **`GET /dq/issues` returns the whole queue: 97,782 rows, ~900 MB, 18 s** —
   it freezes a browser tab. Measured: 86% of that payload is
   `source_record_ids`, 9% descriptions, and `subject_context` 0.2 MB
   (**0.0%**). Pre-existing and NOT this wave's regression, but it is now the
   binding constraint on `/dq` and the biggest backend follow-up. The
   deep-link path (`GET /dq/issues/{id}`, handoff 0026) is unaffected and is
   how the finding above was verified.
5. **Screenshot caveat, stated precisely.** To capture the browser evidence,
   the whole-queue list call (item 4) was stubbed to `[]` in the page. Every
   other call — including the deep-linked finding and its context — hit the
   real API against the real database. Chrome's screenshot capture also timed
   out repeatedly on this page after the 900 MB download crashed a renderer;
   three captures succeeded and are committed, and the live axe/keyboard
   results above were read out of the page programmatically.
6. **A `canonical.dr_trips` resolver** would extend the same treatment to the
   Demand Response findings. Their ids are already the agency's own dispatch
   identifiers, so the gain is route/time context, not vocabulary. Recorded.
7. **Two runs of 2026-07-22 are in the live queue** (one before the 0.4.0
   `_blocks` subjects were added, one after). Findings are deliberately not
   deduplicated (migration 0023) and DQ evidence is never deleted, so both
   stand; the later run is the one quoted here.

**Untouched, as scoped:** `services/ingestion/`, `services/transform/`,
`install/`, `deploy/`, `.github/`. **No commits** — the tree is left for the
orchestrator.

**Ops note (environment action, nothing in the repo):** the live API (host
uvicorn, `127.0.0.1:8000`, `--factory headway_api.app:create_app`) was
restarted once for the backend change. Its environment was captured from
`/proc/<pid>/environ` before the restart and restored byte-for-byte —
including `HEADWAY_SESSION_SECRET` — so, unlike the handoff-0025 restart, **no
live session was invalidated**. `HEADWAY_DATABASE_URL` (PG key-value form),
`HEADWAY_SIGNING_KEY`, `HEADWAY_CORS_ORIGINS=http://localhost:5173,http://localhost:4173`,
and the four `S3_*` vars were unchanged. Vite (localhost:5173) was not
restarted. The API is LEFT RUNNING.
