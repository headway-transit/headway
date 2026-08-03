/**
 * Developer tool (see index.html): renders the handoff-0043 map overlay —
 * mode-aware vehicle marks, a flagged finding, and the relationship
 * inspector — over this installation's real PMTiles archive, on either
 * authored basemap style.
 *
 * It imports the SHIPPED modules and the SHIPPED component rather than
 * restating a colour, a glyph, a layer or a panel, so a screenshot taken
 * here cannot flatter something /map does not actually draw. The only thing
 * invented in this file is the FIXTURE DATA, and it is labelled as such on
 * screen: no API and no login exist in this environment.
 *
 * Not in the production artifact: `vite build` has a single HTML input.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { Map as MapLibreMap, addProtocol, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { PMTiles, Protocol as PmtilesProtocol } from "pmtiles";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
// The app's own stylesheet and the map overlay's own: the panel below is
// the real component, so it has to be the real chrome too.
import "../../src/styles.css";
import "../../src/map/overlay.css";
import {
  BASEMAP_STYLES,
  basemapLayerSpecs,
  type BasemapStyleId,
} from "../../src/map/basemapStyle.ts";
import { overlayLayerSpecs } from "../../src/map/overlayLayers.ts";
import {
  markContrastResults,
  type MarkGround,
} from "../../src/map/marks.ts";
import { routeModeIndex, vehiclesToGeojson } from "../../src/map/vehicles.ts";
import { findingChain, placeFindings } from "../../src/map/findings.ts";
import { RelationshipInspector } from "../../src/map/RelationshipInspector.tsx";
import type {
  DqIssueSummary,
  OpsVehicle,
  RoutesCollection,
} from "../../src/api/types.ts";

setWorkerUrl(maplibreWorkerUrl);
addProtocol("pmtiles", new PmtilesProtocol().tile);

const BASEMAP_PATH = "/basemap/region.pmtiles";
const params = new URLSearchParams(window.location.search);
const styleId: BasemapStyleId =
  params.get("style") === "dark" ? "dark" : "light";
const ground: MarkGround = styleId;
const style = BASEMAP_STYLES[styleId];
const showPanel = params.get("panel") !== "0";

// The app chrome follows the street style here so the panel is legible in
// the same frame as the marks it describes. On /map the two are chosen
// separately; this is a screenshot harness, not a claim about that.
document.documentElement.setAttribute("data-theme", styleId);

const caption = document.getElementById("caption") as HTMLParagraphElement;
if (styleId === "dark") caption.classList.add("on-dark");

const marks = markContrastResults().filter((r) => r.ground === ground);
const worstMark = Math.min(...marks.map((r) => r.worst));
caption.textContent =
  `${style.name} + mode marks — worst measured mark contrast ${worstMark.toFixed(2)}:1 ` +
  `against its grounds and its own halo (bar 3:1, WCAG 2.1 SC 1.4.11). ` +
  `Vehicles, routes and the finding are FIXTURE data (no API in this ` +
  `environment); every colour, glyph, layer and the panel itself are the ` +
  `shipped modules. © OpenStreetMap contributors · Protomaps`;

// ---- fixture data ---------------------------------------------------------

/** A short polyline walking away from a center, in degrees. */
function leg(
  center: [number, number],
  bearingDeg: number,
  km: number,
  points = 6,
): [number, number][] {
  const rad = (bearingDeg * Math.PI) / 180;
  const dLat = (km / 111) * Math.cos(rad);
  const dLng =
    (km / (111 * Math.cos((center[1] * Math.PI) / 180))) * Math.sin(rad);
  return Array.from({ length: points }, (_, i) => {
    const t = i / (points - 1);
    return [center[0] + dLng * t, center[1] + dLat * t] as [number, number];
  });
}

