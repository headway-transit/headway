/**
 * The mode join and the flagged-findings layer (handoff 0043, design
 * points 4, 6 and 7) — the parts that are pure functions, pinned here so
 * the honesty rules are executable rather than aspirational:
 *
 *   - a vehicle's mode is JOINED from the agency's own schedule data and is
 *     'unknown' the moment that join fails, with the reason counted;
 *   - a finding has no location, so a flag is anchored to a route line the
 *     finding itself names — and a finding that cannot be anchored is never
 *     dropped, only listed with the reason;
 *   - the chain is assembled entirely out of what the API served: the
 *     finding's own frozen subject context and the calc runs that named its
 *     issue id.
 */

import { describe, expect, it } from "vitest";
import {
  FLAG_CAP,
  anchorVertex,
  findingChain,
  findingRouteIds,
  placeFindings,
  routeGeometryIndex,
  routeLabelIndex,
} from "../map/findings";
import {
  modeFilterOptions,
  routeModeIndex,
  vehicleMode,
  vehiclesToGeojson,
} from "../map/vehicles";
import type {
  CalcRunRecord,
  DqIssueSummary,
  OpsVehicle,
  RoutesCollection,
} from "../api/types";

function route(
  routeId: string,
  mode: string,
  coords: [number, number][] = [
    [-71, 42],
    [-71.1, 42.1],
    [-71.2, 42.2],
  ],
  shortName: string | null = routeId,
) {
  return {
    type: "Feature",
    geometry: { type: "LineString", coordinates: coords },
    properties: {
      route_id: routeId,
      short_name: shortName,
      long_name: `${routeId} Line`,
      mode,
    },
  };
}

function routes(features: ReturnType<typeof route>[]): RoutesCollection {
  return {
    type: "FeatureCollection",
    features,
    category: "ops",
    ops_note: "",
    geometry_kind: "schematic_stop_sequence",
    geometry_note: "",
    route_count: features.length,
    routes_without_geometry: 0,
    cap: 2000,
    truncated: false,
    total_routes_with_trips: features.length,
    computed_at: "2026-08-01T00:00:00Z",
    cache_ttl_seconds: 900,
    cache_note: "",
    note: null,
  } as unknown as RoutesCollection;
}

function vehicle(id: string, routeId: string | null): OpsVehicle {
  return {
    vehicle_id: id,
    latitude: 42,
    longitude: -71,
    recorded_at: "2026-08-01T00:00:00Z",
    age_seconds: 10,
    route_id: routeId,
    source_record_id: `raw-${id}`,
    source: "gtfs_rt",
    simulated: false,
  };
}

function issue(
  id: string,
  overrides: Partial<DqIssueSummary> = {},
): DqIssueSummary {
  return {
    issue_id: id,
    issue_type: "coverage_gap",
    severity: "blocking",
    status: "open",
    owner: null,
    title: `Finding ${id}`,
    description: "Something the calculation could not certify over.",
    created_at: "2026-08-01T00:00:00Z",
    resolved_at: null,
    resolution: null,
    ...overrides,
  };
}

function subject(
  groups: {
    block_id: string | null;
    block_label?: string | null;
    routes: string[];
    trip_count?: number;
    trip_ids?: string[];
  }[],
  extra: Record<string, unknown> = {},
) {
  return {
    version: 1,
    kind: "trips",
    total: 10,
    grouped_by: "block",
    group_count: groups.length,
    group_cap: 20,
    trip_id_cap: 20,
    groups: groups.map((g) => ({
      block_id: g.block_id,
      block_label: g.block_label ?? null,
      trip_count: g.trip_count ?? 2,
      routes: g.routes.map((r) => ({
        route_id: r,
        short_name: r,
        long_name: `${r} Line`,
      })),
      route_count: g.routes.length,
      first_departure: "2026-08-01T05:00:00Z",
      last_departure: "2026-08-01T23:00:00Z",
      trip_ids: g.trip_ids ?? ["t1", "t2"],
    })),
    ...extra,
  } as DqIssueSummary["subject_context"];
}

