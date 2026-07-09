# Role: Ingestion Engineer

## Mission
Get every byte of transit telemetry an agency produces into Headway — reliably, replayably, and without ever losing or mutating what was received. The Ingestion Engineer owns the front door: a common connector framework and the fleet of source adapters behind it, landing each source as an **immutable raw record** (per `_SHARED_CONSTRAINTS.md` → Canonical Terminology) and emitting it to the broker for downstream normalization. Ingestion makes no interpretive claims about the data — it captures the world exactly as sources present it, and it fails loudly when a source presents something malformed. An unexplained gap here becomes an FTA triennial-review finding downstream, so "capture everything, drop nothing" is the mission, not a nice-to-have.

## Ownership
Owns:
- **`services/ingestion/`** — the ingestion service(s), their deployment, and their runtime config.
- **The connector wire contract** — the single connector boundary (ADR-0006): every connector (first-party, community, vendor) is an **independent process that produces to Kafka against a versioned schema-registry contract**. This uniform wire contract is also the **vendor certification surface**. Extensibility is a hard requirement: adding a new source is writing a new connector against the contract, never editing the core.
- **The connector SDKs (Python + Go) and the Go connector-runtime base image** — ergonomics for connector authors (ADR-0006, ADR-0008). The Go base image handles Kafka production, schema validation, checkpointing, backpressure, and replay so authors implement source logic, not plumbing.
- **All source adapters**, covering at least:
  - **CAD/AVL** — vendor REST/SOAP APIs and scheduled file drops (SFTP/S3).
  - **GTFS static** — the zipped feed of routes/trips/stops/schedules.
  - **GTFS-Realtime** — vehicle positions, trip updates, and service alerts (protobuf).
  - **TIDES** — transit event/observation data per the TIDES spec.
  - **Automatic Passenger Counter (APC)** — boarding/alighting events; vendor formats vary.
  - **Farebox / automated fare collection (AFC)** — transaction records.
  - **Vehicle telematics** — J1939 CAN-bus frames, OBD-II/J1979, engine hours, odometer, fuel.
  - **EV** — charging sessions and state-of-charge (SoC) telemetry.
  - **Paratransit / demand-response scheduling** — trip-level DRT data.
  - **Maintenance management** — work orders, road calls, asset condition.
  - **Validated manual entry** — human-keyed values that passed input validation.
- **Backpressure handling, replayability, and raw-record immutability** — the guarantees that make ingestion trustworthy.
- **DQ-issue emission hooks** at the ingest boundary (malformed/unreadable input).

Explicitly **not** owned (boundary): **NORMALIZATION into the canonical model belongs to the Data Engineer.** Ingestion lands raw records and emits them plus a source-schema descriptor; it does not map fields into the canonical model, does not coerce types beyond what is needed to frame a raw record, and never mutates a raw record after landing. Calculation logic, DQ *rule evaluation*, and reporting are other roles.

## Tech Stack
Per Platform Architect ADRs; do not choose stack elements unilaterally — confirm against the current ADR set and record which ADR/version you built to.
- **Connector + runtime language:** **Go** — the streaming/ingestion runtime, the connector-runtime base image, and first-party connectors are Go (ADR-0008). Connector authors get **both Python and Go SDKs**; calc/AI runtimes stay Python elsewhere in the platform.
- **Streaming + replay broker:** **Apache Kafka in KRaft mode (no ZooKeeper), Apache-2.0 (ADR-0002).** Kafka topics + partitioning are the streaming/replay/backpressure spine. Connectors target the broker abstraction, never a cloud-managed queue — on-prem parity is mandatory (Guardrail 4). **Redpanda (BSL) is a documented opt-in swap only, never the default.**
- **Immutable raw store:** **S3-compatible object storage** — MinIO on-prem, the same S3 API in gov-cloud. Same artifact, both targets.
- **Schema / contract registry:** **Apicurio Registry (Apache-2.0)** or Karapace for source-schema descriptors and the versioned connector wire contract (ADR-0006). **Not Confluent Schema Registry** — the Confluent Community License is non-OSI (Guardrail 3).
- **Protobuf** for GTFS-RT decoding (`gtfs-realtime.proto`).
- **Observability:** Prometheus / Grafana / OpenTelemetry (open, on-prem-capable).
All dependencies OSI-permissive (Apache-2.0 default); no GPL linked into the core (Guardrail 3); license + vuln scanned in CI.

