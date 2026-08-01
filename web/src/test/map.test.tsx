/**
 * /map — the living system view (handoff 0024, design point 1).
 *
 * MapLibre's WebGL canvas cannot run in jsdom, so the module is mocked
 * with a spy double; these tests pin the HONESTY SURFACES around the
 * canvas — the staleness chip's live/quiet states, the verbatim server
 * notes (ops boundary, schematic geometry, staleness), the SIMULATED
 * badge, the window selector's requests, the teaching empty states, the
 * vehicle list equivalent — and the no-external-requests posture at the
 * unit level (every fetch the view makes is same-origin API-relative).
 * The real-browser proof (zero third-party requests on a live /map) is
 * the headless-Chrome network log in the handoff evidence.
 */

import { describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { RouteHandler } from "./helpers";
import { copy } from "../copy";
import { BASEMAP_FONT, BASEMAP_STYLES } from "../map/basemapStyle.ts";
import { contrastRatio } from "../map/contrast.ts";
import {
  FINDING_GLYPH,
  MARK_HALO,
  TOKEN_MARK_COLORS,
  modeColorExpression,
  routeOpacityExpression,
  routeWidthExpression,
} from "../map/marks";
import { PULSE_STATIC } from "../map/pulse";

// ---- the maplibre-gl double (hoisted before the view imports it) ----
vi.mock("maplibre-gl", () => {
  class FakeMap {
    handlers: Record<string, (...args: unknown[]) => void> = {};
    canvas = document.createElement("canvas");
    /** Sources added at runtime, by id (the basemap wave asserts the
     *  pmtiles source is only ever added in the present state). */
    sources: Record<string, unknown> = {};
    /** addLayer calls in order: {id, before} — pins that every basemap
     *  street layer is inserted BELOW the schematic route lines. The whole
     *  spec is kept too, so the basemap-style wave (handoff 0043) can
     *  assert the AUTHORED paint actually reaches the canvas. */
    layerAdds: { id: string; before?: string; layer: LayerLike }[] = [];
    /** setPaintProperty calls in order — the background ground color
     *  follows the STREET style once tiles are drawing (handoff 0043). */
    paintSets: { id: string; prop: string; value: unknown }[] = [];
    /** setFeatureState calls in order — the relationship inspector lights
     *  a finding's routes IN PLACE rather than re-sending the source
     *  (handoff 0043, design points 6 and 7). */
    featureStates: { source: string; id: unknown; state: unknown }[] = [];
    /** The last data each source was given, so the mode join and the
     *  findings placement can be asserted on what reached the canvas. */
    sourceData: Record<string, unknown> = {};
    constructor() {
      fakeMaps.push(this);
    }
    on(event: string, a?: unknown, b?: unknown) {
      const cb = (typeof a === "function" ? a : b) as (
        ...args: unknown[]
      ) => void;
      const key = typeof a === "string" ? `${event}:${a}` : event;
      this.handlers[key] = cb;
      // The style "loads" immediately in the double.
      if (event === "load") cb();
      return this;
    }
    addSource(id: string, spec: unknown) {
      this.sources[id] = spec;
    }
    addLayer(layer: LayerLike, before?: string) {
      this.layerAdds.push({ id: layer.id, before, layer });
    }
    removeLayer() {}
    getLayer() {
      return { id: "x" };
    }
    getSource(id: string) {
      if (id === "basemap" && !(id in this.sources)) return undefined;
      return {
        setData: (data: unknown) => {
          this.sourceData[id] = data;
        },
      };
    }
    setPaintProperty(id: string, prop: string, value: unknown) {
      this.paintSets.push({ id, prop, value });
    }
    setFilter() {}
    setFeatureState(
      target: { source: string; id: unknown },
      state: unknown,
    ) {
      this.featureStates.push({
        source: target.source,
        id: target.id,
        state,
      });
    }
    getCanvas() {
      return this.canvas;
    }
    fitBounds() {}
    getZoom() {
      return 10;
    }
    jumpTo = vi.fn();
    easeTo = vi.fn();
    remove() {}
  }
  return { Map: FakeMap, setWorkerUrl: () => {}, addProtocol: () => {} };
});
const fakeMaps: FakeMapShape[] = [];
interface LayerLike {
  id: string;
  type?: string;
  paint?: Record<string, unknown>;
  layout?: Record<string, unknown>;
}
interface FakeMapShape {
  sources: Record<string, unknown>;
  layerAdds: { id: string; before?: string; layer: LayerLike }[];
  paintSets: { id: string; prop: string; value: unknown }[];
  featureStates: { source: string; id: unknown; state: unknown }[];
  sourceData: Record<string, unknown>;
}

// ---- fixtures mirroring the live envelopes (handoff 0023 evidence) ----

const OPS_NOTE =
  "Operations data — not an NTD reported figure. Live vehicle positions are never certifiable, never part of any submission, and never a gate on certification (migration 0024 boundary).";
const GEOMETRY_NOTE =
  "Schematic geometry: each route line connects the stops of the route's most common trip pattern with straight segments. It shows structure, not streets — Headway has not ingested shapes.txt (street-level geometry is a recorded future increment), and this line must not be presented as the path vehicles drive.";
const STALE_NOTE =
  "No vehicle has reported a position in the last 300 seconds. The newest position on record is 55141 seconds old — the feed is stale or service is not running, not an empty fleet.";

const stopsBody = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [-71.082754, 42.330957] },
      properties: { stop_id: "1", name: "Washington St opp Ruggles St" },
    },
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [-71.1, 42.34] },
      properties: { stop_id: "2", name: "Second Stop" },
    },
  ],
  category: "ops",
  ops_note: OPS_NOTE,
  stop_count: 2,
  stops_without_coordinates: 0,
  cap: 50000,
  truncated: false,
  total_stops: 2,
  note: null,
};

