/**
 * Audience lenses + KPI sparklines (/dashboard — handoff 0024, design
 * point 2). Pins the binding rules:
 *   - a preset is a LENS CONFIGURATION: it changes the server bucket param
 *     and the section order, never a number (the intro says so, and the
 *     server's grouping_note renders verbatim);
 *   - sparkline points are PERSISTED figures verbatim, each a real button
 *     one click from its full Receipt;
 *   - a calendar bucket with no figure renders as a GAP, stated in words —
 *     never interpolated;
 *   - certification status on a point is shape + words, never color alone.
 */

import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import type { RouteHandler } from "./helpers";
import { dashboardValues } from "./fixtures";

/** Persisted vrm figures at agency scope across monthly buckets — with
 *  2026-05 MISSING (the gap the sparkline must draw as absence). */
function historyPoint(overrides: Record<string, unknown>) {
  return {
    metric_value_id: "mv-h-1",
    metric: "vrm",
    unit: "miles",
    period_start: "2026-04-01",
    period_end: "2026-04-30",
    scope: "agency",
    value: "100.10",
    calc_name: "vrm_v0",
    calc_version: "0.2.0",
    computed_at: "2026-05-01T06:00:00Z",
    certification_status: "uncertified",
    detail: {},
    category: "ntd",
    simulated: false,
    ...overrides,
  };
}

const GROUPING_NOTE =
  "Buckets group persisted figures by the calendar bucket their period starts in. The server never sums, averages, or otherwise derives a new number from grouped figures — every value is a calculation library figure served verbatim with its metric_value_id receipt. A true quarterly or annual rollup is a calculation library job, not this endpoint's.";

const historyWithGap: RouteHandler = (call) => {
  const bucket =
    new URL(call.url, "http://test").searchParams.get("bucket") ?? "month";
  return {
    status: 200,
    body: {
      bucket,
      metric: null,
      scope: null,
      calc_version: null,
      period_from: null,
      period_to: null,
      buckets: [
        { bucket_key: "2026-04", points: [historyPoint({})] },
        {
          bucket_key: "2026-06",
          points: [
            historyPoint({
              metric_value_id: "mv-h-2",
              period_start: "2026-06-01",
              period_end: "2026-06-30",
              value: "120.50",
              computed_at: "2026-07-01T06:00:00Z",
              certification_status: "certified",
            }),
          ],
        },
        {
          bucket_key: "2026-07",
          points: [
            historyPoint({
              metric_value_id: "mv-h-3",
              period_start: "2026-07-01",
              period_end: "2026-07-31",
              value: "160835.49",
              computed_at: "2026-08-01T06:00:00Z",
            }),
          ],
        },
      ],
      point_count: 3,
      total_matching: 3,
      cap: 5000,
      truncated: false,
      grouping_note: GROUPING_NOTE,
      note: null,
    },
  };
};

function mockLensDashboard() {
  return mockApi({
    "GET /metrics/values": { status: 200, body: dashboardValues },
    "GET /dq/issues": { status: 200, body: [] },
    "GET /metrics/history": historyWithGap,
  });
}

