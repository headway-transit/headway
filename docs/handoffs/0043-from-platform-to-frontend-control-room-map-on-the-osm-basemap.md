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

---

## Response — frontend, wave 2 of 3: mode-aware marks, the flagged-findings layer, the relationship inspector

**Scope of this wave: design points 4, 6 and 7.** Wave 1 (above) landed the
two authored basemap styles and the map-theme toggle. This wave lands the
overlay on top of them. Points **8 and 9 are explicitly NOT in this wave** —
no `shapes.txt` ingestion, no rail diagram view, no demand-responsive zones
or O–D flows, and no demand-density heatmap at all. Nothing outside
`web/src/map/**`, `web/src/views/MapView.tsx`, the `map` block of
`web/src/copy.ts`, `web/scripts/overlay-preview/`, the web tests,
`docs/basemap.md` and this file was touched.

### The sprite question, answered: we did not add one

Wave 1 left this note for whoever took the overlay: *"the styles currently
declare no `sprite`, and the POI layer is dropped precisely because none is
vendored; adding one is a deliberate, gated change, not a default."* Design
point 4 had assumed a sprite sheet ("circle layer + symbol layer over a
self-hosted sprite").

**No sprite was added, and none is needed.** The shapes come out of the SDF
glyph stack this installation already vendors and already draws every street
name with — `web/public/basemap-fonts/Noto Sans Regular/` (SIL OFL 1.1,
already through the ADR-0001 gate). Its `9472-9727` range carries the whole
Unicode *Geometric Shapes* block, so a `symbol` layer whose `text-field` is a
data-driven `match` over `mode` gives:

- **zero new assets, zero new licences, zero new download-pipeline steps**,
  and no `sprite` key on either style — wave 1's recorded posture is intact;
- **fully data-driven paint**: `text-color`, `text-halo-color` and
  `text-opacity` are all data-driven properties in the MapLibre style spec,
  so mode colour, the ground-contrast halo and the mode filter are one
  expression each, evaluated on the GPU over the whole source;
- **a gate against silent rot**: `src/test/map-marks.test.ts` parses the
  actual vendored `.pbf` and asserts every codepoint we draw is in it. A
  re-vendored font subset that dropped these characters fails the build
  instead of quietly erasing the fleet from the map.

The considered alternative was generating an SDF sprite in-repo and
`addImage()`-ing it at runtime. It was rejected as strictly more machinery
for the same result: a shape channel we can already draw, licensed, with an
existing gate.

| | drawn as | reserved for |
|---|---|---|
| road (bus, trolleybus) | ● | |
| rail (rail, subway, tram, monorail) | ■ | |
| water (ferry) | ◆ | |
| cable (cable tram, funicular, aerial lift) | ▬ | |
| mode not known | ○ | a vehicle we were **not told** about |
| — | ▲ | **findings only** — never a mode |

### `mode` does not exist on the vehicles payload — so we joined it, and said so

`GET /ops/vehicles/latest` has no `mode` field. `GET /geometry/routes` — which
this page already fetches — carries `mode` on every route feature (the
canonical string the transform derived from the agency's own GTFS
`route_type`). The mark's mode is therefore a **client-side join through the
route the feed named**, and nothing else:

- no route_id reported → `unknown`, drawn as the hollow ring, **counted** on
  screen ("N vehicles reported no route, so no mode could be looked up");
- a route_id we hold no schedule data for → also `unknown`, but a **different
  sentence**, because it means something different: the feed and the schedule
  disagree, which is worth someone's time;
- a mode string outside the canonical vocabulary is still **drawn** (as the
  ring) and still **named verbatim** in the vehicle list, so a vocabulary that
  grows is visible rather than silently dropped.

**Backend follow-up (not done here, per the lane rules):** if a future
`/ops/vehicles/latest` grows a server-side `mode`, it should win outright and
this join should become the fallback. The derivation is a *display* attribute
only — no figure is computed client-side.

### Colour is the second channel, and that claim is measured

Ten canonical modes cannot be told apart by hue by anyone, least of all by a
viewer with a colour-vision deficiency. So shape carries the **family**, and
colour only has to separate modes drawn with the **same glyph** — and those
pairs are gated:

- the palette is **generated** from (hue anchor × luminance tier), not typed
  as hex, which makes "every mark clears its bar" true by construction;
- hue anchors are **Okabe & Ito's** CVD-safe qualitative set **minus its two
  oranges**, because signal-orange is the one non-semantic identity accent
  and a mode must never be mistaken for it;
- every same-glyph pair is separated under a **Viénot/Brettel (1999)
  protanopia and deuteranopia simulation** (ΔE ≥ 15, CIE76) **and** by
  relative luminance (≥ 1.35:1) — a channel no colour-vision deficiency
  removes, and the one that carries the pairs tritanopia would flatten;
- a **control test** proves the simulation is not a no-op (pure red and pure
  green must collapse under deuteranopia);
- and nothing is colour-only anyway: the legend draws the same glyph in the
  same colour the canvas does, and the **vehicle list gained a Mode column**
  naming every vehicle's mode in words.

### Measured contrast — marks on both grounds

Full table: `docs/images/handoff-0043/mark-contrast-measurements.txt`
(`cd web && npm run check:map-marks`). Bar: **3:1**, WCAG 2.1 SC 1.4.11 — a
vehicle you cannot see is a vehicle that is not on the map.

| | **Light ground** | **Dark ground** |
|---|---|---|
| Worst mark, any ground or its own halo | **3.07:1** (monorail / aerial lift `#7B7522`) | **3.39:1** (funicular `#95597A`) |
| Best mark | 11.36:1 (subway `#001B2B`) | 12.73:1 (monorail `#E9DE40`) |
| Bus | 8.07:1 (`#003755`) | 5.43:1 (`#4196C5`) |
| Mode not known (ring) | 8.18:1 (`#303338`) | 5.44:1 (`#878F97`) |
| Finding flag (`--status-alert`) | 5.12:1 (`#9f1b1b`) | 5.24:1 (`#f5514e`) |
| Selection / related (`--signal`) | 3.88:1 (`#a84400`) | 6.84:1 (`#ff7a1a`) |
| Worst same-glyph CVD separation | ΔE 16.9 deutan (rail/tram), luminance 1.38:1 (subway/tram) | ΔE 22.9 deutan (rail/tram), luminance 1.49:1 (rail/monorail) |

Each mark is measured against **three grounds** — the style's `earth`, its
`background` (outside the extracted region) and the app's `--map-bg` canvas
for the no-basemap state — **and against its own halo**, so the outline is a
real edge rather than a suggestion.

**Plus the generated all-surfaces sweep — 1,155 checks, 0 failures.** Wave 1
learned by measuring a rendered frame that checking against bare `earth`
passes things that are not legible (a shoreline over woodland measured
2.80:1). A mark has the same problem, and worse: the basemap layers all draw
*below* it, so a mark can land on a bright motorway fill or a place label as
easily as on grass. The sweep is flattened straight out of each authored
palette — 54 light surfaces, 51 dark — and requires that **either the ink or
the halo** clears 3:1 over each, with both numbers always reported so a weak
ink cannot hide behind a strong halo. It is generated, so a surface added to
a style later is gated the day it appears.

**Two colours are quoted from the shipped token set rather than invented**
(`--status-alert` for the flag, `--signal` for "this is what you are pointing
at"), one value per **ground** rather than per app theme. They are literals in
`marks.ts` because a canvas cannot resolve a CSS custom property — so a test
parses `src/styles.css` and asserts each still matches, and the same test pins
`--map-bg`. **`src/styles.css` was not edited and no token was added.**

### Honesty rules, as shipped

- **Positions observed, never interpolated.** Each poll replaces the whole
  collection, so a mark **jumps** to its newly observed position. Nothing
  tweens, eases, or carries a previous position forward, and a test asserts
  the feature lands on the feed's exact coordinates.
- **A gap is drawn as a gap.** The existing staleness treatment (the
  live/quiet chip, the verbatim server note, the per-vehicle age) is
  unchanged; this wave added no bridging of any kind.
- **The glow says "look here" and nothing else.** It is a *ring* — `circle`
  layer, transparent fill — so it can never sit behind a figure. It is fed
  only by `status=open` **and** `severity=blocking` and then capped at 12
  drawn flags, because a pulse only means anything while it is rare. There is
  no "all-clear" green glow anywhere.
- **The glow is an amplifier, never the signal.** Every flagged item also
  carries the reserved ▲ shape, a text label on the canvas, a row in the
  "needs investigation" list, and its severity in words.
- **`prefers-reduced-motion` collapses the pulse to a static ring at full
  strength** — never a slower one, and never no ring, because the ring is part
  of the mark. Pinned by test.
- **The rAF loop never touches the fleet.** It repaints one paint property on
  the findings ring layer, which holds at most 12 features; a test asserts no
  `circle-radius` set ever names another layer.
- **A finding has no location, and this surface does not invent one.** A flag
  is anchored to a vertex of the schematic line of a route the finding itself
  names; the position *along* that line means nothing and the legend says so
  in those words. Anchoring is deterministic, so a re-poll never reshuffles
  the flags and two findings on one route stay separately clickable.
- **The map's drawing limits never shrink the worklist.** A finding that names
  no route, names a route we hold no line for, is about a run rather than
  about trips, or fell past the flag cap is in the list anyway, each with the
  reason it has no flag. The count line states both numbers ("2 findings need
  a person. 1 of them is drawn on the map.").
- **The mode filter dims, it does not filter.** One paint expression each on
  `routes-line` and the mark layer; a test asserts **zero** additional
  requests and that the vehicle counts are unchanged. Dim opacity is 0.22 —
  a real reduction, never zero.
- **Labels are never dropped to avoid a collision.** `text-allow-overlap` and
  `text-ignore-placement` are set on every mark layer and pinned by test:
  MapLibre's default collision handling would silently hide vehicles in a
  busy depot, which is precisely the kind of quiet gap this product exists to
  refuse.

### The relationship inspector

`src/map/RelationshipInspector.tsx` — a **react-aria** panel (`useDialog` for
the dialog semantics and label wiring, `FocusScope` with `restoreFocus` so
focus returns to whatever opened it). It deliberately does **not** `contain`
focus: it is a read-only readout beside a live map and a worklist, and
trapping a keyboard user inside one would be a keyboard trap with no purpose.
Escape closes it.

It renders **finding → block → route → calculation → data-quality owner**,
entirely from what the API served:

- **finding** — title, description, severity, status, raised-at and issue id
  verbatim from the queue's own record;
- **block** — the agency's *operational* block name (`block_label`, e.g.
  "225-4") from the finding's own frozen `subject_context`, with the trip
  count and the departure window;
- **route** — the routes that context names, each with the mode joined from
  the schedule data, and marked when we hold no line for it;
- **calculation** — the calc runs whose own outcome rows name this exact
  issue id, with `calc_name`, version, metric and whether the calculation
  **refused** over it. When none is found it says so rather than inventing
  one ("this page reads the most recent runs only");
- **owner** — or, for an open finding with none, the sentence that says an
  unowned finding is nobody's job until someone takes it;
- **provenance** — the finding's `source_record_ids` from
  `GET /dq/issues/{id}`, in monospace, plus a door into the DQ queue.

Where the subject context capped its own lists it says so and shows the true
count beside the sample; trips it could not attribute to a block are counted,
never dropped.

Opening a finding sets `feature-state {related:true}` on each named route
(the source carries `promoteId: "route_id"`) and `{selected:true}` on the
flag — the routes light in the identity accent **in place**, with no data
re-sent and no re-render of the map.

### Accessibility

- **The canvas cannot be read, so the list is the entry point.** Every
  flagged finding is a real `<button>` in a "needs investigation" region,
  ranked, with `aria-pressed`; opening one from the keyboard does exactly
  what clicking its flag does. Pinned by a test that focuses the row and
  presses Enter.
- **Never colour alone**: shape + label on the canvas, severity in words with
  the existing `SeverityIcon` shape encoding, and the new Mode column.
- **Contrast**: 3:1 for every mark on every ground it can appear on, gated.
- **Plain language**: no jargon reached the screen — "Recorded miles stop
  part-way through block 225-4", "No owner yet. An open finding with no owner
  is nobody's job until someone takes it."
- **Reduced motion**: the pulse collapses to a static ring; nothing else on
  the surface animates.
- **axe green** on `/map` with the marks, the mode filter, the worklist and
  the inspector open.
- The mode filter reuses the house filter-bar pattern (labeled `role="group"`,
  real `<button>`s, `aria-pressed`) rather than being rebuilt on
  react-aria-components — the existing control already meets AA.

### One thing worth recording: the preview cannot flatter the app

Wave 1's rule was that the developer preview imports the **shipped**
`basemapLayerSpecs()` "so a preview cannot flatter a style the app does not
draw". This wave's screenshots show marks, a flag and the panel, so the same
rule had to cover the overlay — which meant the layer stack could not stay
inline in the view. It now lives in `src/map/overlayLayers.ts`, and `/map` and
`web/scripts/overlay-preview/` both build their layers from it. The preview
also renders the **real** `<RelationshipInspector>` with the **real**
stylesheet. Only the vehicles, routes and findings are fixture data (no API
and no credentials exist in this environment) and the page says so on screen
and in the caption.

### Screenshots — marks, a flagged finding and the inspector, on both grounds

`docs/images/handoff-0043/`, 1400×900, over this installation's real
`region.pmtiles` (Boston extract, `-71.0700, 42.1894`):

| File | What it shows |
|---|---|
| `overlay-light-inspector.png` | Light street map, z14 — mode marks, two flagged findings (▲ in a ring, labelled), route 39 lit as "related", inspector open |
| `overlay-dark-inspector.png` | Dark street map, z14 — the same frame; marks and flags legible against the bright street network |
| `marks-light-street.png` | Light, z15 — the marks and a flag without the panel |
| `marks-dark-street.png` | Dark, z15 — the same frame |

Each caption is computed live from `markContrastResults()`, so the number in
the image and the number in the gate are the same number.

### Zero external requests — re-verified

Nothing was added that could make a request: the shapes are characters from a
font this installation already vendors, and no sprite, image or CDN URL
entered the style. **One honest change to record:** a symbol layer now exists
even with **no basemap downloaded**, so glyph ranges are fetched in that state
where previously nothing was. That fetch is `/basemap-fonts/…` — an
app-artifact path on this origin. The module header was corrected to say so.

1. **Rendered with every non-localhost host made unresolvable** and compared
   byte-for-byte, three runs each:
   ```
   google-chrome --headless --host-resolver-rules="MAP * ~NOTFOUND, EXCLUDE localhost" \
       --virtual-time-budget=45000 --window-size=1400,900 \
       --screenshot=… "http://localhost:5199/scripts/overlay-preview/index.html?style=dark…"

   dark   normal   3/3  b9068bc347083d39916231d90bf075d9
          airgapped 3/3 b9068bc347083d39916231d90bf075d9   IDENTICAL
   light  settled frame 0d617cb37e9caa1477f39aebd52f4c5f — produced by BOTH
          normal (2/3) and airgapped (2/3) runs
   ```
   The light style also produced a second hash, `4e2b25d5…`, in one normal run
   **and** one airgapped run: decoding it shows a pre-paint frame (panel
   drawn, WebGL frame not yet composited). It is a capture-timing artifact of
   `--virtual-time-budget`, not an airgap effect — recorded rather than
   quietly re-rolled until the numbers looked tidy.
2. **The app-level pin still holds**: the existing test that every request
   `/map` makes is a same-origin relative path is unchanged and green, in both
   the basemap-absent and basemap-present states.
3. **Unit level**: the mark layers are asserted to carry no `icon-image`, to
   name exactly the one vendored glyph stack, and both authored styles are
   asserted to still declare **no `sprite`**.
4. **License gate**: `python3 scripts/license_gate.py --ecosystem node` →
   **PASS, 164 dependencies**. No dependency was added.

### Verification run (commands + output)

```
cd web
npx tsc -b                    → exit 0
npx vitest run                → Test Files 43 passed (43) · Tests 396 passed (396)
npm run build                 → ✓ built in 606ms, no errors
npx oxlint                    → exit 0, 0 warnings
npm run check:map-contrast    → 27 passed (27)   (wave 1's gate, still green)
npm run check:map-marks       → 26 passed (26)   (this wave's gate; tables recorded)
python3 scripts/license_gate.py --ecosystem node → PASS (164 deps)
grep -rl "overlay-preview\|basemap-preview" dist/ → no matches
```

The suite went **337 → 396**: 26 in `src/test/map-marks.test.ts`, 21 in
`src/test/map-findings.test.ts`, 12 new `/map` view tests. Nothing skipped,
nothing disabled.

**Two tests earned their keep during the build.** The token-drift gate first
failed with "no `--status-alert` in the light block" — `styles.css` opens with
a comment that mentions both `:root` selectors, so slicing on the first
textual occurrence silently read the wrong region; the check now matches the
selectors at the start of a line. And the palette generator's exactness
assertion failed only at the brightest tier, which is 8-bit sRGB quantization
being worth more luminance near white than near black — the tolerance is now
proportional and says why.

### Lane discipline

- **`web/src/styles.css` was NOT edited and no token was added.** The overlay's
  own chrome lives in `web/src/map/overlay.css`, which consumes the shipped
  tokens only (`--color-bg`, `--color-border`, `--signal`, `--signal-soft`,
  `--font-mono`, the spacing scale). No new token was needed.
- **`services/api/**`, `db/migrations/**` and `docs/handoffs/0040-*` were not
  touched**, and no review-queue view was created or edited. The missing
  `mode` field was derived client-side rather than added to the API, and the
  API-side follow-up is recorded above instead of taken.
- **`web/src/copy.ts`** was appended to **inside the existing `map` block
  only** (four new sub-blocks: `marks`, `modeFilter`, `findings`,
  `inspector`). No other block was touched or reformatted.
- **`web/src/test/helpers.tsx`** gained two default mock routes (`GET
  /dq/issues`, `GET /calc/runs`) so the pre-existing `/map` tests keep
  exercising what they exercised instead of silently rendering an error
  banner — the same precedent as the existing `GET /dq/issues/counts` default.
  `web/package.json` gained one script line.

### Deferred (explicitly not attempted here)

- **`shapes.txt` street-level route geometry** (point 8, open question) —
  still not ingested; route lines remain schematic, the legend still says so,
  and the flags are anchored to those schematic lines with the caveat stated.
- **The rail diagram view** (point 8) and **demand-responsive zones and O–D
  flows** (points 8, 9). Demand-density heatmaps remain **out of scope
  entirely**.
- **The temporal replay scrubber** — the separate TOC dashboard's signature,
  blocked on the retention decision. Not forced in here.
- **Heading on marks** (survey open question 1): GTFS-RT `bearing` is on the
  payload but often absent or stale; rendering a rotation from it would be a
  fabricated heading. Left as a non-directional mark, deliberately.
- **Zoom-progressive label disclosure** for vehicle marks — the marks carry no
  canvas label at all today; the vehicle list is the readable equivalent.
- **A server-side `mode` on `/ops/vehicles/latest`** — a backend follow-up,
  not a frontend workaround.