const routesBody = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-71.082754, 42.330957],
          [-71.1, 42.34],
        ],
      },
      properties: {
        route_id: "Red",
        short_name: "Red",
        long_name: "Red Line",
        mode: "subway",
        geometry_kind: "schematic_stop_sequence",
        pattern_trip_count: 613,
        stop_count: 2,
        stops_missing_coordinates: 0,
      },
    },
  ],
  category: "ops",
  ops_note: OPS_NOTE,
  geometry_kind: "schematic_stop_sequence",
  geometry_note: GEOMETRY_NOTE,
  route_count: 1,
  routes_without_geometry: 0,
  cap: 2000,
  truncated: false,
  total_routes_with_trips: 1,
  computed_at: "2026-07-22T18:18:17Z",
  cache_ttl_seconds: 900,
  cache_note:
    "Served from a per-process cache for up to cache_ttl_seconds after computed_at; schedule geometry changes only when a new static GTFS feed is ingested.",
  note: null,
};

const liveVehicle = {
  vehicle_id: "1702",
  latitude: 41.8327,
  longitude: -71.4128,
  recorded_at: "2026-07-22T18:17:20Z",
  age_seconds: 17,
  bearing: null,
  speed_mps: null,
  trip_id: "SouthBase-826224-881",
  route_id: "CR-Providence",
  source_record_id: "raw-1",
  source: "gtfs_rt",
  simulated: false,
};

const simulatedVehicle = {
  ...liveVehicle,
  vehicle_id: "SIM-9",
  trip_id: null,
  route_id: null,
  source_record_id: "raw-2",
  source: "tides_simulated",
  simulated: true,
};

/** A FRESH feed: newest position 17 s before as_of. */
const vehiclesLive = {
  as_of: "2026-07-22T18:17:37Z",
  max_age_seconds: 300,
  category: "ops",
  ops_note: OPS_NOTE,
  vehicles: [liveVehicle, simulatedVehicle],
  vehicle_count: 2,
  total_in_window: 2,
  cap: 5000,
  truncated: false,
  newest_position_at: "2026-07-22T18:17:20Z",
  note: null,
};

/** The QUIET feed exactly as live-verified in handoff 0023: zero vehicles
 *  in the default window, newest position ~15.3 h old, note stated. */
const vehiclesQuiet = {
  ...vehiclesLive,
  vehicles: [],
  vehicle_count: 0,
  total_in_window: 0,
  newest_position_at: "2026-07-22T02:58:36Z",
  note: STALE_NOTE,
};

/** The widened 24 h window over the same stale feed: real dots, old ages. */
const vehiclesWide = {
  ...vehiclesLive,
  max_age_seconds: 86400,
  vehicles: [{ ...liveVehicle, age_seconds: 55141 }],
  vehicle_count: 1,
  total_in_window: 1,
  newest_position_at: "2026-07-22T02:58:36Z",
  note: null,
};

function geometryRoutes(): Record<string, RouteHandler> {
  return {
    "GET /geometry/stops": { status: 200, body: stopsBody },
    "GET /geometry/routes": { status: 200, body: routesBody },
  };
}

