/**
 * The SIMULATED DATA badge (handoff 0005's simulated-data rule): whenever a
 * figure's detail.source_mix contains any source that is not a real feed
 * (any source name containing "simulated" — see isSimulated in
 * src/detail.ts), the figure is marked — text + icon + color, never color
 * alone (WCAG 1.4.1) — everywhere it appears, including any report that
 * contains it. A certifiable figure computed from simulated records is a
 * contradiction the UI must make impossible to miss.
 */

import { copy } from "../copy";

export function SimulatedBadge() {
  return (
    <span className="tag simulated" title={copy.simulated.tooltip}>
      {/* Decorative flag icon (aria-hidden): the text carries the meaning;
          the distinct shape keeps the encoding without color. */}
      <svg
        aria-hidden="true"
        width={14}
        height={14}
        viewBox="0 0 16 16"
        fill="currentColor"
      >
        <path d="M3 1h2v14H3zM6 2h8l-2.5 3L14 8H6z" />
      </svg>
      {copy.simulated.badge}
      {/* Full plain-language explanation for screen readers (the title
          attribute is mouse-hover only). */}
      <span className="visually-hidden"> — {copy.simulated.tooltip}</span>
    </span>
  );
}
