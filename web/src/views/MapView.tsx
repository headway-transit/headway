/**
 * /map — the living system view (handoff 0024, design point 1).
 *
 * MapLibre GL JS (BSD-3-Clause, verified against the ADR-0001 license gate)
 * rendering ONLY self-hosted data:
 *   - stops + schematic route lines from GET /geometry/stops|routes;
 *   - live vehicles from GET /ops/vehicles/latest, polled every 20 s (the
 *     endpoint's own guidance: the upstream feed updates ~every 30 s).
 *
 * NO EXTERNAL REQUESTS OF ANY KIND — including with the basemap (handoff
 * 0027). The style is inline; its only `glyphs` URL points at THIS
 * installation's own vendored font files (/basemap-fonts/, same origin),
 * and there is no `sprite`. When no basemap has been downloaded the map is
 * the styled water-tone canvas exactly as before, with zero symbol layers
 * and nothing to fetch. When an administrator has run the consented
 * `install.sh --download-basemap`, streets appear from the SELF-HOSTED
 * /basemap/region.pmtiles archive (PMTiles read by same-origin byte-range
 * requests) under the schematic/stops/vehicle layers — attribution
 * "© OpenStreetMap contributors · Protomaps" visible on the canvas
 * whenever tiles render (ODbL). Either way the network log stays
 * same-origin only, pinned by test in BOTH states.
 *
 * Those streets are drawn in one of HEADWAY'S OWN two basemap styles
 * (handoff 0043 — src/map/basemapStyle.ts), light or dark, chosen by the
 * user independently of the app theme and defaulting to light. Both are
 * authored against a measured WCAG bar rather than taken as a vendor
 * flavor, because a partner agency's ITS manager reported that a dark
 * theme buried the street network — and the measurement agreed with them.
 *
 * Honesty surfaces, all VERBATIM from the server envelopes:
 *   - the legend states that route lines are schematic (geometry_note,
 *     mirroring geometry_kind — we have never ingested shapes.txt);
 *   - the staleness chip: "Live — …" only while the newest position is
 *     inside the live window; otherwise it says plainly how long the feed
 *     has been quiet (duration = date math on the server's own as_of and
 *     newest_position_at — never a guess), with the server's note beside;
 *   - the ops boundary: OpsBadge on the surface + ops_note verbatim;
 *   - caps/truncation notes render verbatim whenever the server sends one.
 *
 * Motion rules (handoff 0021): vehicle dots JUMP to each newly reported
 * position — for everyone. The feed reports ~every 30 s; gliding a dot
 * between two reports would draw positions no vehicle ever reported
 * (interpolation), so nothing here tweens a position. The one camera
 * animation (centering on a vehicle picked from the list) is disabled
 * under prefers-reduced-motion (jump, not glide).
 *
 * Accessibility: the canvas is labeled and MapLibre's built-in keyboard
 * handler pans/zooms it, but the canvas is PRESENTATION — the readable
 * equivalents live beside it: the chip, the counts, the vehicle detail
 * panel, and the vehicle list table (capped, cap stated).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Map as MapLibreMap, addProtocol, setWorkerUrl } from "maplibre-gl";
import type { GeoJSONSource, MapLayerMouseEvent } from "maplibre-gl";
import type { GeoJSON } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
// PMTiles protocol (BSD-3-Clause, license-gate verified): teaches MapLibre
// to read the single self-hosted /basemap/region.pmtiles archive via
// same-origin byte-range requests. No tile server, no external host.
import { Protocol as PmtilesProtocol } from "pmtiles";
// Headway's OWN two basemap styles (handoff 0043): light and dark, both
// AUTHORED against a measured contrast bar instead of taken as a vendor
// flavor — see src/map/basemapStyle.ts for the reason and the numbers.
import {
  BASEMAP_STYLES,
  basemapLayerSpecs,
  type BasemapStyleId,
} from "../map/basemapStyle.ts";
// MapLibre's own worker-URL guess is a SIBLING maplibre-gl-worker.mjs of
// its bundle — a file a bundled app does not serve, so sources would never
// parse (found live: a silent stall, no dots). `?worker&url` makes vite
// bundle the worker WITH its dependencies as a first-party asset — served
// from this installation like everything else (no external request), in
// dev and in the built artifact alike.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

setWorkerUrl(maplibreWorkerUrl);
// Registered once per module load; the protocol only ever fetches the URL
// the "basemap" source names — this installation's own /basemap path.
addProtocol("pmtiles", new PmtilesProtocol().tile);
import {
  ApiError,
  getLatestVehicles,
  getRoutesGeojson,
  getStopsGeojson,
} from "../api/client";
import type {
  OpsVehicle,
  OpsVehiclesLatest,
  RoutesCollection,
  StopsCollection,
} from "../api/types";
import { OpsBadge } from "../components/OpsBadge";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { Skeleton } from "../components/Skeleton";
import { copy } from "../copy";
import { useSession } from "../auth/session";
import { useTheme } from "../theme";

/** One async slice: skeleton → verbatim error | data (house pattern). */
type Load<T> =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; data: T };