function fixtureRoutes(center: [number, number]): RoutesCollection {
  const spec: [string, string, string, number, number][] = [
    ["Red", "Red", "subway", 20, 1.5],
    ["39", "39", "bus", 110, 1.4],
    ["Mattapan", "M", "tram", 200, 1.2],
    ["F1", "F1", "ferry", 285, 1.1],
    ["77", "77", "bus", 335, 1.3],
  ];
  return {
    type: "FeatureCollection",
    features: spec.map(([routeId, shortName, mode, bearing, km]) => ({
      type: "Feature",
      geometry: { type: "LineString", coordinates: leg(center, bearing, km) },
      properties: {
        route_id: routeId,
        short_name: shortName,
        long_name: `${shortName} line`,
        mode,
        geometry_kind: "schematic_stop_sequence",
      },
    })),
    category: "ops",
    ops_note: "",
    geometry_kind: "schematic_stop_sequence",
    geometry_note: "",
    route_count: spec.length,
    routes_without_geometry: 0,
    cap: 2000,
    truncated: false,
    total_routes_with_trips: spec.length,
    computed_at: new Date().toISOString(),
    cache_ttl_seconds: 900,
    cache_note: "",
    note: null,
  } as unknown as RoutesCollection;
}

function fixtureVehicles(routes: RoutesCollection): OpsVehicle[] {
  const out: OpsVehicle[] = [];
  let n = 0;
  for (const feature of routes.features) {
    const coords = feature.geometry.coordinates as unknown as [
      number,
      number,
    ][];
    for (const at of [1, 3, 4]) {
      const [lng, lat] = coords[at];
      out.push({
        vehicle_id: `V${++n}`,
        latitude: lat,
        longitude: lng,
        recorded_at: new Date().toISOString(),
        age_seconds: 12,
        route_id: String(feature.properties.route_id),
        source_record_id: `raw-${n}`,
        source: "gtfs_rt",
        simulated: false,
      });
    }
  }
  // Two the schedule data cannot place: one with no route reported, one
  // naming a route this installation holds nothing for. Both draw as the
  // hollow ring — the point of having a shape for "we were not told".
  const [lng, lat] = routes.features[0].geometry
    .coordinates[2] as unknown as [number, number];
  out.push({
    vehicle_id: `V${++n}`,
    latitude: lat + 0.004,
    longitude: lng + 0.004,
    recorded_at: new Date().toISOString(),
    age_seconds: 41,
    route_id: null,
    source_record_id: `raw-${n}`,
    source: "gtfs_rt",
    simulated: false,
  });
  out.push({
    vehicle_id: `V${++n}`,
    latitude: lat - 0.004,
    longitude: lng - 0.004,
    recorded_at: new Date().toISOString(),
    age_seconds: 33,
    route_id: "route-we-hold-nothing-for",
    source_record_id: `raw-${n}`,
    source: "gtfs_rt",
    simulated: false,
  });
  return out;
}

const fixtureFindings: DqIssueSummary[] = [
  {
    issue_id: "dq-4471",
    issue_type: "position_gap_in_block",
    severity: "blocking",
    status: "open",
    owner: null,
    title: "Recorded miles stop part-way through block 225-4",
    description:
      "Four trips on block 225-4 have no recorded position after 14:10, so the miles for that block cannot be certified for June.",
    created_at: "2026-07-22T15:04:11Z",
    resolved_at: null,
    resolution: null,
    subject_context: {
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
          routes: [{ route_id: "39", short_name: "39", long_name: "39 line" }],
          route_count: 1,
          first_departure: "2026-06-14T09:12:00Z",
          last_departure: "2026-06-14T18:41:00Z",
          trip_ids: ["t-91204", "t-91205", "t-91206", "t-91207"],
        },
      ],
    },
  } as unknown as DqIssueSummary,
  {
    issue_id: "dq-4482",
    issue_type: "odometer_avl_conflict",
    severity: "blocking",
    status: "open",
    owner: null,
    title: "GPS miles and odometer miles disagree on block 118-2",
    description:
      "For block 118-2 on 14 June the GPS trace records 41 fewer miles than the odometer. One of the two is wrong and the figure cannot be certified until someone picks.",
    created_at: "2026-07-22T15:07:52Z",
    resolved_at: null,
    resolution: null,
    subject_context: {
      version: 1,
      kind: "trips",
      total: 6,
      grouped_by: "block",
      group_count: 1,
      group_cap: 20,
      trip_id_cap: 20,
      groups: [
        {
          block_id: "118",
          block_label: "118-2",
          trip_count: 6,
          routes: [
            { route_id: "Mattapan", short_name: "M", long_name: "M line" },
          ],
          route_count: 1,
          first_departure: "2026-06-14T05:40:00Z",
          last_departure: "2026-06-14T22:05:00Z",
          trip_ids: ["t-77100", "t-77101"],
        },
      ],
    },
  } as unknown as DqIssueSummary,
];

