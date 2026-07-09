# Headway database migrations

Plain SQL migrations implementing the canonical schema contract v0
(`docs/handoffs/0001-from-platform-architect-to-all-canonical-schema-v0.md`),
targeting PostgreSQL 16 + TimescaleDB. One database per agency; there is no
`tenant_id` anywhere (ADR-0004).

## Running

```sh
pip install -r db/requirements.txt      # psycopg v3, the only dependency
export DATABASE_URL=postgres://user:pass@host:5432/agency_db
python3 db/migrate.py
```

The runner tracks applied migrations in `public.schema_migrations`
(filename + applied_at), applies pending `db/migrations/NNNN_*.sql` files in
filename order, one transaction per migration, and exits nonzero on the first
failure. Re-running is a no-op for already-applied files.

## Immutability and append-only triggers

Two tables carry triggers that `RAISE EXCEPTION` on any `UPDATE` or `DELETE`:

- **`raw.records`** — a raw record is an immutable, as-received unit of
  ingested data. Every reported value must remain traceable back to the raw
  records that produced it (shared constraint: **full provenance**); mutating
  or deleting a raw record would sever that chain, so the database itself
  refuses.
- **`audit.events`** — the audit log is append-only. Rewriting history would
  hide actions instead of surfacing them (shared constraint: **fail
  loudly**), and full audit logging is part of the public-sector security
  posture.

These are deliberate hard failures, not soft warnings: pipelines never
silently drop or rewrite data. If something needs correcting, land a new
record/event and surface the conflict as a `dq.issues` row with an owner.

## Static tests

```sh
pytest db/test_migrations_static.py -q
```

Checks (no live database needed): migration filenames sequential and unique;
every contract table present; no `tenant_id` (ADR-0004); no `DROP TABLE`;
`computed.metric_values.value` is NUMERIC not float; hypertable + unique
index on `canonical.vehicle_positions`; immutability triggers present.

## Verification status

Per the shared constraint **verification before assertion**:

- **Verified (this environment, 2026-07-08):**
  - `pytest db/test_migrations_static.py -q` — all static checks pass.
  - `python3 -m py_compile db/migrate.py` — runner compiles cleanly.
- **PENDING — not yet verified:**
  - Live apply against a real PostgreSQL 16 + TimescaleDB instance. Docker
    and PostgreSQL are unavailable in the authoring environment, so the
    migrations have **not** been executed against a live database. The first
    Docker-capable environment must run `python3 db/migrate.py` against a
    TimescaleDB container, exercise the triggers (attempt UPDATE/DELETE on
    `raw.records` and `audit.events`, expect exceptions), and append the
    evidence to the handoff document before this schema is declared Done.
