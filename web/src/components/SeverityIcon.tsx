/**
 * Severity icon shapes, shared by the DQ queue and the dashboard's DQ chart
 * legend. Decorative (aria-hidden): the adjacent text carries the meaning.
 * Distinct SHAPES per severity so the encoding survives without color
 * (WCAG 1.4.1 — never color alone).
 */

export function SeverityIcon({ severity }: { severity: string }) {
  const common = {
    "aria-hidden": true,
    width: 14,
    height: 14,
    viewBox: "0 0 16 16",
    fill: "currentColor",
  } as const;
  if (severity === "blocking") {
    // octagon (stop)
    return (
      <svg {...common}>
        <polygon points="5,1 11,1 15,5 15,11 11,15 5,15 1,11 1,5" />
      </svg>
    );
  }
  if (severity === "warning") {
    // triangle
    return (
      <svg {...common}>
        <polygon points="8,1 15,15 1,15" />
      </svg>
    );
  }
  // circle (info / unknown)
  return (
    <svg {...common}>
      <circle cx="8" cy="8" r="7" />
    </svg>
  );
}
