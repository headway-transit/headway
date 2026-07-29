# Handoff: platform → frontend+devops — Self-hosted basemap (UAT wave 3, expedited)

## Context
The first partner agency's ITS manager is already demoing Headway to his COO; the
project lead expedited the basemap from roadmap to build queue (2026-07-28 evening).
The design was ratified in ROADMAP.md and every technical fact is now PROVEN on this
box (orchestrator, this evening): `pmtiles extract` against the daily Protomaps planet
build (`https://build.protomaps.com/YYYYMMDD.pmtiles`, HTTP 200, range-request
friendly) pulled the ENTIRE first agency's service area (bbox
-119.55,46.05,-118.85,46.45) as a **12 MB file in 5 seconds** (67 requests, overfetch
0.05); go-pmtiles v1.31.2 ships Linux x86_64/arm64 tarballs; `pmtiles` JS 4.4.1 and
`protomaps-themes-base` 4.5.0 are both BSD-3-Clause. The rule this wave must never
bend: **the map makes zero external requests at view time** — the download is a
one-time, admin-consented act, exactly like `--check-updates`.

## Design (binding)

1. **`install.sh --download-basemap` (devops half).** Guided, plain-language:
   - States plainly, BEFORE acting: this contacts `build.protomaps.com` once to
     download OpenStreetMap-derived map data for your area (~10–50 MB typical); Headway
     never contacts it again; the data is © OpenStreetMap contributors (ODbL) and the
     map will display that credit.
   - **Bounding box from their own data**: query canonical.stops min/max lat/lon (via
     the standard one-off container psql pattern) + a stated margin; fall back to
     asking for a bbox (with a plain-words explanation and an example) when no stops
     exist yet. Show the computed box and ask before downloading.
   - Fetch the go-pmtiles release tarball (pinned version + checksum verified — same
     rigor as the cosign install in `--upgrade`), run `pmtiles extract` against the
     most recent available daily build (probe today, step back a few days), write to
     `deploy/compose/basemap/region.pmtiles` (gitignored dir, like tides-drop).
   - Wire serving: the web container mounts `./basemap` read-only and nginx serves
     `/basemap/` with byte-range support (verify ranges actually work through nginx —
     PMTiles requires them). Dev parity: vite serves the same path (public dir or
     middleware — record the choice). `--download-basemap` on a box with an existing
     file offers refresh/keep.
   - Re-runnable; failure leaves nothing half-written (temp file + atomic move).
2. **Map rendering (frontend half).**
   - `pmtiles` JS protocol + `protomaps-themes-base` layers under the existing
     schematic/stops/vehicle layers. The basemap is detected at runtime (HEAD/ranged
     GET of `/basemap/region.pmtiles`); ABSENT → today's canvas exactly as-is plus,
     for certifying_official only, one quiet teaching line naming the installer
     command; PRESENT → streets appear.
   - **Attribution is non-negotiable**: "© OpenStreetMap contributors" (+ Protomaps)
     visibly on the map whenever basemap tiles render — ODbL requires it and we honor
     licenses conspicuously.
   - Light AND dark themes wired to the existing theme toggle (protomaps-themes-base
     ships both; contrast gate covers any new chrome).
   - **Glyphs/fonts self-hosted**: label rendering needs PBF glyphs — vendor the
     needed font stack(s) from protomaps/basemaps-assets into the web bundle/public
     path (record licenses — Noto is OFL — and satisfy the license gate). Sprites may
     be skipped in v0 (record). If glyph vendoring balloons, a labels-off basemap v0
     is an acceptable recorded fallback — streets without street names still beat a
     void; state the limitation in the legend.
   - The zero-external-requests test EXTENDS to the basemap-present state: every
     request in the network log stays same-origin, pinned by test in both states.
   - Schematic legend line stays (route lines are still stop-to-stop until shapes.txt
     ingestion); the legend now also carries the attribution when tiles are present.
