/**
 * Hand-rolled SVG time-series line chart (handoff 0008, pillar B). No chart
 * library — plain SVG + design tokens, the LineageGraph precedent.
 *
 * Dataviz discipline applied here:
 * - ONE y-axis per plot, always (two measures = two charts / small
 *   multiples — never dual-axis). A structural test asserts every chart svg
 *   carries at most one data-axis="y" group.
 * - Marks: 2px round-joined line; end markers r=4 with a 2px surface ring;
 *   recessive solid hairline grid; axis/label text in TEXT tokens, never the
 *   series color. Series colors come ONLY from the validated --series-*
 *   tokens (never --brand-*: brand colors are chrome, not data encodings —
 *   they pass a server-side surface-contrast gate but were never validated
 *   for CVD separation or chart-surface contrast).
 * - Interaction (interaction.md): a crosshair finds the X — the vertical
 *   hairline snaps to the nearest data position and ONE tooltip lists every
 *   series at that X. The hover layer doubles as the keyboard reader
 *   (role="slider": arrow keys walk the points; aria-valuetext announces the
 *   same details the tooltip shows). Tooltips enhance, never gate — the
 *   endpoint is direct-labeled and the ChartCard table view lists every
 *   value.
 * - Direct labels: the endpoint value of each series (≤ 4 series), skipped
 *   when labels would collide (legend + tooltip + table carry it instead).
 * - Legend: rendered by the CALLER for ≥ 2 series; a single series needs no
 *   legend box — the card title names it.
 *
 * NUMBERS STAY SACRED. Every displayed value (tooltip, direct label, table,
 * aria-valuetext) is the API's string VERBATIM, passed in as
 * `point.display`. The parsed `point.y` is GEOMETRY ONLY — it positions
 * marks and is never shown. Axis tick values are chart scaffolding (scale
 * annotations this UI draws), not reported figures.
 */

import { useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import { copy } from "../../copy";

export interface SeriesPoint {
  /** x position (ms epoch of the period start) — geometry only. */
  x: number;
  /** The period, verbatim from the API's ISO date strings. */
  xLabel: string;
  /** The DISPLAYED figure: the API's string verbatim (never recomputed). */
  display: string;
  /** Parsed value for mark positioning ONLY — never displayed. */
  y: number;
}

export interface ChartSeries {
  id: string;
  label: string;
  /** A validated --series-* token, e.g. "var(--series-1)". */
  color: string;
  points: SeriesPoint[];
}

export interface ReferenceLine {
  /** Geometry position on the y scale. */
  y: number;
  /** Plain-language label carrying the verbatim threshold figure. */
  label: string;
}

interface TimeSeriesChartProps {
  series: ChartSeries[];
  /** Accessible name for the reader layer. */
  ariaLabel: string;
  /** Unit label appended to values in tooltip / aria-valuetext. */
  unit: string;
  /** Fixed y maximum (e.g. 100 for percent scales); computed when absent. */
  yMax?: number;
  referenceLine?: ReferenceLine;
}

// Internal coordinate system; the svg scales responsively via viewBox. The
// height includes the x-axis band (the container grows with content — a
// fixed height that clips axis labels is an anti-pattern).
const W = 640;
const H = 240;
const M = { top: 14, right: 96, bottom: 30, left: 56 };
const PLOT_W = W - M.left - M.right;
const PLOT_H = H - M.top - M.bottom;
const END_LABEL_MIN_GAP = 13;

/** Clean tick values (0 / 1,000 / 2,000 …) — axis scaffolding, not figures. */
function niceTicks(maxValue: number): number[] {
  if (maxValue <= 0) return [0, 1];
  const rough = maxValue / 4;
  const power = Math.pow(10, Math.floor(Math.log10(rough)));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) ??
    10 * power;
  const ticks: number[] = [];
  for (let v = 0; v <= maxValue + step * 0.001; v += step) ticks.push(v);
  return ticks;
}

/** Tick label formatting — scale annotation only, never a reported figure. */
function formatTick(value: number): string {
  return value.toLocaleString("en-US");
}

