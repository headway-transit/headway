/**
 * The Receipt (handoff 0007, pillar 1): five parts, in order — story,
 * coverage meter + exclusions, the verbatim FTA rule, flags, and the walk to
 * raw records. Numbers stay sacred: everything asserted here is the API's
 * string verbatim; the meter's aria-valuenow is the integer part of the
 * string-shifted percent, and its aria-valuetext is the verbatim string.
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
import {
  simulatedUptValue,
  uptValue,
  vrmValue,
  vrmWithCoverage,
} from "./fixtures";
import { copy } from "../copy";
import quotes from "../regulatory/quotes.json";

/** Asserts the given elements appear in DOM order. */
function expectInOrder(elements: Element[]) {
  for (let i = 0; i < elements.length - 1; i++) {
    expect(
      elements[i].compareDocumentPosition(elements[i + 1]) &
        Node.DOCUMENT_POSITION_FOLLOWING,
      `element ${i} must precede element ${i + 1}`,
    ).toBeTruthy();
  }
}

const REVENUE_SERVICE_QUOTE =
  "A transit vehicle is in revenue service when it is providing public transportation and is available to carry passengers. Non-public transportation activities, such as exclusive school bus service and charter service are not considered revenue service. Revenue service includes both fare and fare-free services.";

describe("Receipt", () => {
  it("renders all five parts in order for a coverage figure, with an accessible meter carrying string-derived aria values", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [vrmWithCoverage] },
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /^Details/ }));

    const receipt = screen.getByRole("region", {
      name: "Receipt for Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31",
    });

    // (a) the plain-language story: the figure verbatim (trailing zero kept).
    const story = within(receipt).getByText(
      "12345.60 miles — Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31.",
    );

    // (b) the coverage meter: aria-valuenow is the INTEGER PART of the
    // string-shifted percent (never a parsed float of the ratio), and
    // aria-valuetext is the verbatim percent string.
    const meter = within(receipt).getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "91");
    expect(meter).toHaveAttribute("aria-valuetext", "91.26%");
    expect(meter).toHaveAccessibleName(
      "Data coverage for Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31",
    );
    // The visible value is the verbatim string, not the meter integer.
    expect(within(receipt).getByText("91.26%")).toBeInTheDocument();

    // …with the exclusions stated in plain language.
    const exclusions = within(receipt).getByText(
      "Covers 91.26% of vehicle-trips; 202 excluded and documented.",
    );
    // …and the rest of the absorbed calculation detail.
    const detailList = within(receipt).getByRole("list", {
      name: "Calculation details for Vehicle Revenue Miles (VRM), 2026-03-01 to 2026-03-31",
    });
    expect(detailList).toHaveTextContent(
      "Vehicle-trip groups in this period: 2313.",
    );
    expect(detailList).toHaveTextContent(
      "This figure is only produced when coverage is at least 50%.",
    );

    // (c) the FTA rule inside the number: verbatim quotes + citations.
    const ruleHeading = within(receipt).getByRole("heading", {
      name: "The FTA rule inside this number",
    });
    expect(receipt.querySelectorAll("blockquote").length).toBe(
      quotes.vrm_v0.length,
    );
    const cites = receipt.querySelectorAll("cite");
    expect(cites[0]).toHaveTextContent(
      "Revenue Service — 2026 NTD Policy Manual, Full Reporting, p. 128",
    );

    // (d) flags: the 0.x calc carries the pre-verification flag + meaning.
    const flagsHeading = within(receipt).getByRole("heading", {
      name: "Flags on this figure",
    });
    expect(within(receipt).getByText("Pre-verification")).toBeInTheDocument();
    expect(
      within(receipt).getByText(
        "This number comes from an early calculation that has not yet been checked against FTA rules. It is not a certifiable figure yet.",
      ),
    ).toBeInTheDocument();

    // (e) the door onward.
    const walk = within(receipt).getByRole("link", {
      name: /Walk this number to its raw records/,
    });
    expect(walk).toHaveAttribute("href", "/metrics/mv-vrm-2/lineage");

    // The five parts appear in the pillar's order.
    expectInOrder([story, meter, exclusions, ruleHeading, flagsHeading, walk]);

    await expectNoAxeViolations();
  });

  it("renders the FTA quotes VERBATIM — the exact tracker sentence, blockquote + cite", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [vrmWithCoverage] },
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /^Details/ }));
    const receipt = screen.getByRole("region", { name: /^Receipt for/ });

    // Exact FTA sentence, character for character, inside a <blockquote>.
    const quoteText = within(receipt).getByText(REVENUE_SERVICE_QUOTE);
    expect(quoteText.closest("blockquote")).not.toBeNull();
    // And it is exactly what quotes.json ships (no re-wording in render).
    expect(
      quotes.vrm_v0.some((q) => q.quote === REVENUE_SERVICE_QUOTE),
    ).toBe(true);
    // The citation is the <cite> of the quote's <figure>.
    const cite = quoteText
      .closest("figure")
      ?.querySelector("figcaption cite");
    expect(cite).toHaveTextContent(
      "Revenue Service — 2026 NTD Policy Manual, Full Reporting, p. 128",
    );
  });

  it("shows the simulated flag with its meaning, states UPT coverage without a meter, and keeps every count verbatim", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [simulatedUptValue] },
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /^Details/ }));
    const receipt = screen.getByRole("region", { name: /^Receipt for/ });

    // Story with the verbatim figure.
    expect(
      within(receipt).getByText(
        "41985.90 unlinked passenger trips — Unlinked Passenger Trips (UPT), 2026-03-01 to 2026-03-31.",
      ),
    ).toBeInTheDocument();

    // UPT detail reports counted trips, not a coverage ratio: the exclusions
    // line states it and NO meter is invented (that would require arithmetic).
    expect(within(receipt).queryByRole("meter")).not.toBeInTheDocument();
    expect(
      within(receipt).getByText(
        "Passenger counts were recorded on 9032 of 9123 operated trips.",
      ),
    ).toBeInTheDocument();

    // The FTA factor-up rule detail line survives the absorption, verbatim.
    expect(
      within(receipt).getByRole("list", { name: /Calculation details/ }),
    ).toHaveTextContent(
      "Adjusted up ×1.010075 for 91 missing trips, as federal rules allow when 2% or fewer are missing.",
    );

    // The UPT rule section quotes the p. 143 definition verbatim.
    expect(
      within(receipt).getByText(/Unlinked Passenger Trips \(UPT\) are the number of boardings on public transportation vehicles during the fiscal year\./),
    ).toBeInTheDocument();

    // Flags: simulated (badge + meaning) AND pre-verification, side by side.
    expect(within(receipt).getByTitle(copy.simulated.tooltip)).toHaveTextContent(
      "Simulated data",
    );
    expect(within(receipt).getByText("Pre-verification")).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("states a missing FTA quote LOUDLY instead of shipping silence", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": {
        status: 200,
        body: [{ ...vrmValue, calc_name: "mystery_calc" }],
      },
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: /^Details/ }));
    const receipt = screen.getByRole("region", { name: /^Receipt for/ });
    expect(
      within(receipt).getByText(
        "No verified FTA quote is on file for the mystery_calc calculation. This figure cannot yet be traced to a verified federal definition — treat it as unverified.",
      ),
    ).toBeInTheDocument();
    expect(receipt.querySelector("blockquote")).toBeNull();
  });

  it("opens a Receipt even for a figure with no calculation detail — absences stated, never blank", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [uptValue, vrmValue] },
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    await screen.findByRole("table");
    // vrmValue has NO detail; its Details toggle still exists and opens.
    const toggles = screen.getAllByRole("button", { name: /^Details/ });
    expect(toggles).toHaveLength(2);
    await user.click(
      screen.getByRole("button", {
        name: /Details.*Vehicle Revenue Miles \(VRM\)/,
      }),
    );
    const receipt = screen.getByRole("region", {
      name: /^Receipt for Vehicle Revenue Miles/,
    });
    expect(
      within(receipt).getByText(
        "The calculation reported no coverage information for this figure.",
      ),
    ).toBeInTheDocument();
    expect(
      within(receipt).getByText(
        "The calculation recorded no extra detail for this figure.",
      ),
    ).toBeInTheDocument();
    // The rule and the walk are still present: no figure without its door.
    expect(receipt.querySelectorAll("blockquote").length).toBeGreaterThan(0);
    expect(
      within(receipt).getByRole("link", { name: /Walk this number/ }),
    ).toBeInTheDocument();
  });
});
