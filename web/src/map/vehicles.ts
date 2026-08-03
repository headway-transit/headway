/**
 * Vehicles → the map source, with a `mode` the API never sent (handoff
 * 0043, design point 4).
 *
 * THE FIELD DOES NOT EXIST, SO WE DO NOT PRETEND IT DOES
 * -----------------------------------------------------
 * `GET /ops/vehicles/latest` has no `mode` on a vehicle — it reports
 * position, age, source, and (when the feed said so) `route_id` and
 * `trip_id`. `GET /geometry/routes`, which this view already fetches, DOES
 * carry `mode` on every route feature: the canonical mode the transform
 * derived from the agency's own GTFS `routes.txt` route_type.
 *
 * So the mode on a mark is a JOIN through the agency's own schedule data —
 * vehicle.route_id → that route's mode — and nothing else. In particular:
 *   - a vehicle the feed reported with NO route_id is 'unknown'. It is not
 *     assigned to a mode by proximity, by its previous trip, or by "most of
 *     the fleet is a bus". The map draws it as the hollow ring and the
 *     list says "Not assigned to a route".
 *   - a vehicle whose route_id we hold no route for is 'unknown' too, and
 *     that is a DIFFERENT sentence in the list, because it means something
 *     different: the feed named a route the schedule data does not contain,
 *     or the routes response was capped. Both are worth someone's time.
 *   - `unresolved` counts exactly how many of each there are, so the gap is
 *     a number on the screen rather than a quietly grey dot.
 *
 * This is a client-side derivation of a DISPLAY attribute, never of a
 * reported figure. If the vehicles payload ever grows a server-side `mode`,
 * it should win outright — see the handoff's backend follow-up.
 */

import type { GeoJSON } from "geojson";
import type { OpsVehicle, RoutesCollection } from "../api/types";

/** The mode a vehicle is drawn as when we were not told one. */
export const MODE_UNKNOWN = "unknown";

/** Why a vehicle has no mode — each reason is a different sentence. */
export type ModeGap = "no-route-id" | "route-not-held";

export interface VehicleModes {
  /** route_id → canonical mode, from the agency's own schedule data. */
  byRoute: Map<string, string>;
  /** Modes that actually appear on routes we hold, in a stable order. */
  present: string[];
}

/**
 * Index the routes response by route_id. Routes whose `mode` is missing or
 * not a string are skipped rather than defaulted — a route with no mode
 * makes its vehicles 'unknown', which is the honest outcome.
 */
export function routeModeIndex(
  routes: RoutesCollection | null,
): VehicleModes {
  const byRoute = new Map<string, string>();
  const present = new Set<string>();
  for (const feature of routes?.features ?? []) {
    const props = feature.properties ?? {};
    const routeId = props.route_id;
    const mode = props.mode;
    if (typeof routeId !== "string" || typeof mode !== "string" || !mode) {
      continue;
    }
    byRoute.set(routeId, mode);
    present.add(mode);
  }
  return { byRoute, present: [...present].sort() };
}

/** The mode of one vehicle, plus WHY when there isn't one. */
export function vehicleMode(
  vehicle: OpsVehicle,
  modes: VehicleModes,
): { mode: string; gap: ModeGap | null } {
  if (!vehicle.route_id) return { mode: MODE_UNKNOWN, gap: "no-route-id" };
  const mode = modes.byRoute.get(vehicle.route_id);
  if (!mode) return { mode: MODE_UNKNOWN, gap: "route-not-held" };
  return { mode, gap: null };
}

export interface VehiclesGeojson {
  data: GeoJSON;
  /** How many vehicles could not be given a mode, and why. */
  unresolved: Record<ModeGap, number>;
}

/**
 * Vehicles → GeoJSON for the map source. Positions verbatim: each feature
 * sits exactly where the feed said the vehicle was, and a new response
 * replaces the collection outright, so a mark JUMPS to its new observed
 * position. Nothing here interpolates, eases, or carries a previous
 * position forward.
 */
export function vehiclesToGeojson(
  vehicles: OpsVehicle[],
  modes: VehicleModes,
): VehiclesGeojson {
  const unresolved: Record<ModeGap, number> = {
    "no-route-id": 0,
    "route-not-held": 0,
  };
  const features = vehicles.map((v) => {
    const { mode, gap } = vehicleMode(v, modes);
    if (gap) unresolved[gap] += 1;
    return {
      type: "Feature" as const,
      geometry: {
        type: "Point" as const,
        coordinates: [v.longitude, v.latitude],
      },
      properties: {
        vehicle_id: v.vehicle_id,
        mode,
        /** The route the FEED named, kept verbatim next to the derived
         *  mode so the join is inspectable rather than magic. */
        route_id: v.route_id ?? null,
      },
    };
  });
  return {
    data: { type: "FeatureCollection", features },
    unresolved,
  };
}

/**
 * The modes the mode filter offers: only modes that actually carry a route
 * in this agency's data, never a hardcoded catalogue (the ModeBar
 * discipline from handoff 0041). 'unknown' is offered only when at least
 * one vehicle actually has no mode — a filter for an empty set is noise.
 */
export function modeFilterOptions(
  modes: VehicleModes,
  unresolvedTotal: number,
): string[] {
  return unresolvedTotal > 0
    ? [...modes.present, MODE_UNKNOWN]
    : [...modes.present];
}
