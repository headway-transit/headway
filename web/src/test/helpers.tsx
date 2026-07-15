/**
 * Shared test utilities: app mounting, in-memory auth, a hand-rolled fetch
 * mock keyed by "METHOD /path", and the axe accessibility gate.
 */

import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axe from "axe-core";
import { expect, vi } from "vitest";
import { AppRoutes } from "../App";
import { setSession } from "../auth/session";
import type { Role } from "../api/types";

export function signInAs(role: Role, username = "test.user"): void {
  setSession({ token: "test-token", username, role });
}

export function renderApp(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

/**
 * Axe smoke check. The color-contrast rule is disabled because jsdom has no
 * layout engine to evaluate it; contrast is verified for every design token
 * pair by scripts/check-contrast.mjs (npm run check:contrast) instead.
 */
export async function expectNoAxeViolations(
  container: Element = document.body,
): Promise<void> {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  const violations = results.violations.map(
    (v) => `${v.id} (${v.help}): ${v.nodes.map((n) => n.html).join(" | ")}`,
  );
  expect(violations).toEqual([]);
}

export interface RecordedCall {
  method: string;
  path: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
}

export interface MockedResponse {
  status: number;
  /** JSON body (the default). Omit when `rawBody` carries the response. */
  body?: unknown;
  /**
   * Raw response body for download endpoints (CSV/XLSX exports): served
   * byte for byte instead of JSON.stringify(body). Pair with `headers`
   * (e.g. Content-Type, Content-Disposition).
   */
  rawBody?: string;
  headers?: Record<string, string>;
}

export type RouteHandler =
  | MockedResponse
  | ((call: RecordedCall) => MockedResponse | Promise<MockedResponse>);

/**
 * The app shell fetches GET /branding on every mount (handoff 0008 pillar
 * C), so the mock answers it by default with the server's seeded defaults.
 * Tests exercising branding override the route.
 */
const DEFAULT_ROUTES: Record<string, RouteHandler> = {
  "GET /branding": {
    status: 200,
    body: {
      display_name: "Headway",
      primary: "#1a5fb4",
      accent: "#0b57d0",
      has_logo: false,
    },
  },
};

/**
 * Install a fetch mock. Routes are keyed "METHOD /path" (query string
 * ignored). Unrouted requests fail the test loudly. Returns the list of
 * recorded calls for assertions on method, headers, and body. Multipart
 * bodies (FormData) are recorded as-is; JSON bodies are parsed.
 */
export function mockApi(routes: Record<string, RouteHandler>): RecordedCall[] {
  const allRoutes = { ...DEFAULT_ROUTES, ...routes };
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      const path = url.split("?")[0];
      const call: RecordedCall = {
        method,
        path,
        url,
        headers: Object.fromEntries(
          Object.entries((init?.headers ?? {}) as Record<string, string>),
        ),
        body:
          typeof init?.body === "string"
            ? JSON.parse(init.body)
            : (init?.body ?? undefined),
      };
      calls.push(call);
      const handler = allRoutes[`${method} ${path}`];
      if (!handler) {
        throw new Error(`Unexpected fetch in test: ${method} ${url}`);
      }
      // A handler may return a Promise (e.g. a manually-resolved deferred) so
      // tests can pin response ORDER — the stale-response guard regressions.
      const result =
        typeof handler === "function" ? await handler(call) : handler;
      if (result.rawBody !== undefined) {
        return new Response(result.rawBody, {
          status: result.status,
          headers: result.headers ?? {},
        });
      }
      return new Response(JSON.stringify(result.body), {
        status: result.status,
        headers: { "Content-Type": "application/json", ...result.headers },
      });
    },
  );
  return calls;
}
