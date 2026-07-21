/**
 * Skeleton loading states (handoff 0021, design point 2): the shape of the
 * content that is coming, instead of a bare "Loading…" line. Used on the
 * main views while their first fetch is in flight.
 *
 * Accessibility (binding):
 * - The skeleton blocks are DECORATIVE (aria-hidden); the loading state is
 *   announced by a visually-hidden status line carrying the view's own
 *   plain-language loading text — screen-reader users get words, never
 *   shapes.
 * - The shimmer is CSS-only and lives entirely behind
 *   prefers-reduced-motion: reduced motion gets a static placeholder
 *   (instant, not "slower").
 * - Skeletons never imitate a figure: no fake numbers, no fake text — grey
 *   blocks only, replaced by real content (or a verbatim error) the moment
 *   the fetch settles.
 */

import { copy } from "../copy";

export interface SkeletonProps {
  /** The plain-language loading announcement (defaults to copy.loading). */
  label?: string;
  /** Layout shape: stat/briefing cards, table rows, or plain text lines. */
  variant?: "cards" | "table" | "lines";
  /** How many cards / rows / lines to sketch. */
  count?: number;
}

function CardShapes({ count }: { count: number }) {
  return (
    <div className="skeleton-grid">
      {Array.from({ length: count }, (_, i) => (
        <div className="card skeleton-card" key={i}>
          <span className="skeleton skeleton-line skeleton-w-40" />
          <span className="skeleton skeleton-figure" />
          <span className="skeleton skeleton-line skeleton-w-80" />
          <span className="skeleton skeleton-line skeleton-w-60" />
        </div>
      ))}
    </div>
  );
}

function TableShapes({ count }: { count: number }) {
  return (
    <div className="card skeleton-card">
      {Array.from({ length: count }, (_, i) => (
        <span className="skeleton skeleton-line skeleton-row" key={i} />
      ))}
    </div>
  );
}

function LineShapes({ count }: { count: number }) {
  return (
    <div className="skeleton-lines">
      {Array.from({ length: count }, (_, i) => (
        <span
          className={`skeleton skeleton-line ${i % 2 ? "skeleton-w-60" : "skeleton-w-80"}`}
          key={i}
        />
      ))}
    </div>
  );
}

export function Skeleton({
  label = copy.loading,
  variant = "lines",
  count = 3,
}: SkeletonProps) {
  return (
    <div className="skeleton-group">
      {/* The words carry the state; role="status" announces politely. */}
      <p role="status" className="visually-hidden">
        {label}
      </p>
      <div aria-hidden="true">
        {variant === "cards" && <CardShapes count={count} />}
        {variant === "table" && <TableShapes count={count} />}
        {variant === "lines" && <LineShapes count={count} />}
      </div>
    </div>
  );
}
