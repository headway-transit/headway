/**
 * THE DISCLOSURE CARVE-OUT (handoff 0044, output 5).
 *
 * Handoff 0044 moved Headway's plain-language paragraphs out of the way of
 * the figures. The danger in that move — named in the handoff itself — is
 * that a wave optimising for a screenshot quietly folds an ADMISSION away
 * with the explanation, and the product's soul goes with it.
 *
 * So this file is the pin. It asserts, WITHOUT EXPANDING ANYTHING:
 *
 *   1. every refusal, held/excluded count, cap, staleness note, scope
 *      receipt, simulated badge and "not an NTD reported figure" boundary
 *      is on screen and VISIBLE;
 *   2. the explanations that moved are still present VERBATIM — the same
 *      strings, not shortened — merely folded;
 *   3. opening a disclosure reveals exactly that text.
 *
 * If a future wave hides an admission to win a nicer picture, these tests
 * go red before the screenshot is ever taken.
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
import { refusalLines } from "../detail";
import {
  dashboardValues,
  dqCountsFor,
  blockingIssue,
  opsOtpAgencyValue,
  opsCvhAgencyValue,
  simulatedUptValue,
} from "./fixtures";

// ---- the maplibre-gl double (WebGL cannot run in jsdom) ----
vi.mock("maplibre-gl", () => {
  class FakeMap {
    canvas = document.createElement("canvas");
    sources: Record<string, unknown> = {};
    on(event: string, a?: unknown, b?: unknown) {
      const cb = (typeof a === "function" ? a : b) as () => void;
      if (event === "load") cb();
      return this;
    }
    addSource(id: string, spec: unknown) {
      this.sources[id] = spec;
    }
    addLayer() {}
    removeLayer() {}
    getLayer() {
      return { id: "x" };
    }
    getSource(id: string) {
      if (id === "basemap" && !(id in this.sources)) return undefined;
      return { setData: () => {} };
    }
    setPaintProperty() {}
    setFilter() {}
    setFeatureState() {}
    getCanvas() {
      return this.canvas;
    }
    fitBounds() {}
    getZoom() {
      return 10;
    }
    jumpTo() {}
    easeTo() {}
    remove() {}
  }
  return { Map: FakeMap, setWorkerUrl: () => {}, addProtocol: () => {} };
});

const OPS_NOTE =
  "Operations data — not an NTD reported figure. Live vehicle positions are never certifiable, never part of any submission, and never a gate on certification (migration 0024 boundary).";
const GEOMETRY_NOTE =
  "Schematic geometry: each route line connects the stops of the route's most common trip pattern with straight segments. It shows structure, not streets.";
const STALE_NOTE =
  "No vehicle has reported a position in the last 300 seconds. The newest position on record is 55141 seconds old — the feed is stale or service is not running, not an empty fleet.";

const stopsBody = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [-71.08, 42.33] },
      properties: { stop_id: "1", name: "Washington St" },
    },
  ],
  category: "ops",
  ops_note: OPS_NOTE,
  stop_count: 1,
  stops_without_coordinates: 0,
  cap: 50000,
  truncated: false,
  total_stops: 1,
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
          [-71.08, 42.33],
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
  cache_note: "Served from a per-process cache.",
  note: null,
};

/** A QUIET feed: the staleness admission the map must never fold away. */
const vehiclesQuiet = {
  as_of: "2026-07-22T18:17:37Z",
  max_age_seconds: 300,
  category: "ops",
  ops_note: OPS_NOTE,
  vehicles: [],
  vehicle_count: 0,
  total_in_window: 0,
  cap: 5000,
  truncated: false,
  newest_position_at: "2026-07-22T02:58:36Z",
  note: STALE_NOTE,
};

function mapRoutes(): Record<string, RouteHandler> {
  return {
    "GET /geometry/stops": { status: 200, body: stopsBody },
    "GET /geometry/routes": { status: 200, body: routesBody },
    "GET /ops/vehicles/latest": { status: 200, body: vehiclesQuiet },
    "GET /dq/issues": {
      status: 200,
      body: {
        issues: [blockingIssue],
        total: 1,
        limit: 50,
        next_cursor: null,
        has_more: false,
      },
    },
  };
}

/**
 * Every disclosure on screen is CLOSED. Called before the carve-out
 * assertions so "visible" can never mean "visible because the test opened
 * something".
 */
function expectEverythingFolded(): HTMLElement[] {
  const toggles = screen
    .getAllByRole("button")
    .filter((b) => b.classList.contains("disclosure-toggle"));
  expect(toggles.length).toBeGreaterThan(0);
  for (const toggle of toggles) {
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  }
  return toggles;
}

