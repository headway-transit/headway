#!/usr/bin/env python3
"""Derive and load an agency's block-label mapping (handoff 0038).

What this does, in the agency's terms: your schedule feed may carry an
opaque identifier in ``block_id`` while your dispatchers call the block
something like ``225-4``. Given your trip->block export (a two-column
``TripName,BlockName`` CSV), this tool joins each TripName to your loaded
GTFS schedule using the SAME trip-name parse your trip-resolution
configuration declares (handoff 0031 — nothing reimplemented, nothing
guessed), lands ``feed block_id -> operational block name`` pairs, and
loads them into ``canonical.block_labels`` with full provenance. Findings
raised AFTER the load name blocks the way your run board does; findings
raised before are history and are never rewritten.

Honesty rules (all enforced in headway_transform.block_labels):
- match / ambiguous / unmatched / unparseable are counted and reported per
  row; nothing unresolved is guessed into the mapping;
- a feed block two rows label differently is EXCLUDED and reported;
- dry run by default — nothing is written without --yes.

The mapping file itself is agency data: it stays wherever you keep it and
never enters the Headway repository.

Connection (db/migrate.py style):
- DATABASE_URL, if set, is passed to psycopg unchanged (percent-encode
  credentials);
- otherwise libpq-style PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE are
  passed as psycopg keyword arguments.

Usage:
    python derive.py --csv /path/to/tripblock.csv \\
        --resolution-spec adapters/tripspark/streets/resolution.v0.yaml   # dry run
    python derive.py --csv ... --resolution-spec ... --yes                # load

Only dependency (execute path): psycopg (v3). The derivation core takes any
DB-API connection and is tested in services/transform/tests.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Import the transform package from the repo checkout so the trip-name parse
# comes from the resolver itself, never a duplicated implementation
# (the tools/canonical-replace precedent).
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "services" / "transform"))

from headway_transform.adapters.resolution import (  # noqa: E402
    load_resolution_spec,
)
from headway_transform.block_labels import (  # noqa: E402
    derive_block_labels,
    load_block_labels,
    load_scheduled_trips,
    read_mapping_csv,
)

TOOL_NAME = "tools/block-labels/derive.py"


def connect():
    import psycopg

    url = os.environ.get("DATABASE_URL")
    if url:
        return psycopg.connect(url)
    kwargs = {}
    for env, key in (
        ("PGHOST", "host"),
        ("PGPORT", "port"),
        ("PGUSER", "user"),
        ("PGPASSWORD", "password"),
        ("PGDATABASE", "dbname"),
    ):
        value = os.environ.get(env)
        if value:
            kwargs[key] = value
    return psycopg.connect(**kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Derive feed block_id -> operational block name from an "
            "agency trip->block export and load canonical.block_labels."
        )
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="The agency's TripName,BlockName mapping file (never committed).",
    )
    parser.add_argument(
        "--resolution-spec",
        required=True,
        help=(
            "The adapter's resolution.v0.yaml whose PARSE rules the "
            "derivation reuses (handoff 0031). Its direction-confirmation "
            "gate is not read and is never changed."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually load the mapping. Without it: dry run, nothing written.",
    )
    args = parser.parse_args(argv)

    spec = load_resolution_spec(args.resolution_spec)
    rows, sha256 = read_mapping_csv(args.csv)
    print(f"mapping file: {args.csv}")
    print(f"  sha256: {sha256}")
    print(f"  rows: {len(rows)}")
    print(f"parse rules: {args.resolution_spec} (config {spec.spec_sha12})")

    conn = connect()
    try:
        trips = load_scheduled_trips(conn)
        print(f"scheduled trips loaded: {len(trips)}")
        result = derive_block_labels(spec, rows, trips)
        for line in result.summary_lines():
            print(line)

        if not args.yes:
            print("\nDRY RUN — nothing written. Re-run with --yes to load.")
            return 0

        source = f"{Path(args.csv).name} sha256={sha256}"
        derivation = (
            f"{TOOL_NAME}: TripName parsed per "
            f"{Path(args.resolution_spec).name} (config {spec.spec_sha12}), "
            "matched on (route_short_name, first scheduled departure) "
            "against canonical.trips; only rows whose every candidate trip "
            "shares one feed block_id landed; ambiguous/unmatched/"
            "conflicting rows reported, never guessed (handoff 0038)."
        )
        written = load_block_labels(
            conn,
            result,
            source=source,
            derivation=derivation,
            loaded_by=TOOL_NAME,
        )
        conn.commit()
        print(f"\nLOADED: {written} block label(s) upserted into "
              "canonical.block_labels.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