export function TimeSeriesChart({
  series,
  ariaLabel,
  unit,
  yMax,
  referenceLine,
}: TimeSeriesChartProps) {
  // null = crosshair inactive.
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  // Unified x positions across series: the crosshair snaps to these, and one
  // tooltip lists EVERY series at that x.
  const xsSet = new Map<number, string>();
  for (const s of series) {
    for (const p of s.points) xsSet.set(p.x, p.xLabel);
  }
  const xs = [...xsSet.keys()].sort((a, b) => a - b);
  if (xs.length === 0) return null;

  const xMin = xs[0];
  const xMax = xs[xs.length - 1];
  const xSpan = xMax - xMin || 1;
  const dataMax = Math.max(
    ...series.flatMap((s) => s.points.map((p) => p.y)),
    referenceLine?.y ?? 0,
  );
  const ticks = yMax !== undefined ? niceTicks(yMax) : niceTicks(dataMax * 1.05);
  const yTop = yMax !== undefined ? yMax : ticks[ticks.length - 1] || 1;

  const px = (x: number) => M.left + ((x - xMin) / xSpan) * PLOT_W;
  const py = (y: number) => M.top + PLOT_H - (Math.min(y, yTop) / yTop) * PLOT_H;

  // Direct end labels (endpoint value, verbatim): drop a label that would
  // collide with an already-placed one — the legend, tooltip, and table
  // carry it (never stack colliding labels).
  const endLabels: { y: number; text: string; color: string }[] = [];
  for (const s of series) {
    const last = s.points[s.points.length - 1];
    if (!last) continue;
    const y = py(last.y);
    if (endLabels.every((l) => Math.abs(l.y - y) >= END_LABEL_MIN_GAP)) {
      endLabels.push({ y, text: last.display, color: s.color });
    }
  }

  const entriesAt = (x: number) =>
    series
      .map((s) => ({ series: s, point: s.points.find((p) => p.x === x) }))
      .filter(
        (e): e is { series: ChartSeries; point: SeriesPoint } =>
          e.point !== undefined,
      );
  /** The readout at one x — the tooltip's content and the slider's value text. */
  const readoutFor = (idx: number) =>
    copy.dashboard.pointLabel(
      xsSet.get(xs[idx]) ?? "",
      entriesAt(xs[idx])
        .map((e) =>
          series.length > 1
            ? `${e.series.label} ${e.point.display} ${unit}`
            : `${e.point.display} ${unit}`,
        )
        .join(", "),
    );

  const activeX = activeIdx === null ? null : xs[activeIdx];
  const activeEntries = activeX === null ? [] : entriesAt(activeX);
  const activeLabel = activeX === null ? "" : (xsSet.get(activeX) ?? "");

  // ---- pointer + keyboard: the crosshair finds the X ----
  const snapToPointer = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    // jsdom (and a not-yet-laid-out element) reports width 0: snap to the
    // first point rather than dividing by zero.
    const frac =
      rect.width > 0
        ? Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
        : 0;
    const target = xMin + frac * xSpan;
    let best = 0;
    for (let i = 1; i < xs.length; i++) {
      if (Math.abs(xs[i] - target) < Math.abs(xs[best] - target)) best = i;
    }
    setActiveIdx(best);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = activeIdx ?? 0;
    let next: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowUp") {
      next = Math.min(xs.length - 1, activeIdx === null ? 0 : current + 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
      next = Math.max(0, activeIdx === null ? 0 : current - 1);
    } else if (event.key === "Home") {
      next = 0;
    } else if (event.key === "End") {
      next = xs.length - 1;
    }
    if (next !== null) {
      event.preventDefault();
      setActiveIdx(next);
    }
  };

  // Tooltip placement: flip sides past the midpoint so it never leaves the
  // card. Positions are percentages of the responsive width.
  const tooltipOnLeft = activeX !== null && px(activeX) > W * 0.55;

  return (
    <figure className="chart-figure">
      {/* The drawn chart is presentation: the reader layer (role=slider),
          the direct labels, and the ChartCard table view carry the
          accessible equivalent. */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width={W}
        height={H}
        aria-hidden="true"
        focusable="false"
      >
        {/* recessive horizontal grid, one hairline per tick */}
        <g>
          {ticks.map((t) => (
            <line
              key={`grid-${t}`}
              className={t === 0 ? "chart-baseline-line" : "chart-grid-line"}
              x1={M.left}
              y1={py(t)}
              x2={M.left + PLOT_W}
              y2={py(t)}
            />
          ))}
        </g>
        {/* ONE y axis (structural marker; see the no-dual-axis test) */}
        <g data-axis="y">
          {ticks.map((t) => (
            <text
              key={`ytick-${t}`}
              className="chart-axis-text"
              x={M.left - 8}
              y={py(t) + 4}
              textAnchor="end"
            >
              {formatTick(t)}
            </text>
          ))}
        </g>
        {/* x axis: first / middle / last period labels, verbatim */}
        <g data-axis="x">
          {[0, xs.length > 2 ? Math.floor((xs.length - 1) / 2) : -1, xs.length - 1]
            .filter((i, pos, arr) => i >= 0 && arr.indexOf(i) === pos)
            .map((i) => (
              <text
                key={`xtick-${xs[i]}`}
                className="chart-axis-text"
                x={px(xs[i])}
                y={M.top + PLOT_H + 18}
                textAnchor={i === 0 ? "start" : i === xs.length - 1 ? "end" : "middle"}
              >
                {xsSet.get(xs[i])}
              </text>
            ))}
        </g>
        {/* threshold reference line — dashed IS its semantic (grid stays solid) */}
        {referenceLine && (
          <g>
            <line
              className="chart-ref-line"
              x1={M.left}
              y1={py(referenceLine.y)}
              x2={M.left + PLOT_W}
              y2={py(referenceLine.y)}
            />
            <text
              className="chart-ref-label"
              x={M.left + PLOT_W}
              y={py(referenceLine.y) - 5}
              textAnchor="end"
            >
              {referenceLine.label}
            </text>
          </g>
        )}
        {/* series marks: 2px round line + ringed end dot */}
        {series.map((s) => {
          const sorted = [...s.points].sort((a, b) => a.x - b.x);
          const d = sorted
            .map((p, i) => `${i === 0 ? "M" : "L"}${px(p.x)},${py(p.y)}`)
            .join(" ");
          const last = sorted[sorted.length - 1];
          return (
            <g key={s.id}>
              <path className="chart-series-line" d={d} style={{ stroke: s.color }} />
              {last && (
                <circle
                  className="chart-end-dot"
                  cx={px(last.x)}
                  cy={py(last.y)}
                  r={4}
                  style={{ fill: s.color }}
                />
              )}
            </g>
          );
        })}
        {/* direct end labels: the endpoint FIGURE verbatim, in a text token */}
        {endLabels.map((l) => (
          <text
            key={`${l.text}-${l.y}`}
            className="chart-end-label"
            x={M.left + PLOT_W + 8}
            y={l.y + 4}
          >
            {l.text}
          </text>
        ))}
        {/* crosshair + per-series highlight dots at the active x */}
        {activeX !== null && (
          <g>
            <line
              className="chart-crosshair"
              x1={px(activeX)}
              y1={M.top}
              x2={px(activeX)}
              y2={M.top + PLOT_H}
            />
            {activeEntries.map((e) => (
              <circle
                key={e.series.id}
                className="chart-end-dot"
                cx={px(activeX)}
                cy={py(e.point.y)}
                r={4}
                style={{ fill: e.series.color }}
              />
            ))}
          </g>
        )}
      </svg>

      {/* The hover/keyboard reader layer over the plot area. Same details on
          keyboard focus as on hover (aria-valuetext = the tooltip readout). */}
      <div
        className="chart-hover"
        style={{
          left: `${(M.left / W) * 100}%`,
          top: `${(M.top / H) * 100}%`,
          width: `${(PLOT_W / W) * 100}%`,
          height: `${(PLOT_H / H) * 100}%`,
        }}
        role="slider"
        aria-label={ariaLabel}
        aria-orientation="horizontal"
        aria-valuemin={0}
        aria-valuemax={xs.length - 1}
        aria-valuenow={activeIdx ?? 0}
        aria-valuetext={readoutFor(activeIdx ?? 0)}
        tabIndex={0}
        onPointerMove={snapToPointer}
        onPointerDown={snapToPointer}
        onPointerLeave={() => setActiveIdx(null)}
        onKeyDown={onKeyDown}
        onFocus={() => setActiveIdx((idx) => idx ?? 0)}
        onBlur={() => setActiveIdx(null)}
      />

      {/* ONE tooltip, every series at the active x. Values lead (strong),
          series names follow; rows key with a line stroke, not a box. All
          content is rendered as React text nodes (textContent — labels are
          untrusted data, never innerHTML). */}
      {activeX !== null && activeEntries.length > 0 && (
        <div
          className="chart-tooltip"
          style={
            tooltipOnLeft
              ? {
                  right: `${100 - ((px(activeX) - 10) / W) * 100}%`,
                  top: `${(M.top / H) * 100}%`,
                }
              : {
                  left: `${((px(activeX) + 10) / W) * 100}%`,
                  top: `${(M.top / H) * 100}%`,
                }
          }
          aria-hidden="true"
        >
          <p className="tooltip-period">{activeLabel}</p>
          <ul>
            {activeEntries.map((e) => (
              <li key={e.series.id}>
                <span
                  className="line-key"
                  style={{ background: e.series.color }}
                />
                <span className="tooltip-value">
                  {e.point.display} {unit}
                </span>
                {series.length > 1 && (
                  <span className="tooltip-series">{e.series.label}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </figure>
  );
}

/**
 * The legend for ≥ 2 series (a single series never gets a legend box — the
 * card title names it). Line keys mirror the mark; label text stays in text
 * tokens.
 */
export function ChartLegend({ series }: { series: ChartSeries[] }) {
  if (series.length < 2) return null;
  return (
    <ul className="chart-legend">
      {series.map((s) => (
        <li key={s.id}>
          <span className="line-key" style={{ background: s.color }} />
          {s.label}
        </li>
      ))}
    </ul>
  );
}
