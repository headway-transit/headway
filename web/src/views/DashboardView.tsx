/**
 * /dashboard (handoff 0008, pillar B): the agency's figures at a glance, for
 * any authenticated role.
 *
 *   1. Hero stat tiles — the latest CERTIFIED VRM / VRH / UPT, each the
 *      API's string verbatim, SimulatedBadge where flagged, provenance link
 *      on every tile (no figure without its "explain this number" path).
 *   2. UPT over time — single-series line (slot 1; the title names it — no
 *      legend box for one series) with crosshair + tooltip.
 *   3. VRM & VRH — SMALL MULTIPLES: two panels, one measure and ONE axis
 *      each. Never dual-axis: miles and hours on one plot would invent a
 *      correlation the data doesn't state.
 *   4. Coverage over time — the coverage ratio from each figure's detail
 *      JSONB, with the coverage threshold as a dashed reference line.
 *   5. Unresolved DQ issues by severity — thin stacked bars in RESERVED
 *      status colors (icon + label, never color alone).
 *
 * NUMBERS STAY SACRED. Every displayed figure (tile, tooltip, direct label,
 * table cell) is the API's string verbatim; coverage percentages come from
 * the string-only decimal shift in src/format.ts. The ONLY numeric parses in
 * this file feed chart GEOMETRY (mark positions) and are never displayed.
 * Series colors come only from the validated --series-* tokens and severity
 * from the reserved --chart-status-* tokens — never brand colors (brand is
 * chrome; the chart palette is validated separately for CVD and surface
 * contrast).
 */

import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, listDqIssues, listMetricValues } from "../api/client";
import type { DqIssue, MetricValue } from "../api/types";
import {
  GRANULARITIES,
  misalignedCount,
  overlapsRange,
} from "../reports/granularity";
import type { Granularity } from "../reports/granularity";
import { ChartCard } from "../components/charts/ChartCard";
import {
  ChartLegend,
  TimeSeriesChart,
} from "../components/charts/TimeSeriesChart";
import type { ChartSeries, SeriesPoint } from "../components/charts/TimeSeriesChart";
import { SeverityStackedBar } from "../components/charts/SeverityStackedBar";
import type { StackedBar } from "../components/charts/SeverityStackedBar";
import { OpsBadge } from "../components/OpsBadge";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { Skeleton } from "../components/Skeleton";
import { copy } from "../copy";
import { isOps, isSimulated, refusalLines } from "../detail";
import { detailValueToString, ratioToPercentString } from "../format";

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function unitLabel(code: string): string {
  return copy.unitLabels[code] ?? code;
}

function periodLabel(value: MetricValue): string {
  return value.period_start === value.period_end
    ? value.period_start
    : `${value.period_start} to ${value.period_end}`;
}

/** Provenance link for one charted/tiled figure (table view + tiles). */
function ExplainLink({ value }: { value: MetricValue }) {
  return (
    <Link to={`/metrics/${value.metric_value_id}/lineage`}>
      {copy.dashboard.explainLink}
      <span className="visually-hidden">
        {` — ${metricLabel(value.metric)}, ${periodLabel(value)}`}
      </span>
    </Link>
  );
}

/**
 * Chart points for one metric's values. `y = Number(value)` is GEOMETRY
 * ONLY (mark position); the displayed figure stays `value.value` verbatim.
 * A value that does not parse cannot be positioned and is charted nowhere —
 * but it still appears, verbatim, in the table view (nothing is hidden).
 */
function seriesPoints(values: MetricValue[]): SeriesPoint[] {
  return values
    .map((v) => ({
      x: Date.parse(v.period_start),
      xLabel: periodLabel(v),
      display: v.value,
      y: Number(v.value),
    }))
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
    .sort((a, b) => a.x - b.x);
}

/** Latest certified figure of a metric — selection only, no arithmetic. */
function latestCertified(values: MetricValue[], metric: string): MetricValue | null {
  const certified = values.filter(
    (v) => v.metric === metric && v.certification_status === "certified",
  );
  if (certified.length === 0) return null;
  return certified.reduce((latest, v) =>
    v.period_end > latest.period_end ? v : latest,
  );
}

/** Workflow tallies for display (the DqView precedent) — never figures. */
function formatCount(count: number): string {
  return count.toLocaleString("en-US");
}

