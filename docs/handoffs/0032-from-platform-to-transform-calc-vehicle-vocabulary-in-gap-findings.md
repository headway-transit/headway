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
(appended by the implementing agent)
