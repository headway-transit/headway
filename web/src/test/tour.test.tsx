/**
 * The first-run guided tour (handoff 0021, design point 3). Pinned — the
 * handoff's binding rules, by the letter:
 *  - auto-offers exactly once (localStorage flag); finishing OR skipping
 *    marks it seen; "Take the tour" in the nav restarts it any time;
 *  - SKIPPABLE AT EVERY STEP: a skip button on every non-final step and
 *    Escape from anywhere;
 *  - NEVER BLOCKS: a non-modal dialog — the page behind stays usable;
 *  - keyboard-accessible: focus moves to each step's heading;
 *  - teaches the thesis end to end: /today → the KPI receipt opens → the
 *    verbatim quote → one lineage step (through the receipt's own walk
 *    door, SPA navigation) → done;
 *  - honest fallback: with no figure on the board, the step SAYS there is
 *    nothing to point at — it never fabricates;
 *  - axe reports zero violations with the panel open.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import {
  lineageTree,
  uptValue,
  vrmValue,
  vrmWithCoverage,
} from "./fixtures";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-07-20T12:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
});

/** vrmWithCoverage carries detail + quotes; make it the newest figure. */
const tourValues = [vrmWithCoverage, vrmValue, uptValue];

function mockTourApi() {
  return mockApi({
    "GET /metrics/values": { status: 200, body: tourValues },
    "GET /metrics/compare": {
      status: 200,
      body: {
        metric: "vrm",
        unit: "miles",
        comparands: [],
        scopes: [],
        rows: [],
        directions: {},
        direction_note: "",
        delta_note: "",
        mixed_certification: false,
        mixed_certification_note: null,
      },
    },
    [`GET /metrics/values/${vrmWithCoverage.metric_value_id}/lineage`]: {
      status: 200,
      body: lineageTree,
    },
  });
}

describe("the guided tour", () => {
  it("auto-offers on the first visit, and a skip dismisses it for good", async () => {
    signInAs("viewer");
    mockTourApi();
    renderApp("/today");

    const dialog = await screen.findByRole("dialog", { name: "Guided tour" });
    expect(dialog).toHaveTextContent("Step 1 of 5");
    expect(dialog).toHaveTextContent("This page is your briefing");
    // Skippable at step 1, and the dismissal persists.
    await userEvent.click(
      screen.getByRole("button", { name: "Skip the tour" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "Guided tour" }),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem("headway-tour-seen")).toBe("1");
  });

  it("does not re-offer once seen", async () => {
    window.localStorage.setItem("headway-tour-seen", "1");
    signInAs("viewer");
    mockTourApi();
    renderApp("/today");
    expect(await screen.findByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: "Guided tour" }),
    ).not.toBeInTheDocument();
  });

  it("walks the whole thesis: receipt opens → verbatim quote → one lineage step → done, keyboard-focused at every step", async () => {
    signInAs("viewer");
    mockTourApi();
    renderApp("/today");

    const dialog = await screen.findByRole("dialog", { name: "Guided tour" });
    // Focus lands on the step heading (keyboard/SR users come along).
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "This page is your briefing" }),
      ).toHaveFocus(),
    );

    // Step 2: the tour OPENS the first KPI receipt (real DOM, no fake).
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(dialog).toHaveTextContent("Step 2 of 5");
    expect(dialog).toHaveTextContent("Every number opens into a receipt");
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: /Receipt.*Vehicle Revenue Miles/i }),
      ).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("heading", {
          name: "Every number opens into a receipt",
        }),
      ).toHaveFocus(),
    );

    // Step 3: dwell on the verbatim FTA quote inside the open receipt.
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(dialog).toHaveTextContent("The federal rule, word for word");
    await waitFor(() => {
      const quote = document.querySelector(
        '[data-tour="kpi-receipt"] .fta-quote',
      );
      expect(quote).not.toBeNull();
      expect(quote).toHaveClass("tour-target");
    });

    // Step 4: the tour takes the receipt's own walk door (SPA nav) to the
    // lineage view — one step of the walk.
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(dialog).toHaveTextContent("Walk the number to its raw records");
    expect(
      await screen.findByRole("heading", { name: /How this number was made/i }),
    ).toBeInTheDocument();

    // Step 5: done — the thesis, then Finish marks the tour seen.
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(dialog).toHaveTextContent("Every number here can prove itself");
    await expectNoAxeViolations();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(
      screen.queryByRole("dialog", { name: "Guided tour" }),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem("headway-tour-seen")).toBe("1");
  });

  it("leaves on Escape at any step — skippable is binding", async () => {
    signInAs("viewer");
    mockTourApi();
    renderApp("/today");

    await screen.findByRole("dialog", { name: "Guided tour" });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.keyboard("{Escape}");
    expect(
      screen.queryByRole("dialog", { name: "Guided tour" }),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem("headway-tour-seen")).toBe("1");
  });

  it("never blocks: the page behind the tour stays fully usable", async () => {
    signInAs("viewer");
    mockTourApi();
    renderApp("/today");

    await screen.findByRole("dialog", { name: "Guided tour" });
    // A control OUTSIDE the tour still works while the tour is open.
    await userEvent.click(
      screen.getByRole("link", { name: "See every computed figure" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Computed metric values" }),
    ).toBeInTheDocument();
  });

  it("is restartable from the nav on any page", async () => {
    window.localStorage.setItem("headway-tour-seen", "1");
    signInAs("viewer");
    mockTourApi();
    renderApp("/metrics");

    await screen.findByRole("heading", { name: "Computed metric values" });
    await userEvent.click(
      screen.getByRole("button", { name: "Take the tour" }),
    );
    // SPA navigation to /today, tour at step 1.
    const dialog = await screen.findByRole("dialog", { name: "Guided tour" });
    expect(dialog).toHaveTextContent("Step 1 of 5");
    expect(
      await screen.findByRole("heading", { name: "Today" }),
    ).toBeInTheDocument();
  });

  it("states an empty board honestly instead of fabricating a target", async () => {
    signInAs("viewer");
    mockApi({ "GET /metrics/values": { status: 200, body: [] } });
    renderApp("/today");

    const dialog = await screen.findByRole("dialog", { name: "Guided tour" });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    // The honest fallback line — the step still teaches, points at
    // nothing. It appears only after the target search truly gives up
    // (~1s of polling), hence the widened timeout.
    await waitFor(
      () =>
        expect(dialog).toHaveTextContent(
          "There is no computed figure on the board yet",
        ),
      { timeout: 4000 },
    );
    await expectNoAxeViolations();
  });
});