const LOADING = { state: "loading" } as const;

function toError(err: unknown): { state: "error"; message: string } {
  return {
    state: "error",
    message: err instanceof ApiError ? err.message : String(err),
  };
}

/** Poll cadence (ms): inside the endpoint's recommended 15–30 s band. */
const POLL_INTERVAL_MS = 20_000;

/** The feed counts as LIVE while the newest position is inside this many
 *  seconds — the endpoint's own default staleness window. */
const LIVE_WINDOW_SECONDS = 300;

/** The window options the selector offers (max_age_seconds sent). */
const WINDOW_OPTIONS: { seconds: number; label: string }[] = [
  { seconds: 300, label: copy.map.window.live },
  { seconds: 3600, label: copy.map.window.hour },
  { seconds: 86400, label: copy.map.window.day },
];

/** Vehicle rows drawn in the list view at once — the cap is STATED. */
const LIST_CAP = 100;

// ---- the self-hosted basemap (handoff 0027) --------------------------------

/** The one deployed basemap file: nginx serves it from the read-only
 *  compose mount; the vite dev middleware serves the same path in dev. */
const BASEMAP_PATH = "/basemap/region.pmtiles";

/**
 * The street-style choice is DELIBERATELY INDEPENDENT of the app theme
 * (first-agency UAT, 2026-07-29: in dark mode the dark streets were hard
 * to read while the rest of the chrome was right). Map legibility is a
 * task decision, not a branding one — someone watching vehicle dots wants
 * the streets that make the dots easiest to find, whatever chrome they
 * prefer. Light streets are therefore the default in BOTH themes, and the
 * choice is the user's, persisted per browser.
 *
 * Handoff 0043 keeps that decoupling and adds the missing half: the dark
 * option is no longer a vendor flavor that measured 1.5:1 for a street
 * against its ground — BOTH styles are now authored by Headway and gated
 * at WCAG 3:1 (streets, water) and 4.5:1 (names). The toggle changes ONLY
 * the tiles: app panels, the audience lens and the app theme are all
 * chosen separately and are untouched by it.
 */
export type BasemapStyle = BasemapStyleId;
const BASEMAP_STYLE_KEY = "headway-basemap-style";

function storedBasemapStyle(): BasemapStyle {
  try {
    const value = window.localStorage.getItem(BASEMAP_STYLE_KEY);
    return value === "dark" ? "dark" : "light";
  } catch {
    return "light"; // storage blocked: the legible default still applies
  }
}

function persistBasemapStyle(style: BasemapStyle): void {
  try {
    window.localStorage.setItem(BASEMAP_STYLE_KEY, style);
  } catch {
    // storage blocked: the choice still applies for this visit
  }
}

/**
 * Detected at runtime, never assumed:
 *   absent   → today's canvas exactly as-is (plus one quiet teaching line
 *              for certifying officials);
 *   present  → streets appear, attribution appears with them;
 *   unusable → a file answered but not as a range-readable PMTiles archive
 *              — said plainly (fail loudly), canvas falls back.
 */
