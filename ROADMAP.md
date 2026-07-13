# Headway Roadmap

Triaged entirely from the repo's own breadcrumbs: handoff Open Questions
(`docs/handoffs/`), tracker open items (`services/calc/REGULATORY_TRACKER.md`), service
README pending sections, and the role files' ownership scopes (`.claude/roles/`). Each
item is one line plus the source that demands it. The roadmap is governed in the open
(`GOVERNANCE.md`); substantial new directions open as an RFC-labeled ADR PR.

## Now (next ~3 waves)

- **Fresh-box installer test** — run `./install/install.sh` end to end on a clean
  machine and capture evidence; every logged attempt so far stopped at the pre-checks.
  *(install/install.log; HANDOFF.md state table)*
- **Close the standing live-verification pendings**: API suite against the live stack
  with migrations 0014–0016 applied; web click-through with captured evidence; AI
  `anomaly_runner` against the live DB; calc `--per-mode` + voms + MR-20 package run on
  MBTA data. *(services/api/README.md, web/README.md, services/ai/README.md,
  services/calc/README.md — each "PENDING" section)*
- **Live webhook receiver** — exercise `certification.created` / `dq.issue.resolved`
  delivery against a real external receiver (HMAC verified only in fakes so far).
  *(docs/handoffs/0006; services/api/README.md)*
- **`dq.issue.created` outbox dispatcher** — outbox table (or DB trigger) drained by a
  dispatcher, so ticketing sync stops depending on polling. *(services/api/README.md
  "HONEST SCOPE"; handoff 0006 contract-change note)*
- **Per-mode reportability path — bus-VRM first** — the nearest reportable target is
  bus-mode VRM (D1 negligible for miles, D2 bus-exempt), pending D3 per-agency
  confirmation and D4 fidelity validation; then work D2–D6 closure in order.
  *(REGULATORY_TRACKER.md "Reportability position" + Divergence analysis)*

## Next

- **APC certification workflow support** — the pp. 147–148 FTA approval/benchmarking
  workflow (±5% vs manual counts, discard rate < 50%, next benchmarking RY 2028) that
  must exist before any APC-derived UPT is reportable. *(REGULATORY_TRACKER.md, upt_v0
  reportability gates)*
- **Statistical anomaly baselines** — robust z-scores/MAD and seasonal decomposition once
  >30 days of computed history exist; replace the engineering-default thresholds.
  *(services/ai/README.md; .claude/roles/AI_SYSTEMS_ENGINEER.md)*
- **Anomaly thresholds via `app.settings`** — per-agency configuration of
  `swing_threshold` / `coverage_drop_threshold` through the audited settings surface.
  *(services/ai/README.md "Thresholds are ENGINEERING DEFAULTS"; migration-0014 pattern)*
- **`coverage_threshold` verification** — verify FTA completeness/sampling expectations
  before the 0.95 placeholder is treated as more than engineering policy.
  *(REGULATORY_TRACKER.md open items; handoff 0002)*
- **Native OIDC relying party** — authorization-code + PKCE producing the existing
  `{sub, username, role}` claim set; Keycloak profile only for SAML-only IdPs.
  *(services/api/README.md "Auth model"; docs/adr/0011)*
- **Lineage-scoped blocking for certification** — replace the global blocking-DQ check
  (deliberate v0 over-refusal). *(services/api/README.md "v0 simplifications")*
- **Webhook-secret encryption at rest + timestamp-bound signatures** — the
  secrets-management increment; v0 stores the HMAC secret plaintext with a documented
  compensating control and signs body-only. *(handoff 0006 Open Questions;
  services/api/README.md)*
- **Helm chart completion + CI parity gate** — charts deploying identical image digests,
  one config schema, parity proven by booting both stacks in CI.
  *(deploy/helm/README.md stub; scripts/parity_gate.md stub; docs/adr/0005)*
- **CAD/AVL connector + first pluggable vendor APC adapter** — the next sources in the
  ingestion fleet; the APC adapter is the template for farebox/EV/maintenance/DRT.
  *(.claude/roles/INGESTION_ENGINEER.md Ownership + First 90 Days items 7–8)*
- **WE-20 weekly module** — reference-week weekday UPT + VRM for sampled agencies, due
  seven business days after the reference week. *(REGULATORY_TRACKER.md "Bonus — WE-20",
  manual p. 34)*
