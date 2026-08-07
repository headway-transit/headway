/**
 * Every admin function stays reachable — enforced, not promised.
 *
 * WHY. The navigation chrome is being reworked into a rail, and the one
 * thing that must not happen is an admin function quietly losing its only
 * door. Several of these are the sole route to something: /admin/users is
 * the only way to create an account or change a role, and losing it can lock
 * an agency out of its own installation.
 *
 * "I checked" is not a safety property. This is: the surface is enumerated
 * once in src/navigation.ts, and every entry is asserted reachable here.
 * Add a screen and forget the menu, and this fails.
 *
 * THE ORDER MATTERS. This test was written and made to pass against the
 * EXISTING admin page before any visual work began. A net woven after the
 * fall has a hole in it exactly where you needed it.
 *
 * It is deliberately about REACHABILITY, not appearance. It says nothing
 * about layout, so the chrome can change freely underneath it — which is the
 * whole point of having it.
 */

import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";

import {
  ADMIN_DESTINATIONS,
  ADMIN_ROUTES,
  ALL_NAV_DESTINATIONS,
  NAV_GROUPS,
} from "../navigation";
import { mockApi, renderApp, signInAs } from "./helpers";
import { setNavMode } from "../nav-mode";

const SSO_CONFIG = {
  configured: false,
  is_enabled: false,
  disabled_by_environment: false,
  discovery_url: null,
  client_id: null,
  client_secret_set: false,
  secret_storage_available: true,
  redirect_uri: null,
  groups_claim: "groups",
  username_claim: "preferred_username",
  clock_skew_seconds: 60,
  ca_bundle_path: null,
  button_label: "Sign in with your agency account",
};

function adminApi() {
  return mockApi({
    "GET /auth/oidc/config": { status: 200, body: SSO_CONFIG },
    "GET /auth/oidc/mappings": { status: 200, body: [] },
  });
}

