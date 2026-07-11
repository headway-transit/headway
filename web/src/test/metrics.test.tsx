import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import { certifiedValue, vrhValue, vrmValue } from "./fixtures";

function mockMetrics() {
  return mockApi({
    "GET /metrics/values": {
      status: 200,
      body: [certifiedValue, vrmValue, vrhValue],
    },
  });
}

describe("/metrics", () => {
  it("renders API values verbatim as strings, with lineage links and the pre-verification banner", async () => {
    signInAs("viewer");
    mockMetrics();
    renderApp("/metrics");

    const table = await screen.findByRole("table");
    // The figure is the exact string the API served — including the trailing
    // zero a number round-trip would destroy.
    expect(within(table).getByText("12345.60")).toBeInTheDocument();
    expect(within(table).getByText("987.25")).toBeInTheDocument();

    // Every figure links to its provenance.
    const lineageLinks = within(table).getAllByRole("link", {
      name: /How this number was made/,
    });
    expect(lineageLinks).toHaveLength(3);
    expect(lineageLinks[1]).toHaveAttribute(
      "href",
      "/metrics/mv-vrm-1/lineage",
    );

    // Plain-language pre-verification banner and per-row tag.
    expect(
      screen.getByText(/early calculation that has not yet been checked/),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Pre-verification").length).toBeGreaterThan(0);

    await expectNoAxeViolations();
  });

  it("holds no inline certify flow: the certifying official gets a plain note pointing to /certify", async () => {
    signInAs("certifying_official");
    mockMetrics();
    renderApp("/metrics");

    await screen.findByRole("table");
    // The flow moved to the cockpit — no selection or certify action here.
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Certify selected figures" }),
    ).not.toBeInTheDocument();

    // The plain redirect note, with its link to the cockpit.
    expect(
      screen.getByText(/Certification has moved to its own room/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Go to the Certify page" }),
    ).toHaveAttribute("href", "/certify");

    await expectNoAxeViolations();
  });

  it("does not show the certify note (or any certify control) to other roles", async () => {
    signInAs("report_preparer");
    mockMetrics();
    renderApp("/metrics");

    await screen.findByRole("table");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Certification has moved to its own room/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Go to the Certify page" }),
    ).not.toBeInTheDocument();
  });
});
