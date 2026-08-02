/**
 * The SIGN-IN half of single sign-on (handoff 0046): the button, the hop out
 * to the identity provider, and the hop back at /auth/callback.
 *
 * The properties held here are the ones that decide whether an agency can
 * actually turn this on:
 *
 * - THE LOCAL FORM IS NEVER DEGRADED. It renders and submits whether the
 *   status call says no, fails outright, or never answers at all — because
 *   the installation whose provider is broken is exactly the one whose
 *   administrator has to sign in with a Headway password;
 * - the browser binding (migration 0043) makes the round trip in
 *   sessionStorage and is REMOVED the moment it is used, on every outcome;
 * - `code` and `state` are scrubbed out of the visible URL, and neither
 *   they nor the binding are ever rendered;
 * - a refusal is the API's one generic sentence, shown verbatim, and it
 *   lands the reader back on a working sign-in form with focus on the
 *   message — never on a dead screen.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { AppRoutes } from "../App";
import { copy } from "../copy";
import {
  expectNoAxeViolations,
  mockApi,
  renderApp,
  type MockedResponse,
} from "./helpers";

/** The key src/auth/sso.ts owns. Named here so a rename is a caught break. */
const BROWSER_TOKEN_KEY = "headway-sso-browser-token";
/** Not a credential: it proves only that this browser started this sign-in. */
const BROWSER_TOKEN = "browser-binding-9f2ad4";
const CODE = "authorization-code-4b8e";
const STATE = "state-7c1f";
const CALLBACK_PATH = `/auth/callback?code=${CODE}&state=${STATE}`;
const AUTHORIZATION_URL =
  "https://idp.example.gov/realms/agency/protocol/openid-connect/auth" +
  `?client_id=headway-api&response_type=code&state=${STATE}` +
  "&code_challenge=8Uq0&code_challenge_method=S256";

/**
 * The API's ONE message for every federated failure (services/api
 * headway_api/oidc.py, GENERIC_LOGIN_FAILURE). The UI shows it verbatim and
 * never tries to work out which check failed — that reason is in the audit
 * trail, deliberately.
 */
const GENERIC_REFUSAL =
  "Headway could not sign you in with single sign-on. If you have just " +
  "been given access, it may not have taken effect yet. Please try again, " +
  "and if it keeps failing ask your Headway administrator to check the " +
  "single sign-on configuration — the reason for this failure is recorded " +
  "in Headway's audit trail.";

const SSO_ON = { enabled: true, button_label: "Sign in with County SSO" };
const SSO_OFF = { enabled: false, button_label: "" };

const STARTED = {
  authorization_url: AUTHORIZATION_URL,
  state: STATE,
  browser_token: BROWSER_TOKEN,
};

const FEDERATED_SESSION = {
  access_token: "sso-session-token",
  token_type: "bearer",
  expires_in: 1800,
  username: "sso.steward",
  role: "data_steward",
};

const LOCAL_SESSION = {
  access_token: "local-session-token",
  token_type: "bearer",
  expires_in: 1800,
  username: "vera",
  role: "viewer",
};

afterEach(() => {
  // Module state must not leak between tests, and neither must the binding.
  window.sessionStorage.clear();
});

/** The tour auto-offers on a true first visit; these tests are not about it. */
function skipTour() {
  window.localStorage.setItem("headway-tour-seen", "1");
}

/**
 * Reports the router's current URL so a test can prove what was scrubbed.
 * A test instrument, not part of the page: aria-hidden keeps it out of the
 * accessibility tree and therefore out of the axe gate's landmark check.
 */
function CurrentUrl() {
  const location = useLocation();
  return (
    <span data-testid="current-url" aria-hidden="true">
      {`${location.pathname}${location.search}`}
    </span>
  );
}

function renderAppWithUrl(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
      <CurrentUrl />
    </MemoryRouter>,
  );
}

/** jsdom implements no navigation, so the hop out is observed, not taken. */
function stubProviderHop() {
  const assign = vi.fn();
  // Restored by vi.unstubAllGlobals() in the shared afterEach.
  vi.stubGlobal("location", {
    assign,
    origin: "http://localhost:3000",
    href: "http://localhost:3000/login",
    pathname: "/login",
    search: "",
  });
  return assign;
}

