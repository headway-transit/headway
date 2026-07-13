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
| GET | `/metrics/values` | any signed-in role | Computed values from `computed.metric_values`; filter by `metric`, `period_start`, `period_end`, `category` (`ntd`\|`ops`, migration 0024). `value` is a string. Every row carries its `category` — the UI badges `ops` rows "Operations metric — not an NTD reported figure". |
| GET | `/metrics/values/{id}/lineage` | any signed-in role, **or** machine key scope `read:metrics` | "Explain this number": recursive traversal of `lineage.edges` (recursive CTE) from the figure down to `raw.records`, returned as a tree `{kind, id, transform_name, transform_version, inputs: [...]}`. A figure with no lineage is a loud 500, never an empty 200. Machine path rate-limited per key + audited (actor `key:<prefix>`); every auth failure is one generic 401 that never reveals which credential type was expected. |
| POST | `/certifications` | `certifying_official` only | Inserts `cert.certifications`, marks the figures `certified`, and writes the `audit.events` row — all in ONE transaction. Refuses with 409 while any blocking DQ issue is unresolved. |
| GET | `/dq/issues` | any signed-in role | Data-quality issues; filter by `status`. Rows include `resolution_minutes` (migration 0016) — null when the effort was not recorded. |
| POST | `/dq/issues/{id}/resolve` | `data_steward` or above | Resolves an issue with a resolution note + audit event, in one transaction. Optional `resolution_minutes` (int ≥ 0; plain-language 422 otherwise) records the effort, audited old→new. Post-commit, dispatches the `dq.issue.resolved` webhook (best-effort — a delivery problem never fails the resolve). |
| GET | `/reports/mr20?month=YYYY-MM` | any signed-in role | The `headway_calc.mr20` MR-20 preview package for the month, served **VERBATIM** (NOT-REPORTABLE banner + caveats included; this API never edits a figure). Plain-language 422 on a bad month. |
| POST | `/machine/keys` | `certifying_official` (v0 admin) | Issues a machine API key. The full key appears ONCE in this response with an explicit warning; only its SHA-256 hash is stored. Audited. |
| GET | `/machine/keys` | `certifying_official` | Lists keys: prefix, name, scopes, source label, created/revoked — never hashes, never key material. |
| DELETE | `/machine/keys/{id}` | `certifying_official` | Revokes a key (sets `revoked_at`; rows are never deleted — audit history). Audited. |
| POST | `/ingest/tides/passenger-events` | machine key, scope `ingest:tides` | Push a TIDES passenger_events CSV (≤ 32 MiB — enforced incrementally as bytes arrive, 413 the moment the cap is passed) over HTTPS. Content-addressed (sha256 → `record_id`), stored to MinIO, produced as a v0 envelope to `raw.tides.passenger_events` — store before produce. 202 `{record_id, parse_status}`; malformed is still landed + produced, flagged. Audited per request. |
| POST | `/ingest/dr/trips` | machine key, scope `ingest:dr` | Push a demand_response_trips CSV (handoff 0013; wire contract `contracts/demand-response-trip.v0.schema.json`) — the SAME connector discipline as the TIDES path (shared helper): ≤ 32 MiB streaming cap, content-addressed, store before produce to `raw.dr.trips`, envelope `source` = the key's bound source_label, malformed still landed + flagged, audited. |
| GET | `/machine/metrics` | machine key, scope `read:metrics` | Machine read of computed values: same filters and row shape as `GET /metrics/values` (same query function — the two cannot drift). `value` a string, `detail` verbatim. Each row's lineage: feed its `metric_value_id` to `GET /metrics/values/{id}/lineage` — the same key works there. Rate-limited per key; every read audited, actor `key:<prefix>`. |
| GET | `/settings` | any signed-in role | The per-agency policy settings (migration 0014 seeds them), each with its plain-language description, basis, and who last changed it. |
| PUT | `/settings/{key}` | `certifying_official` only | Change one policy setting. Value validated against the setting's `value_type` (decimal parsed via `Decimal` — never float; 422 in plain language); old→new audited; unknown key 404 (settings are seeded, never client-creatable). |
| POST | `/webhooks` | `certifying_official` | Subscribe a URL to `certification.created` and/or `dq.issue.resolved`. The HMAC secret is accepted here and never returned by anything. Audited. |
| GET | `/webhooks` | `certifying_official` | Lists subscriptions (secret-free). |
| DELETE | `/webhooks/{id}` | `certifying_official` | Removes a subscription (soft revoke). Audited. |
| GET | `/public/metrics/certified` | **none — public open data** | ONLY figures a certifying official already attested (`certification_status='certified'`) AND `category='ntd'` (migration 0024 — an operations figure is structurally uncertifiable and hard-excluded here besides); values as strings, `detail` verbatim (simulated flags shown, figures never hidden); no PII; rate-limited per client IP. |
| POST | `/safety/events` | `data_steward` or above | Enter one Safety & Security event (handoff 0010; migration 0017). Plain-language validation; runs the deterministic classifier (`headway_calc.sscls`, sscls_v0) SYNCHRONOUSLY and returns classification + thresholds_met + a plain-language explanation with the tracker citation per threshold. Event, classification, and audit record commit in ONE transaction. |
| GET | `/safety/events` | any signed-in role | Events with each one's LATEST classification; filters: `classification` (major/non_major/not_reportable), `month` (YYYY-MM, UTC half-open on `occurred_at`), `mode`. `property_damage_usd` is a string (exact NUMERIC). |
| POST | `/safety/events/{id}/supersede` | `data_steward` or above | Append-only correction: the full corrected event is entered as a NEW row (classified like any entry), and the original gets its one permitted update — the `superseded_by` link (migration 0017 trigger enforces this). Requires a `reason` (audited). 404 unknown; 409 if already corrected. |
| GET | `/safety/deadlines` | any signed-in role | Computed due dates, quote-cited: S&S-40 per open (unsuperseded) major event — `occurred_at` + 30 days (Exhibit 2, p. 4); S&S-50 per mode for the month (`?month=YYYY-MM`, default current UTC month) — due end of the following month (Exhibit 3), INCLUDING zero-event rows for every operated mode (derived like the handoff-0009 per-mode calc path). Carries `period_convention` (the ss50-declared UTC month bucketing) + a plain-language `period_note`; `GET /safety/events` records carry the same `period_convention`. |
| GET | `/sampling/options` | any signed-in role | The sampling plan wizard's vocabulary (modes, units per mode per Table 41.01, options, frequencies), the §41.01/§41.03 eligibility guidance strings, and the ≥3-year documentation-retention note (2026 manual p. 150). All from `headway_calc.sampling` constants. |
| GET | `/sampling/requirements` | any signed-in role | One ready-to-use table cell, verbatim + cited (`mode`,`unit`,`efficiency_option`,`frequency`) — the wizard's live preview. Reads every encoded cell incl. the reference-only grouped-APTL columns. Plain-language 422 for combinations outside the tables. |
| POST | `/sampling/plans` | `data_steward` or above | Create a sampling plan (handoff 0012; migration 0020). Required per-period + annual sizes come from the calc selector (sampling_v0) with its version recorded — this API never encodes a regulatory number. `aptl` and `base` only (grouped deferred, honest scope). Audited. |
| GET | `/sampling/plans` (+ `/{id}`, `/{id}/draws`, `/{id}/measurements`) | any signed-in role | Plans (filter `report_year`, `mode`), a plan, its draws (seed, frame, selection all recorded), its measurements (`observed_pmt` a string; `include_superseded=true` for full history). |
| POST | `/sampling/plans/{id}/draws` | `data_steward` or above | One random-selection act per period at the plan's frequency: caller supplies the period's full expected service-unit list (§63.07); the seeded calc drawer selects WITHOUT replacement (§63.03); seed recorded (generated via CSPRNG when not supplied) **with its provenance** — `seed_source` `'generated'`/`'client'` on the row, in the audit detail, and conditioning the method text's randomness claim (migration 0022; Headway only vouches for the randomness of seeds it generated). Optional random `oversample_units`, flagged with the p. 149 citation. 409 for a repeated period; 422 for reused unit ids across periods, duplicate ids, or an undersized frame. Audited. |
| POST | `/sampling/plans/{id}/measurements` | `data_steward` or above | Manual ride-check entry for ONE drawn unit (observed UPT, PMT; optional Weekday/Saturday/Sunday label + service date). Refuses units outside the drawn sample (hand-picked extras are not random sampling). 409 if the unit already has an active observation — corrections supersede. Audited. |
| POST | `/sampling/measurements/{id}/supersede` | `data_steward` or above | Append-only correction (the migration-0017 pattern): corrected observation entered as a NEW row, original gets its one permitted `superseded_by` update (link-then-insert under the one-active-per-unit index; deferrable FK). Requires a `reason` (audited). |
| GET | `/sampling/plans/{id}/progress` | any signed-in role | Measured vs required, per draw and overall, with the drawn-but-unmeasured worksheet, the undersampling citation (p. 149: follow the technique exactly), and the retention note. |
| POST | `/sampling/plans/{id}/estimate` | `report_preparer` or above | The §83 APTL estimate over the plan's active measurements: sample APTL = ratio of totals (the §83.05(b)-banned average-of-ratios is unconstructible in the calc API), estimated PMT = caller-supplied 100% UPT × APTL, optional by-service-day breakdown. REFUSES undersampled plans (with the citation) and Base-option plans (Section 70 deferred). Result is a provenance-labeled SAMPLED ESTIMATE — `computed.metric_values` is never written. Audited. |
| POST | `/branding/logo` | `certifying_official` | Upload the agency logo (multipart): SVG or PNG only (415 otherwise), ≤ 512 KiB (413 above), stored to the object store at `branding/logo`, content type recorded in `app.settings.brand_logo_meta`. Audited. |
| GET | `/branding/logo` | **none — public** | The agency logo bytes with the stored content type, `Cache-Control: public, max-age=300`, `nosniff` (+ script-blocking CSP for SVG). Plain-language 404 while no logo is uploaded. Rate-limited per client IP. |
| GET | `/branding` | **none — public** | `{display_name, primary, accent, has_logo}` for the app shell — colors already passed the contrast guardrail at write time. Rate-limited per client IP. |

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
`GET /metrics/values/{metric_value_id}/lineage`, which accepts the **same
`read:metrics` key** (or a human session — dual-credential dependency
`machine_auth.require_human_session_or_machine_scope`; the v0 human-only
follow-up is closed). On the lineage endpoint the machine path spends from
the same per-key bucket and each successful traversal is audited (action
`machine_read_lineage`, actor `key:<prefix>`, id only — never figures); the
human path is unchanged, and every authentication failure there is one
generic 401 that does not leak which credential type was expected (the audit
trail keeps the specific reason). Every successful read is audited (action
`machine_read_metrics`,
actor `key:<key_prefix>`, filters + row count in detail — never the figures);
denials and auth failures are audited by the shared machine-auth dependency.
Spends from the same per-key token bucket as ingest.