const fixtureCalcRuns = [
  {
    run_id: "run-2026-06",
    requested_by: "j.okafor",
    requested_at: "2026-07-22T14:55:00Z",
    period_start: "2026-06-01",
    period_end: "2026-07-01",
    status: "succeeded",
    started_at: "2026-07-22T14:55:02Z",
    finished_at: "2026-07-22T14:57:31Z",
    runner_pid: null,
    summary: {
      metrics: [
        {
          calc_name: "vrm_v0",
          calc_version: "0.3.0",
          metric: "vrm",
          unit: "miles",
          scope: "mode:bus",
          outcome: "refused",
          value: null,
          metric_value_id: null,
          coverage: null,
          blocking_issue_ids: ["dq-4471"],
          warning_issue_ids: [],
          info_issue_ids: [],
        },
      ],
    },
    stdout_tail: null,
    duration_seconds: 149,
    stale: false,
    stale_note: null,
  },
];

// ---- render ---------------------------------------------------------------

async function main(): Promise<void> {
  const header = await new PMTiles(
    `${window.location.origin}${BASEMAP_PATH}`,
  ).getHeader();
  const lng = Number(params.get("lng") ?? header.centerLon);
  const lat = Number(params.get("lat") ?? header.centerLat);
  const zoom = Number(params.get("zoom") ?? 14);
  const center: [number, number] = [lng, lat];

  const routes = fixtureRoutes(center);
  const modes = routeModeIndex(routes);
  const vehicles = vehiclesToGeojson(fixtureVehicles(routes), modes);
  const placement = placeFindings(fixtureFindings, routes);

  // The app's own route/stop tokens, read from the stylesheet exactly as
  // MapView reads them.
  const computed = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) =>
    computed.getPropertyValue(name).trim() || fallback;

  const map = new MapLibreMap({
    container: "map",
    style: {
      version: 8,
      glyphs: `${window.location.origin}/basemap-fonts/{fontstack}/{range}.pbf`,
      sources: {
        basemap: {
          type: "vector",
          url: `pmtiles://${window.location.origin}${BASEMAP_PATH}`,
          attribution: "© OpenStreetMap contributors · Protomaps",
        },
        routes: {
          type: "geojson",
          data: routes as unknown as GeoJSON.GeoJSON,
          promoteId: "route_id",
        },
        stops: {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
        },
        vehicles: { type: "geojson", data: vehicles.data },
        findings: {
          type: "geojson",
          data: placement.data,
          promoteId: "finding_key",
        },
      },
      layers: [
        {
          id: "background",
          type: "background",
          paint: { "background-color": String(style.theme.background) },
        },
        ...basemapLayerSpecs(styleId),
        ...overlayLayerSpecs({
          ground,
          routeColor: token("--map-route", "#5c7086"),
          stopColor: token("--map-stop", "#57606a"),
        }),
      ],
    },
    center,
    zoom,
    attributionControl: false,
    canvasContextAttributes: { preserveDrawingBuffer: true },
  });

  // The inspector's own effect on the map: the finding's routes light up.
  const chain = findingChain(
    fixtureFindings[0],
    routes,
    modes,
    fixtureCalcRuns as never,
  );
  map.on("load", () => {
    for (const route of chain.routes) {
      if (route.drawn) {
        map.setFeatureState(
          { source: "routes", id: route.route_id },
          { related: true },
        );
      }
    }
    map.setFeatureState(
      { source: "findings", id: fixtureFindings[0].issue_id },
      { selected: true },
    );
  });

  if (showPanel) {
    createRoot(document.getElementById("overlay")!).render(
      <StrictMode>
        <MemoryRouter>
          <RelationshipInspector
            chain={chain}
            sourceRecordIds={[
              "sha256:9f2a41c0b8e7d5…",
              "sha256:41cc02de7708aa…",
            ]}
            sourceRecordsLoading={false}
            fromMap
            onClose={() => {}}
          />
        </MemoryRouter>
      </StrictMode>,
    );
  }

  map.on("idle", () => {
    document.body.dataset.mapIdle = "true";
  });
}

void main();