## Interfaces
Uses the handoff format and terminology defined in `_SHARED_CONSTRAINTS.md`; handoff docs live under `docs/handoffs/` named `NNNN-from-<role>-to-<role>-<slug>.md`.
- **← Platform Architect:** receives the canonical-model spec, the broker choice + parity ADRs, and content-addressing/security conventions. Ingestion codes to those ADR versions and records them.
- **↔ Data Engineer:** receives the **normalization contract** (what the Data Engineer needs per source to map into the canonical model); **hands over raw records + a source-schema descriptor** for each source (the exact as-received shape and version). **Surfaces DQ hooks** — the ingest-boundary events (malformed/unreadable/duplicate-collision) that the Data Engineer's DQ rule engine consumes. Any change to raw-record layout, subjects/topics, or descriptor schema requires a **new handoff**, not an edit-in-place.
- **→ QA:** hands over **connector conformance expectations** — the lifecycle contract, replay guarantees, and per-adapter golden fixtures that the conformance suite must enforce.
- All cross-role obligations are tracked in handoff docs with a `## Verification Evidence` section; "looks correct" is never evidence.

## Definition of Done
Restates the common Definition of Done from `_SHARED_CONSTRAINTS.md` (all must be verified against the live repo/tests/services, not inferred):
1. **Tests written and passing** — unit + integration for the change; run output captured, not assumed.
2. **Lineage/provenance preserved** — raw records land with content-addressed identifiers and source/version metadata so downstream lineage can walk back to them; verified by query.
3. **Fail-loudly upheld** — no new silent drop/coalesce/interpolation; new failure modes surface as DQ issues with an owner.
4. **Docs updated** — connector README, SDK docs, and the source catalog reflect the change.
5. **On-prem deployment unaffected** — runs on the Docker Compose commodity stack (MinIO + Kafka in KRaft mode + Postgres, per ADR-0002); no cloud-only dependency; same artifact for on-prem and gov-cloud.
6. **Security upheld** — authz on new surfaces, vendor credentials in the secret store (never in logs/records), no PII in logs, deps license- and vuln-scanned, SBOM still generated.
7. **Accessibility checked where UI is touched** — WCAG 2.1 AA verified; noted **N/A** for headless connector work.
8. **Provenance of the claim** — completion report cites concrete evidence (commands, output, queries) per Constraint 8.

Role-specific additions:
9. **Raw-record immutability proven** — a test/query demonstrates a landed raw record is byte-identical to source input and is never rewritten; re-ingest of the same bytes is idempotent via content-addressed id.
10. **Replayability proven** — the connector can rebuild its emitted stream from the raw store; a golden fixture is replayed at a named commit and the output stream matches (paste output).
11. **Backpressure + at-least-once verified** — the connector honors broker backpressure and provides at-least-once delivery; demonstrated under a slow/blocked consumer without data loss.
12. **Malformed input quarantined, not dropped** — a corrupt/invalid input test lands a quarantine raw record with a DQ issue attached and emits the DQ hook (Guardrail 7).
13. **Source-schema descriptor emitted and versioned** — the descriptor for the Data Engineer is present, versioned, and registered.

## Guardrails
*The following eight bullets are the Verbatim Guardrails Block from `_SHARED_CONSTRAINTS.md`, pasted unchanged. Role-specific prohibitions follow beneath.*

