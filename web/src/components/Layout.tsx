/**
 * App shell for the public AND authenticated pages: skip link, header
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
 */

import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { brandingLogoUrl } from "../api/client";
import { loadBranding, useBranding } from "../branding";
import { copy } from "../copy";
import { canCertify, clearSession, useSession } from "../auth/session";
import { initTheme, setTheme, useTheme } from "../theme";
import { clearToasts } from "../toasts";
import { ToastRegion } from "./Toasts";

export function Layout() {
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const branding = useBranding();
  const theme = useTheme();
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

  return (
    <>
      <a className="skip-link" href="#main">
        {copy.skipToContent}
      </a>
      <header className="app-header">
        <span className="brand">
          {/* Decorative: the display name beside it carries the meaning. */}
          {branding?.has_logo && (
            <img className="brand-logo" src={brandingLogoUrl()} alt="" />
          )}
          {displayName}
        </span>
        <nav aria-label="Main">
          <ul>
            {/* Authenticated pages are linked only when signed in — UX, not
                security: the API enforces authentication on every call. */}
            {session && (
              <>
                <li>
                  <NavLink to="/dashboard">{copy.nav.dashboard}</NavLink>
                </li>
                <li>
                  <NavLink to="/metrics">{copy.nav.metrics}</NavLink>
                </li>
                <li>
                  <NavLink to="/compare">{copy.nav.compare}</NavLink>
                </li>
                <li>
                  <NavLink to="/reports/monthly">{copy.nav.reports}</NavLink>
                </li>
                <li>
                  <NavLink to="/safety">{copy.nav.safety}</NavLink>
                </li>
                <li>
                  <NavLink to="/sampling">{copy.nav.sampling}</NavLink>
                </li>
                <li>
                  <NavLink to="/dq">{copy.nav.dq}</NavLink>
                </li>
                <li>
                  <NavLink to="/sandbox">{copy.nav.sandbox}</NavLink>
                </li>
                {/* Shown only to the certifying official — UX, not security:
                    the API enforces the role on POST /certifications and on
                    every branding write. */}
                {canCertify(session) && (
                  <>
                    <li>
                      <NavLink to="/certify">{copy.nav.certify}</NavLink>
                    </li>
                    <li>
                      <NavLink to="/settings/branding">
                        {copy.nav.branding}
                      </NavLink>
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
        <div className="session-info">
          <button
            type="button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark"
              ? copy.theme.switchToLight
              : copy.theme.switchToDark}
          </button>
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
      </header>
      <main id="main" tabIndex={-1} ref={mainRef}>
        <Outlet />
      </main>
      {/* The shell-wide action-confirmation region (handoff 0017 #4):
          persistent aria-live polite, so confirmations pushed from any
          view are reliably announced. */}
      <ToastRegion />
    </>
  );
}
