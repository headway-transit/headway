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

### Mode-appropriate geometry (binding — the visualization adapts to the mode)

8. **One visual language, mode-honest geometry.** A single schematic/diagram treatment
   is only *honest* for rail (fixed lines, ordered stations — geography can be
   abstracted). Applied to the rest of the service it misrepresents:
   - **Fixed-route bus** runs on real streets → render GTFS `shapes.txt` polylines that
     follow the streets over the forensic basemap, **not** straight schematic connectors.
   - **Rail** → the diagram/Vignelli treatment is honest and iconic *here*; offer it as
     an optional **"diagram view"** toggle for rail, never as the default for street modes.
   - **Demand-responsive (Vanpool, Via Connect, Dial-A-Ride/paratransit)** has **no fixed
     lines at all** — a schematic fabricates a structure the service does not have. Render
     the **service zone** (translucent boundary) and trips as **aggregated
     origin→destination flows** (hub-to-hub, volume-weighted arcs) or vehicle points.
     **Not demand-density heatmaps.** Demand *concentration* ("where should service
     exist / where's the gap") is advisory — a **planning/optimization** concern that is a
     separate Phase-2 initiative unlocked at production, **not** the compliance
     instrument's job. Flows are observational (trips that occurred, in-scope); density is
     advisory (out-of-scope here). Keep the boundary crisp.
9. **Demand-responsive privacy floor (non-negotiable).** DAR/paratransit locations can
   disclose disability status (already withheld column-level, migration 0028 +
   `docs/data-classification.md`). This view **never plots rider-address pins** — it shows
   **aggregated zone density**, not dots on homes. Honesty (no fabricated network) and
   privacy (no rider re-identification) are the same move here. The demo's flat SVG
   schematic was a CSP stand-in *and* is mode-apt only for rail — do not carry it forward
   as the street-mode or demand-responsive default.

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
- **Route geometry fidelity (direction set, point 8).** `/geometry/routes` v0 is the
  *schematic* built from ordered stop sequences, not true GTFS `shapes.txt` polylines —
  it must NOT be the street-mode default (a line that looks like a street but isn't would
  mislead). Resolved direction: ingest `shapes.txt` for fixed-route street rendering;
  reserve the schematic/diagram for the optional rail view. Remaining question is
  sequencing — does `shapes.txt` ingestion gate the first map wave, or does the map ship
  fixed-route as points/stops first and add street polylines in a follow-up?
- **Demand-responsive zone data** — the service-zone boundary + demand-density for
  VP/Via/DAR needs a source (zone polygons from the agency, or derived from trip O/D
  aggregates). What's the minimum privacy-safe aggregate (hex-bin? zone-level counts?)
  that shows density without re-identifying a paratransit rider?
- **Sprite generation in the license/offline gate** — the mode-shape sprite sheet must
  be built and vendored self-hosted; confirm the build step fits the existing
  basemap-asset pipeline (handoff 0027's download-basemap path).

---

## Response — frontend, wave 1 of 3: the two legibility-tuned basemap styles + the map-theme toggle

**Scope of this wave: the FIRST sequenced item only** — "land the two legible
basemap styles + toggle first (the thing the ITS manager asked for)". The mode
marks (design point 4), the flagged-findings layer (6) and the relationship
inspector (7) are **not** in this wave; they depend on the 0041 token system and
are sequenced behind it. Nothing outside `web/src/map/**`, `MapView.tsx`, the map
copy block, `docs/basemap.md` and this file was touched.

### The complaint, in numbers

The ITS manager's report ("streets and geographic features became hard to read")
was never an impression. Measured against WCAG 2.1, the stock Protomaps flavors
Headway shipped in handoff 0027 fail on both sides:

| Pair | Stock **dark** | Stock **light** | Bar |
|---|---|---|---|
| Minor street vs its ground | **1.52:1** | 1.33:1 fill / **1.01:1 casing** | 3:1 (SC 1.4.11) |
| Motorway vs its ground | **1.77:1** | 1.33:1 fill | 3:1 |
| Water vs land | **1.34:1** | **1.17:1** | 3:1 |
| Minor street name vs ground | **2.11:1** | **2.59:1** | 4.5:1 (SC 1.4.3) |
| Major street name vs ground | **2.87:1** | **2.52:1** | 4.5:1 |

The light flavor's road *casing* measuring **1.01:1** against the earth is the
finding that reframed the wave: the dark map was the complaint, but by
measurement **neither** style had a street edge that was actually there. Both
were re-authored. These stock numbers are pinned as a regression test
(`the stock Protomaps flavors — why we authored our own`) so nobody can quietly
swap an authored palette back out for a vendor flavor.

### What shipped

1. **Two authored MapLibre basemap styles, light and dark, both first-class.**
   `web/src/map/styles/headway-basemap-light.json` and
   `…-dark.json` — ~90 hand-chosen colors each, plus each style's own halo
   width, road-width scale, contrast targets and **its own check list**. Neither
   is a tint or filter of the other: a test asserts the two share **zero** palette
   entries, that the dark style's street *fills* are lighter than its ground while
   the light style's street *casings* are darker than its ground (the contrast is
   inverted, not the brightness), and that the dark ground sits in the warm
   near-black control-room family (relative luminance < 0.02).
   - **Dark** — ground `#0C0F16`; roads by class as light hairlines
     (`#F2F5FA` motorway → `#A8B6C9` minor → `#7C8AA0` service); water raised to
     `#35709A`; every label light over a `#05070B` halo at 1.6px; road widths
     scaled ×1.15 because bright hairlines on a dark ground read thinner.
   - **Light** — ground `#E7E2D9`; white road fills kept (cartographic
     convention) but every class given a **real** casing (`#524D40` motorway →
     `#7A7466` service) so the street edge exists by measurement; names pushed to
     near-black over a white halo; water darkened to `#45758F`.
   - **Deliberate reuse, recorded:** the *layer structure* (source-layers, `kind`
     filters, zoom stops) is still `protomaps-themes-base`'s, consumed through its
     `*WithCustomTheme` entry points. That structure is the contract with the
     vendored tile schema our own installer downloads; hand-copying ~70 layer
     definitions into our JSON would fork it and rot the first time either moves.
     What is ours is all of the paint. A test asserts our layer id set is exactly
     the vendored one, so the reuse cannot silently drift.

2. **The map-theme toggle: kept independent, defaulted to light, and now honest
   about what it promises.** The toggle already existed (handoff 0029); this wave
   made the dark option worth choosing. It remains a labeled `role="group"` of
   real `<button>`s with `aria-pressed` — the house filter-bar pattern, fully
   keyboard-operable — deliberately *not* rebuilt on react-aria-components, since
   the existing control already meets AA and churning it would have been change
   for its own sake. Light is still the default in both app themes and the choice
   still persists per browser. Switching repaints **tiles only**: a test asserts
   the overlay layers (routes, stops, vehicles) are never re-added on a swap.
   - **One behavior change:** the map's *background* layer now follows the
     **street style** rather than the app theme once tiles are drawing. Without
     this, choosing the dark map left a pale app-theme halo around the extracted
     region and every contrast number measured against `theme.earth` stopped
     describing what was actually on screen outside it. With no basemap
     downloaded there are no tiles to agree with, so the app token still wins.
   - The legend now names the style in use and states the promise in plain
     language, and the toggle's note carries the real numbers.

3. **Contrast verified, not eyeballed — and gated.**
   `web/src/map/contrast.ts` + `web/src/test/basemap-style.test.ts`.
   The checks live **inside each style file as theme keys**, not as a hand-copied
   hex table like `scripts/check-contrast.mjs` — change a color and the gate
   re-measures the new color automatically, so it cannot drift out of sync with
   the thing it gates. 28 declared pairs per style, plus the generated
   all-grounds sweep. `npm run check:map-contrast` prints the table.
   - **"Best stroke wins" for roads, both numbers always reported.** A street is a
     fill over a casing and which one carries the contrast depends on the ground —
     bright fill on dark, dark casing on light. A road check lists both keys and
     passes on the better one, but the report prints each, so a weak stroke cannot
     hide behind a strong one.
   - **Bars are the WCAG ones**, asserted as such: 3:1 for streets and water
     (SC 1.4.11, non-text contrast — a street you cannot see is a street that is
     not on the map), 4.5:1 for names (SC 1.4.3).
   - **The gate is proven non-trivial**: a test feeds the stock flavors through
     our own check lists and asserts they fail more than five pairs each.

### Measured contrast — the recorded numbers

Full 28-pair table per style: `docs/images/handoff-0043/contrast-measurements.txt`
(generated by `cd web && npm run check:map-contrast`). Worst case per category:

| | **Light** (ground `#E7E2D9`) | **Dark** (ground `#0C0F16`) | Bar |
|---|---|---|---|
| Worst road-vs-ground | **3.60:1** (service casing `#7A7466`) | **3.39:1** (minor tunnel `#5C6879`) | 3:1 |
| Motorway vs ground | 6.53:1 (casing `#524D40`) | 17.54:1 (fill `#F2F5FA`) | 3:1 |
| Minor street vs ground | 4.29:1 (casing `#6E685A`) | 9.31:1 (fill `#A8B6C9`) | 3:1 |
| Water vs ground | 3.88:1 | 3.59:1 | 3:1 |
| Worst label-vs-ground | **5.01:1** (lake name on water) | **4.72:1** (lake name on water) | 4.5:1 |
| Minor street name vs ground | 9.52:1 | 13.19:1 | 4.5:1 |
| Major street name vs ground | 12.67:1 | 17.66:1 | 4.5:1 |
| Street name vs its own halo | 12.28:1 | 13.87:1 | 4.5:1 |

Against the stock flavor being replaced: minor-street legibility goes
**1.52:1 → 9.31:1** on dark and **1.01:1 → 4.29:1** on light; minor street names
go **2.11:1 → 13.19:1** and **2.59:1 → 9.52:1**.

### A finding the screenshots produced (and the gate it added)

The first dark capture was of a wooded stretch of the Boston extract, and
measuring its *rendered pixels* showed the modal color of the frame was
`wood_b`, **not** `earth` — a third of the visible ground was land cover. Water
over that green measured **2.80:1** and would have shipped as a pass, because
every declared check measured against `earth`. A shoreline does not care which
polygon it happens to be crossing.

Fixed two ways, both permanent:
- the dark palette's land cover, parks, woods, runways and piers were pulled
  back toward the ground and water was lifted `#31688C → #35709A`;
- a **generated sweep** now holds streets, water and street names to their bars
  over **every one of the 27 ground surfaces** each palette can draw — parks,
  woods, buildings, land cover, runways, piers — not just the bare earth. It is
  generated from the palette, so a ground color added later is gated the day it
  appears.

### Screenshots — both styles, streets legible in each

`docs/images/handoff-0043/`, 1400×900, over this installation's real
`region.pmtiles` (Boston extract, `-71.0625, 42.1894`):

| File | What it shows |
|---|---|
| `basemap-light-neighborhood.png` | Light, z14 — network, water, highway interchange, place names |
| `basemap-dark-neighborhood.png` | Dark, z14 — same frame; the street network is the brightest thing on screen |
| `basemap-light-street.png` | Light, z16 — every street name readable |
| `basemap-dark-street.png` | Dark, z16 — same frame; names readable, road classes distinguishable by weight and brightness |

Captured through `web/scripts/basemap-preview/` — a developer page that imports
the **shipped** `basemapLayerSpecs()` and style files rather than restating any
color, so a preview cannot flatter a style the app does not draw. It needs no API
and no login (no dev credentials existed for this environment), and `vite build`
has a single HTML input so it is **not** in the production artifact — verified:
`grep -rl "basemap-preview" dist/` returns nothing.

Each capture's caption line is computed live from the style's own measured
worst-case ratios, so the numbers in the image and the numbers in the gate are
the same numbers.

### Zero external requests — proven, not assumed

1. **Rendered with every non-localhost host made unresolvable** and compared
   byte-for-byte with the normal render:
   ```
   google-chrome --headless --host-resolver-rules="MAP * ~NOTFOUND, EXCLUDE localhost" \
       --screenshot=airgap-dark-z16.png "http://localhost:5199/scripts/basemap-preview/…?style=dark"
   light: airgapped=7256a4af40f40feeccfc12be6357b16e normal=7256a4af40f40feeccfc12be6357b16e  IDENTICAL
   dark:  airgapped=3f98823fa7df62d31bf39a165f67e952 normal=3f98823fa7df62d31bf39a165f67e952  IDENTICAL
   ```
   Full street network, water and labels rendered identically with the outside
   world unreachable. Nothing off-box was needed to draw either style.
2. **Chrome net log** for both styles: the only non-localhost URLs are Chrome's
   own telemetry (`clients2.google.com/time`, `accounts.google.com/ListAccounts`,
   `safebrowsingohttpgateway.googleapis.com`) — browser-internal, no page request.
3. **Unit-level**, in the style module test: every produced layer is asserted to
   carry no `icon-image`, exactly the one vendored glyph stack, and the whole
   serialized layer set is asserted to contain no `https?://` and no host-shaped
   string. The POI layer and the vendor background layer are dropped.
4. **The existing app-level pin still holds** — every request `/map` makes,
   detection HEAD and ranged magic GET included, is a same-origin relative path.
5. The three external URLs present in the built `MapView` chunk are vendor
   strings, not fetches: a WebGL help link inside a MapLibre error message,
   MapLibre's default attribution-control markup (the app passes
   `attributionControl: false`), and a PMTiles doc comment. Our style files
   contain zero occurrences of `http`.

