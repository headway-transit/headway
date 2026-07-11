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
| POST | `/machine/keys` | `certifying_official` (v0 admin) | Issues a machine API key. The full key appears ONCE in this response with an explicit warning; only its SHA-256 hash is stored. Audited. |
| GET | `/machine/keys` | `certifying_official` | Lists keys: prefix, name, scopes, source label, created/revoked — never hashes, never key material. |
| DELETE | `/machine/keys/{id}` | `certifying_official` | Revokes a key (sets `revoked_at`; rows are never deleted — audit history). Audited. |
| POST | `/ingest/tides/passenger-events` | machine key, scope `ingest:tides` | Push a TIDES passenger_events CSV (≤ 32 MiB) over HTTPS. Content-addressed (sha256 → `record_id`), stored to MinIO, produced as a v0 envelope to `raw.tides.passenger_events` — store before produce. 202 `{record_id, parse_status}`; malformed is still landed + produced, flagged. Audited per request. |
| GET | `/machine/metrics` | machine key, scope `read:metrics` | Machine read of computed values: same filters and row shape as `GET /metrics/values` (same query function — the two cannot drift). `value` a string, `detail` verbatim. Each row's lineage: feed its `metric_value_id` to `GET /metrics/values/{id}/lineage`. Rate-limited per key; every read audited, actor `key:<prefix>`. |
| GET | `/settings` | any signed-in role | The per-agency policy settings (migration 0014 seeds them), each with its plain-language description, basis, and who last changed it. |
| PUT | `/settings/{key}` | `certifying_official` only | Change one policy setting. Value validated against the setting's `value_type` (decimal parsed via `Decimal` — never float; 422 in plain language); old→new audited; unknown key 404 (settings are seeded, never client-creatable). |
| POST | `/webhooks` | `certifying_official` | Subscribe a URL to `certification.created`. The HMAC secret is accepted here and never returned by anything. Audited. |
| GET | `/webhooks` | `certifying_official` | Lists subscriptions (secret-free). |
| DELETE | `/webhooks/{id}` | `certifying_official` | Removes a subscription (soft revoke). Audited. |
| GET | `/public/metrics/certified` | **none — public open data** | ONLY figures a certifying official already attested (`certification_status='certified'`); values as strings, `detail` verbatim (simulated flags shown, figures never hidden); no PII; rate-limited per client IP. |

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

## Machine API (handoff 0006)

Vendors and agency systems push data and consume results without human
sessions, via **service-account API keys**: `hwk_<32 bytes url-safe random>`.
The `hwk_` prefix makes leaked keys grep-able and distinguishes them from
session JWTs.

**Key lifecycle:**

1. **Issue** (admin — `certifying_official` in v0): the response contains the
   full key exactly once, with a warning string. Only the SHA-256 hash is
   stored (`auth.api_keys.key_hash`, migration 0013). SHA-256 — not bcrypt —
   is deliberate: the key is high-entropy random, so there is no dictionary
   to defend against and a fast hash is the correct at-rest protection
   (see `headway_api/machine_auth.py` docstring).
2. **Use**: `Authorization: Bearer hwk_...` on machine endpoints. Scopes are
   deny-by-default (`ingest:tides` → the ingest endpoint, `read:metrics` →
   `GET /machine/metrics`). Ingest keys are bound to a `source_label` — the ONLY envelope
   `source` they can write (a simulator key gets `tides_simulated`; a
   client-supplied source is ignored). Success and denial are both audited,
   actor `key:<key_prefix>`.
3. **Revoke**: `DELETE /machine/keys/{id}` sets `revoked_at`; a revoked key
   gets a plain-language 401 (audited). Keys are never deleted.

