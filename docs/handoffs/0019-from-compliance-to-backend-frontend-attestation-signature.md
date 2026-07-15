# Handoff: ntd-compliance + security → backend, frontend — Statistician attestations + certifier digital signature

## Context
Two halves of one principle: accountable human judgment rendered into the permanent record (project direction, 2026-07-15). (A) The p. 146 rule (quoted in REGULATORY_TRACKER.md, upt_v0 section) permits factoring beyond 2% missing "if a qualified statistician approves the factoring method" — Headway currently refuses flat, which is STRICTER than the regulation and blocks agencies with legitimate approvals. (B) Certification today is an audited consent flow but not a visible signature; the certifier's sign-off must become a front-and-center digital signature with tamper-evidence.

## Design (binding)

### A. Statistician attestations
1. Migration (next free number): `cert.attestations` — attestation_id, statistician name + credentials summary, method description, document reference (external doc pointer, never the doc itself), scope (metric, mode/TOS pattern, period range), entered_by, entered_at, revoked_at NULLABLE (revocation, never deletion; append-only discipline per house pattern). Audited entry via new authorized-role API (certifying_official or a new attestation-manager permission — inspect the role model and pick the smallest honest fit; document).
2. Calc integration: upt_v0/pmt_v0 factor-up path accepts an attestation context — WITHOUT a matching in-scope attestation, >2% refusal stands exactly as today; WITH one, the calc emits the factored figure carrying attestation_id + method summary in detail/provenance; receipt renders "factored beyond the 2% threshold under a statistician-approved method — attestation #N" + the p. 146 quote + attestation details. New calc version bumps per house convention (0.1.x → next; tracker rows citing the p. 146 sentence verbatim). The pre-existing refusal DQ issue resolves to an explicit 'attested' resolution state (audited, never deleted).
3. HARD LIMITS (pinned by tests): attestation can never unblock sampling undersampling (manual prohibition — no statistician cure; cite the "must not collect a smaller sample" quote), never touches simulated flags, never applies outside its declared scope, never affects ops metrics.

### B. Certifier digital signature
4. Migration (same or next): cert.certifications gains signature fields — canonical_document (the exact signed bytes: figures + receipt hashes + certifier identity/typed name+title + acknowledgments incl. attestations + timestamp, canonical JSON), signature (Ed25519, installation key), key_fingerprint. Key: generated at install/first-use, stored like other secrets (.env/secret file, never in DB or repo; installer note). Existing certifications keep NULL signature (honest history, never backfilled).
5. Signing ceremony (frontend): the cockpit's final step becomes a signature block — typed full name + title against the intent statement, everything covered listed above it (figures w/ receipt hashes, acknowledgments, attestations); submit → server canonicalizes, signs, stores; the UI then renders the certificate view: signature block front and center, fingerprint, covered list, verify button.
6. Verification: GET endpoint re-verifies stored document vs signature (and a verify UI affordance); tamper test pinned (mutate a stored canonical_document via SQL in test → verification fails loudly).
7. Propagation: certificate block (signer, timestamp, fingerprint) renders on the certification record view, joins MR-20/S&S-50 XLSX "Read first" sheets when the period is certified, and the public certified endpoint serves the fingerprint.
8. HONEST SCOPE stated on the certificate itself: installation-held key = integrity + attribution within this system (tamper-evidence), NOT PKI non-repudiation; per-certifier keys (WebAuthn) is the documented v1. ESIGN-style intent statement wording reviewed for plain language.

## Outputs
Migrations live-applied + attacked (append-only, tamper test), calc bumps + tracker rows, attestation API + calc + receipt path, signing ceremony + certificate + verify, export/public propagation, all suites green + axe/contrast, live end-to-end evidence (an attested factored figure + a signed certification, psql-verified), evidence here.

## Open Questions
- Per-certifier WebAuthn signing keys (v1).
- Attestation-document storage (v0 = external reference only; in-system encrypted doc storage later).
- Whether S&S-20-style CEO certs adopt the same signature machinery (likely yes; separate increment).

