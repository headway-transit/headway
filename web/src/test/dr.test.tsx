/**
 * Demand Response surfacing (handoff 0013, design point 5): DR-scoped
 * figures (scope mode:DR / mode:DR:tos:*) carry a mode/TOS badge with
 * plain-language TOS labels, and their receipts call out — verbatim, with
 * page citations — each verified rule the TOS makes govern the figure:
 * the TX onboard-only rule, the TX/TN no-deadhead rule, the Exhibit 36
 * no-show-is-revenue rule (vrh/vrm), and the DR VOMS atypical-day
 * INCLUSION. SIMULATED badges come from the existing source_mix plumbing
 * (every live DR row is simulator-sourced) — asserted, not rebuilt.
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
  drPmtModeValue,
  drVomsModeValue,
  drVrhModeValue,
  drVrhTxValue,
  drVrmTnValue,
  vrmValue,
} from "./fixtures";
import { copy } from "../copy";

const TX_ONBOARD_QUOTE =
  "agencies must report only the miles and hours when a transit passenger is onboard as revenue service. When a transit passenger is not onboard, the service is not reportable to the NTD.";
const NO_DEADHEAD_QUOTE =
  "Full Reporters do not report deadhead for the Vanpool mode or the TX and Transportation Network Company (TN) TOS.";
const NO_SHOW_QUOTE =
  "Driver travels to pick up a passenger but the passenger is a no-show";
const VOMS_ATYPICAL_QUOTE =
  "The largest number of vehicles in revenue service at any one time during the reporting year (INCLUDES atypical service)";

async function openReceipt(name: RegExp) {
  const user = userEvent.setup();
  await screen.findByRole("table");
  await user.click(screen.getByRole("button", { name }));
  return screen.getByRole("region", { name: /^Receipt for/ });
}

describe("Demand Response figures (handoff 0013)", () => {
  it("badges DR rows in the metrics table — mode + plain-language TOS — while a fleet row carries no DR badge", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": {
        status: 200,
        body: [vrmValue, drVrhModeValue, drVrhTxValue],
      },
    });
    renderApp("/metrics");
    await screen.findByRole("table");

    // The whole-mode row: DR badge + "All types of service".
    const modeRow = screen
      .getByText("24.63")
      .closest("tr") as HTMLTableRowElement;
    expect(within(modeRow).getByText("Demand response (DR)")).toBeInTheDocument();
    expect(within(modeRow).getByText("All types of service")).toBeInTheDocument();
    // SIMULATED via the existing source_mix plumbing — never rebuilt.
    expect(within(modeRow).getByText("Simulated data")).toBeInTheDocument();

    // The TX row: DR badge + the plain-language TOS label.
    const txRow = screen.getByText("3.09").closest("tr") as HTMLTableRowElement;
    expect(within(txRow).getByText("Demand response (DR)")).toBeInTheDocument();
    expect(within(txRow).getByText("Taxi (TX)")).toBeInTheDocument();

    // The fleet-scoped VRM row carries NO DR badge.
    const fleetRow = screen
      .getByText("12345.60")
      .closest("tr") as HTMLTableRowElement;
    expect(
      within(fleetRow).queryByText("Demand response (DR)"),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("TX vrh receipt: TOS badge, the TX onboard-only and no-deadhead rules quoted with page cites, and NO no-show callout (TX supersedes it)", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [drVrhTxValue] },
    });
    renderApp("/metrics");
    const receipt = await openReceipt(/^Details/);

    // The badge rides with the story.
    expect(within(receipt).getByText("Demand response (DR)")).toBeInTheDocument();
    expect(within(receipt).getByText("Taxi (TX)")).toBeInTheDocument();

    // The TX onboard-only callout: plain-language lead-in + VERBATIM quote
    // + page citation. The quote also appears in the full verified list
    // below, so every check is scoped to the callout itself.
    const txCallout = within(receipt)
      .getByText(copy.dr.calloutIntro.txOnboard)
      .closest(".dr-callout") as HTMLElement;
    const txQuote = within(txCallout).getByText(TX_ONBOARD_QUOTE);
    expect(txQuote.closest("blockquote")).not.toBeNull();
    expect(
      txQuote.closest("figure")?.querySelector("figcaption cite"),
    ).toHaveTextContent(
      "TX revenue rule — 2026 NTD Full Reporting Policy Manual, p. 129",
    );

    // The no-deadhead callout, cited to p. 130. The quote also appears in
    // the full verified list below, so scope the check to the callout.
    const deadheadCallouts = within(receipt)
      .getByText(copy.dr.calloutIntro.noDeadhead)
      .closest(".dr-callout") as HTMLElement;
    expect(within(deadheadCallouts).getByText(NO_DEADHEAD_QUOTE)).toBeInTheDocument();
    expect(
      within(deadheadCallouts).getByRole("figure").querySelector("cite"),
    ).toHaveTextContent(
      "Non-fixed-route deadhead legs — 2026 NTD Full Reporting Policy Manual, p. 130",
    );

    // NO no-show callout on TX: a no-show contributes nothing to TX, so
    // calling out the no-show-is-revenue rule here would state the wrong
    // rule (the onboard-only rule above governs instead).
    expect(
      within(receipt).queryByText(copy.dr.calloutIntro.noShowRevenue),
    ).not.toBeInTheDocument();

    // SIMULATED flag via the existing plumbing (source_mix dr_simulated).
    expect(
      within(receipt).getByTitle(copy.simulated.tooltip),
    ).toHaveTextContent("Simulated data");

    await expectNoAxeViolations();
  });

  it("whole-mode vrh receipt: the Exhibit 36 no-show-is-revenue rule is called out, quoted verbatim", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [drVrhModeValue] },
    });
    renderApp("/metrics");
    const receipt = await openReceipt(/^Details/);

    expect(within(receipt).getByText("All types of service")).toBeInTheDocument();

    const callout = within(receipt)
      .getByText(copy.dr.calloutIntro.noShowRevenue)
      .closest(".dr-callout") as HTMLElement;
    expect(within(callout).getByText(NO_SHOW_QUOTE)).toBeInTheDocument();
    expect(within(callout).getByRole("figure").querySelector("cite")).toHaveTextContent(
      /Exhibit 36 activity table — 2026 NTD Full Reporting Policy Manual, pp\. 134–135/,
    );

    // No TX/TN callouts at mode level.
    expect(
      within(receipt).queryByText(copy.dr.calloutIntro.txOnboard),
    ).not.toBeInTheDocument();
    expect(
      within(receipt).queryByText(copy.dr.calloutIntro.noDeadhead),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("TN vrm receipt: no-deadhead AND no-show callouts together (TN keeps span semantics)", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [drVrmTnValue] },
    });
    renderApp("/metrics");
    const receipt = await openReceipt(/^Details/);

    expect(
      within(receipt).getByText("Transportation Network Company (TN)"),
    ).toBeInTheDocument();
    expect(
      within(receipt).getByText(copy.dr.calloutIntro.noDeadhead),
    ).toBeInTheDocument();
    expect(
      within(receipt).getByText(copy.dr.calloutIntro.noShowRevenue),
    ).toBeInTheDocument();
    expect(
      within(receipt).queryByText(copy.dr.calloutIntro.txOnboard),
    ).not.toBeInTheDocument();
  });

  it("DR VOMS receipt: the atypical-day INCLUSION note, quoted with its exhibit citation", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [drVomsModeValue] },
    });
    renderApp("/metrics");
    const receipt = await openReceipt(/^Details/);

    const callout = within(receipt)
      .getByText(copy.dr.calloutIntro.vomsAtypical)
      .closest(".dr-callout") as HTMLElement;
    expect(within(callout).getByText(VOMS_ATYPICAL_QUOTE)).toBeInTheDocument();
    expect(within(callout).getByRole("figure").querySelector("cite")).toHaveTextContent(
      "DR VOMS — 2026 NTD Full Reporting Policy Manual, Exhibits 38 + 40, pp. 138–139",
    );

    await expectNoAxeViolations();
  });

  it("DR PMT receipt: labeled Passenger Miles Traveled, DR-badged, quotes on file, no TOS callouts (onboard distance is PMT's basis for every TOS)", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [drPmtModeValue] },
    });
    renderApp("/metrics");
    const receipt = await openReceipt(/^Details/);

    // The story uses the new pmt metric + unit labels, figure verbatim.
    expect(
      within(receipt).getByText(
        "1112.23 passenger miles — Passenger Miles Traveled (PMT), 2026-07-14 to 2026-07-16.",
        { exact: false },
      ),
    ).toBeInTheDocument();
    expect(within(receipt).getByText("Demand response (DR)")).toBeInTheDocument();

    // No callouts — but the verified DR quotes render for dr_pmt_v0.
    expect(receipt.querySelector(".dr-callout")).toBeNull();
    expect(receipt.querySelectorAll("blockquote").length).toBeGreaterThan(0);
    expect(
      within(receipt).getByText(copy.receipt.ruleIntro("dr_pmt_v0")),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });
});
