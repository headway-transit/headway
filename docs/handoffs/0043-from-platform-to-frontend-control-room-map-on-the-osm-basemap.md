# Handoff: platform → frontend — The control-room map, on the OSM basemap (legible in both themes)

## Context

The design-sync pass (handoff 0041) produced a control-room aesthetic — a dark,
forensic-instrument surface with mode-shaped vehicle marks, flagged-for-investigation
items, and a relationship inspector. Two demo Artifacts proved the language. **This
wave lands that language on the real map**, and it is explicitly **queued behind the
0041 dashboard design-sync pass** — do that first, inherit its tokens, then this.

**Two facts set the whole approach:**

1. **We are not building a new map.** `web/src/views/MapView.tsx` already ships
   MapLibre GL JS (BSD-3, ADR-0001 license gate) over a self-hosted PMTiles OSM
   basemap, with routes/stops/vehicles already loaded as **GeoJSON sources**
   (`addSource`/`addLayer`) from `GET /geometry/routes`, `GET /geometry/stops`, and
   `GET /ops/vehicles/latest` (polled 20 s). The demo Artifacts drew a hand-authored
   SVG schematic **only because the Artifact CSP blocks real tiles** — that SVG is a
   stand-in, not the target. The design becomes a **restyle + three added layers** on
   the map that already exists, not a rebuild.

2. **The dark map's real problem is contrast, not darkness** (the partner agency's ITS
   manager called this out: streets and geographic features became hard to read when a
   dark theme was applied). A naive dark basemap renders roads as dark grey on a dark
   ground — that is what buried the network. The control-room fix is the **opposite**:
   a dark *ground* with roads, water, and labels rendered **lighter and higher-contrast
   than the default**, so the street network is *more* legible than on the muddy
   default — which is also the more honest emphasis for an ops map (the network you are
   reasoning about should dominate the frame). And the integration must work with
   **both** OSM themes, both held to the same legibility bar.

## Design (binding)

### The basemap: two legibility-tuned styles, light default

1. **Two MapLibre style JSONs — light and dark — both first-class.** The dark style is
   authored (not filtered) for legibility: dark ground, but roads by class rendered as
   *light hairlines*, water raised in contrast, every label given a `text-halo` so it
   never dissolves into the base. Neither style is a tint of the other. Self-hosted
   glyphs/sprite; **zero external requests** (the on-prem / no-external-tiles rule
   holds — this is why we self-host PMTiles in the first place).
2. **A map-theme toggle, independent of app chrome, defaulting to light.** The ITS
   manager found the light map legible — so light is the default and dark is an opt-in
   that has been contrast-tuned. The map theme is chosen **separately** from the app
   theme and from the audience lens; the control-room panels/inspector may stay dark
   regardless — only the tiles switch. (Extends the light/dark basemap decoupling of
   handoff 0029; this wave holds both variants to a real contrast target.)
3. **Contrast is verified, not eyeballed.** Both styles get a real check — road and
   label contrast against their ground, and marks against both grounds — gated the way
   the AA token system is. The dark map **does not ship** until a street reads. "Looks
   cool" is not the acceptance test; legibility is.

### The overlay: the forensic language, theme-aware

4. **Vehicle marks by mode = data-driven paint on the existing vehicles source.**
   `vehiclesToGeojson()` gains a `mode` property; color+shape come from a data-driven
   expression (circle layer + symbol layer over a self-hosted sprite for the
   fixed/DAR/van/Via mode shapes). Marks read their colors from **theme-scoped tokens**
   so they stay high-contrast on either ground (light basemap → darker marks with a
   soft outline; dark basemap → lighter marks with a glow). The CVD-safe mode palette
   is preserved.
5. **The honesty rule is unchanged: positions observed, never interpolated.** Marks
   **jump** to each newly observed position — no tweening between polls that would
   imply motion we did not observe. A stale/gapped vehicle keeps its existing staleness
   treatment; a gap is drawn as a gap, not bridged. (The temporal replay scrubber
   remains the separate TOC dashboard's signature, blocked on retention — do not force
   it here.)
6. **Mode filter + flagged items + relationships = MapLibre `feature-state`, not DOM.**
   Mode highlight is a paint expression on `mode` (dim non-selected, thicken the
   selected mode's routes) — instant, no re-fetch. Flagged-for-investigation markers
   are a small findings layer (sourced from the DQ/findings API) pulsed by a
   `requestAnimationFrame` paint loop on **just those few features** (not the whole
   fleet). Selecting a feature sets `feature-state {selected/related:true}` to brighten
   the connected route/stop.
7. **Inspector + relationship chain = a React (react-aria) side-panel over the canvas.**
   A MapLibre `click` on a feature hands its props to a panel that renders the finding
   detail and the finding → block → route → calc → DQ-owner chain from the API, and
   toggles `feature-state` to light those elements on the map. **The accessible entry
   point is the "needs investigation" list** (the canvas itself is not natively
   accessible) — keyboard users reach every flagged item through the list, matching the
   demo.

## Outputs

Two contrast-verified basemap styles (light default) + the independent map-theme
toggle + `mode`-aware vehicle marks (self-hosted sprite) + the flagged-findings layer +
the relationship inspector side-panel; theme-aware overlay tokens extending the 0041
system; reduced-motion honored (pulse and any reveal collapse); web tests; screenshots
of **all four** combinations (light/dark basemap × a mark set on each). Sequence:
land the two legible basemap styles + toggle first (the thing the ITS manager asked
for), then the mode marks, then the findings layer + inspector.

## Open Questions

- **Where does the map-theme toggle live** — in the map controls only, or promoted to a
  global setting alongside app theme? (Recommended: map-scoped, since it is a legibility
  choice about the tiles, not an app-wide preference.)
- **Route geometry fidelity** — `/geometry/routes` v0 is the *schematic* built from
  ordered stop sequences, not true GTFS `shapes.txt` polylines. On a real basemap a
  schematic line will not follow the streets; do we ingest `shapes.txt` for this view,
  or label the lines as schematic connectors? (This is the honesty seam to get right —
  a line that looks like a street but isn't would mislead.)
- **Sprite generation in the license/offline gate** — the mode-shape sprite sheet must
  be built and vendored self-hosted; confirm the build step fits the existing
  basemap-asset pipeline (handoff 0027's download-basemap path).
