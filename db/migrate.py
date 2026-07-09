#!/usr/bin/env python3
"""Minimal migration runner for Headway.

Applies db/migrations/NNNN_*.sql in filename order against DATABASE_URL,
tracking applied files in public.schema_migrations. Each migration runs in
its own transaction; any failure aborts loudly with a nonzero exit.

Only dependency: psycopg (v3). No ORM, no framework.
"""

import os
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def fail(message: str) -> "None":
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    try:
        import psycopg
    except ImportError:
        fail("psycopg (v3) is required: pip install 'psycopg[binary]'")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        fail("DATABASE_URL environment variable is not set")

    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        fail(f"no .sql files found in {MIGRATIONS_DIR}")

    with psycopg.connect(database_url) as conn:
        with conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS public.schema_migrations (
                    filename   TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

        applied = {
            row[0]
            for row in conn.execute(
                "SELECT filename FROM public.schema_migrations"
            ).fetchall()
        }

        pending = [m for m in migrations if m.name not in applied]
        if not pending:
            print(f"up to date: {len(applied)} migration(s) already applied")
            return

        for migration in pending:
            print(f"applying {migration.name} ... ", end="", flush=True)
            sql = migration.read_text(encoding="utf-8")
            try:
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO public.schema_migrations (filename) VALUES (%s)",
                        (migration.name,),
                    )
            except psycopg.Error as exc:
                print("FAILED")
                fail(f"{migration.name}: {exc}")
            print("ok")

        print(f"applied {len(pending)} migration(s)")


if __name__ == "__main__":
    main()