**Rate limits**: in-process token bucket, 60 req/min per key (and per client
IP on the public endpoint), 429 + `Retry-After`. Single-instance limitation
documented in `machine_auth.RateLimiter`; distributed limiting is the
hosted-tier increment.

**Webhooks**: two event types (deny-by-default registry, like machine
scopes):

- `certification.created` — on certification (post-commit, never blocking
  the 201): certification id, metric ids, values as strings, certified_by,
  certified_at.
- `dq.issue.resolved` (added 2026-07-11, dated note on handoff 0006) — on DQ
  resolution (post-commit, never blocking the 200): `{event_type, issue_id,
  issue_type, severity, resolved_by, resolution_minutes, resolved_at}`;
  `resolution_minutes` is null when the resolver recorded no effort.

Every delivery is a JSON POST signed with
`X-Headway-Signature: sha256=<HMAC-SHA256(body, secret)>` plus
`X-Headway-Timestamp` (receivers should reject stale timestamps; binding the
timestamp into the signature is a tracked hardening increment). One retry;
outcomes audit-logged; a delivery failure never fails the action that
triggered it. The subscription secret is stored plaintext with a
documented risk note + compensating control (migration 0013) — encryption at
rest of that column is the secrets-management increment.

**HONEST SCOPE NOTE — no `dq.issue.created` event.** DQ issues are written
by the calc/transform services, outside this API's process, so the API has
no post-commit moment to dispatch a created-event from — it cannot honestly
offer one. An outbox table (or DB trigger) drained by a dispatcher is the
documented follow-up for full ticketing sync. **v0 ticketing integration**
= the `dq.issue.resolved` push above + polling `GET /dq/issues` (filter by
`status`) for new/open issues.

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

