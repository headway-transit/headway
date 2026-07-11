/**
 * /dashboard (handoff 0008, pillar B): hero tiles verbatim, every chart type
 * renders from fixtures, table-view toggles, tooltip on hover and keyboard,
 * the structural no-dual-axis guarantee, and the axe gate.
 */

import { describe, expect, it } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import {
  blockingIssue,
  dashboardValues,
  resolvedIssue,
  warningIssue,
} from "./fixtures";
import { copy } from "../copy";
import {
  misalignedCount,
  overlapsRange,
  spansBucket,
} from "../reports/granularity";

function mockDashboard() {
  return mockApi({
    "GET /metrics/values": { status: 200, body: dashboardValues },
    "GET /dq/issues": {
      status: 200,
      body: [blockingIssue, warningIssue, resolvedIssue],
    },
  });
}

async function renderDashboard() {
  signInAs("viewer"); // any authenticated role
  mockDashboard();
  renderApp("/dashboard");
  expect(
    await screen.findByRole("heading", { name: "Dashboard" }),
  ).toBeInTheDocument();
}

describe("/dashboard", () => {
  it("renders hero tiles with the latest CERTIFIED figures verbatim, SimulatedBadge where flagged, and a provenance link on every tile", async () => {
    await renderDashboard();

    const tiles = screen.getByRole("region", {
      name: "Latest certified figures",
    });
    // Latest certified VRM/VRH are the February figures — verbatim, with
    // their trailing zeros/decimals intact.
    expect(within(tiles).getByText("11111.10")).toBeInTheDocument();
    expect(within(tiles).getByText("987.25")).toBeInTheDocument();
    // Latest certified UPT is the (simulated) March 3 daily figure.
    expect(within(tiles).getByText("1398.25")).toBeInTheDocument();

    // The simulated certified figure carries the badge; the others do not.
    const uptTile = within(tiles)
      .getByText("1398.25")
      .closest("li") as HTMLElement;
    expect(within(uptTile).getByText("Simulated data")).toBeInTheDocument();
    const vrmTile = within(tiles)
      .getByText("11111.10")
      .closest("li") as HTMLElement;
    expect(
      within(vrmTile).queryByText("Simulated data"),
    ).not.toBeInTheDocument();

    // Every displayed figure keeps its provenance path.
    expect(
      within(vrmTile).getByRole("link", {
        name: /How this number was made/,
      }),
    ).toHaveAttribute("href", "/metrics/mv-vrm-feb/lineage");
  });

  it("renders every chart type: UPT line, VRM/VRH small multiples, coverage with its threshold reference line, and DQ stacked bars with icon+label legend", async () => {
    await renderDashboard();

    // (2) UPT line: single series — the reader layer names the chart.
    expect(
      screen.getByRole("slider", {
        name: "Unlinked passenger trips over time",
      }),
    ).toBeInTheDocument();

    // (3) VRM & VRH as SMALL MULTIPLES: two separate panels, each its own
    // reader (its own plot, its own single axis).
    expect(
      screen.getByRole("slider", { name: "Vehicle Revenue Miles (VRM)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("slider", { name: "Vehicle Revenue Hours (VRH)" }),
    ).toBeInTheDocument();

    // (4) coverage over time: legend for the two series (≥2 series always
    // get a legend) and the dashed threshold reference line, labeled with
    // the string-shifted percent of the served "0.5".
    const coverageCard = screen
      .getByRole("heading", { name: "Data coverage over time" })
      .closest("section") as HTMLElement;
    expect(within(coverageCard).getByText("VRM coverage")).toBeInTheDocument();
    expect(within(coverageCard).getByText("VRH coverage")).toBeInTheDocument();
    expect(
      within(coverageCard).getByText("Coverage threshold (50%)"),
    ).toBeInTheDocument();
    expect(
      coverageCard.querySelector(".chart-ref-line"),
    ).not.toBeNull();

    // (5) DQ stacked bars: status colors reserved, icon + label legend,
    // per-segment accessible names with workflow tallies.
    const dqCard = screen
      .getByRole("heading", {
        name: "Unresolved data-quality issues by severity",
      })
      .closest("section") as HTMLElement;
    expect(
      within(dqCard).getByRole("img", { name: "Blocking: 1 open issue" }),
    ).toBeInTheDocument();
    expect(
      within(dqCard).getByRole("img", { name: "Warning: 1 owned issue" }),
    ).toBeInTheDocument();
    // Legend pairs each severity swatch with its icon and text label.
    const legend = dqCard.querySelector(".chart-legend") as HTMLElement;
    expect(legend).toHaveTextContent("Blocking");
    expect(legend).toHaveTextContent("Warning");
    expect(legend).toHaveTextContent("Info");
    expect(legend.querySelectorAll("svg").length).toBe(3);
  });

  it("NEVER draws a dual-axis chart: every svg carries at most one y-axis group", async () => {
    await renderDashboard();
    const svgs = document.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThan(0);
    for (const svg of svgs) {
      expect(
        svg.querySelectorAll('[data-axis="y"]').length,
      ).toBeLessThanOrEqual(1);
    }
  });

  it("toggles each chart to an accessible table view with verbatim figures and provenance links", async () => {
    const user = userEvent.setup();
    await renderDashboard();

    const uptCard = screen
      .getByRole("heading", { name: "Unlinked passenger trips over time" })
      .closest("section") as HTMLElement;
    await user.click(within(uptCard).getByRole("button", { name: "Table" }));

    const table = within(uptCard).getByRole("table");
    // Values verbatim — trailing zeros preserved, never reparsed.
    expect(within(table).getByText("1401.00")).toBeInTheDocument();
    expect(within(table).getByText("1250.50")).toBeInTheDocument();
    expect(within(table).getByText("1398.25")).toBeInTheDocument();
    // Every charted figure keeps its provenance path in the table view.
    expect(
      within(table).getAllByRole("link", { name: /How this number was made/ }),
    ).toHaveLength(3);

    // The DQ table view lists the tallies by status and severity.
    const dqCard = screen
      .getByRole("heading", {
        name: "Unresolved data-quality issues by severity",
      })
      .closest("section") as HTMLElement;
    await user.click(within(dqCard).getByRole("button", { name: "Table" }));
    const dqTable = within(dqCard).getByRole("table");
    expect(within(dqTable).getByRole("rowheader", { name: "Open" })).toBeInTheDocument();
    expect(within(dqTable).getByRole("rowheader", { name: "Owned" })).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("shows one tooltip with the verbatim value on hover, and the same readout on keyboard focus + arrows", async () => {
    await renderDashboard();

    const reader = screen.getByRole("slider", {
      name: "Unlinked passenger trips over time",
    });

    // Hover: the crosshair snaps to the nearest point (jsdom reports a
    // zero-width rect, so the layer snaps to the first point) and the
    // tooltip shows the figure verbatim.
    fireEvent.pointerMove(reader, { clientX: 0, clientY: 10 });
    const uptCard = reader.closest("section") as HTMLElement;
    const tooltip = uptCard.querySelector(".chart-tooltip") as HTMLElement;
    expect(tooltip).not.toBeNull();
    expect(tooltip).toHaveTextContent("1401.00 unlinked passenger trips");
    expect(tooltip).toHaveTextContent("2026-03-01");

    // Leaving hides it — the table view still carries every value.
    fireEvent.pointerLeave(reader);
    expect(uptCard.querySelector(".chart-tooltip")).toBeNull();

    // Keyboard: focus shows the same details; arrows walk the points and
    // the announced value text carries the verbatim figure.
    fireEvent.focus(reader);
    expect(reader).toHaveAttribute("aria-valuenow", "0");
    fireEvent.keyDown(reader, { key: "ArrowRight" });
    expect(reader).toHaveAttribute("aria-valuenow", "1");
    expect(reader.getAttribute("aria-valuetext")).toContain(
      "1250.50 unlinked passenger trips",
    );
    expect(
      uptCard.querySelector(".chart-tooltip") as HTMLElement,
    ).toHaveTextContent("1250.50 unlinked passenger trips");
  });

  it("filter row: date range first then a granularity aria-pressed group, keyboard operable; coarse granularities show the honest as-reported note and NEVER a client-side sum", async () => {
    const user = userEvent.setup();
    await renderDashboard();

    // ONE filter row above the charts; the date-range fields come first.
    const row = screen.getByRole("group", { name: "Filter the charts" });
    const fromInput = within(row).getByLabelText("From date");
    within(row).getByLabelText("To date");
    const granGroup = within(row).getByRole("group", {
      name: "Show periods as",
    });
    const controls = within(row).queryAllByRole("button");
    expect(
      fromInput.compareDocumentPosition(granGroup) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(controls.map((b) => b.textContent)).toEqual([
      "Hourly",
      "Daily",
      "Weekly",
      "Monthly",
      "Quarterly",
    ]);

    // Monthly is the default; state is conveyed by aria-pressed.
    expect(
      within(granGroup).getByRole("button", { name: "Monthly" }),
    ).toHaveAttribute("aria-pressed", "true");

    // Daily UPT rows under Monthly: the periods do not line up, so the card
    // says so — and shows every reported figure as-is.
    const uptCard = screen
      .getByRole("heading", { name: "Unlinked passenger trips over time" })
      .closest("section") as HTMLElement;
    expect(
      within(uptCard).getByText(
        copy.dashboard.filters.asReported("3", "Monthly"),
      ),
    ).toBeInTheDocument();
    // Monthly VRM/VRH rows line up with Monthly: no note.
    const serviceCard = screen
      .getByRole("heading", {
        name: "Vehicle revenue miles and hours over time",
      })
      .closest("section") as HTMLElement;
    expect(
      within(serviceCard).queryByText(/as reported/),
    ).not.toBeInTheDocument();

    // Keyboard path: the Quarterly toggle is focusable and operable.
    const quarterly = within(granGroup).getByRole("button", {
      name: "Quarterly",
    });
    quarterly.focus();
    await user.keyboard("{Enter}");
    expect(quarterly).toHaveAttribute("aria-pressed", "true");
    expect(
      within(granGroup).getByRole("button", { name: "Monthly" }),
    ).toHaveAttribute("aria-pressed", "false");

    // Monthly rows under Quarterly are coarser than the data: the honest
    // note appears — and NOTHING was summed. A client-side quarterly sum of
    // the daily UPT figures (1401.00 + 1250.50 + 1398.25) would be 4049.75;
    // that figure must exist NOWHERE, in any locale formatting.
    expect(
      within(serviceCard).getByText(
        copy.dashboard.filters.asReported("4", "Quarterly"),
      ),
    ).toBeInTheDocument();
    expect(
      within(uptCard).getByText(
        copy.dashboard.filters.asReported("3", "Quarterly"),
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/4049\.75/)).not.toBeInTheDocument();
    expect(screen.queryByText(/4,049\.75/)).not.toBeInTheDocument();
    // The verbatim figures are all still there (chart end label + table).
    await user.click(within(uptCard).getByRole("button", { name: "Table" }));
    expect(within(uptCard).getByText("1401.00")).toBeInTheDocument();
    expect(within(uptCard).getByText("1250.50")).toBeInTheDocument();
    expect(within(uptCard).getByText("1398.25")).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("filter changes NEVER recolor a series: every series keeps its hue across granularity and date-range changes", async () => {
    const user = userEvent.setup();
    await renderDashboard();

    const strokes = () =>
      [...document.querySelectorAll(".chart-series-line")].map((el) =>
        el.getAttribute("style"),
      );
    const before = strokes();
    expect(before.length).toBeGreaterThan(0);

    // Change granularity…
    await user.click(screen.getByRole("button", { name: "Weekly" }));
    expect(strokes()).toEqual(before);

    // …and narrow the date range (drops the February points but keeps every
    // series): survivors keep their hue — color follows the entity.
    fireEvent.change(screen.getByLabelText("From date"), {
      target: { value: "2026-03-01" },
    });
    expect(strokes()).toEqual(before);
  });

  it("the date range scopes every chart AND table below the row to the same slice, and the DQ card states what the range holds back", async () => {
    const user = userEvent.setup();
    await renderDashboard();

    fireEvent.change(screen.getByLabelText("From date"), {
      target: { value: "2026-03-02" },
    });
    fireEvent.change(screen.getByLabelText("To date"), {
      target: { value: "2026-03-04" },
    });

    // UPT table: the March 1 row is outside the slice; the others remain,
    // verbatim.
    const uptCard = screen
      .getByRole("heading", { name: "Unlinked passenger trips over time" })
      .closest("section") as HTMLElement;
    await user.click(within(uptCard).getByRole("button", { name: "Table" }));
    expect(within(uptCard).queryByText("1401.00")).not.toBeInTheDocument();
    expect(within(uptCard).getByText("1250.50")).toBeInTheDocument();
    expect(within(uptCard).getByText("1398.25")).toBeInTheDocument();

    // Service table: February rows are outside; March rows remain.
    const serviceCard = screen
      .getByRole("heading", {
        name: "Vehicle revenue miles and hours over time",
      })
      .closest("section") as HTMLElement;
    await user.click(
      within(serviceCard).getByRole("button", { name: "Table" }),
    );
    expect(within(serviceCard).queryByText("11111.10")).not.toBeInTheDocument();
    expect(within(serviceCard).getByText("12345.60")).toBeInTheDocument();

    // DQ card: the warning issue (created 2026-03-06) is outside the slice.
    // It is NOT silently gone — the held-back count is stated — and the
    // blocking issue inside the slice still shows.
    const dqCard = screen
      .getByRole("heading", {
        name: "Unresolved data-quality issues by severity",
      })
      .closest("section") as HTMLElement;
    expect(
      within(dqCard).getByRole("img", { name: "Blocking: 1 open issue" }),
    ).toBeInTheDocument();
    expect(
      within(dqCard).queryByRole("img", { name: "Warning: 1 owned issue" }),
    ).not.toBeInTheDocument();
    expect(dqCard).toHaveTextContent(
      copy.dashboard.filters.dqOutsideRange("1"),
    );

    await expectNoAxeViolations();
  });

  it("fails loudly when data cannot load, and passes axe in the default chart view", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: dashboardValues },
      "GET /dq/issues": {
        status: 503,
        body: { detail: "The data-quality service is unavailable." },
      },
    });
    renderApp("/dashboard");

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent("The data-quality service is unavailable.");

    await expectNoAxeViolations();
  });
});

describe("granularity bucketing (date math on period boundaries ONLY)", () => {
  it("spansBucket: a period counts as aligned only when it exactly spans a bucket", () => {
    // Daily: single-day periods only.
    expect(spansBucket("2026-03-01", "2026-03-01", "daily")).toBe(true);
    expect(spansBucket("2026-03-01", "2026-03-02", "daily")).toBe(false);
    // Weekly: ISO Monday..Sunday (2026-03-02 is a Monday).
    expect(spansBucket("2026-03-02", "2026-03-08", "weekly")).toBe(true);
    expect(spansBucket("2026-03-01", "2026-03-07", "weekly")).toBe(false);
    // Monthly: first..last calendar day, leap-year February included.
    expect(spansBucket("2026-02-01", "2026-02-28", "monthly")).toBe(true);
    expect(spansBucket("2024-02-01", "2024-02-29", "monthly")).toBe(true);
    expect(spansBucket("2026-03-01", "2026-03-30", "monthly")).toBe(false);
    // Quarterly: calendar quarters.
    expect(spansBucket("2026-01-01", "2026-03-31", "quarterly")).toBe(true);
    expect(spansBucket("2026-02-01", "2026-02-28", "quarterly")).toBe(false);
    // Hourly can never be spanned: the API's periods are whole dates.
    expect(spansBucket("2026-03-01", "2026-03-01", "hourly")).toBe(false);
  });

  it("misalignedCount and overlapsRange: selection math only, never figures", () => {
    const rows = [
      { period_start: "2026-03-01", period_end: "2026-03-01" },
      { period_start: "2026-03-01", period_end: "2026-03-31" },
    ];
    expect(misalignedCount(rows, "daily")).toBe(1);
    expect(misalignedCount(rows, "monthly")).toBe(1);
    // Empty bounds are unbounded; ISO strings compare as dates.
    expect(overlapsRange("2026-03-01", "2026-03-31", "", "")).toBe(true);
    expect(overlapsRange("2026-03-01", "2026-03-31", "2026-03-31", "")).toBe(true);
    expect(overlapsRange("2026-03-01", "2026-03-31", "2026-04-01", "")).toBe(false);
    expect(overlapsRange("2026-03-01", "2026-03-31", "", "2026-02-28")).toBe(false);
  });
});