## Response (backend + calc, 2026-07-15)

Contract ACCEPTED. Design points A.1–A.3 and B.4/B.6/B.7-backend/B.8-backend
are built, tested, live-verified, and evidenced below. B.5 (signing ceremony
UI) and the certificate/receipt rendering are the frontend wave's, against
the contract in "API contract for the frontend" below.

### Deviations from the letter (reported, not silently absorbed)

1. **Attestation-entry role = `certifying_official`** (the design offered
   "certifying_official or a new attestation-manager permission — pick the
   smallest honest fit; document"). Chosen and documented in
   `services/api/headway_api/routers/attestations.py`: recording a
   statistician's approval directly changes what figures the platform emits
   for federal reporting — the same accountability class as certification;
   a new permission would grow the role vocabulary for one action that in
   practice belongs to the same officer. The `attested` DQ closure
   (POST /dq/issues/{id}/attest) is `data_steward`+, like every resolution.
2. **"Migration (next free number)" became TWO migrations** — 0029
   (cert.attestations + the `attested` dq status) and 0030 (certification
   signature columns + append-only trigger) — the design's "same or next"
   for B.4 read as permission for a second file; separation keeps each
   attackable independently.
3. **cert.certifications gained a strict append-only trigger** (0030) — not
   explicitly demanded, but implied by tamper-evidence: no in-band
   UPDATE/DELETE at all. The tamper test therefore DISABLES the trigger in
   the scratch copy first (simulating out-of-band DB access) — exactly the
   attacker the signature exists to catch.
4. **The live signed certification covers a REAL figure (voms 984, MBTA
   GTFS-RT positions), not the attested PMT figure.** The attested PMT
   figure derives from SIMULATED passenger events (`tides_simulated`) — a
   certifiable figure containing simulated records is a contradiction
   (handoff 0005 rule), so certifying it, even as a demo, would have broken
   the standing honesty rule. The certificate's statistician-attestation
   acknowledgment block is pinned by unit test
   (test_signature.py::test_certify_signs_canonical_document_with_receipt_hashes)
   instead.
5. **The live UPT figure for the evidence period factored WITHOUT the
   attestation** — its missing share improved to 0.0100 (≤ 2%) since
   handoff 0011 (more simulated events have since been ingested), so the
   ordinary ≤2% branch applied and the attestation correctly did NOT govern
   (detail carries `factor_applied` 1.010075 and no `attestation` key).
   PMT (share 0.3659) is the attested live evidence.
6. **quotes.json regeneration is handed to the frontend wave** (web/ is
   out of this wave's tree): the tracker gained the "Verified —
   statistician attestations (calc upt_v0 + calc pmt_v0 0.2.0, …)" section,
   so `npm run extract:quotes` changes `web/src/regulatory/quotes.json`
   keys `upt_v0` (+2 quotes: p. 149, p. 150) and `pmt_v0` (same). Verified
   by a dry-run of the extractor to a scratch path (extracts cleanly, 11
   upt / 22 pmt quotes, the p. 149 sentence present under both). The CI
   quotes drift gate FAILS until the frontend agent regenerates.
7. **License-gate note:** `cryptography` (Apache-2.0 OR BSD-3-Clause,
   tier-2 permissive) added to services/api and PASSES the gate. The gate's
   one current FAIL is `pandas` declared in `clients/python/pyproject.toml`
   — the in-flight handoff-0018 tree, not this wave's; its owner installs
   and re-runs.

### API contract for the frontend (exact shapes)

**`GET /certifications/intent`** (any role) →
`{"intent_statement": str, "scope_statement": str, "algorithm": "ed25519"}`
— render both in the ceremony; the scope statement is the B.8 honest-scope
text and is also INSIDE every signed document.

**`POST /certifications`** (certifying_official) — request:

```json
{"metric_value_ids": ["<uuid>", "..."],
 "attestation": "<the acknowledgment text, min 1 char>",
 "signer_full_name": "<typed, min 1>",
 "signer_title": "<typed, min 1>"}
```

201 response: `{certification_id, metric_value_ids, certified_by,
certified_at, attestation, signer_full_name, signer_title,
canonical_document (str — the exact signed text), signature (base64),
key_fingerprint ("ed25519:<64 hex>"), algorithm: "ed25519",
audit_event_id}`. Refusals: 409 open/owned blocking DQ (message unchanged),
404 unknown ids, 409 ops ids, 409 already certified, 422 missing typed
name/title, **503 when no signing key is configured (nothing written)**.

The canonical document (parse `canonical_document` or use the `document`
field of the certificate view): `{document_type: "headway-certification",
document_version: 1, certification_id, certified_at (ISO-8601 UTC),
certifier: {username, role, typed_full_name, typed_title},
intent_statement, scope_statement, attestation_text,
figures: [{metric_value_id, metric, unit, value (string),
period_start, period_end, scope, calc_name, calc_version, category,
detail (verbatim dict), receipt_sha256}],
statistician_attestations: [<detail.attestation dicts, unique, sorted>]}`.
`receipt_sha256` = SHA-256 hex over the canonical bytes of the figure
object minus the hash key itself (canonicalization documented in
`headway_api/signing.py`) — independently recomputable client-side.

**`GET /certifications`** (any role) → `[{certification_id,
metric_value_ids, certified_by, certified_at, attestation, signed (bool),
key_fingerprint (str|null), signer_full_name (str|null),
signer_title (str|null)}]` — nulls = pre-signature legacy, render honestly.

**`GET /certifications/{id}`** (any role) → the record fields above +
`{canonical_document (str|null), signature (str|null),
document (parsed object|null), verification: <VerificationResult>}` — the
certificate view payload.

**`GET /certifications/{id}/verify`** (any role) and
**`GET /public/certifications/{id}/verify`** (public, rate-limited) →
`VerificationResult = {certification_id, signed (bool),
verified (bool|null), verdict: "verified"|"failed"|"unsigned_legacy"|
"key_mismatch", algorithm: "ed25519", key_fingerprint (str|null),
certified_at, message (plain language)}`. `failed` messages start
"VERIFICATION FAILED" — render loudly. The public variant carries no
certifier identity anywhere.

**`GET /public/metrics/certified`** rows gained
`certification: {certification_id, certified_at,
key_fingerprint (str|null)} | null`.

**`POST /attestations`** (certifying_official) — request:
`{statistician_name, statistician_credentials, method_description,
document_reference, metric: "upt"|"pmt", scope_pattern (fnmatch over
computed.metric_values.scope: "agency", "mode:bus", "mode:DR:tos:*", "*"),
period_start, period_end (dates, half-open)}` → 201 with all fields +
`{attestation_id, entered_by, entered_at, revoked_at: null, revoked_by:
null, revocation_reason: null, audit_event_id}`.
**`GET /attestations?metric=&include_revoked=`** (any role; revoked served
by default) and **`GET /attestations/{id}`** → the same record shape.
**`POST /attestations/{id}/revoke`** (certifying_official) —
`{"reason": str}` → 200 with the revoked record + audit_event_id; 409 if
already revoked (never un-revokable, never deletable).

**`POST /dq/issues/{issue_id}/attest`** (data_steward+) —
`{"attestation_id": "<uuid>"}` → 200 `{issue_id, status: "attested",
resolved_at, resolution (server-built, names the attestation),
attestation_id, audit_event_id}`. 409 for any issue_type other than
`apc_missing_trips_above_fta_threshold` (message quotes the p. 149
no-smaller-sample sentence), 409 revoked attestation / already-closed
issue, 404s. `GET /dq/issues?status=attested` filters; `attested` appears
in `/dq/issues/counts.by_status`.

**Receipt data for an attested figure:** `detail.attestation` on the
metric value (present ONLY when an attestation governed) =
`{attestation_id, statistician_name, statistician_credentials,
method_description, document_reference, metric, scope_pattern,
period_start, period_end, entered_by, entered_at, basis}` where `basis` is
the verbatim p. 146 sentence. The paired DQ info finding is issue_type
`apc_missing_trips_attested_factor_up`, title "Factored beyond the 2%
threshold under a statistician-approved method — attestation #<id>". The
p. 146/p. 149/p. 150 quotes are in the tracker section "Verified —
statistician attestations" (extract:quotes serves them under `upt_v0` /
`pmt_v0`).

Full regenerated contract: `services/api/openapi.json` (drift-gate clean).

## Outputs — backend evidence (2026-07-15)

**Migrations taken: 0029, 0030** (0028 was taken by the handoff-0018 wave —
checked immediately before numbering and again before applying).
Live-applied via `db/migrate.py` to the live TimescaleDB
(`schema_migrations` shows both), plus applied to a FRESH scratch database
by the real-PostgreSQL integration suite (0001–0030 end to end).

**Attacked (separate psql connection, live DB):**

- `UPDATE cert.attestations SET statistician_name='Mallory' …` →
  `ERROR: cert.attestations is append-only: the only permitted UPDATE is
  setting revoked_at, revoked_by and revocation_reason once, together …`
- `DELETE FROM cert.attestations …` → `ERROR: … DELETE rejected. Revoke
  instead …`
- revocation trio UPDATE → `UPDATE 1`; second revocation → `ERROR: … is
  already revoked and can never change again.`
- `UPDATE cert.certifications SET attestation='tampered' …` /
  `DELETE FROM cert.certifications …` → both rejected by
  `certifications_append_only`.
- dq status CHECK live:
  `issues_status_check CHECK (status IN ('open','owned','resolved','attested'))`.

**Suites (all green, 2026-07-15):**

- calc: **537 passed** (was 506; +31 — attestation module/upt/pmt/runner
  tests, see services/calc/README.md).
- api: **279 passed** (was 245; +34 — attestations, attested closure,
  signature/verify/tamper, public + export propagation).
- db static: **28 passed** (+2 for 0029/0030).
- integration (REAL PostgreSQL, `HEADWAY_IT_ADMIN_URL` at the live server):
  **6 passed** — the autocommit-guard suite now exercises the SIGNING
  certification path and migrations 0001–0030 on a scratch DB.
- untouched suites re-run green: transform 131, ai 109 + grounding gate
  6/6, ingestion `go build`/`vet`/`test` ok. web untouched (frontend wave).
- license gate: `cryptography 49.0.0 — Apache-2.0 OR BSD-3-Clause — PASS`
  (the one FAIL is `pandas` in the in-flight handoff-0018 clients/ tree,
  not this wave's).
- openapi drift gate: `python3 scripts/export_openapi.py` regenerated;
  re-run produces zero diff against the tree.

**Live end-to-end — statistician attestation (design point A):**

1. Attestations entered through the API as `certifier`
   (certifying_official): pmt `b4f5311e-2f90-4d96-86e3-2d4c339e853e`, upt
   `603322fa-4ff6-41b7-97fc-fb336c9747d2` — statistician "Dr. Rosa Field",
   scope `agency`, period [2026-07-09, 2026-07-10) (the handoff-0011 PMT
   refusal period). Audit rows written in-transaction.
2. Pre-existing refusal issues closed to the EXPLICIT `attested` state via
   `POST /dq/issues/{id}/attest` (as `dsteward`): pmt refusal
   `ad0412e7-…` (the 0011 evidence row, share 0.3659) and upt refusal
   `dc3bdccc-…`; audit events 820/821; resolution text names statistician,
   method, attestation id, p. 146.
3. Live run `python3 -m headway_calc.runner --period-start 2026-07-09
   --period-end 2026-07-10` → `attestations_loaded: 2`;
   **pmt agency 0.2.0 PERSISTED: 221996.24 passenger miles**, factor
   1.577010 over share 0.3659 — the exact period handoff 0011 refused —
   metric_value_id `82f8c972-f50c-4657-b3ff-3d3de50bbf71`; upt agency
   0.2.0 persisted 238100 via the ORDINARY ≤2% branch (share now 0.0100 —
   deviation 5 above). vrm/vrh still refuse on coverage (untouched by
   attestations — correct).
4. psql-verified from a separate connection:
   `detail->'attestation'->>'attestation_id' = b4f5311e-…`,
   `->>'statistician_name' = Dr. Rosa Field`,
   `detail->>'factor_applied' = 1.577010`,
   `detail->>'missing_or_invalid_share' = 0.3659`; 1 lineage edge to the
   period's single raw TIDES batch record (all 0 counted events share one
   content-addressed source record — verified:
   `SELECT count(DISTINCT source_record_id) FROM
   canonical.passenger_events WHERE …` → 1); routed info finding
   `17213385-…` "Factored beyond the 2% threshold under a
   statistician-approved method — attestation #b4f5311e…".

**Live end-to-end — signed certification (design point B):**

1. Remaining 33 open blocking NTD issues closed through the audited
   `POST /dq/issues/{id}/resolve` workflow (v0 global gate; each resolution
   states it closes historical refusal evidence for this walkthrough).
2. `POST /certifications` as `certifier`, typed signer "Casey Certifier,
   Director of Operations, Demo Transit Agency", covering the REAL figure
   voms agency 984 ([2026-07-09, 2026-07-10), voms_v0 0.1.0, MBTA GTFS-RT
   positions; deviation 4) → certification
   `f47c4ce0-b6e3-4fba-81d9-9bc0a48c3b92`, key fingerprint
   `ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7b32fd3041691ecd10be9e371`,
   audit event 857 (fingerprint + signer in detail). psql: doc 2223 bytes,
   sig 88 base64 chars, figure `certified`; the pre-existing handoff-0002
   certification `2fbf5451-…` keeps NULL signature columns (honest
   history).
3. `GET /certifications/{id}/verify` → `verdict: "verified"`; PUBLIC
   `GET /public/certifications/{id}/verify` (no auth) → verified, no
   certifier identity in the payload; `GET /public/metrics/certified` →
   the voms row carries `certification.key_fingerprint`, the legacy
   vrm/vrh rows carry `key_fingerprint: null`.
4. **Tamper test in a scratch copy:** `pg_dump -n cert` into scratch DB
   `headway_tamper`; `ALTER TABLE … DISABLE TRIGGER
   certifications_append_only` (out-of-band attacker); SQL-mutated the
   stored canonical_document (`"value":"984"` → `"value":"1984"`); second
   API instance pointed at the scratch DB →
   `GET /public/certifications/f47c4ce0-…/verify` →
   `verdict: "failed", verified: false, message: "VERIFICATION FAILED: …
   The record has been tampered with since signing …"`. The untampered
   legacy row in the same scratch reads `unsigned_legacy`. Scratch DB
   dropped after.
5. **Live XLSX propagation:** `GET /reports/mr20/export?month=2026-07
   &format=xlsx` → "Read first" sheet carries the certificate block:
   `Certification f47c4ce0-…: signed by Casey Certifier, Director of
   Operations, Demo Transit Agency on 2026-07-15T23:00:05… — Ed25519
   signature, key fingerprint ed25519:f0995b71…` plus the honest legacy
   line for `2fbf5451-…` ("recorded before digital signatures existed").

**Key posture (live + shipped):** installation key generated
`openssl rand -hex 32` into `deploy/compose/.env` (mode 600, value never
logged); `HEADWAY_SIGNING_KEY` added to `.env.example`, `compose.yaml` api
environment, and `install/install.sh` (generated at install, same pattern
as the session secret); first-use file generation via
`HEADWAY_SIGNING_KEY_FILE` (0600) unit-tested. Never in DB or repo —
pinned by migration text, README, and the 503-refusal test. Live API on
127.0.0.1:8000 restarted with its full preserved environment + the key
(web dev server untouched).

**For the frontend wave:** regenerate `web/src/regulatory/quotes.json`
(`npm run extract:quotes` — deviation 6); build B.5 against "API contract
for the frontend" above.

## Outputs — frontend evidence (2026-07-15, web/ only; no commits)

Design point B.5 + the attestation/certificate surfaces are built,
mock-first against this handoff's binding design, then RECONCILED against
the backend's "API contract for the frontend" above and the regenerated
`services/api/openapi.json`, and live-verified end to end through the real
stack (vite on localhost:5173 → API on 127.0.0.1:8000, SPA nav only after
login, headless Chrome via CDP).

### What was built

- **Signing ceremony (`src/views/CertifyView.tsx`, design 5):** the
  cockpit's final step is now the signature block — everything the
  signature covers listed first (each selected figure verbatim with its
  provenance link, the honest receipt-hash line — hashes exist only inside
  the signed document, so the ceremony says "computed and recorded by the
  server when it signs" and never fakes one — and any statistician
  attestation the figure relies on), then the SERVER's ESIGN-style intent
  statement (`GET /certifications/intent`, rendered verbatim; if it cannot
  be loaded the ceremony refuses to arm, with the reason stated — you can
  only sign against the exact words the server records), then the typed
  full name + title, then the sign action under the house
  aria-disabled-with-reason pattern (every cause stated beside the button:
  blockers with the API's own 409 wording, empty selection,
  unacknowledged warnings, missing name/title, intent not loaded).
  Submit → `POST /certifications` → SPA-nav to the certificate. The
  certificate page IS the confirmation (focus moves to it; a toast would
  not survive the designed navigation — the shell retires toasts on route
  change by design). The simulated/pre-verification acknowledgment gate
  stands unchanged and re-arms on any selection change.
- **Certificate view (`src/views/CertificateView.tsx`, route
  `/certifications/:id`, designs 5–8):** signature block FRONT AND CENTER
  (typed signer + title, timestamp, key fingerprint, collapsible raw
  signature), the SERVER's verification verdict rendered verbatim on load
  AND on the verify button's re-check — four verdicts, each honest:
  `verified` (success status), `failed` (loud alert, "SIGNATURE
  VERIFICATION FAILED." + the server's message verbatim), `key_mismatch`
  (warning voice — the server's "treat as UNVERIFIED, not proof of
  tampering" verbatim), `unsigned_legacy` (plain banner, the server's
  honest-history message verbatim; no verify button, nothing backfilled).
  The HONEST-SCOPE statement renders exactly as it was signed
  (`document.scope_statement`, never paraphrased); a signed record without
  one gets a loud absence statement, never a substitute. Covered figures
  come from the signed canonical document with their `receipt_sha256`
  hashes and lineage links; legacy records fall back to ids-only, stated.
  Statistician attestations recorded in the document are listed.
- **Attestations room (`src/views/AttestationsView.tsx`, route
  `/attestations`, nav entry for every signed-in role; design A):** the
  p. 146 rule VERBATIM (lead-in never stands alone), the behavior note,
  the hard-limits list with the p. 149 no-undersampling quote verbatim
  beneath it, the audited entry form (gated to certifying_official in UX —
  mirroring the backend's documented role choice; the API enforces it)
  with plain-language fields + the p. 150 statistician-qualifications
  quote verbatim in the statistician fieldset, fnmatch scope-pattern hint
  matching the router's own examples, disabled-with-reason submit, and
  the append-only record: every attestation listed, REVOKED ONES INCLUDED
  (labeled, with who/when/why — never hidden), plus a per-card revocation
  form (required reason, kept in the record and audit log; the note states
  revoking stops future runs only and deletes nothing).
- **Attested-figure receipt callout (`src/components/Receipt.tsx`,
  design 2):** a figure carrying `detail.attestation` renders a dedicated
  exception callout — the "Statistician-approved exception" tag (text +
  icon + a NEW violet exception color family, so a justified exception
  reads as neither a normal figure nor an error), the handoff's statement
  ("factored beyond the 2% threshold under a statistician-approved method
  — attestation #N"), the p. 146 quote verbatim with citation, the
  approving statistician and method verbatim from the figure's own
  permanent provenance, and the door to /attestations. The provenance
  never double-renders in the generic detail list; on non-receipt
  surfaces `detailLines` renders it as one plain sentence.
- **Public propagation (design 7):** `/public` cards render the
  certification block's key fingerprint when served (never any certifier
  identity), and the honest legacy line ("Certified before digital
  signatures existed in Headway — no signature fingerprint") for
  pre-signature certifications.
- **`attested` DQ closure vocabulary (migration 0029):** /dq labels the
  status, shows the closed issue's resolution story, offers no resolve
  form on it, and counts "open" as open+owned — exactly the API's
  certification rule (see the found-live bug below).
- **`quotes.json` regenerated** (backend deviation 6 closed):
  `npm run extract:quotes` → upt_v0 11 quotes / pmt_v0 22, including the
  p. 146 permission sentence, the p. 149 undersampling HARD LIMIT, and
  the p. 150 qualifications guidance under BOTH factor-up calcs; every
  snippet the new surfaces rely on is pinned by
  `src/test/quotes.test.ts`.

### The CertifyView stale-response fix (+ regression test)

The month-switch race is fixed with a load-sequence guard: every load
takes a ticket and a response only lands in state if no newer load started
since — a consent screen must never paint one month's figures under
another month's picker. Pinned by a regression test that hangs the first
month's response, switches months, lands the second month's figures, THEN
resolves the stale response and asserts it is discarded
(`src/test/certify.test.tsx`, "discards a stale month's late response").
The test harness's `mockApi` route handlers may now return promises so
response ORDER can be pinned.

### Contract reconciliation (mock-first → the real contract; none silent)

Built against typed mocks from this handoff's binding design while the
backend was in flight; reconciled against the backend's contract section +
the regenerated openapi.json the same day. Corrections made:
`signer_full_name` (not the mock's `signer_name`); the intent + scope
statements are SERVER text (`GET /certifications/intent`) — the mock's
bundle-owned intent statement was deleted; no `acknowledgments` array in
the POST (the signed document carries each figure's flags in its detail;
the ceremony's acknowledgment gate is UX); no per-figure `receipt_hash` on
GET /metrics/values (hashes exist only inside the signed document — the
ceremony states that); the certificate is record + raw signed bytes +
parsed `document` + a LIVE `verification` computed on every read (the
mock had a flat `scope_statement`); verification has four verdicts
including `key_mismatch` (the mock had a boolean); `detail.attestation`
is the calc's full provenance dict (the mock guessed flat
`attestation_id`/`attestation_method` keys); attestation ids are uuids
(the mock guessed serials); `AttestationCreated`/`AttestationRevoked` are
flat records; revocation carries `revoked_by`/`revocation_reason`, both
rendered.

### Found live, fixed, pinned

- **The cockpit blocked on ATTESTED issues.** The client-side blockers
  filter counted `status !== 'resolved'` as open, so the two
  blocking-severity issues closed to the new `attested` state (migration
  0029) kept the sign button off while the API would have allowed the
  certification — screen and server told different stories, caught
  because the first live signing attempt refused to arm. Fixed in
  CertifyView AND /dq (open = open|owned, matching the API's rule exactly)
  and pinned by tests in both suites ("treats an ATTESTED blocking issue
  as closed").

### Suites / gates (2026-07-15)

```
npm test -- --run        Test Files 28 passed (28); Tests 172 passed (172)
                         (was 26 files / 150 tests; +2 files — attestations,
                          certificate — and every new surface asserts zero
                          axe violations, ceremony and certificate included)
npx tsc -b && npm run build   clean (the >500 kB chunk warning pre-exists
                              at HEAD — verified by building HEAD in a
                              scratch worktree)
npm run lint             clean
npm run check:contrast   All 77 token pairs meet WCAG 2.1 AA (4 new:
                         the statistician-exception violet family —
                         tag text/icon on exception background and the
                         callout border, light + dark)
```

### Live click-through (2026-07-15, headless Chrome/CDP, SPA nav only;
screenshots `shots-0019/01…14*.png` in the session scratchpad)

Phase 1 — before the backend routes landed (mock-first honesty check):
the attestations room rendered the p. 146 rule + form with the API's
"Not Found" shown verbatim for the list [01]; the ceremony rendered real
July figures (70 consent checkboxes) with the covered list, the reason
line stating every cause — including the then-33 blocking issues — and
the certificate route showed its honest load error [02, 04–06].

Phase 2 — full loop against the live 0019 backend:

1. **UI attestation entry + revocation (both write paths):** recorded
   attestation `833293d1-b929-406f-a7d8-6a42b4c5855c` through the form
   (audit event 859; content clearly labeled "UI Click-Through Evidence
   (not a real approval)", scoped to the data-free period
   [2026-01-01, 2026-01-02) so it could never govern a real figure), then
   revoked it through the per-card form (reason recorded; the row stays
   visible, labeled Revoked) [07, 08]. The live list shows Dr. Rosa
   Field's standing attestations and the backend's revoked attack row —
   append-only history on screen.
2. **The attested receipt, live:** the pmt_v0 0.2.0 figure
   (`82f8c972…`, 221996.24 passenger miles, [2026-07-09, 2026-07-10))
   renders the exception callout — the handoff statement naming
   attestation #b4f5311e…, the p. 146 quote + citation, statistician and
   method verbatim [09].
3. **The ceremony on that real figure:** consent checkbox → the
   simulated + pre-verification warnings → explicit acknowledgment →
   typed "Alex Rivera, NTD Certifying Official" against the server's
   intent statement → armed [10] → signed. Certificate
   `a3f4c2f4-3700-488f-8dc7-cdc4ca90f196` rendered: signature block front
   and center, on-load verdict "Signature verified." with the server's
   message verbatim, fingerprint `ed25519:f0995b71…`, the honest-scope
   statement as signed, the covered figure with its `receipt_sha256`, and
   the Dr. Rosa Field attestation acknowledgment [11]. Verify button →
   second green verdict (re-checked on demand) [12].
4. **Post-reconciliation pass:** /public shows the voms certification's
   key fingerprint and the honest legacy line on pre-signature rows [13];
   /attestations shows the p. 149 + p. 150 quotes verbatim [14].

### Honest notes for the orchestrator

- **The live ceremony certified a SIMULATED figure.** The frontend loop
  deliberately exercised the full designed gate chain — including the
  simulated-data warning and explicit acknowledgment — on the attested
  PMT figure, so certification `a3f4c2f4…` permanently covers a
  simulated-source figure (its source_mix rides inside the signed
  document, and the /public row keeps its SIMULATED badge). The backend's
  deviation 4 took the opposite stance for its own evidence (certifying
  simulated data "would break the standing honesty rule") and certified
  the real voms figure instead. Both records now exist, append-only.
  OPEN QUESTION for NTD/Compliance: should POST /certifications
  structurally REFUSE simulated figures (fail loudly) instead of relying
  on the UI's acknowledged-consent gate? Today the API accepts them and
  only the cockpit warns. If the answer is refuse, the cockpit's
  simulated-acknowledgment path becomes dead code to remove — and the
  a3f4c2f4 record stands as honest history of the earlier rule.
- **`GET /certifications` (the list) has no UI room yet** — the
  certificate view is reached from the ceremony (and by URL). A
  certifications index (list → certificate) is a small follow-up.
- **`POST /dq/issues/{id}/attest` has no UI room yet** — the attested
  closure is displayed everywhere (status label, resolution story,
  correct open-counting) but entering one is API-only today, like the
  calc-knob settings flow before it. Recorded rather than papered over.
- **The public verify endpoint** (`GET /public/certifications/{id}/verify`)
  is not yet linked from /public — the fingerprint renders; a
  public-verify affordance is a small follow-up increment.
- The two heaviest new tests carry explicit 15 s vitest timeouts (the
  house precedent — they sat at the 5 s default's edge under full-suite
  load on this box).