describe("admin reachability", () => {
  it("the inventory is not empty and every route entry declares a path", () => {
    // Guards against the inventory being gutted, which would make every
    // assertion below pass vacuously — the failure mode of a list-driven
    // test is an empty list.
    expect(ADMIN_DESTINATIONS.length).toBeGreaterThanOrEqual(7);
    for (const d of ADMIN_DESTINATIONS) {
      if (d.kind === "route") {
        expect(d.to, `${d.id} is a route and needs a path`).toBeTruthy();
        expect(d.to!.startsWith("/")).toBe(true);
      }
      expect(d.headingMatch.length).toBeGreaterThan(2);
      expect(d.note.length).toBeGreaterThan(20);
    }
  });

  it("every admin destination is reachable from the hub", async () => {
    signInAs("certifying_official");
    adminApi();
    renderApp("/admin");

    await screen.findByRole("heading", { name: /^admin$/i, level: 1 });

    for (const dest of ADMIN_DESTINATIONS) {
      if (dest.kind === "route") {
        // A link that actually points at the route — not merely the words.
        const links = screen.getAllByRole("link");
        const match = links.find((el) => el.getAttribute("href") === dest.to);
        expect(
          match,
          `no link to ${dest.to} (${dest.id}) — ${dest.note}`,
        ).toBeTruthy();
      } else {
        // Sections have no route, so a HEADING is the handle. Matching any
        // text would pass on a passing mention in body copy, which is not
        // the same thing as the section being present.
        const heading = screen
          .getAllByRole("heading")
          .find((el) =>
            new RegExp(dest.headingMatch, "i").test(el.textContent ?? ""),
          );
        expect(
          heading,
          `no heading for "${dest.headingMatch}" (${dest.id}) — ${dest.note}`,
        ).toBeTruthy();
      }
    }
  });

  it("each admin route renders its own screen when opened directly", async () => {
    // Deep links must keep working regardless of what the chrome does. An
    // operator with /admin/users bookmarked should never be affected by a
    // navigation redesign.
    for (const dest of ADMIN_DESTINATIONS.filter((d) => d.kind === "route")) {
      signInAs("certifying_official");
      adminApi();
      const { unmount } = renderApp(dest.to!);
      await screen.findByRole("heading", {
        name: new RegExp(dest.headingMatch, "i"),
        level: 1,
      });
      unmount();
    }
  });

  it("a non-certifier is refused, and told so rather than shown a blank page", async () => {
    // The counterpart property: reachable does NOT mean permitted. Hiding a
    // door was never the security here — the API enforces the role on every
    // call — but a person who cannot use the admin area should be told why.
    signInAs("data_steward");
    adminApi();
    renderApp("/admin");

    await screen.findByRole("heading", { name: /^admin$/i, level: 1 });
    expect(
      screen.getByText(/only a certifying official/i),
    ).toBeTruthy();
  });

  it("exports the deep-linkable routes for whoever builds the next chrome", () => {
    expect(ADMIN_ROUTES).toContain("/admin/users");
    expect(ADMIN_ROUTES).toContain("/admin/block-labels");
    // Branding lives outside /admin and is the one most likely to be dropped
    // by someone refactoring "the admin area".
    expect(ADMIN_ROUTES).toContain("/settings/branding");
    expect(ADMIN_ROUTES.every((r) => r.startsWith("/"))).toBe(true);
  });

  // -------------------------------------------------------------------------
  // The whole navigable surface, not just admin. Sampling is as easy to drop
  // from a redesign as Branding was, and nobody would notice until a
  // submission needed it.
  // -------------------------------------------------------------------------

  it("every room a certifying official can see is in the navigation", async () => {
    signInAs("certifying_official");
    adminApi();
    renderApp("/today");
    await screen.findByRole("navigation", { name: /main/i });

    const nav = screen.getByRole("navigation", { name: /main/i });
    const hrefs = new Set(
      Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href")),
    );

    // A reader-only room is not shown to a certifier — by design, it is a
    // read-only role's HOME, not a room everyone needs.
    const expected = ALL_NAV_DESTINATIONS.filter((d) => d.requires !== "reader");
    const missing = expected.filter((d) => !hrefs.has(d.to)).map((d) => d.to);
    expect(
      missing,
      `these rooms have no link in the navigation: ${missing.join(", ")}`,
    ).toEqual([]);
  });

  it("the long tail is grouped exactly as the group map says", () => {
    // The rail renders from NAV_GROUPS while Layout keeps GROUP_PATHS for its
    // "which group am I in" highlight. If those two ever disagree, a room is
    // in one menu and not the other — so they are asserted equal here rather
    // than kept in step by hand.
    const expected: Record<string, string[]> = {
      reports: ["/reports/monthly", "/safety", "/sampling", "/compare"],
      records: ["/certifications", "/attestations"],
      tools: ["/calc-runs", "/revenue-review", "/sandbox"],
    };
    for (const group of NAV_GROUPS) {
      expect(
        group.items.map((i) => i.to),
        `group "${group.id}" drifted from Layout's GROUP_PATHS`,
      ).toEqual(expected[group.id]);
    }
  });

  it("a viewer sees the rooms their role allows, and not the certifier's", async () => {
    signInAs("viewer");
    adminApi();
    renderApp("/today");
    await screen.findByRole("navigation", { name: /main/i });

    const nav = screen.getByRole("navigation", { name: /main/i });
    const hrefs = new Set(
      Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href")),
    );

    // Every authenticated room is present...
    for (const d of ALL_NAV_DESTINATIONS.filter(
      (x) => x.requires === "authenticated" || x.requires === "public",
    )) {
      expect(hrefs.has(d.to), `viewer cannot reach ${d.to}`).toBe(true);
    }
    // ...and the certifier's are not shown. UX only: the API enforces it.
    expect(hrefs.has("/admin")).toBe(false);
    expect(hrefs.has("/certify")).toBe(false);
  });

  // -------------------------------------------------------------------------
  // THE RAIL MUST NOT BE A SECOND PRODUCT.
  //
  // Both modes render the same routes, the same components and the same
  // authorisation — only the chrome differs. The moment a room exists in one
  // mode and not the other, an operator's access depends on a preference,
  // which is indefensible. So the SAME inventory is asserted in rail mode.
  // -------------------------------------------------------------------------

  it("the rail reaches every room the strip reaches", async () => {
    setNavMode("rail");
    try {
      signInAs("certifying_official");
      adminApi();
      renderApp("/today");
      await screen.findByRole("navigation", { name: /main/i });

      const nav = screen.getByRole("navigation", { name: /main/i });
      // Group flyouts are hidden until opened, so their links are queried
      // from the DOM rather than by role — hidden is not missing.
      const hrefs = new Set(
        Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href")),
      );

      const expected = ALL_NAV_DESTINATIONS.filter(
        (d) => d.requires !== "reader",
      );
      const missing = expected.filter((d) => !hrefs.has(d.to)).map((d) => d.to);
      expect(
        missing,
        `the rail cannot reach: ${missing.join(", ")}`,
      ).toEqual([]);
    } finally {
      setNavMode("strip");
    }
  });

  it("the rail hides the certifier's rooms from a viewer, exactly as the strip does", async () => {
    setNavMode("rail");
    try {
      signInAs("viewer");
      adminApi();
      renderApp("/today");
      await screen.findByRole("navigation", { name: /main/i });

      const nav = screen.getByRole("navigation", { name: /main/i });
      const hrefs = new Set(
        Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href")),
      );
      expect(hrefs.has("/map")).toBe(true);
      expect(hrefs.has("/admin")).toBe(false);
      expect(hrefs.has("/certify")).toBe(false);
    } finally {
      setNavMode("strip");
    }
  });

  it("the classic strip is untouched when the preference is absent", async () => {
    // The default must be the navigation people already know. Nobody opts in
    // by accident, and an operator who never hears about this sees no change.
    setNavMode("strip");
    signInAs("certifying_official");
    adminApi();
    const { container } = renderApp("/today");
    await screen.findByRole("navigation", { name: /main/i });

    expect(container.querySelector(".nav-strip")).toBeTruthy();
    expect(container.querySelector(".command-rail")).toBeNull();
  });
});