describe("progressive disclosure: explanation folds, admission never does", () => {
  it("/dashboard — every refusal, boundary, receipt and simulated badge is VISIBLE with nothing expanded", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": {
        status: 200,
        body: [
          ...dashboardValues,
          simulatedUptValue,
          opsOtpAgencyValue,
          opsCvhAgencyValue,
        ],
      },
      "GET /dq/issues/counts": (call) => {
        const status = new URL(call.url, "http://test").searchParams.get(
          "status",
        );
        return { status: 200, body: dqCountsFor([blockingIssue], status) };
      },
    });
    renderApp("/dashboard");
    await screen.findByRole("heading", { name: "Latest certified figures" });
    // Wait for the two slowest-arriving admissions before asserting on the
    // page as a whole: the DQ card's blocking flag (its own counts call)
    // and the operations boundary (the ops slice of the figures call).
    await screen.findByText(copy.dashboard.dq.blockingFlag("1"));
    await screen.findAllByText(copy.ops.badge);

    // Nothing on this page has been opened.
    expectEverythingFolded();

    // --- the carve-out, item by item -------------------------------------
    // "Not an NTD reported figure": the operations boundary.
    for (const badge of screen.getAllByText(copy.ops.badge)) {
      expect(badge).toBeVisible();
    }
    // The derivation's REFUSAL accounting — what the calculation declined
    // to count, and why. Never folded.
    const refusals = refusalLines(opsOtpAgencyValue.detail);
    expect(refusals.length).toBeGreaterThan(0);
    for (const line of refusals) {
      expect(screen.getAllByText(line)[0]).toBeVisible();
    }
    // The scope receipt — the string the rows were actually filtered on.
    for (const receipt of screen.getAllByText(
      copy.dashboard.mode.scopeReceipt("agency"),
    )) {
      expect(receipt).toBeVisible();
    }
    // "This is NOT a total this page added up from the modes."
    expect(screen.getByText(copy.dashboard.mode.agencyNote)).toBeVisible();
    // "Only modes that already have computed figures are listed here."
    expect(screen.getByText(copy.dashboard.mode.dataDrivenNote)).toBeVisible();
    // An open blocking issue needs a person — the card frame says so.
    expect(
      screen.getByText(copy.dashboard.dq.blockingFlag("1")),
    ).toBeVisible();
    // The SIMULATED badge on a figure computed from test data.
    expect(screen.getAllByText(copy.simulated.badge)[0]).toBeVisible();

    // --- and the explanations are still here, VERBATIM, merely folded ----
    expect(screen.getByText(copy.dashboard.intro)).not.toBeVisible();
    expect(screen.getByText(copy.dashboard.mode.intro)).not.toBeVisible();
    expect(screen.getByText(copy.dashboard.lens.intro)).not.toBeVisible();

    await expectNoAxeViolations();
  });

  it("/dashboard — opening 'What this shows' reveals the introduction word for word (nothing was shortened when it moved)", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: dashboardValues },
    });
    const user = userEvent.setup();
    renderApp("/dashboard");
    await screen.findByRole("heading", { name: "Latest certified figures" });

    const toggle = screen.getAllByRole("button", {
      name: copy.disclosure.what,
    })[0];
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(copy.dashboard.intro)).toBeVisible();

    // Closing puts it back — the panel is genuinely hidden, not merely
    // invisible, so it leaves the tab order with it.
    await user.click(toggle);
    expect(screen.getByText(copy.dashboard.intro)).not.toBeVisible();
  });

  it("/map — the staleness note, the ops boundary, the schematic note and the one-line summary are VISIBLE with nothing expanded", async () => {
    signInAs("viewer");
    mockApi(mapRoutes());
    renderApp("/map");
    await screen.findByRole("heading", { name: "Live map" });

    expectEverythingFolded();

    // The always-visible one-liner that replaced the wall of prose.
    expect(screen.getByText(copy.map.summary)).toBeVisible();
    // The server's own staleness note, verbatim — the feed has gone quiet.
    expect(await screen.findByText(STALE_NOTE)).toBeVisible();
    // The staleness CHIP itself.
    expect(
      screen.getByText(copy.map.chip.quiet("15 h 19 min")),
    ).toBeVisible();
    // What to do about a quiet feed — an admission, not an explanation.
    expect(screen.getByText(copy.map.empty.vehiclesAction)).toBeVisible();
    // The operations boundary: badge + the server's note.
    expect(screen.getByText(copy.ops.badge)).toBeVisible();
    expect(screen.getAllByText(OPS_NOTE)[0]).toBeVisible();
    // The cadence: how old what you are looking at can be.
    expect(screen.getByText(copy.map.pollNote)).toBeVisible();
    // The schematic-geometry limitation, in the server's own words.
    expect(screen.getByText(new RegExp(GEOMETRY_NOTE))).toBeVisible();
    // A flag anchored to a route line means nothing about WHERE it is.
    expect(screen.getByText(copy.map.findings.legendNote)).toBeVisible();

    // The explanation of the page and of its controls is folded, verbatim.
    expect(screen.getByText(copy.map.intro)).not.toBeVisible();
    expect(screen.getByText(copy.map.window.note)).not.toBeVisible();
  });

  it("/map — 'How these controls work' opens onto the full control explanations, unshortened", async () => {
    signInAs("viewer");
    mockApi(mapRoutes());
    const user = userEvent.setup();
    renderApp("/map");
    await screen.findByRole("heading", { name: "Live map" });

    const toggle = screen.getByRole("button", {
      name: copy.map.controls.explain,
    });
    await user.click(toggle);
    const panel = document.getElementById(
      toggle.getAttribute("aria-controls") ?? "",
    );
    expect(panel).not.toBeNull();
    expect(within(panel as HTMLElement).getByText(copy.map.intro)).toBeVisible();
    expect(
      within(panel as HTMLElement).getByText(copy.map.window.note),
    ).toBeVisible();
    expect(
      within(panel as HTMLElement).getByText(copy.map.modeFilter.note),
    ).toBeVisible();
  });
});
