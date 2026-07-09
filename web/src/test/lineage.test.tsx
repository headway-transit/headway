import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import { lineageTree } from "./fixtures";

describe("/metrics/:id/lineage", () => {
  function mockLineage() {
    return mockApi({
      "GET /metrics/values/mv-vrm-1/lineage": {
        status: 200,
        body: lineageTree,
      },
    });
  }

  it("renders the provenance tree as nested lists down to the raw records", async () => {
    signInAs("viewer");
    mockLineage();
    renderApp("/metrics/mv-vrm-1/lineage");

    expect(
      await screen.findByRole("heading", { name: "How this number was made" }),
    ).toBeInTheDocument();

    // Root: the reported figure, with the calc that produced it and version.
    expect(screen.getByText("Reported figure")).toBeInTheDocument();
    expect(screen.getByText("made by vrm_v0 (version 0.1.0)")).toBeInTheDocument();

    // Intermediate nodes with their transform + version.
    expect(screen.getAllByText("Cleaned vehicle position")).toHaveLength(2);
    expect(
      screen.getAllByText("made by gtfsrt_normalizer (version 0.2.0)"),
    ).toHaveLength(2);

    // Leaves: content-addressed raw records, labeled as the end of the trail.
    expect(screen.getByText("sha256:aaaa1111")).toBeInTheDocument();
    expect(screen.getByText("sha256:bbbb2222")).toBeInTheDocument();
    expect(
      screen.getAllByText("raw source record as received — the end of the trail"),
    ).toHaveLength(2);

    // Structure is genuinely nested lists (root > canonical > raw).
    const rootItem = screen
      .getByText("Reported figure")
      .closest("li") as HTMLElement;
    const nested = within(rootItem).getAllByRole("list");
    expect(nested.length).toBeGreaterThanOrEqual(3); // 1 inputs list + 2 leaf lists

    await expectNoAxeViolations();
  });

  it("collapses and expands a node by keyboard via its aria-expanded toggle", async () => {
    signInAs("viewer");
    mockLineage();
    const user = userEvent.setup();
    renderApp("/metrics/mv-vrm-1/lineage");

    const rootToggle = await screen.findByRole("button", {
      name: "Inputs of Reported figure mv-vrm-1",
    });
    expect(rootToggle).toHaveAttribute("aria-expanded", "true");

    rootToggle.focus();
    await user.keyboard("{Enter}");
    expect(rootToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("sha256:aaaa1111")).not.toBeInTheDocument();

    await user.keyboard("{Enter}");
    expect(rootToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("sha256:aaaa1111")).toBeInTheDocument();
  });

  it("surfaces a lineage API error verbatim", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values/mv-vrm-1/lineage": {
        status: 404,
        body: { detail: "No metric value with that id exists." },
      },
    });
    renderApp("/metrics/mv-vrm-1/lineage");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No metric value with that id exists.",
    );
  });
});