### Verification run (commands + output)

```
cd web
npx tsc -b                    → exit 0
npx vitest run                → Test Files 39 passed (39) · Tests 319 passed (319)
npm run build                 → ✓ built in 587ms, no errors
npm run lint                  → oxlint, 0 warnings
npm run check:map-contrast    → 27 passed (27); full table recorded
```

The suite went **289 → 319**: 27 new tests in `src/test/basemap-style.test.ts`
plus 3 new `/map` tests. Nothing skipped, nothing disabled. axe is green on `/map`
in both street styles (the new legend line is covered by an axe assertion).

**A test earned its keep during the build:** the road-width scale silently
matched nothing, because `isRoadLine()` was checking the already-namespaced
`basemap-roads_*` id against a `roads_*` prefix. Caught by the assertion that the
two styles must produce different `roads_minor` widths.

### Accessibility

- Toggle: labeled `role="group"`, real `<button>`s, `aria-pressed`, full keyboard
  path — unchanged pattern, still AA.
- Contrast: the whole point of the wave; 3:1 non-text / 4.5:1 text, gated.
- Plain language: the toggle note and the new legend line state the promise and
  the numbers in words an operations manager can act on; no jargon, no color-only
  signalling.
- `prefers-reduced-motion`: nothing animates in this wave — a style swap is an
  instant repaint, and the one pre-existing camera animation still degrades to a
  jump. The pulse/reveal work arrives with the findings layer.
