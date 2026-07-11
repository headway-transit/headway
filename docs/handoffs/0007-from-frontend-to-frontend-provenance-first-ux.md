# Handoff: frontend-engineer → frontend-engineer — Provenance-first UX ("every number is a door")

## Context
Headway's UI is honest but spartan; its differentiator — total provenance — renders as nested lists. The redesign inverts the transit-dashboard convention: instead of charts that hide uncertainty, **provenance becomes the interface**. Radical honesty, not decoration; WCAG 2.1 AA and plain language remain non-negotiable (constraint 6).

## Design pillars (binding)
1. **The Receipt.** Every displayed figure is interactive. Opening it shows, in order: (a) plain-language story ("12,794.92 miles of revenue service across 2,540 vehicle-trips, July 9–10"); (b) a coverage meter (accessible, text+visual) with exclusions stated ("covers 92.63% — 202 vehicle-trips excluded and documented"); (c) **the FTA rule inside the number**: the verbatim manual quote + page citation for the calc version that produced it (source: `REGULATORY_TRACKER.md` quotes — shipped to the UI as a static, versioned JSON extracted from the tracker at build time; NEVER paraphrased, NEVER generated); (d) flags (simulated/pre-verification/anomaly) with their meanings; (e) the door onward: "walk this number to its raw records."
2. **The lineage walk, drawn.** `/metrics/:id/lineage` becomes a visual graph: metric node → transform node (calc name+version) → raw-record leaves, rendered as an accessible SVG flow (collapsible tiers, counts on collapsed groups — "326 raw records", expand pages of 20). Keyboard-navigable (arrow keys tier-to-tier, Enter expands), with a parallel text tree (the current list) always one toggle away — the graph is progressive enhancement, never the only path.
3. **Design system.** Adopt React Aria Components as the accessible foundation (role file's deferred increment): tokens (existing AA-verified palette), Meter, Disclosure, Dialog, Tabs, focus management. Hand-rolled patterns retired as views migrate; contrast script remains the gate.
4. **Numbers stay sacred:** values render verbatim (string), meters/percentages via the string-only decimal-shift helpers; no arithmetic, ever.

## Scope — tonight's increment (Receipt + Graph)
- `web/src/regulatory/quotes.json` + a small extraction script (`web/scripts/extract-quotes.mjs`) reading `services/calc/REGULATORY_TRACKER.md`'s "Verified definitions" quotes into `{calc_name → [{quote, citation}]}`; CI-able; build fails if a calc named in code lacks quotes rather than shipping silence.
- `Receipt` component replacing/absorbing `MetricDetail` per pillar 1; wired into Metrics view + Monthly report.
- `LineageGraph` view per pillar 2 (SVG, no charting dependency needed for v1; if one is added it must be permissive-licensed).
- React Aria Components adoption for the NEW components (existing views migrate opportunistically, not big-bang).
- Certification cockpit is TOMORROW's increment (pillar for it drafted here: one screen showing exactly what a signature covers).

## Verification
- npm build + full vitest (existing 37 + new) green; axe on Receipt + LineageGraph; contrast gate green; keyboard paths tested (graph tier navigation, receipt disclosure); quotes.json extraction verified against the real tracker file.

## Open Questions
- Charting library adoption for future dashboards (defer; dataviz pass planned for daylight).
- Cockpit interaction with webhook/publish surfaces — tomorrow.