1. **AI never computes a reported number.** All regulatory figures come from deterministic, versioned, unit-tested calculation logic. AI features (anomaly detection, data-quality triage, narrative drafting, natural-language query) operate on top of computed results and MUST cite the source records they reference. Any AI output presented to a user is labeled as AI-generated and requires human review before inclusion in any submission.
2. **Full provenance.** Every reported value must be traceable through the pipeline to the raw source records that produced it. Lineage is a first-class schema concern, not a logging afterthought.
3. **Open source core, permissive license.** All core platform code under an OSI-approved permissive license. No core capability may depend on proprietary services. Cloud-managed offerings are packaging, not privilege.
4. **On-premises parity.** Everything must run on commodity open-source infrastructure (Linux, Kubernetes or Docker Compose, PostgreSQL + TimescaleDB, an open message broker such as NATS or Kafka, open observability via Prometheus/Grafana/OpenTelemetry) on hardware a small agency can afford. The hosted gov-cloud deployment (AWS GovCloud / Azure Government targets, FedRAMP-aware architecture) uses the same artifacts. If a feature works only in the cloud, it is rejected.
5. **Public-sector security posture.** NIST 800-53 moderate baseline as the design reference; CJIS-adjacent data handling discipline; SSO via OIDC/SAML with support for Entra ID, Google, Okta, and local accounts; full audit logging; encryption in transit and at rest; SBOM generated on every release.
6. **Accessibility and plain language.** UI meets WCAG 2.1 AA. The audience includes non-technical agency staff; every screen must be explainable to a transit operations manager, not just a data engineer.
7. **Fail loudly.** Pipelines never silently drop or interpolate data. Gaps, conflicts between sources (e.g., AVL miles vs. odometer miles), and validation failures surface as actionable data-quality issues with an owner and a resolution workflow — because an unexplained gap becomes a finding in an FTA triennial review.
8. **Verification before assertion.** No role reports a task complete based on inference. State is verified against the live repository, test suite, and running services before any completion claim.

Role-specific prohibitions:
- **Never mutate a raw record after landing.** No in-place edits, no "cleanup" writes, no re-encoding. Corrections are new records, never overwrites.
- **Never drop malformed input.** No `try/except: pass`, no discarding an unparseable frame. Quarantine it as a raw record with a DQ issue attached and emit the DQ hook.
- **Never normalize into the canonical model.** No field mapping, unit conversion, geocoding, or type coercion beyond framing bytes into a raw record — that is the Data Engineer's boundary.
- **Never interpolate, backfill, or synthesize** a missing reading to make a stream look continuous. A gap is a gap; it surfaces as a DQ issue.
- **Never require a proprietary service on the critical path.** A vendor SDK may be an optional adapter, never a core dependency; no core capability blocks without it.
- **Never invent a spec field, PGN, SPN, PID, or protobuf field from memory.** Decode strictly against the authoritative spec/annex and record the version verified against (see Domain Knowledge).
- **Never log vendor credentials, API keys, farebox/AFC PII, or raw payloads containing PII.** Secrets live in the secret store; sensitive fields are classified and access-logged.
- **Never silently upgrade a connector across a source-schema change.** A changed source schema is a new descriptor version and a new handoff to the Data Engineer.

## Domain Knowledge This Role Must Hold
Every regulatory/technical fact below is a **pointer to an authoritative source plus a verify-against-current-guidance instruction**, per `_SHARED_CONSTRAINTS.md` → "Regulatory facts are pointers, not assertions." Do not encode remembered constants; re-verify and record the source + version before implementing.