describe("/map", () => {
  it("badges the surface as operations insight, renders the server's ops note and the SCHEMATIC legend note verbatim, and passes axe", async () => {
    signInAs("viewer");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
    });
    renderApp("/map");

    expect(
      await screen.findByRole("heading", { name: "Live map" }),
    ).toBeInTheDocument();
    // The ops boundary ON the surface: badge + the server's note verbatim.
    expect(
      await screen.findByText("Operations metric — not an NTD reported figure"),
    ).toBeInTheDocument();
    expect(await screen.findByText(OPS_NOTE)).toBeInTheDocument();
    // The legend: swatch labels + the schematic note VERBATIM (the
    // geometry_kind honesty made visible).
    const legend = await screen.findByRole("region", {
      name: "What the map shows",
    });
    expect(legend).toHaveTextContent("Route line — schematic");
    expect(legend).toHaveTextContent(GEOMETRY_NOTE);
    expect(legend).toHaveTextContent(
      "About the route lines, in the server's own words:",
    );

    await expectNoAxeViolations();
  });

  it("shows the LIVE staleness chip (newest position time) and the vehicle count while the feed is fresh", async () => {
    signInAs("viewer");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
    });
    renderApp("/map");

    expect(
      await screen.findByText("Live — newest position at 18:17:20 UTC"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("2 vehicles with a position in the selected window."),
    ).toBeInTheDocument();
    // The poll cadence is stated — and the no-fake-motion rule with it.
    expect(
      screen.getByText(/A vehicle's dot moves only when a new position is reported/),
    ).toBeInTheDocument();
  });

  it("degrades HONESTLY when the feed goes quiet: the quiet chip with the real gap, the server's note verbatim, and the teaching line — never fake motion", async () => {
    signInAs("viewer");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesQuiet },
    });
    renderApp("/map");

    // as_of − newest_position_at = 15 h 19 min: said plainly.
    expect(
      await screen.findByText("No vehicle positions in the last 15 h 19 min"),
    ).toBeInTheDocument();
    // The server's own staleness note, verbatim.
    expect(screen.getByText(STALE_NOTE)).toBeInTheDocument();
    // The teaching line: how an agency gets its first dot.
    expect(
      screen.getByText(/Vehicle dots appear when a live vehicle-positions feed/),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("the refresh button visibly WORKS even when nothing changed: it re-asks the API and updates the last-checked stamp (UAT 2026-07-28: a silent refresh reads as broken)", async () => {
    signInAs("viewer");
    const calls = mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesQuiet },
    });
    renderApp("/map");
    const user = userEvent.setup();

    // Initial load: one vehicles request, and the round-trip is stamped.
    await screen.findByText(/No vehicle positions in the last/);
    expect(await screen.findByText(/^Last checked /)).toBeInTheDocument();
    const vehicleCalls = () =>
      calls.filter((c) => c.path.startsWith("/ops/vehicles/latest")).length;
    const before = vehicleCalls();

    await user.click(
      screen.getByRole("button", { name: copy.map.refresh }),
    );

    // The API was genuinely asked again — same quiet answer, but the page
    // PROVES it checked rather than silently doing nothing.
    expect(vehicleCalls()).toBe(before + 1);
    expect(await screen.findByText(/^Last checked /)).toBeInTheDocument();
  });

  it("widening the window requests max_age_seconds=86400, draws the last known positions, and KEEPS the quiet chip while the feed is stale (both honesty states at once)", async () => {
    signInAs("viewer");
    const calls = mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": (call) => {
        const age = new URL(call.url, "http://test").searchParams.get(
          "max_age_seconds",
        );
        return {
          status: 200,
          body: age === "86400" ? vehiclesWide : vehiclesQuiet,
        };
      },
    });
    const user = userEvent.setup();
    renderApp("/map");

    await screen.findByText("No vehicle positions in the last 15 h 19 min");
    await user.click(
      screen.getByRole("button", { name: "The last 24 hours" }),
    );

    // The request carries the widened window…
    expect(
      calls.some(
        (c) =>
          c.path === "/ops/vehicles/latest" &&
          new URL(c.url, "http://test").searchParams.get("max_age_seconds") ===
            "86400",
      ),
    ).toBe(true);
    // …vehicles appear…
    expect(
      await screen.findByText("1 vehicle with a position in the selected window."),
    ).toBeInTheDocument();
    // …and the chip STAYS quiet: last known positions are not a live feed.
    expect(
      screen.getByText("No vehicle positions in the last 15 h 19 min"),
    ).toBeInTheDocument();
    // The window note says exactly what widening means.
    expect(
      screen.getByText(/a dot never moves without a new report/),
    ).toBeInTheDocument();
  });

  it("lists vehicles as an accessible table equivalent: route context, verbatim age, source, the per-vehicle SIMULATED badge, and a detail panel from the list", async () => {
    signInAs("data_steward");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
    });
    const user = userEvent.setup();
    renderApp("/map");

    await user.click(
      await screen.findByRole("button", { name: "List the vehicles" }),
    );
    const table = screen.getByRole("table");
    const row1702 = within(table)
      .getByRole("button", { name: /1702/ })
      .closest("tr") as HTMLElement;
    expect(row1702).toHaveTextContent("CR-Providence");
    expect(row1702).toHaveTextContent("17"); // age_seconds verbatim
    expect(row1702).toHaveTextContent("gtfs_rt");
    // The SIMULATED vehicle wears its badge in the list…
    const simRow = within(table)
      .getByRole("button", { name: /SIM-9/ })
      .closest("tr") as HTMLElement;
    expect(within(simRow).getByText("Simulated data")).toBeInTheDocument();
    expect(simRow).toHaveTextContent("Not assigned");

    // …and in the detail panel, with the unassigned state served honestly.
    await user.click(within(simRow).getByRole("button", { name: /SIM-9/ }));
    const panel = screen.getByRole("region", { name: "Vehicle SIM-9" });
    expect(within(panel).getByText("Simulated data")).toBeInTheDocument();
    expect(panel).toHaveTextContent(
      "Not assigned to a route or trip in this report — served unassigned, never guessed.",
    );
    expect(panel).toHaveTextContent(
      "Position as of 17 seconds ago (at the last refresh).",
    );
    expect(panel).toHaveTextContent("Source feed: tides_simulated");
    await user.click(
      within(panel).getByRole("button", { name: "Close vehicle details" }),
    );
    expect(
      screen.queryByRole("region", { name: "Vehicle SIM-9" }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("caps the vehicle list LOUDLY (the map and counts keep everything)", async () => {
    signInAs("viewer");
    const many = Array.from({ length: 120 }, (_, i) => ({
      ...liveVehicle,
      vehicle_id: `bus-${i}`,
      source_record_id: `raw-${i}`,
    }));
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": {
        status: 200,
        body: {
          ...vehiclesLive,
          vehicles: many,
          vehicle_count: 120,
          total_in_window: 120,
        },
      },
    });
    const user = userEvent.setup();
    renderApp("/map");

    await user.click(
      await screen.findByRole("button", { name: "List the vehicles" }),
    );
    expect(
      screen.getByText(/Showing the first 100 of 120 vehicles in the window/),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(101); // header + cap
  });

  it("teaches on a truly empty system: no geometry means a warm what-this-is + the concrete first action", async () => {
    signInAs("viewer");
    mockApi({
      "GET /geometry/stops": {
        status: 200,
        body: { ...stopsBody, features: [], stop_count: 0, total_stops: 0 },
      },
      "GET /geometry/routes": {
        status: 200,
        body: {
          ...routesBody,
          features: [],
          route_count: 0,
          total_routes_with_trips: 0,
        },
      },
      "GET /ops/vehicles/latest": {
        status: 200,
        body: { ...vehiclesQuiet, newest_position_at: null, note: null },
      },
    });
    renderApp("/map");

    expect(
      await screen.findByText(/No stops or routes to draw yet/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/ingest the agency's GTFS static feed/),
    ).toBeInTheDocument();
    // No positions on record at all: the chip states that, plainly.
    expect(
      await screen.findByText("No vehicle positions on record"),
    ).toBeInTheDocument();
  });

  it("makes ONLY same-origin API requests — no tile, font, sprite, or any other external URL leaves the page", async () => {
    signInAs("viewer");
    const calls = mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
    });
    renderApp("/map");
    await screen.findByText("Live — newest position at 18:17:20 UTC");

    expect(calls.length).toBeGreaterThan(0);
    for (const call of calls) {
      // Relative API paths only — an absolute URL would be a phone-home.
      expect(call.url.startsWith("/")).toBe(true);
    }
    expect(copy.map.intro).toContain("no request ever leaves this installation");
  });

  // ---- the self-hosted basemap (handoff 0027) ----------------------------

  /** The present state: HEAD answers, and the ranged GET proves both byte
   *  ranges and the PMTiles magic — exactly what the view checks live. */
  const basemapPresentRoutes: Record<string, RouteHandler> = {
    "HEAD /basemap/region.pmtiles": { status: 200, rawBody: "" },
    "GET /basemap/region.pmtiles": {
      status: 206,
      rawBody: "PMTiles",
      headers: {
        "Content-Range": "bytes 0-6/12582912",
        "Accept-Ranges": "bytes",
      },
    },
  };

  it("with NO basemap downloaded, the canvas stays exactly as before: no pmtiles source, no street layers, no attribution — and no teaching line for a data steward", async () => {
    signInAs("data_steward");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
      // DEFAULT_ROUTES already answers the HEAD with 404 (absent).
    });
    renderApp("/map");
    await screen.findByText("Live — newest position at 18:17:20 UTC");

    const map = fakeMaps[fakeMaps.length - 1];
    expect("basemap" in map.sources).toBe(false);
    expect(
      map.layerAdds.filter((l) => l.id.startsWith("basemap-")),
    ).toHaveLength(0);
    expect(
      screen.queryByText(copy.map.basemap.attribution),
    ).not.toBeInTheDocument();
    // The quiet teaching line is for certifying officials ONLY.
    expect(
      screen.queryByText(copy.map.basemap.teachingAbsent),
    ).not.toBeInTheDocument();
  });

  it("teaches the certifying official — one quiet line naming the installer command — when no basemap exists", async () => {
    signInAs("certifying_official");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesQuiet },
    });
    renderApp("/map");

    expect(
      await screen.findByText(copy.map.basemap.teachingAbsent),
    ).toBeInTheDocument();
    expect(copy.map.basemap.teachingAbsent).toContain(
      "./install/install.sh --download-basemap",
    );
  });

  it("with the basemap PRESENT: the self-hosted archive becomes a source, every street layer is inserted UNDER the schematic route lines, the POI icon layer is dropped (sprites not vendored, v0), and the ODbL attribution is visible on the map and in the legend — axe green", async () => {
    signInAs("viewer");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
      ...basemapPresentRoutes,
    });
    renderApp("/map");

    // Attribution ON the canvas whenever tiles render — non-negotiable.
    expect(
      await screen.findByText("© OpenStreetMap contributors · Protomaps"),
    ).toBeInTheDocument();

    const map = fakeMaps[fakeMaps.length - 1];
    // The one source: this installation's own archive, via pmtiles://.
    const src = map.sources["basemap"] as { url: string; attribution: string };
    expect(src.url).toBe(
      `pmtiles://${window.location.origin}/basemap/region.pmtiles`,
    );
    expect(src.attribution).toBe(copy.map.basemap.attribution);
    // Streets exist and sit BELOW the overlay: every basemap layer was
    // added with beforeId "routes-line".
    const streetAdds = map.layerAdds.filter((l) =>
      l.id.startsWith("basemap-"),
    );
    expect(streetAdds.length).toBeGreaterThan(0);
    for (const add of streetAdds) {
      expect(add.before).toBe("routes-line");
    }
    // Sprites are skipped in v0: the POI icon layer is not added at all.
    expect(streetAdds.some((l) => l.id === "basemap-pois")).toBe(false);

    // The legend carries the basemap line, the ODbL credit, and the
    // limitation in plain words — while the schematic line STAYS.
    const legend = await screen.findByRole("region", {
      name: "What the map shows",
    });
    expect(legend).toHaveTextContent(copy.map.basemap.legendLine);
    expect(legend).toHaveTextContent(/© OpenStreetMap contributors/);
    expect(legend).toHaveTextContent(/without point-of-interest icons/);
    expect(legend).toHaveTextContent(GEOMETRY_NOTE);

    await expectNoAxeViolations();
  });

  it("street style is the USER's choice, never the app theme: dark chrome still gets light streets by default, switching swaps the street layers only, and the choice persists (UAT 2026-07-29)", async () => {
    window.localStorage.setItem("headway-theme", "dark");
    window.localStorage.removeItem("headway-basemap-style");
    signInAs("viewer");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
      ...basemapPresentRoutes,
    });
    renderApp("/map");
    const user = userEvent.setup();

    await screen.findByText("© OpenStreetMap contributors · Protomaps");
    const map = fakeMaps[fakeMaps.length - 1];

    // The app is in DARK theme, yet the streets came up LIGHT: legibility
    // is a task decision, not a branding one.
    const lightControl = screen.getByRole("button", {
      name: copy.map.basemap.style.light,
    });
    expect(lightControl).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: copy.map.basemap.style.dark }),
    ).toHaveAttribute("aria-pressed", "false");

    const streetAddsBefore = map.layerAdds.filter((l) =>
      l.id.startsWith("basemap-"),
    ).length;
    expect(streetAddsBefore).toBeGreaterThan(0);
    // Headway's OWN marks were added too and must survive a style swap.
    const overlayAddsBefore = map.layerAdds.filter(
      (l) => !l.id.startsWith("basemap-"),
    ).length;

    await user.click(
      screen.getByRole("button", { name: copy.map.basemap.style.dark }),
    );

    // Only street layers were re-added; the overlay layers were never
    // touched, and the choice is remembered for next time.
    expect(
      map.layerAdds.filter((l) => l.id.startsWith("basemap-")).length,
    ).toBeGreaterThan(streetAddsBefore);
    expect(
      map.layerAdds.filter((l) => !l.id.startsWith("basemap-")).length,
    ).toBe(overlayAddsBefore);
    expect(window.localStorage.getItem("headway-basemap-style")).toBe("dark");
    expect(
      screen.getByRole("button", { name: copy.map.basemap.style.dark }),
    ).toHaveAttribute("aria-pressed", "true");

    window.localStorage.removeItem("headway-theme");
    window.localStorage.removeItem("headway-basemap-style");
  });

  // ---- the two authored, contrast-tuned styles (handoff 0043) ----------

  it("draws HEADWAY's OWN authored street styles, not the vendor flavors: the dark map puts LIGHT streets on a near-black ground and every label carries a raised halo", async () => {
    window.localStorage.removeItem("headway-basemap-style");
    signInAs("viewer");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
      ...basemapPresentRoutes,
    });
    renderApp("/map");
    const user = userEvent.setup();
    await screen.findByText(copy.map.basemap.attribution);
    const map = fakeMaps[fakeMaps.length - 1];

    const streetLayers = () =>
      map.layerAdds.filter((l) => l.id.startsWith("basemap-"));

    // Light is what came up (the ITS manager found it legible), and it is
    // OURS: the ground and the road casings are the authored values.
    /** The most recent add of a layer id — after a style swap that is the
     *  layer the newly chosen style put on the canvas. */
    const latest = (id: string) =>
      [...streetLayers()].reverse().find((l) => l.id === id);

    const lightGround = String(BASEMAP_STYLES.light.theme.earth);
    expect(latest("basemap-earth")?.layer.paint?.["fill-color"]).toBe(
      lightGround,
    );

    const beforeSwap = streetLayers().length;
    await user.click(
      screen.getByRole("button", { name: copy.map.basemap.style.dark }),
    );
    expect(streetLayers().length).toBeGreaterThan(beforeSwap);

    const darkTheme = BASEMAP_STYLES.dark.theme as Record<string, string>;
    expect(latest("basemap-earth")?.layer.paint?.["fill-color"]).toBe(
      darkTheme.earth,
    );

    // The street network is LIGHTER than the ground it sits on — the whole
    // point of the wave — and the separation is measured, never eyeballed.
    expect(latest("basemap-roads_minor")).toBeDefined();
    expect(
      contrastRatio(darkTheme.minor_b, darkTheme.earth),
    ).toBeGreaterThanOrEqual(3);
    expect(
      contrastRatio(darkTheme.roads_label_minor, darkTheme.earth),
    ).toBeGreaterThanOrEqual(4.5);

    // Every label layer that reached the canvas carries the raised halo.
    const symbols = streetLayers().filter((l) => l.layer.type === "symbol");
    expect(symbols.length).toBeGreaterThan(0);
    for (const s of symbols) {
      expect(Number(s.layer.paint?.["text-halo-width"])).toBeGreaterThan(1);
      expect(s.layer.layout?.["text-font"]).toEqual(["Noto Sans Regular"]);
    }

    window.localStorage.removeItem("headway-basemap-style");
  });

  it("the ground under everything follows the STREET style, not the app theme: choosing the dark map repaints the canvas to its own near-black, so no pale halo survives around the extracted region", async () => {
    window.localStorage.removeItem("headway-basemap-style");
    signInAs("viewer");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
      ...basemapPresentRoutes,
    });
    renderApp("/map");
    const user = userEvent.setup();
    await screen.findByText(copy.map.basemap.attribution);
    const map = fakeMaps[fakeMaps.length - 1];

    const lastBackground = () =>
      [...map.paintSets]
        .reverse()
        .find((p) => p.id === "background" && p.prop === "background-color")
        ?.value;

    expect(lastBackground()).toBe(BASEMAP_STYLES.light.theme.background);

    await user.click(
      screen.getByRole("button", { name: copy.map.basemap.style.dark }),
    );
    expect(lastBackground()).toBe(BASEMAP_STYLES.dark.theme.background);

    window.localStorage.removeItem("headway-basemap-style");
  });

  it("names the street style in use and states the legibility promise in the legend — the ITS manager's report answered where people look", async () => {
    window.localStorage.removeItem("headway-basemap-style");
    signInAs("viewer");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
      ...basemapPresentRoutes,
    });
    renderApp("/map");
    const user = userEvent.setup();
    await screen.findByText(copy.map.basemap.attribution);

    const legend = screen.getByRole("region", {
      name: copy.map.legend.heading,
    });
    expect(legend).toHaveTextContent(
      copy.map.basemap.legendStyleLine(BASEMAP_STYLES.light.name),
    );
    // The promise is stated in plain language with the real numbers.
    expect(copy.map.basemap.legendStyleLine("x")).toContain("3:1");
    expect(copy.map.basemap.legendStyleLine("x")).toContain("4.5:1");
    expect(copy.map.basemap.style.note).toContain("3:1");

    await user.click(
      screen.getByRole("button", { name: copy.map.basemap.style.dark }),
    );
    expect(legend).toHaveTextContent(
      copy.map.basemap.legendStyleLine(BASEMAP_STYLES.dark.name),
    );
    await expectNoAxeViolations();

    window.localStorage.removeItem("headway-basemap-style");
  });

  it("EXTENDS the zero-external-requests pin to the basemap-present state: every request stays same-origin (detection HEAD + ranged magic GET included)", async () => {
    signInAs("viewer");
    const calls = mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
      ...basemapPresentRoutes,
    });
    renderApp("/map");
    await screen.findByText("© OpenStreetMap contributors · Protomaps");

    // The detection really ran: HEAD, then a ranged GET for the magic.
    const head = calls.find(
      (c) => c.method === "HEAD" && c.path === "/basemap/region.pmtiles",
    );
    const ranged = calls.find(
      (c) => c.method === "GET" && c.path === "/basemap/region.pmtiles",
    );
    expect(head).toBeDefined();
    expect(ranged?.headers["Range"]).toBe("bytes=0-6");
    // And EVERY request in the log — API, detection, all of it — is a
    // same-origin relative path. Nothing leaves this installation.
    expect(calls.length).toBeGreaterThan(0);
    for (const call of calls) {
      expect(call.url.startsWith("/")).toBe(true);
    }
  });

  it("fails LOUDLY when a basemap file answers without byte-range support: plain-language alert, no attribution, no street layers (the canvas still works)", async () => {
    signInAs("viewer");
    mockApi({
      ...geometryRoutes(),
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesLive },
      "HEAD /basemap/region.pmtiles": { status: 200, rawBody: "" },
      // A server that ignores Range answers 200 — PMTiles cannot work.
      "GET /basemap/region.pmtiles": { status: 200, rawBody: "PMTiles" },
    });
    renderApp("/map");

    expect(
      await screen.findByText(copy.map.basemap.unusable),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(copy.map.basemap.attribution),
    ).not.toBeInTheDocument();
    const map = fakeMaps[fakeMaps.length - 1];
    expect("basemap" in map.sources).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Handoff 0043, second half: mode-aware marks, the flagged-findings layer and
// the relationship inspector. The canvas is a spy double, so these tests pin
// (a) exactly what paint reaches it, (b) the readable equivalents beside it,
// and (c) the honesty rules that would otherwise be prose in a comment.
// ---------------------------------------------------------------------------

/** Two routes with DIFFERENT modes — the mode marks need something to tell
 *  apart, and the mode filter needs more than one option to be real. */
const routesTwoModes = {
  ...routesBody,
  features: [
    routesBody.features[0],
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-71.05, 42.35],
          [-71.06, 42.36],
          [-71.07, 42.37],
        ],
      },
      properties: {
        route_id: "39",
        short_name: "39",
        long_name: "Forest Hills — Back Bay",
        mode: "bus",
        geometry_kind: "schematic_stop_sequence",
        pattern_trip_count: 200,
        stop_count: 3,
        stops_missing_coordinates: 0,
      },
    },
  ],
  route_count: 2,
  total_routes_with_trips: 2,
};