**Machine read (`GET /machine/metrics`, scope `read:metrics`)**: computed
values for dashboards and downstream agency systems, without a human session.
Same filters (`metric`, `period_start`, `period_end`) and exactly the same
row shape as the human `GET /metrics/values` — both endpoints call the one
shared query function, so they can never drift: `value` is a **string**
(exact NUMERIC, never float) and `detail` is served **verbatim** as the calc
library persisted it (ratio/factor strings stay strings; simulated-source
flags shown). **Lineage**: each row's `metric_value_id` is the input to the
existing "explain this number" endpoint,
`GET /metrics/values/{metric_value_id}/lineage`; that endpoint takes a human
session token in v0 — accepting `read:metrics` keys there too is a follow-up
increment. Every successful read is audited (action `machine_read_metrics`,
actor `key:<key_prefix>`, filters + row count in detail — never the figures);
denials and auth failures are audited by the shared machine-auth dependency.
Spends from the same per-key token bucket as ingest.

**Rate limits**: in-process token bucket, 60 req/min per key (and per client
IP on the public endpoint), 429 + `Retry-After`. Single-instance limitation
documented in `machine_auth.RateLimiter`; distributed limiting is the
hosted-tier increment.

**Webhooks**: on certification (post-commit, never blocking the 201), each
live `certification.created` subscription gets a JSON POST signed with
`X-Headway-Signature: sha256=<HMAC-SHA256(body, secret)>` plus
`X-Headway-Timestamp` (receivers should reject stale timestamps; binding the
timestamp into the signature is a tracked hardening increment). One retry;
outcomes audit-logged. The subscription secret is stored plaintext with a
documented risk note + compensating control (migration 0013) — encryption at
rest of that column is the secrets-management increment.

**Ingest dependencies** (`pip install '.[ingest]'`): MinIO (`minio`) and
Kafka (`kafka-python-ng`), wired from the same env vars as the Go connectors
(`S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`,
`KAFKA_BROKERS`). Both live behind small protocols on `app.state`
(injectable fakes in tests); unconfigured means a loud 503, never a silent
accept.

**curl examples:**

```sh
# Issue a key (as a certifying official; save the key — it is shown once)
curl -s -X POST https://headway.agency.example/machine/keys \
  -H "Authorization: Bearer $SESSION_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "TIDES simulator", "scopes": ["ingest:tides"],
       "source_label": "tides_simulated"}'

# Push a passenger_events CSV with that key
curl -s -X POST https://headway.agency.example/ingest/tides/passenger-events \
  -H "Authorization: Bearer hwk_..." -H 'Content-Type: text/csv' \
  --data-binary @passenger_events_2026-06-01.csv
# -> {"record_id": "<sha256 of the bytes>", "parse_status": "ok"}

# Revoke it
curl -s -X DELETE https://headway.agency.example/machine/keys/<key_id> \
  -H "Authorization: Bearer $SESSION_TOKEN"

# Subscribe an external system to certifications
curl -s -X POST https://headway.agency.example/webhooks \
  -H "Authorization: Bearer $SESSION_TOKEN" -H 'Content-Type: application/json' \
  -d '{"url": "https://city.example/hooks/headway",
       "event_types": ["certification.created"],
       "secret": "<random shared secret, min 16 chars>"}'

# Machine read of computed values (key issued with scope read:metrics)
curl -s "https://headway.agency.example/machine/metrics?metric=vrm&period_start=2026-06-01" \
  -H "Authorization: Bearer hwk_..."

# Public open data — no auth at all
curl -s https://headway.agency.example/public/metrics/certified
```

## Per-agency settings (migration 0014)

`app.settings` is the ONE audited place an agency sets calculation policy.
Migration 0014 seeds the four calc policy knobs — settings are **never
client-creatable** (unknown key → 404):

