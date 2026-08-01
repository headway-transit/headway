# Transit UI/UX comparative survey — sharpening the forensic-instrument direction

Status: **survey / design input, not built.** Authored 2026-08 as a comparative
UI/UX scan to sharpen the visual direction established by the 0041 design-sync
(control-room / forensic-instrument aesthetic) and its map landing (handoff 0043).
This feeds handoff `docs/handoffs/0041-...` (the design-forward UI wave) and its
map follow-on. Everything here is subordinate to
`.claude/roles/_SHARED_CONSTRAINTS.md` and the non-negotiables restated in §1.

Findings are grounded in real, current products with cited sources. Where a
specific UI detail could not be verified, it is marked **unverified** rather than
fabricated. Agency anonymity is preserved throughout (generic terms only).

---

## 1. Purpose & scope boundary

Headway is an **internal compliance & telemetry instrument** for transit-agency
staff — ITS managers, data analysts, NTD/FTA report preparers, auditors. Its job
is to **report what DID happen, provably**: verbatim figures with full provenance
("explain this number" → lineage → raw records → quoted FTA definition), refusals
over guesses, and gaps drawn as gaps.

This survey is scoped to that job. Two things Headway is **NOT**, which bound what
we borrow:

- **NOT a rider-facing trip-planner.** Wayfinding is a different problem. We mine
  the rider apps in Bucket A for *map craft* (legibility, mode iconography,
  live-mark rendering, zone UIs) — never for their trip-planning flows or their
  consumer reassurance patterns.
- **NOT a planning/optimization tool.** Demand-density heatmaps and "where to add
  service" are a **separate Phase-2 initiative, out of scope** (handoff 0043 §8
  keeps this boundary crisp). We borrow ops-tool *density and authority*, never
  their optimization/what-if framing.

**Design direction being sharpened (not re-litigated):** control-room / forensic
instrument — "Vignelli transit-diagram × avionics data-density, executed FLAT."
Obsidian matte ground, hairline etching (no bevels / skeuomorphism), ONE
signal-orange identity accent, a CVD-safe semantic status set (ok / watch / alert)
kept **separate** from identity, monospace tabular-nums for figures/receipts,
honest attention-"glow" (halo on the **frame** of flagged items only, never on
figures), coordinated multi-panel views, a live provenance terminal.

**Non-negotiables (they are the product):** WCAG 2.1 AA floor, CVD-safe palette,
on-prem / zero-external-dependency (self-hosted map tiles + fonts), honesty
(numbers never animate to mislead; reconstruction ≠ observation).

---

## 2. Bucket A — rider / microtransit map craft

Mined for map legibility, mode iconography, live-vehicle rendering, and
service-zone UIs. Not for trip-planning flows.

### Transit (transitapp.com)
- **Does well:** best-in-class auto-generated map craft. Bundled parallel routes
  are drawn cleanly side-by-side by skeletonizing route shapes in pixel space and
  ordering lines with **integer linear programming** that penalizes crossings
  (Chicago solved in ~0.2 s). Corners use **circular-arc segments, not Béziers**,
  so parallel lines stay parallel around curves. Stop marks are contextual:
  multi-line stops get a high-contrast white bar with black outline across all
  lines; single-line stops get a filled circle in that line's color.
- **Borrow:** (a) the **contextual convergence glyph** — a high-contrast
  white-bar-with-outline where multiple lines meet — directly adoptable in the
  **relationship inspector** where several provenance lines converge on one node.
  (b) **arc-segment paths + line-ordering** for any corridor where multiple
  routes/pipelines run together (bundled edges stay legible without hand-tuning).
- **Avoid:** its live "GO" positions are **crowdsourced/interpolated** and shown as
  fact; a forensic instrument must mark inferred positions as reconstruction. Skip
  the playful rider-avatar treatment.