3. **Docs**: `docs/connecting-your-data.md` gets nothing (not data); the basemap story
   lands in `install/README.md` ("After installing" bullet) + a short
   `docs/basemap.md`: what it is, the one-time-download consent model, refresh cadence
   (rerun the command when you want newer map data), ODbL note, air-gapped path (run
   the extract elsewhere, copy the file in — document the exact command).
4. **Honest scope:** no auto-refresh of map data (rerun = consent each time); no
   global/nationwide basemaps (service-area bbox only, by design); no routing/geocoding;
   vehicles/stops/schematic layers and all their honesty affordances unchanged.

## Outputs
Live verification on this box: run the real `--download-basemap` end to end (stops
bbox from the live MBTA data → Boston-area extract), serve it through BOTH the vite
dev path and a disposable nginx web container proving range requests, render with
streets + attribution in light and dark, click-through + screenshots (docs/images/
handoff-0027/), zero-external-requests network log in basemap-present state, web
tests + axe + contrast + license gate green, build clean; the 12 MB Tri-Cities
extract already produced this evening sits at the scratchpad as a second dataset if
useful. Evidence appended here. No commits — the orchestrator integrates.

## Open Questions
- Sprites/POI icons (v1); labels if deferred; shapes.txt street-aligned routes pairing.
- Public /map exposure (the public page currently has no map) — separate decision.
- Bundling a starter basemap with releases (size/licensing questions) vs download-only.

## Outputs — evidence

### Response — frontend+devops (2026-07-28, working tree on top of `0028dbf`)

Contract accepted; both halves implemented and everything below verified
LIVE on this box: the real `--download-basemap` end to end against the
live MBTA stops, both serving paths (vite dev middleware + the real nginx
web image in a disposable container), streets rendered light AND dark with
attribution, and the zero-external-requests pin extended to the
basemap-present state — by unit test and by real-browser network log.

**What shipped:**

*Devops half (`install/install.sh --download-basemap` + serving):*

- `install.sh --download-basemap`: guided, plain-language, consent BEFORE
  network contact (names both hosts — github.com for the tool,
  build.protomaps.com for the data — the ~size, the ODbL credit, and the
  never-phones-again promise). Bounding box from the agency's OWN data
  (`canonical.stops` min/max via the standard one-off container psql
  pattern, `timescale/timescaledb:latest-pg16` image, PGPASSWORD via
  environment inheritance) + a stated 0.10° (~7 mi) margin, shown and
  confirmed before anything downloads; plain-words manual-bbox fallback
  (with the Tri-Cities example) when no stops exist or the computed box is
  refused; >5° areas draw a loud size warning. go-pmtiles is pinned
  v1.31.2 AND sha256-pinned per arch in the script (x86_64
  `3ed7dbf4…0a312f`, arm64 `f8bd47e7…801cb1` — computed 2026-07-28 from
  the GitHub release; the release publishes no checksums.txt asset, so the
  pins are this project's own recorded fingerprints, same spirit as the
  cosign identity pin in --upgrade; nothing downloaded runs before
  `sha256sum -c` passes). Daily build probed today-back-4-days. Extract
  writes into a `mktemp -d` INSIDE the basemap dir → `pmtiles show`
  sanity-check → `chmod 644` → single same-filesystem `mv` (atomic);
  temp dir removed by trap on every exit path. Existing file → offers
  keep/replace with size+date. `--yes` is REFUSED for this mode (consent
  must be a person). Mode exclusivity extended.
- Serving: `deploy/compose/basemap/` is a tracked directory (its own
  `.gitignore`, tides-drop posture: `*` ignored, `.gitignore` kept, so the
  mount exists in every checkout); compose `web` service gains
  `./basemap:/basemap:ro`; `web/deploy/nginx.conf` gains `location
  /basemap/` (alias, octet-stream, `Cache-Control: no-cache`, NO
  try_files — absent file answers 404, never the SPA fallback; nginx
  serves byte ranges for static files by default). Dev parity — RECORDED
  CHOICE: a small vite plugin middleware (`web/vite.config.ts`) serving
  the SAME `deploy/compose/basemap/region.pmtiles` with full
  Range/206/416 semantics, NOT the public/ dir — public/ is copied into
  the build artifact by `vite build`, and the basemap is deployment data,
  never artifact data.