describe("the mode join — the schedule data decides, and a miss is said out loud", () => {
  const collection = routes([route("R1", "bus"), route("R2", "subway")]);

  it("takes a vehicle's mode from the route the FEED named, in the agency's own data", () => {
    const modes = routeModeIndex(collection);
    expect(vehicleMode(vehicle("v1", "R1"), modes)).toEqual({
      mode: "bus",
      gap: null,
    });
    expect(vehicleMode(vehicle("v2", "R2"), modes).mode).toBe("subway");
  });

  it("says 'unknown' — never a guess — when the feed reported no route", () => {
    const modes = routeModeIndex(collection);
    expect(vehicleMode(vehicle("v3", null), modes)).toEqual({
      mode: "unknown",
      gap: "no-route-id",
    });
  });

  it("distinguishes 'no route reported' from 'route we hold no schedule for'", () => {
    const modes = routeModeIndex(collection);
    // These are DIFFERENT problems: one is a quiet feed field, the other is
    // the feed and the schedule disagreeing. Both stay 'unknown'.
    expect(vehicleMode(vehicle("v4", "R-nope"), modes).gap).toBe(
      "route-not-held",
    );
  });

  it("counts every unresolved vehicle by reason instead of quietly greying it", () => {
    const modes = routeModeIndex(collection);
    const { data, unresolved } = vehiclesToGeojson(
      [
        vehicle("v1", "R1"),
        vehicle("v2", null),
        vehicle("v3", null),
        vehicle("v4", "R-nope"),
      ],
      modes,
    );
    expect(unresolved).toEqual({ "no-route-id": 2, "route-not-held": 1 });
    const features = (data as { features: { properties: Record<string, unknown> }[] })
      .features;
    expect(features.map((f) => f.properties.mode)).toEqual([
      "bus",
      "unknown",
      "unknown",
      "unknown",
    ]);
    // The route the FEED named survives next to the derived mode, so the
    // join is inspectable rather than magic.
    expect(features[3].properties.route_id).toBe("R-nope");
  });

  it("puts each vehicle exactly where the feed said it was — no smoothing, no carry-forward", () => {
    const modes = routeModeIndex(collection);
    const v = vehicle("v1", "R1");
    v.longitude = -71.0625;
    v.latitude = 42.1894;
    const { data } = vehiclesToGeojson([v], modes);
    const features = (data as { features: { geometry: { coordinates: number[] } }[] })
      .features;
    expect(features[0].geometry.coordinates).toEqual([-71.0625, 42.1894]);
  });

  it("skips a route with no usable mode rather than defaulting it to something", () => {
    const broken = routes([route("R1", ""), route("R2", "ferry")]);
    const modes = routeModeIndex(broken);
    expect(modes.byRoute.has("R1")).toBe(false);
    expect(modes.present).toEqual(["ferry"]);
  });

  it("offers the filter only for modes the agency's own routes carry", () => {
    const modes = routeModeIndex(collection);
    expect(modeFilterOptions(modes, 0)).toEqual(["bus", "subway"]);
    // 'unknown' appears only once at least one vehicle actually has no mode.
    expect(modeFilterOptions(modes, 3)).toEqual(["bus", "subway", "unknown"]);
  });
});

