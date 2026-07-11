import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import { lineageTree, lineageTreeLarge } from "./fixtures";

describe("/metrics/:id/lineage", () => {
  function mockLineage(body = lineageTree) {
    return mockApi({
      "GET /metrics/values/mv-vrm-1/lineage": {
        status: 200,
        body,
      },
    });
  }

  async function switchToTextView() {
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Text view" }),
    );
    return user;
  }

  it("defaults to the graph view with the text toggle always visible", async () => {
    signInAs("viewer");
    mockLineage();
    renderApp("/metrics/mv-vrm-1/lineage");

    expect(
      await screen.findByRole("group", {
        name: "Lineage graph: from the reported figure to its raw records",
      }),
    ).toBeInTheDocument();
    // Both view buttons are visible; the graph is pressed.
    expect(screen.getByRole("button", { name: "Graph view" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Text view" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await expectNoAxeViolations();
  });

  it("graph: three tiers with accessible names; the raw tier starts collapsed as a count node", async () => {
    signInAs("viewer");
    mockLineage(lineageTreeLarge);
    renderApp("/metrics/mv-vrm-1/lineage");

    const graph = await screen.findByRole("group", {
      name: /Lineage graph/,
    });
    // Tier 1: the reported figure.
    expect(
      within(graph).getByRole("img", { name: "Reported figure mv-vrm-1" }),
    ).toBeInTheDocument();
    // Tier 2: every distinct processing step, with version and count.
    expect(
      within(graph).getByRole("img", {
        name: "Processing step vrm_v0, version 0.1.0 — produced 1 record in this trail",
      }),
    ).toBeInTheDocument();
    expect(
      within(graph).getByRole("img", {
        name: "Processing step gtfsrt_normalizer, version 0.2.0 — produced 26 records in this trail",
      }),
    ).toBeInTheDocument();
    // Tier 3: collapsed to the count node — no raw record is drawn yet.
    const rawGroup = within(graph).getByRole("button", {
      name: /26 raw records/,
    });
    expect(rawGroup).toHaveAttribute("aria-expanded", "false");
    expect(
      within(graph).queryByRole("img", { name: /Raw source record/ }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("graph keyboard path: arrows walk the tiers, Enter expands the raw group in pages of 20, focus stays visible in the graph", async () => {
    signInAs("viewer");
    mockLineage(lineageTreeLarge);
    const user = userEvent.setup();
    renderApp("/metrics/mv-vrm-1/lineage");

    const graph = await screen.findByRole("group", { name: /Lineage graph/ });
    const metricNode = within(graph).getByRole("img", {
      name: "Reported figure mv-vrm-1",
    });
    // The metric node owns the roving tabindex initially.
    expect(metricNode).toHaveAttribute("tabindex", "0");
    metricNode.focus();
    expect(metricNode).toHaveFocus();

    // ArrowRight: metric tier → transform tier.
    await user.keyboard("{ArrowRight}");
    const firstTransform = within(graph).getByRole("img", {
      name: /Processing step vrm_v0/,
    });
    expect(firstTransform).toHaveFocus();

    // ArrowDown within the transform tier.
    await user.keyboard("{ArrowDown}");
    expect(
      within(graph).getByRole("img", {
        name: /Processing step gtfsrt_normalizer/,
      }),
    ).toHaveFocus();

    // ArrowRight: transform tier → raw tier (row clamps to the count node).
    await user.keyboard("{ArrowRight}");
    const rawGroup = within(graph).getByRole("button", {
      name: /26 raw records/,
    });
    expect(rawGroup).toHaveFocus();
    expect(rawGroup).toHaveAttribute("aria-expanded", "false");

    // Enter expands: the first PAGE of 20 raw records, plus "show more".
    await user.keyboard("{Enter}");
    expect(rawGroup).toHaveAttribute("aria-expanded", "true");
    expect(
      within(graph).getAllByRole("img", { name: /Raw source record/ }),
    ).toHaveLength(20);
    expect(
      within(graph).getByRole("img", {
        name: "Raw source record sha256:raw0000",
      }),
    ).toBeInTheDocument();
    const showMore = within(graph).getByRole("button", {
      name: "Showing 20 of 26 raw records. Show 20 more",
    });

    // Walk down to a raw record: full id in the accessible name.
    await user.keyboard("{ArrowDown}");
    expect(
      within(graph).getByRole("img", {
        name: "Raw source record sha256:raw0000",
      }),
    ).toHaveFocus();

    // Activate "show more" (click = same activation path): all 26 shown.
    await user.click(showMore);
    expect(
      within(graph).getAllByRole("img", { name: /Raw source record/ }),
    ).toHaveLength(26);
    expect(
      within(graph).queryByRole("button", { name: /Show 20 more/ }),
    ).not.toBeInTheDocument();

    // Enter on the count node again collapses the tier.
    rawGroup.focus();
    await user.keyboard("{Enter}");
    expect(rawGroup).toHaveAttribute("aria-expanded", "false");
    expect(
      within(graph).queryByRole("img", { name: /Raw source record/ }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("text view: renders the provenance tree as nested lists down to the raw records (fully equivalent path)", async () => {
    signInAs("viewer");
    mockLineage();
    renderApp("/metrics/mv-vrm-1/lineage");

    expect(
      await screen.findByRole("heading", { name: "How this number was made" }),
    ).toBeInTheDocument();
    await switchToTextView();

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

    // The graph is gone; toggling back restores it.
    expect(screen.queryByRole("group", { name: /Lineage graph/ })).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("text view: collapses and expands a node by keyboard via its aria-expanded toggle", async () => {
    signInAs("viewer");
    mockLineage();
    renderApp("/metrics/mv-vrm-1/lineage");
    await screen.findByRole("heading", { name: "How this number was made" });
    const user = await switchToTextView();

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
