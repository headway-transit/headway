/**
 * Unresolved data-quality issues by severity: thin horizontal stacked bars,
 * hand-rolled SVG (handoff 0008, pillar B).
 *
 * Dataviz discipline:
 * - Thin marks (14px — under the 24px cap), growing from a single baseline.
 * - A 2px SURFACE GAP separates touching segments — the gap does the
 *   separating, never a stroke around the mark.
 * - Severity wears STATUS colors (--chart-status-*), which are RESERVED for
 *   state and always ride with an icon + label (the legend pairs each swatch
 *   with the severity's distinct icon shape and its name — never color
 *   alone). Categorical series tokens are never used for status, and status
 *   tokens never color a non-status series.
 * - Each segment is its own hit target (no crosshair on bars): hover or
 *   keyboard focus lifts the mark and shows its tooltip; every count is also
 *   direct-labeled at the bar end and listed in the ChartCard table view, so
 *   the tooltip never gates a value.
 *
 * The counts are workflow tallies of queue issues (the DqView precedent) —
 * NOT regulatory figures, which would be displayed verbatim from the API
 * instead.
 */

import { useState } from "react";
import { copy } from "../../copy";
import { SeverityIcon } from "../SeverityIcon";

export interface BarSegment {
  severity: string;
  /** Severity display label (icon + label rule). */
  label: string;
  /** Workflow tally (issue count), formatted for display by the caller. */
  count: number;
  displayCount: string;
  /** A reserved --chart-status-* token. */
  color: string;
}

export interface StackedBar {
  key: string;
  /** Row label (workflow status: Open / Owned). */
  label: string;
  segments: BarSegment[];
  /** Total tally for the row, formatted for display. */
  displayTotal: string;
}

export interface SeverityStackedBarProps {
  bars: StackedBar[];
  /** Legend entries (icon + label + swatch), in severity order. */
  legend: { severity: string; label: string; color: string }[];
}

const W = 640;
const BAR_H = 14; // thin mark, under the 24px cap
const ROW_H = 44;
const GAP = 2; // the surface gap between touching segments
const M = { top: 6, right: 72, left: 76, bottom: 6 };
const PLOT_W = W - M.left - M.right;

export function SeverityStackedBar({ bars, legend }: SeverityStackedBarProps) {
  const [active, setActive] = useState<{ bar: string; severity: string } | null>(
    null,
  );

  const maxTotal = Math.max(
    ...bars.map((b) => b.segments.reduce((sum, s) => sum + s.count, 0)),
    1,
  );
  const height = M.top + bars.length * ROW_H + M.bottom;
  const scale = (count: number) => (count / maxTotal) * PLOT_W;

  const activeSegment = active
    ? bars
        .find((b) => b.key === active.bar)
        ?.segments.find((s) => s.severity === active.severity)
    : null;
  const activeBar = active ? bars.find((b) => b.key === active.bar) : null;

  return (
    <>
      {/* Legend: severity = status colors, always icon + label. */}
      <ul className="chart-legend">
        {legend.map((entry) => (
          <li key={entry.severity} className="legend-status">
            <span className="swatch-key" style={{ background: entry.color }} />
            <SeverityIcon severity={entry.severity} />
            {entry.label}
          </li>
        ))}
      </ul>
      <figure className="chart-figure">
        <svg viewBox={`0 0 ${W} ${height}`} width={W} height={height} role="list" aria-label={copy.dashboard.dq.heading}>
          {bars.map((bar, rowIdx) => {
            const y = M.top + rowIdx * ROW_H + (ROW_H - BAR_H) / 2;
            let cursor = M.left;
            const rects = bar.segments
              .filter((s) => s.count > 0)
              .map((s) => {
                const width = Math.max(scale(s.count) - GAP, 1);
                const x = cursor;
                cursor += scale(s.count);
                return { segment: s, x, width };
              });
            return (
              <g key={bar.key} role="listitem" aria-label={`${bar.label}: ${bar.displayTotal}`}>
                {/* row label — text token, never a data color */}
                <text
                  className="chart-axis-text"
                  x={M.left - 10}
                  y={y + BAR_H - 3}
                  textAnchor="end"
                >
                  {bar.label}
                </text>
                {rects.map(({ segment, x, width }) => {
                  const isActive =
                    active?.bar === bar.key &&
                    active.severity === segment.severity;
                  return (
                    <g
                      key={segment.severity}
                      className="dq-bar-segment"
                      role="img"
                      aria-label={copy.dashboard.dq.segmentLabel(
                        segment.label,
                        segment.displayCount,
                        bar.label.toLowerCase(),
                      )}
                      tabIndex={0}
                      onPointerEnter={() =>
                        setActive({ bar: bar.key, severity: segment.severity })
                      }
                      onPointerLeave={() => setActive(null)}
                      onFocus={() =>
                        setActive({ bar: bar.key, severity: segment.severity })
                      }
                      onBlur={() => setActive(null)}
                    >
                      {/* The hit target includes the gap and clears ~24px. */}
                      <rect
                        x={x - GAP}
                        y={y - 6}
                        width={width + 2 * GAP}
                        height={BAR_H + 12}
                        fill="transparent"
                      />
                      <rect
                        x={x}
                        y={y}
                        width={width}
                        height={BAR_H}
                        rx={isActive ? 1 : 0}
                        style={{ fill: segment.color }}
                      />
                    </g>
                  );
                })}
                {/* direct label: the row's total tally at the bar end */}
                <text
                  className="chart-end-label"
                  x={cursor + 8}
                  y={y + BAR_H - 3}
                >
                  {bar.displayTotal}
                </text>
              </g>
            );
          })}
        </svg>
        {/* One tooltip for the hovered/focused mark — the mark is the hit
            target on bars (no crosshair). Content mirrors the aria-label. */}
        {active && activeSegment && activeBar && (
          <div className="chart-tooltip" style={{ left: `${(M.left / W) * 100}%`, top: 0 }} aria-hidden="true">
            <p className="tooltip-period">{activeBar.label}</p>
            <ul>
              <li>
                <span
                  className="swatch-key"
                  style={{ background: activeSegment.color }}
                />
                <span className="tooltip-value">{activeSegment.displayCount}</span>
                <span className="tooltip-series">{activeSegment.label}</span>
              </li>
            </ul>
          </div>
        )}
      </figure>
    </>
  );
}
