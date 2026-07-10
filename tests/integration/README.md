# Integration tests — the API against a real PostgreSQL/TimescaleDB

This suite is the standing protection for the **2026-07-10 autocommit bug
class**: the API returned `201 Created` for a certification while
`cert.certifications` stayed empty, because psycopg3's implicit-transaction
trap kept every write inside a never-committed savepoint. A fake connection
cannot catch that; only a real database, observed from a **separate**
connection (the psql-equivalent that caught it live), can. Background:
`services/api/headway_api/db.py` and
`services/api/tests/test_transaction_discipline.py`.

## What it does

- Requires `HEADWAY_IT_ADMIN_URL` — a superuser/owner connection URL to a
  **throwaway** PostgreSQL 16 + TimescaleDB server. If unset, every test
  **skips** with a clear reason, so unit CI needs no database.
- Creates a scratch database (`headway_it_<random>`), applies **all**
  `db/migrations/*.sql` via `db/migrate.py`, runs the tests, then
  `DROP DATABASE ... WITH (FORCE)` — even on failure. Existing databases on
  the server are never written to.
- Boots the FastAPI app through the **production** path: `create_app()` +
  the real lifespan opening a real psycopg connection from
  `HEADWAY_DATABASE_URL` (pointed at the scratch database).
- Every assertion about persisted state goes through a separate psycopg
  connection, never the app's own.

## Running locally

Point `HEADWAY_IT_ADMIN_URL` at any throwaway Postgres+Timescale —
**NEVER at a production database** (the suite only creates/drops its own
scratch database, but a throwaway server is the only safe habit):

```sh
# e.g. a disposable container:
docker run --rm -d -p 5432:5432 -e POSTGRES_PASSWORD=throwaway \
    timescale/timescaledb:latest-pg16

python -m pip install -e "services/api[test]" -r tests/integration/requirements.txt

export HEADWAY_IT_ADMIN_URL='postgres://postgres:throwaway@127.0.0.1:5432/postgres'
python -m pytest tests/integration -q
```

Credentials in the URL must be **percent-encoded** (e.g. `@` → `%40`) — the
URL is parsed as a URL; see `db/README.md` for the 2026-07-09 finding.
Internally the suite converts it to keyword form once, so the scratch-db DSN
handed to the app and to `migrate.py` is immune to the encoding trap.

Without `HEADWAY_IT_ADMIN_URL` the suite skips cleanly:

```sh
python -m pytest tests/integration -q   # -> all tests SKIPPED, exit 0
```

## In CI

`.github/workflows/ci.yml` job `integration-postgres` runs this suite against
a `timescale/timescaledb:latest-pg16` service container on every change to
`services/api/`, `db/`, `tests/integration/`, or the workflows themselves.
