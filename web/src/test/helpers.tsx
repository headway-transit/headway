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
  // The map detects the self-hosted basemap at runtime (handoff 0027) with
  // a HEAD of /basemap/region.pmtiles. Default: 404 — no basemap
  // downloaded, the canvas exactly as before. Basemap-present tests
  // override this route (and the ranged GET) explicitly.
  "HEAD /basemap/region.pmtiles": { status: 404, body: null },
  "GET /branding": {
    status: 200,
    body: {
      display_name: "Headway",
      primary: "#1a5fb4",
      accent: "#0b57d0",
      has_logo: false,
    },
  },
  // The dashboard (and /certify's blockers panel) read the DQ tallies from
  // GET /dq/issues/counts (handoff 0030 — the list endpoint pages, so
  // nothing downloads the queue to count it). Default: an empty queue, so
  // tests not about DQ need no route. DQ tests override with real counts.
  "GET /dq/issues/counts": {
    status: 200,
    body: {
      total: 0,
      by_severity: { blocking: 0, warning: 0, info: 0 },
      by_status: { open: 0, owned: 0, resolved: 0, attested: 0 },
      resolution_minutes_total: 0,
    },
  },
  // /map's flagged-findings layer asks for the OPEN BLOCKING findings on
  // every mount (handoff 0043, design point 6), and looks through recent
  // calculation runs for the ones that named a finding. Defaults: an empty
  // queue and no runs, so the many pre-existing map tests keep exercising
  // exactly what they exercised. Findings tests override both.
  "GET /dq/issues": {
    status: 200,
    body: {
      issues: [],
      total: 0,
      limit: 50,
      next_cursor: null,
      has_more: false,
    },
  },
  "GET /calc/runs": { status: 200, body: [] },
  // The dashboard fetches its sparkline history on every mount (handoff
  // 0024 #2); the default is an EMPTY series (no trend rendered), so the
  // many pre-existing dashboard tests keep exercising exactly what they
  // exercised. Sparkline/lens tests override this route with real buckets.
  "GET /metrics/history": (call) => {
    const bucket =
      new URL(call.url, "http://test").searchParams.get("bucket") ?? "month";
    return {
      status: 200,
      body: {
        bucket,
        metric: null,
        scope: null,
        calc_version: null,
        period_from: null,
        period_to: null,
        buckets: [],
        point_count: 0,
        total_matching: 0,
        cap: 5000,
        truncated: false,
        grouping_note:
          "Buckets group persisted figures by the calendar bucket their period starts in. The server never sums, averages, or otherwise derives a new number from grouped figures — every value is a calculation library figure served verbatim with its metric_value_id receipt. A true quarterly or annual rollup is a calculation library job, not this endpoint's.",
        note: null,
      },
    };
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
