# Handoff: platform → frontend — The living map + audience lenses (the showpiece wave, frontend half)

## Context
Project lead direction (2026-07-21): take the UI to the next level — make people *want*
to use it. Handoff 0023 (backend half — read its evidence section before starting) ships
the data: `/ops/vehicles/latest`, `/geometry/stops`, `/geometry/routes` (schematic,
self-labeled), `/metrics/history` (bucketed, verbatim), and sub-second DQ counts. This
wave is the visible payoff: the first screen that *draws* the transit system, and the
dashboard learning to speak to boards, executives, and ops supervisors at their own
altitude. Inspiration (Domo-class polish), never imitation — and never at the cost of an
honesty surface.

## Design (binding)

1. **`/map` — the living system view.** MapLibre GL JS (BSD-3 — verify the license and
   satisfy the CI license gate) rendering ONLY self-hosted data: stops and schematic
   route lines from the /geometry endpoints, live vehicles from `/ops/vehicles/latest`
   polled at the endpoint's documented interval. **No external tile/font/sprite requests
   of any kind** — the no-phone-home posture extends to maps; the background is a styled
   solid/water-tone canvas, and the network tab must prove zero third-party requests.
   - The schematic honesty is VISIBLE: a legend line stating route lines are schematic
     (straight lines between stops), mirroring the endpoint's `geometry_kind`.
   - Vehicle affordances: hover/click → popover with route/trip context, position age
     ("as of Ns ago"), and the SIMULATED badge whenever the source row carries the flag.
   - A staleness chip that degrades honestly: "Live — as of HH:MM:SS" while fresh; when
     the feed goes quiet, say so plainly ("no positions in the last N min") — never fake
     motion, never interpolate positions.
   - Ops boundary on the surface itself: the map is badged as operational insight (reuse
     OpsBadge/precedent from 0014), never certified figures.
   - Motion rules from 0021 stand: `prefers-reduced-motion` means markers jump, not
     glide; nothing bad-news ever animates cutely.
   - Empty state teaches (0021 pattern): no vehicles in window → what that means and how
     an agency gets its first dot on the map.
   - Nav placement + a tour step if it fits the existing 5-step tour without bloating it
     (your call; record it).

2. **Audience lenses on the dashboard.** A period selector (day / week / month / quarter)
   driven by `/metrics/history`'s bucket param — **grouping and framing only, never
   client-side arithmetic**: every figure shown is a persisted figure verbatim, deltas
   only via the existing server-computed `/metrics/compare`. Three named presets that are
   just lens configurations (and say so): **Board** (quarter grouping, certified figures
   emphasized), **Executive** (month), **Operations** (day, ops cards forward). Sparkline
   trends on KPI cards where history exists — points are real figures, each clickable to
   its receipt; gaps render as gaps (a missing month is visible absence, not
   interpolation).

3. **Cash in the speed.** Handoff 0021 deviation 2 consumed `/dq/issues/counts`
   per-status-only because of the ~5s query. With 0023's fix live, consume the counts
   properly on /today and /dq, delete the workaround, and re-measure /today first paint
   (budget stands: under 1s; record the number).

4. **Honest scope:** no historical playback/time-scrub (v1 — Open Questions); no
   geocoding/search-the-map; no OTP coloring of vehicles (prediction-accuracy work is
   its own increment); no layout upheaval of existing views; no changes outside `web/`
   (+ this handoff file + docs screenshots if you capture them).

## Outputs
Tests (component + interaction; axe green; contrast pairs pass) + full web suite green;
`npm run build` clean; live click-through in headless Chrome through real login as at
least two roles (map interactions: popover, staleness chip, legend; dashboard: all three
presets + bucket switching + receipt-from-sparkline), screenshots captured; network-tab
proof of zero external requests on /map; /today first-paint re-measurement; evidence
appended here. No commits — the orchestrator integrates and commits.

## Open Questions
- Time-scrub playback (yesterday's service replayed on the map) — the natural v1 demo
  feature once retention policy lands.
- True street geometry pending shapes.txt ingestion (0023 Open Questions) — the legend
  line simply gets better.
- Per-mode dark brand variants (standing queue item) — separate small wave.
- Map screenshot into README hero once the view exists.

## Outputs — evidence
(appended by the implementing agent)