const SEVERITY_ORDER = ["blocking", "warning", "info"] as const;
const SEVERITY_COLOR: Record<string, string> = {
  blocking: "var(--chart-status-blocking)",
  warning: "var(--chart-status-warning)",
  info: "var(--chart-status-info)",
};

/**
 * The honest coarse-bucket note (docket #1). Bucketing is date math on
 * period boundaries ONLY: when the reported periods do not line up with the
 * selected granularity, the chart keeps showing every reported period
 * verbatim and says so — summing display values into a coarser bucket
 * client-side is FORBIDDEN (it would invent a figure nobody computed).
 * See src/reports/granularity.ts.
 */
function AsReportedNote({
  rows,
  granularity,
}: {
  rows: MetricValue[];
  granularity: Granularity;
}) {
  if (rows.length === 0 || misalignedCount(rows, granularity) === 0) {
    return null;
  }
  return (
    <p className="chart-desc as-reported-note">
      {copy.dashboard.filters.asReported(
        formatCount(rows.length),
        copy.dashboard.filters.granularityOptions[granularity] ?? granularity,
      )}
    </p>
  );
}

/**
 * The one filter row above the charts (dataviz interaction.md): date range
 * first, then the period-granularity aria-pressed group. Everything below
 * the row — every chart AND its table view — re-renders against the same
 * slice. Filter changes never recolor a series: colors are assigned to the
 * ENTITY (--series-* slot per metric) and never re-derived from what is
 * currently visible (recolor-on-filter is the anti-pattern).
 */
