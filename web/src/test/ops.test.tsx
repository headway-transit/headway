/**
 * Operations-metric surfacing (handoff 0014, design point 5): every
 * `category === "ops"` figure carries the "Operations metric — not an NTD
 * reported figure" badge everywhere it appears; ops receipts cite the
 * VERBATIM TCQSM basis plus the Headway-owned definitions (labeled,
 * visually distinct — never confusable with federal quotes); the dashboard
 * grows route-level OTP + headway adherence cards with the derivation's
 * refusal accounting shown, never hidden; and the boundary holds in both
 * directions — NTD figures carry no ops badge, and the certify cockpit asks
 * the server for category=ntd only.
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
  opsCvhAgencyValue,
  opsOtpAgencyValue,
  opsValues,
  vrmWithCoverage,
} from "./fixtures";
import { copy } from "../copy";

const OTP_WINDOW_QUOTE =
  "this edition of the TCQSM defines 'on-time' as a departure from a " +
  "timepoint as 1 min early to 5 min late or an arrival at the route " +
  "terminal up to 5 min late.";

async function openReceipt(name: RegExp) {
  const user = userEvent.setup();
  await screen.findByRole("table");
  await user.click(screen.getByRole("button", { name }));
  return screen.getByRole("region", { name: /^Receipt for/ });
}

describe("operations metrics (handoff 0014)", () => {
  it("badges every ops row in the metrics table while an NTD row carries NO ops badge", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": {
        status: 200,
        body: [vrmWithCoverage, opsOtpAgencyValue, opsCvhAgencyValue],
      },
    });
    renderApp("/metrics");
    await screen.findByRole("table");

    const otpRow = screen
      .getByText("54.10")
      .closest("tr") as HTMLTableRowElement;
    expect(within(otpRow).getByText(copy.ops.badge)).toBeInTheDocument();
    const cvhRow = screen
      .getByText("0.3010")
      .closest("tr") as HTMLTableRowElement;
    expect(within(cvhRow).getByText(copy.ops.badge)).toBeInTheDocument();

    // The NTD row: NO ops badge — non-contamination in the UI layer too.
    const ntdRow = screen
      .getByText("12345.60")
      .closest("tr") as HTMLTableRowElement;
    expect(within(ntdRow).queryByText(copy.ops.badge)).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("ops OTP receipt: badge + the VERBATIM TCQSM window quote (p. 5-29) + Headway-owned definitions labeled and distinct + the refusal accounting + the walk to raw records", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [opsOtpAgencyValue] },
    });
    renderApp("/metrics");
    const receipt = await openReceipt(/^Details/);

    // The badge rides with the story line.
    expect(within(receipt).getByText(copy.ops.badge)).toBeInTheDocument();
    expect(
      within(receipt).getByText(
        "54.10 percent — On-time performance (OTP), 2026-07-01 to 2026-08-01.",
        { exact: false },
      ),
    ).toBeInTheDocument();

    // The INDUSTRY basis — never the FTA rule heading.
    expect(
      within(receipt).getByText(copy.ops.receipt.basisHeading),
    ).toBeInTheDocument();
    expect(
      within(receipt).queryByText(copy.receipt.ruleHeading),
    ).not.toBeInTheDocument();

    // The TCQSM window, verbatim, with its page citation.
    const windowQuote = within(receipt).getByText(OTP_WINDOW_QUOTE);
    expect(windowQuote.closest("blockquote")).not.toBeNull();
    expect(
      windowQuote.closest("figure")?.querySelector("figcaption cite"),
    ).toHaveTextContent(/p\. 5-29/);
    expect(
      windowQuote.closest("figure")?.querySelector("figcaption cite"),
    ).toHaveTextContent(/Transit Capacity and Quality of Service Manual/);

    // The Headway-owned definitions: labeled, OUTSIDE any blockquote (a
    // reader must never mistake OUR definitions for quoted rules), with
    // the otp_v0 formula shown and the derivation definition alongside.
    const ownedLabels = within(receipt).getAllByText(
      copy.ops.receipt.ownedLabel,
    );
    expect(ownedLabels.length).toBe(2);
    for (const label of ownedLabels) {
      expect(label.closest("blockquote")).toBeNull();
      expect(label.closest(".ops-owned")).not.toBeNull();
    }
    expect(within(receipt).getByText("otp_v0 0.1.0")).toBeInTheDocument();
    expect(
      within(receipt).getByText("derive_stop_passages 0.1.0"),
    ).toBeInTheDocument();
    expect(
      within(receipt).getByRole("region", { name: "Formula for otp_v0" }),
    ).toHaveTextContent("OTP = 100 ×");

    // The refusal accounting (design point 3): every count, stated.
    expect(
      within(receipt).getByText(/131384 passages refused/),
    ).toBeInTheDocument();
    expect(
      within(receipt).getByText(/21445 passages refused/),
    ).toBeInTheDocument();
    expect(
      within(receipt).getByText(/3880 passages refused: cadence too sparse/),
    ).toBeInTheDocument();

    // Provenance is never orphaned: the walk to raw records stands.
    expect(
      within(receipt).getByRole("link", { name: /Walk this number/ }),
    ).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("ops cvh receipt: the TCQSM cvh definition verbatim and the Example-3 formula labeled Headway-owned", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [opsCvhAgencyValue] },
    });
    renderApp("/metrics");
    const receipt = await openReceipt(/^Details/);

    expect(within(receipt).getByText(copy.ops.badge)).toBeInTheDocument();
    expect(
      within(receipt).getByText(/coefficient of variation of headways/),
    ).toBeInTheDocument();
    expect(
      within(receipt).getByText("headway_adherence_v0 0.1.0"),
    ).toBeInTheDocument();
    expect(
      within(receipt).getByRole("region", {
        name: "Formula for headway_adherence_v0",
      }),
    ).toHaveTextContent("cvh = pstdev");

    // The pair exclusions are spelled out in the detail lines.
    expect(
      within(receipt).getByText(/non-positive headway/),
    ).toHaveTextContent("20143");

    await expectNoAxeViolations();
  });

  it("NTD receipt: NO ops badge and NO industry-basis section — the FTA rule renders unchanged", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [vrmWithCoverage] },
    });
    renderApp("/metrics");
    const receipt = await openReceipt(/^Details/);

    expect(within(receipt).queryByText(copy.ops.badge)).not.toBeInTheDocument();
    expect(
      within(receipt).queryByText(copy.ops.receipt.basisHeading),
    ).not.toBeInTheDocument();
    expect(
      within(receipt).queryByText(copy.ops.receipt.ownedLabel),
    ).not.toBeInTheDocument();
    expect(
      within(receipt).getByText(copy.receipt.ruleHeading),
    ).toBeInTheDocument();
    expect(
      within(receipt).getByText(copy.receipt.ruleIntro("vrm_v0")),
    ).toBeInTheDocument();
  });

  it("dashboard: ops cards render the live agency figures VERBATIM with the badge, the breakdown, the refusal accounting, and route-level table rows", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: opsValues },
      "GET /dq/issues": { status: 200, body: [] },
    });
    renderApp("/dashboard");
    await screen.findByRole("heading", { name: copy.ops.dashboard.heading });

    const otpCard = screen
      .getByRole("heading", { name: copy.ops.dashboard.otp.heading })
      .closest("section") as HTMLElement;
    // The badge on the card (every ops figure, everywhere it appears).
    expect(within(otpCard).getByText(copy.ops.badge)).toBeInTheDocument();
    // The agency figure verbatim + the on-time/early/late breakdown.
    expect(
      within(otpCard).getByText(copy.ops.dashboard.otp.agencyStat("54.10")),
    ).toBeInTheDocument();
    expect(
      within(otpCard).getByText(
        copy.ops.dashboard.otp.breakdown("289826", "94663", "151267"),
      ),
    ).toBeInTheDocument();
    // Refusal counts shown, not hidden.
    expect(
      within(otpCard).getByText(/3880 passages refused: cadence too sparse/),
    ).toBeInTheDocument();
    expect(
      within(otpCard).getByText(/131384 passages refused/),
    ).toBeInTheDocument();

    // The route-level table view lists the agency and route rows verbatim.
    const user = userEvent.setup();
    await user.click(
      within(otpCard).getByRole("button", { name: copy.dashboard.tableView }),
    );
    expect(within(otpCard).getByText("Route 1")).toBeInTheDocument();
    expect(within(otpCard).getByText("44.16%")).toBeInTheDocument();
    expect(
      within(otpCard).getAllByRole("link", {
        name: /How this number was made/,
      }).length,
    ).toBeGreaterThanOrEqual(2);

    const cvhCard = screen
      .getByRole("heading", { name: copy.ops.dashboard.cvh.heading })
      .closest("section") as HTMLElement;
    expect(within(cvhCard).getByText(copy.ops.badge)).toBeInTheDocument();
    expect(
      within(cvhCard).getByText(copy.ops.dashboard.cvh.agencyStat("0.3010")),
    ).toBeInTheDocument();
    // No interpretation bands are invented: the formula reference ships
    // with the raw value (OPS_DEFINITIONS.md defines no bands).
    expect(
      within(cvhCard).getByText(copy.ops.dashboard.cvh.formulaReference),
    ).toBeInTheDocument();
    expect(
      within(cvhCard).getByText(
        copy.ops.dashboard.cvh.exclusions("20143", "10020", "0"),
      ),
    ).toBeInTheDocument();
    await user.click(
      within(cvhCard).getByRole("button", { name: copy.dashboard.tableView }),
    );
    expect(within(cvhCard).getByText("Route 66")).toBeInTheDocument();
    expect(within(cvhCard).getByText("0.4476")).toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("dashboard: with no ops rows the section states the absence (never a blank)", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": {
        status: 200,
        body: [vrmWithCoverage],
      },
      "GET /dq/issues": { status: 200, body: [] },
    });
    renderApp("/dashboard");
    await screen.findByRole("heading", { name: copy.ops.dashboard.heading });
    expect(screen.getByText(copy.ops.dashboard.empty)).toBeInTheDocument();
  });

  it("certify cockpit asks the server for category=ntd — ops figures never appear beside a signature checkbox", async () => {
    signInAs("certifying_official");
    const calls = mockApi({
      "GET /metrics/values": { status: 200, body: [vrmWithCoverage] },
      "GET /dq/issues": { status: 200, body: [] },
    });
    renderApp("/certify");
    await screen.findByRole("heading", { name: copy.certify.heading });
    await screen.findByText(/12345\.60/);

    const metricCalls = calls.filter((c) => c.path === "/metrics/values");
    expect(metricCalls.length).toBeGreaterThanOrEqual(1);
    for (const call of metricCalls) {
      expect(call.url).toContain("category=ntd");
    }
  });
});