*Frontend half (`web/`):*

- `pmtiles` 4.4.1 (protocol) + `protomaps-themes-base` 4.5.0 (street
  layers), both BSD-3-Clause. Detection at runtime, never assumed: HEAD of
  `/basemap/region.pmtiles`, then a ranged GET of bytes 0–6 that must
  answer 206 with the `PMTiles` magic — which proves byte-range support
  through the serving stack AND the file format in one request. ABSENT →
  the 0024 canvas byte-for-byte (no source, no layers, nothing fetched)
  plus ONE quiet teaching line for certifying_official only, naming
  `./install/install.sh --download-basemap`. PRESENT → the archive becomes
  a `pmtiles://` vector source at `window.location.origin` (same-origin by
  construction) and every street layer is inserted with beforeId
  `"routes-line"` — streets UNDER schematic/stops/vehicles, always. A file
  that answers without ranges (or wrong magic) is a plain-language
  `role="alert"` — fail loudly, canvas still works.
- Themes: light AND dark flavors from protomaps-themes-base, wired to the
  existing theme toggle (theme switch removes/re-adds the basemap layers
  in place; overlay layers and their data untouched). The theme's own
  `background` layer is dropped so the token water-tone canvas (already
  AA-checked against the mark colors, both themes) stays outside the
  extract's coverage.
- Attribution (ODbL, non-negotiable): "© OpenStreetMap contributors ·
  Protomaps" rendered ON the canvas (solid `--color-text`/`--color-bg`
  chip — an already-registered AA pair in both themes; pointer-events
  none so panning is never blocked) whenever tiles render, plus the
  legend: a basemap key line, the full ODbL credit, and the stated v0
  limitation. The schematic legend line STAYS.
- Glyphs self-hosted: the complete Noto Sans Regular PBF stack (256 range
  files, 6.9 MB, SIL OFL 1.1 — `OFL.txt` vendored alongside + README)
  vendored from protomaps/basemaps-assets into
  `web/public/basemap-fonts/`; the style's one `glyphs` URL points at it
  (same origin), and every basemap label layer is rewritten to
  `["Noto Sans Regular"]` so a request for an unvendored stack can never
  fire. RECORDED trade: Medium/Italic not vendored (pure typography, no
  data loss; vendoring all three would be 13.5 MB — Regular alone keeps
  labels ON instead of the labels-off fallback). Sprites NOT vendored
  (v0): the `pois` layer is dropped and `icon-image` stripped from the
  locality layer — limitation stated in the legend in plain words.
- copy.ts: all new strings externalized under `copy.map.basemap`.

*Docs:* `docs/basemap.md` (what it is, the consent model, refresh cadence,
ODbL note, the exact air-gapped commands, honest not-list);
`install/README.md` "After installing" bullet; `web/README.md` route table
+ dependency table (incl. the vendored OFL fonts).
`docs/connecting-your-data.md` untouched (not data), per the handoff.

**License gate:** `python3 scripts/license_gate.py --ecosystem node` →
**"164 deps: 164 pass (5 via reviewed allowlist), 0 fail — LICENSE GATE:
PASS"** (was 161), with the new rows verbatim: `pmtiles 4.4.1
BSD-3-Clause PASS`, `protomaps-themes-base 4.5.0 BSD-3-Clause PASS`.
Vendored fonts recorded as SIL OFL 1.1 in web/README.md +
`web/public/basemap-fonts/README.md` + the served `OFL.txt`.

**Gates (all green, run 2026-07-28 after all web changes):**

```
npx vitest run          → 36 files, 262 tests, all pass
                          (map.test.tsx 9 → 14: +5 basemap tests — absent
                           unchanged-canvas + no-teaching-for-steward,
                           certifying-official teaching line, present state
                           (source/layers-under/attribution/legend/axe),
                           zero-external-requests EXTENDED to present state,
                           no-range fail-loudly)