- On-prem parity, provenance, fail-loudly and "AI never computes a number" are
  untouched: this wave changes paint on a self-hosted basemap only. The
  "route lines are schematic" honesty line is unchanged and still shown.

### Deferred to the later map sub-waves (explicitly not attempted here)

- **Mode-shaped vehicle marks** (design point 4) and the self-hosted mode-shape
  **sprite sheet** — needs the 0041 theme-scoped tokens and a sprite build step in
  the download-basemap pipeline. Note for whoever takes it: the styles currently
  declare **no `sprite`**, and the POI layer is dropped precisely because none is
  vendored; adding one is a deliberate, gated change, not a default.
- **Mode filter, flagged-findings layer, `feature-state` relationships** (6) and
  the **relationship inspector side-panel** (7).
- **`shapes.txt` street-level route geometry** (open question, point 8) — still
  not ingested; route lines remain schematic and the legend still says so.
- **Demand-responsive zones and O–D flows** (8, 9) and the optional rail
  **diagram view**.
- The **light-style road fills** are still white-on-cream by convention, so their
  fill-vs-ground ratio stays ~1.3:1 and the casing carries the street. That is
  recorded as a deliberate cartographic choice, not an oversight; if a future
  agency needs a high-contrast light map for a glare-lit dispatch room, the honest
  answer is a third authored style, not a tweak to this one.

### One thing the orchestrator should know

`web/src/copy.ts` was edited (the `map.basemap` block only: the style note plus a
new `legendStyleLine`). It is a shared file rather than a track-owned one, so it
is the single likely conflict point with the concurrent 0041 track; the change is
confined to that one block. `web/src/styles.css`, `web/src/components/**`,
`web/src/views/Dashboard*` and `docs/handoffs/0041-*` were **not** touched, and
the map styles deliberately define their own colors internally rather than
consuming or adding design tokens. `scripts/check-contrast.mjs` was also left
alone for the same reason — the map's gate lives in its own file.