- **MR-20 e-file/export** — emit a submission-formatted artifact once the FTA portal's
  accepted format is verified against published guidance (never from memory); today's
  generator is an explicit NOT-REPORTABLE preview. *(services/calc/headway_calc/mr20.py
  banner; handoff 0009; _SHARED_CONSTRAINTS.md "Regulatory facts are pointers")*
- **Installer `--upgrade`** — in-place upgrade path; today the installer refuses to
  touch an existing installation. *(install/README.md "If the installer stops")*
- **VOMS atypical-day exclusion** — needs an agency calendar policy rule before the
  p. 33 exclusion is implementable. *(handoff 0009 Open Questions; REGULATORY_TRACKER.md
  voms_v0 divergence (b))*

## Later

- **Native database / data-lake connectors** — SQL Server, Oracle, Snowflake, etc.;
  today's supported path is the documented CSV export + drop/push, and no commitment
  exists yet. *(docs/connecting-your-data.md §4)*
- **Remaining source fleet** — J1939/telematics (verify every PGN/SPN against the SAE
  Digital Annex), farebox/AFC, EV charging + SoC (OCPP where it applies),
  paratransit/DRT, maintenance management, validated manual entry.
  *(.claude/roles/INGESTION_ENGINEER.md Ownership + Domain Knowledge)*
- **PMT + FTA statistical sampling** — pluggable sampling paths with precision/confidence
  as verified inputs per FTA Circular 2710.x and current NTD sampling guidance.
  *(.claude/roles/NTD_COMPLIANCE_ENGINEER.md items 4/83)*
- **D2 rail passenger-car measure** — needs consist data absent from GTFS-RT; rail modes
  stay non-reportable until a consist/AVL source lands. *(REGULATORY_TRACKER.md D2)*
- **D5 demand-response calc** — DR revenue time is a different rule (first pick-up →
  last drop-off); its own future calc version. *(REGULATORY_TRACKER.md D5)*
- **Per-mode dark-brand variants / dark theme** — one stored brand color cannot pass AA
  against both light and dark surfaces (math in `headway_api/branding.py`); dark mode
  needs per-mode variants validated against their own surfaces. *(handoff 0008 Response
  point 3; services/api/README.md branding notes)*
- **Distributed rate limiting** — the hosted multi-instance increment; v0 is an
  in-process per-key/per-IP token bucket. *(handoff 0006 Open Questions;
  services/api/README.md)*
- **Hosted multi-tenancy routing** — per-request tenant→database routing on the
  existing `app.state.db` seam (one DB per agency stands, ADR-0004).
  *(services/api/README.md "v0 simplifications")*
- **Docs site** — self-hosted, WCAG 2.1 AA, built/served from the same commodity stack.
  *(.claude/roles/DOCS_ENGINEER.md; docs/adr/0010 layout)*
- **i18n** — copy is already externalized in `web/src/copy.ts`; no framework wired yet.
  *(web/README.md)*
- **httpOnly cookie sessions** — remove the bearer token from JS reach entirely.
  *(web/README.md "Sessions")*
- **Connector certification program mechanics** — public conformance results + revocable
  badge against `contracts/`; certification by conformance, never payment.
  *(GOVERNANCE.md; .claude/roles/COMMUNITY_MAINTAINER.md)*
- **Ingestion runtime hardening** — connector-runtime base image, checkpointing,
  backpressure tuning, GTFS-static re-poll, directory watcher for TIDES drops, DQ-issue
  emission at the ingest boundary. *(services/ingestion/README.md "Deliberately out of
  scope")*

## Research

- **Partial retention of an excised trip's layover intervals** when the gap is provably
  outside layover-adjacent running segments — conservative both-sides drop stands for
  vrh 0.4.0. *(handoff 0004 Open Questions; REGULATORY_TRACKER.md)*
- **Auto-resolving excluded-group warnings** when a later replay fills the telemetry gap.
  *(handoff 0002 Open Questions, owner Data Engineer)*
- **Null-trip positions inside a block's span** — attribute to the block? (v0.4 ignores
  them, conservative.) *(handoff 0003 Open Questions)*
- **Trip-distance authority** — shape-based vs position-derived haversine; D4 fidelity
  validation against odometer/shape distance. *(handoff 0001 Open Questions;
  REGULATORY_TRACKER.md D4)*
