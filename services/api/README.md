# Headway API (`services/api`)

FastAPI service for the ADR-0009 walking skeleton: serves computed metric
values with full lineage, the DQ resolution workflow, and the audited human
certification action. **This API never originates a figure** — it serves what
the calculation library wrote to `computed.metric_values`, joined to its
provenance in `lineage.edges` (handoff 0001 schema contract, exactly).

Reported values are **strings in JSON** (PostgreSQL `NUMERIC` precision
preserved end to end; floating point never touches a figure).

## Endpoints

| Method | Path | Role required | What it does |
| --- | --- | --- | --- |
| POST | `/auth/login` | none (credentials) | Local-account login; returns a short-lived HS256 session token. Success/failure is audit-logged. |
| GET | `/metrics/values` | any signed-in role | Computed values from `computed.metric_values`; filter by `metric`, `period_start`, `period_end`. `value` is a string. |
| GET | `/metrics/values/{id}/lineage` | any signed-in role | "Explain this number": recursive traversal of `lineage.edges` (recursive CTE) from the figure down to `raw.records`, returned as a tree `{kind, id, transform_name, transform_version, inputs: [...]}`. A figure with no lineage is a loud 500, never an empty 200. |
| POST | `/certifications` | `certifying_official` only | Inserts `cert.certifications`, marks the figures `certified`, and writes the `audit.events` row — all in ONE transaction. Refuses with 409 while any blocking DQ issue is unresolved. |
| GET | `/dq/issues` | any signed-in role | Data-quality issues; filter by `status`. |
| POST | `/dq/issues/{id}/resolve` | `data_steward` or above | Resolves an issue with a resolution note + audit event, in one transaction. |

The full contract is `openapi.json` (regenerate with
`python3 scripts/export_openapi.py`) — the artifact handed to the web team.

## Auth model (ADR-0011)

**This slice ships local accounts.** `auth.users` (migration
`db/migrations/0009_auth_users.sql` — added by the Backend Engineer with a
Response section on handoff 0001, since it is not part of that schema
contract) holds `user_id, username, password_hash, role, created_at,
disabled`.

- Password hashing: **bcrypt** via the `bcrypt` package (**Apache-2.0** —
  OSI permissive per ADR-0001). Passwords over 72 bytes are rejected loudly,
  never truncated.
- Sessions: **PyJWT** (MIT) HS256 tokens, secret from
  `HEADWAY_SESSION_SECRET` (the app refuses to start without it), TTL from
  `HEADWAY_TOKEN_TTL_SECONDS` (default 30 minutes).
- Claim set: `{sub, username, role}`. The **native OIDC relying party
  (authorization-code + PKCE) is the next increment** and produces this same
  claim set, so `authz.py` and every router are untouched by that addition —
  local accounts are one token source, the RP is the second.
- Roles: `viewer < data_steward < report_preparer < certifying_official`.
  Any signed-in role reads; resolving DQ issues needs data_steward or above;
  **certification is gated to exactly `certifying_official`** (separation of
  duties). Every denial is a plain-language 403.

## Audit guarantees

Every state change (login outcomes, DQ resolution, certification) writes an
`audit.events` row through one helper (`headway_api/audit.py`) that **refuses
to be a no-op** — no connection means the action fails. Audit writes share the
state change's transaction, so nothing commits unlogged; `audit.events` is
append-only at the DB level (migration 0007 trigger).

## v0 simplifications (deliberate, documented)

- **Blocking-DQ check is global, not lineage-scoped**: certification refuses
  if *any* `dq.issues` row with `severity='blocking'` is unresolved.
  Lineage-scoped blocking is the next increment; until then we over-refuse
  rather than ever certify over a known blocking gap.
- Single-tenant wiring: one injected connection (one database per agency,
  ADR-0004). Per-request tenant→database routing arrives with hosted
  multi-tenancy; the seam is `app.state.db` / `get_db`.

## Running

```sh
export HEADWAY_SESSION_SECRET=<random 32+ bytes>
export HEADWAY_DATABASE_URL=postgresql://.../agency_db
uvicorn "headway_api.app:create_app" --factory
```

Tests (no database needed — a fake connection with honest transaction
rollback stands in):

```sh
python3 -m pytest tests/ -q
```

## Verification status

- `pytest tests/ -q`: **36 passed** (2026-07-08, Python 3.12, this repo) —
  covers login/token lifecycle, password-hash round trip, expired/invalid
  token 401s, role denials (viewer cannot certify), certification happy path
  (cert row + status update + audit event in one transaction), blocking-DQ
  409 with rollback, lineage tree from canned edges, DQ resolve + audit.
- `openapi.json` generated: OpenAPI 3.1.0, 6 paths.
- **PENDING**: live verification against real PostgreSQL/TimescaleDB
  (migrations 0001–0009 applied, psycopg connection, `uvicorn` boot,
  recursive CTE executed by a real planner). Docker/Postgres is unavailable
  in the authoring environment; the first environment with Docker must run
  the suite against a live database before this service is declared Done.
