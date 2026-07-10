/**
 * Authenticated app shell: skip link, header navigation, and focus management
 * on route changes (focus moves to <main> so keyboard and screen-reader users
 * land on the new page's content, not back at the top of the tab order).
 */

import { useEffect, useRef } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { copy } from "../copy";
import { clearSession, useSession } from "../auth/session";

export function Layout() {
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const isFirstRender = useRef(true);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    mainRef.current?.focus();
  }, [location.pathname]);

  const handleSignOut = () => {
    clearSession();
    navigate("/login");
  };

  return (
    <>
      <a className="skip-link" href="#main">
        {copy.skipToContent}
      </a>
      <header className="app-header">
        <span className="brand">{copy.appName}</span>
        <nav aria-label="Main">
          <ul>
            <li>
              <Link to="/metrics">{copy.nav.metrics}</Link>
            </li>
            <li>
              <Link to="/reports/monthly">{copy.nav.reports}</Link>
            </li>
            <li>
              <Link to="/dq">{copy.nav.dq}</Link>
            </li>
          </ul>
        </nav>
        {session && (
          <div className="session-info">
            <span>
              {copy.signedInAs(
                session.username,
                copy.roleLabels[session.role] ?? session.role,
              )}
            </span>
            <button type="button" onClick={handleSignOut}>
              {copy.signOut}
            </button>
          </div>
        )}
      </header>
      <main id="main" tabIndex={-1} ref={mainRef}>
        <Outlet />
      </main>
    </>
  );
}