describe("/dashboard audience lenses", () => {
  it("defaults to the Executive lens (month), states that a lens reframes and never recomputes, and renders the server's grouping note verbatim", async () => {
    signInAs("viewer");
    const calls = mockLensDashboard();
    renderApp("/dashboard");

    const lensBar = await screen.findByRole("region", {
      name: "Audience lens",
    });
    expect(
      within(lensBar).getByRole("button", { name: "Executive" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(lensBar).getByRole("button", { name: "Month" }),
    ).toHaveAttribute("aria-pressed", "true");
    // Framing-only, in this page's words AND the server's.
    expect(lensBar).toHaveTextContent(
      "it changes the calendar grouping of the trend lines and the order of the sections, nothing else",
    );
    expect(await within(lensBar).findByText(new RegExp("never sums, averages"))).toBeInTheDocument();
    expect(lensBar).toHaveTextContent(GROUPING_NOTE);
    // The history request carried the bucket param — grouping is the
    // SERVER's, never client arithmetic.
    expect(
      calls.some(
        (c) =>
          c.path === "/metrics/history" &&
          new URL(c.url, "http://test").searchParams.get("bucket") === "month",
      ),
    ).toBe(true);
    await expectNoAxeViolations();
  });

  it("the Board preset is quarter grouping; pressing it refetches with bucket=quarter and shows its certified-figures framing", async () => {
    signInAs("viewer");
    const calls = mockLensDashboard();
    const user = userEvent.setup();
    renderApp("/dashboard");

    const lensBar = await screen.findByRole("region", {
      name: "Audience lens",
    });
    await user.click(within(lensBar).getByRole("button", { name: "Board" }));
    expect(
      within(lensBar).getByRole("button", { name: "Board" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(lensBar).getByRole("button", { name: "Quarter" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(lensBar).toHaveTextContent(
      "Board lens: trends grouped by quarter, certified figures leading.",
    );
    expect(
      calls.some(
        (c) =>
          c.path === "/metrics/history" &&
          new URL(c.url, "http://test").searchParams.get("bucket") ===
            "quarter",
      ),
    ).toBe(true);
  });

  it("hand-picking a bucket that disagrees with the pressed preset unpresses it — a preset never LOOKS active while its configuration is not", async () => {
    signInAs("viewer");
    mockLensDashboard();
    const user = userEvent.setup();
    renderApp("/dashboard");

    const lensBar = await screen.findByRole("region", {
      name: "Audience lens",
    });
    await user.click(within(lensBar).getByRole("button", { name: "Day" }));
    expect(
      within(lensBar).getByRole("button", { name: "Day" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(lensBar).getByRole("button", { name: "Executive" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("the Operations lens puts the ops section FORWARD (an order change only) — and day grouping", async () => {
    signInAs("viewer");
    mockLensDashboard();
    const user = userEvent.setup();
    renderApp("/dashboard");

    const lensBar = await screen.findByRole("region", {
      name: "Audience lens",
    });
    const domOrder = () => {
      const ops = screen.getByRole("heading", { name: "Operations metrics" });
      const charts = screen.getByRole("heading", {
        name: "Unlinked passenger trips over time",
      });
      return ops.compareDocumentPosition(charts) &
        Node.DOCUMENT_POSITION_FOLLOWING
        ? "ops-first"
        : "charts-first";
    };
    expect(domOrder()).toBe("charts-first");

    await user.click(
      within(lensBar).getByRole("button", { name: "Operations" }),
    );
    expect(domOrder()).toBe("ops-first");
    expect(
      within(lensBar).getByRole("button", { name: "Day" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(lensBar).toHaveTextContent(
      "Operations lens: trends grouped by day, operations cards first.",
    );
  });

  it("sparkline points are persisted figures VERBATIM — real buttons, status in words and shape, one click from the full Receipt — and a missing month is a stated gap", async () => {
    signInAs("viewer");
    mockLensDashboard();
    const user = userEvent.setup();
    renderApp("/dashboard");

    // The VRM tile's trend: three points from /metrics/history.
    const trend = await screen.findByRole("group", {
      name: /Trend of persisted Vehicle Revenue Miles/,
    });
    const point1 = within(trend).getByRole("button", {
      name: "100.10 miles, 2026-04-01 to 2026-04-30 (uncertified) — open the receipt",
    });
    const certifiedPoint = within(trend).getByRole("button", {
      name: "120.50 miles, 2026-06-01 to 2026-06-30 (certified) — open the receipt",
    });
    // Status is SHAPE (the certified class fills the marker) + words in
    // the accessible name — never color alone.
    expect(certifiedPoint.className).toContain("certified");
    expect(point1.className).not.toContain("certified");

    // THE GAP: 2026-05 holds no figure — visible absence, stated in words.
    expect(
      screen.getAllByText(
        "1 bucket in this range has no figure — drawn as a gap, never filled in.",
      ).length,
    ).toBeGreaterThan(0);

    // One click to the receipt: the house Receipt opens with the figure's
    // own story line (value + metric + period, verbatim).
    await user.click(point1);
    const receipt = await screen.findByRole("region", {
      name: /Receipt for Vehicle Revenue Miles/,
    });
    expect(receipt).toHaveTextContent("100.10 miles");
    await user.click(
      screen.getByRole("button", { name: "Close the receipt" }),
    );
    expect(
      screen.queryByRole("region", { name: /Receipt for Vehicle Revenue Miles/ }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });
});