# Subscribe an external system to certifications and DQ resolutions
curl -s -X POST https://headway.agency.example/webhooks \
  -H "Authorization: Bearer $SESSION_TOKEN" -H 'Content-Type: application/json' \
  -d '{"url": "https://city.example/hooks/headway",
       "event_types": ["certification.created", "dq.issue.resolved"],
       "secret": "<random shared secret, min 16 chars>"}'

# Machine read of computed values (key issued with scope read:metrics)
curl -s "https://headway.agency.example/machine/metrics?metric=vrm&period_start=2026-06-01" \
  -H "Authorization: Bearer hwk_..."

# ...and "explain this number" with the same key (dual-credential endpoint)
curl -s https://headway.agency.example/metrics/values/<metric_value_id>/lineage \
  -H "Authorization: Bearer hwk_..."

# Public open data — no auth at all
curl -s https://headway.agency.example/public/metrics/certified
```

## MR-20 preview report (`GET /reports/mr20?month=YYYY-MM`)

Serves the `headway_calc.mr20` package (handoff 0009) **VERBATIM**: the API
imports the calc library, calls `build_mr20_package(conn, month)`, and
returns exactly those bytes — the NOT-REPORTABLE banner, the
programmatically enumerated caveats (fixed divergence list D1–D6 plus
flag-derived), and the four MR-20 data points per mode + fleet totals, each
cell carrying full provenance (`metric_value_id`, `calc_name`,
`calc_version`, `certification_status`, `flags`, `coverage`) or an explicit
`{"value": null, "reason": ...}`. No reshaping, no recomputation — this API
never originates or edits a figure. Any signed-in role reads it (it is a
preview with its own governing caveats, not a certification surface); a
month that is not `YYYY-MM` is a plain-language 422.

**DEPLOYMENT ASSUMPTION (Dockerfile follow-up — not yet edited):**
`headway-calc` is a sibling path package (`services/calc`, not on PyPI),
declared in `pyproject.toml` and installed into the shared venv from the
repo (`pip install services/calc`). The api Docker image must install
`services/calc` the same way before installing/running this service;
updating `services/api/Dockerfile` to COPY + install it is a tracked
follow-up.

```sh
curl -s "https://headway.agency.example/reports/mr20?month=2026-07" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

