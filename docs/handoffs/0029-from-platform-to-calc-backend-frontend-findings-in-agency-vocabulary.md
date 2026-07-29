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
