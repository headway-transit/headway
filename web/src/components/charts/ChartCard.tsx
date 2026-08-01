/**
 * The shared chart-card frame (handoff 0008, pillar B): heading,
 * plain-language description, and the chart / table view toggle. The table
 * view is the WCAG-clean equivalent of the chart — every value a tooltip or
 * label shows is reachable there without hovering (dataviz interaction.md:
 * tooltips enhance, they never gate), and it is where each charted figure
 * carries its provenance link.
 *
 * The toggle mirrors the lineage view's pattern: plain buttons with
 * aria-pressed; the pressed one is the only filled one AND keeps its label,
 * so selection is never conveyed by color alone.
 *
 * ATTENTION (handoff 0041): a card may carry a `flag` — an edge-rail on the
 * card FRAME plus a shape + a plain-language line. The rule the rail obeys:
 * glow says "look here", never "this is good" and never "this number is
 * big"; it never sits behind a figure (that would eat the figure's contrast
 * ratio); and the flag always ships an icon and words, so the signal
 * survives for a reader who perceives no glow at all. `prefers-reduced-
 * motion` collapses the pulse to a static rail (see styles.css).
 */

import { useId, useState } from "react";
import type { ReactNode } from "react";
import { copy } from "../../copy";
import { SeverityIcon } from "../SeverityIcon";

export interface ChartTable {
  caption: string;
  columns: string[];
  rows: ReactNode[][];
}

export interface ChartCardProps {
  heading: string;
  description: string;
  table: ChartTable;
  /** Shown under the description in chart view (e.g. the keyboard hint). */
  hint?: string;
  /**
   * Rendered directly under the heading, above the description — e.g. the
   * OpsBadge every operations-metric card must carry (handoff 0014).
   */
  badge?: ReactNode;
  /**
   * An honest attention flag: `tone` picks the semantic status rail
   * (watch | alert — never the identity accent, which encodes nothing) and
   * `label` is the plain-language reason a human should look. Both are
   * required together: a rail with no words would be color alone.
   */
  flag?: { tone: "watch" | "alert"; label: string };
  children: ReactNode;
}

export function ChartCard({
  heading,
  description,
  table,
  hint,
  badge,
  flag,
  children,
}: ChartCardProps) {
  const headingId = useId();
  const [view, setView] = useState<"chart" | "table">("chart");

  return (
    <section
      className={`card chart-card${flag ? ` attn attn-${flag.tone}` : ""}`}
      aria-labelledby={headingId}
    >
      <h2 id={headingId}>{heading}</h2>
      {flag && (
        <p className={`card-flag card-flag-${flag.tone}`}>
          <SeverityIcon severity={flag.tone === "alert" ? "blocking" : "warning"} />
          <span>{flag.label}</span>
        </p>
      )}
      {badge && <p className="chart-card-badge">{badge}</p>}
      <p className="chart-desc">{description}</p>
      <div
        className="view-toggle"
        role="group"
        aria-label={copy.dashboard.viewToggleLabel(heading)}
      >
        <button
          type="button"
          aria-pressed={view === "chart"}
          onClick={() => setView("chart")}
        >
          {copy.dashboard.chartView}
        </button>
        <button
          type="button"
          aria-pressed={view === "table"}
          onClick={() => setView("table")}
        >
          {copy.dashboard.tableView}
        </button>
      </div>
      {view === "chart" ? (
        <>
          {children}
          {hint && <p className="chart-desc">{hint}</p>}
        </>
      ) : (
        /* role/tabIndex: a horizontally scrollable region must be
           keyboard-reachable and named (axe: scrollable-region-focusable) */
        <div
          className="table-wrap"
          role="region"
          aria-label={table.caption}
          tabIndex={0}
        >
          <table>
            <caption>{table.caption}</caption>
            <thead>
              <tr>
                {table.columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, r) => (
                // Rows are static fixtures of served data; index keys are fine.
                // eslint-disable-next-line react/no-array-index-key
                <tr key={r}>
                  {row.map((cell, c) =>
                    c === 0 ? (
                      // eslint-disable-next-line react/no-array-index-key
                      <th key={c} scope="row">
                        {cell}
                      </th>
                    ) : (
                      // eslint-disable-next-line react/no-array-index-key
                      <td key={c}>{cell}</td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
