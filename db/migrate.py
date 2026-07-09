#!/usr/bin/env python3
"""Minimal migration runner for Headway.

Applies db/migrations/NNNN_*.sql in filename order, tracking applied files
in public.schema_migrations. Each migration runs in its own transaction; any
failure aborts loudly with a nonzero exit.

Connection (see db/README.md):
- DATABASE_URL, if set, is passed to psycopg unchanged — credentials in it
  must be percent-encoded (2026-07-09 live-run finding: a password containing
  '@' or other reserved characters breaks URL parsing).
- Otherwise, libpq-style PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE are
  passed as psycopg keyword arguments — no URL is ever built, so special
  characters in credentials need no encoding.

Only dependency: psycopg (v3). No ORM, no framework.
"""

import os
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def fail(message: str) -> "None":
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def connect_kwargs() -> dict:
    """Connection parameters from the environment.

    DATABASE_URL wins if set (must be percent-encoded; see module docstring).
    Otherwise build psycopg keyword args from libpq-style PG* variables —
    values are passed verbatim, never embedded in a URL.
    """
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
        fail(
            "no connection configured: set DATABASE_URL (percent-encode "
            "credentials), or set PGHOST and PGDATABASE (plus PGPORT/"
            "PGUSER/PGPASSWORD as needed)"
        )
    return kwargs


def main() -> None:
    try:
        import psycopg
    except ImportError:
        fail("psycopg (v3) is required: pip install 'psycopg[binary]'")

    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        fail(f"no .sql files found in {MIGRATIONS_DIR}")

    with psycopg.connect(**connect_kwargs()) as conn:
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
