/**
 * The admin surface, enumerated once.
 *
 * WHY THIS FILE EXISTS. The navigation is hand-written JSX, so "every admin
 * function is still reachable" was a claim nobody could check — you would
 * have to read every view and compare it against every route by eye. That is
 * fine until the chrome changes, and the chrome is about to change.
 *
 * So the surface is listed here once, and `admin-reachability.test.tsx`
 * asserts every entry is reachable from the admin hub. Add a screen and
 * forget the menu, and a test fails instead of an operator quietly losing
 * access to something they are the only person authorised to do.
 *
 * This list is NOT authorisation. Every destination is enforced server-side
 * on every call; hiding a door has never been security here. It is an
 * inventory, and its only job is to make loss detectable.
 */

export type AdminDestinationKind =
  /** Has its own route and deep link. */
  | "route"
  /** Lives inside the hub page — no route, so it can only be checked by heading. */
  | "section";

export interface AdminDestination {
  /** Stable key. Never rendered; safe to reference from tests. */
  id: string;
  /** Route path, for `kind: "route"` entries. */
  to?: string;
  /**
   * A distinctive fragment of the visible heading, used by the reachability
   * test. Kept deliberately short so ordinary copy edits do not break it.
   */
  headingMatch: string;
  kind: AdminDestinationKind;
  /**
   * Why it is here, for whoever inherits this. Several of these are the only
   * route to a function — losing one is not a cosmetic regression.
   */
  note: string;
}

export const ADMIN_DESTINATIONS: readonly AdminDestination[] = [
  {
    id: "users",
    to: "/admin/users",
    headingMatch: "Users",
    kind: "route",
    note: "The only way to create an account or change a role. Losing it can lock an agency out of its own installation.",
  },
  {
    id: "sources",
    to: "/admin/sources",
    headingMatch: "Data sources",
    kind: "route",
    note: "What each connected source has delivered. The first screen to check when nothing is ingesting.",
  },
  {
    id: "branding",
    to: "/settings/branding",
    headingMatch: "Branding",
    kind: "route",
    note: "Lives OUTSIDE /admin — easy to miss when refactoring the admin area, which is precisely why it is listed.",
  },
  {
    id: "settings",
    to: "/admin/settings",
    headingMatch: "Settings",
    kind: "route",
    note: "The calculation policy knobs, each audited old->new. Includes the service-day timezone.",
  },
  {
    id: "block-labels",
    to: "/admin/block-labels",
    headingMatch: "Block names",
    kind: "route",
    note: "Upload the trip-to-block mapping. Replaced a command-line tool that was never once run.",
  },
  {
    id: "sso",
    headingMatch: "Single sign-on",
    kind: "section",
    note: "An expandable section on the hub, not a route. Carries provider settings, the show-once secret, and group-to-role mappings.",
  },
  {
    id: "updates",
    headingMatch: "Updates",
    kind: "section",
    note: "Deliberately has no route and no button: a web session must never be able to replace the software it runs in. It states the commands instead.",
  },
] as const;

/** Every admin destination that owns a route (i.e. is deep-linkable). */
export const ADMIN_ROUTES: readonly string[] = ADMIN_DESTINATIONS.filter(
  (d) => d.kind === "route",
).map((d) => d.to as string);
