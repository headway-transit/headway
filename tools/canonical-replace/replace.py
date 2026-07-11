#!/usr/bin/env python3
"""Canonical-replacement tool: delete canonical rows AND their lineage edges together.

Motivation (2026-07-10 incident, handoff 0005 Verification Evidence, last
bullet): replacing the simulated 2026-07-09 canonical.passenger_events rows
deleted the rows but left ~92k lineage.edges rows keyed to canonical rows
that no longer existed — stale edges that had to be cleaned up manually by
input record id. A canonical row and its lineage edges are one unit of
provenance; this tool deletes them in one transaction so neither can be
orphaned.

Scope (deliberately narrow):
- ONLY the replaceable canonical tables in ALLOWLIST may be targeted.
- raw.records and audit.events are IMMUTABLE and are never touched — the
  whole point of a replacement is that the raw inputs survive so the data
  can be re-normalized.
- computed.metric_values (and cert.certifications) are never deleted:
  computed values are superseded by new calc runs writing new versioned
  rows, not by deleting history.

Lineage output_id reconstruction: each normalizer in
services/transform/headway_transform writes lineage.edges.output_id in a
table-specific natural-key format. This tool imports the transform package
and rebuilds each doomed row's output_id through the normalizers' OWN
dataclass ``output_id`` properties (no duplicated format strings), then
deletes edges by (output_kind, output_id). If rows match but ZERO edges are
found, the tool refuses (likely format drift between this tool and the
normalizers) unless --allow-edgeless is passed — fail loudly, never
silently orphan.

Connection (db/migrate.py style):
- DATABASE_URL, if set, is passed to psycopg unchanged (percent-encode
  credentials — 2026-07-09 live-run finding).
- Otherwise libpq-style PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE are
  passed as psycopg keyword arguments.

Usage:
    python replace.py --table canonical.passenger_events \\
        --where "service_date = %s" --param 2026-07-09            # dry run
    python replace.py --table canonical.passenger_events \\
        --where "service_date = %s" --param 2026-07-09 --yes      # execute

Only dependency (execute path): psycopg (v3). Core logic takes any DB-API
connection so tests inject fakes; this tool is never pointed at raw.records.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

# Import the transform package from the repo checkout so output_id formats
# come from the normalizers themselves, never a duplicated format string.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "services" / "transform"))

from headway_transform import (  # noqa: E402
    gtfs_rt_positions,
    gtfs_static,
    tides_passenger_events,
)
from headway_transform.writer import INSERT_DQ_ISSUE_SQL  # noqa: E402

TOOL_NAME = "canonical-replace"

# Edge deletes/counts run in batches of this many output_ids per statement.
BATCH_SIZE = 1000

# Placeholder values for non-key dataclass fields. Only the natural-key
# fields participate in output_id (pinned by tests/test_output_id_builders.py
# against the normalizers' real output); the placeholders are never rendered.
_PLACEHOLDER_DATE = date(1970, 1, 1)


def _passenger_event_output_id(
    passenger_event_id: str, event_timestamp: datetime, source_record_id: str
) -> str:
    """output_id exactly as normalize_tides_passenger_events wrote it."""
    return tides_passenger_events.CanonicalPassengerEvent(
        event_timestamp=event_timestamp,
        service_date=_PLACEHOLDER_DATE,
        passenger_event_id=passenger_event_id,
        vehicle_id="",
        trip_id=None,
        trip_stop_sequence=None,
        event_type="",
        event_count=None,
        source="",
        source_record_id=source_record_id,
    ).output_id


def _vehicle_position_output_id(
    vehicle_id: str, time: datetime, source_record_id: str
) -> str:
    """output_id exactly as normalize_gtfs_rt_positions wrote it."""
    return gtfs_rt_positions.CanonicalVehiclePosition(
        time=time,
        vehicle_id=vehicle_id,
        trip_id=None,
        route_id=None,
        latitude=0.0,
        longitude=0.0,
        bearing=None,
        speed_mps=None,
        odometer_m=None,
        source_record_id=source_record_id,
    ).output_id


def _route_output_id(route_id: str) -> str:
    """output_id exactly as normalize_gtfs_static wrote it (the route_id)."""
    return route_id


def _trip_output_id(trip_id: str) -> str:
    """output_id exactly as normalize_gtfs_static wrote it (the trip_id)."""
    return trip_id


@dataclass(frozen=True)
class TableSpec:
    """How to rebuild one replaceable table's lineage output_ids."""

    table: str
    output_kind: str  # lineage.edges.output_kind the normalizer writes
    key_columns: tuple[str, ...]  # SELECTed to rebuild output_id, in order
    build_output_id: Callable[..., str]  # (*key column values) -> output_id
    source_record_id_index: int | None  # index into key_columns, for dq row


