# block-labels — name blocks the way your run board does

Some schedule feeds carry an opaque identifier in `block_id` while the
agency's dispatchers call the block something like `225-4`. Headway never
invents a name it does not have, so findings over such a feed can only show
the opaque id — unless the agency supplies the mapping. This tool loads it
(handoff 0038).

## Use the screen unless you have a reason not to

Headway has an **Admin → Block names** page that does exactly what this tool
does, from a browser: it checks the file and reports what would happen before
anything is written, then loads it. Same derivation, same refusals, same
provenance (file sha256 + parse-config hash) — the screen calls this repo's
`headway_transform.block_labels`, so the two doors cannot give different
answers.

This command-line tool remains for scripted or unattended loads, and for
anyone who would rather work in a shell.

## What it needs

1. **Your trip→block export**: a two-column CSV, `TripName,BlockName`, one
   row per trip (an optional `TripName,BlockName` header row is tolerated).
   This file is your data: keep it wherever you like — it is read in place
   and never enters the Headway repository.
2. **Your adapter's `resolution.v0.yaml`** (handoff 0031): the derivation
   reuses its *parse* rules, so a TripName comes apart here exactly as it
   does during trip resolution. The direction-confirmation gate in that
   file is not involved and is never changed — deriving a block name needs
   route + start time only.
3. **Your GTFS schedule already normalized** into `canonical.trips` /
   `canonical.routes` / `canonical.stop_times`.

## What it does

Each TripName is parsed (`route - pattern - start`) and matched against the
schedule on **(route short name, first scheduled departure)**. A row lands a
`block_id → BlockName` pair only when every scheduled trip sharing that key
carries the same feed block. Everything else is reported, never guessed:

- **ambiguous** — the key spans more than one feed block;
- **unmatched** — no scheduled trip has that route and start;
- **unparseable** — the trip name does not read as configured (or the row
  has no block name);
- **conflict** — two rows label the same feed block differently: that block
  is excluded and both labels are named.

True totals are always printed; sample lists are capped and say so.

The surviving pairs are upserted into `canonical.block_labels` with
provenance (source file + sha256, parse-config content hash, tool,
timestamp). Consumers (`headway_calc.subjects`) attach the label to new
findings **at persistence time, frozen** — so a reload refreshes future
findings and never rewrites history. An unmapped block renders exactly as it
did before this table existed; a feed whose `block_id` is already the
operational name (MBTA) simply needs no rows here.

## Running

```sh
export PGHOST=localhost PGPORT=5432 PGUSER=headway PGPASSWORD=... PGDATABASE=agency_db

# Dry run (default): derive, report counts, write nothing.
python tools/block-labels/derive.py \
    --csv /path/to/tripblock.csv \
    --resolution-spec adapters/tripspark/streets/resolution.v0.yaml

# Load.
python tools/block-labels/derive.py --csv ... --resolution-spec ... --yes
```

`DATABASE_URL` is honored if set (percent-encode credentials). Only
dependency on the execute path: psycopg (v3).

The derivation core lives in
`services/transform/headway_transform/block_labels.py` and is tested in
`services/transform/tests/test_block_labels.py` (synthetic fixtures — the
handoff-0016 twin discipline).

## Roadmap note

Refreshing this mapping currently means re-running the tool. Whether it
should instead ride the vendor-drop path (agency self-service refresh) is
recorded in `ROADMAP.md` (handoff 0038, open question).