type BasemapState = "checking" | "absent" | "present" | "unusable";

/**
 * HEAD first (does anything exist?), then a ranged GET of the archive's
 * first 7 bytes — which verifies BOTH that byte ranges work through the
 * serving stack (PMTiles requires them) and that the bytes are a PMTiles
 * archive (magic "PMTiles"). Same-origin throughout.
 */
async function detectBasemap(): Promise<Exclude<BasemapState, "checking">> {
  try {
    const head = await fetch(BASEMAP_PATH, { method: "HEAD" });
    if (!head.ok) return "absent";
    const ranged = await fetch(BASEMAP_PATH, {
      headers: { Range: "bytes=0-6" },
    });
    if (ranged.status !== 206) return "unusable";
    const magic = new TextDecoder().decode(await ranged.arrayBuffer());
    return magic.startsWith("PMTiles") ? "present" : "unusable";
  } catch {
    // No answer at all: treated as no basemap — the map never blocks on it.
    return "absent";
  }
}

/** Map paint tokens for HEADWAY'S OWN MARKS — the canvas, route lines,
 *  stops and vehicle dots. These DO follow the app theme: they are our
 *  tokens and every pair is contrast-gated. Only the OpenStreetMap street
 *  background is decoupled (see BasemapStyle).
 *
 *  Resolved from the stylesheet per theme (the canvas
 *  cannot read CSS custom properties itself). */
function mapColors(): {
  bg: string;
  route: string;
  stop: string;
  vehicle: string;
  vehicleRing: string;
} {
  const styles = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string) =>
    styles.getPropertyValue(name).trim() || fallback;
  return {
    bg: read("--map-bg", "#dce8f0"),
    route: read("--map-route", "#5c7086"),
    stop: read("--map-stop", "#57606a"),
    vehicle: read("--map-vehicle", "#1a56a8"),
    vehicleRing: read("--color-bg", "#ffffff"),
  };
}

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Vehicles → GeoJSON for the map source. Positions verbatim. */
function vehiclesToGeojson(vehicles: OpsVehicle[]): GeoJSON {
  return {
    type: "FeatureCollection",
    features: vehicles.map((v) => ({
      type: "Feature" as const,
      geometry: {
        type: "Point" as const,
        coordinates: [v.longitude, v.latitude],
      },
      properties: { vehicle_id: v.vehicle_id },
    })),
  };
}