| Key | Default | Type | Basis |
| --- | --- | --- | --- |
| `coverage_threshold` | `0.95` | decimal | ENGINEERING PLACEHOLDER, not an FTA number (`services/calc/REGULATORY_TRACKER.md`); the measured MBTA trip-level structural coverage is ~0.914 — the reason this is per-agency policy. |
| `gap_threshold_seconds` | `300` | integer | Engineering default for the telemetry-gap rule (handoff 0002). |
| `layover_max_seconds` | `1800` | integer | Data-informed (97.3% of measured MBTA in-block intervals under it) and aligned with NTD Policy Manual Exhibit 35's out-of-service exclusion; not an FTA-published number. |
| `missing_trip_threshold` | `0.02` | decimal | The REAL FTA threshold — 2026 NTD Policy Manual p. 146 (≤ 2% missing trips: factor up; above: statistician approval, a human workflow, so the calc refuses). |

Any signed-in role reads (`GET /settings` — policy must be visible to the
people it governs); changing one (`PUT /settings/{key}`) is gated to exactly
the **certifying official** (v0 admin, the machine-keys precedent), because
these knobs move the certifiability line itself. Values are strings validated
against the row's `value_type` — `decimal` parses via `Decimal` (floating
point never touches a policy number), `integer` must be a whole number; a
value that does not parse is a plain-language 422 and changes nothing. Every
change is audited with the **old and new value** in the audit detail, in the
same transaction as the update.

**DOCUMENTED LIMITATION — the calc runner does not read these yet.** Runs
are still governed by the runner's explicit CLI flags
(`--coverage-threshold`, `--gap-threshold-seconds`, `--layover-max-seconds`,
`--missing-trip-threshold`); wiring runner-reads-settings is the follow-up
increment (see the Response on handoff 0002). This surface exists now so
agencies have one audited place to set policy, and so the web team can build
against a stable contract.

```sh
# Read the policy settings (any signed-in role)
curl -s https://headway.agency.example/settings \
  -H "Authorization: Bearer $SESSION_TOKEN"

# Change one (certifying official; old→new lands in audit.events)
curl -s -X PUT https://headway.agency.example/settings/coverage_threshold \
  -H "Authorization: Bearer $SESSION_TOKEN" -H 'Content-Type: application/json' \
  -d '{"value": "0.90"}'
```

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

- `pytest tests/ -q`: **90 passed** (2026-07-10, Python 3.12, this repo) —
  covers login/token lifecycle, password-hash round trip, expired/invalid
  token 401s, role denials (viewer cannot certify), certification happy path
  (cert row + status update + audit event in one transaction), blocking-DQ
  409 with rollback, lineage tree from canned edges, DQ resolve + audit;
  plus the machine API (handoff 0006): key issuance shows the key once and
  stores only the hash (no plaintext in any captured SQL parameter), revoked
  key 401 / wrong scope 403 (both audited), ingest happy path with the
  envelope validated against `contracts/raw-record-envelope.v0.schema.json`,
  client-supplied source ignored in favor of the key's `source_label`,
  store-before-produce ordering asserted on a shared fake call log,
  malformed CSV still landed + produced, 32 MiB 413, unconfigured deps 503,
  per-key and per-IP 429 with Retry-After, webhook HMAC recomputed and
  verified in test, one retry, delivery failure never failing the 201, and
  the public endpoint serving only certified figures with no auth;
  plus the machine read (`GET /machine/metrics`): ingest-only key 403
  (audited scope denial), revoked key 401 (audited), human session token
  401 (credential-type separation), values/detail byte-identical to the
  human endpoint's response, filters, per-key 429 with Retry-After, and
  the per-request `machine_read_metrics` audit event with actor
  `key:<prefix>`; and the settings surface: seeded reads for any role,
  writer gated to certifying_official, decimal/integer 422s in plain
  language, old→new in the audit detail, unknown key 404.
- `openapi.json` generated: OpenAPI 3.1.0, 15 paths.
- **PENDING**: live verification against real PostgreSQL/TimescaleDB,
  MinIO, and Kafka (migrations 0001–0014 applied, psycopg connection,
  `uvicorn` boot, a real ingest → envelope consumed). The authoring
  environment must not touch the live stack; the first environment cleared
  to do so must run the suite against live services before this increment is
  declared Done.
