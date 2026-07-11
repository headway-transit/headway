/**
 * Theme selection (handoff 0008, pillar A): the explicit toggle stamps
 * <html data-theme> and persists to localStorage; a persisted choice is
 * respected on the next load; without one the OS preference decides
 * (jsdom has no matchMedia, which exercises the light fallback).
 */

import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expectNoAxeViolations, mockApi, renderApp } from "./helpers";

function mockPublicPage() {
  mockApi({ "GET /public/metrics/certified": { status: 200, body: [] } });
}

describe("theme toggle", () => {
  it("switches to dark on demand, stamps data-theme, and persists the choice to localStorage", async () => {
    const user = userEvent.setup();
    mockPublicPage();
    renderApp("/public");

    // No stored choice + no matchMedia (jsdom): the light set applies.
    const toggle = await screen.findByRole("button", {
      name: "Switch to dark theme",
    });
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");

    await user.click(toggle);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(window.localStorage.getItem("headway-theme")).toBe("dark");

    // The toggle now offers the way back (label names the action).
    const back = screen.getByRole("button", { name: "Switch to light theme" });
    await user.click(back);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(window.localStorage.getItem("headway-theme")).toBe("light");

    await expectNoAxeViolations();
  });

  it("respects a persisted dark choice on load", async () => {
    window.localStorage.setItem("headway-theme", "dark");
    mockPublicPage();
    renderApp("/public");

    expect(
      await screen.findByRole("button", { name: "Switch to light theme" }),
    ).toBeInTheDocument();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
});
