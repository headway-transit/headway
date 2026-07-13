# HANDOFF — Headway lead-contributor continuity document

This file is the front door for the next lead contributor — human or AI. It assumes **no
access to any prior working session**. Everything below is reconstructible from the repo
itself: the ~20-commit wave arc in `git log --oneline`, the role contracts in
`.claude/roles/`, the eleven ADRs in `docs/adr/`, the nine handoffs in `docs/handoffs/`
(each carrying live verification evidence), the per-service `README.md` verification
sections, and `services/calc/REGULATORY_TRACKER.md`. When this document and those sources
disagree, **the sources win** — update this file, never the evidence.

---

## 1. What this is

Headway is an open-source (Apache-2.0) Autonomous Transit Data Platform: it ingests a
transit agency's operational telemetry (GTFS static, GTFS-Realtime, TIDES passenger
events today; the full source fleet in `.claude/roles/INGESTION_ENGINEER.md` eventually),
normalizes it into one open canonical model, and computes the figures agencies report to
the FTA's National Transit Database — Vehicle Revenue Miles and Hours, Unlinked Passenger
Trips, Vehicles Operated in Maximum Service — with the anchor requirement that an
unexplained gap in Headway becomes a finding in an FTA triennial review. The stakes
standard governs every decision (`.claude/roles/_SHARED_CONSTRAINTS.md`).

The thesis is **radical provenance**: every number can prove itself. Every reported
figure originates only in the deterministic, versioned, unit-tested calculation library
(`services/calc/` — the *only* writer of `computed.metric_values`), carries the verbatim,
page-cited federal-manual quote it implements (extracted from
`services/calc/REGULATORY_TRACKER.md` into the UI, never paraphrased), and can be walked
through an explicit lineage graph (`lineage.edges`, ADR-0007) back to content-addressed
immutable raw records. Gaps are never papered over: calculations *refuse* to emit a
certifiable figure over an unresolved gap, every exclusion becomes an owned `dq.issues`
row, simulated data is permanently distinguishable in provenance, and certification is
informed consent mechanized — the signing screen shows exactly what a signature covers
and will not arm while blocking issues are open. AI assists (anomaly flags, grounded
explanations) but **AI never computes a reported number** — enforced by types and a CI
grounding regression gate (`services/ai/`), not by policy prose.

The same thesis governs how the project is *built*. Specialized role sessions
(`.claude/roles/`) work under eight non-negotiable shared constraints; cross-role work
moves only through written handoff documents with verification evidence
(`docs/handoffs/`); architecture changes only through ADRs (`docs/adr/`); no regulatory
number ever enters code from memory — only as a tracker row quoting a published source
(`services/calc/REGULATORY_TRACKER.md`). And no completion claim is made by inference:
**verification before assertion**, with live evidence. The repo's own history (section 6)
shows why that rule is load-bearing.

---

## 2. Architecture map

```mermaid
flowchart LR
    subgraph SRC[Sources]
        G1[GTFS static zip]
        G2[GTFS-RT feeds]
        T1[TIDES passenger_events CSV<br/>file drop or HTTPS push]
    end

    subgraph ING[Ingestion — Go<br/>services/ingestion]
        C1[connectors: gtfsrt / gtfsstatic / tides<br/>immutable raw bytes, sha-256 record_id]
    end

    OBJ[(MinIO<br/>raw payload objects)]
    K[(Kafka KRaft<br/>topics per contracts/topics.v0.md<br/>envelope: contracts/raw-record-envelope.v0.schema.json)]

    subgraph TR[Transform — Python<br/>services/transform]
        N1[normalizers + DQ quarantine<br/>one lineage edge per canonical row]
    end

    subgraph DB[(TimescaleDB — one database per agency, ADR-0004)]
        R[raw.records]
        CA[canonical.*]
        L[lineage.edges]
        CO[computed.metric_values]
        DQ[dq.issues]
        AU[audit.events / cert.* / auth.* / app.settings]
    end

    CALC[Calc library — Python<br/>services/calc: vrm/vrh/upt/voms,<br/>runner, mr20 package generator<br/>THE ONLY WRITER of computed figures]

    subgraph API[API — FastAPI<br/>services/api]
        H[human endpoints: auth, metrics,<br/>lineage, DQ, settings, certify, branding]
        M[machine API: hwk_ service keys,<br/>POST /ingest/tides/passenger-events,<br/>GET /machine/metrics, webhooks]
        P[public open data:<br/>GET /public/metrics/certified]
    end

    WEB[Web — React/TS<br/>web/: Receipt, lineage walk,<br/>dashboards, certification cockpit]

    AI[AI harness — services/ai<br/>grounding gate FIRST, then detectors —<br/>writes only dq.issues flags]

    DS[design-sync<br/>.design-sync + .ds-sync → ds-bundle/]

    SRC --> C1
    C1 -->|object_ref payloads| OBJ
    C1 -->|enveloped records| K
    M -->|store-before-produce| OBJ
    M --> K
    K --> N1
    OBJ --> N1
    N1 --> R & CA & L & DQ
    CA --> CALC
    CALC --> CO & L & DQ
    DB --> H
    DB --> AI
    AI --> DQ
    H --> WEB
    P --> WEB
    WEB -.component sync.- DS
```

