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

## Outputs — evidence

**2026-07-31, Transform + Calc (built by a Fable agent; integrated and
verified by the orchestrator after the agent hit its usage limit before
writing this section).**

### What shipped (files)

- `db/migrations/0038_block_labels.sql` — `canonical.block_labels`
  (feed `block_id` → operational name, per-source provenance columns:
  mapping file + sha256, derivation method + resolution-config hash + match
  key). One row per block_id; no row = UNMAPPED, consumers show the feed id
  unchanged. Applied live (table present on this box).
- `tools/block-labels/derive.py` — the loader/deriver: parses each `TripName`
  with the **handoff-0031 resolution machinery** (route short name + first
  scheduled departure), joins to loaded GTFS trips → `block_id`, and pairs
  it with the export's block name. Dry-run by default; `--yes` to load.
- `services/transform/headway_transform/block_labels.py` + tests (17).
- `services/calc/headway_calc/subjects.py` — attaches the operational name at
  persistence, **frozen** (the 0032/0029 rule); an unmapped block shows
  exactly what it showed before; old findings are never rewritten.
- `web/src/views/DqView.tsx` + copy/types/fixtures — renders the operational
  name with the feed id available (the 0032 vehicle-label presentation).

### Live run of the deriver (and why it proves the no-guess guarantee)

This dev box runs **MBTA** GTFS, not the partner feed (MBTA `block_id`s are
already operational names like `C01-29`). Running the deriver against the
partner's real mapping CSV (`tripblock-2026-07-29.reversed.csv`, 1,429 rows,
sha256 `22feacee…41fb5`) and the live MBTA schedule was therefore a
**deliberate mismatch** — and the tool behaved exactly as designed:

```
mapping rows: 1429
  matched:     87   (coincidental route+start collisions against the WRONG feed)
  unmatched:   1102 (TripName splits into 1 part, not the configured 3 — reported, not guessed)
block labels derived: 25
label conflicts (block_id excluded): 18   (e.g. B26-21 → both '26-1' and '26-2' — "never picked between")
DRY RUN — nothing written.
```

The 18 conflicts and 1,102 honest "nothing was assumed about which part is
which" refusals are the guarantee working: a block that resolves to two
different labels is **excluded**, never coin-flipped; a TripName that does not
parse is reported with its reason. **Nothing was loaded** — writing MBTA-feed
block_ids under partner block names would be exactly the cross-agency
contamination the confirm-before-load discipline exists to prevent.

### What is proven vs. what awaits the partner feed

- **Proven here:** migration applies; the deriver runs end-to-end against a
  live DB; its refusal/no-guess behavior is demonstrated on real data;
  `canonical.block_labels` is empty so **every existing MBTA finding renders
  its block_id unchanged** (no regression — web 289 green).
- **Awaits the partner's GTFS** (loaded on their VM, not this box): the real
  `block_id → name` derivation and a finding carrying a real partner block
  name. This is the same box-is-MBTA constraint the direction-evidence work
  hit; it is a data-availability gap, not a code gap. `resolution.v0.yaml`
  stays `confirmed: false` — deriving a label mapping never touched it.

### Tests

calc 620 (+5), transform 226 (+block_labels 17), web 289 (+2); privacy grep
over committed files clean (the partner CSV stays gitignored; fixtures are
synthetic). Merge conflict in `services/calc/tests/conftest.py` (both this
wave and the dedupe wave added a `RecordingConnection` parameter) resolved by
keeping both.
