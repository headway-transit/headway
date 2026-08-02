/**
 * THE PROVENANCE TERMINAL (handoff 0044, output 4).
 *
 * The study's most alive element is also the easiest thing in this product
 * to make dishonest: a stream that ticks looks like a working platform
 * whether or not anything happened. So the rules are pinned here.
 *
 *   1. EVERY ROW IS A REAL RECORDED EVENT — each one traceable to a
 *      calculation-run row or a data-quality finding the API served, with
 *      that record's own timestamp. The row count equals the record count;
 *      there is no filler.
 *   2. NOTHING ON RECORD SAYS SO — the empty state is the honest state,
 *      never an invented tick.
 *   3. IT NEVER GRADES A FIGURE — a computed figure takes the neutral rail;
 *      ok/watch/alert appear only where the platform assigned a severity,
 *      and the identity accent marks Headway's own refusals.
 *   4. THE CADENCE IS STATED — v0 polls existing endpoints and says so.
 *   5. A FAILURE TO READ THE RECORD IS SAID, not drawn as an empty stream.
 */

import { describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { expectNoAxeViolations, mockApi, renderApp, signInAs } from "./helpers";
import type { RouteHandler } from "./helpers";
import { copy } from "../copy";
import { TERMINAL_POLL_MS } from "../components/ProvenanceTerminal";
import { blockingIssue } from "./fixtures";

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

const emptyGeometry = {
  type: "FeatureCollection",
  features: [],
  category: "ops",
  ops_note: "Operations data — not an NTD reported figure.",
  cap: 5000,
  truncated: false,
  note: null,
};

const vehiclesEmpty = {
  as_of: "2026-08-02T06:00:00Z",
  max_age_seconds: 300,
  category: "ops",
  ops_note: "Operations data — not an NTD reported figure.",
  vehicles: [],
  vehicle_count: 0,
  total_in_window: 0,
  cap: 5000,
  truncated: false,
  newest_position_at: null,
  note: null,
};

/** A run that computed one figure and REFUSED another, exactly as the
 *  runner reports it (calc_runs.summary). */
const runRecord = {
  run_id: "run-77",
  requested_by: "maria.ops",
  requested_at: "2026-08-02T05:58:00Z",
  period_start: "2026-07-01",
  period_end: "2026-08-01",
  status: "refused",
  started_at: "2026-08-02T05:58:02Z",
  finished_at: "2026-08-02T05:59:41Z",
  runner_pid: 4242,
  duration_seconds: 99,
  stale: false,
  stale_note: null,
  stdout_tail: null,
  summary: {
    runner: "headway_calc.runner",
    period_start: "2026-07-01",
    period_end: "2026-08-01",
    persisted_count: 1,
    blocked_count: 1,
    metrics: [
      {
        calc_name: "vrm_v1",
        calc_version: "1.0.0",
        metric: "vrm",
        unit: "miles",
        scope: "agency",
        outcome: "persisted",
        value: "9317.64",
        metric_value_id: "mv-vrm-77",
        coverage: "0.981",
        blocking_issue_ids: [],
        warning_issue_ids: [],
        info_issue_ids: [],
      },
      {
        calc_name: "upt_v1",
        calc_version: "1.0.0",
        metric: "upt",
        unit: "unlinked_passenger_trips",
        scope: "agency",
        outcome: "refused",
        value: null,
        metric_value_id: null,
        coverage: null,
        blocking_issue_ids: ["dq-1", "dq-2"],
        warning_issue_ids: [],
        info_issue_ids: [],
      },
    ],
  },
};

function mapShell(extra: Record<string, RouteHandler>) {
  return mockApi({
    "GET /geometry/stops": { status: 200, body: emptyGeometry },
    "GET /geometry/routes": { status: 200, body: emptyGeometry },
    "GET /ops/vehicles/latest": { status: 200, body: vehiclesEmpty },
    ...extra,
  });
}

/** The stream's rows, in document order. */
function rows(): HTMLElement[] {
  const terminal = screen.getByRole("region", {
    name: copy.terminal.heading,
  });
  return Array.from(terminal.querySelectorAll("li.term-row"));
}

describe("the provenance terminal (handoff 0044)", () => {
  it("says NOTHING IS ON RECORD rather than inventing activity, and still states its cadence", async () => {
    signInAs("viewer");
    mapShell({
      "GET /calc/runs": { status: 200, body: [] },
      "GET /dq/issues": {
        status: 200,
        body: {
          issues: [],
          total: 0,
          limit: 12,
          next_cursor: null,
          has_more: false,
        },
      },
    });
    renderApp("/map");

    const terminal = await screen.findByRole("region", {
      name: copy.terminal.heading,
    });
    expect(await within(terminal).findByText(copy.terminal.empty)).toBeVisible();
    // Not one row: no decorative tick has ever been emitted here.
    expect(rows()).toHaveLength(0);
    // The cadence is labelled, and it is the real one.
    expect(
      within(terminal).getByText(
        copy.terminal.cadence(String(TERMINAL_POLL_MS / 1000)),
      ),
    ).toBeVisible();
    expect(within(terminal).getByText(copy.terminal.sources)).toBeVisible();

    await expectNoAxeViolations();
  });

  it("streams REAL events only: one row per record the API served, newest first, each with the record's own timestamp", async () => {
    signInAs("viewer");
    mapShell({
      "GET /calc/runs": { status: 200, body: [runRecord] },
      "GET /dq/issues": {
        status: 200,
        body: {
          issues: [blockingIssue],
          total: 1,
          limit: 12,
          next_cursor: null,
          has_more: false,
        },
      },
    });
    renderApp("/map");
    const terminal = await screen.findByRole("region", {
      name: copy.terminal.heading,
    });

    // 4 records → 4 rows: the run, its two figure outcomes, and the
    // finding. Nothing else appears, ever.
    await within(terminal).findByText(
      copy.terminal.rows.figureComputed(
        "Vehicle Revenue Miles (VRM)",
        "agency",
        "9317.64 miles",
      ),
    );
    expect(rows()).toHaveLength(4);

    // The refusal: Headway declining to produce a figure, with the count of
    // findings that blocked it — and the identity-accent rail, which is
    // NON-SEMANTIC (a refusal is the product working, not bad news).
    const refusal = within(terminal).getByText(
      copy.terminal.rows.figureRefused(
        "Unlinked Passenger Trips (UPT)",
        "agency",
        "2",
      ),
    );
    expect(refusal.closest("li")).toHaveClass("term-sig");
    expect(
      within(refusal.closest("li") as HTMLElement).getByText(
        copy.terminal.tags.refused,
      ),
    ).toBeVisible();

    // A computed figure takes the NEUTRAL rail — the terminal never says a
    // figure is good.
    const computed = within(terminal).getByText(
      copy.terminal.rows.figureComputed(
        "Vehicle Revenue Miles (VRM)",
        "agency",
        "9317.64 miles",
      ),
    );
    expect(computed.closest("li")).toHaveClass("term-note");
    expect(computed.closest("li")).not.toHaveClass("term-alert");

    // The finding: the severity is the PLATFORM's, echoed as an alert rail
    // and stated in words beside it.
    const finding = within(terminal).getByText(
      copy.terminal.rows.findingRaised(
        copy.dq.severityLabels.blocking,
        blockingIssue.title,
      ),
    );
    expect(finding.closest("li")).toHaveClass("term-alert");

    // Every timestamp is the RECORD's own, never generated here.
    const times = Array.from(
      terminal.querySelectorAll("li.term-row time"),
    ).map((t) => t.getAttribute("datetime"));
    expect(new Set(times)).toEqual(
      new Set([runRecord.finished_at, blockingIssue.created_at]),
    );

    // Newest first.
    const order = Array.from(
      terminal.querySelectorAll("li.term-row time"),
    ).map((t) => t.getAttribute("datetime") ?? "");
    expect([...order].sort().reverse()).toEqual(order);

    // The cap on what is shown is STATED, never a silent truncation.
    expect(within(terminal).getByText(/The newest \d+ events are shown/)).
      toBeVisible();

    await expectNoAxeViolations();
  });

  it("says the event record could not be read rather than drawing an empty stream", async () => {
    signInAs("viewer");
    mapShell({
      "GET /calc/runs": {
        status: 500,
        body: { detail: "The calculation-run record is unavailable." },
      },
      "GET /dq/issues": {
        status: 200,
        body: {
          issues: [],
          total: 0,
          limit: 12,
          next_cursor: null,
          has_more: false,
        },
      },
    });
    renderApp("/map");
    const terminal = await screen.findByRole("region", {
      name: copy.terminal.heading,
    });
    expect(
      await within(terminal).findByText(/The event record could not be read/),
    ).toBeVisible();
    expect(rows()).toHaveLength(0);
    // The empty state must NOT stand in for a failure — silence and
    // "we could not look" are different sentences.
    expect(
      within(terminal).queryByText(copy.terminal.empty),
    ).not.toBeInTheDocument();
  });
});