Layer contracts: wire = `contracts/raw-record-envelope.v0.schema.json` +
`contracts/topics.v0.md` (ADR-0006); schema = handoff
`docs/handoffs/0001-from-platform-architect-to-all-canonical-schema-v0.md` plus
migrations `db/migrations/0001…0016`; language policy = ADR-0008 (Go ingestion, Python
calc/transform/API/AI, TypeScript web).

---

## 3. How to run everything

### 3.1 Guided install (one Linux box)

```sh
./install/install.sh --check     # dry run: checks Docker/ports/memory/disk, changes nothing
./install/install.sh             # guided install (see install/README.md)
./install/install.sh --yes       # unattended: HEADWAY_AGENCY_ID, HEADWAY_ADMIN_USERNAME,
                                 # HEADWAY_ADMIN_PASSWORD (+ optional feed URLs) from env
./install/uninstall.sh           # three separately confirmed removal stages
```

Everything is logged to `install/install.log` (never passwords). The installer creates
`deploy/compose/.env`, boots the stack, applies migrations via a throwaway container, and
creates one `certifying_official` account. **Note the standing pending in section 5: a
full fresh-box run of this installer has never been executed end to end.**

### 3.2 Compose stack directly

```sh
cd deploy/compose
cp .env.example .env             # set the required passwords
docker compose up -d                       # infrastructure: kafka, timescaledb, apicurio,
                                           # minio, prometheus, grafana + bootstrap containers
docker compose --profile app up -d --build # + ingestion, transform, api, web
docker compose ps                          # every long-running service must be healthy;
                                           # bootstrap-kafka / bootstrap-minio exit 0 (healthy state)
```

Host ports (all 127.0.0.1 only): API 8000, web 8080, Grafana 3000, Postgres 5432, Kafka
dev listener 29092, Apicurio 8081, MinIO 9000/9001, Prometheus 9090. Details:
`deploy/compose/README.md`.

Migrations by hand (either connection style — see `db/README.md`; URL credentials must be
percent-encoded, the 2026-07-09 live finding):

```sh
PGHOST=127.0.0.1 PGUSER=... PGPASSWORD=... PGDATABASE=... python3 db/migrate.py
```

### 3.3 Every test suite (real commands)

```sh
# Go ingestion
cd services/ingestion && go build ./... && go vet ./... && go test ./... -count=1

# Python services (each has a [test] extra; see .github/workflows/ci.yml)
cd services/calc      && python3 -m pytest tests/ -q      # 245 passed at last recorded run
cd services/api       && python3 -m pytest tests/ -q      # 136 passed at last recorded run
cd services/transform && python3 -m pytest tests/ -q      # 49 passed at last recorded run
cd services/ai        && python3 -m pytest tests/ -q && python3 -m headway_ai.regression
                                                           # regression = the CI grounding gate

# DB migrations, static checks
cd db && python3 -m pytest test_migrations_static.py -q   # 15 passed at last recorded run

# API integration against a REAL PostgreSQL/TimescaleDB (the autocommit-bug guard;
# skips cleanly when the env var is unset — see tests/integration/README.md)
docker run --rm -d -p 5432:5432 -e POSTGRES_PASSWORD=throwaway timescale/timescaledb:latest-pg16
export HEADWAY_IT_ADMIN_URL='postgres://postgres:throwaway@127.0.0.1:5432/postgres'
python -m pytest tests/integration -q

# Web
cd web && npm install && npm run lint && npm run build && npm test -- --run
npm run check:contrast     # WCAG gate over every color token pair
npm run extract:quotes     # regenerate src/regulatory/quotes.json from the tracker

# License gate (ADR-0001) and local SBOM+scan
python3 scripts/license_gate.py            # see scripts/license_allowlist.toml
scripts/sbom_local.sh                      # release threshold (>= high); FAIL_ON=critical for the CI push gate
```

