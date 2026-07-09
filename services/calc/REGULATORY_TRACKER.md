# Regulatory-Change Tracker — headway-calc

The durable memory mapping every calculation (and version) to the authoritative
source it implements. **Rule: no calculation version ships without a row here,
and no regulatory number enters code from memory** — every definition,
threshold, and rounding convention is a pointer to a published source that must
be verified against the current reporting-year guidance before implementation.
Changing calculation logic mints a new version and a new row; shipped versions
are never deleted or rewritten.

| calc_name | version | What it implements | Citation (pointer — verify, never from memory) | Verification status | Source version verified / date |
|---|---|---|---|---|---|
| vrm_v0 | 0.1.0 | Vehicle Revenue Miles approximation: haversine distance summed between consecutive vehicle positions grouped by (vehicle_id, trip_id); trip assignment used as revenue-service proxy; fail-loud telemetry-gap rule (default 300 s, explicit input); Decimal quantized 0.01 mi, ROUND_HALF_EVEN (engineering placeholder) | FTA NTD definitions of Vehicle Revenue Miles/Hours — FTA NTD Reporting Manuals (current reporting year) | PRE-VERIFICATION — walking-skeleton approximation (position-derived, trip-assignment as revenue proxy, no deadhead handling). MUST be verified against the current published FTA NTD Reporting Manual before any figure is treated as reportable. | none / not yet verified |
| vrh_v0 | 0.1.0 | Vehicle Revenue Hours approximation: time deltas summed between consecutive in-trip vehicle positions, same grouping and fail-loud gap rule as vrm_v0; Decimal quantized 0.01 h, ROUND_HALF_EVEN (engineering placeholder) | FTA NTD definitions of Vehicle Revenue Miles/Hours — FTA NTD Reporting Manuals (current reporting year) | PRE-VERIFICATION — walking-skeleton approximation (position-derived, trip-assignment as revenue proxy, no deadhead handling). MUST be verified against the current published FTA NTD Reporting Manual before any figure is treated as reportable. | none / not yet verified |
| vrm_v0 | 0.2.0 | Gap policy per handoff 0002: same distance semantics as 0.1.0, but a (vehicle_id, trip_id) group containing a gap > gap_threshold_seconds (explicit input, default 300 s) is EXCLUDED from the figure (one warning DQ finding 'telemetry_gap_excluded' per group, citing all its records); coverage = clean_groups/total_groups (clean-position share also reported) carried in the persisted detail JSONB; run refuses (ONE blocking 'coverage_below_threshold' finding, value None, nothing persisted) when coverage < coverage_threshold (explicit input, default 0.95 — an ENGINEERING PLACEHOLDER, not an FTA number); input_record_ids/lineage cover included groups only; coverage ratios quantized 0.0001 ROUND_HALF_EVEN (engineering convention); 0.1.0 retained runnable (compute_vrm_v0_1) | FTA NTD definitions of Vehicle Revenue Miles/Hours and completeness/sampling expectations — 2025 NTD Full Reporting Policy Manual (current reporting year) | PRE-VERIFICATION — verification ATTEMPTED 2026-07-10 and BLOCKED: transit.dot.gov returned 403 (bot-blocked) for both HTML and PDF from this environment (handoff 0002). The 2025 NTD Full Reporting Policy Manual must be obtained and the VRM/VRH/deadhead/layover definitions QUOTED here before any figure from this calculation is treated as reportable. The 0.95 coverage_threshold default is an engineering placeholder pending FTA completeness/sampling guidance and per-agency configuration. | none / attempted 2026-07-10, source unreachable (403) |
| vrh_v0 | 0.2.0 | Gap policy per handoff 0002: same duration semantics as 0.1.0 with per-group exclusion + coverage identical to vrm_v0 0.2.0 (warning 'telemetry_gap_excluded' per excluded group; blocking 'coverage_below_threshold' below coverage_threshold, default 0.95 — ENGINEERING PLACEHOLDER; detail JSONB with coverage/threshold provenance; lineage over included groups only); 0.1.0 retained runnable (compute_vrh_v0_1) | FTA NTD definitions of Vehicle Revenue Miles/Hours and completeness/sampling expectations — 2025 NTD Full Reporting Policy Manual (current reporting year) | PRE-VERIFICATION — verification ATTEMPTED 2026-07-10 and BLOCKED: transit.dot.gov 403 for HTML and PDF (handoff 0002). The 2025 NTD Full Reporting Policy Manual must be obtained and the VRM/VRH/deadhead/layover definitions QUOTED here before any figure is treated as reportable. Coverage threshold 0.95 is an engineering placeholder, not an FTA number. | none / attempted 2026-07-10, source unreachable (403) |

## Open verification items (owner: NTD & Compliance Engineer)

- Revenue-service inclusion and deadhead exclusion for VRM/VRH: verify against
  the current published FTA NTD Reporting Manual for the applicable reporting
  year; record the manual version and verification date here before minting
  any post-v0 version.
- Rounding/unit conventions for reportable VRM/VRH: v0's 0.01 quantum with
  ROUND_HALF_EVEN is an explicit engineering placeholder, not a verified FTA
  convention — verify and cite before reportability.
- Trip-distance authority (shape-based vs position-derived) is deferred to
  slice 2 per handoff 0001; v0 uses position-derived haversine, flagged here
  and in the calc docstrings.
- **2025 NTD Full Reporting Policy Manual access (blocking all 0.2.0
  verification)**: a verification attempt on 2026-07-10 was bot-blocked
  (transit.dot.gov returned 403 for both the HTML page and the PDF from this
  environment — handoff 0002). The manual must be supplied by the repo owner;
  the VRM/VRH/deadhead/layover definitions must be quoted in this tracker
  before any 0.2.0 figure is treated as reportable. Both 0.2.0 rows stay
  PRE-VERIFICATION until then.
- **coverage_threshold default (0.95)**: an engineering placeholder chosen for
  calc 0.2.0's certifiability line, NOT an FTA number. FTA
  completeness/sampling expectations must be verified against the current NTD
  Policy Manual before this default is treated as more than a placeholder;
  ultimately per-agency configuration (handoff 0002 open question, owner: NTD
  role, then Backend for the config surface).
