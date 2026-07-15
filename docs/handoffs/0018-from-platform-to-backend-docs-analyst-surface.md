# Handoff: platform → backend, docs — The analyst surface: Python client, read-only SQL, example notebooks

## Context
Planning/data teams evaluate platforms by how well they feed the tools they already use (project direction, 2026-07-15). Headway's answer: meet them where they are — never a hosted notebook environment (declined deliberately: bloats the one-box, adds surface; analysts have their own environments). The honesty story is structural and must be stated everywhere: explore and compute freely; nothing computed outside services/calc can ever become a reported figure (only calc writes computed.metric_values; category walls are DB CHECKs).

## Design (binding)
1. **`headway-client` Python library** (new `clients/python/`, Apache-2.0, published-ready packaging but NOT published this wave): core deps minimal (httpx; pandas behind an optional `[pandas]` extra); auth = machine key (hwk_, existing scopes) or none for the public certified endpoint. Surface: metrics values + compare, machine metrics, lineage walk, DQ issues, public certified — typed models mirroring the API contracts. THE DIFFERENTIATOR: DataFrame helpers preserve provenance columns (metric_value_id, calc name/version, category, certification_status, simulated flags) and a `walk_lineage(metric_value_id)` helper returns the full trail. Provenance columns are not optional kwargs — they are always present (dropping them is the caller's explicit act). Docstrings carry the honesty story. Tests against the existing API test fixtures pattern (respx/fake transport — no live dependency in unit tests); one live smoke run in evidence.
2. **Read-only SQL role** (migration 0028): `headway_readonly` NOLOGIN role with SELECT on canonical.*, computed.*, lineage.*, dq.* and raw.records METADATA columns only if payloads aren't inline (inspect; least privilege wins — exclude auth/audit/cert/app schemas entirely, exclude sampling measurement PII-adjacent free-text if any). Idempotent migration per house pattern; docs/analyst-access.md documents: creating a login user granted the role (commands printed for the admin, installer-style plain language), connecting from psql/DBeaver/pandas.read_sql, and the same never-expose-Postgres-to-the-internet posture as network-access.md.
3. **`notebooks/`**: three example notebooks — ridership exploration (UPT/VRM/VRH with coverage context), OTP + headway adherence analysis (ops category, refusal accounting surfaced honestly), DQ triage (counts, severities, owning workflow) — each using headway-client, each opening with a markdown cell stating the honesty story, each executed ONCE against the live stack with real outputs committed (GitHub renders them — they double as documentation). CI: an nbformat-validity check only (execution needs a live stack — state that honestly in a notebooks/README.md).
4. **README**: one new subsection under "Connect your data" or adjacent — "For analysts" — three lines + links. Docs cross-links (connecting-your-data, sizing).

## Outputs
Client library + tests, migration 0028 + analyst-access.md, three executed notebooks + validity CI step, README subsection, suites green, live smoke evidence appended here.

## Open Questions
- PyPI publication (name reservation, release automation) — Community Maintainer decision, after the library stabilizes a wave or two.
- R/tidyverse parity (the other analyst half) — future increment if agency demand appears.
- Notebook re-execution automation against a demo stack — nice-to-have, not v0.

## Response — backend/docs engineer (2026-07-15)

Contract accepted and delivered: `clients/python/` (headway-client 0.1.0),
migration `db/migrations/0028_readonly_analyst_role.sql` +
`docs/analyst-access.md`, three notebooks executed once against the live
stack with real outputs committed + `notebooks/README.md`, the README "For
analysts" subsection, and the nbformat-validity CI job. The honesty story
appears verbatim-identically (pinned by a unit test on the library side) in
the library docstrings (`headway_client.HONESTY_STORY`), every notebook's
opening cell, docs/analyst-access.md, and the README subsection.

**Deviations from the letter, reported not absorbed:**

1. **The client also accepts a session token, and ships a `login()`
   helper.** The design says "auth = machine key or none," but two of the
   five required surfaces — `GET /metrics/compare` and `GET /dq/issues[...]`
   — accept only a signed-in human session (`require_authenticated`), and
   changing the API is out of scope for this role. The one `token` slot
   therefore carries either credential (both are plain Bearer tokens);
   `metric_values()` dispatches on the token's shape (`hwk_` →
   `/machine/metrics`, else `/metrics/values` — the API guarantees identical
   rows), and the session-only methods say so honestly in their docstrings
   and relay the server's 401 otherwise. `login()` wraps the API's own
   `POST /auth/login`, nothing more. **Open question for the Platform
   Architect / Security Engineer:** extend the dual-credential
   `read:metrics` dependency (the lineage-endpoint pattern) to
   `/metrics/compare` and the DQ reads, so the machine-key-only story
   becomes fully true; the client needs no change when that lands.
