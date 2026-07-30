# Handoff: platform → transform+calc — Gap findings name the vehicle and route

## Context
First-agency UAT (ITS manager via project lead, 2026-07-29): telemetry-gap warnings
should show **what vehicle and route** they concern. Today's title:
*"Group excluded over telemetry gap of 731s: vehicle 07b5efcb-… trip f3a4a888-…"* — the
0029 principle (findings speak the agency's vocabulary) applied to the vrm/vrh finding
family.

**Verified against the agency's LIVE feed (orchestrator, 2026-07-29):** all 54 of their
GTFS-RT vehicles broadcast `VehicleDescriptor.label` — fleet numbers (`5335`, `5317`) —
the identifier dispatch actually uses. **The normalizer currently discards it**;
`canonical.vehicle_positions` has no label column. The data Tony wants is in his own
feed, dropped at ingestion. (MBTA also labels its fleet; the fix is general.)

Handoff 0029's machinery already covers the trip side: `telemetry_gap_excluded`
findings carry trip subject refs, resolved at persistence to block/route/span. This
wave adds the vehicle side and rewrites the titles.

## Design (binding)

1. **Transform captures the label.** Migration 0037: `canonical.vehicle_positions
   .vehicle_label TEXT` (nullable — a feed without labels stores NULL, never an
   invented name). The GTFS-RT normalizer maps `VehicleDescriptor.label` verbatim.
   Forward-only: no backfill in this wave (raw records are retained and replayable —
   record the backfill/replay option in Open Questions rather than building it).
2. **Calc findings lead with the human handle.** Gap-family titles become, in order of
   what a dispatcher scans for: route, vehicle, when — e.g. *"Route 42, vehicle 5335:
   12-minute telemetry silence (22:41–22:53 Jul 28)"* — falling back honestly when a
   part is unknown (`vehicle 07b5efcb…` shortened id when no label exists; no route
   when the trip is unresolvable). The calc stays pure: it formats from fields it is
   GIVEN (the group's vehicle_label travels with the input rows), never queries.
   Durations in minutes when ≥ 120 s (a dispatcher reads "12-minute", not "731s");
   the exact seconds stay in the description. UTC-vs-local: state times in UTC with
   the date, as the description already does — local-time display is the UI's job.
3. **Vehicle subject refs.** `Finding` subjects gain a `canonical.vehicle_positions`
   … no — the operational subject is the VEHICLE, not its position rows: add a
   lightweight vehicle reference (id + label if known) to the finding's subject
   context via the existing runner-resolution path, so the UI groups gap findings by
   route/vehicle exactly as 0029 groups missing trips by block.
4. **Full-family sweep.** Every finding whose title or description names a bare
   vehicle_id or trip UUID gets the treatment: vrm/vrh gap findings (0.2.0/0.3.0/
   0.4.0), layover findings, block-unavailable, pmt exclusions. Same review discipline
   as 0029: fix the cheap ones, record the rest.
5. **Honest scope:** no calc-math change, no threshold change; goldens updated for
   title text only; existing persisted findings are history and are not rewritten.

## Outputs
Migration 0037 applied live; transform normalizer + tests (label present, absent,
empty-string → NULL); calc title/format changes with goldens updated and the fallback
cases pinned; runner vehicle-label resolution + tests; a live re-run over the MBTA data
showing the new titles end to end (MBTA labels verify the general case); evidence
appended here. No commits — the orchestrator integrates.

**Sequencing note:** services/transform is owned by the running 0031 wave — this wave
STARTS ONLY after 0031 lands and is committed.

## Open Questions
- Backfill via raw replay so historical positions gain labels (the replay tooling
  exists — tools/canonical-replace precedent).
- Whether the live map should prefer vehicle_label on dots/popovers once canonical
  carries it (almost certainly yes — separate small web change, the map currently
  shows feed ids).

## Outputs — evidence

### Response — transform + calc (2026-07-30)

Contract accepted and shipped in full. One deviation is stated in §7 (pmt/apc
titles shorten the trip id rather than naming a route — the route is not in
those calcs' inputs), and one piece of unplanned but in-scope work was forced
by verification: **the live transform pipeline had been silently stalled
since 2026-07-22**, found and fixed here (§5), because the live re-run this
handoff demands was impossible over a stalled pipeline.

---

#### 1. Transform captures the label (design point 1)

Migration `db/migrations/0037_vehicle_position_label.sql`:
`canonical.vehicle_positions.vehicle_label TEXT`, nullable, comment carrying
the GTFS-RT spec pointer, no index (nothing filters on it), no backfill
(forward-only per the handoff; raw replay recorded in Open Questions).
Applied live via `db/migrate.py`:

```
applying 0037_vehicle_position_label.sql ... ok
applied 1 migration(s)
('vehicle_label', 'text', 'YES')          <- information_schema, live
labeled/total: (0, 15016508)              <- every pre-0037 row stays NULL
```

`normalize_gtfs_rt_positions` bumped **0.1.0 → 0.2.0**: maps
`VehicleDescriptor.label` verbatim; absent AND empty-string store NULL
(proto3 cannot distinguish unset from `""`, and `""` must never masquerade
as a name). The three cases the handoff names are pinned:
`test_vehicle_label_is_mapped_verbatim_when_present`,
`test_absent_vehicle_label_stores_none_never_a_guess`,
`test_empty_string_vehicle_label_normalizes_to_none`. Writer INSERT carries
the column; MBTA feed re-verified live before building (2026-07-30:
**555 of 555 entities labeled**, fleet numbers like `3114`).

#### 2. Calc titles lead with the human handle (design point 2)

New pure helper module `services/calc/headway_calc/_vocabulary.py`
(stdlib-only; the calc formats what it is GIVEN — `vehicle_label` and
`routes.short_name` now travel with every `VehiclePosition` via the reader's
existing LEFT JOINs). Every gap-family title is now *route, vehicle, when*:

- `telemetry_gap_excluded` (0.2.0 group path, 0.3.0 block path, 0.4.0
  trip-excision path): `"Route 42, vehicle 5335: 12-minute telemetry
  silence (22:41–22:53 Jul 28)"` — the largest gap is the headline.
- `layover_exceeds_max` (both versions): `"… : 33-minute layover not
  counted (22:42–23:15 Jul 28)"`.
- `block_unavailable`: `"… : no block in the schedule on Jul 28 (3 trip(s)
  counted per-trip)"`.

Honest fallbacks, each pinned by test: no label → shortened id (`vehicle
07b5efcb…`; fleet-style ids ≤16 chars stay whole, so `G-10099` never
truncates); unresolvable trip → no route at all (never a placeholder);
label arriving mid-period → latest broadcast wins, deterministically.
Durations ≥120 s render in minutes (rounded; the **exact seconds stay in
the description**, which also keeps the full vehicle/trip/block ids — the
provenance footnote). Times are UTC with the date, both sides dated across
midnight. No math, threshold or version changed in any calc; goldens
updated for title text only (`test_golden_v04`, `test_vrh_v03/v04`,
`test_runner` — assertions moved from title to description/subject).

Pre-0037 database safety: the position reader falls back to a label-free
SELECT on SQLSTATE 42703 (rollback + WARNING; labels honestly None) — a
vocabulary feature must never stop a calculation from reading its inputs.
Pinned: `test_pre_0037_database_falls_back_to_the_label_free_select`.

#### 3. Vehicle subject refs (design point 3)

`SubjectRef` gained `vehicle: VehicleRef | None` (id + label, no new
subject KIND — the ids still name `canonical.trips` and the closed-registry
test still binds kinds to resolvers). The existing persistence-time
resolution path (`headway_calc.subjects` → `dq.issues.subject_context`)
freezes it as an ADDITIVE key under context version 1:

```json
"vehicle": {"vehicle_id": "G-10010", "label": "3671-3870"}
```

No query is added (the label travelled with the calc's input rows), a
subject without a vehicle stores no key at all, and an unlabeled vehicle
stores `"label": null` — never a guess. The UI can now group gap findings
by route/vehicle exactly as 0029 groups missing trips by block (web change
itself is out of this wave's scope).

#### 4. Full-family sweep (design point 4)

Fixed: all three `telemetry_gap_excluded` paths, both `layover_exceeds_max`
paths, `block_unavailable` (titles + vehicle refs);
`pmt_invalid_trip_excluded`, `apc_null_count`, `apc_count_imbalance`,
`apc_negative_load` (bare trip UUIDs in titles now shortened; full ids stay
in description + subject — their calcs' inputs carry no route names, see
§7). Recorded, deliberately unchanged: 0.1.0 `telemetry_gap` (blocking,
retained for bit-for-bit historical recomputes); `dr_*` findings (already
the agency's own dispatch identifiers — 0029's position stands);
`coverage_below_threshold` and the other run-level findings (no rows to
name).

#### 5. The live pipeline was down, and the fix is part of this evidence

Verification before assertion cut both ways: the live re-run required live
data, and there was none — `canonical.vehicle_positions` stopped at
**2026-07-22 02:58 UTC** while ingestion kept producing. Root cause,
py-spy'd against the running container: a GTFS static feed is ONE Kafka
message and one DB transaction, and at MBTA scale (3.2M stop_times + a
lineage edge per entity) the writer's one-round-trip-per-row inserts made
one message outlast kafka-python's 5-minute `max_poll_interval` — the
consumer was expelled from the group mid-message, its offset commit failed,
the message redelivered, forever. Eight days of silent no-progress.

In-scope fixes (`services/transform/`):

- **`writer.py`: every multi-row method now issues one `executemany` per
  batch** (psycopg 3 pipelines it; semantics identical — same statement per
  parameter set, same ON CONFLICT behavior, empty batch executes nothing).
  A static message now lands in ~4–5 minutes instead of an hour+. Pinned:
  `test_multi_row_methods_issue_one_executemany_per_batch`.
- **`kafka_source.py`: `max_poll_interval_ms` raised to 30 min** and made a
  constructor input, sized to the largest single-message unit of work.
- **`Dockerfile`: the image could not boot at all** when rebuilt — two
  latent 0031-wave bugs found the first time anyone rebuilt: (a)
  `COPY --chmod=644` minted `/app` itself with mode 644 (non-traversable
  for the nonroot user; fixed with explicit `install -d -m 0755` first),
  and (b) `adapter-resolution.v0.schema.json` and
  `fleet-telematics.v0.schema.json` are opened at import but were never
  copied into the image. Both now in the COPY list.

After rebuild+restart the consumer held its group (zero heartbeat
expiries), committed offsets, and replayed the retained Kafka backlog with
the NEW normalizer — so the replayed days landed **with labels**. Kafka
retention had already discarded 2026-07-22→23 14:19 UTC; that gap is
permanent, is an ops fact of the outage (not of this change), and the
associated telemetry-gap findings will say so loudly. At time of writing
the watermark had advanced Jul 22 → Jul 25+ and was still catching up to
live (~3.5 feed-hours per minute); the container is LEFT RUNNING.

#### 6. The live re-run (design points 2+3 end to end, MBTA labels)

`python -m headway_calc.runner --period-start 2026-07-23 --period-end
2026-07-24` against the live compose TimescaleDB: **712,102 positions (all
label-bearing rows for the day; 962 distinct fleet labels)** → 1,746
findings routed; every one of the day's 1,436 `telemetry_gap_excluded`
findings carries a frozen subject context, **1,436/1,436 with a feed
label**, 814 leading with a route (the rest have no schedule-resolvable
trip and honestly omit it). Live rows, verbatim:

> **Route E, vehicle 3671-3870: 7-minute telemetry silence (19:03–19:10 Jul 23)**
> (issue `97f358d2-c35b-4743-b37f-ba5708927bc5`; context vehicle
> `{"vehicle_id": "G-10010", "label": "3671-3870"}`, block `B800-53`, route `E`)

> **Route D, vehicle 3805-3611: 13-minute telemetry silence (22:23–22:36 Jul 23)**
> (issue `122f2d3f-…`; vehicle_id `G-10014` preserved beneath the label)

> **Route D, vehicle G-10044: 179-minute layover not counted (13:04–16:03 Jul 21)**
> (pre-0037 rows: no label broadcast-time, so the id stands — the honest fallback, live)

> **Vehicle 3806-3620: no block in the schedule on Jul 23 (6 trip(s) counted per-trip)**

The description under each title still carries the exact seconds and full
ids, e.g. *"Group (vehicle_id='G-10001', trip_id='76510327') contains 1
telemetry gap(s) exceeding the gap threshold of 300s (largest 311s; …)"*.
A second live run over pre-0037 data (2026-07-21→22, 3,490 findings)
verified the whole fallback family: labels absent → `Vehicle G-10211: …`,
routes present where trips resolve (`Route SL2, vehicle y1311: …`),
`subject_context.vehicle.label` frozen as `null`. Existing persisted
findings were not rewritten; both runs added new rows only.

#### 7. Deviations and open items

1. **pmt/apc titles name a shortened trip id, not a route** — those calcs'
   inputs (passenger events, stop geometry) carry no route names, and the
   calc never queries. The frozen subject context DOES carry block/route
   for them. Feeding route names into the APC input types is recorded as
   the clean follow-up if UAT asks.
2. **Kafka had already discarded Jul 22 → Jul 23 14:19 UTC** before the
   stall was found; those positions are unrecoverable from the broker (raw
   records for them never landed). Permanent, stated here rather than
   papered over.
3. **The 0.1.0 `telemetry_gap` blocking finding keeps its old title** —
   that path is contractually frozen for historical recomputes.
4. **`vrm/vrh` remained blocked on 2026-07-23** (coverage below 0.95 over
   backlog-replayed data) and `upt/pmt` blocked on missing APC data —
   correct refusals, unchanged thresholds; the findings ARE the deliverable
   here and no math changed (all goldens pass untouched except title text).

#### 8. Test counts (every suite touched)

| Suite | Command | Result |
| --- | --- | --- |
| transform | `pytest -q` (services/transform) | **207 passed** (was 203; +3 label, +1 batching) |
| calc | `pytest -q` (services/calc) | **610 passed** (was 591; +18 `tests/test_vocabulary.py`, +1 reader fallback) |
| db static | `pytest -q test_migrations_static.py` | **30 passed** |

**Untouched, as scoped:** `services/ingestion/`, `services/mcp/`,
`services/api/`, `web/`, `install/`, `deploy/`, `.github/`. The live API
(8000) and Vite (5173) were not restarted. **No commits** — the tree is
left for the orchestrator. `git status` shows only:
`db/migrations/0037_*.sql`, `services/transform/*`, `services/calc/*`, and
this handoff.
