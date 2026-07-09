# Headway — Shared Constraints

**This document is binding on every role.** Read it in full before assuming any role. Every role file embeds the *Verbatim Guardrails Block* (below) inside its own `## Guardrails` section, word for word, and then adds role-specific prohibitions. If anything in a role file appears to contradict this document, this document wins — raise the conflict as an open question in a handoff document rather than resolving it silently.

Headway is an open-source Autonomous Transit Data Platform. It ingests transit telemetry from every available source, normalizes it into one open data model, and automates regulatory reporting — with the FTA National Transit Database (NTD) as the anchor requirement. It is intended to be the single source of truth for an agency's entire fleet. An unexplained gap in Headway becomes a finding in an FTA triennial review; that stakes standard governs every decision.

---

## The Eight Non-Negotiable Constraints (expanded)

Each constraint below is stated, then illustrated with a concrete **Violation** and the **Correct alternative**. The terse canonical wording that every role embeds is in the *Verbatim Guardrails Block* at the end.

### 1. AI never computes a reported number
All regulatory figures come from deterministic, versioned, unit-tested calculation logic. AI features (anomaly detection, data-quality triage, narrative drafting, natural-language query) operate *on top of* computed results and must cite the source records they reference. Any AI output shown to a user is labeled AI-generated and requires human review before inclusion in any submission.

- **Violation:** An LLM is asked "estimate this route's unlinked passenger trips for March" and its number flows into the NTD MR module. A model summarizes APC gaps by guessing a fill value.
- **Correct:** A deterministic calculator sums certified APC counts per the versioned rule; the AI layer only flags "March UPT is 22% below the trailing-12-month mean for this route — see records [ids]" and a human triages it. The number itself never originates in a model.

### 2. Full provenance
Every reported value must be traceable through the pipeline to the raw source records that produced it. Lineage is a first-class schema concern, not a logging afterthought.

- **Violation:** A monthly VRM total exists in a reporting table with no column, join, or lineage row connecting it to the AVL/odometer records and the transformation version that produced it.
- **Correct:** Each computed value carries (or is joinable to) the set of raw record identifiers, the transformation/version id, and the calculation-library version. "Explain this number" can walk from the submission cell back to raw ingest.

### 3. Open source core, permissive license
All core platform code is under an OSI-approved permissive license (Apache-2.0 is the project default). No core capability may depend on a proprietary service. Cloud-managed offerings are packaging, not privilege.

- **Violation:** Normalization silently requires a paid geocoding SaaS; without it, the core cannot compute passenger miles. A connector links a GPL library into the core, forcing copyleft on the whole platform.
- **Correct:** Core uses an open geocoder/routing engine (e.g., self-hostable) with a pluggable interface; a proprietary provider may be an *optional* adapter that is never on the critical path. License of every dependency is checked in CI.

### 4. On-premises parity
Everything runs on commodity open-source infrastructure — Linux, Docker Compose or Kubernetes, PostgreSQL + TimescaleDB, an open broker (NATS or Kafka), open observability (Prometheus / Grafana / OpenTelemetry) — on hardware a small agency can afford. The hosted gov-cloud deployment (AWS GovCloud / Azure Government, FedRAMP-aware) uses the *same artifacts*. If a feature works only in the cloud, it is rejected.

- **Violation:** A pipeline stage calls a managed cloud queue or a serverless-only API; on-prem it silently degrades or fails.
- **Correct:** The stage targets the Apache Kafka (KRaft) broker (see ADR-0002) that runs identically in Docker Compose on a single box and in gov-cloud. The same container image ships to both.

### 5. Public-sector security posture
NIST 800-53 moderate baseline is the design reference; CJIS-adjacent data-handling discipline applies; SSO via OIDC/SAML with Entra ID, Google, Okta, and local accounts; full audit logging; encryption in transit and at rest; an SBOM is generated on every release.

- **Violation:** A service exposes an unauthenticated internal endpoint "because it's behind the VPN," or writes PII to logs, or ships a release with no SBOM.
- **Correct:** Every endpoint authenticates and authorizes; sensitive fields are classified and access-logged; TLS everywhere; at-rest encryption enabled by default; `cyclonedx`/`syft` SBOM attached to each release artifact.

### 6. Accessibility and plain language
The UI meets WCAG 2.1 AA. The audience includes non-technical agency staff; every screen must be explainable to a transit operations manager, not just a data engineer.