describe("flagged findings — anchored to a route, never to an invented place", () => {
  const collection = routes([route("R1", "bus"), route("R2", "subway")]);

  it("anchors a flag on the route's OWN vertices, deterministically", () => {
    const coords: [number, number][] = [
      [0, 0],
      [1, 1],
      [2, 2],
      [3, 3],
      [4, 4],
    ];
    const first = anchorVertex(coords, 0);
    const second = anchorVertex(coords, 1);
    expect(coords).toContainEqual(first);
    expect(coords).toContainEqual(second);
    // Two findings on one route do not stack on top of each other …
    expect(first).not.toEqual(second);
    // … and the same finding lands in the same place on every poll.
    expect(anchorVertex(coords, 0)).toEqual(first);
    // A degenerate one-point line still anchors rather than throwing.
    expect(anchorVertex([[9, 9]], 3)).toEqual([9, 9]);
  });

  it("draws one flag per FINDING, not one per route it touches", () => {
    const placement = placeFindings(
      [issue("i1", { subject_context: subject([{ block_id: "b1", routes: ["R1", "R2"] }]) })],
      collection,
    );
    expect(placement.placed.length).toBe(1);
    // The routes it also names are counted, not hidden.
    expect(placement.placed[0].other_route_count).toBe(1);
    expect(placement.placed[0].route_id).toBe("R1");
  });

  it("labels a flag with the route's short name, from the schedule data", () => {
    const named = routes([route("R1", "bus", undefined, "77")]);
    const placement = placeFindings(
      [issue("i1", { subject_context: subject([{ block_id: "b", routes: ["R1"] }]) })],
      named,
    );
    expect(placement.placed[0].label).toBe("77");
  });

  it("keeps every un-anchorable finding, each with the REASON it has no flag", () => {
    const placement = placeFindings(
      [
        issue("no-context"),
        issue("no-route", { subject_context: subject([{ block_id: "b", routes: [] }]) }),
        issue("undrawn", {
          subject_context: subject([{ block_id: "b", routes: ["R-nope"] }]),
        }),
        issue("ok", { subject_context: subject([{ block_id: "b", routes: ["R1"] }]) }),
      ],
      collection,
    );
    expect(placement.placed.map((p) => p.issue_id)).toEqual(["ok"]);
    expect(placement.skipped.map((s) => [s.issue.issue_id, s.gap])).toEqual([
      ["no-context", "no-subject"],
      ["no-route", "no-route"],
      ["undrawn", "route-not-drawn"],
    ]);
  });

  it("keeps the flags SCARCE — past the cap a finding is listed, never silently gone", () => {
    const many = Array.from({ length: FLAG_CAP + 4 }, (_, i) =>
      issue(`i${i}`, {
        subject_context: subject([{ block_id: `b${i}`, routes: ["R1"] }]),
      }),
    );
    const placement = placeFindings(many, collection);
    expect(placement.placed.length).toBe(FLAG_CAP);
    expect(placement.skipped.length).toBe(4);
    expect(placement.skipped.every((s) => s.gap === "over-cap")).toBe(true);
    // Nothing has left the worklist.
    expect(placement.placed.length + placement.skipped.length).toBe(many.length);
  });

  it("hands MapLibre a stable feature id so a re-poll never reshuffles the flags", () => {
    const placement = placeFindings(
      [issue("i1", { subject_context: subject([{ block_id: "b", routes: ["R1"] }]) })],
      collection,
    );
    const features = (
      placement.data as { features: { properties: Record<string, unknown> }[] }
    ).features;
    expect(features[0].properties.finding_key).toBe("i1");
    expect(features[0].properties.issue_id).toBe("i1");
    expect(features[0].properties.severity).toBe("blocking");
  });

  it("draws nothing at all when no route geometry has been loaded yet", () => {
    const placement = placeFindings(
      [issue("i1", { subject_context: subject([{ block_id: "b", routes: ["R1"] }]) })],
      null,
    );
    expect(placement.placed).toEqual([]);
    expect(placement.skipped[0].gap).toBe("route-not-drawn");
  });

  it("indexes routes by id for geometry and for label, skipping malformed features", () => {
    const messy = routes([route("R1", "bus")]);
    messy.features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: [] },
      properties: { route_id: "R-empty" },
    } as unknown as (typeof messy.features)[number]);
    expect([...routeGeometryIndex(messy).keys()]).toEqual(["R1"]);
    // A route with no short name falls back to its id, never to a blank.
    expect(routeLabelIndex(routes([route("R9", "bus", undefined, null)])).get("R9")).toBe(
      "R9",
    );
  });

  it("de-duplicates the routes a finding names, in the order it named them", () => {
    expect(
      findingRouteIds(
        issue("i", {
          subject_context: subject([
            { block_id: "b1", routes: ["R2", "R1"] },
            { block_id: "b2", routes: ["R1"] },
          ]),
        }),
      ),
    ).toEqual(["R2", "R1"]);
  });
});

