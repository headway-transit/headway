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

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, listDqIssues, listMetricValues } from "../api/client";
import type { DqIssue, MetricValue } from "../api/types";
import { ChartCard } from "../components/charts/ChartCard";
import {
  ChartLegend,
  TimeSeriesChart,
} from "../components/charts/TimeSeriesChart";
import type { ChartSeries, SeriesPoint } from "../components/charts/TimeSeriesChart";
import { SeverityStackedBar } from "../components/charts/SeverityStackedBar";
import type { StackedBar } from "../components/charts/SeverityStackedBar";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { copy } from "../copy";
import { isSimulated } from "../detail";
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
  const byMetric = (metric: string) =>
    all
      .filter((v) => v.metric === metric)
      .sort((a, b) => (a.period_start < b.period_start ? -1 : 1));

  const uptValues = byMetric("upt");
  const vrmValues = byMetric("vrm");
  const vrhValues = byMetric("vrh");

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
  const unresolved = (issues ?? []).filter((i) => i.status !== "resolved");
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
      {!values && !valuesError && <p>{copy.loading}</p>}

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
            <p>{copy.dashboard.empty}</p>
          ) : (
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
                  <TimeSeriesChart
                    series={uptSeries}
                    ariaLabel={copy.dashboard.upt.heading}
                    unit={unitLabel("unlinked_passenger_trips")}
                  />
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
                  <p>{copy.dashboard.dq.empty}</p>
                ) : (
                  <SeverityStackedBar
                    bars={dqBars}
                    legend={SEVERITY_ORDER.map((severity) => ({
                      severity,
                      label: copy.dq.severityLabels[severity] ?? severity,
                      color: SEVERITY_COLOR[severity],
                    }))}
                  />
                )}
                <p>
                  <Link to="/dq">{copy.dashboard.dq.goToQueue}</Link>
                </p>
              </ChartCard>
            </div>
          )}
        </>
      )}
    </>
  );
}
