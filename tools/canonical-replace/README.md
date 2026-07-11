# canonical-replace

Deletes canonical rows **and their lineage edges together**, in one
transaction, with a `dq.issues` info row documenting the replacement.
Dry-run by default.

## Why this exists (the 2026-07-10 incident)

During the slice-2 UPT work, the simulated 2026-07-09
`canonical.passenger_events` rows had to be regenerated after a simulator
defect was fixed (handoff 0005, Verification Evidence, last bullet). The
first replacement deleted the canonical rows but not their lineage —
leaving ~92k `lineage.edges` rows keyed to canonical rows that no longer
existed. The stale edges had to be cleaned up manually by input record id.

A canonical row and its lineage edges are one unit of provenance
(ADR-0007: "explain this number" traverses edges from computed values back
to `raw.records`). Deleting one without the other silently corrupts the
lineage graph. This tool makes that mistake structurally impossible: edges
and rows go in the same transaction, or nothing goes.

## When to use it

Replacing **simulated or erroneous canonical data** that will be
re-normalized from the (still intact) raw records — e.g. regenerating a
service day of simulated passenger events, or re-loading positions after a
normalizer fix. The flow is:

1. Dry-run to see exactly what would be deleted.
2. Run with `--yes` to delete rows + edges in one transaction.
3. Re-run the normalizer / connector over the raw records to repopulate.

Replaceable tables (the full allowlist):

- `canonical.passenger_events`
- `canonical.vehicle_positions`
- `canonical.routes`
- `canonical.trips`

## What is deliberately out of scope

- **`raw.records` and `audit.events` — never.** Both are immutable at the
  database level (triggers reject UPDATE/DELETE), and this tool refuses
  them before even connecting. Raw records are the whole reason a
  replacement is safe: the inputs survive so canonical data can be rebuilt
  from them. An editable audit log is not an audit log.
- **`computed.metric_values` (and `cert.certifications`) — never deleted.**
  A wrong or outdated computed value is *superseded* by a new calc run
  writing a new versioned row; deleting computed history would erase the
  provenance of previously reported figures. Re-run the calc instead.
- **`dq.issues`** — resolved through the DQ workflow, not deleted.

Any table outside the allowlist is refused with an explanation.

## Usage

```sh
# Dry run (the default): counts only, no changes
python replace.py --table canonical.passenger_events \
    --where "service_date = %s" --param 2026-07-09

# Actually delete (edges first, then rows, one transaction)
python replace.py --table canonical.passenger_events \
    --where "service_date = %s" --param 2026-07-09 --yes

# Multiple placeholders: repeat --param in order
python replace.py --table canonical.vehicle_positions \
    --where "\"time\" >= %s AND \"time\" < %s" \
    --param 2026-07-09T00:00:00Z --param 2026-07-10T00:00:00Z
```

Connection comes from the environment, `db/migrate.py` style: `DATABASE_URL`
(credentials percent-encoded) or libpq `PGHOST`/`PGPORT`/`PGUSER`/
`PGPASSWORD`/`PGDATABASE`. Requires `psycopg` (v3) to execute; the core
logic takes any injected DB-API connection (tests run against a fake).

## How lineage edges are matched

The tool SELECTs the doomed rows' natural-key columns and rebuilds each
row's `lineage.edges.output_id` **through the normalizers' own code**
(`services/transform/headway_transform` is imported; the dataclass
`output_id` properties and `OUTPUT_KIND` constants are reused, never
duplicated). Edges are then deleted by `(output_kind, output_id)` in
batches. Tests pin the builders against real normalizer output from tiny
fixtures, so format drift fails the suite before it can orphan edges.

### The edgeless guard

If rows match but **zero** edges are found for their reconstructed
output_ids, the tool refuses: every canonical row is written with exactly
one lineage edge, so zero edges almost certainly means format drift between
this tool and the normalizer — deleting anyway would recreate the
2026-07-10 incident. `--allow-edgeless` overrides the refusal (with a loud
warning) for the rare case where rows genuinely have no edges.

## Provenance of the deletion itself

Every executed replacement writes one `dq.issues` row
(`issue_type=canonical_replacement`, severity `info`) in the same
transaction, recording the table, WHERE clause and parameters, row and edge
counts, and the distinct `source_record_id`s of the deleted rows (where the
table carries them) — so the deletion is as explainable as the data was.

## Tests

```sh
cd tools/canonical-replace && python3 -m pytest tests/ -q
```