/** One vehicle per mode, plus one the schedule data cannot place. */
const vehiclesByMode = {
  ...vehiclesLive,
  vehicles: [
    { ...liveVehicle, vehicle_id: "1702", route_id: "Red" },
    { ...liveVehicle, vehicle_id: "2101", route_id: "39", source_record_id: "raw-3" },
    { ...simulatedVehicle },
  ],
  vehicle_count: 3,
  total_in_window: 3,
};

function subjectContext(routeIds: string[]) {
  return {
    version: 1,
    kind: "trips",
    total: 4,
    grouped_by: "block",
    group_count: 1,
    group_cap: 20,
    trip_id_cap: 20,
    groups: [
      {
        block_id: "225",
        block_label: "225-4",
        trip_count: 4,
        routes: routeIds.map((id) => ({
          route_id: id,
          short_name: id,
          long_name: `${id} Line`,
        })),
        route_count: routeIds.length,
        first_departure: "2026-07-22T05:00:00Z",
        last_departure: "2026-07-22T23:00:00Z",
        trip_ids: ["t1", "t2", "t3", "t4"],
      },
    ],
  };
}

const flaggedIssue = {
  issue_id: "dq-1",
  issue_type: "coverage_gap",
  severity: "blocking",
  status: "open",
  owner: null,
  title: "Recorded miles stop part-way through block 225-4",
  description:
    "Four trips on block 225-4 have no recorded position after 14:10, so the miles for that block cannot be certified.",
  created_at: "2026-07-22T15:00:00Z",
  resolved_at: null,
  resolution: null,
  subject_context: subjectContext(["39"]),
};