2. **License gate touched (kept green, as required).** The gate only
   scanned `services/*/pyproject.toml`, so the new package would have been
   invisible: extended the glob to `clients/*/pyproject.toml` (+ the CI
   install line). Doing so exposed a latent gate crash — `_TIER_RANK` was
   missing the Amendment-2 public-domain tier, so numpy 2.x's
   `BSD-3-Clause AND … AND CC0-1.0` expression raised KeyError instead of
   being judged. Fixed the rank map (permissive < weak < public-domain <
   forbidden < unknown) and added the reviewed tier-3b allowlist row for
   numpy (transitive of the `[pandas]` extra; analyst-side only, never in
   any Headway release artifact).
3. **raw.records access is narrower than "metadata columns":**
   `payload_ref` (object-store keys) and `parse_error` (parser output that
   can quote malformed-payload fragments verbatim) are withheld; the other
   nine columns are granted column-level. Least privilege won, as the
   design instructed.
4. **canonical.\* granted as designed, with one flag for Security review:**
   `canonical.dr_trips` carries pickup/dropoff coordinates — for
   demand-response that is rider-location data (potentially home
   addresses). The binding design says `canonical.*` and that stands, but
   the next Security pass should consciously confirm or column-restrict it.
5. **One CI step only, as scoped:** the nbformat-validity job. The client's
   own unit suite (37 tests, fake transport, no live dependency) is not yet
   a CI job — natural follow-up is a `clients/python` entry in the python
   matrix.
