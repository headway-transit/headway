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

import { ADMIN_DESTINATIONS, ADMIN_ROUTES } from "../navigation";
import { mockApi, renderApp, signInAs } from "./helpers";

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
});
