/**
 * App shell for the public AND authenticated pages: skip link, command bar,
 * navigation, and focus management on route changes (focus moves to <main>
 * so keyboard and screen-reader users land on the new page's content, not
 * back at the top of the tab order). Signed out, only the public-data link
 * and a sign-in link show; signed in, the full navigation does.
 *
 * Handoff 0008 additions:
 * - THEME (pillar A): the effective theme (explicit choice in localStorage,
 *   else prefers-color-scheme) is applied as data-theme on <html>; the
 *   header toggle persists an explicit choice.
 * - BRANDING (pillar C): GET /branding is fetched on load; the display name
 *   replaces "Headway" in the header, the logo renders when one exists, and
 *   the two brand colors are applied as CSS custom-property overrides for
 *   CHROME ONLY (--brand-primary / --brand-accent). Charts never read these
 *   tokens: the chart palette is validated separately for CVD separation
 *   and chart-surface contrast — checks a brand hex has never passed — so
 *   brand != data encoding (see src/branding.ts). The dark theme also pins
 *   its own accent, because the server's contrast guardrail covers the
 *   light surfaces only.
 *
 * HANDOFF 0044 — THE COMMAND BAR (output 1)
 * -----------------------------------------
 * The shell was the most generic element on every screen: a two-row
 * wrapping text nav that spent a full screen-inch on seventeen links before
 * any content appeared, and no wave had ever owned it.
 *
 * It is now two dense rows with different jobs:
 *   1. THE COMMAND BAR — the brand mark, the agency's own name, the room
 *      you are in, and an "as computed" run stamp read from the real
 *      calculation-run record (RunStamp), then the utility cluster
 *      (tour, theme, session).
 *   2. THE NAVIGATION ROW — one row. The rooms people live in stay direct
 *      links; the long tail sits in named groups (NavGroup), which are
 *      disclosures over ordinary links rather than a command palette (the
 *      handoff's open question: a palette hides the map of the product from
 *      an audience one week into Linux).
 *
 * Keyboard order is unchanged in kind: skip link → brand → nav in visual
 * order → utilities → main. Focus visibility is the house ring throughout,
 * and a group's links are genuinely `hidden` when it is closed, so focus
 * never lands somewhere invisible.
 */

import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { CommandRail } from "./CommandRail";
import { setNavMode, useNavMode } from "../nav-mode";
import { brandingLogoUrl } from "../api/client";
import { loadBranding, useBranding } from "../branding";
import { copy } from "../copy";
import { canCertify, canReviewOnly, clearSession, useSession } from "../auth/session";
import { initTheme, setTheme, useTheme } from "../theme";
import { clearToasts } from "../toasts";
import { startTour } from "../tour";
import { NavGroup } from "./NavGroup";
import { RunStamp } from "./RunStamp";
import { ToastRegion } from "./Toasts";
import { TourOverlay } from "./Tour";

/**
 * The room you are in, for the command bar's context slot. Longest prefix
 * wins, so /metrics/{id}/lineage still reads as Metrics. Nothing here is
 * security: it is a label.
 */
const CONTEXTS: { path: string; label: string }[] = [
  { path: "/today", label: copy.nav.today },
  { path: "/review", label: copy.nav.review },
  { path: "/map", label: copy.nav.map },
  { path: "/dashboard", label: copy.nav.dashboard },
  { path: "/metrics", label: copy.nav.metrics },
  { path: "/calc-runs", label: copy.nav.calcRuns },
  { path: "/compare", label: copy.nav.compare },
  { path: "/reports/monthly", label: copy.nav.reports },
  { path: "/safety", label: copy.nav.safety },
  { path: "/sampling", label: copy.nav.sampling },
  { path: "/dq", label: copy.nav.dq },
  { path: "/revenue-review", label: copy.nav.revenueReview },
  { path: "/sandbox", label: copy.nav.sandbox },
  { path: "/attestations", label: copy.nav.attestations },
  { path: "/certifications", label: copy.nav.certifications },
  { path: "/certify", label: copy.nav.certify },
  { path: "/admin", label: copy.nav.admin },
  { path: "/settings/branding", label: copy.nav.admin },
  { path: "/public", label: copy.nav.publicData },
  { path: "/login", label: copy.nav.signIn },
];