/** A finding that CANNOT be drawn — it is about the run, not about trips. */
const runWideIssue = {
  ...flaggedIssue,
  issue_id: "dq-2",
  title: "The feed reported no positions at all for two hours",
  subject_context: null,
};

const calcRunNamingIssue = {
  run_id: "run-9",
  requested_by: "steward",
  requested_at: "2026-07-23T09:00:00Z",
  period_start: "2026-06-01",
  period_end: "2026-07-01",
  status: "succeeded",
  started_at: "2026-07-23T09:00:01Z",
  finished_at: "2026-07-23T09:02:00Z",
  runner_pid: null,
  summary: {
    metrics: [
      {
        calc_name: "vrm_v0",
        calc_version: "0.3.0",
        metric: "vrm",
        unit: "miles",
        scope: "agency",
        outcome: "refused",
        value: null,
        metric_value_id: null,
        coverage: null,
        blocking_issue_ids: ["dq-1"],
        warning_issue_ids: [],
        info_issue_ids: [],
      },
    ],
  },
  stdout_tail: null,
  duration_seconds: 119,
  stale: false,
  stale_note: null,
};

function findingRoutes(
  issues: unknown[] = [],
  runs: unknown[] = [],
): Record<string, RouteHandler> {
  return {
    "GET /dq/issues": {
      status: 200,
      body: {
        issues,
        total: issues.length,
        limit: 50,
        next_cursor: null,
        has_more: false,
      },
    },
    "GET /dq/issues/dq-1": {
      status: 200,
      body: { ...flaggedIssue, source_record_ids: ["sha256:abc123"] },
    },
    "GET /dq/issues/dq-2": {
      status: 200,
      body: { ...runWideIssue, source_record_ids: null },
    },
    "GET /calc/runs": { status: 200, body: runs },
  };
}

