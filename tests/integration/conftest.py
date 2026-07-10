"""Fixtures for the real-PostgreSQL integration suite (ADR-0010 tests/ layout).

Why this suite exists — the 2026-07-10 autocommit bug: the API returned 201
for a certification while cert.certifications stayed EMPTY, because the
lifespan opened its psycopg3 connection with the default autocommit=False and
every router ``with db.transaction():`` block nested as a SAVEPOINT inside a
never-committed implicit transaction. Unit tests with a fake connection
cannot catch that class of bug; only a real database observed from a SEPARATE
connection (the psql-equivalent, which is what caught it live) can. See
services/api/headway_api/db.py and
services/api/tests/test_transaction_discipline.py.

Contract of this suite:

- HEADWAY_IT_ADMIN_URL must point at a superuser/owner connection on a
  THROWAWAY PostgreSQL (+TimescaleDB) server — never production. When it is
  unset the whole suite SKIPS, so unit CI stays green without a database.
- The suite creates its own scratch database (headway_it_<random>), applies
  every db/migrations/*.sql through db/migrate.py, runs, and DROPs the
  scratch database WITH (FORCE) even on failure. The server's existing
  databases are never touched.
- The app under test is built by the production factory and lifespan
  (HEADWAY_DATABASE_URL -> psycopg.connect in headway_api.db.lifespan); the
  database connection semantics exercised are the REAL ones, not a fake.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

ADMIN_URL_ENV = "HEADWAY_IT_ADMIN_URL"
SKIP_REASON = (
    f"{ADMIN_URL_ENV} is not set. The real-PostgreSQL integration suite "
    "needs a superuser/owner connection to a THROWAWAY server (it creates "
    "and drops its own scratch database). See tests/integration/README.md."
)

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "services" / "api"
MIGRATE_PY = REPO_ROOT / "db" / "migrate.py"
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

# CI installs services/api as a package; for ad-hoc local runs make
# headway_api importable straight from the repo (same pattern as
# services/api/tests/conftest.py).
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

TEST_SESSION_SECRET = "integration-test-only-session-secret"


def admin_url_or_skip() -> str:
    url = os.environ.get(ADMIN_URL_ENV, "").strip()
    if not url:
        pytest.skip(SKIP_REASON)
    return url


@pytest.fixture(scope="session")
def scratch_db_conninfo():
    """Create a scratch database on the admin server; drop it afterwards.

    Yields a libpq conninfo string for the scratch database. The conninfo is
    built with psycopg.conninfo.make_conninfo (key=value form), so credentials
    never pass through URL parsing — no percent-encoding trap (db/README.md,
    2026-07-09 live-run finding).
    """
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    admin_url = admin_url_or_skip()
    params = conninfo_to_dict(admin_url)
    dbname = f"headway_it_{secrets.token_hex(4)}"

    admin = psycopg.connect(make_conninfo(**params), autocommit=True)
    try:
        admin.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname))
        )
        try:
            yield make_conninfo(**{**params, "dbname": dbname})
        finally:
            # WITH (FORCE): kick any connection the app or a failed test left
            # open, so teardown never strands a scratch database.
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(dbname)
                )
            )
    finally:
        admin.close()


@pytest.fixture(scope="session")
def migrated_db(scratch_db_conninfo):
    """Apply ALL db/migrations/*.sql to the scratch db via db/migrate.py.

    migrate.py is invoked as a subprocess with DATABASE_URL set to the
    scratch conninfo (migrate.py passes it to psycopg unchanged, and a
    key=value conninfo string is valid libpq conninfo) — the exact machinery
    an operator runs, not a re-implementation.
    """
    import psycopg

    env = {**os.environ, "DATABASE_URL": scratch_db_conninfo}
    result = subprocess.run(
        [sys.executable, str(MIGRATE_PY)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"db/migrate.py failed against the scratch database:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # Glob, don't hardcode the count: new migrations must be picked up.
    expected = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    with psycopg.connect(scratch_db_conninfo, autocommit=True) as conn:
        applied = sorted(
            row[0]
            for row in conn.execute(
                "SELECT filename FROM public.schema_migrations"
            ).fetchall()
        )
    assert applied == expected, (
        f"migrate.py did not apply every db/migrations/*.sql file: "
        f"expected {expected}, applied {applied}"
    )
    return scratch_db_conninfo


@pytest.fixture()
def observer(migrated_db):
    """A SEPARATE psycopg connection to the scratch database.

    This is the psql-equivalent outside the app's own connection — the
    vantage point that caught the 2026-07-10 bug. Every test asserts
    persisted state through THIS connection, never through the app's.
    autocommit=True so each statement is its own transaction and reads always
    see the latest committed state.
    """
    import psycopg

    conn = psycopg.connect(migrated_db, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def api_client(migrated_db, monkeypatch):
    """The API booted through the PRODUCTION path.

    create_app() with no injected db + TestClient's context manager runs the
    real lifespan, which opens a real psycopg connection from
    HEADWAY_DATABASE_URL (autocommit=True — the fix under regression test).
    """
    monkeypatch.setenv("HEADWAY_DATABASE_URL", migrated_db)
    monkeypatch.setenv("HEADWAY_SESSION_SECRET", TEST_SESSION_SECRET)

    from fastapi.testclient import TestClient

    from headway_api.app import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def seed_user(observer):
    """Insert an auth.users row (bcrypt hash via headway_api.auth) and return
    its user_id. Seeding goes through the observer connection: test setup is
    outside-the-app state, like an administrator using psql."""
    from headway_api import auth

    def _seed(username: str, password: str, role: str) -> str:
        row = observer.execute(
            "INSERT INTO auth.users (username, password_hash, role) "
            "VALUES (%s, %s, %s) RETURNING user_id",
            (username, auth.hash_password(password), role),
        ).fetchone()
        return str(row[0])

    return _seed


def login(client, username: str, password: str) -> dict:
    """Log in through the API and return Authorization headers."""
    resp = client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