async function signInLocally(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Username"), "vera");
  await user.type(screen.getByLabelText("Password"), "pw123");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("single sign-on: the sign-in screen", () => {
  it("offers no single-sign-on button when the server says it is off", async () => {
    const calls = mockApi({
      "GET /auth/oidc/status": { status: 200, body: SSO_OFF },
    });
    renderApp("/login");

    await waitFor(() =>
      expect(calls.some((c) => c.path === "/auth/oidc/status")).toBe(true),
    );
    // The screen is exactly what it has always been: one button, the local
    // one, and nothing about single sign-on anywhere on it.
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: copy.login.submit }),
    ).toBeInTheDocument();
    expect(screen.queryByText(copy.login.sso.hint)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("still signs someone in locally when the status call is REFUSED", async () => {
    skipTour();
    mockApi({
      // Not a 200 body — a rejection, the way an unreachable API behaves.
      "GET /auth/oidc/status": () =>
        Promise.reject(new Error("connection reset")) as Promise<MockedResponse>,
      "POST /auth/login": { status: 200, body: LOCAL_SESSION },
      "GET /metrics/values": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    renderApp("/login");

    // No error about a feature this reader may not even use, and no button.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await signInLocally(user);
    expect(
      await screen.findByRole("heading", { name: "Today" }),
    ).toBeInTheDocument();
  });

  it("does not wait for the status call: the local form works while it is still in flight", async () => {
    skipTour();
    mockApi({
      // Never answers. The break-glass path must not notice.
      "GET /auth/oidc/status": () => new Promise<MockedResponse>(() => {}),
      "POST /auth/login": { status: 200, body: LOCAL_SESSION },
      "GET /metrics/values": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    renderApp("/login");

    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    await signInLocally(user);
    expect(
      await screen.findByRole("heading", { name: "Today" }),
    ).toBeInTheDocument();
  });

  it("shows the button with the words the administrator chose, beside the local form", async () => {
    mockApi({ "GET /auth/oidc/status": { status: 200, body: SSO_ON } });
    renderApp("/login");

    const button = await screen.findByRole("button", {
      name: SSO_ON.button_label,
    });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("type", "button");
    // The local form is still whole, and still says so.
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: copy.login.submit }),
    ).toBeInTheDocument();
    expect(screen.getByText(copy.login.sso.hint)).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it("falls back to neutral wording when no label is configured", async () => {
    mockApi({
      "GET /auth/oidc/status": {
        status: 200,
        body: { enabled: true, button_label: "  " },
      },
    });
    renderApp("/login");

    expect(
      await screen.findByRole("button", { name: copy.login.sso.button }),
    ).toBeInTheDocument();
  });

  it("stores the browser binding and hands the browser to the provider", async () => {
    const assign = stubProviderHop();
    const calls = mockApi({
      "GET /auth/oidc/status": { status: 200, body: SSO_ON },
      "POST /auth/oidc/start": { status: 200, body: STARTED },
    });
    const user = userEvent.setup();
    renderApp("/login");

    const button = await screen.findByRole("button", {
      name: SSO_ON.button_label,
    });
    await user.click(button);

    await waitFor(() => expect(assign).toHaveBeenCalledWith(AUTHORIZATION_URL));
    expect(calls.find((c) => c.path === "/auth/oidc/start")?.method).toBe(
      "POST",
    );
    // The binding is held for the redirect (migration 0043) and shown to
    // nobody: not in the DOM, not in the URL.
    expect(window.sessionStorage.getItem(BROWSER_TOKEN_KEY)).toBe(
      BROWSER_TOKEN,
    );
    expect(document.body.textContent).not.toContain(BROWSER_TOKEN);
    // Announced, not merely drawn — and focus stays on the control the
    // reader pressed while the browser leaves (aria-disabled, not disabled).
    expect(
      within(screen.getByRole("status")).getByText(copy.login.sso.starting),
    ).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveFocus();
  });

  it("leaves a working local form behind when starting single sign-on fails", async () => {
    skipTour();
    const assign = stubProviderHop();
    mockApi({
      "GET /auth/oidc/status": { status: 200, body: SSO_ON },
      "POST /auth/oidc/start": {
        status: 503,
        body: { detail: GENERIC_REFUSAL },
      },
      "POST /auth/login": { status: 200, body: LOCAL_SESSION },
      "GET /metrics/values": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    renderApp("/login");

    await user.click(
      await screen.findByRole("button", { name: SSO_ON.button_label }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(GENERIC_REFUSAL);
    expect(assign).not.toHaveBeenCalled();
    // Nothing half-written left for the next attempt to trip over.
    expect(window.sessionStorage.getItem(BROWSER_TOKEN_KEY)).toBeNull();
    await signInLocally(user);
    expect(
      await screen.findByRole("heading", { name: "Today" }),
    ).toBeInTheDocument();
  });
});

describe("single sign-on: the callback", () => {
  it("finishes the sign-in, establishes the session, and scrubs the URL", async () => {
    skipTour();
    window.sessionStorage.setItem(BROWSER_TOKEN_KEY, BROWSER_TOKEN);
    const calls = mockApi({
      "POST /auth/oidc/callback": { status: 200, body: FEDERATED_SESSION },
      "GET /metrics/values": { status: 200, body: [] },
    });
    renderAppWithUrl(CALLBACK_PATH);

    expect(
      await screen.findByRole("heading", { name: "Today" }),
    ).toBeInTheDocument();

    // The three parts of the exchange went up exactly once, together.
    const callback = calls.filter((c) => c.path === "/auth/oidc/callback");
    expect(callback).toHaveLength(1);
    expect(callback[0].body).toEqual({
      code: CODE,
      state: STATE,
      browser_token: BROWSER_TOKEN,
    });
    // The session is the one the local path establishes: the next call
    // carries the bearer token from this response.
    expect(
      calls.find((c) => c.path === "/metrics/values")?.headers["Authorization"],
    ).toBe(`Bearer ${FEDERATED_SESSION.access_token}`);
    // Single use on this side too.
    expect(window.sessionStorage.getItem(BROWSER_TOKEN_KEY)).toBeNull();
    // Nothing about the exchange survives in the URL or on the screen.
    expect(screen.getByTestId("current-url")).toHaveTextContent("/today");
    expect(document.body.textContent).not.toContain(CODE);
    expect(document.body.textContent).not.toContain(STATE);
    expect(document.body.textContent).not.toContain(BROWSER_TOKEN);
  });

  it("takes the code and state out of the URL before the exchange, not after", async () => {
    window.sessionStorage.setItem(BROWSER_TOKEN_KEY, BROWSER_TOKEN);
    mockApi({
      // Held open: the screen sits on the callback address with the exchange
      // still in flight, which is precisely when the code must already be
      // gone from the address bar.
      "POST /auth/oidc/callback": () => new Promise<MockedResponse>(() => {}),
    });
    renderAppWithUrl(CALLBACK_PATH);

    await waitFor(() =>
      expect(screen.getByTestId("current-url")).toHaveTextContent(
        "/auth/callback",
      ),
    );
    expect(screen.getByTestId("current-url").textContent).toBe(
      "/auth/callback",
    );
    // And the reader is told where they are while it happens. Same reason as
    // below for waitFor: the focus effect trails the render it belongs to.
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: copy.login.sso.finishingHeading }),
      ).toHaveFocus(),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      copy.login.sso.finishing,
    );
    await expectNoAxeViolations();
  });

  it("returns the reader to a working local form when the exchange is refused", async () => {
    skipTour();
    window.sessionStorage.setItem(BROWSER_TOKEN_KEY, BROWSER_TOKEN);
    mockApi({
      "POST /auth/oidc/callback": {
        status: 401,
        body: { detail: GENERIC_REFUSAL },
      },
      "GET /auth/oidc/status": { status: 200, body: SSO_ON },
      "POST /auth/login": { status: 200, body: LOCAL_SESSION },
      "GET /metrics/values": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    renderAppWithUrl(CALLBACK_PATH);

    // The API's generic sentence, verbatim, with focus on it: a full-page
    // hop would otherwise leave focus on <body> saying nothing.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(GENERIC_REFUSAL);
    // waitFor, not a bare assertion: the element exists one commit before the
    // effect that focuses it has run, so asserting synchronously passes on an
    // idle machine and fails on a loaded one. A flaky test about focus is
    // worse than none — it trains everyone to re-run CI.
    await waitFor(() => expect(alert).toHaveFocus());
    expect(
      screen.getByRole("heading", { name: copy.login.heading }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("current-url")).toHaveTextContent("/login");
    expect(window.sessionStorage.getItem(BROWSER_TOKEN_KEY)).toBeNull();
    await expectNoAxeViolations();

    // Not a dead end: the break-glass path works from right here.
    await signInLocally(user);
    expect(
      await screen.findByRole("heading", { name: "Today" }),
    ).toBeInTheDocument();
  });

  it("refuses without calling the server when this browser holds no binding", async () => {
    const calls = mockApi({
      "GET /auth/oidc/status": { status: 200, body: SSO_ON },
    });
    renderAppWithUrl(CALLBACK_PATH);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      copy.login.sso.failed,
    );
    // A callback someone else arranged never reaches the exchange at all.
    expect(calls.some((c) => c.path === "/auth/oidc/callback")).toBe(false);
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
  });

  it("treats a provider that sends no code as a refusal, and never shows its words", async () => {
    window.sessionStorage.setItem(BROWSER_TOKEN_KEY, BROWSER_TOKEN);
    const calls = mockApi({
      "GET /auth/oidc/status": { status: 200, body: SSO_ON },
    });
    renderAppWithUrl(
      "/auth/callback?error=access_denied&error_description=" +
        encodeURIComponent("Rejected by the tenant sign-in policy"),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      copy.login.sso.failed,
    );
    // Text this screen did not author is never put on it.
    expect(document.body.textContent).not.toContain("tenant sign-in policy");
    expect(calls.some((c) => c.path === "/auth/oidc/callback")).toBe(false);
    // The binding is spent either way — an abandoned attempt leaves nothing.
    expect(window.sessionStorage.getItem(BROWSER_TOKEN_KEY)).toBeNull();
  });

  it("refuses a role this build cannot map, exactly as the local path does", async () => {
    window.sessionStorage.setItem(BROWSER_TOKEN_KEY, BROWSER_TOKEN);
    mockApi({
      "POST /auth/oidc/callback": {
        status: 200,
        body: { ...FEDERATED_SESSION, role: "superuser" },
      },
      "GET /auth/oidc/status": { status: 200, body: SSO_ON },
    });
    renderAppWithUrl(CALLBACK_PATH);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      copy.login.unknownRole("superuser"),
    );
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });
});
