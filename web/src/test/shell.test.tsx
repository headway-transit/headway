/**
 * Shell-wide UI-wave behaviors (handoff 0017):
 *  - design point 4: the persistent toast region (aria-live polite via
 *    role="log", explicit dismiss, cleared on route change) and the
 *    breadcrumb trail on deep entities (receipt → lineage);
 *  - design point 7: themed nav chrome from branding v2 fields — applied
 *    only in the display mode it was validated for (light), NEUTRAL
 *    default when unset, dark always neutral (the stated per-mode
 *    limitation), reverting cleanly when toggled back.
 */

import { describe, expect, it } from "vitest";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  signInAs,
} from "./helpers";
import { pushToast } from "../toasts";
import { lineageTree, vrmValue } from "./fixtures";
import { copy } from "../copy";

const themedBranding = {
  display_name: "Metro Transit",
  primary: "#1a5fb4",
  accent: "#0b57d0",
  has_logo: false,
  // Branding v2 (services/api ChromeTheme): ONE color set, every pair
  // server-verified by the WCAG guardrail before it is ever served.
  chrome: {
    header_bg: "#1a5fb4",
    header_fg: "#ffffff",
    accent: "#ffd24a",
  },
  chrome_note:
    "The chrome theme carries one color set, validated for readability against itself. A theme is applied only where it renders readably; in a display mode it was not validated for (dark mode), the shell keeps the neutral Headway chrome and says so — stated, never silent.",
};

describe("shell (handoff 0017)", () => {
  it("renders toasts in a persistent polite live region with explicit dismiss, and clears them on route change", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [vrmValue] },
      "GET /dq/issues": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    renderApp("/metrics");
    await screen.findByRole("heading", { name: "Computed metric values" });

    // The region exists BEFORE any toast (a live region that pops into
    // existence is unreliably announced) and is polite.
    const region = screen.getByRole("log", { name: "Action confirmations" });
    expect(region).toHaveAttribute("aria-live", "polite");

    act(() => pushToast("Something was recorded."));
    expect(region).toHaveTextContent("Something was recorded.");

    // Explicit dismiss — no timer ever removes a confirmation.
    await user.click(within(region).getByRole("button", { name: /Dismiss/ }));
    expect(region).not.toHaveTextContent("Something was recorded.");

    // A toast belongs to the page it confirmed on: navigation clears it.
    act(() => pushToast("Stale confirmation."));
    expect(region).toHaveTextContent("Stale confirmation.");
    await user.click(screen.getByRole("link", { name: "Data quality" }));
    await screen.findByRole("heading", { name: "Data-quality issues" });
    expect(
      screen.getByRole("log", { name: "Action confirmations" }),
    ).not.toHaveTextContent("Stale confirmation.");

    await expectNoAxeViolations();
  });

  it("shows a breadcrumb trail on the lineage deep entity: metrics → figure → this page", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values/mv-vrm-1/lineage": {
        status: 200,
        body: lineageTree,
      },
    });
    renderApp("/metrics/mv-vrm-1/lineage");
    await screen.findByRole("heading", { name: "How this number was made" });

    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(
      within(crumbs).getByRole("link", { name: "Metrics" }),
    ).toHaveAttribute("href", "/metrics");
    expect(within(crumbs).getByText("Figure mv-vrm-1")).toBeInTheDocument();
    const current = within(crumbs).getByText("How this number was made");
    expect(current).toHaveAttribute("aria-current", "page");

    await expectNoAxeViolations();
  });

  it("applies themed chrome from branding v2 in light mode only, keeps dark NEUTRAL (the stated per-mode limitation), and reverts cleanly", async () => {
    mockApi({
      "GET /branding": { status: 200, body: themedBranding },
      "GET /public/metrics/certified": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    renderApp("/public");
    await screen.findByRole("heading", {
      name: "Public data: certified figures",
    });

    // Light mode: the chrome custom properties are applied (values the
    // server already contrast-verified) and the chrome flag is set.
    const root = document.documentElement;
    expect(root.style.getPropertyValue("--chrome-header-bg")).toBe("#1a5fb4");
    expect(root.style.getPropertyValue("--chrome-header-text")).toBe(
      "#ffffff",
    );
    expect(root.style.getPropertyValue("--chrome-active-accent")).toBe(
      "#ffd24a",
    );
    expect(root.getAttribute("data-chrome")).toBe("on");

    // Dark mode: the chrome was validated for light only, so it simply
    // does not apply — neutral Headway dark chrome (the API's chrome_note
    // and the branding room state the rule). Nothing lingers.
    await user.click(
      screen.getByRole("button", { name: "Switch to dark theme" }),
    );
    expect(root.style.getPropertyValue("--chrome-header-bg")).toBe("");
    expect(root.style.getPropertyValue("--chrome-header-text")).toBe("");
    expect(root.getAttribute("data-chrome")).toBeNull();

    // Back to light: the chrome re-applies.
    await user.click(
      screen.getByRole("button", { name: "Switch to light theme" }),
    );
    expect(root.style.getPropertyValue("--chrome-header-bg")).toBe("#1a5fb4");
    expect(root.getAttribute("data-chrome")).toBe("on");

    await expectNoAxeViolations();
  });

  it("keeps the NEUTRAL Headway chrome when branding v2 fields are unset (an API that predates them, or defaults)", async () => {
    mockApi({
      "GET /public/metrics/certified": { status: 200, body: [] },
      // The helpers' default GET /branding has no chrome fields at all.
    });
    renderApp("/public");
    await screen.findByRole("heading", {
      name: "Public data: certified figures",
    });

    const root = document.documentElement;
    expect(root.style.getPropertyValue("--chrome-header-bg")).toBe("");
    expect(root.getAttribute("data-chrome")).toBeNull();
  });
});