/** The mark layer as it actually reached the canvas. */
function markLayer(map: FakeMapShape): LayerLike {
  const add = map.layerAdds.find((a) => a.id === "vehicles-mark");
  if (!add) throw new Error("no vehicles-mark layer was added");
  return add.layer;
}

describe("/map — mode-aware vehicle marks (handoff 0043, design point 4)", () => {
  it("encodes mode as ONE data-driven expression per channel — shape, colour and size — and never hides a vehicle to avoid a label collision", async () => {
    signInAs("viewer");
    mockApi({
      "GET /geometry/stops": { status: 200, body: stopsBody },
      "GET /geometry/routes": { status: 200, body: routesTwoModes },
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesByMode },
    });
    renderApp("/map");
    await screen.findByRole("heading", { name: "Live map" });

    const layer = markLayer(fakeMaps[fakeMaps.length - 1]);
    expect(layer.type).toBe("symbol");
    // Shape, size and colour are each a MATCH over the `mode` property —
    // one GPU expression over the whole source, not a marker per vehicle.
    for (const expression of [
      layer.layout?.["text-field"],
      layer.layout?.["text-size"],
      layer.paint?.["text-color"],
    ]) {
      expect(Array.isArray(expression)).toBe(true);
      expect((expression as unknown[])[0]).toBe("match");
      expect((expression as unknown[])[1]).toEqual(["get", "mode"]);
    }
    // The colours are the SHIPPED palette for the ground in use.
    expect(layer.paint?.["text-color"]).toEqual(modeColorExpression("light"));
    expect(layer.paint?.["text-halo-color"]).toBe(MARK_HALO.light);
    // A vehicle is never dropped for a label collision: that would be a
    // silent gap, which is the one thing this product cannot do.
    expect(layer.layout?.["text-allow-overlap"]).toBe(true);
    expect(layer.layout?.["text-ignore-placement"]).toBe(true);
    // The glyphs come from the vendored font, so no sprite is ever named.
    expect(layer.layout?.["text-font"]).toEqual([BASEMAP_FONT]);
    expect(JSON.stringify(layer)).not.toContain("icon-image");
  });

  it("joins the mode from the agency's OWN schedule data and says 'not known' out loud where it cannot", async () => {
    signInAs("viewer");
    mockApi({
      "GET /geometry/stops": { status: 200, body: stopsBody },
      "GET /geometry/routes": { status: 200, body: routesTwoModes },
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesByMode },
    });
    renderApp("/map");
    await screen.findByRole("heading", { name: "Live map" });

    // What actually reached the canvas carries the joined mode.
    await waitFor(() => {
      const data = fakeMaps[fakeMaps.length - 1].sourceData.vehicles as {
        features: { properties: Record<string, unknown> }[];
      };
      expect(data.features.map((f) => f.properties.mode)).toEqual([
        "subway",
        "bus",
        "unknown",
      ]);
    });

    // And the readable equivalent names every mode in words — the map is
    // never the only place the encoding exists.
    await userEvent.click(
      await screen.findByRole("button", { name: "List the vehicles" }),
    );
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Subway or metro")).toBeInTheDocument();
    expect(within(table).getByText("Bus")).toBeInTheDocument();
    expect(within(table).getByText("Not known")).toBeInTheDocument();
    // The count of unplaceable vehicles is stated, not quietly greyed.
    expect(
      screen.getByText(copy.map.marks.unknownNoRoute("1")),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("marks follow the GROUND, not the app theme: dark chrome over a light street map still gets the light-ground palette, and switching the street style repaints them", async () => {
    signInAs("viewer");
    // Dark APP theme, light street map (the shipped default pairing).
    document.documentElement.setAttribute("data-theme", "dark");
    window.localStorage.setItem("headway-theme", "dark");
    mockApi({
      "GET /geometry/stops": { status: 200, body: stopsBody },
      "GET /geometry/routes": { status: 200, body: routesTwoModes },
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesByMode },
      "HEAD /basemap/region.pmtiles": { status: 200, rawBody: "" },
      "GET /basemap/region.pmtiles": { status: 206, rawBody: "PMTiles" },
    });
    renderApp("/map");
    await screen.findByText(copy.map.basemap.attribution);

    const map = fakeMaps[fakeMaps.length - 1];
    const colorOf = () =>
      [...map.paintSets]
        .reverse()
        .find((p) => p.id === "vehicles-mark" && p.prop === "text-color")?.value;
    await waitFor(() => expect(colorOf()).toEqual(modeColorExpression("light")));

    await userEvent.click(screen.getByRole("button", { name: "Dark" }));
    await waitFor(() => expect(colorOf()).toEqual(modeColorExpression("dark")));
    // The halo inverts with it: light marks on dark need a DARK outline.
    expect(
      [...map.paintSets]
        .reverse()
        .find((p) => p.id === "vehicles-mark" && p.prop === "text-halo-color")
        ?.value,
    ).toBe(MARK_HALO.dark);
  });
});