### 3.4 Running the pipeline pieces

```sh
# API (local)
export HEADWAY_SESSION_SECRET=<random 32+ bytes>
export HEADWAY_DATABASE_URL=postgresql://.../agency_db
cd services/api && uvicorn "headway_api.app:create_app" --factory

# Web dev server against it
cd web && VITE_API_BASE_URL=http://localhost:8000 npm run dev   # http://localhost:5173

# Calc run (thresholds: explicit flag > app.settings row > code default)
export HEADWAY_DATABASE_URL=postgresql://.../agency_db
python -m headway_calc.runner --period-start 2026-07-01 --period-end 2026-08-01 [--per-mode]
python -m headway_calc.mr20 --month 2026-07 [--run]    # NOT-REPORTABLE MR-20 preview package
python -m headway_calc.ss50 --month 2026-07             # S&S-50 monthly summary (incl. zero-event rows)
python -m headway_calc.ss50 --ss40-event <event-id>     # S&S-40 detail export for one major event

# AI anomaly detection (writes only dq.issues flags)
PGHOST=... PGDATABASE=... PGUSER=... PGPASSWORD=... python3 -m headway_ai.anomaly_runner

# TIDES simulator (SIMULATED data — MUST run the connector with TIDES_SOURCE=tides_simulated)
# see tools/tides-simulator/README.md
# Canonical replacement (rows + lineage edges in ONE transaction; dry-run by default)
# see tools/canonical-replace/README.md
```

**Demo users on the current dev box's live Compose database** (created during the wave
verification runs; NOT seeded by anything in this repo — a fresh install has only the
admin account the installer creates): `dsteward` (data_steward) and `certifier`
(certifying_official), password pattern `demo-<username>-2026`. If your database lacks
them, create accounts the same way `install/install.sh` does (bcrypt hash into
`auth.users`).

### 3.5 Design-system re-sync

Per `.design-sync/NOTES.md` (read it first — it lists the hand-maintained
`dtsPropsFor` contracts, known render warns, and re-sync risks). Prereq on a fresh clone:

```sh
ln -sfn .. web/node_modules/web    # gitignored self-symlink the converter needs
node .ds-sync/resync.mjs --config .design-sync/config.json \
     --node-modules web/node_modules --out ./ds-bundle
```

The bundle in `ds-bundle/` (tokens, components, guidelines) is what design work consumes;
`.design-sync/conventions.md` carries the five non-negotiable Headway design rules
(verbatim figure strings, SimulatedBadge, severity never color-alone, validated chart
tokens only, provenance path on every figure).

### 3.6 Release / tag flow

Per `.github/workflows/release.yml`: push a tag matching `v*.*.*`. The pipeline then, per
image (`headway-{ingestion,api,transform,ai,web}` → `ghcr.io/headway-transit/...`):
builds → Syft SBOMs (CycloneDX **and** SPDX, source tree and every image) → **Grype gate
at severity ≥ high, before push** (nothing failing the gate reaches the registry; CI
pushes/PRs gate at critical in `ci.yml` — changing either threshold is a Security-role
decision) → push → Cosign keyless sign + CycloneDX attestation on the immutable digest →
`gh release create` with all SBOMs attached. Verification command and expected OIDC
identity: `docs/supply-chain.md`. `scripts/sbom_local.sh` reproduces the SBOM+scan half
locally. Governance rule (`GOVERNANCE.md`): no unsigned or unscanned artifact is ever
published as a release.

---

## 4. The governance system — and how to work IN it

Read, in order: `.claude/roles/_SHARED_CONSTRAINTS.md` (binding on everyone), then
`.claude/roles/README.md`, then `GOVERNANCE.md`.

1. **Assume a role.** Start a session with: *"Assume the role defined in
   `.claude/roles/{FILE}` and its shared constraints."* Twelve roles exist (Platform
   Architect, Ingestion, Data, NTD & Compliance, AI Systems, Backend, Frontend, DevOps,
   Security, QA, Docs, Community Maintainer). A role file is a governing contract:
   ownership, handoff partners, definition of done, guardrails, first-90-days plan.
   Where a role file conflicts with the shared constraints, the shared constraints win.

