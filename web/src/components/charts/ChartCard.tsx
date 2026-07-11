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
 */

import { useId, useState } from "react";
import type { ReactNode } from "react";
import { copy } from "../../copy";

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
  children: ReactNode;
}

export function ChartCard({
  heading,
  description,
  table,
  hint,
  children,
}: ChartCardProps) {
  const headingId = useId();
  const [view, setView] = useState<"chart" | "table">("chart");

  return (
    <section className="card chart-card" aria-labelledby={headingId}>
      <h2 id={headingId}>{heading}</h2>
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
