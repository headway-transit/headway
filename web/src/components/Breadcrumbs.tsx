/**
 * Breadcrumbs for deep entities (handoff 0017, design point 4): receipt →
 * lineage, sampling plan → draw → measurements, safety event → correction.
 * The APG breadcrumb pattern: a <nav> landmark holding an ordered list,
 * the current location marked aria-current="page" and not a link.
 *
 * `label` defaults to "Breadcrumb" (the name screen-reader users know the
 * landmark by). Pages that render MORE than one trail (e.g. one per
 * worksheet) must pass distinct labels so the landmarks stay uniquely
 * named (axe: landmark-unique).
 */

import { Link } from "react-router-dom";
import { copy } from "../copy";

export interface Crumb {
  label: string;
  /** Router path for ancestor crumbs; omit (with no href) for the current page. */
  to?: string;
  /** Same-page anchor alternative to `to` (in-page entity chains). */
  href?: string;
}

export function Breadcrumbs({
  trail,
  label = copy.breadcrumbs.label,
}: {
  trail: Crumb[];
  label?: string;
}) {
  return (
    <nav aria-label={label} className="breadcrumbs">
      <ol>
        {trail.map((crumb, index) => {
          const isLast = index === trail.length - 1;
          return (
            <li key={`${crumb.label}:${index}`}>
              {index > 0 && (
                <span aria-hidden="true" className="crumb-sep">
                  ›
                </span>
              )}
              {isLast ? (
                <span aria-current="page">{crumb.label}</span>
              ) : crumb.to ? (
                <Link to={crumb.to}>{crumb.label}</Link>
              ) : crumb.href ? (
                <a href={crumb.href}>{crumb.label}</a>
              ) : (
                <span>{crumb.label}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
