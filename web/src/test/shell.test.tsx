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