## DQ resolution effort (migration 0016)

`dq.issues.resolution_minutes` (nullable INTEGER, `CHECK >= 0`, no default)
records how many human minutes a fix took. `POST /dq/issues/{id}/resolve`
accepts an optional `resolution_minutes` (int ≥ 0; a negative or non-integer
value is a plain-language 422 that changes nothing); the value is persisted
with the resolution and audited **old→new** in the same transaction. Bodies
without the field behave exactly as before — the column stays NULL
(unmeasured is null, never zero). `GET /dq/issues` rows include it.

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

## Agency branding — with the accessibility guardrail (migration 0015, handoff 0008)

Agencies brand their Headway instance through the same settings surface:
`agency_display_name` (text), `brand_color_primary` / `brand_color_accent`
(`#rrggbb` hex), and a logo. **THE GUARDRAIL: the server refuses colors that
fail accessibility contrast.** On every `PUT /settings/brand_color_*` the API
computes the WCAG 2.1 contrast ratio server-side
(`headway_api/branding.py` — formula and constants verified against the
published W3C spec, cited in the module docstring) and refuses any color
under **4.5:1 (WCAG 2.1 AA, SC 1.4.3)** against either app surface: the
`#ffffff` page background (`--color-bg`) or the `#f6f8fa` raised card surface
(`--color-surface`), both cited from `web/src/styles.css` `:root` tokens. The
refusal is a plain-language 422 naming the failing surface and the measured
ratio. You can brand it; you cannot brand it inaccessible.

Notes:

- Both shipped surfaces are light (the web app is single-light-theme today).
  A true dark theme cannot reuse one brand color: no color reaches 4.5:1
  against both `#ffffff` and a near-black surface (the math is in
  `branding.py`) — dark mode will need a per-mode brand variant, validated
  against its own surface, as a follow-up.
- Charts never take brand colors: the dashboard palette is validated
  separately (brand ≠ data encoding, handoff 0008).