# The ONLY tables this tool may replace. output_kind constants come from the
# normalizers, so a renamed kind breaks here loudly instead of drifting.
ALLOWLIST: dict[str, TableSpec] = {
    "canonical.passenger_events": TableSpec(
        table="canonical.passenger_events",
        output_kind=tides_passenger_events.OUTPUT_KIND,
        key_columns=("passenger_event_id", "event_timestamp", "source_record_id"),
        build_output_id=_passenger_event_output_id,
        source_record_id_index=2,
    ),
    "canonical.vehicle_positions": TableSpec(
        table="canonical.vehicle_positions",
        output_kind=gtfs_rt_positions.OUTPUT_KIND,
        key_columns=("vehicle_id", '"time"', "source_record_id"),
        build_output_id=_vehicle_position_output_id,
        source_record_id_index=2,
    ),
    "canonical.routes": TableSpec(
        table="canonical.routes",
        output_kind=gtfs_static.ROUTES_OUTPUT_KIND,
        key_columns=("route_id",),
        build_output_id=_route_output_id,
        source_record_id_index=None,
    ),
    "canonical.trips": TableSpec(
        table="canonical.trips",
        output_kind=gtfs_static.TRIPS_OUTPUT_KIND,
        key_columns=("trip_id",),
        build_output_id=_trip_output_id,
        source_record_id_index=None,
    ),
}

# Plain-language refusals for protected data, keyed by schema prefix.
_PROTECTED_PREFIXES: dict[str, str] = {
    "raw.": (
        "raw.records is the immutable registry of ingested raw data — the "
        "database itself rejects UPDATE and DELETE on it, and this tool "
        "never touches it. Raw records are the whole reason a replacement "
        "is safe: the inputs survive so canonical data can be re-normalized "
        "from them."
    ),
    "audit.": (
        "audit.events is the append-only audit log — the database rejects "
        "UPDATE and DELETE on it, and this tool never touches it. An audit "
        "trail that can be edited is not an audit trail."
    ),
    "computed.": (
        "computed values are never deleted: a wrong or outdated figure is "
        "superseded by a new calc run writing a new versioned "
        "computed.metric_values row. Deleting computed history would erase "
        "the provenance of previously reported numbers. Re-run the calc "
        "instead."
    ),
    "cert.": (
        "certifications are a permanent record of who attested to what and "
        "when. They are never deleted; a certification of superseded data "
        "is handled through the certification workflow, not by deleting "
        "rows."
    ),
    "dq.": (
        "dq.issues rows are resolved through the DQ workflow (status/"
        "resolution fields), not deleted."
    ),
}


def refusal_message(table: str) -> str:
    """Plain-language explanation of why a table cannot be replaced."""
    for prefix, why in _PROTECTED_PREFIXES.items():
        if table == prefix.rstrip(".") or table.startswith(prefix):
            return f"REFUSED: cannot replace {table}. {why}"
    allowed = ", ".join(sorted(ALLOWLIST))
    return (
        f"REFUSED: {table} is not a replaceable table. This tool only "
        f"replaces canonical data it knows how to reconstruct lineage for: "
        f"{allowed}."
    )


