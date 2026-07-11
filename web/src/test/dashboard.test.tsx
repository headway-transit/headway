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
