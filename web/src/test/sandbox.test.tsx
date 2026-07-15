/**
 * /sandbox (handoff 0017, design point 6) — the HARD WALLS under test:
 * "modeling preview — changes nothing" is prominent on every visit; there
 * is NO apply control anywhere on the surface; proposed values stay strings
 * end to end; preview figures render verbatim with the preview tag; an
 * honest refusal is a stated result with its would-be findings listed;
 * deltas are the server's exact strings, sign-neutral.
 *
 * Typed against services/api routers/sandbox.py (reconciled 2026-07-14):
 * previews are EPHEMERAL (persisted=false, nothing written anywhere), so
 * preview figures deliberately carry NO receipt/lineage door — there is
 * no persisted row to walk.
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
import { sandboxPreviewResponse, sandboxSettings } from "./fixtures";

function mockSandbox() {
  return mockApi({
    "GET /settings": { status: 200, body: sandboxSettings },
    "POST /sandbox/preview": { status: 200, body: sandboxPreviewResponse },
  });
}

async function proposeAndPickPeriod(
  user: ReturnType<typeof userEvent.setup>,
) {
  await user.type(
    await screen.findByLabelText("Proposed value for coverage_threshold"),
    "0.90",
  );
  await user.type(screen.getByLabelText("From date"), "2026-06-01");
  await user.type(screen.getByLabelText("To date"), "2026-07-01");
}

describe("/sandbox", () => {
  it("states 'changes nothing' prominently, names the audited settings flow, and offers NO apply control", async () => {
    signInAs("data_steward");
    mockSandbox();
    renderApp("/sandbox");

    expect(
      await screen.findByRole("heading", { name: "Settings sandbox" }),
    ).toBeInTheDocument();
    // The prominent wall, on every visit — before any preview runs.
    expect(
      screen.getByText(/Modeling preview — changes nothing\./),
    ).toBeInTheDocument();
    // The separate audited flow is NAMED; applying is not offered here.
    expect(screen.getByText(/audited settings flow/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /apply/i }),
    ).not.toBeInTheDocument();

    // The knob set: calculation-policy settings only, with today's values
    // verbatim; a non-knob setting (display name) is not offered.
    expect(
      screen.getByLabelText("Proposed value for coverage_threshold"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Proposed value for layover_max_seconds"),
    ).toBeInTheDocument();
    expect(screen.getByText("Today's value: 0.95")).toBeInTheDocument();
    expect(screen.getByText("Today's value: 1800")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Proposed value for agency_display_name"),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("keeps the preview button off (reason at the button) until a proposed value and a period exist; refused clicks send nothing", async () => {
    signInAs("data_steward");
    const calls = mockSandbox();
    const user = userEvent.setup();
    renderApp("/sandbox");

    const button = await screen.findByRole("button", {
      name: "Run the preview",
    });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getByText(/Propose a new value for at least one setting/),
    ).toBeInTheDocument();
    await user.click(button);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    await user.type(
      screen.getByLabelText("Proposed value for coverage_threshold"),
      "0.90",
    );
    expect(screen.getByText(/Pick the period to preview/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("From date"), "2026-06-01");
    await user.type(screen.getByLabelText("To date"), "2026-07-01");
    expect(button).not.toHaveAttribute("aria-disabled");

    await expectNoAxeViolations();
  });

  it("runs the preview with string values end to end and renders the impact rail: verbatim figures, preview tags, sign-neutral delta, stated refusals with their findings", async () => {
    signInAs("data_steward");
    const calls = mockSandbox();
    const user = userEvent.setup();
    renderApp("/sandbox");

    await proposeAndPickPeriod(user);
    await user.click(screen.getByRole("button", { name: "Run the preview" }));

    // The request body matches SandboxPreviewRequest exactly: values are
    // STRINGS (the app.settings discipline), untouched knobs omitted.
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/sandbox/preview");
    expect(post?.body).toEqual({
      period_start: "2026-06-01",
      period_end: "2026-07-01",
      proposed: { coverage_threshold: "0.90" },
    });

    // The confirmation goes through the shell's toast region and states
    // the wall again.
    expect(await screen.findByRole("log")).toHaveTextContent(
      "Preview computed. Nothing was changed",
    );

    const rail = screen.getByRole("region", { name: "What would change" });
    // The SERVER's own banner, verbatim.
    expect(
      within(rail).getByText(/computed on the fly for this response only/),
    ).toBeInTheDocument();
    // The knobs BOTH variants ran under: today → proposed, verbatim, with
    // the baseline's recorded provenance.
    expect(
      within(rail).getByText(/coverage_threshold: 0\.95 today → 0\.90 proposed/),
    ).toBeInTheDocument();
    expect(
      within(rail).getAllByText(/app\.settings row \(updated by migration-0014\)/)
        .length,
    ).toBeGreaterThan(0);
    // Figures verbatim; every preview figure carries the changes-nothing tag.
    expect(within(rail).getByText("9758.55")).toBeInTheDocument();
    expect(within(rail).getByText("64871.22")).toBeInTheDocument();
    expect(
      within(rail).getAllByText("Preview — changes nothing").length,
    ).toBeGreaterThan(1);
    // The delta is the server's exact string, SIGN-NEUTRAL (no better/worse).
    expect(
      within(rail).getByText(/671\.22 more than today's figure/),
    ).toBeInTheDocument();
    expect(within(rail).queryByText(/better/)).not.toBeInTheDocument();
    // An honest refusal is a stated result WITH its would-be findings.
    expect(
      within(rail).getAllByText(/The calculation refused to produce this figure/)
        .length,
    ).toBeGreaterThan(0);
    expect(
      within(rail).getByText(
        "Trip coverage 0.9126 is below the coverage threshold 0.95 — the run refused to emit a figure.",
      ),
    ).toBeInTheDocument();
    // A standing figure's would-be warnings are listed too, never hidden.
    expect(
      within(rail).getByText(
        "202 gapped vehicle-trip groups excluded and documented.",
      ),
    ).toBeInTheDocument();
    // The server's audited-flow pointer, verbatim; still no apply control.
    expect(
      within(rail).getByText(/Applying a knob is a separate, audited act/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /apply/i }),
    ).not.toBeInTheDocument();

    await expectNoAxeViolations();
  });

  it("surfaces a preview refusal from the API verbatim", async () => {
    signInAs("data_steward");
    const refusal =
      "'abc' is not a decimal number, so it cannot be previewed as " +
      "'coverage_threshold'. Please send a plain decimal number, for " +
      "example '0.95'.";
    mockApi({
      "GET /settings": { status: 200, body: sandboxSettings },
      "POST /sandbox/preview": { status: 422, body: { detail: refusal } },
    });
    const user = userEvent.setup();
    renderApp("/sandbox");

    await proposeAndPickPeriod(user);
    await user.click(screen.getByRole("button", { name: "Run the preview" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(refusal);
  });
});
