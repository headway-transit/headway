/**
 * The flagged-for-investigation layer and the relationship chain behind it
 * (handoff 0043, design points 6 and 7).
 *
 * A FINDING HAS NO LOCATION, AND THIS FILE NEVER INVENTS ONE
 * ----------------------------------------------------------
 * `GET /dq/issues` returns no coordinates. A data-quality finding is about
 * a set of trips on a block, not about a place, and it is usually about a
 * period that has already ended. So a flag on this map does NOT say "the
 * problem is here". It says "the route drawn under this flag has an open,
 * blocking finding on it" — the flag is anchored to the route's own
 * schematic line, which is itself explicitly not the path a vehicle drove.
 * The position ALONG that line carries no meaning at all and the legend and
 * the panel both say so, in those words.
 *
 * Anchoring is deterministic (nth vertex for the nth finding on a route) so
 * two findings on one route are separately clickable, and so a re-poll
 * never shuffles the flags around.
 *
 * SCARCE, BY CONSTRUCTION
 * -----------------------
 * Attention-glow only means anything while it is rare. The layer is
 * therefore fed from `status=open` + `severity=blocking` — the findings
 * that are actually blocking a certifiable figure and have nobody's
 * resolution on them yet — and then capped, with the cap stated. Findings
 * that could not be drawn are NOT dropped: every one of them is in the
 * "needs investigation" list beside the map with the reason it has no flag.
 */

import type {
  CalcRunRecord,
  DqIssue,
  DqIssueSummary,
  DqSubjectGroup,
  RoutesCollection,
} from "../api/types";
import type { GeoJSON } from "geojson";
import type { VehicleModes } from "./vehicles";

/** Flags drawn on the canvas at once. Scarce on purpose; stated in copy. */
export const FLAG_CAP = 12;

/** Why a finding has no flag on the map. Each is a different sentence. */
export type PlacementGap =
  | "no-subject"
  | "no-route"
  | "route-not-drawn"
  | "over-cap";

export interface PlacedFinding {
  issue_id: string;
  severity: string;
  status: string;
  title: string;
  owner: string | null;
  /** The route the flag was anchored to. */
  route_id: string;
  /** What the flag is labelled with on the canvas — short by design. */
  label: string;
  /** Other routes this same finding also names, counted not hidden. */
  other_route_count: number;
  coordinates: [number, number];
}

export interface FindingPlacement {
  /** Drawn flags, in the order they were placed. */
  placed: PlacedFinding[];
  /** Findings with no flag, each with the reason — shown in the list. */
  skipped: { issue: DqIssueSummary; gap: PlacementGap }[];
  /** GeoJSON for the findings source; `finding_key` is the promoted id. */
  data: GeoJSON;
}

/** Every route id a finding names, in the order its subject context lists
 *  them, de-duplicated. */
export function findingRouteIds(issue: DqIssueSummary): string[] {
  const seen: string[] = [];
  for (const group of issue.subject_context?.groups ?? []) {
    for (const route of group.routes ?? []) {
      if (route.route_id && !seen.includes(route.route_id)) {
        seen.push(route.route_id);
      }
    }
  }
  return seen;
}

/** route_id → its drawn LineString coordinates, from /geometry/routes. */
export function routeGeometryIndex(
  routes: RoutesCollection | null,
): Map<string, [number, number][]> {
  const index = new Map<string, [number, number][]>();
  for (const feature of routes?.features ?? []) {
    const routeId = feature.properties?.route_id;
    const coords = feature.geometry?.coordinates;
    if (typeof routeId !== "string" || !Array.isArray(coords)) continue;
    if (coords.length === 0) continue;
    index.set(routeId, coords as [number, number][]);
  }
  return index;
}

/** route_id → its display short name, for the flag's on-canvas label. */
export function routeLabelIndex(
  routes: RoutesCollection | null,
): Map<string, string> {
  const index = new Map<string, string>();
  for (const feature of routes?.features ?? []) {
    const props = feature.properties ?? {};
    const routeId = props.route_id;
    if (typeof routeId !== "string") continue;
    const short = props.short_name;
    index.set(routeId, typeof short === "string" && short ? short : routeId);
  }
  return index;
}

/**
 * Anchor point for the nth flag on a route: walk the route's own vertices
 * so the flag always sits ON the drawn line. `nth` spreads repeat findings
 * apart without ever leaving the geometry.
 */
export function anchorVertex(
  coords: [number, number][],
  nth: number,
): [number, number] {
  if (coords.length === 1) return coords[0];
  // Fractions 1/2, 1/3, 2/3, 1/4, 3/4 … — deterministic, never random.
  const denominator = Math.floor(nth / 2) + 2;
  const numerator = (nth % 2) + 1;
  const at = Math.min(
    coords.length - 1,
    Math.max(0, Math.round(((coords.length - 1) * numerator) / denominator)),
  );
  return coords[at];
}

/**
 * Place the flagged findings on the routes they name.
 *
 * One flag per FINDING (not per route it touches), so the count of flags on
 * screen is the count of things needing a human — which is the only reading
 * that makes the glow mean anything.
 */
