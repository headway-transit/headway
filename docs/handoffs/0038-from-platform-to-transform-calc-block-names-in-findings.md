# Handoff: platform → transform+calc — Block names in findings (the agency's own words, part 2)

## Context

Handoff 0032 put vehicles and routes into findings in agency vocabulary; blocks are
the missing third. `headway_calc/subjects.py` names the gap in its own comments: *"No
agency block-label mapping (feed `block_id` → operational name like `225-4`). The
partner agency's feed carries opaque UUIDs in `block_id`."* An ops person reading
"block `8f3a…`" cannot act on it; "block 3-2" is the word on their run board.

The agency has now supplied the mapping source: a trip→block export
(`docs/reference/vendor/tripblock-2026-07-29.reversed.csv`, **gitignored agency
data, never committed**) — 1,428 rows of `TripName,BlockName` (e.g.
`"3 - 3S - 08:45","3-2"`), already Excel-reversal-corrected and cross-checked
**824/824** against the agency's separate block export during the direction-evidence
derivation. TripName is the same `route - pattern - start` key the 0031 trip
resolution already parses, so TripName→GTFS trip→`block_id` gives the
`block_id → BlockName` mapping the code comment asks for.

## Design (binding)

1. **An agency-local block-label mapping, as reference data.** Additive migration: a
   table mapping feed `block_id` → operational block name (per source/agency,
   provenance columns: where the mapping came from, loaded when, by what). Loaded by
   a tool/loader from a mapping file — the vendor CSV itself never enters the repo;
   committed fixtures are synthetic (the 0016 synthetic-twin discipline; run the
   privacy greps).
2. **Derivation uses the 0031 resolution machinery, not a reimplementation.** Parse
   TripName exactly as the resolver does; resolve against the agency's GTFS
   (route_short_name + first departure; direction is NOT needed to land a
   trip→block_id join when route+start is already unique — record match/ambiguous/
   unmatched counts honestly). Rows that don't resolve are reported, not guessed.
   Note: `resolution.v0.yaml` remains `confirmed: false` for APC resolution — that
   gate is about passenger-count assignment; deriving a block-name mapping does not
   require flipping it, and this handoff must not flip it.
3. **Names attach at persistence, frozen** (0032 rule): finding contexts that today
   group by block gain the operational name when the mapping knows it. **No label is
   ever invented** — an unmapped block shows exactly what it shows today. Old
   findings are not rewritten.
4. **Web**: wherever findings render block ids (grouped-by-block tables from 0029,
   0032 surfaces), show the operational name with the id available (tooltip/detail —
   follow the 0032 vehicle-label presentation).
5. **Live proof on this box**: load the real CSV via the loader against the agency's
   GTFS (already ingested from their published feed), report the resolved mapping
   count, and show one finding context (or a staged one) carrying a real block name.
   MBTA findings are unaffected (their `block_id` is already the operational vocab —
   the mapping table simply has no rows for them; prove nothing regresses:
   calc + transform + api + web suites green).

## Outputs

Migration + loader/tool + resolver-reuse derivation + calc persistence change + web
rendering + synthetic fixtures + tests at every layer; privacy greps clean; live
derivation counts and screenshots/JSON in evidence appended here. No commits — the
orchestrator integrates.

## Open Questions

- Whether the mapping should eventually ride the vendor-drop path (agency
  self-service refresh) rather than a load tool — ROADMAP note.
- Whether ambiguous TripName→trip matches (same route+start on two services) should
  consult the row's service date the way full resolution does — do it if cheap, else
  record the count and leave them unmapped.