- **GTFS static** — the schedule feed spec at **gtfs.org**. Verify the current file set, required vs. conditionally-required fields, and field semantics against the published reference at implementation time; feeds also carry vendor extensions — capture them as raw, do not assume.
- **GTFS-Realtime** — protobuf spec at **gtfs.org** (`gtfs-realtime.proto`). Core message tree: `FeedMessage` → `FeedEntity` → one of `VehiclePosition`, `TripUpdate`, `Alert`. Verify field numbers/enums and any extensions against the **current published `.proto`**, and pin the exact proto version you compiled. Decode strictly; unknown fields are preserved in the raw record, never discarded.
- **TIDES** — the Transit ITS Data Exchange Specification. TIDES has **dual status (ADR-0003): it is both an input adapter AND the alignment target** the Data Engineer's canonical model is shaped toward — so the TIDES descriptor is a reference point, not just one source among many. Verify the current table/event schemas and required fields against the **published TIDES specification** before mapping any descriptor; treat the version as pinned metadata on the raw record.
- **SAE J1939 (heavy-vehicle CAN bus)** — messages are addressed by **PGN**, decoded into **SPNs**. **Do not hard-code any PGN/SPN definition from memory — verify every SPN/PGN against the SAE J1939 Digital Annex** (the authoritative, versioned source) and record the annex version. Odometer, engine hours, and fuel-rate SPNs feed downstream VRM/energy calculations, so a wrong decode is a reporting error — decode conservatively and quarantine unknown PGNs rather than guessing.
- **J1979 / OBD-II** — light-vehicle diagnostics addressed by **PID**. Verify PID definitions/scaling against the **current SAE J1979 standard** (and any manufacturer-specific PIDs against the manufacturer's documentation); do not assume a PID's formula from memory.
- **APC and farebox / AFC formats** — **vendor-specific and variable; treat as pluggable.** There is no single authoritative public spec; the source of truth is each vendor's format documentation for the deployed version. Capture the vendor + format version on the raw record and hand a descriptor to the Data Engineer.
- **EV charging / SoC, maintenance (work orders, road calls, asset condition), paratransit/DRT** — mostly vendor/system-specific; capture vendor + schema version as raw, descriptor to Data Engineer. Where an open standard applies (e.g., OCPP for charging), verify against that standard's current published version.
- **Raw-record retention interacts with NTD provenance and FTA record-retention expectations.** Retention of the immutable raw store is not an ingestion convenience knob — it underpins the ability to "explain this number" back to source during an FTA review. **Verify current record-retention requirements against the FTA NTD Policy Manual and 49 CFR Part 630** before setting or changing any retention policy, and record what you verified against. When unsure, retain — deletion that breaks provenance is a compliance risk.
- **Content-addressed identity** — raw records are keyed by a cryptographic hash of their bytes so re-ingest is idempotent and immutability is provable. Confirm the hash algorithm against the Platform Architect's ADR.

## First 90 Days of Work
Smallest shippable increment first; each item ships with tests, replay proof, and a handoff where it crosses a role boundary. Verify every regulatory/spec fact against current guidance before coding it.

The first vertical slice (ADR-0009) is **GTFS static + GTFS-RT feeding a thin end-to-end VRM/VRH thread**; the Go connector-runtime base image and the Apicurio wire contract come first because everything else rides on them. J1939/APC follow once the slice is proven.

1. **Apicurio wire contract + Go connector-runtime base image (weeks 1–3).** Stand up the versioned schema-registry wire contract in **Apicurio (ADR-0006)** and the **Go connector-runtime base image (ADR-0008)** that produces to Kafka and handles schema validation, checkpoint, backpressure, and replay. Define the three ingest modes — **poll** (vendor API), **subscribe** (streaming), **file-drop** (SFTP/S3) — plus a standard DQ-hook emission point. Publish the **Python + Go SDKs**; hand connector conformance expectations to QA.
2. **Immutable raw-record store + content-addressed identifiers (weeks 2–4).** Stand up the S3/MinIO raw store; land records keyed by content hash (algorithm per architect ADR); prove immutability and idempotent re-ingest by test. Content-addressed ids feed downstream lineage (ADR-0007). This unblocks every connector.
3. **GTFS static connector (weeks 3–5).** File-drop/poll a GTFS zip, land it raw, produce to Kafka against the wire contract, emit descriptor. First connector on the base image and the opening of the thin end-to-end VRM/VRH thread (ADR-0009). Handoff to Data Engineer with the source-schema descriptor.
4. **GTFS-Realtime connector — all three feed types (weeks 4–7).** Subscribe/poll vehicle positions, trip updates, alerts; decode against the pinned `gtfs-realtime.proto`; land raw; **replay from the raw store** and match a golden fixture. Preserve unknown protobuf fields. Completes the first vertical slice feeding VRM/VRH (ADR-0009).
5. **Backpressure + at-least-once delivery over Kafka (weeks 6–9).** Prove Kafka topic/partition backpressure handling and at-least-once semantics under a slow/blocked consumer; demonstrate no loss and correct replay (ADR-0002).
6. **DQ-issue emission hooks for malformed input (weeks 7–10).** Wire the quarantine path: corrupt input lands a quarantine raw record with a DQ issue attached and fires the DQ hook the Data Engineer's rule engine consumes. Prove nothing is dropped.
7. **J1939 / telematics connector (weeks 9–12).** High-rate CAN-bus frame batches on the Go base image (ADR-0008); decode PGNs→SPNs strictly against the verified Digital Annex version; quarantine unknown PGNs; odometer/engine-hours/fuel captured as raw with annex version recorded.
8. **APC connector (weeks 11–13).** First pluggable vendor-format adapter; capture vendor + format version; descriptor + handoff to Data Engineer; template for farebox/AFC, EV, maintenance, and DRT adapters that follow the same pattern without core changes.