### Citymapper
- **Does well:** aggressive mode consolidation into one legible interface (bus,
  train, tram, ferry, subway, bike/scooter-share, walk) with a disciplined,
  minimal directional-arrow icon motif that reads instantly at small sizes;
  per-line color coding with intersecting-line transfer markers.
  *Unverified:* current live-mark rendering technique (canvas vs DOM) and whether
  marks are heading-rotated.
- **Borrow:** the **unified small-size mode-icon system** — a single
  tightly-constrained glyph set covering every mode at legend size is exactly what
  Headway's map legend and dashboard mode cards need (one flat icon per
  mode/vehicle-class, no per-agency drift).
- **Avoid:** consumer personalization gloss (emoji/custom location dots). Identity
  must be fixed, not user-decorated.

### Moovit
- **Does well:** "Live Location" tracks a chosen line's vehicle across the map in
  real time across 220+ cities, and — critically for honesty — **surfaces when the
  tracking data was last updated** and shows service alerts inline; multiple lines
  animate at once. *Unverified:* whether the mark is heading-rotated.
- **Borrow:** the **explicit "last updated" timestamp bound to each live mark** —
  the single most transferable honesty pattern in Bucket A. Every live figure and
  vehicle in Headway should carry a visible **data-age stamp**; stale is drawn as
  stale, never as fresh.
- **Avoid:** smooth position interpolation between GPS pings that implies
  continuous observation the data doesn't support.

### Google Maps vs Apple Maps transit layer
- **Does well / poorly (per Transit's own teardown):** **Google** scales to many
  cities via automation but draws **straight chords between stations and jagged,
  poorly-interpolated curves** that "hardly ever follow the actual route path," and
  is often subway-only. **Apple** hand-draws smoother curves, includes multiple
  modes, and gives a **per-station transfer readout** (arrival time per station,
  connecting lines listed) — but is slow, manual, and limited-city.
- **Borrow:** from **Apple**, the **per-node transfer readout** (list every line
  touching a node + its state) maps directly to the **relationship inspector**:
  click a node, reveal every line/relationship that touches it.
- **Avoid:** Google's **geometrically dishonest paths** (straight chords / jagged
  curves masquerading as the true route). A drawn edge must reflect real topology
  or be explicitly abstracted — never a lazy interpolation posing as truth. (This
  is exactly handoff 0043 §8's rule: schematic connectors are honest only for rail;
  street modes need real `shapes.txt` polylines.)

### Via microtransit rider app (+ Uber/Lyft zone UIs)
- **Does well:** Via's rider app is driven by **map-based service-zone definitions**
  authored upstream (service-area polygons, hours, dates); published zone edits
  reflect downstream **instantly** — a clean authored-definition → rider-visible
  provenance chain. It also **refuses to offer on-demand when a fixed route is
  genuinely better** (a "refusal over guess" behavior). *Unverified:* exact
  zone-polygon rendering (fill opacity, edge treatment) and current live-mark
  technique. **Uber/Lyft zone UIs: unverified** — not confirmed by available
  sources.
- **Borrow:** (a) the **authored-zone → instantly-reflected-downstream** model as a
  provenance pattern — a boundary shown to a viewer traces to the exact published
  definition and its effective date. (b) the **refusal-over-guess** behavior —
  surface only the supportable answer.
- **Avoid:** soft glowy zone fills and bouncing pickup-pin motion (consumer
  reassurance). Zones in a compliance view are **hairline-edged polygons with
  honest fill**, and coverage gaps are drawn as gaps. (Reinforces the 0043
  demand-responsive rule: render the service **zone + aggregated O→D flows**, never
  rider-address pins, never demand-density heatmaps here.)

---

## 3. Bucket B — operations / dispatch / observability instruments

The closer cousins: dense, real-time, authoritative. Mined for density,
real-time rendering, and authoritative/provenance drill-paths.

### Swiftly (transit real-time / analytics)
- **Does well:** a Live Map "bird's eye view" of the system with a right-side
  **Real-Time Stats panel that is simultaneously legend AND filter**, and **routes
  ranked in real time by number of issues** — a worklist, not just a map. Crowding
  shown as a discrete icon on vehicles.