2. **The two rules that override everything:** (a) AI never computes a reported number;
   (b) verification before assertion — no completion claim without live evidence.

3. **Cross-role work moves only through handoff documents** —
   `docs/handoffs/NNNN-from-<role>-to-<role>-<slug>.md` with exactly: Context, Inputs,
   Outputs, Open Questions, Verification Evidence. The receiver appends `## Response`.
   Interface changes after a handoff require a **new** handoff (or a dated note/response
   appended — see handoff 0006's "Contract change" section for the pattern), never an
   edit-in-place. Next handoff number: **0010**.

4. **Architecture changes go through ADRs** (`docs/adr/`, MADR format, owned by the
   Platform Architect; eleven ratified — license, Kafka, TIDES-hybrid model, DB-per-agency,
   Compose+Helm parity, connector contract, lineage graph, polyglot layers, walking
   skeleton, monorepo+contracts, native OIDC). Never silently contradict an accepted ADR.
   Per `GOVERNANCE.md`, substantial new directions open as an ADR PR labeled `rfc`, held
   ≥ 14 days. The eight shared constraints are constitutional: changing them takes a
   public ADR with **unanimous** maintainer approval.

5. **Never a regulatory number from memory.** Every FTA definition, threshold, or
   convention enters code only as a `services/calc/REGULATORY_TRACKER.md` row quoting the
   published source with page citation and verification date. Changing calculation logic
   mints a NEW calc version and a new tracker row; shipped versions are never deleted or
   rewritten (0.1.0 through current are all still runnable). Engineering placeholders are
   labeled as such (e.g. `coverage_threshold` 0.95) and distinguished from real FTA
   numbers (e.g. `missing_trip_threshold` 0.02, manual p. 146).

6. **Anti-capture (`GOVERNANCE.md`):** no single organization may hold exclusive merge
   rights, release keys, or a roadmap veto; cloud offerings are packaging, not privilege;
   connector certification is earned by conformance against `contracts/`, never by
   payment. Currently a single founding maintainer — growing that number is the first
   order of governance business.

---

## 5. State: live-verified vs standing pendings

Mined from the service READMEs' verification sections and the handoffs' evidence. The
service READMEs are the honest source of record — re-check them before relying on this
table.

| Area | Live-verified (evidence pointer) | Standing pendings (source) |
| --- | --- | --- |
| Compose stack | Cold boot, 6/6 healthchecks green; bootstrap containers close the manual topic/bucket gap (`deploy/compose/README.md`; handoff 0001, 2026-07-09) | — |
| DB migrations | **0001–0026 all applied** to the live TimescaleDB (psql-listed 2026-07-12); runner idempotent; immutability proven by attack, incl. safety.events + sampling.* append-only triggers (handoffs 0001/0002/0005/0006/0010/0012) | — |
| Ingestion (Go) | Suites/build/vet green; live GTFS-RT + GTFS-static run against MBTA feeds, content addressing proven across restart, image built and run (handoff 0001, 2026-07-09; handoff 0005 TIDES connector live) | Apicurio schema registration; replay-from-raw-store proof; backpressure/at-least-once demo under a slow consumer (`services/ingestion/README.md`) |
| Transform | 49 tests; live Kafka→TimescaleDB normalization at scale (172k lineage edges wave 3; 185k+ passenger events wave 7); migrations 0011/0012 applied live (handoffs 0001/0003/0005) | README's live-verification items are closed by the orchestrator evidence above; keep the replay-fixture habit for new normalizers (`services/transform/README.md`) |
| Calc | 496 tests incl. goldens with hand-worked BASIS.md + Hypothesis properties; live runs produced the first persisted, certified figures (VRM 12,794.92 mi / VRH 1,260.85 h, handoff 0002) and the three-way v0.2/v0.3/v0.4 comparison (handoff 0004); `sscls_v0` 0.1.1 golden-tested against the S&S manual's own Examples 4/6/7, zero skips (handoff 0010) | Live per-mode + voms + MR-20 package run against MBTA data; reportability gated on D2–D6 + `coverage_threshold` verification (`services/calc/README.md` "What is PENDING"; tracker) |
| API | 202 tests; certification/DQ/lineage flow live end-to-end incl. psql-verified rows (handoff 0002); machine key → HTTPS ingest → canonical row live; public endpoint live (handoff 0006 orchestrator section); /safety endpoints live with psql-verified writes + audit rows (handoff 0010) | Full suite against live PostgreSQL/MinIO/Kafka with migrations 0001–0016 applied (`services/api/README.md` PENDING); webhook delivery to a live external receiver never exercised (fakes only); `dq.issue.created` cannot be offered without an outbox (README "HONEST SCOPE") |
| Web | `npm run build` clean, 128 tests + axe green, contrast pairs pass; **live end-to-end click-through captured** (headless Chrome through real login → /safety entry → receipt → supersede → deadlines, handoff 0010 frontend evidence) | — |
| Ops analytics (new, handoff 0014) | The platform measures its namesake: canonical trip_updates (2.53M prediction rows live-replayed, idempotent), stop-passage derivation with measured-cadence tolerances (2.24M gaps measured; 156k passages refused, counted), otp_v0 + headway_adherence_v0 with TCQSM quotes verified from TRB's public PDF (OPS_DEFINITIONS.md); live MBTA figures: agency OTP 54.10%, cvh 0.3010, 172 route rows; the ops/NTD honesty boundary is a DB CHECK (certified ops row unrepresentable — proven by live attack) and ops findings never gate certification | GTFS-RT trip_update poller DISABLED pending a retention policy (~1.1 GB/hr normalized; Platform Architect decision needed — likely Timescale retention on the hypertable); prediction-accuracy metrics (v1); cvh interpretation bands deliberately not invented |
| Demand Response (new, handoff 0013) | Second data-source family live end to end: dr wire contract + Go file-drop connector + machine push (`ingest:dr` scope) + dr-simulator → canonical.dr_trips (95 rows, 2 injected defects quarantined) → five dr calcs (Exhibit 36 goldens row-by-row incl. no-show-is-revenue, TX onboard-only, DR VOMS atypical-INCLUSION) → 20 simulated figures persisted + served with TOS-badged receipts (live TX receipt render verified) | Real vendor adapters (Via export sample needed); GTFS-Flex (D5); DR ops analytics; `raw.dr.trips` topic needs Platform Architect ratification (handoff 0013 Response); passenger_events stop_id increment for rail PMT still open |
| PMT + sampling (new, handoffs 0011/0012) | Geometry pipeline live (10,309 stops / 3.08M stop_times, 0 DQ); pmt_v0 live-verified via an HONEST REFUSE (36.6% missing/invalid vs the 2% line, 6 blocking + 6,494 owned exclusions, psql-confirmed 0 pmt rows); sampling_v0 full walkthrough live (plan→draws→50 measurements→APTL 3.80→950,000 est. PMT, kept out of computed.metric_values) | TIDES ordinal stop-sequence gap blocks rail PMT (needs passenger_events stop_id — folded into DR wave); human live click-through of /sampling pending (handoff 0012 frontend evidence caveat); grouped-APTL + Base-option estimation deferred |
| Safety & Security (new, handoff 0010) | Manual event entry → `sscls_v0` 0.1.1 classification → S&S-50 generator → deadlines, all live-verified end to end incl. the p. 22 single-injury non-major case and migration 0017/0018 proven by attack; every UI receipt token maps to a verbatim manual quote + page cite | v1: full S&S-40 form field walk (manual pp. 20–40), submission-status tracking, hazmat/act-of-God vocabulary, batch re-classification tooling, CAD/incident connector (handoff 0010 Open Questions) |
| AI | Unit suite + grounding regression gate green; fixtures pin pass AND fail directions (`services/ai/README.md`) | OllamaProvider never live-verified; anomaly runner never executed against a live DB; real-DB citation checks via fakes only (`services/ai/README.md` "Verification status (honest)") |
| Installer | Pre-check phase exercised live — correctly diagnosed docker-group and port conflicts (`install/install.log`) | **Full fresh-box guided install never completed end to end** (`install/install.log` shows two `--check` runs and two guided runs that stopped at the pre-checks on an already-occupied box) |
| Helm / parity gate | — | Stubs only: `deploy/helm/README.md`, `scripts/parity_gate.md` ("not implemented. Nothing here runs yet") |
| Design system | Bundle synced; previews verified (a real yTop-clamp bug found by preview verification, fixed in source) | Hand-maintained `dtsPropsFor` must track component API changes; known Modal capture-sheet warn accepted (`.design-sync/NOTES.md`) |
| Release pipeline | Workflow authored, actions pinned to patched versions (commit f5f8b55 unblocked the gate) | Whether a tag has shipped is not recorded in-repo — check GitHub releases before assuming |

---

## 6. Operating norms — with the receipts

These are the norms every session works under, each taught by something that actually
happened in this repo:

1. **Live verification catches what unit fakes cannot — the autocommit phantom-write
   bug.** (Handoff 0002, Verification Evidence.) The API returned `201 Created` for a
   certification while **zero rows reached disk**: psycopg3's default
   `autocommit=False` opened an implicit transaction nothing committed, so every router
   `transaction()` block nested as a savepoint. The unit-test fake had masked it; a real
   database observed from a *separate* connection caught it. The fix (`autocommit=True`
   in the lifespan + `services/api/tests/test_transaction_discipline.py` with a fake that
   honestly models psycopg3 nesting) is now permanently guarded by
   `tests/integration/` — a real-PostgreSQL suite that exists specifically as "the
   standing protection for the 2026-07-10 autocommit bug class"
   (`tests/integration/README.md`). Norm: **a green unit suite is necessary, never
   sufficient; every increment ends with the live stack exercised and evidence pasted.**

2. **Live data finds design bugs specs cannot — the simulator JOIN defect and the
   stale-lineage incident.** (Handoff 0005, Verification Evidence;
   `tools/canonical-replace/README.md`.) The first live UPT runs refused at missing-trip
   shares of 19–30% — and that refusal itself exposed a simulator defect (its JOIN to
   `canonical.trips` hid MBTA's RT-only ADDED trips from the operated denominator). The
   cleanup then caused a second incident: deleting canonical rows without their lineage
   edges left ~92k edges pointing at nothing — silent lineage-graph corruption. The
   response was structural, not procedural: `tools/canonical-replace` deletes rows and
   edges in one transaction or not at all. Norm: **when a mistake is possible, make it
   structurally impossible; fail-loudly is a feature that finds other bugs.**

3. **Honest pendings are part of done.** Every service README carries a verification
   section that says exactly what ran (with output) and what is PENDING. Work that could
   not be verified live says so explicitly (see the "fakes only — live stack untouched"
   pattern throughout the handoffs). Never delete a pending without attaching the
   evidence that closes it.

4. **Documented limitations over silent gaps.** The API refuses to pretend a
   `dq.issue.created` webhook exists (it has no post-commit moment for rows other
   services write — `services/api/README.md` "HONEST SCOPE"); migration 0014 shipped with
   an EXPLICIT LIMITATION paragraph until the runner-reads-settings increment landed, and
   the paragraph *stands unedited as history* with a dated superseding note (handoff
   0002). Deviations from a handoff's letter are reported in the Response, never silently
   absorbed (handoff 0006's Response lists three).

5. **Numbers are sacred everywhere.** Decimal/NUMERIC end to end; values are strings in
   JSON and in the UI (`web/README.md` non-negotiables); the AI layer's fabrication check
   compares normalized Decimal strings; policy knobs parse via `Decimal`, never float.

6. **Plain language and accessibility are constraints, not polish** — WCAG 2.1 AA gated
   in CI (`npm run check:contrast`, axe in every view test), server-side contrast
   refusal for agency brand colors, and every error message written for a transit
   operations manager.

---

## 7. Contacts and support

- **Questions / discussion:** GitHub Discussions —
  https://github.com/headway-transit/headway/discussions
- **Bugs:** GitHub Issues — https://github.com/headway-transit/headway/issues (include
  record_ids or DQ issue ids, never raw rider data)
- **Security reports:** private reporting per `SECURITY.md`
- **Commercial support, deployment assistance, agency onboarding:** **Bekus Solutions —
  support@bekus.co** (`SUPPORT.md`). Per `GOVERNANCE.md`, commercial support is a service
  around the open platform — it purchases **no privilege** over the project: every
  commercially supported capability is the same Apache-2.0 code every agency runs for
  free, and the roadmap is governed in the open.

Next steps for a new lead: read `ROADMAP.md` (triaged from the repo's own breadcrumbs),
pick the wave, assume the role that owns it, and open a handoff.
