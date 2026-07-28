# The street map under the Live map (the "basemap")

*Audience: the person who administers a Headway installation. Design
contract: `docs/handoffs/0027-from-platform-to-frontend-devops-basemap.md`.*

## What it is

Headway's **Live map** page draws your transit system from your own data —
stops, schematic route lines, vehicle positions — and by design it makes
**zero requests to the internet**: no outside tile service, no font
service, nothing. Out of the box, the background is a plain canvas.

The **basemap** is an optional street-map background for that page: real
streets, water, parks and place names for **your service area only**,
stored as **one file on your Headway computer**
(`deploy/compose/basemap/region.pmtiles`) and served by your own
installation. With it, the Live map shows your vehicles on actual streets
— and still makes zero external requests.

The map data comes from **OpenStreetMap** — the free, community-built map
of the world — packaged by the **Protomaps** project into a daily build
that Headway can cut your area out of.

## The consent model: one download, only when you ask

Headway never fetches map data on its own. The only way map data ever
arrives is:

```
./install/install.sh --download-basemap
```

run by an administrator, on the Headway computer. The command:

1. **Explains first, acts second.** Before any network contact it states
   exactly what it will download and from where: the map-extract tool from
   `github.com` (pinned version `v1.31.2`, verified against a sha256
   fingerprint recorded in the installer before it is run) and your area's
   map data from `build.protomaps.com` (usually 10–50 MB).
2. **Reads the map area from your own data**: the bounding box of your
   stops (`canonical.stops`) plus a stated ~7-mile margin — shown to you
   for confirmation. No stops yet? It asks you for the area in plain
   words, with an example.
3. Downloads **only your area** out of the daily planet build (the tool
   reads the big file with byte-range requests; the whole planet is never
   downloaded), writes to a temporary file, and moves it into place
   **atomically** — a failed or interrupted run leaves nothing
   half-written and any existing map untouched.
4. Never contacts either site again. The map page serves the file from
   your installation only.

Re-running the command is always safe: it offers to keep or replace an
existing map, and every re-run is the same consent conversation again.

## Refreshing the map data

Streets change slowly. When you want newer map data — a new development, a
renamed road — simply re-run `./install/install.sh --download-basemap` and
choose "replace". Once or twice a year is plenty for most agencies.
Headway will never do this for you in the background; the download happens
only when you run the command.

## The license credit (please do not remove it)

OpenStreetMap data is licensed under the **Open Database License (ODbL)**,
which requires visible credit. Whenever street tiles render, the Live map
shows **"© OpenStreetMap contributors · Protomaps"** on the map itself and
repeats the credit in the map legend. Headway honors licenses
conspicuously; the credit is not optional chrome. Full terms:
`openstreetmap.org/copyright`.

The map label typeface (Noto Sans, SIL Open Font License 1.1) ships inside
Headway's own web bundle (`web/public/basemap-fonts/`) so label rendering
also never contacts a font server.

## Computers with no internet access (air-gapped path)

The Headway box never needs internet access for the map to *work* — only
the one-time download needs it. If the Headway computer is air-gapped, run
the extract on any machine that does have internet access:

1. Download the extract tool from
   `https://github.com/protomaps/go-pmtiles/releases` (v1.31.2, the
   `go-pmtiles_1.31.2_Linux_x86_64.tar.gz` asset or your platform's
   equivalent) and unpack the `pmtiles` binary.
2. Run the extract for your area (west,south,east,north — this example is
   the Tri-Cities area of Washington state; substitute your own):

   ```
   ./pmtiles extract https://build.protomaps.com/20260727.pmtiles \
       region.pmtiles --bbox=-119.55,46.05,-118.85,46.45
   ```

   Use today's date in `YYYYMMDD.pmtiles` form (step back a day if today's
   build is not up yet).
3. Copy `region.pmtiles` to the Headway computer at:

   ```
   deploy/compose/basemap/region.pmtiles
   ```

4. Reload the Live map page (and, the first time after updating Headway to
   a version with basemap support, refresh the services once so the web
   container mounts the folder:
   `docker compose --project-directory deploy/compose --profile app up -d`).

## What this feature deliberately does NOT do

- **No automatic refresh.** Every download is a person running the
  command and consenting.
- **No nationwide or worldwide maps.** The extract covers your service
  area's bounding box, by design — that is all the Live map needs.
- **No routing, no geocoding, no address search.** The basemap is visual
  context under your own data, nothing more.
- **No change to the honesty surfaces.** Route lines remain schematic
  (straight lines between stops) and the legend still says so; streets
  underneath are context, not the path vehicles drive. Vehicles, stops and
  staleness behavior are unchanged.
- **v0 limitation, stated in the legend too:** street and place names are
  drawn (one bundled typeface); point-of-interest icons are not included
  in this version.

## How it is served (for the technically curious)

The file is a [PMTiles](https://github.com/protomaps/PMTiles) archive —
a single file the browser reads with HTTP byte-range requests. The web
container bind-mounts `deploy/compose/basemap/` read-only and nginx serves
it at `/basemap/` with range support; in development, Vite serves the same
path from the same folder. The map page detects the file at runtime (a
HEAD plus a ranged read of the archive's magic bytes): absent means the
plain canvas, exactly as before; present means streets. The directory is
gitignored (like `tides-drop/`): map data is per-installation runtime
data, never source.