def _batches(items: Sequence[str], size: int) -> list[Sequence[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


COUNT_EDGES_SQL = (
    "SELECT count(*) FROM lineage.edges "
    "WHERE output_kind = %s AND output_id = ANY(%s)"
).strip()

DELETE_EDGES_SQL = (
    "DELETE FROM lineage.edges "
    "WHERE output_kind = %s AND output_id = ANY(%s)"
).strip()


def _count_edges(cursor: Any, output_kind: str, output_ids: list[str], batch_size: int) -> int:
    total = 0
    for batch in _batches(output_ids, batch_size):
        cursor.execute(COUNT_EDGES_SQL, (output_kind, list(batch)))
        total += cursor.fetchone()[0]
    return total


def _delete_edges(cursor: Any, output_kind: str, output_ids: list[str], batch_size: int) -> int:
    total = 0
    for batch in _batches(output_ids, batch_size):
        cursor.execute(DELETE_EDGES_SQL, (output_kind, list(batch)))
        total += cursor.rowcount
    return total


def run(
    conn: Any,
    *,
    table: str,
    where: str,
    params: Sequence[Any],
    execute: bool = False,
    allow_edgeless: bool = False,
    actor: str | None = None,
    batch_size: int = BATCH_SIZE,
    out: Callable[[str], None] = print,
) -> int:
    """Perform (or dry-run) one canonical replacement. Returns an exit code.

    conn is any DB-API 2.0 connection (psycopg in production, a fake in
    tests). Nothing is committed unless execute=True and every step
    succeeds; any failure rolls back so rows and edges can never diverge.
    """
    spec = ALLOWLIST.get(table)
    if spec is None:
        out(refusal_message(table))
        return 2

    params = list(params)
    cursor = conn.cursor()
    try:
        # (b) SELECT the doomed rows first and rebuild each row's lineage
        # output_id exactly as its normalizer wrote it.
        select_sql = (
            f"SELECT {', '.join(spec.key_columns)} FROM {spec.table} "
            f"WHERE {where}"
        )
        cursor.execute(select_sql, params)
        key_rows = cursor.fetchall()
        row_count = len(key_rows)

        output_ids = [spec.build_output_id(*row) for row in key_rows]
        edge_count = _count_edges(cursor, spec.output_kind, output_ids, batch_size)

        out(f"table: {spec.table} (lineage output_kind: {spec.output_kind})")
        out(f"where: {where}  params: {params}")
        out(f"rows matching: {row_count}")
        out(f"lineage edges matching reconstructed output_ids: {edge_count}")

        if row_count == 0:
            out("Nothing to do: no rows match. No changes made.")
            return 0

        edgeless = edge_count == 0
        if edgeless:
            out(
                "WARNING: rows match but ZERO lineage edges were found for "
                "their reconstructed output_ids. Every canonical row is "
                "written with exactly one lineage edge, so this strongly "
                "suggests FORMAT DRIFT between this tool's output_id "
                "builders and the normalizer that wrote these rows "
                "(services/transform/headway_transform). Deleting anyway "
                "would orphan the rows' real edges — the 2026-07-10 stale-"
                "lineage incident, again."
            )

        if not execute:
            out(
                f"DRY RUN — no changes made. Re-run with --yes to delete "
                f"{row_count} row(s) and {edge_count} lineage edge(s)."
            )
            return 0

        # (e) Refuse to orphan lineage unless explicitly overridden.
        if edgeless and not allow_edgeless:
            out(
                "REFUSED: not deleting. Fix the output_id builder (or the "
                "drift) first, or re-run with --allow-edgeless if these "
                "rows genuinely have no edges. Failing loudly beats "
                "silently orphaning lineage."
            )
            return 2
        if edgeless and allow_edgeless:
            out(
                "WARNING: proceeding WITHOUT lineage edges because "
                "--allow-edgeless was given. If edges for these rows exist "
                "under a different output_id format they are now orphaned "
                "and must be cleaned up by input record id."
            )

        # (d) One transaction: edges first, then the canonical rows, then
        # the dq.issues provenance row; commit only if all succeed.
        edges_deleted = _delete_edges(
            cursor, spec.output_kind, output_ids, batch_size
        )

        cursor.execute(f"DELETE FROM {spec.table} WHERE {where}", params)
        rows_deleted = cursor.rowcount

        # (f) Provenance of the deletion itself: one dq.issues info row.
        source_record_ids: list[str] = []
        if spec.source_record_id_index is not None:
            source_record_ids = sorted(
                {row[spec.source_record_id_index] for row in key_rows}
            )
        description = (
            f"Canonical replacement performed by tools/{TOOL_NAME}"
            + (f" (actor: {actor})" if actor else "")
            + f": deleted {rows_deleted} row(s) from {spec.table} matching "
            f"WHERE {where} with params {params}, together with "
            f"{edges_deleted} lineage.edges row(s) "
            f"(output_kind={spec.output_kind}), in one transaction. "
            f"Pre-delete counts: {row_count} row(s), {edge_count} edge(s)"
            + ("; --allow-edgeless was given" if edgeless else "")
            + ". raw.records and audit.events were not touched; the raw "
            "inputs remain available for re-normalization."
        )
        cursor.execute(
            INSERT_DQ_ISSUE_SQL,
            (
                "canonical_replacement",
                "info",
                f"Canonical replacement: {rows_deleted} row(s) deleted "
                f"from {spec.table}",
                description,
                source_record_ids,
            ),
        )

        conn.commit()
        out(f"deleted {edges_deleted} lineage edge(s)")
        out(f"deleted {rows_deleted} row(s) from {spec.table}")
        out("dq.issues info row written (issue_type=canonical_replacement)")
        return 0
    except BaseException:
        conn.rollback()
        raise
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            close()


def connect_kwargs() -> dict:
    """Connection parameters from the environment (db/migrate.py style)."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return {"conninfo": database_url}

    kwargs = {
        keyword: os.environ[env_var]
        for keyword, env_var in (
            ("host", "PGHOST"),
            ("port", "PGPORT"),
            ("user", "PGUSER"),
            ("password", "PGPASSWORD"),
            ("dbname", "PGDATABASE"),
        )
        if os.environ.get(env_var)
    }
    if "host" not in kwargs or "dbname" not in kwargs:
        print(
            "ERROR: no connection configured: set DATABASE_URL "
            "(percent-encode credentials), or set PGHOST and PGDATABASE "
            "(plus PGPORT/PGUSER/PGPASSWORD as needed)",
            file=sys.stderr,
        )
        sys.exit(1)
    return kwargs


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Replace canonical data safely: delete matching canonical rows "
            "AND their lineage.edges together, in one transaction, with a "
            "dq.issues info row documenting the replacement. Dry-run by "
            "default."
        ),
    )
    parser.add_argument(
        "--table",
        required=True,
        help=f"target table; one of: {', '.join(sorted(ALLOWLIST))}",
    )
    parser.add_argument(
        "--where",
        required=True,
        help="SQL WHERE clause with %%s placeholders, e.g. 'service_date = %%s'",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="value for one %%s placeholder (repeatable, in order)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be deleted and exit (the default behavior)",
    )
    mode.add_argument(
        "--yes",
        action="store_true",
        help="actually delete (edges then rows, one transaction)",
    )
    parser.add_argument(
        "--allow-edgeless",
        action="store_true",
        help=(
            "override the refusal when rows match but zero lineage edges "
            "are found (zero edges usually means format drift between this "
            "tool and the normalizer — investigate first)"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    # Refuse before ever connecting: a disallowed table needs no database.
    if args.table not in ALLOWLIST:
        print(refusal_message(args.table))
        sys.exit(2)

    try:
        import psycopg
    except ImportError:
        print(
            "ERROR: psycopg (v3) is required: pip install 'psycopg[binary]'",
            file=sys.stderr,
        )
        sys.exit(1)

    actor = os.environ.get("USER") or os.environ.get("USERNAME")
    with psycopg.connect(**connect_kwargs()) as conn:
        code = run(
            conn,
            table=args.table,
            where=args.where,
            params=args.param,
            execute=args.yes,
            allow_edgeless=args.allow_edgeless,
            actor=actor,
        )
    sys.exit(code)


if __name__ == "__main__":
    main()
