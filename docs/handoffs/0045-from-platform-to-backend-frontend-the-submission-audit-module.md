# Handoff: platform → backend+frontend — The submission audit module (self-audit first)

## Context

GTFS feeds are public. NTD data is public. Between them sits an obvious and
genuinely valuable question nobody has packaged well: **does an agency's
reported service actually reconcile with the service its own schedule
describes?** That is what a triennial reviewer works out by hand.

**The idea came from the project lead (2026-08-02) and it is a strong one.** It
is also the single easiest feature in this product to get *ethically* wrong, so
the design below is as much about framing as about arithmetic.

**The decisive reframe: point it at yourself first.** The primary product is an
agency running this against **its own submission before filing** — "here is what
a reviewer will find, before they find it." That version sells itself, is used
by the person who can actually act on it, and carries no reputational hazard.
The same engine pointed outward, gated to people with real audit authority, is
the *second* deliverable, not the first.

**Why the sequencing is not merely tactical.** Transit is a small, tight-knit
industry, and Headway's adoption depends on agencies trusting it. A tool that
arrives as "the thing that accuses your peers" is a tool agencies keep out of
the building. Proving the engine on the friendly case first is how it earns the
right to be pointed anywhere else.

## Design (binding)

### 1. What is actually derivable — and what is not

- **From GTFS:** *scheduled* VRM and VRH (from `shapes.txt` + `stop_times`), and
  VOMS (peak concurrent scheduled vehicles). These are schedule-derived, and the
  module must say so in those words every time it shows one.
- **NOT from GTFS: UPT.** There is no ridership in a GTFS feed. Any module that
  appears to check reported ridership against a schedule is fabricating, and
  fabrication is the one thing this platform does not do. **UPT is checked only
  for internal consistency** (below), never against the schedule.
- **From published NTD data:** the agency's own reported UPT/VRM/VRH/VOMS by
  mode and month.

### 2. A discrepancy is NOT an inaccuracy, and the module never says it is

Reported actuals legitimately differ from schedule: deadhead is excluded, trips
are missed, actual service is not the published timetable, and a detour changes
miles. **The output is always of the form "these two public figures do not
reconcile; here is the arithmetic and here are the ordinary reasons that gap
exists"** — never "this figure is wrong," and never a score, grade, or ranking.

Every finding states the honest alternatives, including "the schedule is stale"
and "this is normal for this service type." A finding an agency can dismiss with
one sentence of local knowledge is a *good* finding, not a failed one.

### 3. The strongest signals are internal, not schedule-vs-actual

Cheapest to compute, hardest to argue with, and closest to what reviewers
actually look for:

- **Flat-lined values** — the same figure repeated month over month (the
  signature of copy-paste reporting).
- **Implausible derived ratios** — UPT per VRM, VRM per VRH (average speed),
  passengers per VOMS — outside a stated band **for that mode**.
- **Year-over-year step changes** with no corresponding service change in the
  schedule.
- **Suspiciously round numbers** where the measurement method could not produce
  them.
- **Arithmetic that does not close** — modes not summing to the reported total.

Each check names its own basis and its own band, and the band is a **stated
engineering default, not a regulation**, unless it is quoted from the manual —
same rule as `DETECTOR_THRESHOLDS.md`.

### 4. Self-audit is the primary surface

A "check my submission" run over the agency's own figures, producing findings in
the existing DQ vocabulary (subject refs, owners, notes, resolution workflow —
handoffs 0029/0030), so it inherits a workflow people already know. A finding
here is a **question to answer before filing**, and answering it with a note is
a complete, legitimate outcome.

### 5. The outward view is gated, second, and role-bound

The same engine over published data for agencies other than your own is visible
**only to `admin` or a new `auditor` role** — not to viewers, not to stewards,
and never on any public page. It is off by default. Every outward run is
audited: who ran it, over whom, when.

**The `auditor` role is added by handoff 0046 (identity), not here** — a role is
worth adding once, alongside the identity work, rather than twice. This wave
therefore ships the self-audit surface and the engine; the outward view lands
when the role exists.

### 6. Provenance, exactly as everywhere else

Every audit finding cites the public sources it used — which NTD publication,
which GTFS feed and feed version, fetched when — with the same lineage rigor as
a computed figure. An audit finding without its receipt is an accusation, which
is precisely what this module must never produce.

### 7. Ingest of public data is consent-first and offline-honest

Fetching NTD publications or third-party GTFS is an **outbound network request**
from an on-prem product that promises none. It is opt-in, consent-before-contact
(the `--download-basemap` precedent, handoff 0027), the fetched artifact is
stored as a raw record like any other input, and an installation that never
enables it loses no existing capability.

## Outputs

The check engine (internal-consistency checks first, schedule-derived
reconciliation second) + the self-audit surface built on the DQ workflow +
public-source ingestion with consent + provenance on every finding + the FTA
quotes for anything asserted as a rule; tests including **fixtures that prove a
legitimate gap is NOT reported as an error** (a deadhead-heavy agency, a stale
schedule); operator-facing copy written for a zero-SQL reader; evidence.

Sequence: internal-consistency checks over the agency's own figures (no external
fetch at all) → schedule-derived reconciliation → the gated outward view once
the `auditor` role exists.

## Open Questions

- **Where do the ratio bands come from?** Published NTD distributions would be
  defensible but need derivation and a stated vintage; engineering defaults are
  honest but weaker. (Recommended: engineering defaults in v0, clearly labelled,
  with the derivation as a follow-up — never an unlabelled band.)
- **How stale may a GTFS feed be before schedule-derived comparison is refused
  outright** rather than caveated? A schedule from before a service change makes
  every comparison meaningless.
- **Does the outward view need a "notify the agency" path**, or is it
  read-only intelligence for someone who already has authority to ask? (Strong
  recommendation: read-only. Headway must not become a machine that sends
  accusations.)
- **Is "auditor" one role or two** — an internal auditor at the agency versus an
  external reviewer with cross-agency reach? They have different blast radii.