/**
 * THE COMMAND BAR (handoff 0044, output 1).
 *
 * The shell used to spend two wrapping rows on seventeen links. What
 * replaced it must stay as reachable as what it replaced, so these pin the
 * things a "denser nav" is most likely to quietly cost: the run stamp being
 * REAL, the tail links being genuinely hidden (never invisible-but-focusable),
 * Escape returning focus to its trigger, and the whole bar staying in a
 * sensible keyboard order.
 */
describe("the command bar (handoff 0044)", () => {
  const runRecord = {
    run_id: "run-9",
    requested_by: "maria.ops",
    requested_at: "2026-08-02T05:58:00Z",
    period_start: "2026-07-01",
    period_end: "2026-08-01",
    status: "succeeded",
    started_at: "2026-08-02T05:58:02Z",
    finished_at: "2026-08-02T05:59:41Z",
    runner_pid: 41,
    duration_seconds: 99,
    stale: false,
    stale_note: null,
    stdout_tail: null,
    summary: { persisted_count: 3, blocked_count: 0, metrics: [] },
  };

  it("stamps the REAL last calculation run, and names the room you are in", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [vrmValue] },
      "GET /calc/runs": { status: 200, body: [runRecord] },
    });
    renderApp("/metrics");
    await screen.findByRole("heading", { name: "Computed metric values" });

    const banner = screen.getByRole("banner");
    // The stamp is the SERVER's timestamp, verbatim, with the run's status.
    expect(
      await within(banner).findByText(
        `${runRecord.finished_at} · succeeded`,
      ),
    ).toBeInTheDocument();
    expect(within(banner).getByText(copy.shell.stamp.label)).toBeInTheDocument();
    // The room you are in, named in the bar (the nav link of the same name
    // also lives in the banner, so the context slot is found by class).
    const context = banner.querySelector(".command-context");
    expect(context).toHaveTextContent(copy.nav.metrics);
  });

  it("says so when no run is on record — never a comforting blank", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [vrmValue] },
      "GET /calc/runs": { status: 200, body: [] },
    });
    renderApp("/metrics");
    await screen.findByRole("heading", { name: "Computed metric values" });
    expect(
      await screen.findByText(copy.shell.stamp.none),
    ).toBeInTheDocument();
  });

  it("says so when the run record cannot be read", async () => {
    signInAs("viewer");
    mockApi({
      "GET /metrics/values": { status: 200, body: [vrmValue] },
      "GET /calc/runs": { status: 500, body: { detail: "unavailable" } },
    });
    renderApp("/metrics");
    await screen.findByRole("heading", { name: "Computed metric values" });
    expect(
      await screen.findByText(copy.shell.stamp.unavailable),
    ).toBeInTheDocument();
  });

  it("keeps the nav to ONE row: the tail sits in named groups whose links are genuinely hidden until opened, and Escape returns focus to the trigger", async () => {
    signInAs("viewer");
    mockApi({ "GET /metrics/values": { status: 200, body: [vrmValue] } });
    const user = userEvent.setup();
    renderApp("/metrics");
    await screen.findByRole("heading", { name: "Computed metric values" });

    const nav = screen.getByRole("navigation", { name: "Main" });
    // The rooms people live in stay direct links.
    for (const label of [
      copy.nav.today,
      copy.nav.map,
      copy.nav.dashboard,
      copy.nav.metrics,
      copy.nav.dq,
      copy.nav.publicData,
    ]) {
      expect(within(nav).getByRole("link", { name: label })).toBeVisible();
    }

    // The tail is behind named groups, and CLOSED means gone from the
    // accessibility tree — not merely invisible while still tabbable.
    const trigger = within(nav).getByRole("button", { name: /^Reports/ });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(
      within(nav).queryByRole("link", { name: copy.nav.reports }),
    ).not.toBeInTheDocument();
    const panel = document.getElementById(
      trigger.getAttribute("aria-controls") ?? "",
    );
    expect(panel).toHaveAttribute("hidden");

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(
      within(nav).getByRole("link", { name: copy.nav.reports }),
    ).toHaveAttribute("href", "/reports/monthly");
    expect(
      within(nav).getByRole("link", { name: copy.nav.sampling }),
    ).toBeVisible();

    // Escape closes it and hands focus back to the control that opened it.
    trigger.focus();
    await user.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();

    await expectNoAxeViolations();
  });

  it("keeps the keyboard order the shell always had: skip link, then the bar, then the nav row, then the page", async () => {
    signInAs("viewer");
    mockApi({ "GET /metrics/values": { status: 200, body: [vrmValue] } });
    const user = userEvent.setup();
    renderApp("/metrics");
    await screen.findByRole("heading", { name: "Computed metric values" });

    await user.tab();
    expect(
      screen.getByRole("link", { name: copy.skipToContent }),
    ).toHaveFocus();
    await user.tab();
    expect(
      screen.getByRole("button", { name: copy.today.takeTourLink }),
    ).toHaveFocus();
    await user.tab();
    expect(
      screen.getByRole("button", { name: copy.theme.switchToDark }),
    ).toHaveFocus();
    // The opt-in navigation toggle sits AFTER the theme control, deliberately:
    // the order of this bar is muscle memory, so a beta control joins the end
    // of the queue rather than displacing something that has been here for
    // months. Everything below it keeps the position it always had.
    await user.tab();
    expect(
      screen.getByRole("button", { name: copy.nav_mode.switchToRail }),
    ).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: copy.signOut })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("link", { name: copy.nav.today })).toHaveFocus();
  });
});