npm run lint            → oxlint, no findings
npm run check:contrast  → 87/87 PASS (no new pairs needed: attribution chip
                          and legend reuse registered token pairs)
npm run build           → tsc -b && vite build, clean:
   dist/assets/index-*.js    657.99 kB │ gzip 183.21 kB
   dist/assets/MapView-*.js  997.66 kB │ gzip 259.37 kB  (/map chunk only:
                             +~60 kB for pmtiles + protomaps-themes-base)
   + basemap-fonts/ (6.9 MB static glyphs) in the artifact
```

Axe asserted in the new present-state and teaching-line tests (same
helper gate as the suite); maplibre stays a spy double in jsdom — the
double now also records addSource/addLayer(before) so the layer-ordering
and source-URL assertions are structural, and the renderer behavior was
proven live (below).

**Live `--download-basemap` run (the real thing, this box, 2026-07-28):**

1. First run (full transcript in `install/install.log`; interactive
   answers were the real prompts): consent text printed BEFORE any network
   contact → bbox computed from the LIVE database — **9,624 stops with
   coordinates, longitude −71.848488…−70.276583, latitude
   41.581095…42.797837**, +0.10° margin → shown and confirmed as
   `west -71.9485 south 41.4811 east -70.1766 north 42.8978` → consent →
   daily build probe answered **20260728** → go-pmtiles tarball fetched
   and **"The tool's fingerprint matches the one pinned in this
   installer"** (sha256 verified) → `pmtiles extract` of the Boston-area
   bbox: **"Completed in 16.647184025s … Extract required 67 total
   requests. Extract transferred 287 MB (overfetch 0.05) for an archive
   size of 274 MB"** → `pmtiles show` verify → atomic move →
   `deploy/compose/basemap/region.pmtiles` (274,014,212 bytes). HONESTY
   NOTE: 274 MB, not the 10–50 MB the consent text calls typical — the
   MBTA service area is a dense major metro spanning ~1.7°×1.4°; the
   consent text says "usually", and the number for a small agency (the
   design target) is the Tri-Cities-class extract the orchestrator proved
   at 12 MB. Recorded, not hidden.
2. Second run (replace flow): mid-extract the upstream connection was
   RESET (`read tcp … connection reset by peer` — a real network
   failure, not simulated). The installer failed LOUDLY in plain language
   ("Any existing map on this computer is untouched. It is safe to run
   this command again."), the temp dir was cleaned by the trap, and the
   existing archive was byte-for-byte untouched — the atomic-write design
   proven by an unplanned live failure.
3. Third run: keep/replace prompt → replace → same build, checksum pass,
   extract completed → file replaced atomically with installer-set
   permissions `-rw-r--r--` (see the 403 finding below).

**Refusal paths (HEADWAY_COMPOSE_DIR seam, disposable dir — no live
touch):** no `.env` → plain refusal naming the install command; `--yes` →
refused ("consent must be a person"); combined with `--check` → mode
exclusivity refusal; existing file + "no" → "Keeping the existing map.
Nothing was downloaded or changed." with the file provably untouched;
consent "no" at the download gate → "Stopping at your request. Nothing was
downloaded; nothing changed."; garbage bbox (`banana`) AND an inverted box
(west>east) both rejected with the plain-words re-prompt, then a valid box
accepted. All exercised, output captured.

**Range-request proofs (both serving paths, real file):**

- *vite dev middleware* (localhost:5173, the restarted dev server):
  HEAD → 200, `Accept-Ranges: bytes`, Content-Length 274014212;
  `Range: bytes=0-6` → **206**, `Content-Range: bytes 0-6/274014212`,
  body exactly `PMTiles`; mid-file `bytes=1000000-1000099` → md5
  **identical to `dd` of the file** (5cb7f6b3…); open-ended
  `bytes=274000000-` → 206 with exactly 14,212 bytes; any other /basemap
  path → 404.
- *nginx, through the REAL web image* (built from `web/Dockerfile` +
  this wave's nginx.conf, run as a DISPOSABLE container
  `headway-0027-web-proof` on 127.0.0.1:18080 with the real
  `./basemap:ro` mount — the 0022 pattern; the live compose stack was
  never touched): first attempt answered **403 — a real finding**: the
  installer's umask 077 produced a 600 file the container's nginx user
  cannot read. Fixed IN the installer (dir 755 + file 644, with the
  recorded reasoning: the basemap is public map data, unlike everything
  else the installer writes) and re-proven through the installer's own
  third run. After the fix: HEAD → 200 octet-stream + no-cache;
  `bytes=0-6` → **206** + `PMTiles`; mid-file range md5 **identical to
  dd**; suffix range `bytes=-1024` → 206/1024; `/basemap/nope.pmtiles` →
  **404, not the SPA fallback**; `/map` → 200 text/html (SPA fallback
  intact). Container and image removed afterwards.
  `docker compose --profile app config` renders the volume
  (`source: …/deploy/compose/basemap, target: /basemap, read_only: true`).

**Live click-through** (headless system Chrome via playwright-core, the
0021/0024/0025/0026 pattern; real logins `dsteward` + `certifier` against
the live API through the live vite server; screenshots + full network log
in `docs/images/handoff-0027/`, logs `clickthrough-log.txt` +
`network-log.txt`):

- **Streets appear, both roles, both themes:** the whole MBTA system —
  9,6xx stops + 372 schematic lines — drawn OVER real OpenStreetMap
  streets, water, parks and place labels (Boston, Lowell, Worcester,
  Provincetown… — the vendored glyphs rendering), attribution chip
  bottom-right of the canvas (`dsteward-map-basemap-light.png`,
  `dsteward-map-basemap-dark.png` — the toggle swaps the whole street
  flavor live, attribution asserted visible in BOTH),
  `certifier-map-basemap-light.png`. Legend asserted live: basemap key
  line + "© OpenStreetMap contributors (Open Database License)…" + the
  POI limitation + the schematic line still present
  (`dsteward-map-legend.png`).
- **ZERO-EXTERNAL-REQUESTS, BASEMAP PRESENT:** every request of every
  phase (two logins, /map with tiles+glyphs streaming, theme switch,
  absent-state session) captured from the browser: **374 requests,
  origins {localhost:5173: 296, localhost:8000: 78}, EXTERNAL: 0** —
  tile range-reads and glyph fetches all same-origin, full per-request
  log in `network-log.txt`. This EXTENDS the 0024 proof (17 requests,
  0 external, basemap-absent) to the basemap-present state; the unit
  test pins both states forever.
- **Absent state (certifying_official):** file moved aside → fresh real
  login → /map: the 0024 canvas exactly (water-tone, schematic, no
  attribution anywhere — asserted) + the ONE quiet teaching line naming
  `./install/install.sh --download-basemap`
  (`certifier-map-absent-teaching.png`); the detection 404s are visible
  in the console/log — same-origin, honest. Steward absent-state
  no-teaching-line is pinned by unit test. File restored.

**Decisions the handoff left to this role (recorded):**

1. **Dev parity = vite middleware, not public/** (reasoning above, in the
   shipped code comment too).
2. **One vendored glyph stack** (Noto Sans Regular, complete 256 ranges —
   no 404-able range) with all label layers rewritten to it; Medium/
   Italic dropped as a typography-only trade. Labels are ON — the
   labels-off fallback was not needed.
3. **Sprites skipped in v0** (per the handoff's explicit permission):
   `pois` layer dropped entirely, `icon-image` stripped from
   `places_locality`; the limitation is stated in the legend, not buried.
4. **Basemap layers namespaced `basemap-*` and inserted before
   `routes-line`**; the theme's own background dropped in favor of the
   existing token canvas so the outside-coverage area and the registered
   contrast pairs are unchanged.
5. **The basemap file is world-readable by design** (installer chmod 644/
   755) — it is public map data; everything else the installer writes
   stays umask-077 private.
6. **`--download-basemap` is interactive-only** (`--yes` refused): a
   network download with a license obligation gets a human consent, every
   time — exactly the --check-updates posture, but stricter.

**Environment honesty (ops actions, none in the repo):**

- The vite dev server was RESTARTED (same command, same
  `VITE_API_BASE_URL=http://localhost:8000`, port 5173) to load this
  wave's config middleware, and is left running. The API on 127.0.0.1:8000
  and every live compose container were untouched.