describe("the relationship chain — assembled only from what the API served", () => {
  const collection = routes([route("R1", "bus"), route("R2", "subway")]);
  const modes = routeModeIndex(collection);

  const run = (metrics: Record<string, unknown>[]): CalcRunRecord =>
    ({
      run_id: "run-1",
      requested_by: "steward",
      requested_at: "2026-08-01T00:00:00Z",
      period_start: "2026-06-01",
      period_end: "2026-07-01",
      status: "succeeded",
      started_at: null,
      finished_at: null,
      runner_pid: null,
      summary: { metrics },
      stdout_tail: null,
      duration_seconds: null,
      stale: false,
      stale_note: null,
    }) as unknown as CalcRunRecord;

  it("walks finding → block → route → calculation → owner", () => {
    const target = issue("i1", {
      owner: "alex",
      subject_context: subject([
        { block_id: "225", block_label: "225-4", routes: ["R1"] },
      ]),
    });
    const chain = findingChain(target, collection, modes, [
      run([
        {
          calc_name: "vrm_v0",
          calc_version: "0.3.0",
          metric: "vrm",
          outcome: "refused",
          blocking_issue_ids: ["i1"],
          warning_issue_ids: [],
          info_issue_ids: [],
        },
      ]),
    ]);
    expect(chain.blocks[0].block_label).toBe("225-4");
    expect(chain.blocks[0].block_id).toBe("225");
    expect(chain.routes).toEqual([
      {
        route_id: "R1",
        short_name: "R1",
        long_name: "R1 Line",
        mode: "bus",
        drawn: true,
      },
    ]);
    expect(chain.calcs).toEqual([
      {
        run_id: "run-1",
        calc_name: "vrm_v0",
        calc_version: "0.3.0",
        metric: "vrm",
        outcome: "refused",
        period_start: "2026-06-01",
        period_end: "2026-07-01",
        role: "blocking",
      },
    ]);
    expect(chain.owner).toBe("alex");
  });

  it("finds no calculation rather than inventing one", () => {
    const chain = findingChain(
      issue("i1", { subject_context: subject([{ block_id: "b", routes: ["R1"] }]) }),
      collection,
      modes,
      [
        run([
          {
            calc_name: "vrm_v0",
            calc_version: "0.3.0",
            metric: "vrm",
            outcome: "persisted",
            blocking_issue_ids: ["some-other-finding"],
            warning_issue_ids: [],
            info_issue_ids: [],
          },
        ]),
      ],
    );
    expect(chain.calcs).toEqual([]);
  });

  it("marks a named route we hold no line for, so the panel can say so", () => {
    const chain = findingChain(
      issue("i1", { subject_context: subject([{ block_id: "b", routes: ["R-nope"] }]) }),
      collection,
      modes,
      [],
    );
    expect(chain.routes[0]).toMatchObject({ drawn: false, mode: null });
  });

  it("surfaces the subject context's OWN caps and its unattributed trips", () => {
    const capped = issue("i1", {
      subject_context: subject(
        [{ block_id: "b", routes: ["R1"], trip_count: 40, trip_ids: ["t1"] }],
        { group_count: 9, unmatched: { trip_count: 3, trip_ids: ["t9"] } },
      ),
    });
    const chain = findingChain(capped, collection, modes, []);
    expect(chain.subjectCapped).toBe(true);
    expect(chain.unmatchedTripCount).toBe(3);
  });

  it("survives a finding with no subject context at all — the normal case", () => {
    const chain = findingChain(issue("i1"), collection, modes, []);
    expect(chain.blocks).toEqual([]);
    expect(chain.routes).toEqual([]);
    expect(chain.subjectCapped).toBe(false);
  });
});
