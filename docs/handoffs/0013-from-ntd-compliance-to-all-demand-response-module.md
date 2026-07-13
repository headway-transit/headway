# Handoff: ntd-compliance-engineer → ingestion, transform, calc, backend, frontend — Demand Response / on-demand module v0 (queued behind handoffs 0011 + 0012)

## Context
DR definitions verified 2026-07-12 (tracker: "Verified — Demand Response / on-demand reporting"). Every fixed-route urban operator legally runs ADA complementary paratransit, so DR reporting is a mandatory report section for the whole target market; on-demand microtransit (Via-class TNC/TX contracts) reports under the same mode with TOS-specific rules. DR data originates in dispatch platforms, NOT GTFS-RT — this module adds Headway's second data-source family. DO NOT start this build until handoffs 0011 (PMT, in flight) and 0012 (sampling, queued) have landed — shared files in services/calc.

## Design (binding)
1. **Wire contract (contracts/, ADR-0006 discipline):** `demand_response_trip` record — trip_id, vehicle_id, mode (DR), tos (DO|PT|TX|TN), request/dispatch/pickup/dropoff timestamps, pickup/dropoff locations, odometer or GPS distance for the passenger-onboard segment(s), passengers (riders, attendants_companions — non-employee rule), ada_related flag, sponsored flag (+ sponsor label), no_show flag, interruption markers (lunch/fuel/garage-return), driver-shift/dispatching-point references for deadhead legs. Versioned, documented, vendor-neutral; a Via-style CSV export maps onto it as the worked example in docs (adapter code optional, docs mandatory).
2. **Intake (ingestion/backend):** reuse the TIDES pattern — file-drop connector + authenticated machine-API push (`POST /ingest/dr/trips`), content-addressed raw records, envelope wire contract, store-before-produce. Simulator (tools/, like tides-simulator) generating spec-valid dispatch days incl. no-shows, interruptions, multi-passenger shared rides, defect-injection flags. SIMULATED source labeling rules identical to TIDES.
3. **Canonical (migration 002x + transform):** canonical.dr_trips (+ segments if needed for TX passenger-onboard-only accounting), per-row lineage.
4. **Calcs (services/calc, each with tracker rows + goldens from the quoted rules):**
   - `dr_vrh/dr_vrm v0`: Exhibit 36 semantics — revenue span from first pickup to last dropoff per vehicle-day, BROKEN by garage/dispatch returns and lunch/fuel interruptions; empty travel between consecutive passengers = revenue; no-show trips = revenue; deadhead legs per the six quoted leg types; TX variant: passenger-onboard time/distance only; TX/TN/VP report no deadhead. Goldens: every Exhibit 36 row as a fixture; a hand-worked vehicle-day.
   - `dr_upt v0`: riders + non-employee attendants/companions; ADA-related split (included in total, never sponsored); sponsored split (included in total). No-shows are NOT boardings (revenue time yes, UPT no — the asymmetry deserves an explicit golden).
   - `dr_voms v0`: max simultaneous vehicles in revenue service INCLUDING atypical days (divergence from voms_v0's non-DR exclusion — do not reuse blindly). Golden: Exhibit 40 Happy Transit (6 unique, 4 simultaneous → 4).
   - DR PMT: passenger-onboard distance sums from the wire contract's distances (feeds pmt_v0's persistence/mode scoping; no load-profile reconstruction needed).
5. **API/UI:** trips land in existing metrics/receipt surfaces; one DR-specific UI affordance only — the mode/TOS badge and TX/TN rule callouts on receipts (quote-extract pattern; extend section map for the DR tracker section). Honest-scope banners: no vendor integrations shipped, wire contract + simulator only.
6. **Honest scope:** shared-vehicle multi-agency rule and PT full-cost/buyer-reports rules are documented guidance (copy + docs), not silent logic; TX "voucher programs are not public transportation" surfaced as an intake validation hint.

## Outputs
Wire contract + docs, intake path live-verified (simulator → machine API → canonical via psql), four calcs with Exhibit-36/40 goldens, live end-to-end DR figures (or honest refusals) from a simulated dispatch day, suites green, tracker rows, evidence here.

## Open Questions
- Real vendor adapters (Via Connect export field mapping first) — needs a real export sample; ROADMAP.
- GTFS-Flex service-description ingestion (D5) — complementary, separate increment.
- DR-specific dashboard views (response times, shared-ride rate) — ops analytics tier, after OTP/headway-adherence wave.
