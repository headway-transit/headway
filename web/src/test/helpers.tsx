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
  body: unknown;
}

export type RouteHandler =
  | MockedResponse
  | ((call: RecordedCall) => MockedResponse);

/**
 * Install a fetch mock. Routes are keyed "METHOD /path" (query string
 * ignored). Unrouted requests fail the test loudly. Returns the list of
 * recorded calls for assertions on method, headers, and body.
 */
export function mockApi(routes: Record<string, RouteHandler>): RecordedCall[] {
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
          typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      };
      calls.push(call);
      const handler = routes[`${method} ${path}`];
      if (!handler) {
        throw new Error(`Unexpected fetch in test: ${method} ${url}`);
      }
      const result = typeof handler === "function" ? handler(call) : handler;
      return new Response(JSON.stringify(result.body), {
        status: result.status,
        headers: { "Content-Type": "application/json" },
      });
    },
  );
  return calls;
}