- `brand_logo_meta` is system-maintained (set by `POST /branding/logo`,
  refused on direct `PUT`); the logo bytes live in the object store at
  `branding/logo` via the same seam as ingest (MinIO in production, a fake
  in tests; without a store the upload refuses with a 503, never a silent
  accept).

```sh
# Set a brand color — a color without enough contrast is refused:
curl -s -X PUT https://headway.agency.example/settings/brand_color_primary \
  -H "Authorization: Bearer $SESSION_TOKEN" -H 'Content-Type: application/json' \
  -d '{"value": "#aabbcc"}'
# -> 422 {"detail": "That color doesn't have enough contrast to be readable:
#    '#aabbcc' measures 1.96:1 against the app's page background (#ffffff),
#    and readable text needs at least 4.5:1 (WCAG 2.1 AA). ..."}

# Upload the logo (certifying official; SVG or PNG, <= 512 KiB; audited)
curl -s -X POST https://headway.agency.example/branding/logo \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -F "file=@logo.svg;type=image/svg+xml"

# The app shell brands itself before sign-in (public, per-IP rate limited)
curl -s https://headway.agency.example/branding
# -> {"display_name": "...", "primary": "#1a5fb4", "accent": "#0b57d0", "has_logo": true}
curl -s https://headway.agency.example/branding/logo -o logo.svg
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

- `pytest tests/ -q`: **202 passed** (2026-07-13, ops analytics wave,
  handoff 0014) — the 196 below plus 6 new: the public certified endpoint
  excludes a category='ops' row even in the (database-impossible)
  certified state and serves `category` on every row; certifying an ops
  figure is a plain-language 409 leaving nothing behind; an open blocking
  OPS finding never gates NTD certification while an NTD one still does;
  `/metrics/values` serves `category` on every row, filters
  `?category=ntd|ops`, and 422s unknown categories.
  `tests/integration`: **6 passed** against a REAL throwaway TimescaleDB
  (migrations 0001–0026 applied) — including the boundary by attack:
  INSERT/UPDATE of a certified ops row refused by
  `metric_values_ops_never_certified`. openapi.json regenerated (31
  paths; MetricValue/PublicMetricValue carry `category`).
- `pytest tests/ -q`: **196 passed** (2026-07-13, Python 3.12, this repo) —
  the hardening-pass Batch C increment
  (docs/reviews/2026-07-13-hardening-pass.md): the pre-existing 188 tests
  unchanged (one renamed: the DR empty-body test now also asserts the
  message names the DR CSV) plus 8 new — streamed-oversized-body 413 with
  the exact pre-streaming message, the incremental reader proven to abort
  mid-stream at the cap (33 of 48 offered MiB chunks consumed, never
  buffering past 32 MiB), oversized Content-Length refused before reading
  any bytes, plain-language length bounds on safety free-text fields
  (narrative 20,000 / location 1,000 / mode + TOS 50 / reason 5,000 —
  at-cap accepted, over-cap 422 saving nothing) and on sampling draw
  fields (period_label 100 / seed 200 / unit ids 500), seed provenance
  (`seed_source='generated'` and `'client'` recorded on the draw row,
  audit detail, list endpoint, and the per-source method text), and the
  UTC month convention surfaced on /safety/deadlines
  (`period_convention` + plain-language `period_note`) and on every
  /safety/events record. `openapi.json` regenerated: OpenAPI 3.1.0,
  **31 paths** (the DR route `/ingest/dr/trips` was missing from the
  previous export; `seed_source`, `period_convention`, `period_note`
  now in the schemas). Migration **0022** (`sampling.draws.seed_source`,
  nullable — pre-0022 draws honestly unknown, append-only, never
  backfilled) applied to the live TimescaleDB via `db/migrate.py` and
  psql-verified; live checks (running API restarted with preserved env):
  streamed oversized POST → 413, `/openapi.json` serving 31 paths, and
  the demo routes still answering — evidence in
  docs/reviews/2026-07-13-hardening-pass.md, "Batch C".
- Earlier record — `pytest tests/ -q`: **179 passed** (2026-07-12, Python 3.12, this repo) —
  the pre-0012 suite unchanged plus 25 sampling tests (handoff 0012):
  wizard options/requirements lookups (verbatim cells + citations), plan
  creation with selector-recorded sizes and the grouped-option refusal,
  seeded reproducible draws (explicit-seed determinism, oversample flagged
  random, repeated-period 409, reused-unit-id/duplicate/undersized-frame
  422s), measurement entry limited to drawn units with supersede
  corrections (same-unit rule, double-correction 409, honest FakeConn model
  of the one-active-per-unit unique index), progress with the worksheet,
  and the §83 estimate (undersampling refusal with citation, Base-option
  refusal, hand-computed ratio-of-totals figures, provenance label,
  by-service-day variant, `computed.metric_values` untouched). LIVE
  (2026-07-12): migration 0020 applied + psql-verified (append-only proven
  by attack on all three tables); the full walkthrough (create plan → 4
  quarterly draws → 50 measurements incl. one supersede → progress →
  estimate) ran through the running API with rows confirmed from a
  separate psql connection — and the live run caught a real supersede
  ordering bug the unit fake had masked (fixed: deferrable FK,
  link-then-insert; the fake now models the unique index honestly).
  Evidence in handoff 0012, "Outputs — backend evidence".
- Earlier record — `pytest tests/ -q`: **154 passed** (2026-07-12, Python 3.12, this repo) —
  the pre-0010 suite unchanged plus 18 Safety & Security tests (handoff
  0010 + the addendum correction round): role denials, synchronous
  classification (sscls_v0 0.1.1) with citation-bearing explanations,
  audit-in-transaction, plain-language 422s, list filters
  (classification/month/mode) with exact-string NUMERIC, supersede
  happy/404/409 with rollback asserted, the deadlines rules (S&S-40 +30
  days; S&S-50 end of following month incl. zero-event operated modes,
  NULL-mode 'unknown' bucketing, superseded majors excluded), the
  migration-0018 runaway_train field flowing to a rail-only threshold, and
  the p. 22 fix (single-injury Other Safety Event → non-major with the
  Non-Major-Summary citation; two injuries → major). LIVE (2026-07-12):
  migrations 0017 and 0018 applied to the compose TimescaleDB and
  inspected via a separate psql connection (append-only proven by attack);
  realistic events POSTed through the running API returned 201 AND the
  event + classification + audit rows were confirmed from a separate psql
  connection (the autocommit-phantom-write check); supersede, filters, and
  deadlines exercised live — evidence in handoff 0010, "Outputs — backend
  evidence".
- Earlier record — `pytest tests/ -q`: **96 passed** (2026-07-11, Python 3.12, this repo) —
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
  `key:<prefix>`; plus the dual-credential lineage endpoint: a
  `read:metrics` key traverses the same canned tree a human session gets,
  ingest-only key 403 (audited), revoked key 401 (audited, generic on the
  wire), one identical generic 401 for every auth-failure mode (no
  credential-type leak), human path untouched by the machine bucket and
  never machine-audited, per-key 429 shared with `/machine/metrics`;
  and the settings surface: seeded reads for any role,
  writer gated to certifying_official, decimal/integer 422s in plain
  language, old→new in the audit detail, unknown key 404.
- `pytest tests/ -q`: **136 passed** (2026-07-11, migration 0016 + MR-20 +
  dq.issue.resolved increment): the 123 pre-existing tests unchanged and
  green, plus the MR-20 endpoint (canned calc package served byte-identical,
  any signed-in role incl. viewer, anonymous 401, plain-language 422 on six
  bad month shapes that never reach the calc library), DQ resolution effort
  (minutes persisted + audited old→new, body without minutes fully backward
  compatible with NULL never zero, negative minutes plain-language 422
  changing nothing, list rows include the field), and the `dq.issue.resolved`
  webhook (HMAC recomputed and verified, post-commit ordering — the
  dq_resolve audit event precedes the delivery event, retry-then-audited
  failure never failing the 200, null minutes delivered as null, and
  event-type matching in both directions between certification-only and
  dq-only subscriptions).
- `openapi.json` generated: OpenAPI 3.1.0, **31 paths** (2026-07-13
  regeneration — the 18-path note here was stale; the export is now
  drift-gated in CI, `.github/workflows/ci.yml`).
- **PENDING**: live verification against real PostgreSQL/TimescaleDB,
  MinIO, and Kafka (migrations 0001–0016 applied, psycopg connection,
  `uvicorn` boot, a real ingest → envelope consumed). The authoring
  environment must not touch the live stack; the first environment cleared
  to do so must run the suite against live services before this increment is
  declared Done.