describe("/map — the mode filter (handoff 0043, design point 6)", () => {
  it("highlights by REPAINTING what is already on the map: no second request, and nothing removed", async () => {
    signInAs("viewer");
    const calls = mockApi({
      "GET /geometry/stops": { status: 200, body: stopsBody },
      "GET /geometry/routes": { status: 200, body: routesTwoModes },
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesByMode },
    });
    renderApp("/map");
    const group = await screen.findByRole("group", {
      name: copy.map.modeFilter.label,
    });
    // Options are data-driven: the modes this agency's routes actually
    // carry, plus 'unknown' because one vehicle has no mode.
    expect(
      within(group)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["All modes", "Bus", "Subway or metro", "Mode not known"]);

    const before = calls.length;
    await userEvent.click(within(group).getByRole("button", { name: "Bus" }));

    const map = fakeMaps[fakeMaps.length - 1];
    await waitFor(() => {
      const opacity = [...map.paintSets]
        .reverse()
        .find((p) => p.id === "routes-line" && p.prop === "line-opacity");
      expect(opacity?.value).toEqual(routeOpacityExpression("bus"));
    });
    expect(
      [...map.paintSets]
        .reverse()
        .find((p) => p.id === "routes-line" && p.prop === "line-width")?.value,
    ).toEqual(routeWidthExpression("bus"));
    // Not one extra request: highlighting is paint, not a query.
    expect(calls.length).toBe(before);
    // And the vehicle counts are untouched — highlighting hides nothing.
    expect(
      screen.getByText(
        "3 vehicles with a position in the selected window.",
      ),
    ).toBeInTheDocument();
  });
});

