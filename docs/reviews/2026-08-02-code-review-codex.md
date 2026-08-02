# Access-control and sensitive-data code review — 2026-08-02

Reviewed `ca3c801..b402c93` on `main`; `git rev-parse --short HEAD` returned `b402c93` and the tree was clean before review. Baselines passed: API `725 passed`, web `475 passed`, and calc `681 passed`.

## Findings

### High — a withheld demand-response record's `parse_error` is still exported in the evidence bundle

- **Confidence:** Plausible
- **Location:** `services/api/headway_api/routers/evidence.py:616-651`; supporting boundary documentation at `db/migrations/0028_readonly_analyst_role.sql:34-40`
- **Problem:** The bundle classifies a raw record as rider-location data and withholds its payload, but unconditionally copies the same row's verbatim `parse_error` into `raw_records[].parse_error`.
- **Failure:** Given a lineage leaf whose raw row has `source='dr'`, `connector='headway-dr'`, `parse_status='malformed'`, and `parse_error='CSV parse error near row dr-1,42.35991117,-71.05988117,42.36112233,-71.06033445'`, an auditor's `GET /certifications/{id}/evidence` places the record in `withheld` with classification `rider_location` yet also returns those coordinates in `raw_records[].parse_error`. Migration 0028 explicitly withholds `parse_error` from the direct-SQL analyst because parser output can quote source fragments; the API bundle defeats that parallel protection.
- **Concern touched:** Rider data disclosure.
- **Why tests miss it:** `test_withheld_record_is_named_with_its_reason_and_its_payload_is_absent` seeds the restricted DR row with `parse_error=None` (`services/api/tests/test_evidence_bundle.py:78-85`) and only searches the response for fragments of the payload fixture. The audit-detail test likewise checks only the audit row. Neither gives a withheld record a parser error containing input fragments.
- **Verification limit:** The data flow is direct and the SQL-layer comment records this exact threat, but I could not execute the temporary failing regression test: the environment's filesystem sandbox fails while creating its loopback namespace (`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`), including through the required patch mechanism. I therefore do not label this Confirmed.
- **Suggested fix:** Apply the same sensitivity decision to metadata capable of echoing content: omit or replace `parse_error` for unreadable records, and add a regression fixture whose restricted row's error contains synthetic coordinates.

## Things I checked that appear correct

- **HTTP/SQL privacy agreement outside the finding:** Searches through `ops.py`, `history.py`, `reports.py`, `sandbox.py`, `public.py`, `machine_read.py`, the MCP client/service, and map geometry found no API query that selects `canonical.dr_trips` pickup/dropoff coordinates. Map point geometry is sourced from scheduled stops or vehicle positions, not DR trip endpoints.
- **Sensitivity role handling:** `may_read_sensitivity()` treats `auditor` at viewer breadth and denies unknown roles; the evidence endpoint uses it before recording a restricted leaf as withheld.
- **Unsafe-route choke point:** I constructed the FastAPI app and recursively enumerated every included router's resolved dependency graph. Every human state-changing route reaches `auth.get_current_identity`; `/auth/login`, `/auth/oidc/start`, and `/auth/oidc/callback` are intentionally unauthenticated authentication-protocol endpoints, while `/ingest/*` uses machine authentication. No mounted sub-application or websocket route bypass was registered.
- **Auditor rank handling:** Remaining direct `ROLE_RANK[...]` accesses are guarded by membership checks or index known constant roles; I found no auditor-triggerable `KeyError` or permissive default.
- **OIDC protocol checks:** State consumption is one conditional `UPDATE ... WHERE consumed_at IS NULL ... RETURNING`; nonce is compared with `compare_digest`; PKCE S256 is generated and the verifier is sent at exchange; issuer and audience are passed to JWT verification; multi-audience `azp` is checked; and asymmetric algorithms are allowlisted before key selection.
- **OIDC mapping:** Mapping rows are administrator-created exact claim values. Database, mapping API, and login resolution all exclude `certifying_official`; unmapped claims produce no account/session.
- **OIDC redirect URI:** It is stored configuration, used consistently in authorization and token exchange, and validated as an absolute HTTPS URI (with the documented localhost development exception); callback input cannot substitute another URI.
- **JWKS rotation:** Keys are cached, a missing `kid` causes a rate-limited forced refresh, and `kid`, key type, algorithm, and intended key use are checked before verification.
- **Evidence seal:** The served model is serialized, only `manifest.bundle_sha256` is removed, and canonical JSON is hashed. The existing test recomputes from the parsed response body and detects both a figure edit and removal of `withheld`; I found no attacker-controlled duplicate-key insertion path through the Pydantic model.
- **Evidence gaps:** Missing figures, lineage failures, missing raw-index rows, changed receipts, and label capping are put in `gaps`; privacy refusals are put in `withheld`. The cap is loud and preserves every leaf ID in lineage, though it caps labels rather than total lineage work.
- **Frontend/server parity in the changed surfaces:** Auditor-hidden mutation controls correspond to server dependencies requiring ladder roles or exactly `certifying_official`; the evidence download and verification reads have server authentication independently of UI visibility.
- **Known limitations:** I found no evidence that the reverse-proxy throttle issue, 30-minute role-demotion lag, or untested real-engine state race is worse than already recorded.

## What I could not get to

- No live PostgreSQL was available, so I did not independently prove the conditional state `UPDATE` race or execute migration 0028 as `headway_readonly`; those remain real-Postgres verification items.
- No live IdP or locally owned OIDC server was available, so discovery/JWKS behavior was checked from code and tests, not over a complete browser redirect and key-rotation ceremony.
- I did not load-test evidence bundles containing thousands of figures. The 5,000-label cap does not bound figure queries or lineage walks, so actual latency and memory amplification remain unmeasured rather than cleared.
- I did not exhaustively review unchanged ingestion, transform, calc, signing, retention, object-store download, or machine-key cryptography outside paths needed to answer the five requested areas.
- The MCP service was traced to its machine-authenticated HTTP client and searched for trip/geometry exposure, but I did not run its separate test suite or exercise a live MCP transport.
- A temporary failing regression test for the `parse_error` disclosure could not be applied because the supplied sandbox fails before filesystem patching. No source or test files were changed; only this review document was written via the approved execution fallback.
