import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import {
  simulatedUptValue,
  uptValue,
  vrmValue,
  vrmWithCoverage,
} from "./fixtures";
import { copy } from "../copy";
import { detailLines, isSimulated } from "../detail";
import { ratioToPercentString } from "../format";

describe("ratioToPercentString (string-only decimal shift)", () => {
  it("shifts the decimal point without ever parsing a number", () => {
    expect(ratioToPercentString("0.9126")).toBe("91.26");
    expect(ratioToPercentString("0.02")).toBe("2");
    expect(ratioToPercentString("0.10")).toBe("10");
    expect(ratioToPercentString("1.0000")).toBe("100");
    expect(ratioToPercentString("0.5")).toBe("50");
    expect(ratioToPercentString("0")).toBe("0");
    // A ratio too precise for a float round-trip survives verbatim.
    expect(ratioToPercentString("0.123456789012345678901")).toBe(
      "12.3456789012345678901",
    );
  });

  it("returns anything that is not a plain decimal unchanged", () => {
    expect(ratioToPercentString("n/a")).toBe("n/a");
    expect(ratioToPercentString("")).toBe("");
  });
});

describe("metrics detail panel", () => {
  it("renders the UPT row (plain-language unit) and translates UptDetail to plain language", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [uptValue] },
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    const table = await screen.findByRole("table");
    // Metric + unit in plain language; the figure verbatim.
    expect(
      within(table).getByText("Unlinked Passenger Trips (UPT)"),
    ).toBeInTheDocument();
    expect(
      within(table).getByText("unlinked passenger trips"),
    ).toBeInTheDocument();
    expect(within(table).getByText("41985.90")).toBeInTheDocument();

    // The detail toggle is labeled per figure and starts collapsed.
    const toggle = screen.getByRole("button", {
      name: /Details.*Unlinked Passenger Trips \(UPT\), 2026-03-01 to 2026-03-31/,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const panel = screen.getByRole("list", {
      name: "Calculation details for Unlinked Passenger Trips (UPT), 2026-03-01 to 2026-03-31",
    });
    // The FTA factor-up rule, in plain language, with the API's strings.
    expect(panel).toHaveTextContent(
      "Adjusted up ×1.010075 for 91 missing trips, as federal rules allow when 2% or fewer are missing.",
    );
    expect(panel).toHaveTextContent(
      "Passenger boardings counted from the data: 41567.",
    );
    expect(panel).toHaveTextContent("Trips operated in this period: 9123.");
    expect(panel).toHaveTextContent(
      "1% of operated trips had no passenger counts.",
    );
    expect(panel).toHaveTextContent(
      "Boarding and alighting counts are flagged for review when they differ by more than 10%.",
    );
    expect(panel).toHaveTextContent(
      "Where the data came from: tides (41567 events).",
    );

    await expectNoAxeViolations();
  });

  it("translates a vrm coverage detail: the coverage sentence and thresholds", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [vrmWithCoverage] },
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /^Details/ }));

    const panel = screen.getByRole("list", { name: /Calculation details/ });
    expect(panel).toHaveTextContent(
      "Covers 91.26% of vehicle-trips; 202 excluded and documented.",
    );
    expect(panel).toHaveTextContent(
      "Vehicle-trip groups in this period: 2313.",
    );
    expect(panel).toHaveTextContent(
      "97.31% of location reports belong to fully covered trips.",
    );
    expect(panel).toHaveTextContent(
      "A trip was set aside when its location reports had a gap longer than 300 seconds.",
    );
    expect(panel).toHaveTextContent(
      "This figure is only produced when coverage is at least 50%.",
    );
  });

  it("shows unknown detail keys raw-but-tidy instead of hiding them (forward-compatible)", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": {
        status: 200,
        body: [
          {
            ...vrmValue,
            detail: {
              coverage: "0.8000",
              excluded_groups: 3,
              apc_vendor_note: "spot-checked",
              new_threshold: 0.07,
            },
          },
        ],
      },
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /^Details/ }));
    const panel = screen.getByRole("list", { name: /Calculation details/ });
    expect(panel).toHaveTextContent("Covers 80% of vehicle-trips");
    expect(panel).toHaveTextContent("apc vendor note: spot-checked");
    expect(panel).toHaveTextContent("new threshold: 0.07");
  });

  it("offers no detail toggle when the API served an empty detail object", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [vrmValue] },
    });
    renderApp("/metrics");
    await screen.findByRole("table");
    expect(
      screen.queryByRole("button", { name: /^Details/ }),
    ).not.toBeInTheDocument();
  });
});

describe("SIMULATED DATA badge", () => {
  it("isSimulated flags any source_mix source containing 'simulated' and nothing else", () => {
    expect(isSimulated(simulatedUptValue.detail)).toBe(true);
    expect(isSimulated(uptValue.detail)).toBe(false);
    expect(isSimulated({})).toBe(false);
    expect(isSimulated(undefined)).toBe(false);
    expect(isSimulated({ source_mix: { SIMULATED_APC: 5 } })).toBe(true);
  });

  it("marks a simulated figure on the metrics view: text + icon + tooltip, axe-clean", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": {
        status: 200,
        body: [uptValue, simulatedUptValue],
      },
    });
    renderApp("/metrics");

    await screen.findByRole("table");
    // Exactly one badge: the real-sources figure carries none.
    const badges = screen.getAllByTitle(copy.simulated.tooltip);
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveTextContent("Simulated data");
    // The plain-language warning is exposed to screen readers too.
    expect(badges[0]).toHaveTextContent(
      "This number was computed from simulated test data. It must never be submitted.",
    );
    await expectNoAxeViolations();
  });

  it("spells out the source mix (including the simulated source) in the detail panel", () => {
    const lines = detailLines(simulatedUptValue.detail as Record<string, unknown>);
    expect(lines).toContain(
      "Where the data came from: tides (40000 events), tides_simulated (1567 events).",
    );
  });
});