describe("/map — flagged findings and the relationship inspector (handoff 0043, design points 6 and 7)", () => {
  function flaggedApi(issues: unknown[] = [flaggedIssue, runWideIssue]) {
    return mockApi({
      "GET /geometry/stops": { status: 200, body: stopsBody },
      "GET /geometry/routes": { status: 200, body: routesTwoModes },
      "GET /ops/vehicles/latest": { status: 200, body: vehiclesByMode },
      ...findingRoutes(issues, [calcRunNamingIssue]),
    });
  }

  it("asks only for the findings that genuinely need a person, and draws them as a FRAME with a shape and a label — never a fill behind a figure", async () => {
    signInAs("viewer");
    const calls = flaggedApi();
    renderApp("/map");
    await screen.findByRole("heading", { name: "Needs investigation" });

    // Scarce by construction: open AND blocking only.
    const ask = calls.find((c) => c.path === "/dq/issues");
    expect(ask?.url).toContain("status=open");
    expect(ask?.url).toContain("severity=blocking");

    const map = fakeMaps[fakeMaps.length - 1];
    const pulse = map.layerAdds.find((a) => a.id === "findings-pulse")!.layer;
    // A ring, never a fill: the glow can never sit behind a figure.
    expect(pulse.type).toBe("circle");
    expect(pulse.paint?.["circle-color"]).toBe("rgba(0,0,0,0)");
    expect(pulse.paint?.["circle-stroke-color"]).toBe(
      TOKEN_MARK_COLORS.alert.light,
    );
    // Shape AND label, so the signal survives without the pulse.
    const mark = map.layerAdds.find((a) => a.id === "findings-mark")!.layer;
    expect(mark.layout?.["text-field"]).toBe(FINDING_GLYPH);
    const label = map.layerAdds.find((a) => a.id === "findings-label")!.layer;
    expect(label.layout?.["text-field"]).toEqual(["get", "label"]);

    await waitFor(() => {
      const data = map.sourceData.findings as {
        features: { properties: Record<string, unknown> }[];
      };
      expect(data.features.length).toBe(1);
      expect(data.features[0].properties.issue_id).toBe("dq-1");
      expect(data.features[0].properties.label).toBe("39");
    });
  });

  it("is reachable from the KEYBOARD through the 'needs investigation' list — the canvas cannot be, so the list is the entry point", async () => {
    signInAs("viewer");
    flaggedApi();
    renderApp("/map");

    const list = await screen.findByRole("region", {
      name: "Needs investigation",
    });
    const row = within(list).getByRole("button", {
      name: /Recorded miles stop part-way through block 225-4/,
    });
    // Tab to it and open it with the keyboard alone.
    row.focus();
    expect(row).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    const panel = await screen.findByRole("dialog");
    expect(panel).toHaveTextContent(
      "Recorded miles stop part-way through block 225-4",
    );
    expect(row).toHaveAttribute("aria-pressed", "true");
    await expectNoAxeViolations();
  });

  it("renders the chain the API can honestly draw — finding → block → route → calculation → owner — plus the raw records behind it", async () => {
    signInAs("viewer");
    flaggedApi();
    renderApp("/map");
    await userEvent.click(
      await screen.findByRole("button", {
        name: /Recorded miles stop part-way through block 225-4/,
      }),
    );

    const panel = await screen.findByRole("dialog");
    // block — the agency's own operational name, with the feed id behind it
    expect(panel).toHaveTextContent("Block 225-4 — 4 trips");
    // route — plus the mode joined from the schedule data
    expect(panel).toHaveTextContent("39 — Bus");
    // calculation — the run that named THIS finding, and what it did
    expect(panel).toHaveTextContent("vrm_v0 0.3.0 — vrm");
    expect(panel).toHaveTextContent(copy.map.inspector.calcOutcomeRefused);
    // owner — an open finding with nobody on it says so
    expect(panel).toHaveTextContent(copy.map.inspector.ownerNone);
    // provenance — the source records the finding cited
    expect(await within(panel).findByText("sha256:abc123")).toBeInTheDocument();
  });

  it("lights the finding's routes IN PLACE with feature-state, instead of re-sending the source", async () => {
    signInAs("viewer");
    flaggedApi();
    renderApp("/map");
    await userEvent.click(
      await screen.findByRole("button", {
        name: /Recorded miles stop part-way through block 225-4/,
      }),
    );
    const map = fakeMaps[fakeMaps.length - 1];
    await waitFor(() => {
      expect(map.featureStates).toContainEqual({
        source: "routes",
        id: "39",
        state: { related: true },
      });
    });
    expect(map.featureStates).toContainEqual({
      source: "findings",
      id: "dq-1",
      state: { selected: true },
    });
    // The route source keeps a promoted id so feature-state can address it.
    expect(map.sources.routes).toMatchObject({ promoteId: "route_id" });
    expect(map.sources.findings).toMatchObject({ promoteId: "finding_key" });
  });

  it("never lets the map's drawing limits shrink the worklist: an un-anchorable finding is listed WITH the reason it has no flag", async () => {
    signInAs("viewer");
    flaggedApi();
    renderApp("/map");

    const list = await screen.findByRole("region", {
      name: "Needs investigation",
    });
    // Two findings need a person; only one of them can be drawn.
    expect(list).toHaveTextContent(
      copy.map.findings.countLine("2", "1"),
    );
    expect(list).toHaveTextContent(
      "The feed reported no positions at all for two hours",
    );
    expect(list).toHaveTextContent(copy.map.findings.gapNoSubject);
    // And the map says, in the legend, what a flag's POSITION does not mean.
    expect(
      screen.getByText(copy.map.findings.legendNote),
    ).toBeInTheDocument();
  });

  it("says so plainly when nothing needs a person — an empty worklist is an answer, not a blank", async () => {
    signInAs("viewer");
    flaggedApi([]);
    renderApp("/map");
    expect(
      await screen.findByText(copy.map.findings.listEmpty),
    ).toBeInTheDocument();
    const map = fakeMaps[fakeMaps.length - 1];
    await waitFor(() => {
      const data = map.sourceData.findings as { features: unknown[] };
      expect(data.features).toEqual([]);
    });
  });

  it("collapses the pulse to a STATIC ring under prefers-reduced-motion, and animates the frame otherwise", async () => {
    signInAs("viewer");
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    flaggedApi();
    renderApp("/map");
    await screen.findByRole("heading", { name: "Needs investigation" });

    const map = fakeMaps[fakeMaps.length - 1];
    await waitFor(() => {
      expect(
        map.paintSets.some(
          (p) => p.id === "findings-pulse" && p.prop === "circle-radius",
        ),
      ).toBe(true);
    });
    // Reduced motion = INSTANT, never "slower": every ring the layer is
    // ever given is the resting one, at full strength.
    for (const set of map.paintSets.filter((p) => p.id === "findings-pulse")) {
      if (set.prop === "circle-radius") {
        expect(set.value).toBe(PULSE_STATIC.radius);
      }
      if (set.prop === "circle-stroke-opacity") {
        expect(set.value).toBe(PULSE_STATIC.strokeOpacity);
      }
    }
  });

  it("keeps the loop off the fleet: the pulse only ever repaints the findings layer", async () => {
    signInAs("viewer");
    flaggedApi();
    renderApp("/map");
    await screen.findByRole("heading", { name: "Needs investigation" });
    const map = fakeMaps[fakeMaps.length - 1];
    // The animated frame really does move …
    await waitFor(() => {
      expect(
        map.paintSets.some(
          (p) =>
            p.id === "findings-pulse" &&
            p.prop === "circle-radius" &&
            p.value !== PULSE_STATIC.radius,
        ),
      ).toBe(true);
    });
    // … and it never touches a vehicle layer while doing it.
    const radiusSets = map.paintSets.filter((p) => p.prop === "circle-radius");
    expect(
      radiusSets.every((p) => p.id === "findings-pulse"),
    ).toBe(true);
  });
});