6. Added the migration-0028 static test to `db/test_migrations_static.py`
   (house pattern: every migration's contract is pinned).

**Library surface (headway_client):** `HeadwayClient(base_url, token=None)`
→ `metric_values`, `machine_metrics`, `public_certified`, `compare`,
`lineage`, `walk_lineage`, `dq_issues`, `dq_issue_counts`; module-level
`login()`; models `MetricValue` (`value_decimal`, `simulated`,
`source_mix`), `LineageNode`, `LineageTrail` (`nodes()`,
`raw_record_ids()`), `DqIssue`, `DqIssueCounts`, `Comparand`/`CompareCell`/
`CompareRow`/`CompareResponse`; `frames.metric_values_frame`,
`frames.dq_issues_frame`, `frames.lineage_frame`, `frames.compare_frame`
(provenance columns `PROVENANCE_COLUMNS` always present — pinned by test,
including an inspect-based test that the helper takes no omission kwarg);
`HeadwayApiError` (server detail verbatim, `retry_after_seconds` on 429);
`HONESTY_STORY`.

## Outputs — evidence

All commands run 2026-07-15 on the dev box against the live Compose demo
stack (API 127.0.0.1:8000, TimescaleDB 127.0.0.1:5432). Working tree note:
`services/calc` and `web/` carry ANOTHER session's uncommitted
work-in-progress (handoff 0019 attestation wave); nothing below touches
those paths, and the calc spot-check was therefore run at committed HEAD in
a clean `git worktree` (see 6).

### 1) Client unit tests — fake transport, no live dependency

```
$ cd clients/python && python -m pytest -q
37 passed in 0.48s
```

(httpx.MockTransport fake mirroring the API's paths, filters, and
credential walls — machine-only /machine/metrics, session-only
/metrics/values + /dq/*, dual-credential lineage, unauthenticated public,
429 with Retry-After, plain-language error relay. Provenance-always rule,
Decimal exactness, simulated-flag house rule, and the verbatim honesty
story are each pinned by test.)

### 2) Migration 0028 — live-applied, psql-verified by attack

```
$ python db/migrate.py
applying 0028_readonly_analyst_role.sql ... ok

$ psql (admin): SELECT rolname, rolcanlogin, rolsuper FROM pg_roles WHERE rolname='headway_readonly';
 headway_readonly | f | f
```

Attack from a SEPARATE connection (temporary login user
`analyst_smoke_0028` granted the role, dropped after; psql inside the
timescaledb container over TCP):

```
SELECT count(*) FROM computed.metric_values;                 -> 429        (allowed)
SELECT count(*) FROM canonical.trips;                        -> 118131     (allowed)
SELECT count(*) FROM lineage.edges;                          -> 15069758   (allowed)
SELECT count(*) FROM dq.issues;                              -> 35456      (allowed)
SELECT record_id, source, connector, parse_status
  FROM raw.records LIMIT 2;                                  -> rows       (allowed)
SELECT * FROM raw.records LIMIT 1;          -> ERROR: permission denied for table records
SELECT payload_ref FROM raw.records ...;    -> ERROR: permission denied for table records
SELECT parse_error FROM raw.records ...;    -> ERROR: permission denied for table records
SELECT * FROM auth.users ...;               -> ERROR: permission denied for schema auth
SELECT * FROM auth.api_keys ...;            -> ERROR: permission denied for schema auth
SELECT * FROM audit.events ...;             -> ERROR: permission denied for schema audit
SELECT * FROM cert.certifications ...;      -> ERROR: permission denied for schema cert
SELECT * FROM app.settings ...;             -> ERROR: permission denied for schema app
SELECT * FROM safety.events ...;            -> ERROR: permission denied for schema safety
SELECT * FROM sampling.measurements ...;    -> ERROR: permission denied for schema sampling
INSERT INTO computed.metric_values (...);   -> ERROR: permission denied for table metric_values
UPDATE dq.issues SET status='resolved';     -> ERROR: permission denied for table issues
```

Static checks: `python -m pytest db/test_migrations_static.py -q` → **26
passed** (25 pre-existing + the new 0028 least-privilege test).

### 3) Live smoke — fresh venv, machine key, real data

Temporary key issued via the API as the demo certifying official —
`POST /machine/keys`, name "handoff-0018 analyst surface live smoke
(temporary)", scope `read:metrics`, prefix `hwk_taME9qbH`, key_id
`16444d9f-2077-4818-ac7f-754023a55461`. Fresh venv, then
`pip install -e "clients/python[pandas]"` (headway-client 0.1.0, httpx
0.28.1, pandas 3.0.3).

```
=== 1) machine-key metrics -> DataFrame (provenance columns) ===
columns: ['metric', 'period_start', 'period_end', 'scope', 'value', 'unit',
 'metric_value_id', 'calc_name', 'calc_version', 'category',
 'certification_status', 'simulated', 'source_mix', 'computed_at', 'detail']
3     vrh 2026-07-09 2026-07-11 agency  1260.85 hours abad3473-… vrh_v0 0.2.0 ntd certified   False
12    vrh 2026-07-14 2026-07-16 mode:DR   24.63 hours 6203d665-… dr_vrh_v0 0.1.0 ntd uncertified True
value dtype is exact Decimal objects: OK

=== 2) walk one lineage trail (certified vrh figure) ===
figure abad3473-5ebe-45d2-ae29-623b15f4c4f8 (vrh 1260.85 hours, certified)
trail nodes: 327; raw records at the bottom: 326
first raw record id: 002da97614ea64e3f2253ded0bf1d10869c5c54f8b9cc6800cce9fa83176aab0

=== 3) public certified endpoint, unauthenticated ===
vrh 2026-07-09 2026-07-11  1260.85 hours certified ntd False vrh_v0 0.2.0
vrm 2026-07-09 2026-07-11 12794.92 miles certified ntd False vrm_v0 0.2.0

=== 4) honest walls ===
dq_issues with machine key -> HTTP 401 (relayed honestly)
LIVE SMOKE: all steps passed
```

The simulated DR figures showing `simulated=True` beside real-feed rows
showing `False` is the provenance-columns rule doing its job on live data.

### 4) Notebooks — executed once live, validated, secret-scanned

All three built and executed via nbclient against the live stack
(credentials only from environment variables; machine key for 01/02,
demo data-steward session for 03), then `nbformat.validate` and an
automated secret scan (full key value, password, `hwk_`, JWT prefix,
`Authorization`) over the serialized notebooks BEFORE writing into the
repo, plus a manual read of every output cell:

```
executing 01-ridership-exploration.ipynb …  ok — validated, secret-scanned
executing 02-otp-headway-adherence.ipynb …  ok — validated, secret-scanned
executing 03-dq-triage.ipynb …              ok — validated, secret-scanned
$ grep -rn "hwk_\|demo-.*-2026\|eyJhbGci\|Authorization" notebooks/*.ipynb | grep -v "read:metrics"
NO SECRETS IN NOTEBOOKS
```

Real committed outputs include: 54 ridership figures with provenance; the
certified VRM 12794.92-mile figure walked to its 326 raw records; coverage
context (e.g. the certified vrh row: coverage 0.9263 vs threshold 0.90,
202 of 2742 groups excluded); UPT missing-trip accounting with factors;
agency OTP 54.10% with the full refusal accounting (2,268,231 positions →
535,756 passages; refused: 3,880 cadence-gap + 131,384 not-reached +
21,445 endpoint-unbounded); DQ triage over 35,456 issues (279 blocking,
33 open-blocking listed). CI validity step reproduced locally: 3/3 ok.

### 5) License gate

```
$ python scripts/license_gate.py --ecosystem python
  ok headway-client deps judged (clients/*/pyproject.toml now scanned)
  ok numpy 2.5.1  BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0  PASS (allowlisted)
  -- 52 deps: 52 pass (5 via reviewed allowlist), 0 fail
LICENSE GATE: PASS — 52 dependencies conform to ADR-0001 Amendment 1.
```

(Node ecosystem locally reports one failure: the gitignored design-sync
self-symlink `web/node_modules/web -> ..` from HANDOFF §3.5 — a dev-box
artifact `npm ci` never creates in CI; pre-existing and unrelated. Go
ecosystem untouched.)

### 6) Existing suites — untouched-green

```
services/calc @ committed HEAD (clean git worktree, fresh venv):
  506 passed in 25.53s
  (main working tree shows 6 calc failures caused by ANOTHER session's
   uncommitted calc WIP — mode.py/pmt.py/types.py/upt.py, handoff-0019
   wave; not touched by this work)
services/api:                    245 passed, 1 warning in 10.18s
db static:                       26 passed
clients/python:                  37 passed
.github/workflows/ci.yml:        parses; jobs include notebooks-validate
```

### 7) Temporary key revoked, demo stack undisturbed

```
DELETE /machine/keys/16444d9f-2077-4818-ac7f-754023a55461
  -> {"revoked_at":"2026-07-15T22:20:39.640779Z","audit_event_id":809}
GET /machine/metrics with the revoked key -> HTTP 401
```

Key material deleted from the scratchpad; only the prefix (`hwk_taME9qbH`)
appears anywhere. The temporary SQL login user was dropped after the
attack run (`DROP USER analyst_smoke_0028`); the `headway_readonly` role
remains, as designed. No compose service was restarted or reconfigured.