- **Borrow:** (a) the **legend-is-also-the-filter** panel (one element carries the
  semantic key + the interaction, cutting chrome). (b) the **issue-ranked
  worklist** — sort surfaces by count of flagged problems so the operator's eye
  lands on the worst first; maps directly to Headway's "flagged items / gaps drawn
  as gaps" and the "needs investigation" list that is the accessible entry point to
  the map (handoff 0043 §7).
- **Avoid:** Swiftly is **100% cloud SaaS** — the opposite of the on-prem
  non-negotiable; borrow the interaction, not the deployment. Its predictions are
  estimates — never render a predicted position as observed.

### Optibus
- **Does well:** a **Gantt-style block/runcut visualization** (Interurban Gantt
  View) for vehicle blocks and driver duties, and a **Map Hub** consolidating
  real-time tracking + route + stop-level detail in one workspace.
- **Borrow:** (a) the **Gantt/timeline band** for time-structured records (a
  vehicle's day, a service block, an audit trail) — dense, legible, and **honest
  about gaps** (a gap in the band reads as a gap in service; this is the same idea
  as the replay dashboard's segment breaks). (b) single-workspace **consolidation**
  supporting the coordinated multi-panel goal.
- **Avoid:** Optibus is optimization/AI-forward — do **not** drift toward "where to
  add service." Borrow the timeline, not the optimization framing (§1 boundary).

### Remix (by Via)
- **Does well:** map-first analysis with **stop-level ridership**
  (boardings/alightings) broken down by time-of-day, day-of-week, and **line
  direction**; the exact metric sits beside its visualization.
- **Borrow:** (a) **directionality as a first-class encoding** — never collapse the
  two directions of a line into one figure when provenance distinguishes them. (b)
  **stop-level drill-down with the exact number beside the chart** — the
  observability twin of "explain this number → lineage → raw record."
- **Avoid:** Remix is a **planning/design canvas** with drawing tools (draw
  polygons, illustrate scenarios). Headway reports what happened; avoid
  editable/illustrative affordances that blur observed vs. proposed.

### Clever Devices (CleverCAD, transit CAD/AVL)
- **Does well:** the closest operational cousin — a control-room CAD/AVL giving
  dispatchers "a clear, real-time picture of the location and status of every
  in-service vehicle," with disruption management as a first-class mode.
- **Borrow:** (a) the **status-of-every-vehicle authoritative roster** — a complete,
  accountable inventory where every unit has a known state and **nothing is silently
  missing** (fits "report what DID happen, provably"; an absent vehicle is
  *ABSENT*, a named state, not a blank). (b) **exception/disruption as its own
  attention channel**.
- **Avoid:** legacy CAD/AVL leans toward dense, dated, high-clutter enterprise
  chrome — adopt the completeness and accountability, not the visual legacy.
  *(Exact screen layout/colors unverified — vendor pages describe capability, not
  pixels.)*

### Grafana
- **Does well:** the reference for staying legible with 20+ panels: **one question
  per panel**, **≤4–5 series per graph**, a consistent spacing grid (20 px rows /
  10 px panel gaps), and **threshold-driven stat panels** that recolor a metric by
  a three-tier (good/warning/critical) mapping. Dark theme for long sessions.
- **Borrow:** (a) **three-tier threshold semantics** → maps cleanly to Headway's
  **ok / watch / alert** — but implemented CVD-safe and, per the honesty rule,
  coloring the **frame/label, never the figure itself**. (b) **one-question-per-panel
  + a strict spacing grid** as the discipline for the dashboard readout cards.
- **Avoid:** Grafana's default red/green thresholds are **not colorblind-safe**, and
  its common blue+orange pairing is an identity palette, not a status set. Keep
  Headway's identity-orange **separate** from the semantic status palette, and never
  let color be the only channel.

### Datadog
- **Does well:** hierarchical, task-oriented dashboards; **heatmaps for
  high-cardinality distributions**; and **correlated click-through** — from a log or
  error, jump to the underlying trace and its full flame-graph. Dark mode uses
  **Viridis and Plasma** host-map palettes.
- **Borrow:** (a) **correlated drill-path** (figure/log → underlying trace) is the
  observability twin of "explain this number → lineage → raw records"; model the
  **provenance terminal** on this drill path. (b) **Viridis/Plasma
  perceptually-uniform, CVD-safe sequential palettes** — a verified, principled
  choice for any intensity encoding, satisfying the CVD-safe requirement (a real
  alternative to rainbow scales).
- **Avoid:** Datadog is cloud SaaS and can lean feature-dense — adopt the drill-path
  and the palette science, not the widget sprawl.

### FlightRadar24 (ADS-B Exchange adjacent)
- **Does well — the strongest rendering exemplar:** the entire web app runs on
  **WebGL2** — base map tiles (vector, not raster), aircraft icons, and trails are
  all GPU-rendered, handling **tens of thousands of moving icons updated ~every 2 s**.
  Vector maps give **continuous zoom**; **heading is a first-class encoding**
  (icons carry heading, trails render at increased granularity); airport pins
  **declutter by zoom** (full label only at high zoom).
- **Borrow:** (a) **GPU/WebGL canvas layer for many heading-rotated live marks** —
  the right technique if/when Headway renders a full fleet as oriented marks at
  density (self-hosted tiles included; matches the deck.gl direction in
  `toc-replay-dashboard.md`). (b) **zoom-progressive label disclosure** — a bare
  mark far out, the identifier/figure revealed on zoom-in — keeps the street map
  uncluttered without hiding data.
- **Avoid:** consumer gloss (3D view, spectacle). And FR24 **interpolates/animates
  positions between updates** for smoothness — Headway must **not** animate marks in
  a way that implies observed motion it doesn't have (handoff 0043 §5: marks jump to
  each newly observed position, never tween).

### MarineTraffic
- **Does well:** renders thousands of AIS vessel positions at once with a
  **multi-channel glyph**: **color = vessel type**, **icon orientation = actual
  course**, **icon shape = moving vs. stopped**. An optional projected-course trail
  is **explicitly labeled an estimation**, visually distinct from recorded
  positions. A toolbar **legend doubles as a type filter**.
- **Borrow:** (a) **multi-channel, non-redundant mark encoding** — one glyph carries
  type (color) + heading (rotation) + state (shape), dense but readable; a template
  for Headway's mode-shaped marks (fixed/DAR/van/Via) carrying state
  (observed/stale/gap). (b) **honest estimate treatment** — inferred/projected data
  rendered visibly differently from observed. This is textbook "reconstruction ≠
  observation."
- **Avoid:** MarineTraffic gets dense fast with limited built-in decluttering
  (zoom-declutter *unverified*); at scale, add the FR24 zoom-declutter rule. Keep
  color-by-type CVD-safe. *(Canvas-vs-WebGL internals unverified.)*

---

## 4. Synthesis — "the blend"

Combine **rider-app map craft** (Transit's bundled-line legibility, Citymapper's
mode-icon discipline, Moovit's data-age honesty) with **ops-tool density and
authority** (Grafana's panel discipline, Datadog's drill-path, FR24/MarineTraffic's
GPU heading-marks, Optibus's timeline, Clever Devices' complete roster) — and let
**Headway's forensic-honesty signature** be the thing that makes the result
distinctly ours: the most striking thing on screen is also the most honest thing.
Eight concrete, adoptable recommendations, each tied to a Headway surface.

1. **Data-age stamp on every live mark and every live figure** *(the street map;
   readout cards).* Adopt Moovit's explicit "last updated" bound to each mark, and
   the MarineTraffic/replay status vocabulary — OBSERVED / RECONSTRUCTED / GAP /
   STALE / ABSENT as **five visually distinct states named in plain words in the
   legend**. This is the honesty ethos rendered as an enum; it is also the answer to
   "why is that dot where it is?"

2. **Multi-channel mode glyph, GPU-drawn, heading-optional, CVD-safe** *(the street
   map).* One flat mark carries **mode = shape** (Citymapper discipline) + **state =
   treatment** (MarineTraffic) + optionally **heading = rotation** (FR24). Render at
   density on a **WebGL/deck.gl canvas layer over self-hosted tiles**
   (`toc-replay-dashboard.md` §1), with **zoom-progressive label disclosure** (FR24)
   so the obsidian frame never clutters. Marks **jump** to observed positions; they
   never tween (handoff 0043 §5).

3. **Honest bundled-corridor rendering** *(the street map).* For fixed-route bus,
   use **real `shapes.txt` polylines** (handoff 0043 §8) — never Google's straight
   chords. Where multiple routes share a corridor, apply Transit's
   **arc-segment paths + line-ordering** for clean parallel edges, and its
   **contextual convergence glyph** at shared stops. Reserve the Vignelli
   schematic/diagram treatment for the optional **rail diagram view** only.

4. **The provenance terminal as a correlated drill-path** *(the provenance
   terminal).* Model it on Datadog's log → trace → flame-graph click-through: a
   figure opens its **lineage → raw records → quoted FTA definition** as one
   continuous drill, each step clickable to the next, the raw-record id always
   reachable. Present it as a **live terminal** (monospace, tabular-nums, streamed
   rows each carrying their record id) — the prettiest possible provenance demo, and
   the moat no pretty-but-opaque dashboard has.

5. **Readout cards on a Grafana-grade discipline, with honest status color** *(the
   dashboard readout cards).* **One question per card**, ≤4–5 series per chart, a
   strict spacing grid. Apply the **three-tier ok/watch/alert** semantics — but
   **CVD-safe and coloring the card frame/label, never the figure** (the honest
   "glow" is a halo on the frame of a flagged item only). Identity-orange stays
   **separate** from the status set. Figures remain verbatim strings; charts scale
   the picture, never the number.

6. **An issue-ranked "needs investigation" worklist beside the map** *(the
   dashboard; the street map).* Adopt Swiftly's **issue-ranked routes** and Clever
   Devices' **exception channel**: rank surfaces by count of flagged findings so the
   worst rises first. This list is also the **accessible entry point** to the map
   (handoff 0043 §7) — keyboard users reach every flagged item through it. The
   flagged frame pulses (reduced-motion collapses it); the figure never does.

7. **The relationship inspector as a per-node transfer readout** *(the relationship
   inspector).* Combine Apple Maps' **per-node "everything touching this node"**
   readout with Transit's convergence glyph: click a node, and the panel renders
   every line/relationship touching it and its state, toggling `feature-state` to
   light the connected route/stop/finding/calc/owner chain on the map (handoff 0043
   §7). Respect **directionality as first-class** (Remix) — never merge two
   directions the provenance keeps apart.

8. **Time-structured records as honest Gantt bands** *(the dashboard; future replay).*
   Adopt Optibus's **block/runcut timeline** for a vehicle's day, a service block,
   or an audit trail — dense horizontal bands where **a gap in the band reads as a
   gap** (never bridged), the same discipline as the replay dashboard's segment
   breaks. For any intensity/density encoding that is legitimately in-scope
   (observed, not advisory), use **Viridis/Plasma** perceptually-uniform CVD-safe
   scales — never a rainbow ramp, never a demand-density heatmap (Phase-2, §1).

---

## 5. Borrow / Avoid — quick reference

**Borrow**
- Data-age "last updated" stamp on every live mark/figure (Moovit).
- Named status enum OBSERVED/RECONSTRUCTED/GAP/STALE/ABSENT, plain-word legend
  (MarineTraffic + replay).
- Multi-channel non-redundant mark: mode-shape + state + heading, GPU-drawn
  (MarineTraffic, FR24, Citymapper).
- Zoom-progressive label disclosure (FR24).
- Arc-segment bundled paths + line-ordering + convergence glyph (Transit).
- Correlated drill-path for the provenance terminal (Datadog).
- Grafana panel discipline: one question per card, ≤5 series, spacing grid,
  three-tier thresholds (CVD-safe, frame-colored).
- Issue-ranked worklist as accessible map entry (Swiftly, Clever Devices).
- Per-node transfer readout for the relationship inspector (Apple Maps).
- Directionality as first-class encoding (Remix).
- Honest Gantt bands where gaps read as gaps (Optibus).
- Viridis/Plasma CVD-safe sequential palettes for in-scope intensity (Datadog).
- Legend-doubles-as-filter panel (Swiftly, MarineTraffic).
- Authored-definition → downstream provenance + refusal-over-guess (Via).

**Avoid**
- Interpolated/crowdsourced positions shown as fact (Transit GO, Moovit/FR24 tween).
- Geometrically dishonest route paths — straight chords, lazy curves (Google).
- Default red/green thresholds; color as the only channel (Grafana defaults).
- Rainbow/rjet intensity ramps (use Viridis/Plasma instead).
- Consumer gloss: 3D spectacle, emoji dots, bouncing pins, glowy zone fills,
  rider avatars (FR24, Citymapper, Via).
- Optimization / what-if / "where to add service" framing (Optibus, Remix) —
  Phase-2, out of scope.
- Demand-density heatmaps and rider-address pins in the compliance view
  (privacy + scope, handoff 0043 §9).
- Cloud-SaaS assumptions and widget sprawl (Swiftly, Datadog) — on-prem,
  zero-external-dependency holds.
- Legacy dense enterprise CAD/AVL chrome (Clever Devices) — take the completeness,
  not the clutter.
- Editable/illustrative map affordances that blur observed vs. proposed (Remix).

---

## 6. Open questions for the 0041 design-sync

1. **Heading on vehicle marks — do we have it?** MarineTraffic/FR24 rotation is
   powerful, but GTFS-RT bearing is often absent or unreliable. If bearing is
   missing or stale, do we render a **non-directional** mark (honest) rather than a
   fabricated heading? (Recommended: heading is opt-in per-feed, and its absence is
   a state, not a guess.)
2. **Where does the data-age stamp live** — on every mark inline (clutter risk at
   fleet density) vs. surfaced on hover/selection + a fleet-wide freshness summary?
3. **Zoom-declutter thresholds** for label/mark disclosure — are these `app.settings`
   values with a basis citation (like the gap threshold), or view-local UI state?
4. **Gantt band scope** — does the block/runcut timeline belong on the metrics
   dashboard now, or is it the replay dashboard's territory (retention-gated)? Avoid
   forcing a temporal scrubber where it doesn't belong (`toc-replay-dashboard.md` §4).
5. **Status-color vs. identity-orange collision test** — confirm the CVD-safe
   ok/watch/alert set is fully distinguishable from signal-orange for all CVD types,
   at AA contrast, on the obsidian ground, before it ships.
6. **Provenance-terminal density budget** — a streamed monospace terminal is
   beautiful but can overwhelm; what's the honest default row cap + truncation
   treatment (reuse the ops-endpoint truncation honesty)?
7. **Unverified items to confirm firsthand** before relying on them: Citymapper/Moovit
   live-mark rendering + heading-rotation; Via zone-polygon rendering; Uber/Lyft zone
   UIs; MarineTraffic canvas-vs-WebGL + zoom-declutter; exact CleverCAD/Remix visual
   specs.

---

## Sources

**Bucket A**
- Transit — [How We Built the World's Prettiest Auto-Generated Transit Maps](https://blog.transitapp.com/how-we-built-the-worlds-prettiest-auto-generated-transit-maps-12d0c6fa502f/); [Transit Maps: Apple vs. Google vs. Us](https://blog.transitapp.com/transit-maps-apple-vs-google-vs-us-cb3d7cd2c362/); [What is GO crowdsourcing?](https://help.transitapp.com/article/91-what-is-go-crowdsourcing)
- Citymapper — [App of the Month (Dec 2025)](https://geekculture.co/app-of-the-month-citymapper-dec-2025/); [Clean Arrow Symbol](https://www.designrush.com/best-designs/logo/citymapper-clean-arrow-symbol); [official site](https://citymapper.com/?lang=en)
- Moovit — [New Live Location feature](https://moovit.com/press-releases/new-live-location-feature/); [Live Location help](https://support.moovitapp.com/hc/en-us/articles/8978526768530-View-the-Live-Location-of-your-transit-line-on-the-map); [TechCrunch coverage](https://techcrunch.com/2022/11/29/moovit-users-can-now-track-transit-vehicles-on-map-in-real-time/)
- Via / Remix — [New features transforming transit](https://ridewithvia.com/resources/via-tells-all-the-new-features-transforming-transit-so-far-this-year); [Integrated transit](https://ridewithvia.com/integrated-transit)

**Bucket B**
- Swiftly — [Live Map View](https://swiftly.zendesk.com/hc/en-us/articles/360019100791-Live-Map-View); [Real-Time Crowding](https://swiftly.zendesk.com/hc/en-us/articles/360050585251-Real-Time-Crowding-in-Live-Operations); [Issues in Live Operations](https://www.goswift.ly/blog/issues-in-live-operations); [Platform](https://www.goswift.ly/platform)
- Optibus — [Real-Time Control enhancements](https://blog.optibus.com/real-time-control-capabilities); [Scheduling](https://optibus.com/product/scheduling/); [Real-Time Control launch](https://blog.optibus.com/optibus-expands-end-to-end-platform-with-real-time-control-for-public-transportation)
- Remix — [Meet the new Remix](https://ridewithvia.com/resources/meet-the-new-remix); [New Remix features](https://ridewithvia.com/resources/power-up-your-planning-new-remix-features-teams-love); [Visualizing Transit Ridership — design process](https://medium.com/remixtemp/visualizing-transit-ridership-in-remix-our-design-process-f6ca54d0a7dc)
- Clever Devices — [CleverCAD](https://www.cleverdevices.com/products/clevercad/); [Operations Control](https://www.cleverdevices.com/solutions/operations-control/); [ATMS II award](https://www.cleverdevices.com/news/clever-devices-awarded-landmark-contract-for-los-angeles-metros-atms-ii-program/)
- Grafana — [Dashboard best practices](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/); [7 Best Practices (MetricFire)](https://www.metricfire.com/blog/7-best-practices-for-grafana-dashboard-design/); [Stat panel thresholds](https://oneuptime.com/blog/post/2026-01-30-grafana-stat-panel-thresholds/view)
- Datadog — [Dashboards](https://www.datadoghq.com/product/platform/dashboards/); [Heatmap engineering](https://www.datadoghq.com/blog/engineering/how-we-built-the-datadog-heatmap-to-visualize-distributions-over-time-at-arbitrary-scale/); [Dark mode + Viridis/Plasma](https://www.datadoghq.com/blog/introducing-datadog-darkmode/)
- FlightRadar24 — [WebGL2 data display](https://www.flightradar24.com/blog/inside-flightradar24/supercharging-flightradar24s-data-display/); [WebGL2 showcase](https://www.webgpu.com/showcase/flightradar24-live-flight-tracking-webgl2/); [Label options](https://www.flightradar24.com/blog/inside-flightradar24/new-flightradar24-com-label-options/)
- MarineTraffic — [Vessels](https://support.marinetraffic.com/en/articles/9552656-vessels); [Live Map](https://support.marinetraffic.com/en/articles/9552654-live-map); [Live Map Layers](https://support.marinetraffic.com/en/articles/9552717-live-map-layers-for-advanced-live-map)
