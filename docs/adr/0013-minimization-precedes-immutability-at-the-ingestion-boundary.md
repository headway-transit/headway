# ADR-0013: Minimization Precedes Immutability at the Ingestion Boundary

- Status: Accepted
- Date: 2026-07-29
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

Two of this project's rules collided for the first time while building the Samsara fleet-
telematics connector (handoff 0028), and the implementing engineer raised it rather than
resolving it quietly — correctly.

- **The ingestion invariant:** a raw record is byte-identical to the source input,
  content-addressed by the SHA-256 of those exact bytes, stored immutably. This is the
  evidence chain: a certified figure can be walked back to precisely what the source said
  (`.claude/roles/INGESTION_ENGINEER.md` Definition of Done item 9; ADR-0006; the
  immutability triggers proven by attack in migration 0007 and earlier).
- **Data minimization:** fleet telematics is employee data. A vendor response can carry
  driver identity, payroll ids, badge scans and behavior scoring that Headway has no
  purpose for and deliberately does not collect (`docs/data-classification.md`).

Storing the response byte-identically satisfies the first rule and violates the second.
The collision is sharpened by a fact specific to this platform: **`raw.records` rejects
UPDATE and DELETE by design.** Personal data landed there is not merely stored — it is
stored somewhere the platform has deliberately made it impossible to remove. An agency
that later needed to honor a bargaining agreement, a privacy determination, or its own
classification policy would find the data un-deletable by construction, in a system whose
whole argument is that it is trustworthy.

## Decision Drivers

- Immutability exists to make evidence tamper-evident. It was designed for operational
  payloads, not as a commitment to permanently retain whatever a vendor chooses to include.
- Personal data that is never collected cannot be leaked, subpoenaed, over-retained, or
  bargained over. Nothing else on the mitigation list is as strong.
- An auditor's question is "does this figure trace to what the source reported?" — not
  "did you also keep the driver's payroll id?" Fields Headway never reads cannot affect a
  figure, so dropping them costs the evidence chain nothing.
- Silent divergence from a stated invariant is the failure mode this project exists to
  refuse. If the rule changes, it changes in writing.
- The alternative of refusing whole payloads that contain personal fields would make the
  connector unusable at agencies whose vendor always includes them — safety theater that
  ends in someone exporting spreadsheets instead.

## Considered Options

- **Minimize at the connector boundary, before the first write; refine the invariant in
  writing** (chosen)
- Store the full response, minimize downstream — preserves byte-identity with the vendor
  and lands un-deletable personal data in an immutable store. Rejected.
- Refuse any payload containing personal fields — fails closed, but disables ingestion for
  ordinary vendor accounts. Rejected as unusable.
- Store full bytes encrypted with a separately held key — adds key management, an illusion
  of deletion (crypto-shredding is defensible but subtle), and still collects the data.
  Rejected for a v0 whose users have no records officer.

## Decision Outcome

**At the ingestion boundary, a documented allow-list minimization runs before anything is
stored. The immutability invariant then applies, in full, to the minimized bytes.**

The invariant is restated as: *a raw record is byte-identical to what Headway accepted
from the source, where what is accepted is defined by a versioned, published allow-list.*

Binding conditions, all of which must hold for this to be honest rather than convenient:

1. **Allow-list, not deny-list.** Fields are kept because they are named and needed. A
   vendor adding a new personal field tomorrow is dropped by default, not leaked by
   default.
2. **Deterministic and versioned.** The minimization is a pure function with a recorded
   version, so the same source response always yields the same record id, and the
   transformation applied to any stored record is knowable after the fact.
3. **Published in agency-readable form.** Every connector documents exactly which fields
   it requests, which it keeps, and which it drops — in a table an HR or legal reviewer
   can read without engineering help (connector README + `docs/connecting-your-data.md`).
4. **Dropped names logged, dropped values never.** Operators can see that minimization
   acted, and on what shape of field, without the log becoming the leak.
5. **Requested scope matches kept scope.** Connectors ask the vendor for the narrowest
   credentials that serve the purpose; minimization is the second line, not the excuse for
   requesting more than needed.
6. **Stated at the point of provenance.** The raw record's own documentation makes clear
   these are post-minimization bytes, so no future auditor mistakes them for an unedited
   vendor response.
7. **Applies to personal-data minimization only.** This ADR is not a license to trim
   payloads for convenience, size, or tidiness. Operational content stays byte-identical;
   the exception is narrow and its justification is privacy.

### Consequences

- Good — personal data an agency has not decided to collect never enters a store the
  platform cannot delete from; the classification and retention decisions in ADR-0012 and
  `docs/data-classification.md` stay implementable rather than aspirational.
- Good — the evidence chain is unaffected for every field any figure is computed from.
- Bad / cost — Headway can no longer claim, without qualification, that a raw record is
  the vendor's exact response. Every connector that minimizes must say so, and this ADR is
  the reason it is a refinement rather than a broken promise.
- Bad / cost — an allow-list must be maintained as vendor APIs evolve; a field newly needed
  for a legitimate purpose requires a deliberate change, which is the intended friction.

### Follow-ups

- Update `.claude/roles/INGESTION_ENGINEER.md` Definition of Done item 9 to the restated
  invariant with a pointer here (role-file edit, Platform Architect).
- Audit the existing connectors: GTFS/GTFS-RT and TIDES payloads are agency operational
  data with no vendor-added personal fields, so they remain byte-identical to source — but
  record that determination rather than assuming it, particularly for the demand-response
  path, where rider coordinates are the most sensitive data in the platform.
