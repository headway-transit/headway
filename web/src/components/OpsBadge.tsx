/**
 * The OPERATIONS METRIC badge (handoff 0014, design point 5): every figure
 * with `category === "ops"` carries "Operations metric — not an NTD reported
 * figure" everywhere it appears — table rows, receipts, dashboard cards.
 * Text + icon + color + border, never color alone (WCAG 1.4.1); info tokens
 * (an AA-verified pair in both themes, scripts/check-contrast.mjs). The
 * badge's whole point is that an ops figure must never be mistakable for a
 * certifiable NTD figure.
 */

import { copy } from "../copy";

export function OpsBadge() {
  return (
    <span className="tag ops" title={copy.ops.badgeTooltip}>
      {/* Decorative gauge icon (aria-hidden): the text carries the meaning;
          the distinct shape keeps the encoding without color. */}
      <svg
        aria-hidden="true"
        width={14}
        height={14}
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.6}
      >
        <path d="M2.5 12.5a6 6 0 1 1 11 0" />
        <path d="M8 9.5 11 5" />
        <circle cx="8" cy="10" r="1.1" fill="currentColor" stroke="none" />
      </svg>
      {copy.ops.badge}
      {/* Full plain-language explanation for screen readers (the title
          attribute is mouse-hover only). */}
      <span className="visually-hidden"> — {copy.ops.badgeTooltip}</span>
    </span>
  );
}
