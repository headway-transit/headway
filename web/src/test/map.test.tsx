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
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { RouteHandler } from "./helpers";
import { copy } from "../copy";

// ---- the maplibre-gl double (hoisted before the view imports it) ----
vi.mock("maplibre-gl", () => {
  class FakeMap {
    handlers: Record<string, (...args: unknown[]) => void> = {};
    canvas = document.createElement("canvas");
    /** Sources added at runtime, by id (the basemap wave asserts the
     *  pmtiles source is only ever added in the present state). */
    sources: Record<string, unknown> = {};
    /** addLayer calls in order: {id, before} — pins that every basemap
     *  street layer is inserted BELOW the schematic route lines. */
    layerAdds: { id: string; before?: string }[] = [];
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
    addLayer(layer: { id: string }, before?: string) {
      this.layerAdds.push({ id: layer.id, before });
    }
    removeLayer() {}
    getLayer() {
      return { id: "x" };
    }
    getSource(id: string) {
      if (id === "basemap" && !(id in this.sources)) return undefined;
      return { setData: vi.fn() };
    }
    setPaintProperty() {}
    setFilter() {}
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
interface FakeMapShape {
  sources: Record<string, unknown>;
  layerAdds: { id: string; before?: string }[];
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
