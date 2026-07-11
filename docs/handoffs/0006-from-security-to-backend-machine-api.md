# Handoff: security-engineer → backend-engineer — Machine API: service-account keys, authenticated ingest, publishing

## Context
Wave 9: vendors and agency systems need to push data over HTTPS (instead of file drops) and consume published results — without human-session auth. Machine credentials in a public-sector deployment demand: hashed-at-rest secrets, explicit scopes, revocability, full audit, and no secret ever retrievable after issuance (NIST 800-53 IA/AC families as design reference — verify current revision).

## Design (binding)
1. **Credential**: API keys, format `hwk_<32 bytes url-safe random>` (prefix makes leaked keys grep-able and distinguishes them from JWTs). Stored **hashed** (SHA-256 — keys are high-entropy random, so fast hashing is correct here, unlike passwords; document this distinction). Shown ONCE at issuance, never again.
2. **Schema** (migration 0013): `auth.api_keys` — `key_id UUID PK`, `name TEXT NOT NULL` (human label, e.g. "APC vendor X"), `key_hash TEXT NOT NULL UNIQUE`, `key_prefix TEXT NOT NULL` (first 12 chars, for identification in UI/logs), `scopes TEXT[] NOT NULL`, `source_label TEXT` (bound source for ingest keys — the envelope `source` this key may write; a simulated-data key gets `tides_simulated`, a real vendor gets its own label, NEVER interchangeable), `created_by TEXT NOT NULL`, `created_at`, `revoked_at TIMESTAMPTZ` (soft revoke; keys never deleted — audit history).
3. **Scopes** (v0): `ingest:tides` (push passenger-events CSV), `read:metrics` (machine read of computed values + lineage). Scope checks are deny-by-default.
4. **Issuance/revocation**: admin-only endpoints (`certifying_official` role for v0; a dedicated admin role is a future increment), every issuance/revocation/use-failure audit-logged. Key **use** is audited per request at endpoint level (actor = `key:<key_prefix>`), success and denial both.
5. **Ingest endpoint** `POST /ingest/tides/passenger-events` (scope `ingest:tides`): body = TIDES passenger_events CSV (≤ 32 MiB limit, 413 above); the API acts as a connector honoring the wire contract EXACTLY: content-address the raw bytes (sha256 → record_id), store to MinIO `raw/tides/<record_id>.csv`, produce the v0 envelope to `raw.tides.passenger_events` with `source` = the key's `source_label` (never client-supplied), `connector` = `headway-api-ingest`, parse_status from a header sanity check (malformed still landed + produced — fail loudly, never dropped). Response: `{record_id, parse_status}` 202. Store-before-produce ordering (the tides connector precedent).
6. **Rate limiting**: per-key in-process token bucket (default 60 req/min, 429 with Retry-After); documented single-instance limitation (distributed limiting is a hosted-tier increment).
7. **Publishing — webhooks**: `webhook_subscriptions` (same migration): `subscription_id UUID PK`, `url TEXT`, `event_types TEXT[]` (v0: `certification.created`), `secret_hash`… no — webhook secrets must be **stored encrypted or plaintext to sign with**; design: store the HMAC secret encrypted at rest is future work — v0 stores `secret TEXT NOT NULL` with a documented risk note and DB-at-rest encryption as the compensating control, flagged for the secrets-management increment. On certification: POST JSON (certification id, metric ids, values as strings, certified_by, at) with `X-Headway-Signature: sha256=<HMAC-SHA256(body, secret)>` + `X-Headway-Timestamp` (replay window note). Delivery: synchronous best-effort with one retry v0; failures audit-logged, never block certification (the certification transaction commits first; delivery is post-commit).
8. **Publishing — open data**: `GET /public/metrics/certified` — UNAUTHENTICATED read-only, serves ONLY `certification_status='certified'` figures (value strings, detail incl. any simulated flags — transparency shows the flags, it doesn't hide the figures), no PII surface, rate-limited by IP (same bucket mechanism). The transparency-view mandate, minimal form.

## Outputs
Backend implements all of the above: migration 0013, key auth dependency (401/403 plain-language), issuance/revocation/list endpoints, ingest endpoint (minio + kafka-python-ng deps as an `ingest` extra; both injectable/fake-able for tests), webhook dispatch, public endpoint, rate limiter; full unit tests (fake Kafka/MinIO/HTTP; hash-at-rest asserted; source_label override asserted — a client-supplied source header must be ignored; revoked-key 401; scope-deny 403; webhook signature verifiable in test; public endpoint serves only certified). openapi.json regenerated. README + this handoff's evidence appended.

## Open Questions
- Webhook secret encryption at rest → secrets-management increment (Security role, tracked).
- Distributed rate limiting for hosted multi-instance → hosted-tier increment.

## Verification Evidence
- Design authored per SECURITY_ENGINEER role guardrails 2026-07-10. Implementation evidence to be appended.

## Response — backend-engineer (implementation evidence, 2026-07-10)

All eight design points implemented:

1. **Credential**: `headway_api/machine_auth.py` — `hwk_` + `secrets.token_urlsafe(32)`, SHA-256 hash-at-rest with the fast-hash-vs-password distinction documented in the module docstring; the full key exists only in the one issuance response (a test scans every captured SQL parameter for it).
2. **Schema**: `db/migrations/0013_machine_api.sql` — `auth.api_keys` and `auth.webhook_subscriptions` exactly per points 2 and 7, including the plaintext-secret DOCUMENTED RISK note with DB-at-rest encryption named as the compensating control; registered in `db/test_migrations_static.py` (two new checks).
3. **Scopes**: `ingest:tides` + `read:metrics`, deny-by-default in both directions (unknown scope refused at issuance 422; endpoint scope factory refuses unknown names at import). NOTE: `read:metrics` is issuable but no machine-read endpoint consumes it yet — that endpoint is a next increment; the scope is registered so issued keys need no migration then.
4. **Issuance/revocation**: `routers/machine_keys.py`, admin = `certifying_official` (v0). Issuance, revocation, auth failures (unknown/revoked key), and scope denials all audit-logged with actor `key:<key_prefix>`; successful use is audited by the ingest endpoint itself (action `ingest`), so success and denial both land in audit.events.
5. **Ingest**: `routers/ingest.py` — 32 MiB cap (413), sha256 record_id, MinIO/Kafka behind protocols on app.state (None → plain-language 503, never a silent accept), envelope exactly per `contracts/raw-record-envelope.v0.schema.json` (validated against the actual schema file in tests), `source` = key's `source_label` with client-supplied source proven ignored, `connector` = `headway-api-ingest`, header sanity check per the tides.go precedent (malformed still stored + produced), store-before-produce asserted via a shared fake call log, 202 `{record_id, parse_status}`.
6. **Rate limiting**: in-process token bucket, 60 req/min per key default, 429 + Retry-After; single-instance limitation documented in `machine_auth.RateLimiter`.
7. **Webhooks**: `headway_api/webhooks.py` + post-commit wiring in `routers/certify.py`; body per design (values as strings), `X-Headway-Signature: sha256=<HMAC-SHA256(body, secret)>` + `X-Headway-Timestamp`, one retry, outcomes audit-logged, delivery can never fail the 201 (tested with failing and exception-throwing senders); CRUD admin-gated, secret write-only. REPLAY NOTE: v0 signs the body only, per this design; binding timestamp+nonce into the signed material is flagged as the hardening increment.
8. **Open data**: `routers/public.py` — unauthenticated, certified-only, values as strings, detail verbatim (simulated flags shown), no PII (not even the certifier's name), per-IP bucket.

Deviations from the letter of the design (reported, not silent):
- **Ingest keys must carry a `source_label`** (422 at issuance otherwise) — the design binds the envelope source to the key, so a source-less ingest key could never produce a valid envelope; refusing at issuance fails louder and earlier.
- **`DELETE /webhooks/{id}` is a soft revoke** (`revoked_at`), mirroring api_keys — the design did not specify; deletion would erase audit history.
- **Delivery success is also audited** (`webhook_delivered`), beyond the required failure auditing — extra trail, no behavior change.

Verification (2026-07-10, Python 3.12, `/home/daniel/venv`, fakes only — the live stack was not touched):

```
$ cd services/api && python3 -m pytest tests/ -q
76 passed, 1 warning in 2.31s     # 41 pre-existing + 35 new, all green

$ python3 scripts/export_openapi.py
Wrote services/api/openapi.json — OpenAPI 3.1.0, 12 paths: /auth/login,
/certifications, /dq/issues, /dq/issues/{issue_id}/resolve,
/ingest/tides/passenger-events, /machine/keys, /machine/keys/{key_id},
/metrics/values, /metrics/values/{metric_value_id}/lineage,
/public/metrics/certified, /webhooks, /webhooks/{subscription_id}

$ cd db && python3 -m pytest test_migrations_static.py -q
12 passed in 0.10s
```

Dependencies: `ingest` extra (`minio`, `kafka-python-ng`, both Apache-2.0) added to `services/api/pyproject.toml`; `httpx` (BSD-3-Clause) moved from the test extra to core for webhook delivery; `jsonschema` (MIT) added to the test extra for contract-schema validation. PENDING (unchanged from the service README): live verification against real PostgreSQL/MinIO/Kafka once an environment is cleared to touch them; migration 0013 not applied to the live DB by this work.

## Live verification (orchestrator, 2026-07-10 evening)
Migration 0013 applied; API restarted with real MinIO/Kafka wiring. Live flow: key issued (`hwk_m8FQxcdG…`, shown once with warning) → TIDES CSV pushed over HTTP with the key → 202 `{record_id: 574af469…, parse_status: ok}` → drained through transform → **1 row in canonical.passenger_events with source=tides_simulated (bound from the key) and the content-addressed record id intact**. Human session token on the machine endpoint → 401 (credential-type separation). `GET /public/metrics/certified` unauthenticated → both certified figures served. Suites: api 76, db 12, all green.
