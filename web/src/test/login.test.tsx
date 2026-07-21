import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
} from "./helpers";

const WRONG_CREDENTIALS_MESSAGE =
  "That username and password combination was not recognized.";

describe("/login", () => {
  it("renders labeled username and password inputs with no axe violations", async () => {
    renderApp("/login");
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Sign in" }),
    ).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("announces a failed login verbatim via role=alert", async () => {
    mockApi({
      "POST /auth/login": {
        status: 401,
        body: { detail: WRONG_CREDENTIALS_MESSAGE },
      },
    });
    const user = userEvent.setup();
    renderApp("/login");

    await user.type(screen.getByLabelText("Username"), "maria.ops");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(WRONG_CREDENTIALS_MESSAGE);
    await expectNoAxeViolations();
  });

  it("signs in entirely by keyboard and lands on the Today briefing (handoff 0021)", async () => {
    // The tour auto-offers on a true first visit; this test covers the
    // login path, so mark it seen (tour.test.tsx owns the tour).
    window.localStorage.setItem("headway-tour-seen", "1");
    const calls = mockApi({
      "POST /auth/login": {
        status: 200,
        body: {
          access_token: "token-abc",
          token_type: "bearer",
          expires_in: 1800,
          username: "maria.ops",
          role: "viewer",
        },
      },
      "GET /metrics/values": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    renderApp("/login");

    // Keyboard-only path: tab to each field, type, submit with Enter.
    await user.tab();
    expect(screen.getByLabelText("Username")).toHaveFocus();
    await user.keyboard("maria.ops");
    await user.tab();
    expect(screen.getByLabelText("Password")).toHaveFocus();
    await user.keyboard("pw123{Enter}");

    expect(
      await screen.findByRole("heading", { name: "Today" }),
    ).toBeInTheDocument();
    expect(calls[0].body).toEqual({
      username: "maria.ops",
      password: "pw123",
    });
    // The follow-up API call carried the bearer token from the login response.
    const metricsCall = calls.find((c) => c.path === "/metrics/values");
    expect(metricsCall?.headers["Authorization"]).toBe("Bearer token-abc");
  });

  it("redirects unauthenticated visitors to /login", () => {
    renderApp("/metrics");
    expect(
      screen.getByRole("heading", { name: "Sign in to Headway" }),
    ).toBeInTheDocument();
  });
});
