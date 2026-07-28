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
(appended by the implementing agent)