- The live compose `web` container still runs its pre-0027 image without
  the mount (do-not-disturb rule for the live infra). The mount lands on
  the next `docker compose --profile app up -d` — which the installer's
  closing message tells the operator, and which the disposable-container
  proof stands in for here.
- `deploy/compose/basemap/region.pmtiles` (274 MB, build 20260728) is
  left in place — runtime data, gitignored by the tracked
  `basemap/.gitignore` (verified: `git check-ignore` names it; `git
  status` shows only scoped paths).
- Disposable proof container + image removed; the second (failed) run's
  temp dir removed by the installer's own trap.

**Deviations, honestly:**

- The orchestrator's scratchpad artifacts (the 12 MB tricities.pmtiles +
  pmtiles binary) were NOT present on disk when this wave started; every
  fact was re-proven fresh (daily build 200s for 20260726–28, tarballs
  re-downloaded, checksums computed, and the real extract run live). The
  orchestrator's cited numbers (12 MB / 5.0 s / 67 requests / overfetch
  0.05 for the Tri-Cities box) are consistent with what this wave
  observed at MBTA scale (67 requests, overfetch 0.05).
- go-pmtiles publishes no checksums.txt release asset, so the pinned
  sha256es are first-party fingerprints computed and recorded this wave
  (stated in the script comment) rather than upstream-published values.
