/**
 * The dashboard Mode selector (handoff 0041, design points 1–4).
 *
 * Pins the binding rules:
 *   - DATA-DRIVEN: the options are the distinct `mode:*` scopes that
 *     actually carry persisted figures — never a hardcoded mode list, and
 *     never a mode that could only ever show zero;
 *   - RE-SCOPE, NEVER DERIVE: a mode shows that mode's own stored rows
 *     VERBATIM with their own metric_value_id receipts, and no figure on
 *     the page is ever a sum/average/difference of the modes;
 *   - INVITING EMPTY STATES: a mode with nothing computed says so warmly
 *     and says why — a fabricated zero appears nowhere;
 *   - surfaces with NO mode dimension (operations metrics are per route, DQ
 *     tallies count issues) say they are not narrowed instead of quietly
 *     showing agency numbers under a mode heading.
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
import type { MetricValue } from "../api/types";
import {
  blockingIssue,
  dashboardModeValues,
  dashboardValues,
  dqCountsFor,
  warningIssue,
  vrmValue,
} from "./fixtures";
import { copy } from "../copy";
import {
  MODE_SEGMENT_MAX,
  modeOptions,
  modeScopeLabel,
  rowInScope,
  selectedModeLabel,
} from "../reports/modes";

function mockDashboardWith(values: MetricValue[]) {
  const issues = [blockingIssue, warningIssue];
  return mockApi({
    "GET /metrics/values": { status: 200, body: values },
    "GET /dq/issues/counts": (call) => {
      const status = new URL(call.url, "http://test").searchParams.get(
        "status",
      );
      return { status: 200, body: dqCountsFor(issues, status) };
    },
  });
}

async function renderDashboardWith(values: MetricValue[]) {
  signInAs("viewer");
  const calls = mockDashboardWith(values);
  renderApp("/dashboard");
  expect(
    await screen.findByRole("heading", { name: "Dashboard" }),
  ).toBeInTheDocument();
  return calls;
}

const WITH_MODES = [...dashboardValues, ...dashboardModeValues];

describe("mode scope vocabulary (src/reports/modes.ts)", () => {
  it("derives the options from the served scopes — never from a list in the code", () => {
    // Nothing but 'agency' present: no mode is offered at all. A hardcoded
    // catalogue would have offered Bus/Vanpool/Via here, forever empty.
    expect(modeOptions(dashboardValues)).toEqual([]);

    const options = modeOptions(WITH_MODES);
    expect(options.map((o) => o.scope).sort()).toEqual([
      "mode:DR",
      "mode:bus",
      "mode:subway",
    ]);
  });

  it("labels a scope by lookup and falls back to the raw code, honestly", () => {
    expect(modeScopeLabel("mode:bus")).toBe("Bus");
    expect(modeScopeLabel("mode:DR")).toBe("Demand response (DR)");
    expect(modeScopeLabel("mode:DR:tos:TX")).toBe(
      "Demand response (DR) — Taxi (TX)",
    );
    // The calc library's NULL-mode bucket is named, not hidden.
    expect(modeScopeLabel("mode:unknown")).toBe("Mode not identified");
    // An unrecognised code is shown as itself — never guessed at.
    expect(modeScopeLabel("mode:hyperloop")).toBe("hyperloop");
    expect(selectedModeLabel("agency")).toBe("All modes (agency)");
  });

  it("rowInScope is EXACT-MATCH selection — a TOS scope never folds into its mode", () => {
    expect(rowInScope("agency", "agency")).toBe(true);
    expect(rowInScope("fleet", "agency")).toBe(true);
    expect(rowInScope("mode:bus", "agency")).toBe(false);
    expect(rowInScope("mode:bus", "mode:bus")).toBe(true);
    // Folding mode:DR:tos:DO into mode:DR would need arithmetic nobody did.
    expect(rowInScope("mode:DR:tos:DO", "mode:DR")).toBe(false);
    expect(rowInScope("agency", "mode:bus")).toBe(false);
  });
});

describe("/dashboard mode selector", () => {
  it("offers only the modes that have persisted figures, plus the agency default — and says so", async () => {
    await renderDashboardWith(WITH_MODES);

    const modeBar = screen.getByRole("region", { name: "Mode" });
    const group = within(modeBar).getByRole("group", { name: "Mode" });
    expect(
      within(group)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual([
      "All modes (agency)",
      "Bus",
      "Demand response (DR)",
      "Subway or metro",
    ]);
    // The default is the persisted agency rollup — never a client-side sum.
    expect(
      within(group).getByRole("button", { name: "All modes (agency)" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(modeBar).toHaveTextContent(copy.dashboard.mode.agencyNote);
    expect(modeBar).toHaveTextContent(copy.dashboard.mode.dataDrivenNote);
    // The scope receipt: what the rows below were filtered on, verbatim.
    expect(modeBar).toHaveTextContent("Figure scope: agency");
  });

  it("shows NO mode selector options when nothing is scoped by mode", async () => {
    await renderDashboardWith(dashboardValues);
    const group = within(
      screen.getByRole("region", { name: "Mode" }),
    ).getByRole("group", { name: "Mode" });
    expect(
      within(group)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["All modes (agency)"]);
  });

  it("RE-SCOPES to the mode's own stored rows, verbatim and with their own receipts — it never derives a per-mode figure", async () => {
    const user = userEvent.setup();
    await renderDashboardWith(WITH_MODES);

    // Agency first: the agency VRM figure is on its tile with its receipt.
    const tiles = () =>
      screen.getByRole("region", { name: /Latest certified figures/ });
    expect(within(tiles()).getByText("11111.10")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Bus" }));

    // The tiles now carry the BUS rows, verbatim, each with its own
    // provenance path; the agency figures are gone (not folded in).
    const busTiles = tiles();
    expect(within(busTiles).getByText("8888.80")).toBeInTheDocument();
    expect(within(busTiles).getByText("701.05")).toBeInTheDocument();
    expect(within(busTiles).getByText("900.00")).toBeInTheDocument();
    expect(within(busTiles).queryByText("11111.10")).not.toBeInTheDocument();
    const vrmTile = within(busTiles)
      .getByText("8888.80")
      .closest("li") as HTMLElement;
    expect(
      within(vrmTile).getByRole("link", { name: /How this number was made/ }),
    ).toHaveAttribute("href", "/metrics/mv-vrm-bus-mar/lineage");
    // The row's OWN scope is on the tile: a mode slice can never pass for
    // the agency rollup.
    expect(vrmTile).toHaveTextContent("Figure scope: mode:bus");

    // NOTHING on the page is a sum, a difference or an average of the
    // agency and mode figures. 11111.10 + 8888.80 = 19999.90;
    // 11111.10 - 8888.80 = 2222.30. Neither exists, in any formatting.
    for (const derived of [
      /19999\.90/,
      /19,999\.90/,
      /2222\.30/,
      /2,222\.30/,
    ]) {
      expect(screen.queryByText(derived)).not.toBeInTheDocument();
    }

    // The heading names the scope, so a mode view is never read as agency.
    expect(
      screen.getByRole("heading", {
        name: "Latest certified figures — Bus",
      }),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("re-scopes the charts and their table views to the mode's rows only", async () => {
    const user = userEvent.setup();
    await renderDashboardWith(WITH_MODES);
    await user.click(screen.getByRole("button", { name: "Bus" }));

    const serviceCard = screen
      .getByRole("heading", {
        name: "Vehicle revenue miles and hours over time",
      })
      .closest("section") as HTMLElement;
    await user.click(
      within(serviceCard).getByRole("button", { name: "Table" }),
    );
    const table = within(serviceCard).getByRole("table");
    expect(within(table).getByText("8888.80")).toBeInTheDocument();
    expect(within(table).getByText("701.05")).toBeInTheDocument();
    // Agency rows are NOT in the mode's table.
    expect(within(table).queryByText("12345.60")).not.toBeInTheDocument();
    expect(within(table).queryByText("11111.10")).not.toBeInTheDocument();
  });

  it("a mode with nothing in the selected dates gets an inviting, designed empty state — never a fabricated zero", async () => {
    const user = userEvent.setup();
    await renderDashboardWith(WITH_MODES);

    // Subway's only figure is a January one; the charts default to every
    // served period, so narrow the range to March first.
    await user.click(screen.getByRole("button", { name: "Subway or metro" }));
    const from = screen.getByLabelText("From date");
    await user.clear(from);
    await user.type(from, "2026-03-01");

    const label = "Subway or metro";
    const panel = screen.getByRole("region", {
      name: copy.dashboard.mode.emptyHeading(label),
    });
    expect(panel).toHaveTextContent(copy.dashboard.mode.emptyBody(label));
    expect(panel).toHaveTextContent(copy.dashboard.mode.emptyWiden);
    expect(panel).toHaveTextContent("Figure scope: mode:subway");
    // The charts are GONE rather than showing zeroes: no chart reader, and
    // no "0" standing in for a figure nobody computed.
    expect(
      screen.queryByRole("slider", {
        name: "Unlinked passenger trips over time",
      }),
    ).not.toBeInTheDocument();

    // FAIL LOUDLY: an empty mode must never hide an open blocking issue.
    // The data-quality card carries no mode dimension, so it rides along
    // — flagged frame and all.
    const dqCard = screen
      .getByRole("heading", {
        name: "Unresolved data-quality issues by severity",
      })
      .closest("section") as HTMLElement;
    expect(dqCard.className).toContain("attn-alert");
    expect(dqCard).toHaveTextContent(copy.dashboard.dq.blockingFlag("1"));

    await expectNoAxeViolations();
  });

  it("says out loud which surfaces are NOT narrowed by a mode (operations is per route; DQ counts issues)", async () => {
    const user = userEvent.setup();
    await renderDashboardWith(WITH_MODES);
    await user.click(screen.getByRole("button", { name: "Bus" }));

    const ops = screen.getByRole("region", { name: "Operations metrics" });
    expect(ops).toHaveTextContent(copy.dashboard.mode.opsNote("Bus"));

    const dqCard = screen
      .getByRole("heading", {
        name: "Unresolved data-quality issues by severity",
      })
      .closest("section") as HTMLElement;
    expect(dqCard).toHaveTextContent(copy.dashboard.mode.dqNote("Bus"));
  });

  it("re-scopes the trend request to the server: picking a mode asks for that scope", async () => {
    const user = userEvent.setup();
    const calls = await renderDashboardWith(WITH_MODES);
    await user.click(screen.getByRole("button", { name: "Bus" }));

    const scopes = calls
      .filter((c) => c.path === "/metrics/history")
      .map((c) => new URL(c.url, "http://test").searchParams.get("scope"));
    // The agency default asks for no scope (the fleet-wide rows, as before);
    // the mode selection asks the SERVER for that mode's persisted rows.
    expect(scopes).toContain(null);
    expect(scopes).toContain("mode:bus");
  });

  it("becomes a keyboard-operable dropdown once the mode count passes the segmented-control limit", async () => {
    const user = userEvent.setup();
    // MODE_SEGMENT_MAX + 1 modes: one more than the segmented control holds.
    const many: MetricValue[] = Array.from(
      { length: MODE_SEGMENT_MAX + 1 },
      (_, i) => ({
        ...vrmValue,
        metric_value_id: `mv-vrm-many-${i}`,
        scope: `mode:m${i}`,
        value: `${100 + i}.00`,
      }),
    );
    await renderDashboardWith([...dashboardValues, ...many]);

    const modeBar = screen.getByRole("region", { name: "Mode" });
    // The segmented group is gone; a labelled listbox button takes over.
    expect(
      within(modeBar).queryByRole("group", { name: "Mode" }),
    ).not.toBeInTheDocument();
    const trigger = within(modeBar).getByRole("button", { name: /Mode/ });
    expect(trigger).toHaveTextContent("All modes (agency)");

    // Keyboard: open the listbox and pick the third option.
    trigger.focus();
    await user.keyboard("{Enter}");
    const listbox = await screen.findByRole("listbox");
    const option = within(listbox).getByRole("option", { name: /m2/ });
    await user.click(option);
    expect(modeBar).toHaveTextContent("Figure scope: mode:m2");

    await expectNoAxeViolations();
  });
});