function ChartFilterRow({
  from,
  to,
  granularity,
  onFrom,
  onTo,
  onGranularity,
}: {
  from: string;
  to: string;
  granularity: Granularity;
  onFrom: (value: string) => void;
  onTo: (value: string) => void;
  onGranularity: (value: Granularity) => void;
}) {
  const fromId = useId();
  const toId = useId();
  return (
    <div
      className="chart-filters"
      role="group"
      aria-label={copy.dashboard.filters.rowLabel}
    >
      <div className="date-range-field">
        <label htmlFor={fromId}>{copy.dashboard.filters.fromLabel}</label>
        <input
          id={fromId}
          type="date"
          value={from}
          onChange={(e) => onFrom(e.target.value)}
        />
      </div>
      <div className="date-range-field">
        <label htmlFor={toId}>{copy.dashboard.filters.toLabel}</label>
        <input
          id={toId}
          type="date"
          value={to}
          onChange={(e) => onTo(e.target.value)}
        />
      </div>
      <div
        className="filter-bar"
        role="group"
        aria-label={copy.dashboard.filters.granularityLabel}
      >
        <span className="filter-bar-label">
          {copy.dashboard.filters.granularityLabel}:
        </span>
        {GRANULARITIES.map((g) => (
          <button
            key={g}
            type="button"
            aria-pressed={granularity === g}
            onClick={() => onGranularity(g)}
          >
            {copy.dashboard.filters.granularityOptions[g]}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * Plain-language scope label for an ops row ("route:66" → "Route 66"); an
 * unknown scope shape falls back to the raw scope, honestly.
 */
function opsScopeLabel(scope: string): string {
  if (scope === "agency") return copy.ops.dashboard.agencyScope;
  if (scope.startsWith("route:")) {
    return copy.ops.dashboard.routeScope(scope.slice("route:".length));
  }
  return scope;
}

/**
 * One operations-metric card (handoff 0014, design point 5): the badge, the
 * latest agency-wide figure VERBATIM with its plain-language context, the
 * agency figure over time (existing chart component, validated palette),
 * the derivation's refusal accounting — shown, never hidden — and a table
 * of every route-level figure with its provenance link.
 */
function OpsMetricCard({
  values,
  heading,
  description,
  emptyText,
  tableCaption,
  statLines,
  seriesColor,
  unit,
  yMax,
  valueSuffix,
}: {
  /** Every ops row of ONE metric in the selected date slice, period-sorted. */
  values: MetricValue[];
  heading: string;
  description: string;
  emptyText: string;
  tableCaption: string;
  /** Plain-language context lines for the latest agency figure (counts and
   *  thresholds drawn from its detail — every number verbatim). */
  statLines: (latest: MetricValue) => string[];
  /** A validated --series-* token — color follows the entity, never rank. */
  seriesColor: string;
  unit: string;
  yMax?: number;
  /** "%" for percent figures — a display label around the verbatim string. */
  valueSuffix?: string;
}) {
  const agencyRows = values.filter((v) => v.scope === "agency");
  const latest =
    agencyRows.length > 0 ? agencyRows[agencyRows.length - 1] : null;
  // The latest period's route-level rows, route-id order (stable, and no
  // figure is ever parsed to rank it).
  const routeRows = latest
    ? values
        .filter(
          (v) =>
            v.scope.startsWith("route:") &&
            v.period_start === latest.period_start &&
            v.period_end === latest.period_end,
        )
        .sort((a, b) => (a.scope < b.scope ? -1 : 1))
    : [];
  const refusals = latest ? refusalLines(latest.detail) : [];
  const series: ChartSeries[] = [
    {
      id: "agency",
      label: copy.ops.dashboard.agencyScope,
      color: seriesColor,
      points: seriesPoints(agencyRows).map((p) => ({
        ...p,
        display: `${p.display}${valueSuffix ?? ""}`,
      })),
    },
  ];

  return (
    <ChartCard
      heading={heading}
      description={description}
      badge={<OpsBadge />}
      hint={copy.dashboard.chartReaderHint}
      table={{
        caption: tableCaption,
        columns: [
          copy.ops.dashboard.columns.scope,
          copy.ops.dashboard.columns.value,
          copy.dashboard.columns.provenance,
        ],
        rows: [...(latest ? [latest] : []), ...routeRows].map((v) => [
          opsScopeLabel(v.scope),
          <span className="figure" key="v">
            {`${v.value}${valueSuffix ?? ""}`}
          </span>,
          <ExplainLink value={v} key="p" />,
        ]),
      }}
    >
      {!latest ? (
        <p>{emptyText}</p>
      ) : (
        <>
          {/* The figure verbatim, in plain language, with its provenance. */}
          {statLines(latest).map((line, i) => (
            <p className={i === 0 ? "ops-stat" : "chart-desc"} key={line}>
              {line}
            </p>
          ))}
          <p>
            <ExplainLink value={latest} />
          </p>
          <TimeSeriesChart
            series={series}
            ariaLabel={heading}
            unit={unit}
            yMax={yMax}
          />
          {/* The refusal accounting (design point 3): the cadence evidence
              behind the figure is stated on the card, never hidden. */}
          {refusals.length > 0 && (
            <>
              <h3>{copy.ops.dashboard.refusalsHeading}</h3>
              <ul className="ops-refusals">
                {refusals.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </ChartCard>
  );
}

function StatTile({ values, metric }: { values: MetricValue[]; metric: string }) {
  const latest = latestCertified(values, metric);
  if (!latest) {
    return (
      <li className="card stat-tile">
        <p className="stat-label">{metricLabel(metric)}</p>
        <p className="stat-value stat-empty">{copy.dashboard.noCertified}</p>
        <p className="stat-period">
          {copy.dashboard.noCertifiedDetail(metricLabel(metric))}
        </p>
      </li>
    );
  }
  return (
    <li className="card stat-tile">
      <p className="stat-label">{metricLabel(metric)}</p>
      {/* The figure, verbatim as the API served it. */}
      <p className="stat-value">
        {latest.value}{" "}
        <span className="stat-unit">{unitLabel(latest.unit)}</span>
      </p>
      <p className="stat-period">
        {copy.dashboard.tilePeriod(latest.period_start, latest.period_end)}
      </p>
      <p className="stat-flags">
        <span className="tag certified">{copy.dashboard.tileCertifiedTag}</span>
        {isSimulated(latest.detail) && <SimulatedBadge />}
      </p>
      <p>
        <ExplainLink value={latest} />
      </p>
    </li>
  );
}

export function DashboardView() {
  const [values, setValues] = useState<MetricValue[] | null>(null);
  const [issues, setIssues] = useState<DqIssue[] | null>(null);
  const [valuesError, setValuesError] = useState<string | null>(null);
  const [issuesError, setIssuesError] = useState<string | null>(null);
  // The chart filters (docket #1). Monthly is the app's reporting rhythm.
  // Empty date bounds mean "everything the API served".
  const [granularity, setGranularity] = useState<Granularity>("monthly");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  useEffect(() => {
    listMetricValues()
      .then(setValues)
      .catch((err) =>
        setValuesError(err instanceof ApiError ? err.message : String(err)),
      );
    listDqIssues()
      .then(setIssues)
      .catch((err) =>
        setIssuesError(err instanceof ApiError ? err.message : String(err)),
      );
  }, []);

  const all = values ?? [];
  // Date-range SELECTION (string comparison on ISO dates — see
  // granularity.ts): every chart and table below the filter row shows the
  // same slice, so the numbers always agree. The hero tiles sit ABOVE the
  // row and keep their fixed "latest certified" meaning.
  const byMetric = (metric: string) =>
    all
      .filter(
        (v) =>
          !isOps(v) &&
          v.metric === metric &&
          overlapsRange(v.period_start, v.period_end, fromDate, toDate),
      )
      .sort((a, b) => (a.period_start < b.period_start ? -1 : 1));

  const uptValues = byMetric("upt");
  const vrmValues = byMetric("vrm");
  const vrhValues = byMetric("vrh");

  // ---- Operations metrics (handoff 0014): the ops slice of the same
  //      fetch, split on the CATEGORY field (the honesty boundary), same
  //      date-range slice as every chart below the filter row. ----
  const opsByMetric = (metric: string) =>
    all
      .filter(
        (v) =>
          isOps(v) &&
          v.metric === metric &&
          overlapsRange(v.period_start, v.period_end, fromDate, toDate),
      )
      .sort((a, b) => (a.period_start < b.period_start ? -1 : 1));
  const otpValues = opsByMetric("otp");
  const cvhValues = opsByMetric("headway_adherence");

  // ---- UPT: one series, slot 1 (the title names it; no legend box) ----
  const uptSeries: ChartSeries[] = [
    {
      id: "upt",
      label: metricLabel("upt"),
      color: "var(--series-1)",
      points: seriesPoints(uptValues),
    },
  ];

  // ---- VRM / VRH small multiples: color follows the entity across the
  //      dashboard (VRM = slot 1, VRH = slot 2 — here AND in the coverage
  //      chart), so a reader who learns the hue keeps it. ----
  const vrmSeries: ChartSeries[] = [
    {
      id: "vrm",
      label: metricLabel("vrm"),
      color: "var(--series-1)",
      points: seriesPoints(vrmValues),
    },
  ];
  const vrhSeries: ChartSeries[] = [
    {
      id: "vrh",
      label: metricLabel("vrh"),
      color: "var(--series-2)",
      points: seriesPoints(vrhValues),
    },
  ];

  // ---- coverage over time, from the detail JSONB history. Display = the
  //      string-shifted percent (never a float); geometry parses only. ----
  const coveragePoints = (metricValues: MetricValue[]): {
    points: SeriesPoint[];
    rows: MetricValue[];
  } => {
    const rows = metricValues.filter(
      (v) => v.detail && typeof v.detail.coverage === "string",
    );
    return {
      rows,
      points: rows
        .map((v) => {
          const ratio = detailValueToString(v.detail?.coverage);
          return {
            x: Date.parse(v.period_start),
            xLabel: periodLabel(v),
            display: `${ratioToPercentString(ratio)}%`,
            y: Number(ratio) * 100, // geometry only
          };
        })
        .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
        .sort((a, b) => a.x - b.x),
    };
  };
  const vrmCoverage = coveragePoints(vrmValues);
  const vrhCoverage = coveragePoints(vrhValues);
  const coverageSeries: ChartSeries[] = [
    {
      id: "vrm-coverage",
      label: copy.dashboard.coverage.seriesVrm,
      color: "var(--series-1)",
      points: vrmCoverage.points,
    },
    {
      id: "vrh-coverage",
      label: copy.dashboard.coverage.seriesVrh,
      color: "var(--series-2)",
      points: vrhCoverage.points,
    },
  ].filter((s) => s.points.length > 0);

  // The certifiability threshold from the served detail (a reference line,
  // labeled with the verbatim string-shifted percent).
  const thresholdValue = [...vrmCoverage.rows, ...vrhCoverage.rows].find(
    (v) => v.detail && "coverage_threshold" in v.detail,
  );
  const thresholdRatio = thresholdValue
    ? detailValueToString(thresholdValue.detail?.coverage_threshold)
    : null;
  const referenceLine =
    thresholdRatio !== null && Number.isFinite(Number(thresholdRatio))
      ? {
          y: Number(thresholdRatio) * 100, // geometry only
          label: copy.dashboard.coverage.thresholdLabel(
            ratioToPercentString(thresholdRatio),
          ),
        }
      : undefined;

  // ---- DQ: unresolved issues by workflow status × severity (tallies) ----
  // The card obeys the same date slice as everything below the filter row
  // (an issue's date is its created_at day), but nothing is hidden silently:
  // the held-back count is always stated, and no issue ever looks resolved
  // because a filter excluded it. Granularity does not apply — these are
  // queue tallies, not a time series.
  const allUnresolved = (issues ?? []).filter((i) => i.status !== "resolved");
  const unresolved = allUnresolved.filter((i) =>
    overlapsRange(
      i.created_at.slice(0, 10),
      i.created_at.slice(0, 10),
      fromDate,
      toDate,
    ),
  );
  const dqHeldBack = allUnresolved.length - unresolved.length;
  const dqBars: StackedBar[] = ["open", "owned"]
    .map((status) => {
      const ofStatus = unresolved.filter((i) => i.status === status);
      return {
        key: status,
        label: copy.dashboard.dq.statusLabels[status] ?? status,
        segments: SEVERITY_ORDER.map((severity) => ({
          severity,
          label: copy.dq.severityLabels[severity] ?? severity,
          count: ofStatus.filter((i) => i.severity === severity).length,
          displayCount: formatCount(
            ofStatus.filter((i) => i.severity === severity).length,
          ),
          color: SEVERITY_COLOR[severity],
        })),
        displayTotal: formatCount(ofStatus.length),
      };
    })
    .filter((bar) => bar.segments.some((s) => s.count > 0));

  const serviceRows = [
    ...vrmValues.map((v) => ({ value: v })),
    ...vrhValues.map((v) => ({ value: v })),
  ];

  return (
    <>
      <h1>{copy.dashboard.heading}</h1>
      <p>{copy.dashboard.intro}</p>

      {valuesError && (
        <div role="alert" className="alert">
          {valuesError}
        </div>
      )}
      {issuesError && (
        <div role="alert" className="alert">
          {issuesError}
        </div>
      )}
      {/* Skeleton (handoff 0021 #2): the tiles' shape while they load. */}
      {!values && !valuesError && <Skeleton variant="cards" count={3} />}

      {values && (
        <>
          <section aria-label={copy.dashboard.tilesHeading}>
            <h2>{copy.dashboard.tilesHeading}</h2>
            <p className="chart-desc">{copy.dashboard.tilesIntro}</p>
            <ul className="stat-grid">
              <StatTile values={all} metric="vrm" />
              <StatTile values={all} metric="vrh" />
              <StatTile values={all} metric="upt" />
            </ul>
          </section>

          {all.length === 0 ? (
            /* Teaching empty state (handoff 0021 #4): warm + the action. */
            <>
              <p>{copy.dashboard.empty}</p>
              <p>
                {copy.dashboard.emptyAction}{" "}
                <code>{copy.dashboard.emptyCommand}</code>
              </p>
            </>
          ) : (
            <>
            {/* ONE filter row, above everything it scopes (interaction.md):
                date range first, then granularity. */}
            <ChartFilterRow
              from={fromDate}
              to={toDate}
              granularity={granularity}
              onFrom={setFromDate}
              onTo={setToDate}
              onGranularity={setGranularity}
            />
            <div className="dashboard-grid">
              {/* (2) daily UPT line */}
              <ChartCard
                heading={copy.dashboard.upt.heading}
                description={copy.dashboard.upt.description}
                hint={copy.dashboard.chartReaderHint}
                table={{
                  caption: copy.dashboard.upt.tableCaption,
                  columns: [
                    copy.dashboard.columns.period,
                    copy.dashboard.columns.value,
                    copy.dashboard.columns.unit,
                    copy.dashboard.columns.provenance,
                  ],
                  rows: uptValues.map((v) => [
                    periodLabel(v),
                    <span className="figure" key="v">
                      {v.value}
                    </span>,
                    unitLabel(v.unit),
                    <ExplainLink value={v} key="p" />,
                  ]),
                }}
              >
                {uptValues.length === 0 ? (
                  <p>{copy.dashboard.upt.empty}</p>
                ) : (
                  <>
                    <TimeSeriesChart
                      series={uptSeries}
                      ariaLabel={copy.dashboard.upt.heading}
                      unit={unitLabel("unlinked_passenger_trips")}
                    />
                    <AsReportedNote rows={uptValues} granularity={granularity} />
                  </>
                )}
              </ChartCard>

              {/* (3) VRM & VRH: SMALL MULTIPLES — one panel, one axis each */}
              <ChartCard
                heading={copy.dashboard.service.heading}
                description={copy.dashboard.service.description}
                hint={copy.dashboard.chartReaderHint}
                table={{
                  caption: copy.dashboard.service.tableCaption,
                  columns: [
                    copy.metrics.columns.metric,
                    copy.dashboard.columns.period,
                    copy.dashboard.columns.value,
                    copy.dashboard.columns.unit,
                    copy.dashboard.columns.provenance,
                  ],
                  rows: serviceRows.map(({ value: v }) => [
                    metricLabel(v.metric),
                    periodLabel(v),
                    <span className="figure" key="v">
                      {v.value}
                    </span>,
                    unitLabel(v.unit),
                    <ExplainLink value={v} key="p" />,
                  ]),
                }}
              >
                {vrmValues.length === 0 && vrhValues.length === 0 ? (
                  <p>{copy.dashboard.service.empty}</p>
                ) : (
                  <>
                    <div className="small-multiples">
                      <div className="chart-panel">
                        <h3>{copy.dashboard.service.vrmPanel}</h3>
                        <TimeSeriesChart
                          series={vrmSeries}
                          ariaLabel={copy.dashboard.service.vrmPanel}
                          unit={unitLabel("miles")}
                        />
                      </div>
                      <div className="chart-panel">
                        <h3>{copy.dashboard.service.vrhPanel}</h3>
                        <TimeSeriesChart
                          series={vrhSeries}
                          ariaLabel={copy.dashboard.service.vrhPanel}
                          unit={unitLabel("hours")}
                        />
                      </div>
                    </div>
                    <AsReportedNote
                      rows={[...vrmValues, ...vrhValues]}
                      granularity={granularity}
                    />
                  </>
                )}
              </ChartCard>

              {/* (4) coverage over time + threshold reference line */}
              <ChartCard
                heading={copy.dashboard.coverage.heading}
                description={copy.dashboard.coverage.description}
                hint={copy.dashboard.chartReaderHint}
                table={{
                  caption: copy.dashboard.coverage.tableCaption,
                  columns: [
                    copy.metrics.columns.metric,
                    copy.dashboard.columns.period,
                    copy.receipt.coverageHeading,
                    copy.dashboard.columns.provenance,
                  ],
                  rows: [...vrmCoverage.rows, ...vrhCoverage.rows].map((v) => [
                    metricLabel(v.metric),
                    periodLabel(v),
                    <span className="figure" key="v">
                      {`${ratioToPercentString(detailValueToString(v.detail?.coverage))}%`}
                    </span>,
                    <ExplainLink value={v} key="p" />,
                  ]),
                }}
              >
                {coverageSeries.length === 0 ? (
                  <p>{copy.dashboard.coverage.empty}</p>
                ) : (
                  <>
                    <ChartLegend series={coverageSeries} />
                    <TimeSeriesChart
                      series={coverageSeries}
                      ariaLabel={copy.dashboard.coverage.heading}
                      unit="%"
                      yMax={100}
                      referenceLine={referenceLine}
                    />
                    <AsReportedNote
                      rows={[...vrmCoverage.rows, ...vrhCoverage.rows]}
                      granularity={granularity}
                    />
                  </>
                )}
              </ChartCard>

              {/* (5) unresolved DQ issues by severity — status colors */}
              <ChartCard
                heading={copy.dashboard.dq.heading}
                description={copy.dashboard.dq.description}
                table={{
                  caption: copy.dashboard.dq.tableCaption,
                  columns: [
                    copy.dashboard.columns.status,
                    copy.dq.severityLabels.blocking,
                    copy.dq.severityLabels.warning,
                    copy.dq.severityLabels.info,
                    copy.dashboard.dq.totalColumn,
                  ],
                  rows: dqBars.map((bar) => [
                    bar.label,
                    ...bar.segments.map((s) => s.displayCount),
                    bar.displayTotal,
                  ]),
                }}
              >
                {issuesError ? (
                  // The load failure is already announced in the page-level
                  // alert; restate it here so the card never looks "clear".
                  <p>{issuesError}</p>
                ) : !issues ? (
                  <p>{copy.loading}</p>
                ) : dqBars.length === 0 ? (
                  // The date slice may hold back issues — say so; the plain
                  // "queue is clear" line only appears when it is true.
                  <p>
                    {dqHeldBack > 0
                      ? copy.dashboard.filters.dqOutsideRange(
                          formatCount(dqHeldBack),
                        )
                      : copy.dashboard.dq.empty}
                  </p>
                ) : (
                  <>
                    <SeverityStackedBar
                      bars={dqBars}
                      legend={SEVERITY_ORDER.map((severity) => ({
                        severity,
                        label: copy.dq.severityLabels[severity] ?? severity,
                        color: SEVERITY_COLOR[severity],
                      }))}
                    />
                    {dqHeldBack > 0 && (
                      <p className="chart-desc">
                        {copy.dashboard.filters.dqOutsideRange(
                          formatCount(dqHeldBack),
                        )}
                      </p>
                    )}
                  </>
                )}
                <p>
                  <Link to="/dq">{copy.dashboard.dq.goToQueue}</Link>
                </p>
              </ChartCard>
            </div>

            {/* ---- Operations metrics (handoff 0014, design point 5):
                 route-level OTP + headway adherence. Every card carries the
                 ops badge; refusal accounting is shown, never hidden; and
                 nothing in this section can be certified — the boundary is
                 structural (category='ops'). ---- */}
            <section aria-label={copy.ops.dashboard.heading}>
              <h2>{copy.ops.dashboard.heading}</h2>
              <p className="chart-desc">{copy.ops.dashboard.intro}</p>
              {otpValues.length === 0 && cvhValues.length === 0 ? (
                <p>{copy.ops.dashboard.empty}</p>
              ) : (
                <div className="dashboard-grid">
                  <OpsMetricCard
                    values={otpValues}
                    heading={copy.ops.dashboard.otp.heading}
                    description={copy.ops.dashboard.otp.description}
                    emptyText={copy.ops.dashboard.otp.empty}
                    tableCaption={copy.ops.dashboard.otp.tableCaption}
                    seriesColor="var(--series-1)"
                    unit="%"
                    yMax={100}
                    valueSuffix="%"
                    statLines={(latest) => {
                      const d = latest.detail ?? {};
                      const lines = [
                        copy.ops.dashboard.otp.agencyStat(latest.value),
                      ];
                      if ("on_time_count" in d) {
                        lines.push(
                          copy.ops.dashboard.otp.breakdown(
                            detailValueToString(d.on_time_count),
                            detailValueToString(d.early_count),
                            detailValueToString(d.late_count),
                          ),
                        );
                      }
                      if ("early_tolerance_seconds" in d) {
                        lines.push(
                          copy.ops.dashboard.otp.windowLine(
                            detailValueToString(d.early_tolerance_seconds),
                            detailValueToString(d.late_tolerance_seconds),
                          ),
                        );
                      }
                      return lines;
                    }}
                  />
                  <OpsMetricCard
                    values={cvhValues}
                    heading={copy.ops.dashboard.cvh.heading}
                    description={copy.ops.dashboard.cvh.description}
                    emptyText={copy.ops.dashboard.cvh.empty}
                    tableCaption={copy.ops.dashboard.cvh.tableCaption}
                    seriesColor="var(--series-2)"
                    unit={unitLabel("ratio")}
                    statLines={(latest) => {
                      const d = latest.detail ?? {};
                      const lines = [
                        copy.ops.dashboard.cvh.agencyStat(latest.value),
                        // No interpretation bands: OPS_DEFINITIONS.md defines
                        // none ("Headway serves the number, never a grade"),
                        // so the raw value ships with its formula reference.
                        copy.ops.dashboard.cvh.formulaReference,
                      ];
                      if ("pairs_excluded_inverted" in d) {
                        lines.push(
                          copy.ops.dashboard.cvh.exclusions(
                            detailValueToString(d.pairs_excluded_inverted),
                            detailValueToString(d.pairs_excluded_over_cap),
                            detailValueToString(d.pairs_excluded_unscheduled),
                          ),
                        );
                      }
                      return lines;
                    }}
                  />
                </div>
              )}
            </section>
            </>
          )}
        </>
      )}
    </>
  );
}
