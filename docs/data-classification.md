# What Headway holds, and how sensitive it is

A data-classification inventory for the agency officer — records manager, privacy
officer, HR, legal counsel, or (very commonly at a small agency) **the one person who
inherited all four hats**.

Most transit agencies Headway is built for have no records officer and no data-governance
program. That is the normal case, not a failure, and this platform is designed for it: it
ships conservative defaults, refuses to destroy anything you have not told it to destroy,
and states plainly what it is holding so that a governance program — whenever it arrives —
can classify what already exists instead of guessing.

**This page is an inventory and a set of engineering facts. It is not legal advice and it
is not a retention schedule.** Your schedule comes from your state and local records
authority; see [`docs/procurement-data-requirements.md`](procurement-data-requirements.md)
for the related contract questions and ADR-0012 for how retention policy is expressed.

## Two axes that are easy to confuse

**Sensitivity** (how carefully must this be handled, and who may see it) and **retention**
(how long must — or must not — this be kept) are different questions with different
authorities. A public timetable is low-sensitivity and may still have a retention rule; a
paratransit trip record is high-sensitivity *and* has a retention rule, and the two
answers come from different places. Headway keeps them separate: this page is
sensitivity, ADR-0012 is retention.

## The inventory

| What Headway holds | Sensitivity | Why — the part that is easy to miss |
| --- | --- | --- |
| Published schedule data (GTFS routes, trips, stops) | **Public** | It is already published for trip planners. |
| Certified NTD figures | **Public** by design | Public reporting is the point; the public endpoint serves certified figures only. |
| Aggregate passenger counts (APC / TIDES boardings and alightings) | **Internal** | Counts at a stop are not personal — but a single boarding at a lightly used stop at a known time can approach identifiability. Treat stop-level detail with more care than route totals. |
| Vehicle positions (GTFS-RT) | **Internal, employee-adjacent** | A position history is also a record of **where an identifiable operator was, minute by minute**, once combined with block or run assignments. In a unionized workplace this can fall under a collective-bargaining agreement. It is not anonymous data because no name is attached. |
| Fleet telematics (Samsara-class) | **Employee data** | Same as above, plus the vendor platform can expose driver identity, duty hours, and driver-behavior scoring. Headway ingests vehicle movement and **deliberately does not ingest driver-identified fields by default** (handoff 0028). Turning that on is a governance decision, not a configuration convenience. |
| **Demand-response / paratransit trip records** | **Highest sensitivity in the platform** | Pickup and dropoff coordinates are **rider home and destination addresses**. Worse: ADA paratransit eligibility implies disability status, so the mere existence of a rider's trip record can disclose a protected characteristic. Headway's read-only analyst role **withholds these coordinates at the column level** (migration 0028) — a decision already made in code, recorded here so a governance program can ratify or tighten it. |
| Safety & security events (S&S-50) | **Restricted** | Incident records can contain injury and assault detail about identifiable people, employees and riders alike. |
| User accounts and the audit trail | **Restricted** | Password hashes never leave the database and appear in no API response. The audit trail is append-only and names people and their actions — a security record and an employee record at once. |
| Certifications and signatures | **Restricted, high integrity** | The record of what your agency told the federal government, signed. Integrity matters more than confidentiality here: these are tamper-evident by design and must never be quietly altered. |
| Raw ingested records (object store) | **Inherits the highest class of its contents** | Raw bytes are kept immutable and content-addressed. A raw paratransit export is as sensitive as the trip records inside it — classification follows the payload, not the storage layer. |
| Configuration, thresholds, branding | **Internal** | Includes basis citations; useful to auditors, boring to everyone else. Note that `deploy/compose/.env` holds this installation's passwords and signing key and is the one file to guard closely. |

## Five things a governance program should decide

1. **Who may see paratransit coordinates**, and under what workflow. Headway's default is
   "not the analyst role" — a floor to build on, not a policy.
2. **Whether driver-identified telematics is collected at all**, and if so, under what
   notice, agreement, and retention. Default: not collected.
3. **How long each class lives**, with the authority cited (ADR-0012). The federal floor
   for NTD source documentation is three years, quoted from the 2026 manual; state and
   local schedules may require longer, and some categories carry destruction obligations.
4. **What is disclosable on request** — in public-records jurisdictions, what still exists
   is generally disclosable, which is why over-retention is its own exposure.
5. **Who holds the hats** when there is no records officer: name the person who answers
   the auditor's "what is your retention policy?" question, even if that person is
   borrowed from HR, IT, or counsel.

## When the right people *do* need employee-linked data

Minimization is not prohibition. There are real duties that require knowing which person
was on which vehicle, and a platform that made them impossible would just push the work
into spreadsheets nobody audits. The cases, honestly stated:

1. **Operator safety and duty of care.** When a vehicle stops where it should not, or an
   alarm is raised, dispatch has to know who is on it. This is the strongest case and it
   is about protecting the employee, not watching them.
2. **Safety & security reporting.** Federal S&S reporting includes injuries to employees;
   the platform already holds safety events, and some of them are inherently about
   identifiable people.
3. **Explaining service, and defending the operator.** Provenance cuts both ways. An
   audited record showing a run was late because of a bridge lift — not the person
   driving — is a defense, and grievance processes turn on exactly that kind of evidence.
   Systems that only ever accuse are systems employees are right to distrust.
4. **Distinguishing revenue service from everything else.** Block and run assignment is
   how deadhead is separated from revenue service. Note that this needs the *assignment*,
   not usually the *person* — see the pattern below.
5. **What is deliberately NOT a Headway purpose:** payroll, discipline scoring, and
   driver-behavior league tables. If an agency wants those, its telematics vendor already
   sells them; this platform is not the place, and saying so plainly is what makes the
   other four defensible.

**The pattern that makes later exposure safe** — designed now, built when an agency asks:

- **Aggregate by default, identify on purpose.** Analysis runs on blocks, runs and
  vehicles. Resolving one of those to a person is a separate, deliberate step — not a
  column that happens to be joinable by anyone with database access.
- **Purpose-bound access, not blanket role access.** Viewing operator-identified data
  means selecting a stated purpose (safety incident, grievance, S&S report) and having
  that choice recorded. This is ordinary practice in HR and clinical systems and it is
  the right shape here.
- **Every look is audited, in an append-only trail.** This is the part that earns union
  trust rather than asking for it: an agency can demonstrate exactly who accessed
  operator-identified data, when, and under what stated purpose — and cannot quietly edit
  that record afterwards.
- **A distinct role,** separate from data stewards and analysts, granted narrowly.
- **Shorter retention** for employee-identified data than for the operational data it
  derives from, per the agency's schedule (ADR-0012).
- **Bargaining and notice come first.** In a unionized workplace, new employee monitoring
  is frequently a mandatory subject of bargaining. Nothing here should ever switch itself
  on, and this page exists partly so an agency can hand the union a straight answer about
  what is collected and who can see it.

## What the platform does about it today, without waiting for a program

- **Column-level withholding** of the most sensitive fields from the analyst read path.
- **Data minimization at the connector boundary**: fields not needed for a stated purpose
  are not requested and not stored.
- **No silent destruction**: retention defaults keep, and an unset policy is surfaced as
  an open item rather than resolved by a vendor default.
- **Provenance that survives deletion**: when a record is lawfully purged, a tombstone
  records that it existed, when it went, and under which authority — so a figure remains
  explainable after its source is gone (ADR-0012).
- **Everything stays on the agency's own computer**: no telemetry, no phone-home, no
  vendor copy. What you hold is what exists.