- **VOMS "maximum service requirement" semantics** — schedule-peak simultaneity vs the
  day-level distinct-vehicle upper-bound proxy. *(REGULATORY_TRACKER.md voms_v0
  divergence (a))*
- **Factor-up dimension** — per-mode vs per-TOS totals for the p. 146 rule beyond the
  current per-mode path. *(handoff 0005 Open Questions; tracker "Mode scoping")*
- **Charting library adoption** for future dashboards (hand-rolled SVG serves today;
  any addition must be permissive-licensed). *(handoff 0007 Open Questions)*

## Research-informed (from the 2026-07 feature-gap sweep)

The full ranked analysis with sources: [`docs/research/feature-gap-report-2026-07.md`](docs/research/feature-gap-report-2026-07.md). Highlights that reorder priorities:
- ~~**PMT + FTA Sampling Manual support** (report #1)~~ — **shipped 2026-07-12 (v0, handoffs 0011 + 0012)**: canonical stops/stop_times geometry (migration 0019, 3.08M rows live), `pmt_v0` load-profile calc with Exhibit 44 estimator (live result: an HONEST REFUSE at 36.6% missing/invalid vs the 2% line — receipts served), and `sampling_v0` (Tables 43.01–43.07 verbatim, §83 APTL estimator with the ratio-of-totals rule structurally enforced, seeded without-replacement drawer, /sampling UI). Known gap: TIDES `trip_stop_sequence` is ordinal, not GTFS `stop_sequence` — rail events unplaceable until canonical.passenger_events carries stop_id (folded into the DR wave's canonical work; handoff 0011 open question).
- **APC certification/benchmarking workbook** — manual-vs-APC variance, discard rates, statistician sign-off; natural extension of the certification cockpit (report #2).
- **GTFS feed NTD-compliance validation** — RY2025/26 makes the feed a CEO-certified artifact; embed the MobilityData canonical validator (report #4).
- ~~**Safety & Security module incl. new cybersecurity event reporting** (report #3)~~ — **shipped 2026-07-12 (v0, handoff 0010)**: manual event entry with validation, `sscls_v0` threshold classifier (Exhibit 5, golden-tested against the manual's own Examples 4/6/7, incl. the Scenario G cyber event), S&S-50 monthly generator, S&S-40/50 deadline tracking, `/safety` UI. v1 remainders live in handoff 0010's Open Questions (full S&S-40 form field walk, submission tracking, hazmat/act-of-God vocabulary, CAD connector).
- **Demand Response / on-demand module — shipped 2026-07-13 (v0, handoff 0013)**: vendor-neutral `demand_response_trip` wire contract (Via-style mapping example in contracts/), file-drop + machine-push intake, dr-simulator, canonical.dr_trips (migration 0021), five DR calcs with Exhibit 36/38/40 goldens (no-show-is-revenue, TX onboard-only, VOMS atypical-inclusion), TOS-badged receipts. The DR revenue-time half of D5 is closed; GTFS-Flex remains.
- **Divergence closers the ecosystem is building toward**: TIDES v2 consists table → D2; Cal-ITP TODS connector → D3/D6; GTFS-Flex (+ ~~DR revenue-time calc~~ shipped, see above) → D5 (reports #9, #5, #10).
- ~~**Ops analytics from data already held** (report #8)~~ — **shipped 2026-07-13 (v0, handoff 0014)**: canonical trip_updates, measured-cadence stop-passage derivation, otp_v0 + headway_adherence_v0 (TCQSM-quoted), ops/NTD boundary enforced by DB CHECK, dashboard cards + ops-badged receipts. OPEN: trip_update poller disabled pending a retention policy (~1.1 GB/hr normalized — Platform Architect); prediction-accuracy metrics are the natural v1.
- **Vendor adapter framework** (NEW, handoff 0015 authored 2026-07-13): declarative mapping specs from vendor exports (Trapeze/TripSpark Streets first — a partner agency's flow: MDT manual counts → TripSpark → storage-server push) onto the open contracts (TIDES passenger_events, demand_response_trip); adapter registry + validation harness + conformance fixtures. TripSpark mapping BLOCKED on a real sample export (field semantics never from memory).
- Distroless runtime bases for the Python images (api/transform/ai) — removes the won't-fix Debian CVE surface entirely; ingestion already proves the pattern (source: docs/supply-chain.md scan policy)
