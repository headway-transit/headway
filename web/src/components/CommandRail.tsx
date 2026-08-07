/**
 * The command rail — navigation laid out like a console, not a website.
 *
 * WHY A RAIL. The top edge is the most valuable strip on an operations
 * screen, and a menu should not own it. A rail also scales: this app has
 * twenty rooms and the strip had already started folding them into
 * disclosure groups that an operator reported he could not see.
 *
 * IT RENDERS FROM THE INVENTORY. Every entry comes from src/navigation.ts,
 * the same list admin-reachability.test.tsx asserts against. The rail cannot
 * drift from the menu it replaces, because there is only one list.
 *
 * ROLE GATING HERE IS UX, NEVER SECURITY — exactly as it always was in the
 * strip. The API enforces every role on every call, and anyone who opens a
 * URL directly gets whatever the server grants them. This only decides what
 * is worth showing.
 *
 * MOTION CARRIES MEANING. The flyout wipes out from the rail edge rather
 * than fading, because direction is information: the panel belongs to the
 * button that opened it. Under prefers-reduced-motion it simply appears.
 */

import { useEffect, useRef, useState, type ReactElement } from "react";
import { NavLink, useLocation } from "react-router-dom";

import {
  NAV_GROUPS,
  NAV_PRIMARY,
  NAV_TAIL,
  type NavAudience,
  type NavDestination,
} from "../navigation";
import { canCertify, canReviewOnly, useSession } from "../auth/session";
import { copy } from "../copy";

/** Short glyphs. Drawn rather than emoji: emoji render differently on every
 *  platform and read as decoration in a room that is meant to be operated. */
const GLYPH: Record<string, ReactElement> = {
  "/review": <path d="M4 6h16M4 12h16M4 18h10" />,
  "/today": <path d="M12 3v9l5 3M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />,
  "/map": <path d="M9 3L3 6v15l6-3 6 3 6-3V3l-6 3-6-3z" />,
  "/dashboard": <path d="M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-4H4zM14 8h6V4h-6z" />,
  "/metrics": <path d="M4 19V5M4 19h16M8 15l3-4 3 3 5-7" />,
  "/dq": <path d="M12 3l8 4v6c0 4-3.5 7-8 8-4.5-1-8-4-8-8V7z M9 12l2 2 4-4" />,
  reports: <path d="M6 3h9l4 4v14H6z M15 3v4h4 M9 13h7M9 17h5" />,
  records: <path d="M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z M4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7" />,
  tools: <path d="M14.7 6.3a4 4 0 01-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 015.4-5.4z" />,
  "/certify": <path d="M9 12l2 2 4-4 M12 3l8 4v6c0 4-3.5 7-8 8-4.5-1-8-4-8-8V7z" />,
  "/admin": <path d="M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-2.9 1.2v.2a2 2 0 11-4 0v-.1a1.7 1.7 0 00-3-1.2l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00-1.2-2.9H3a2 2 0 110-4h.1a1.7 1.7 0 001.2-3l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 002.9-1.2V3a2 2 0 114 0v.1a1.7 1.7 0 003 1.2l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 001.2 2.9H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" />,
  "/public": <path d="M12 21a9 9 0 100-18 9 9 0 000 18z M3 12h18 M12 3a14 14 0 000 18 14 14 0 000-18z" />,
};

function Glyph({ id }: { id: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="rail-glyph">
      {GLYPH[id] ?? <circle cx="12" cy="12" r="8" />}
    </svg>
  );
}

function label(dest: NavDestination): string {
  const map: Record<string, string> = {
    "/review": copy.nav.review,
    "/today": copy.nav.today,
    "/map": copy.nav.map,
    "/dashboard": copy.nav.dashboard,
    "/metrics": copy.nav.metrics,
    "/dq": copy.nav.dq,
    "/reports/monthly": copy.nav.reports,
    "/safety": copy.nav.safety,
    "/sampling": copy.nav.sampling,
    "/compare": copy.nav.compare,
    "/certifications": copy.nav.certifications,
    "/attestations": copy.nav.attestations,
    "/calc-runs": copy.nav.calcRuns,
    "/revenue-review": copy.nav.revenueReview,
    "/sandbox": copy.nav.sandbox,
    "/certify": copy.nav.certify,
    "/admin": copy.nav.admin,
    "/public": copy.nav.publicData,
  };
  return map[dest.to] ?? dest.labelMatch;
}

export function CommandRail() {
  const session = useSession();
  const location = useLocation();
  const [open, setOpen] = useState<string | null>(null);
  const railRef = useRef<HTMLElement>(null);

  // A room change closes the flyout: the panel did its job.
  useEffect(() => setOpen(null), [location.pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    const onClick = (e: MouseEvent) => {
      if (!railRef.current?.contains(e.target as Node)) setOpen(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  function allowed(requires: NavAudience): boolean {
    if (requires === "public") return true;
    if (!session) return false;
    if (requires === "reader") return canReviewOnly(session);
    if (requires === "certifier") return canCertify(session);
    return true;
  }

  const primary = NAV_PRIMARY.filter((d) => allowed(d.requires));
  const tail = NAV_TAIL.filter((d) => allowed(d.requires));
  const groups = session ? NAV_GROUPS : [];

  return (
    <nav aria-label="Main" className="command-rail" ref={railRef}>
      <ul className="rail-list">
        {primary.map((dest) => (
          <li key={dest.to}>
            <NavLink to={dest.to} className="rail-item">
              <Glyph id={dest.to} />
              <span>{label(dest)}</span>
            </NavLink>
          </li>
        ))}

        {groups.map((group) => {
          const isOpen = open === group.id;
          const holdsCurrent = group.items.some(
            (i) =>
              location.pathname === i.to ||
              location.pathname.startsWith(`${i.to}/`),
          );
          return (
            <li key={group.id}>
              <button
                type="button"
                className="rail-item rail-group-button"
                aria-expanded={isOpen}
                aria-controls={`rail-fly-${group.id}`}
                data-current={holdsCurrent || undefined}
                onClick={() => setOpen(isOpen ? null : group.id)}
              >
                <Glyph id={group.id} />
                <span>{copy.shell.groups[group.id]}</span>
              </button>
              <div
                id={`rail-fly-${group.id}`}
                className="rail-flyout"
                data-open={isOpen}
                hidden={!isOpen}
              >
                <p className="rail-fly-title">{copy.shell.groups[group.id]}</p>
                {/* Cards, not a list of names. A menu that only lists rooms
                    makes you open one to find out whether it was the one you
                    wanted; a menu that says what each room is FOR answers
                    before the trip. */}
                <ul className="rail-fly-cards">
                  {group.items.map((item) => (
                    <li key={item.to}>
                      <NavLink to={item.to}>
                        <span className="rail-fly-name">{label(item)}</span>
                        {item.blurb && (
                          <span className="rail-fly-blurb">{item.blurb}</span>
                        )}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            </li>
          );
        })}

        {tail.map((dest) => (
          <li key={dest.to}>
            <NavLink to={dest.to} className="rail-item">
              <Glyph id={dest.to} />
              <span>{label(dest)}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