function contextLabel(pathname: string): string | null {
  let best: { path: string; label: string } | null = null;
  for (const entry of CONTEXTS) {
    if (pathname === entry.path || pathname.startsWith(`${entry.path}/`)) {
      if (!best || entry.path.length > best.path.length) best = entry;
    }
  }
  return best?.label ?? null;
}

/** Which grouped rooms live behind each nav group (for the current mark). */
const GROUP_PATHS: Record<string, string[]> = {
  reports: ["/reports/monthly", "/safety", "/sampling", "/compare"],
  records: ["/certifications", "/attestations"],
  tools: ["/calc-runs", "/revenue-review", "/sandbox"],
};

function groupHasCurrent(group: string, pathname: string): boolean {
  return (GROUP_PATHS[group] ?? []).some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

export function Layout() {
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const branding = useBranding();
  const theme = useTheme();
  // Opt-in per user (src/nav-mode.ts). Both modes render the same routes and
  // the same authorisation — only the chrome differs.
  const navMode = useNavMode();
  const mainRef = useRef<HTMLElement>(null);
  const isFirstRender = useRef(true);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    mainRef.current?.focus();
    // Action confirmations belong to the page they confirmed on: leaving
    // the page retires them (the deterministic toast lifetime — no timers).
    clearToasts();
  }, [location.pathname]);

  // Theme: resolve (localStorage override, else OS preference) and stamp
  // <html data-theme>. index.html does the same inline pre-paint.
  useEffect(() => {
    initTheme();
  }, []);

  // Branding: fetched once; failures keep the defaults (chrome is cosmetic —
  // never worth blocking the app; the header just says "Headway").
  useEffect(() => {
    void loadBranding();
  }, []);

  // Apply brand colors as custom-property overrides — CHROME ONLY. Charts
  // read --series-*/--chart-* tokens exclusively, never --brand-*.
  useEffect(() => {
    if (!branding) return;
    const root = document.documentElement;
    root.style.setProperty("--brand-primary", branding.primary);
    root.style.setProperty("--brand-accent", branding.accent);
    return () => {
      root.style.removeProperty("--brand-primary");
      root.style.removeProperty("--brand-accent");
    };
  }, [branding]);

  // Themed nav chrome (branding v2 — handoff 0017, design point 7). The
  // server serves ONE chrome color set, validated against itself by the
  // WCAG pair guardrail at write time — for the LIGHT display mode. It is
  // applied only in the mode it was validated for: in dark mode the shell
  // keeps the neutral Headway dark tokens (the known per-mode limitation —
  // the API's chrome_note and the branding room state it; never silently
  // approximated). Charts are untouched: the chrome custom properties are
  // read only by the header styles.
  useEffect(() => {
    const chrome = theme === "dark" ? null : (branding?.chrome ?? null);
    const root = document.documentElement;
    if (!chrome) return;
    root.style.setProperty("--chrome-header-bg", chrome.header_bg);
    root.style.setProperty("--chrome-header-text", chrome.header_fg);
    root.style.setProperty("--chrome-active-accent", chrome.accent);
    root.setAttribute("data-chrome", "on");
    return () => {
      root.style.removeProperty("--chrome-header-bg");
      root.style.removeProperty("--chrome-header-text");
      root.style.removeProperty("--chrome-active-accent");
      root.removeAttribute("data-chrome");
    };
  }, [branding, theme]);

  const handleSignOut = () => {
    clearSession();
    navigate("/login");
  };

  const displayName = branding?.display_name ?? copy.appName;
  const context = contextLabel(location.pathname);
  // The map is the one surface that takes the whole viewport (handoff 0044,
  // output 2): the canvas is the hero, so <main> drops its reading-width
  // column there and the page composes its own grid.
  const fullBleed = location.pathname === "/map";

  return (
    <>
      <a className="skip-link" href="#main">
        {copy.skipToContent}
      </a>
      <header className="app-header">
        {/* ---- row 1: the command bar ---- */}
        <div className="command-bar">
          <span className="brand">
            {/* Decorative: the display name beside it carries the meaning. */}
            {/* logo_version busts the browser cache on replacement (handoff
                0025 #3): a new upload mints a new URL, so the new logo shows
                immediately. */}
            {branding?.has_logo && (
              <img
                className="brand-logo"
                src={brandingLogoUrl(branding.logo_version)}
                alt=""
              />
            )}
            {displayName}
          </span>
          {context && (
            <span className="command-context">
              <span className="visually-hidden">
                {`${copy.shell.contextLabel}: `}
              </span>
              {context}
            </span>
          )}
          {/* The run stamp reads the real calculation-run record; it needs a
              session, so signed-out visitors simply do not see it. */}
          {session && <RunStamp />}
          <div className="session-info">
            {/* "Take the tour" (handoff 0021 #3): restartable any time.
                SPA navigation to /today, then the tour starts at step 1. */}
            {session && (
              <button
                type="button"
                className="link-like"
                onClick={() => {
                  navigate("/today");
                  startTour();
                }}
              >
                {copy.today.takeTourLink}
              </button>
            )}
            <button
              type="button"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark"
                ? copy.theme.switchToLight
                : copy.theme.switchToDark}
            </button>
            {/* Opt-in navigation, placed AFTER the theme control on purpose:
                the keyboard order of this bar is something people have
                muscle memory for, and a beta toggle should not jump the
                queue ahead of a control that has been there for months.
                Signed-in only — the sign-in page has no nav to speak of. */}
            {session && (
              <button
                type="button"
                title={copy.nav_mode.railHint}
                onClick={() =>
                  setNavMode(navMode === "rail" ? "strip" : "rail")
                }
              >
                {navMode === "rail"
                  ? copy.nav_mode.switchToStrip
                  : copy.nav_mode.switchToRail}
              </button>
            )}
            {session ? (
              <>
                <span>
                  {copy.signedInAs(
                    session.username,
                    copy.roleLabels[session.role] ?? session.role,
                  )}
                </span>
                <button type="button" onClick={handleSignOut}>
                  {copy.signOut}
                </button>
              </>
            ) : (
              <NavLink to="/login">{copy.nav.signIn}</NavLink>
            )}
          </div>
        </div>

        {/* ---- row 2: one dense navigation row ---- */}
        {navMode === "rail" ? (
          <CommandRail />
        ) : (
        <nav aria-label="Main" className="nav-strip">
          <ul>
            {/* Authenticated pages are linked only when signed in — UX, not
                security: the API enforces authentication on every call. */}
            {session && (
              <>
                {/* The rooms people live in stay direct links. */}
                {/* A read-only role's home comes first, because it IS their
                    home (handoff 0047): they land here, not in the control
                    room. Offered to readers only — that is UX, never
                    security: /review is composed of reads the API already
                    grants every signed-in account, and any role that opens
                    it directly gets the page. */}
                {canReviewOnly(session) && (
                  <li>
                    <NavLink to="/review">{copy.nav.review}</NavLink>
                  </li>
                )}
                <li>
                  <NavLink to="/today">{copy.nav.today}</NavLink>
                </li>
                <li>
                  <NavLink to="/map">{copy.nav.map}</NavLink>
                </li>
                <li>
                  <NavLink to="/dashboard">{copy.nav.dashboard}</NavLink>
                </li>
                <li>
                  <NavLink to="/metrics">{copy.nav.metrics}</NavLink>
                </li>
                <li>
                  <NavLink to="/dq">{copy.nav.dq}</NavLink>
                </li>
                {/* The long tail, in named groups. */}
                <li>
                  <NavGroup
                    label={copy.shell.groups.reports}
                    containsCurrent={groupHasCurrent(
                      "reports",
                      location.pathname,
                    )}
                    hint={copy.shell.groupHint(copy.shell.groups.reports)}
                    currentHint={copy.shell.groupCurrentHint(
                      copy.shell.groups.reports,
                    )}
                  >
                    <li>
                      <NavLink to="/reports/monthly">
                        {copy.nav.reports}
                      </NavLink>
                    </li>
                    <li>
                      <NavLink to="/safety">{copy.nav.safety}</NavLink>
                    </li>
                    <li>
                      <NavLink to="/sampling">{copy.nav.sampling}</NavLink>
                    </li>
                    <li>
                      <NavLink to="/compare">{copy.nav.compare}</NavLink>
                    </li>
                  </NavGroup>
                </li>
                <li>
                  <NavGroup
                    label={copy.shell.groups.records}
                    containsCurrent={groupHasCurrent(
                      "records",
                      location.pathname,
                    )}
                    hint={copy.shell.groupHint(copy.shell.groups.records)}
                    currentHint={copy.shell.groupCurrentHint(
                      copy.shell.groups.records,
                    )}
                  >
                    {/* The certifications index (handoff 0019 follow-up):
                        any signed-in role reads the record, like the API. */}
                    <li>
                      <NavLink to="/certifications">
                        {copy.nav.certifications}
                      </NavLink>
                    </li>
                    {/* Statistician attestations (handoff 0019): every
                        signed-in role can read the record; the entry form
                        inside is role-gated (UX only — API enforces). */}
                    <li>
                      <NavLink to="/attestations">
                        {copy.nav.attestations}
                      </NavLink>
                    </li>
                  </NavGroup>
                </li>
                <li>
                  <NavGroup
                    label={copy.shell.groups.tools}
                    containsCurrent={groupHasCurrent(
                      "tools",
                      location.pathname,
                    )}
                    hint={copy.shell.groupHint(copy.shell.groups.tools)}
                    currentHint={copy.shell.groupCurrentHint(
                      copy.shell.groups.tools,
                    )}
                  >
                    {/* The calculations room (handoff 0026). Linked for
                        EVERY signed-in role since handoff 0047: the link
                        used to be gated on canComputeFigures, but GET
                        /calc/runs is require_authenticated, so the nav was
                        hiding a surface the API grants — and which
                        calculation version produced a figure, and what a run
                        refused to compute, is evidence. A reader who cannot
                        find it has to be told the URL. The write controls
                        INSIDE the page stay gated exactly as they were (UX
                        only; the API enforces data_steward+ on POST). */}
                    <li>
                      <NavLink to="/calc-runs">{copy.nav.calcRuns}</NavLink>
                    </li>
                    {/* The revenue review queue (handoff 0040): boardings
                        held out of the ridership figure until a person says
                        what they were. */}
                    <li>
                      <NavLink to="/revenue-review">
                        {copy.nav.revenueReview}
                      </NavLink>
                    </li>
                    <li>
                      <NavLink to="/sandbox">{copy.nav.sandbox}</NavLink>
                    </li>
                  </NavGroup>
                </li>
                {/* Shown only to the certifying official — UX, not security:
                    the API enforces the role on POST /certifications and on
                    every admin/branding write. */}
                {canCertify(session) && (
                  <>
                    <li>
                      <NavLink to="/certify">{copy.nav.certify}</NavLink>
                    </li>
                    <li>
                      <NavLink to="/admin">{copy.nav.admin}</NavLink>
                    </li>
                  </>
                )}
              </>
            )}
            {/* Always visible, signed in or out: /public needs no account. */}
            <li>
              <NavLink to="/public">{copy.nav.publicData}</NavLink>
            </li>
          </ul>
        </nav>
        )}
      </header>
      <main
        id="main"
        tabIndex={-1}
        ref={mainRef}
        className={fullBleed ? "page-full" : undefined}
      >
        <Outlet />
      </main>
      {/* The shell-wide action-confirmation region (handoff 0017 #4):
          persistent aria-live polite, so confirmations pushed from any
          view are reliably announced. */}
      <ToastRegion />
      {/* The guided tour (handoff 0021 #3): shell-level so it survives the
          walk from /today into the lineage view. Signed-in only — the tour
          teaches authenticated surfaces. */}
      {session && <TourOverlay />}
    </>
  );
}
