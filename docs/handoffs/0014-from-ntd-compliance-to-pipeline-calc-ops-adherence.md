# Handoff: platform/ntd roles → transform, calc, backend, frontend — Ops analytics v0: headway adherence + on-time performance (READY, not yet launched)

## Context
The platform is named Headway and does not yet measure headway. GTFS-RT trip updates are ingested as raw records but never normalized (feature-gap report #8, "data already held"); vehicle_positions + (since migration 0019) canonical stops/stop_times give scheduled AND observable actual stop passage. These are OPERATIONS metrics, not NTD reported figures — a new honesty boundary this handoff must draw explicitly.

## Design (binding)
1. **Honesty boundary first:** ops metrics are NOT regulatory figures. They must be persisted with `category='ops'` (or equivalent) such that they can NEVER appear in the certification cockpit, the MR-20/S&S packages, or /public/metrics/certified. Their receipts cite an industry basis (TCRP Transit Capacity and Quality of Service Manual definitions — quote what we can verify from public sources; if a definition cannot be verified from a source ON FILE or fetchable, state the metric is a Headway operational definition, versioned, with the formula shown), never an FTA manual page. No new REGULATORY_TRACKER rows — instead a parallel `services/calc/OPS_DEFINITIONS.md` with the same quote-or-own-it discipline.
2. **Canonical trip_updates (migration 0022 + transform):** normalize GTFS-RT TripUpdate stop-time events (predictions with timestamps, per trip/stop_sequence, feed timestamp preserved — predictions are PREDICTIONS; label them so) with lineage, replay fixtures. Live-replay the raw MBTA trip_update records already in MinIO/Kafka.
3. **Observed stop passages:** derive actual arrival/passage events from vehicle_positions proximity to canonical stops per trip (deterministic, versioned derivation with documented geometry tolerance; store as a derived canonical table or calc-internal — smallest honest design wins; document the choice). MBTA position cadence limits precision — measure and report the observed inter-position gap distribution before choosing tolerances; refuse per-stop OTP where cadence can't support it (the gap-policy discipline applies to ops metrics too).
4. **Calcs (ops-labeled, versioned like everything else):** `otp_v0` — % of observed timepoint passages within a CONFIGURABLE window (default from a verifiable public basis if one exists; else Headway-defined default, clearly labeled, per-agency app.settings knob with provenance like coverage_threshold); `headway_adherence_v0` — observed vs scheduled headway per route/stop/period (headway CV or excess wait time; pick ONE well-defined v0 formula, show the math in OPS_DEFINITIONS.md). Goldens hand-worked; property tests.
5. **API/UI:** ops metrics served under an /ops or metrics category distinction; dashboard cards (route-level OTP, headway adherence over time) using the existing chart components + dataviz palette discipline; every ops figure visually distinct from NTD figures (badge: "Operations metric — not an NTD reported figure"); SIMULATED/coverage caveats as usual.
6. **Live verification:** end-to-end against the MBTA data already held; report real OTP/adherence numbers (or honest refusals with the cadence evidence).

## Outputs
Migration + normalizer live-replayed, derivation + two calcs with goldens, OPS_DEFINITIONS.md, API/UI surfacing, live numbers, suites green, evidence here.

## Open Questions
- TCRP TCQSM quotes: fetch/verify public excerpts or own the definitions — decide at implementation, document either way.
- Excess wait time vs headway CV as the v1 second formula.
- Prediction-accuracy metrics (trip_update predictions vs observed passages) — natural v1 once both tables exist.
