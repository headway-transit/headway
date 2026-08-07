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


// ---------------------------------------------------------------------------
// The WHOLE navigable surface, not just admin.
//
// Added when the chrome moved to a rail. The admin inventory above proved its
// worth immediately — it catches seven kinds of loss — but the same argument
// applies to every room: Sampling is as easy to drop from a redesign as
// Branding was, and nobody would notice until a submission needed it.
//
// This mirrors the structure the nav strip already had (GROUP_PATHS in
// Layout.tsx): six rooms people live in, three named groups for the long
// tail, then the certifying official's rooms and the public page. The rail
// renders FROM this list, so the list and the menu cannot disagree.
//
// `requires` is UX only, exactly as the nav strip's gating always was — the
// API enforces every role on every call, and any account that opens a URL
// directly gets whatever the server grants it. Hiding a door has never been
// the security here.
// ---------------------------------------------------------------------------

export type NavAudience =
  /** Signed in, any role. */
  | "authenticated"
  /** A read-only role's home. */
  | "reader"
  /** Certifying official only (UX gating; the API enforces it too). */
  | "certifier"
  /** No account needed. */
  | "public";

export interface NavDestination {
  to: string;
  /** Distinctive fragment of the visible label, for the reachability test. */
  labelMatch: string;
  requires: NavAudience;
  /**
   * One line saying what the room is FOR, in the operator's words.
   *
   * Shown on the rail's flyout cards. A menu that only lists names makes you
   * open a room to find out whether it was the one you wanted; a menu that
   * says what each room does answers before the trip. Only the grouped
   * rooms need these — the primary rooms are one click away and named
   * plainly enough.
   */
  blurb?: string;
}

export interface NavGroupSpec {
  /** Matches the existing GROUP_PATHS keys, so the two cannot drift. */
  id: "reports" | "records" | "tools";
  labelMatch: string;
  items: readonly NavDestination[];
}

/** Rooms that stay one click away — the ones people live in all day. */
export const NAV_PRIMARY: readonly NavDestination[] = [
  { to: "/review", labelMatch: "Review", requires: "reader" },
  { to: "/today", labelMatch: "Today", requires: "authenticated" },
  { to: "/map", labelMatch: "Map", requires: "authenticated" },
  { to: "/dashboard", labelMatch: "Dashboard", requires: "authenticated" },
  { to: "/metrics", labelMatch: "Metrics", requires: "authenticated" },
  { to: "/dq", labelMatch: "Data quality", requires: "authenticated" },
] as const;

/** The long tail, in the groups the nav strip already used. */
export const NAV_GROUPS: readonly NavGroupSpec[] = [
  {
    id: "reports",
    labelMatch: "Reports",
    items: [
      {
        to: "/reports/monthly",
        labelMatch: "Monthly",
        requires: "authenticated",
        blurb: "Passenger trips, revenue miles and hours for a reporting month.",
      },
      {
        to: "/safety",
        labelMatch: "Safety",
        requires: "authenticated",
        blurb: "Events, how each was classified, and the rule behind it.",
      },
      {
        to: "/sampling",
        labelMatch: "Sampling",
        requires: "authenticated",
        blurb: "Draw a plan, record measurements, estimate passenger miles.",
      },
      {
        to: "/compare",
        labelMatch: "Compare",
        requires: "authenticated",
        blurb: "One figure against another period, with both receipts.",
      },
    ],
  },
  {
    id: "records",
    labelMatch: "Records",
    items: [
      {
        to: "/certifications",
        labelMatch: "Certifications",
        requires: "authenticated",
        blurb: "Every signed submission: who signed, what it covered, when.",
      },
      {
        to: "/attestations",
        labelMatch: "Attestations",
        requires: "authenticated",
        blurb: "The statistician\u2019s record for a sampling plan.",
      },
    ],
  },
  {
    id: "tools",
    labelMatch: "Tools",
    items: [
      {
        to: "/calc-runs",
        labelMatch: "Calculations",
        requires: "authenticated",
        blurb: "Which version produced a figure, and what a run refused to compute.",
      },
      {
        to: "/revenue-review",
        labelMatch: "Revenue",
        requires: "authenticated",
        blurb: "Boardings the calculation would not decide alone.",
      },
      {
        to: "/sandbox",
        labelMatch: "Sandbox",
        requires: "authenticated",
        blurb: "Model a policy change. Nothing here is saved or reported.",
      },
    ],
  },
] as const;

/** The certifying official's rooms, and the page that needs no account. */
export const NAV_TAIL: readonly NavDestination[] = [
  { to: "/certify", labelMatch: "Certify", requires: "certifier" },
  { to: "/admin", labelMatch: "Admin", requires: "certifier" },
  { to: "/public", labelMatch: "Public", requires: "public" },
] as const;

/** Every navigable destination, flattened. */
export const ALL_NAV_DESTINATIONS: readonly NavDestination[] = [
  ...NAV_PRIMARY,
  ...NAV_GROUPS.flatMap((g) => g.items),
  ...NAV_TAIL,
];