export function placeFindings(
  issues: DqIssueSummary[],
  routes: RoutesCollection | null,
  cap: number = FLAG_CAP,
): FindingPlacement {
  const geometry = routeGeometryIndex(routes);
  const labels = routeLabelIndex(routes);
  const placed: PlacedFinding[] = [];
  const skipped: { issue: DqIssueSummary; gap: PlacementGap }[] = [];
  const perRoute = new Map<string, number>();

  for (const issue of issues) {
    if (!issue.subject_context) {
      skipped.push({ issue, gap: "no-subject" });
      continue;
    }
    const routeIds = findingRouteIds(issue);
    if (routeIds.length === 0) {
      skipped.push({ issue, gap: "no-route" });
      continue;
    }
    const drawn = routeIds.find((id) => geometry.has(id));
    if (!drawn) {
      skipped.push({ issue, gap: "route-not-drawn" });
      continue;
    }
    if (placed.length >= cap) {
      skipped.push({ issue, gap: "over-cap" });
      continue;
    }
    const nth = perRoute.get(drawn) ?? 0;
    perRoute.set(drawn, nth + 1);
    placed.push({
      issue_id: issue.issue_id,
      severity: issue.severity,
      status: issue.status,
      title: issue.title,
      owner: issue.owner,
      route_id: drawn,
      label: labels.get(drawn) ?? drawn,
      other_route_count: routeIds.length - 1,
      coordinates: anchorVertex(geometry.get(drawn)!, nth),
    });
  }

  return {
    placed,
    skipped,
    data: {
      type: "FeatureCollection",
      features: placed.map((flag) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: flag.coordinates },
        properties: {
          finding_key: flag.issue_id,
          issue_id: flag.issue_id,
          severity: flag.severity,
          label: flag.label,
        },
      })),
    },
  };
}

// ---- the relationship chain ---------------------------------------------

export interface ChainRoute {
  route_id: string;
  short_name: string | null;
  long_name: string | null;
  /** From the agency's own schedule data, or null when we hold no route. */
  mode: string | null;
  /** Whether this route has a line on the map to light up. */
  drawn: boolean;
}

export interface ChainBlock {
  block_id: string | null;
  block_label: string | null;
  trip_count: number;
  first_departure: string | null;
  last_departure: string | null;
  /** The subject context's own capped sample of trip ids. */
  trip_ids: string[];
  routes: ChainRoute[];
}

export interface ChainCalc {
  run_id: string;
  calc_name: string | null;
  calc_version: string | null;
  metric: string | null;
  outcome: string;
  period_start: string;
  period_end: string;
  /** Which severity bucket of that calculation named this finding. */
  role: "blocking" | "warning" | "info";
}

export interface FindingChain {
  issue: DqIssueSummary | DqIssue;
  blocks: ChainBlock[];
  /** Every route the finding names, flattened and de-duplicated. */
  routes: ChainRoute[];
  calcs: ChainCalc[];
  owner: string | null;
  /** Trips the subject context could not attribute to a block. */
  unmatchedTripCount: number;
  /** True when the subject context capped its own group or trip lists. */
  subjectCapped: boolean;
}

function chainRoutes(
  group: DqSubjectGroup,
  modes: VehicleModes,
  geometry: Map<string, [number, number][]>,
): ChainRoute[] {
  return (group.routes ?? []).map((route) => ({
    route_id: route.route_id,
    short_name: route.short_name,
    long_name: route.long_name,
    mode: modes.byRoute.get(route.route_id) ?? null,
    drawn: geometry.has(route.route_id),
  }));
}

/**
 * Assemble finding → block → route → calculation → owner, entirely from
 * what the API served. Nothing here infers a link: the block/route half
 * comes from the finding's own frozen `subject_context`, and the
 * calculation half is the calc runs that named this exact issue id in their
 * own outcome rows.
 */
export function findingChain(
  issue: DqIssueSummary | DqIssue,
  routes: RoutesCollection | null,
  modes: VehicleModes,
  calcRuns: CalcRunRecord[],
): FindingChain {
  const geometry = routeGeometryIndex(routes);
  const context = issue.subject_context ?? null;
  const blocks: ChainBlock[] = (context?.groups ?? []).map((group) => ({
    block_id: group.block_id,
    block_label: group.block_label ?? null,
    trip_count: group.trip_count,
    first_departure: group.first_departure,
    last_departure: group.last_departure,
    trip_ids: group.trip_ids ?? [],
    routes: chainRoutes(group, modes, geometry),
  }));

  const flat = new Map<string, ChainRoute>();
  for (const block of blocks) {
    for (const route of block.routes) {
      if (!flat.has(route.route_id)) flat.set(route.route_id, route);
    }
  }

  const calcs: ChainCalc[] = [];
  for (const run of calcRuns) {
    for (const metric of run.summary?.metrics ?? []) {
      const roles: [ChainCalc["role"], string[]][] = [
        ["blocking", metric.blocking_issue_ids ?? []],
        ["warning", metric.warning_issue_ids ?? []],
        ["info", metric.info_issue_ids ?? []],
      ];
      for (const [role, ids] of roles) {
        if (!ids.includes(issue.issue_id)) continue;
        calcs.push({
          run_id: run.run_id,
          calc_name: metric.calc_name,
          calc_version: metric.calc_version,
          metric: metric.metric,
          outcome: metric.outcome,
          period_start: run.period_start,
          period_end: run.period_end,
          role,
        });
      }
    }
  }

  return {
    issue,
    blocks,
    routes: [...flat.values()],
    calcs,
    owner: issue.owner,
    unmatchedTripCount: context?.unmatched?.trip_count ?? 0,
    subjectCapped:
      context != null &&
      (context.group_count > context.groups.length ||
        context.groups.some((g) => g.trip_count > (g.trip_ids ?? []).length)),
  };
}
