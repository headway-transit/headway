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