- **Violation:** A data-quality queue uses color alone to signal severity, has unlabeled icon buttons, and describes an issue as "AVL/odo delta > 3σ."
- **Correct:** Severity has text + icon + sufficient contrast; controls have accessible names and keyboard paths; the same issue reads "Recorded miles from GPS and from the odometer disagree by 41 miles on Bus 1207, March 3 — pick which to trust."

### 7. Fail loudly
Pipelines never silently drop or interpolate data. Gaps, conflicts between sources (e.g., AVL miles vs. odometer miles), and validation failures surface as actionable data-quality issues with an owner and a resolution workflow.

- **Violation:** An ingest adapter `try/except: pass` on malformed rows; a normalizer coalesces a missing value to 0; a calculator interpolates across a telemetry gap.
- **Correct:** The bad row is quarantined as a raw record with a data-quality issue attached; the missing value produces an open issue with an owner; the calculator refuses to emit a certifiable figure over an unresolved gap and says so.

### 8. Verification before assertion
No role reports a task complete based on inference. State is verified against the live repository, the test suite, and running services before any completion claim.

- **Violation:** "The connector is done — the code looks correct." "Tests should pass now."
- **Correct:** "Connector conformance suite run at <commit>: 34/34 pass (paste output). Ran against a live Kafka + Postgres compose stack; replayed the golden GTFS-RT fixture; provenance rows verified present via query X."

---

## Canonical Terminology

Use these terms exactly; do not invent synonyms. Where a term is a regulatory term of art, defer to the FTA source over this gloss.

- **Source record / raw record** — an immutable, as-received unit of ingested data (a GTFS-RT feed message, a J1939 frame batch, an APC event, a farebox transaction). Never mutated after landing.
- **Canonical model** — Headway's single normalized open data model that all sources map into.
- **Lineage / provenance** — the traceable chain from a reported value back to the raw records and transformation versions that produced it.
- **Calculation library** — the deterministic, versioned, unit-tested code that produces every regulatory figure. The *only* place reported numbers originate.
- **Data-quality (DQ) issue** — a surfaced gap, conflict, or validation failure with a type, severity, owner, and resolution workflow state.
- **Connector / adapter** — code that ingests one source type behind the common connector framework interface.
- **Golden dataset** — a fixed set of known inputs with certified expected outputs, used for regression-testing calculations.
- **Submission package** — the assembled, validated artifact set for an NTD (or state/grant) report, ready for human certification.
- **Certification** — the human act of attesting a report is correct before submission; gated in the UI, audit-logged.
- **Agency** — the transit provider that is Headway's tenant/operator. **Fleet** — its revenue and non-revenue vehicles.
- **NTD modules referenced** — Monthly Ridership (MR); Safety & Security (S&S); Annual Report metrics: revenue vehicle miles (VRM) / hours (VRH), unlinked passenger trips (UPT), passenger miles traveled (PMT), vehicles operated in maximum service (VOMS), energy consumption, asset inventory / Transit Asset Management (TAM).
- **Reporting periods** — MR is monthly; the Annual Report is annual on the FTA fiscal-year cycle. **Do not hard-code due dates or thresholds** — resolve them against current FTA guidance (see Constraint on regulatory facts below).

### Regulatory facts are pointers, not assertions
Headway enforces anti-hallucination discipline; the role files must model it. Whenever a role states a regulatory fact — an NTD rule, a due date, an edit-check threshold, a sampling requirement, a spec field — phrase it as **a pointer to the authoritative source plus an instruction to verify against current published guidance**, never as an unsourced number remembered from training. Authoritative sources include: FTA NTD Policy Manual and Reporting Manuals, FTA NTD Sampling Manual (e.g., FTA Circular 2710.x series for statistical sampling of PMT), 49 CFR Part 630, the GTFS and GTFS-Realtime specifications (gtfs.org), the TIDES specification, SAE J1939 / J1979 (OBD-II), and applicable NIST SP 800-53 / FedRAMP baselines. When a rule is version-dependent, the role must re-verify before implementing and record the source and version it verified against.

---

## Definition of Done (common to all roles)

A task is Done only when **all** of the following are true and verified against the live repo/tests/services — not inferred:

1. **Tests written and passing** — unit + integration appropriate to the change; new logic has new tests; the run output is captured, not assumed.
2. **Lineage/provenance preserved** — the change cannot break the chain from a reported value to its raw records; where it touches data flow, provenance rows/joins are present and verified by query.
3. **Fail-loudly upheld** — no new silent drop, coalesce, or interpolation path; new failure modes surface as DQ issues with an owner.
4. **Docs updated** — user- and/or contributor-facing docs reflect the change, including "explain this number" where a calculation or its inputs changed.
5. **On-prem deployment unaffected** — the change runs on the Docker Compose commodity stack; no cloud-only dependency introduced; same artifact for on-prem and gov-cloud.
6. **Security upheld** — authz enforced on new surfaces, no secrets/PII in logs, dependencies license- and vuln-scanned, SBOM still generated.
7. **Accessibility checked where UI is touched** — WCAG 2.1 AA verified (keyboard, contrast, names, plain language); noted as N/A only when no UI changed.
8. **Provenance of the claim** — the completion report cites concrete verification evidence (commands run, outputs, queries) per Constraint 8.

Each role's `## Definition of Done` restates this list and adds role-specific items.

---

## Inter-Role Handoff Format

Cross-role work requires an explicit handoff document — a markdown file placed under `docs/handoffs/` named `NNNN-from-<role>-to-<role>-<slug>.md`. No role begins dependent work from a verbal/implied handoff. The document has exactly these sections:

```markdown
# Handoff: <from-role> → <to-role> — <short title>

## Context
Why this handoff exists; the user/agency need it serves.

## Inputs (what the receiving role is given)
- Artifacts: paths, schemas, endpoints, message subjects, versions.
- Contracts: the exact interface/schema/spec version the receiver must code against.
- Assumptions the sender made that the receiver must not silently break.

## Outputs (what the receiving role must produce)
- Deliverables and their acceptance criteria, tied to the Definition of Done.

## Open Questions
- Unresolved decisions, with a proposed default and who must decide.

## Verification Evidence
- Proof the sender's side is real: commands run + output, test results at a
  named commit, queries showing provenance rows exist, screenshots for UI.
  "Looks correct" is not evidence.
```

The receiving role replies in the same document (append a `## Response` section) accepting the contract or raising blockers. Interface/schema changes after a handoff require a new handoff, not an edit-in-place.

---

## Verbatim Guardrails Block

*Every role file pastes the following eight bullets, unchanged, into its `## Guardrails` section, then adds role-specific prohibitions beneath them.*

1. **AI never computes a reported number.** All regulatory figures come from deterministic, versioned, unit-tested calculation logic. AI features (anomaly detection, data-quality triage, narrative drafting, natural-language query) operate on top of computed results and MUST cite the source records they reference. Any AI output presented to a user is labeled as AI-generated and requires human review before inclusion in any submission.
2. **Full provenance.** Every reported value must be traceable through the pipeline to the raw source records that produced it. Lineage is a first-class schema concern, not a logging afterthought.
3. **Open source core, permissive license.** All core platform code under an OSI-approved permissive license. No core capability may depend on proprietary services. Cloud-managed offerings are packaging, not privilege.
4. **On-premises parity.** Everything must run on commodity open-source infrastructure (Linux, Kubernetes or Docker Compose, PostgreSQL + TimescaleDB, an open message broker such as NATS or Kafka, open observability via Prometheus/Grafana/OpenTelemetry) on hardware a small agency can afford. The hosted gov-cloud deployment (AWS GovCloud / Azure Government targets, FedRAMP-aware architecture) uses the same artifacts. If a feature works only in the cloud, it is rejected.
5. **Public-sector security posture.** NIST 800-53 moderate baseline as the design reference; CJIS-adjacent data handling discipline; SSO via OIDC/SAML with support for Entra ID, Google, Okta, and local accounts; full audit logging; encryption in transit and at rest; SBOM generated on every release.
6. **Accessibility and plain language.** UI meets WCAG 2.1 AA. The audience includes non-technical agency staff; every screen must be explainable to a transit operations manager, not just a data engineer.
7. **Fail loudly.** Pipelines never silently drop or interpolate data. Gaps, conflicts between sources (e.g., AVL miles vs. odometer miles), and validation failures surface as actionable data-quality issues with an owner and a resolution workflow — because an unexplained gap becomes a finding in an FTA triennial review.
8. **Verification before assertion.** No role reports a task complete based on inference. State is verified against the live repository, test suite, and running services before any completion claim.
