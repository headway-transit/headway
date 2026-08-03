# ADR-0012: Retention Is a Per-Agency Records Policy with a Federal Floor, Not a Disk Setting

- Status: Accepted
- Date: 2026-07-29
- Deciders: Founding Architect (Headway)

## Context and Problem Statement
The GTFS-Realtime `trip_updates` poller has been DISABLED since handoff 0014 pending "a
retention policy" — recorded there as an engineering problem (~1.1 GB/hr of normalized
prediction rows on a small-agency box). Framing it that way was wrong, and the project
lead named the reason (2026-07-29): **every transit agency is a public body operating
under its own state and local records-retention schedule.** How long data lives is a
records-management decision the agency is legally accountable for — not a disk-space
tuning parameter the platform gets to choose.

The exposure runs in *both* directions, which is what makes a single shipped default
unacceptable:

- **Deleting too early** is unlawful destruction of public records under state schedules,
  and it fails the federal test below.
- **Keeping too long** is its own liability: in public-records-act jurisdictions, data
  that still exists is generally disclosable, and agencies destroy records on schedule
  precisely so that they are not holding them.

A platform that picks one number for everyone is guaranteeing that some agencies break
one rule or the other.

## Decision Drivers

- **The federal floor is real, quotable, and audited.** The 2026 NTD Policy Manual is on
  file (`docs/reference/`) and states, verbatim: *"Transit agencies must retain sampling
  documentation in their records for at least three years."* The Independent Auditor
  Statement procedures go further — the auditor is instructed to *"Ask these same
  personnel about the retention policy that the transit agency follows as to source
  documents supporting NTD data reported on the Federal Funding Allocation Statistics
  form,"* then to *"identify all the source documents that the transit agency must retain
  for a minimum of three years,"* select three months, and check that each document
  exists. **An agency's retention policy is itself an audited artifact**, and Headway
  holds the source documents in question.
- State and local schedules vary by jurisdiction and frequently exceed three years; some
  categories carry destruction obligations.
- Litigation hold suspends destruction regardless of schedule — a universal public-agency
  requirement.
- The platform's own guardrails: `raw.records` and `audit.events` carry immutability
  triggers that reject UPDATE and DELETE by design (migrations 0007 and earlier, proven
  by attack). Retention cannot be bolted on by weakening them.
- Certified figures must remain explainable for as long as they are relied upon; deleting
  the evidence under a certified figure without recording that fact would silently break
  the platform's central promise.

## Considered Options

- **Per-agency, per-class policy with a federal floor and tombstoned deletion** (chosen)
- A single shipped retention default (e.g. 90 days of telemetry) — simple, and wrong for
  every agency whose schedule differs; converts a legal decision into a vendor default.
- Retain everything forever — dodges deletion complexity, maximizes disclosure exposure,
  and makes small-box economics impossible at 1.1 GB/hr.
- Delegate entirely to the agency's DBA with no platform support — the honest fallback
  today, but it leaves the audited "what is your retention policy?" question unanswerable
  from the system that holds the records.

## Decision Outcome

**Retention is configured per agency, per data class, with a citation, enforced by the
platform, and every deletion leaves a tombstone.**

1. **Per data class, not one global TTL.** The classes have genuinely different legal
   character: raw source records (the NTD audit's "source documents"); canonical derived
   rows; computed figures, certifications and signatures (the record of what was
   reported); the audit trail; high-volume operational telemetry (trip-update
   predictions, the 1.1 GB/hr class); data-quality findings and lineage.
2. **Every policy carries its authority.** A retention setting is not a number alone; it
   records the schedule or statute the agency is following (e.g. a state records-retention
   schedule section, or the NTD three-year floor), exactly as calc thresholds carry basis
   citations today (migration 0014). This is what makes the auditor's question answerable
   from the platform: *here is the policy, here is its authority, here is the proof.*
3. **A federal floor the platform refuses to go below silently.** Classes that constitute
   NTD source documentation cannot be configured under three years without an explicit,
   recorded, role-gated override stating the agency's reason — the same fail-closed
   pattern as every other guardrail. The floor is quoted, not invented.
4. **Deletion is tombstoned, never silent.** Purging a record writes an immutable
   tombstone: what existed (id and content hash), when it was deleted, under which policy
   and authority, and by which process. Lineage edges therefore never dangle into
   nothing — they resolve to a statement that the input existed and was destroyed under
   a named schedule. **The tombstone is the receipt for a deletion**, and it preserves
   the ability to explain a figure whose underlying bytes are lawfully gone.
5. **Immutability is preserved, not relaxed.** The append-only triggers stay. Retention
   deletion runs through a single privileged, audited path that the triggers recognize —
   no general DELETE grant, no weakening of the tamper-evidence proven by attack.
6. **Legal hold overrides everything.** A hold suspends all deletion for the affected
   scope, is itself audited, and no schedule expiry may override it.
7. **Certified-figure protection.** A purge that would destroy evidence under a figure
   currently certified refuses by default and requires an explicit override, recorded
   with the same weight as any other refusal in this platform.
8. **Defaults are conservative.** Out of the box Headway retains and warns rather than
   deletes; an agency that has not set a policy has not consented to destruction. The
   installer and admin surface ask for the policy in plain language, and the absence of
   one is surfaced as an open item, not silently resolved.

### Consequences

- Good — the audited question "what is your retention policy?" becomes answerable from
  the system that holds the records, with evidence; agencies stay inside their own
  schedules in both directions; the trip-update poller can finally be re-enabled behind
  an agency-set policy for its class.
- Good — deletion becomes explainable, which keeps "explain this number" true even after
  lawful destruction of the underlying source.
- Bad / cost — materially more machinery than a TTL: a policy model, an enforcement job,
  tombstones, holds, overrides, and an admin surface for all of it. Retention work is now
  a compliance feature with the NTD Compliance role in the loop, not a devops chore.
- Bad / cost — the platform must not give legal advice. It supplies the federal floor
  (quoted), the structure, and the citation field; the agency's records officer supplies
  the schedule. Documentation must be explicit about that boundary.

### Follow-ups

- Handoff for the retention model + tombstones + hold mechanics (Backend + NTD
  Compliance; the immutability-trigger interaction is the hard part).
- Re-enable the `trip_updates` poller once its class has a policy (unblocks the replay
  dashboard's prediction features — `docs/design/toc-replay-dashboard.md` §6).
- Quote the state-schedule research for the first partner agency's jurisdiction into the
  regulatory tracker the same way FTA definitions are quoted — never paraphrased.
- **Retention policy assumes a classifier.** The first partner agency has no records
  officer (oversight sits with HR and external counsel) and is only now standing up a
  data-classification program — which is the NORMAL case at a small agency, not an
  exception. `docs/data-classification.md` therefore ships the inventory side of this:
  what the platform holds and how sensitive each class is, so an agency can classify what
  already exists rather than start from a blank page. Retention policy consumes those
  classes; neither waits on the other.