/** "HH:MM:SS UTC" of an ISO timestamp — a time label, never a figure. */
function timeLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(11, 19)} UTC`;
}

/**
 * How long the feed has been quiet: SERVER as_of minus SERVER
 * newest_position_at (two server clocks — no client guess), in plain words.
 */
function quietDuration(res: OpsVehiclesLatest): string | null {
  if (!res.newest_position_at) return null;
  const asOf = Date.parse(res.as_of);
  const newest = Date.parse(res.newest_position_at);
  if (Number.isNaN(asOf) || Number.isNaN(newest) || newest > asOf) return null;
  const minutes = Math.floor((asOf - newest) / 60_000);
  if (minutes < 120) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export function MapView() {
  const theme = useTheme();
  const session = useSession();
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [basemap, setBasemap] = useState<BasemapState>("checking");
  /** Street style — the user's own choice, NOT the app theme (see
   *  BasemapStyle). Light by default in both themes. */
  const [basemapStyle, setBasemapStyle] =
    useState<BasemapStyle>(storedBasemapStyle);
  /** The basemap layer ids currently on the map (style swaps remove and
   *  re-add them; the overlay layers are never touched). */
  const basemapLayerIds = useRef<string[]>([]);

  const [stops, setStops] = useState<Load<StopsCollection>>(LOADING);
  const [routes, setRoutes] = useState<Load<RoutesCollection>>(LOADING);
  const [vehicles, setVehicles] = useState<Load<OpsVehiclesLatest>>(LOADING);
  // When the API was last ASKED — round-trip proof, distinct from data
  // freshness (UAT 2026-07-28: with an unchanged quiet feed, a refresh with
  // no visible effect reads as a broken button).
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);
  const [polling, setPolling] = useState(false);
  const [windowSeconds, setWindowSeconds] = useState(300);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(false);
  /** Monotonic fetch counter so a slow stale poll never overwrites a
   *  newer response (house stale-response guard). */
  const fetchSeq = useRef(0);

  // ---- the map itself ----
  useEffect(() => {
    if (!containerRef.current) return;
    const colors = mapColors();
    const map = new MapLibreMap({
      container: containerRef.current,
      // Inline style: no tile sources, no sprite. The one glyphs URL is
      // THIS installation's own vendored font path (same origin) — and
      // with no symbol layers in the style, nothing is fetched at all
      // until (and unless) the self-hosted basemap is detected. Zero
      // external requests, by design, in both states.
      style: {
        version: 8,
        glyphs: `${window.location.origin}/basemap-fonts/{fontstack}/{range}.pbf`,
        sources: {},
        layers: [
          {
            id: "background",
            type: "background",
            paint: { "background-color": colors.bg },
          },
        ],
      },
      center: [0, 0],
      zoom: 1,
      attributionControl: false,
      // Keep the drawn frame readable after present: screenshots (agency
      // evidence, this project's own click-through proofs) capture the map
      // instead of a blank canvas. Cost: one retained framebuffer.
      canvasContextAttributes: { preserveDrawingBuffer: true },
    });
    mapRef.current = map;
    if (import.meta.env.DEV) {
      // Dev-only verification handle (click-through scripts assert layer
      // and source state); never present in the production bundle.
      (window as unknown as Record<string, unknown>).__headwayMap = map;
    }
    map.on("load", () => {
      const c = mapColors();
      map.addSource("routes", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addSource("stops", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addSource("vehicles", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "routes-line",
        type: "line",
        source: "routes",
        paint: { "line-color": c.route, "line-width": 1.5 },
      });
      map.addLayer({
        id: "stops-dot",
        type: "circle",
        source: "stops",
        paint: {
          "circle-radius": 2,
          "circle-color": c.stop,
          "circle-opacity": 0.75,
        },
      });
      map.addLayer({
        id: "vehicles-dot",
        type: "circle",
        source: "vehicles",
        paint: {
          "circle-radius": 5,
          "circle-color": c.vehicle,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": c.vehicleRing,
        },
      });
      map.addLayer({
        id: "vehicles-selected",
        type: "circle",
        source: "vehicles",
        filter: ["==", ["get", "vehicle_id"], ""],
        paint: {
          "circle-radius": 9,
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-width": 2.5,
          "circle-stroke-color": c.vehicle,
        },
      });
      map.on("click", "vehicles-dot", (e: MapLayerMouseEvent) => {
        const f = e.features?.[0];
        const id = f?.properties?.vehicle_id;
        if (typeof id === "string") setSelectedId(id);
      });
      map.on("mouseenter", "vehicles-dot", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "vehicles-dot", () => {
        map.getCanvas().style.cursor = "";
      });
      map.getCanvas().setAttribute("aria-label", copy.map.canvasLabel);
      setMapReady(true);
    });
    return () => {
      mapRef.current = null;
      setMapReady(false);
      map.remove();
    };
    // The map mounts once; theme restyling is its own effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Theme switch: repaint the canvas layers from the new token values.
  //
  // The BACKGROUND is the one exception. It is the ground the whole map
  // sits on, so once street tiles are drawing it must belong to the STREET
  // style, not the app theme — otherwise picking the dark map leaves a
  // pale halo of app-theme canvas around the extracted region and every
  // contrast number measured against `theme.earth` stops describing what
  // is on screen outside it. With no basemap downloaded there are no
  // street tiles to agree with, so the app token stays.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const c = mapColors();
    const ground =
      basemap === "present"
        ? String(BASEMAP_STYLES[basemapStyle].theme.background)
        : c.bg;
    map.setPaintProperty("background", "background-color", ground);
    if (map.getLayer("routes-line")) {
      map.setPaintProperty("routes-line", "line-color", c.route);
    }
    if (map.getLayer("stops-dot")) {
      map.setPaintProperty("stops-dot", "circle-color", c.stop);
    }
    if (map.getLayer("vehicles-dot")) {
      map.setPaintProperty("vehicles-dot", "circle-color", c.vehicle);
      map.setPaintProperty("vehicles-dot", "circle-stroke-color", c.vehicleRing);
    }
    if (map.getLayer("vehicles-selected")) {
      map.setPaintProperty("vehicles-selected", "circle-stroke-color", c.vehicle);
    }
  }, [theme, mapReady, basemap, basemapStyle]);

  // ---- the self-hosted basemap: detected, never assumed ----
  useEffect(() => {
    let cancelled = false;
    detectBasemap().then((state) => {
      if (!cancelled) setBasemap(state);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Streets under everything: the archive source plus the chosen style's
  // street layers, inserted BEFORE the schematic route lines so stops,
  // routes and vehicles always draw on top. Style switches swap the street
  // layers in place; the overlay layers and their data are never touched.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || basemap !== "present") return;
    if (!map.getSource("basemap")) {
      map.addSource("basemap", {
        type: "vector",
        url: `pmtiles://${window.location.origin}${BASEMAP_PATH}`,
        // MapLibre-level attribution metadata; the VISIBLE credit is the
        // always-on overlay + legend (ODbL is honored conspicuously).
        attribution: copy.map.basemap.attribution,
      });
    }
    for (const id of basemapLayerIds.current) {
      if (map.getLayer(id)) map.removeLayer(id);
    }
    const specs = basemapLayerSpecs(basemapStyle);
    for (const spec of specs) {
      map.addLayer(spec, "routes-line");
    }
    basemapLayerIds.current = specs.map((s) => s.id);
  }, [mapReady, basemap, basemapStyle]);

  // ---- geometry: fetched once ----
  useEffect(() => {
    getStopsGeojson()
      .then((data) => setStops({ state: "ready", data }))
      .catch((err) => setStops(toError(err)));
    getRoutesGeojson()
      .then((data) => setRoutes({ state: "ready", data }))
      .catch((err) => setRoutes(toError(err)));
  }, []);

  // Geometry onto the map + fit the view to the system's own extent.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || stops.state !== "ready") return;
    const src = map.getSource("stops") as GeoJSONSource | undefined;
    src?.setData(stops.data as unknown as GeoJSON);
    // Fit to the stops' own bounding box (position math, not figures).
    const coords = stops.data.features.map((f) => f.geometry.coordinates);
    if (coords.length > 0) {
      let [minX, minY] = coords[0];
      let [maxX, maxY] = coords[0];
      for (const [x, y] of coords) {
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      }
      map.fitBounds(
        [
          [minX, minY],
          [maxX, maxY],
        ],
        { padding: 40, duration: 0 }, // initial framing: instant, not motion
      );
    }
  }, [mapReady, stops]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || routes.state !== "ready") return;
    const src = map.getSource("routes") as GeoJSONSource | undefined;
    src?.setData(routes.data as unknown as GeoJSON);
  }, [mapReady, routes]);

  // ---- vehicles: fetch now + poll (dots JUMP on new data, by design) ----
  const fetchVehicles = useMemo(
    () => (seconds: number) => {
      const seq = ++fetchSeq.current;
      setPolling(true);
      getLatestVehicles(seconds)
        .then((data) => {
          if (seq !== fetchSeq.current) return; // a newer fetch superseded us
          setVehicles({ state: "ready", data });
          setPolling(false);
          setLastCheckedAt(new Date());
        })
        .catch((err) => {
          if (seq !== fetchSeq.current) return;
          setVehicles(toError(err));
          setPolling(false);
          setLastCheckedAt(new Date());
        });
    },
    [],
  );

  useEffect(() => {
    fetchVehicles(windowSeconds);
    const timer = window.setInterval(
      () => fetchVehicles(windowSeconds),
      POLL_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, [windowSeconds, fetchVehicles]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || vehicles.state !== "ready") return;
    const src = map.getSource("vehicles") as GeoJSONSource | undefined;
    src?.setData(vehiclesToGeojson(vehicles.data.vehicles));
  }, [mapReady, vehicles]);

  // Selection ring follows the selected vehicle.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !map.getLayer("vehicles-selected")) return;
    map.setFilter("vehicles-selected", [
      "==",
      ["get", "vehicle_id"],
      selectedId ?? "",
    ]);
  }, [mapReady, selectedId]);

  const t = copy.map;
  const res = vehicles.state === "ready" ? vehicles.data : null;
  const selected =
    res?.vehicles.find((v) => v.vehicle_id === selectedId) ?? null;

  // The staleness chip: LIVE only while the newest position on record is
  // inside the live window — regardless of how wide the user's window is.
  const chip = (() => {
    if (!res) return null;
    if (!res.newest_position_at) {
      return { tone: "quiet" as const, text: t.chip.none };
    }
    const asOf = Date.parse(res.as_of);
    const newest = Date.parse(res.newest_position_at);
    const fresh =
      !Number.isNaN(asOf) &&
      !Number.isNaN(newest) &&
      asOf - newest <= LIVE_WINDOW_SECONDS * 1000;
    if (fresh) {
      return {
        tone: "live" as const,
        text: t.chip.live(timeLabel(res.newest_position_at)),
      };
    }
    const duration = quietDuration(res);
    return {
      tone: "quiet" as const,
      text: duration ? t.chip.quiet(duration) : t.chip.none,
    };
  })();

  const selectFromList = (vehicle: OpsVehicle) => {
    setSelectedId(vehicle.vehicle_id);
    const map = mapRef.current;
    if (map && mapReady) {
      const target = {
        center: [vehicle.longitude, vehicle.latitude] as [number, number],
        zoom: Math.max(map.getZoom(), 12),
      };
      // Reduced motion = jump, not glide (handoff 0021 motion rules).
      if (prefersReducedMotion()) map.jumpTo(target);
      else map.easeTo({ ...target, duration: 600 });
    }
  };

  const geometryEmpty =
    stops.state === "ready" &&
    routes.state === "ready" &&
    stops.data.features.length === 0 &&
    routes.data.features.length === 0;

  const listRows = res ? res.vehicles.slice(0, LIST_CAP) : [];

  return (
    <>
      <h1>{t.heading}</h1>
      <p>{t.intro}</p>
      {/* Ops boundary ON the surface (handoff 0014 precedent): the badge +
          the server's own boundary statement, verbatim. */}
      <p className="stat-flags">
        <OpsBadge />
      </p>
      {res && <p className="chart-desc">{res.ops_note}</p>}

      {/* ---- the staleness window ---- */}
      <div
        className="filter-bar"
        role="group"
        aria-label={t.window.label}
      >
        <span className="filter-bar-label">{t.window.label}:</span>
        {WINDOW_OPTIONS.map((opt) => (
          <button
            key={opt.seconds}
            type="button"
            aria-pressed={windowSeconds === opt.seconds}
            onClick={() => setWindowSeconds(opt.seconds)}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <p className="chart-desc">{t.window.note}</p>

      {/* ---- street style: the user's own choice, not the app theme.
              Real <button>s in a labeled group with aria-pressed — the
              house filter-bar pattern, reachable and operable from the
              keyboard, and the same control whichever app theme or
              audience lens is active. Switching repaints tiles only. ---- */}
      {basemap === "present" && (
        <>
          <div
            className="filter-bar"
            role="group"
            aria-label={t.basemap.style.label}
          >
            <span className="filter-bar-label">{t.basemap.style.label}:</span>
            {(["light", "dark"] as BasemapStyle[]).map((style) => (
              <button
                key={style}
                type="button"
                aria-pressed={basemapStyle === style}
                onClick={() => {
                  setBasemapStyle(style);
                  persistBasemapStyle(style);
                }}
              >
                {t.basemap.style[style]}
              </button>
            ))}
          </div>
          <p className="chart-desc">{t.basemap.style.note}</p>
        </>
      )}

      {/* ---- the honesty chip row ---- */}
      <div className="map-status">
        {vehicles.state === "loading" && (
          <span className="chip">{t.chip.checking}</span>
        )}
        {chip && (
          <span className={`chip map-chip ${chip.tone}`}>{chip.text}</span>
        )}
        {res && (
          <span className="map-count">
            {t.vehiclesCount(res.vehicle_count.toLocaleString("en-US"))}
          </span>
        )}
        <button
          type="button"
          aria-busy={polling}
          onClick={() => {
            if (!polling) fetchVehicles(windowSeconds);
          }}
        >
          {polling ? t.refreshing : t.refresh}
        </button>
        {lastCheckedAt && (
          <span className="map-last-checked" role="status">
            {t.lastChecked(
              lastCheckedAt.toLocaleTimeString("en-US", { hour12: false }),
            )}
          </span>
        )}
      </div>
      <p className="chart-desc">{t.pollNote}</p>
      {/* Load failures render VERBATIM, never animated (house rule). */}
      {vehicles.state === "error" && (
        <div role="alert" className="alert">
          {vehicles.message}
        </div>
      )}
      {stops.state === "error" && (
        <div role="alert" className="alert">
          {stops.message}
        </div>
      )}
      {routes.state === "error" && (
        <div role="alert" className="alert">
          {routes.message}
        </div>
      )}
      {/* Fail loudly: a basemap file that answered wrong is SAID, not
          silently skipped (the canvas still works without it). */}
      {basemap === "unusable" && (
        <div role="alert" className="alert">
          {t.basemap.unusable}
        </div>
      )}
      {/* The server's own staleness/emptiness note, verbatim. */}
      {res?.note && <p className="banner">{res.note}</p>}
      {res && res.vehicle_count === 0 && (
        <p className="chart-desc">{t.empty.vehiclesAction}</p>
      )}
      {/* Cap honesty: any truncation note renders verbatim. */}
      {res?.truncated && res.note === null && (
        <p className="banner">{t.truncatedIntro}</p>
      )}
      {stops.state === "ready" && stops.data.note && (
        <p className="banner">{stops.data.note}</p>
      )}
      {routes.state === "ready" && routes.data.note && (
        <p className="banner">{routes.data.note}</p>
      )}

      {/* ---- teaching empty state: nothing to draw at all ---- */}
      {geometryEmpty && (
        <div className="card today-card">
          <p>{t.empty.geometry}</p>
          <p>{t.empty.geometryAction}</p>
        </div>
      )}

      {(stops.state === "loading" || routes.state === "loading") && (
        <Skeleton variant="lines" count={2} label={t.loading} />
      )}

      {/* ---- the canvas (presentation; equivalents beside it) ---- */}
      <div className="map-canvas-wrap">
        <div
          ref={containerRef}
          className="map-canvas"
          role="application"
          aria-label={t.canvasLabel}
          data-testid="map-canvas"
        />
        {/* ODbL attribution — visible ON the map whenever street tiles
            render. Non-negotiable (handoff 0027); solid token surface so
            the credit is readable over any imagery, both themes. */}
        {basemap === "present" && (
          <p className="map-attribution">{t.basemap.attribution}</p>
        )}
      </div>

      {/* ---- legend: the schematic honesty is VISIBLE ---- */}
      <section aria-label={t.legend.heading} className="map-legend">
        <h2>{t.legend.heading}</h2>
        <ul>
          <li>
            <span className="map-key map-key-stop" aria-hidden="true" />
            {t.legend.stops}
          </li>
          <li>
            <span className="map-key map-key-route" aria-hidden="true" />
            {t.legend.routes}
          </li>
          <li>
            <span className="map-key map-key-vehicle" aria-hidden="true" />
            {t.legend.vehicles}
          </li>
          {basemap === "present" && (
            <li>
              <span className="map-key map-key-basemap" aria-hidden="true" />
              {t.basemap.legendLine}
            </li>
          )}
        </ul>
        {routes.state === "ready" && (
          <p className="chart-desc">
            {t.legend.schematicIntro} {routes.data.geometry_note}
          </p>
        )}
        {/* Basemap present: the legend carries the ODbL credit and the
            recorded v0 limitation (no POI icons); the schematic line above
            STAYS — streets underneath change nothing about route honesty. */}
        {basemap === "present" && (
          <>
            {/* Which street style is drawing, and the promise it keeps —
                the ITS manager's complaint answered where they look. */}
            <p className="chart-desc">
              {t.basemap.legendStyleLine(BASEMAP_STYLES[basemapStyle].name)}
            </p>
            <p className="chart-desc">{t.basemap.legendCredit}</p>
            <p className="chart-desc">{t.basemap.legendLimit}</p>
          </>
        )}
      </section>

      {/* Quiet teaching line — certifying officials only, basemap absent:
          the one person who could act learns the installer command. */}
      {basemap === "absent" && session?.role === "certifying_official" && (
        <p className="chart-desc">{t.basemap.teachingAbsent}</p>
      )}

      {/* ---- selected vehicle details ---- */}
      {selected && (
        <section
          aria-label={t.vehicle.panelHeading(selected.vehicle_id)}
          className="card map-vehicle-panel"
        >
          <h2>{t.vehicle.panelHeading(selected.vehicle_id)}</h2>
          {selected.simulated && (
            <p className="stat-flags">
              <SimulatedBadge />
            </p>
          )}
          <p>
            {selected.route_id
              ? t.vehicle.routeLine(selected.route_id)
              : t.vehicle.unassigned}
            {selected.trip_id && <> · {t.vehicle.tripLine(selected.trip_id)}</>}
          </p>
          <p>{t.vehicle.ageLine(String(selected.age_seconds))}</p>
          <p>{t.vehicle.recordedLine(selected.recorded_at)}</p>
          <p>
            {t.vehicle.positionLine(
              String(selected.latitude),
              String(selected.longitude),
            )}
          </p>
          <p>{t.vehicle.sourceLine(selected.source)}</p>
          <button type="button" onClick={() => setSelectedId(null)}>
            {t.vehicle.close}
          </button>
        </section>
      )}

      {/* ---- the readable equivalent: the vehicle list ---- */}
      {res && res.vehicle_count > 0 && (
        <section aria-label={t.list.heading} className="map-list">
          <button
            type="button"
            aria-expanded={listOpen}
            onClick={() => setListOpen((open) => !open)}
          >
            {t.list.toggle}
          </button>
          {listOpen && (
            <>
              {res.vehicles.length > LIST_CAP && (
                <p className="banner">
                  {t.list.cap(
                    String(LIST_CAP),
                    res.vehicles.length.toLocaleString("en-US"),
                  )}
                </p>
              )}
              <table>
                <caption>{t.list.caption}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t.list.columns.vehicle}</th>
                    <th scope="col">{t.list.columns.route}</th>
                    <th scope="col">{t.list.columns.age}</th>
                    <th scope="col">{t.list.columns.source}</th>
                  </tr>
                </thead>
                <tbody>
                  {listRows.map((v) => (
                    <tr key={v.vehicle_id}>
                      <td>
                        <button
                          type="button"
                          className="link-like"
                          onClick={() => selectFromList(v)}
                        >
                          {v.vehicle_id}
                          <span className="visually-hidden">
                            {` — ${t.list.select(v.vehicle_id)}`}
                          </span>
                        </button>
                      </td>
                      <td>
                        {v.route_id ?? t.list.unassigned}
                        {v.simulated && (
                          <>
                            {" "}
                            <SimulatedBadge />
                          </>
                        )}
                      </td>
                      <td>{v.age_seconds}</td>
                      <td>{v.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}
    </>
  );
}

export default MapView;
