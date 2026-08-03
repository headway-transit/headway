/**
 * The router surface stays in declarative mode — and that is a SECURITY
 * control, not a style preference.
 *
 * react-router 7.18.2 carries one open high advisory: GHSA-qwww-vcr4-c8h2,
 * an RSC-mode CSRF bypass covering >=7.12.0 <8.3.0. No fixed version exists —
 * 8.3.0 has never been published, and `latest` is 7.18.2. Downgrading is
 * strictly worse: 7.11.0 sits inside EIGHT advisories including an
 * unauthenticated RCE via vendored turbo-stream (GHSA-49rj-9fvp-4h2h).
 * 7.18.2 is the most-patched version that exists.
 *
 * What makes the advisory unreachable here is that this app uses React
 * Router's DECLARATIVE mode only: components and hooks, no data router, no
 * loaders, no actions, no React Server Components. The vulnerable code path
 * is not compiled in.
 *
 * That argument is only true while it stays true. A future contributor
 * reaching for `createBrowserRouter`, a route `action`, or an RSC entry point
 * would silently invalidate a written risk acceptance nobody re-reads. This
 * test makes the claim enforceable: the day someone needs those APIs, this
 * fails and the security question gets asked again, on purpose.
 *
 * If you are here because this test failed: that is the system working. Do
 * not widen the list to make it pass. Check whether a fixed react-router has
 * shipped, and if not, decide the risk deliberately.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(process.cwd(), "src");

/** Declarative-mode API only. Every entry was verified in use on 2026-08-03. */
const ALLOWED = new Set([
  "BrowserRouter",
  "Link",
  "MemoryRouter",
  "NavLink",
  "Navigate",
  "Outlet",
  "Route",
  "Routes",
  "useLocation",
  "useNavigate",
  "useParams",
  "useSearchParams",
]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(entry) ? [path] : [];
  });
}

describe("the react-router surface", () => {
  const files = sourceFiles(SRC);

  it("imports only declarative-mode APIs", () => {
    const found = new Map<string, string>();
    for (const file of files) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(
        /import\s*\{([^}]*)\}\s*from\s*"react-router(?:-dom)?"/gs,
      )) {
        for (const raw of m[1].split(",")) {
          const name = raw.replace(/\s+as\s+.*/, "").trim();
          if (name && !ALLOWED.has(name)) found.set(name, file);
        }
      }
    }
    expect(
      [...found].map(([name, file]) => `${name} (${file.replace(SRC, "src")})`),
      "A react-router API outside declarative mode is now imported. That may " +
        "move this app onto the code path of GHSA-qwww-vcr4-c8h2, which has " +
        "no fixed release. Do not widen ALLOWED to silence this — re-check " +
        "whether a fixed react-router has shipped, then decide deliberately.",
    ).toEqual([]);
  });
});