- The MBTA-area extract is 274 MB, well above the "10–50 MB typical"
  consent estimate (dense major metro; the design target small agency is
  the 12 MB class). The consent text says "usually" and the >5° warning
  guards the runaway case; recorded here rather than papered over.

**Honest scope — not done / not proven:**

- Sprites/POI icons, Medium/Italic label styling, and per-layer label
  language options: v1 (Open Questions stand).
- The air-gapped path is documented with exact commands
  (docs/basemap.md) but was not executed end-to-end on a second machine
  this wave; every command in it is the same one the live run executed.
- The live compose web container was not recreated (rule above), so
  basemap-through-the-LIVE-stack remains proven by the identical-image
  disposable container, not the running one.
- Manual screen-reader pass remains the standing gap noted in
  web/README.md; keyboard/axe covered in the automated tests.
- `git status` shows exactly: modified `deploy/compose/compose.yaml`,
  `install/install.sh`, `install/README.md`, `web/` (10 files incl.
  package.json/lock), this handoff; new `deploy/compose/basemap/`
  (.gitignore only), `docs/basemap.md`, `docs/images/handoff-0027/`
  (6 screenshots + 2 logs), `web/public/basemap-fonts/` (258 files).
  No commits, per the wave's rule.

### Field follow-up (orchestrator, 2026-07-29): street style decoupled from the app theme

First agency UAT, the morning after the basemap reached their VM: it works —
and "in dark mode the map is also darkened, making it more difficult to read.
Going forward, we may not want to have the map pick up on Headway's theme."

Correct, and the reasoning generalizes: **map legibility is a task decision,
not a branding one.** Someone watching vehicle dots wants whichever streets
make the dots easiest to find, independent of the chrome they prefer. The
theme coupling shipped in this wave was an assumption, not a requirement.

Changed: the street background now has its own user setting (light | dark),
**light by default in BOTH themes**, persisted per browser
(`headway-basemap-style`), with the control beside the staleness-window
selector and a plain-words note that it is deliberately separate from the
app theme. The split is principled, not blanket: Headway's OWN marks — the
canvas, route lines, stops, vehicle dots — still follow the theme, because
those are our contrast-gated tokens; only the OpenStreetMap street layers
decouple. Pinned by a test that runs the app in dark theme and asserts light
streets, that a style swap re-adds street layers only (overlay layers
untouched), and that the choice persists. Web 263 tests, build/lint/types
clean.
