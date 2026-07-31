# Handoff: platform → transform+calc+backend+frontend — Revenue classification of boardings (no-run detection + human-in-the-loop review)

## Context

A live diagnostic with the partner agency's ITS manager (2026-07-31, over a real
full-day APC export) cracked open a real ridership-accuracy problem — and turned it
into one of the strongest "explain this number" features on the roadmap.

**The finding.** ~3.3% of the export's boardings sit on rows that carry **no run
assignment at all** — trip, route, stop, direction and stop-sequence are all NULL.
The APC counter fired on a vehicle at a moment the system had it tied to no trip.
Plotted against real assigned ridership by hour, these "ghost" boardings cluster
hard at the **start of the service day** (the pre-service hour has ~3x more ghost
than real boardings) and the **end** (after the last trip, ghost boardings with zero
real ones), and are sparse through midday. The ITS manager identified them
immediately: **drivers and staff boarding during prep, pull-out and pull-in** —
dropping items off, prepping the bus, maintenance — while the vehicle is moving with
the APC on but not logged into a run.

**The reframe.** A vehicle not logged into a run **is not in revenue service**, so
these boardings are **not unlinked passenger trips**. Excluding them is not a hack —
it is the NTD-correct treatment. This **inverts** the earlier plan (which was to
count all unassigned boardings so Headway's total matched the agency's raw APC
total): the agency's raw total is the one that is inflated, by counting non-revenue
prep activity. Headway's value is to separate real ridership from prep-time noise
**with the receipts to prove it**, so the reported figure is defensible.

**Detours are NOT the cause, and need no fix.** The export's detour flag is used
correctly: detour-flagged boardings — including riders picked up at the temporary
stops that stand in for a detoured route — carry a **full trip and stop** and count
as normal ridership. Detour handling is already right; the only opportunity is to
**surface** the flag so an analyst can see which ridership occurred during a detour.

**The residual.** A small set of no-run boardings occur mid-service (a handful of
rows on one or two specific vehicles, larger-than-usual counts). These fit neither
prep nor detour — genuinely ambiguous, and the poster child for **a human should
look at this one**.

**Supersedes / relates:**
- Replaces the earlier "count off-designated-stop boardings toward UPT" direction —
  the diagnostic showed those rows are non-revenue prep, not off-stop riders.
- The same rows are why the adapter currently quarantines on NULL `PatternPointRank`
  (a loud but lossy ~3.3% drop). This wave changes that quarantine into
  classification.
- Header-tolerance for these exports already shipped (`skip_optional_header`,
  2026-07-31); the confirmed DirectionKey→direction_id mapping also shipped.

## Design (binding)

1. **Stop quarantining no-run boardings; emit them for classification.** A boarding
   whose row resolves to no run (the fully-unassigned case) is emitted as a
   passenger event marked with an explicit assignment/revenue **status** — never
   silently dropped and never silently counted. Additive contract change on
   `tides_passenger_events` (a `revenue_classification` / assignment-status field);
   the normal assigned path is unchanged.

2. **Derive revenue-service windows from the GTFS schedule Headway already ingests.**
   The first and last scheduled trip per route/service define the revenue window — no
   new ingestion. This is a **corroborating** signal, not the sole rule: the primary
   discriminator is the **no-run assignment itself** (only a few ghosts fall strictly
   before the first trip; most are interspersed but still unassigned).

3. **Auto-classify the clear cases**, so humans only ever see the genuinely ambiguous:
   - no-run **and** outside the revenue window (prep / pull-in) → suggested
     **non-revenue**, reason recorded, excluded from UPT;
   - detour-flagged with full attribution → **revenue**, tagged "during detour"
     (counts, surfaced);
   - normal assigned → **revenue**.

4. **Route the residual to a human-in-the-loop review queue**, built on the existing
   DQ resolution workflow (handoffs 0029/0030 — owners, status, notes). Unclassified
   boardings surface with full context (vehicle, time, count, why flagged). The
   analyst marks each **revenue / non-revenue** and **writes a justification note**
   (who, when, why — e.g. "unit's counter double-fired during layover, confirmed with
   dispatch"). That note becomes part of the figure's receipt: "explain this number"
   now includes the human judgment calls, auditable.

5. **UPT excludes non-revenue-classified boardings.** The metric detail records the
   split — revenue / excluded-non-revenue / pending-review — and links the human
   justifications. **Pending-review boardings are held out of a certifiable figure
   until classified** (a boarding of unknown revenue status must not silently inflate
   or deflate a certified number); the default-until-reviewed policy is stated, not
   assumed. Do not let excluded boardings participate in the missing-trip factor
   (no double-count).

6. **Surface the detour flag** on ridership for transparency (analysts can see
   detour-time boardings even though they already count).

7. **NTD verification (quote-or-own-it):** quote the FTA revenue-service / UPT
   definition into `services/calc/REGULATORY_TRACKER.md` before this governs a
   certified figure — the exclusion of non-revenue boardings must rest on the
   manual's own words, not our inference.

## Outputs

Additive contract change + adapter change (no-quarantine → status) + schedule-window
derivation + calc classification/exclusion + the review-queue UI with justification
notes + detour-flag surfacing; tests at every layer; NTD tracker quote; evidence.
A wave of this size decomposes into sub-waves (contract+adapter first, then
schedule/calc, then the review UI) — sequence them, keep each green.

## Open Questions

- **Default policy for pending-review boardings** — exclude-until-classified (the
  conservative, recommended default) vs include-with-flag? Agency-configurable?
- **Root-causing the mid-service residual** — a specific vehicle's counter firing
  off-run is also a maintenance signal; worth its own DQ finding to the fleet team?
- **Revenue window edge cases** — a route with no schedule (shouldn't happen for
  fixed route), and service that spans midnight (ties into the still-unconfirmed
  service-day rollover in `resolution.v0.yaml`).
- **Reconciliation reporting** — a view that shows the agency the *difference*
  between their raw APC total and Headway's revenue-only total, with the excluded
  non-revenue and the human notes, so the correction is transparent (this is the
  "over-reporting" conversation, made defensible rather than accusatory).
