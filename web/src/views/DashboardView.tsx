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
 * MODE VIEWS (handoff 0041): a data-driven Mode selector sits in the
 * control deck beside the Audience lens. Its options are the distinct
 * `mode:*` scopes that actually carry persisted figures (src/reports/
 * modes.ts) — never a hardcoded mode list. Selecting a mode RE-SCOPES:
 * every tile, chart, sparkline and table filters to that mode's own stored
 * rows, verbatim, each with its metric_value_id receipt. Nothing on this
 * page sums, averages, or synthesizes a per-mode figure — not even a total
 * across modes. Surfaces that carry no mode dimension (operations metrics
 * are per route; DQ tallies count issues) SAY they are not narrowed,
 * instead of quietly showing agency numbers under a mode heading.
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
import {
  ApiError,
  getDqIssueCounts,
  getMetricsHistory,
  listMetricValues,
} from "../api/client";
import type {
  DqIssueCounts,
  HistoryPoint,
  HistoryResponse,
  MetricValue,
} from "../api/types";
import { canComputeFigures, useSession } from "../auth/session";
import { HISTORY_BUCKETS } from "../reports/buckets";
import type { HistoryBucketKind } from "../reports/buckets";
import {
  GRANULARITIES,
  misalignedCount,
  overlapsRange,
} from "../reports/granularity";
import type { Granularity } from "../reports/granularity";
import {
  AGENCY_SCOPE,
  isAgencyScope,
  modeOptions,
  rowInScope,
  selectedModeLabel,
} from "../reports/modes";
import { ModeBar } from "../components/ModeBar";
import { ChartCard } from "../components/charts/ChartCard";
import {
  ChartLegend,
  TimeSeriesChart,
} from "../components/charts/TimeSeriesChart";
import type { ChartSeries, SeriesPoint } from "../components/charts/TimeSeriesChart";
import { SeverityStackedBar } from "../components/charts/SeverityStackedBar";
import type { StackedBar } from "../components/charts/SeverityStackedBar";
import { Sparkline } from "../components/charts/Sparkline";
import type { SparklinePoint } from "../components/charts/Sparkline";
import { OpsBadge } from "../components/OpsBadge";
import { Receipt } from "../components/Receipt";
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

function StatTile({
  values,
  metric,
  scope,
  spark,
  bucket,
  openSparkId,
  onToggleSpark,
}: {
  /** Already re-scoped to the selected mode — selection, never arithmetic. */
  values: MetricValue[];
  metric: string;
  /** The selected scope string, shown verbatim when the tile is empty. */
  scope: string;
  /** Persisted history figures for this tile's trend (handoff 0024 #2). */
  spark: SparklinePoint[];
  bucket: HistoryBucketKind;
  openSparkId: string | null;
  onToggleSpark: (point: HistoryPoint) => void;
}) {
  const latest = latestCertified(values, metric);
  // The open sparkline receipt, if it belongs to this tile's trend.
  const openPoint =
    openSparkId === null
      ? null
      : (spark.find((sp) => sp.point.metric_value_id === openSparkId)?.point ??
        null);
  // Sparkline trends appear WHERE HISTORY EXISTS (handoff 0024): every
  // point is a persisted figure one click from its receipt.
  const trend =
    spark.length > 0 ? (
      <>
        <Sparkline
          metricLabel={metricLabel(metric)}
          unit={unitLabel(spark[0].point.unit)}
          bucket={bucket}
          points={spark}
          openId={openSparkId}
          onToggle={onToggleSpark}
        />
        {openPoint && (
          <div className="spark-receipt">
            <Receipt value={openPoint} />
            <button type="button" onClick={() => onToggleSpark(openPoint)}>
              {copy.dashboard.sparkline.closeReceipt}
            </button>
          </div>
        )}
      </>
    ) : null;
  if (!latest) {
    return (
      <li className="card stat-tile">
        <p className="stat-label">{metricLabel(metric)}</p>
        <p className="stat-value stat-empty">{copy.dashboard.noCertified}</p>
        <p className="stat-period">
          {copy.dashboard.noCertifiedDetail(metricLabel(metric))}
        </p>
        <p className="stat-scope mono">
          {copy.dashboard.mode.scopeReceipt(scope)}
        </p>
        {trend}
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
      {/* The row's OWN scope, verbatim — a mode slice can never pass for
          the agency rollup, and the agency rollup can never pass for a
          mode. */}
      <p className="stat-scope mono">
        {copy.dashboard.mode.scopeReceipt(latest.scope)}
      </p>
      <p className="stat-flags">
        <span className="tag certified">{copy.dashboard.tileCertifiedTag}</span>
        {isSimulated(latest.detail) && <SimulatedBadge />}
      </p>
      <p>
        <ExplainLink value={latest} />
      </p>
      {trend}
    </li>
  );
}

/**
 * The audience-lens bar (handoff 0024, design point 2): three NAMED LENS
 * CONFIGURATIONS + the calendar-bucket group that drives /metrics/history.
 * A lens is grouping and framing ONLY — the hint under the bar says so,
 * and the server's own grouping_note renders verbatim beside it.
 */
const LENS_PRESETS: Record<string, HistoryBucketKind> = {
  board: "quarter",
  executive: "month",
  operations: "day",
};

function LensBar({
  preset,
  bucket,
  groupingNote,
  onPreset,
  onBucket,
}: {
  preset: string | null;
  bucket: HistoryBucketKind;
  /** The server's grouping_note, rendered VERBATIM when history loaded. */
  groupingNote: string | null;
  onPreset: (key: string | null) => void;
  onBucket: (bucket: HistoryBucketKind) => void;
}) {
  const t = copy.dashboard.lens;
  return (
    <section aria-label={t.rowLabel} className="lens-bar">
      <p className="chart-desc">{t.intro}</p>
      <div className="chart-filters">
        <div className="filter-bar" role="group" aria-label={t.rowLabel}>
          <span className="filter-bar-label">{t.rowLabel}:</span>
          {Object.keys(LENS_PRESETS).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={preset === key}
              onClick={() => onPreset(preset === key ? null : key)}
            >
              {t.presets[key]}
            </button>
          ))}
        </div>
        <div className="filter-bar" role="group" aria-label={t.bucketLabel}>
          <span className="filter-bar-label">{t.bucketLabel}:</span>
          {HISTORY_BUCKETS.map((b) => (
            <button
              key={b}
              type="button"
              aria-pressed={bucket === b}
              onClick={() => onBucket(b)}
            >
              {t.bucketOptions[b]}
            </button>
          ))}
        </div>
      </div>
      {preset && <p className="chart-desc">{t.presetHints[preset]}</p>}
      {groupingNote && (
        <p className="chart-desc">
          {t.groupingIntro} {groupingNote}
        </p>
      )}
    </section>
  );
}

export function DashboardView() {
  const session = useSession();
  const [values, setValues] = useState<MetricValue[] | null>(null);
  // The DQ card's tallies come from the SERVER's counts endpoint (handoff
  // 0030): the issue list now serves one page at a time, so tallying
  // downloaded rows would have tallied a page and called it the queue.
  // One DqIssueCounts per unresolved status — by_severity within each.
  const [dqCounts, setDqCounts] = useState<{
    open: DqIssueCounts;
    owned: DqIssueCounts;
  } | null>(null);
  const [valuesError, setValuesError] = useState<string | null>(null);
  const [issuesError, setIssuesError] = useState<string | null>(null);
  // The chart filters (docket #1). Monthly is the app's reporting rhythm.
  // Empty date bounds mean "everything the API served".
  const [granularity, setGranularity] = useState<Granularity>("monthly");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  // The audience lens (handoff 0024 #2): a preset is a lens CONFIGURATION —
  // it picks the history bucket and the section order, nothing else.
  // "Executive" (month) is the default rhythm.
  const [preset, setPreset] = useState<string | null>("executive");
  const [bucket, setBucket] = useState<HistoryBucketKind>("month");
  // The mode dimension (handoff 0041). "agency" is the persisted
  // agency-wide rollup, NOT a client-side total of the modes.
  const [modeScope, setModeScope] = useState<string>(AGENCY_SCOPE);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [openSparkId, setOpenSparkId] = useState<string | null>(null);

  useEffect(() => {
    listMetricValues()
      .then(setValues)
      .catch((err) =>
        setValuesError(err instanceof ApiError ? err.message : String(err)),
      );
    Promise.all([getDqIssueCounts("open"), getDqIssueCounts("owned")])
      .then(([open, owned]) => setDqCounts({ open, owned }))
      .catch((err) =>
        setIssuesError(err instanceof ApiError ? err.message : String(err)),
      );
  }, []);

  // The period series behind the sparklines: persisted figures, grouped by
  // the selected calendar bucket BY THE SERVER (never summed anywhere).
  useEffect(() => {
    let stale = false;
    setHistory(null);
    setHistoryError(null);
    // A mode selection RE-SCOPES the request: the server returns that
    // mode's persisted rows. The agency default sends no scope param so
    // the fleet-wide rows come back exactly as before.
    getMetricsHistory(
      isAgencyScope(modeScope) ? { bucket } : { bucket, scope: modeScope },
    )
      .then((data) => {
        if (!stale) setHistory(data);
      })
      .catch((err) => {
        if (!stale)
          setHistoryError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      stale = true;
    };
  }, [bucket, modeScope]);

  const applyPreset = (key: string | null) => {
    setPreset(key);
    if (key !== null) setBucket(LENS_PRESETS[key]);
  };
  const applyBucket = (b: HistoryBucketKind) => {
    setBucket(b);
    // A hand-picked bucket that disagrees with the pressed preset unpresses
    // it — a preset never LOOKS active while its configuration is not.
    if (preset !== null && LENS_PRESETS[preset] !== b) setPreset(null);
  };

  /**
   * The tile's trend: this metric's AGENCY-WIDE persisted NTD figures
   * (fleet/agency scope — a mode slice never silently stands in for the
   * whole), each tagged with the server's bucket key. Selection only.
   */
  const sparkFor = (metric: string): SparklinePoint[] => {
    if (!history) return [];
    const out: SparklinePoint[] = [];
    for (const b of history.buckets) {
      for (const point of b.points) {
        if (
          point.metric === metric &&
          point.category !== "ops" &&
          rowInScope(point.scope, modeScope)
        ) {
          out.push({ point, bucketKey: b.bucket_key });
        }
      }
    }
    return out;
  };
  const toggleSpark = (point: HistoryPoint) =>
    setOpenSparkId((prev) =>
      prev === point.metric_value_id ? null : point.metric_value_id,
    );
  // "Operations" lens: ops cards forward — an ORDER change only.
  const opsFirst = preset === "operations";

  const all = values ?? [];
  // The mode dimension, DERIVED FROM THE DATA (handoff 0041 #2): the
  // distinct mode:* scopes the API actually served. No mode is named in
  // the frontend — a new mode appears the day its calc wave lands.
  const modeOpts = modeOptions(all);
  const modeLabel = selectedModeLabel(modeScope);
  const agencyView = isAgencyScope(modeScope);
  // Every NTD row in the selected scope, whatever the dates. RE-SCOPE, not
  // derive: this is a filter over the served rows and nothing else.
  const scopedNtd = all.filter((v) => !isOps(v) && rowInScope(v.scope, modeScope));
  // Date-range SELECTION (string comparison on ISO dates — see
  // granularity.ts): every chart and table below the filter row shows the
  // same slice, so the numbers always agree. The hero tiles sit ABOVE the
  // row and keep their fixed "latest certified" meaning.
  const byMetric = (metric: string) =>
    scopedNtd
      .filter(
        (v) =>
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
  // Server-counted over the WHOLE queue (handoff 0030): one counts call
  // per unresolved status, by_severity within each — the same tallies /dq
  // and /today read. The date filter below does NOT slice this card any
  // more: the list endpoint pages and the counts endpoint carries no date
  // filter, so a sliced tally could only have come from counting loaded
  // rows — a page passing for the queue. The card says in words that it
  // always covers the whole queue. Granularity does not apply — these are
  // queue tallies, not a time series.
  const dqBars: StackedBar[] = (["open", "owned"] as const)
    .map((status) => {
      const bySeverity = dqCounts?.[status].by_severity ?? {};
      const statusTotal = SEVERITY_ORDER.reduce(
        (sum, severity) => sum + (bySeverity[severity] ?? 0),
        0,
      );
      return {
        key: status,
        label: copy.dashboard.dq.statusLabels[status] ?? status,
        segments: SEVERITY_ORDER.map((severity) => ({
          severity,
          label: copy.dq.severityLabels[severity] ?? severity,
          count: bySeverity[severity] ?? 0,
          displayCount: formatCount(bySeverity[severity] ?? 0),
          color: SEVERITY_COLOR[severity],
        })),
        displayTotal: formatCount(statusTotal),
      };
    })
    .filter((bar) => bar.segments.some((s) => s.count > 0));

  const serviceRows = [
    ...vrmValues.map((v) => ({ value: v })),
    ...vrhValues.map((v) => ({ value: v })),
  ];

  /**
   * A card's empty line. Under a mode it NAMES the mode and says why the
   * space is empty (handoff 0041 #4) — a fabricated zero is never shown,
   * and a blank card never passes for "nothing happened".
   */
  const cardEmpty = (what: string, agencyText: string) =>
    agencyView
      ? agencyText
      : copy.dashboard.mode.cardEmpty(
          copy.dashboard.mode.cardEmptyWhat[what] ?? what,
          modeLabel,
        );

  /** Does the selected mode have any NTD figure in the selected dates? */
  const scopedInRange =
    uptValues.length + vrmValues.length + vrhValues.length;

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
          {/* The control deck: Mode, then Audience lens and Group trends
              by — one honest strip, everything visible at once (handoff
              0041 #1: no fly-out, no sub-menu). */}
          <div className="control-deck">
            <ModeBar
              options={modeOpts}
              scope={modeScope}
              onScope={setModeScope}
            />
            <LensBar
              preset={preset}
              bucket={bucket}
              groupingNote={history?.grouping_note ?? null}
              onPreset={applyPreset}
              onBucket={applyBucket}
            />
          </div>
          {/* A trend that failed to load is stated, never blank — the tiles
              themselves still render their certified figures. */}
          {historyError && (
            <p className="chart-desc">
              {copy.dashboard.lens.historyUnavailable(historyError)}
            </p>
          )}
          <section aria-label={copy.dashboard.tilesHeading}>
            <h2>
              {agencyView
                ? copy.dashboard.tilesHeading
                : copy.dashboard.mode.tilesFor(modeLabel)}
            </h2>
            <p className="chart-desc">{copy.dashboard.tilesIntro}</p>
            <ul className="stat-grid">
              {["vrm", "vrh", "upt"].map((metric) => (
                <StatTile
                  key={metric}
                  values={scopedNtd}
                  metric={metric}
                  scope={modeScope}
                  spark={sparkFor(metric)}
                  bucket={bucket}
                  openSparkId={openSparkId}
                  onToggleSpark={toggleSpark}
                />
              ))}
            </ul>
          </section>

          {all.length === 0 ? (
            /* Teaching empty state (handoff 0021 #4): warm + the action —
               since handoff 0026 the Compute figures room, never a CLI
               line on a user surface. */
            <>
              <p>{copy.dashboard.empty}</p>
              {canComputeFigures(session) ? (
                <p>
                  {copy.dashboard.emptyActionAuthorized}{" "}
                  <Link to="/calc-runs">{copy.dashboard.emptyDoor}</Link>
                </p>
              ) : (
                <p>{copy.dashboard.emptyActionViewer}</p>
              )}
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
            {(() => {
            /* The three FIGURE cards — the only ones the Mode selector
               re-scopes. The data-quality card below is deliberately kept
               out of this group: it carries no mode dimension, so an empty
               mode must never make an open blocking issue disappear. */
            const figureCards = (
            <>
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
                  <p>{cardEmpty("upt", copy.dashboard.upt.empty)}</p>
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
                  <p>{cardEmpty("service", copy.dashboard.service.empty)}</p>
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
                  <p>{cardEmpty("coverage", copy.dashboard.coverage.empty)}</p>
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

            </>
            );

            /* (5) unresolved DQ issues by severity — status colors.
                  The honest attention rail (handoff 0041): an OPEN BLOCKING
                  issue is the one thing on this page that genuinely needs a
                  human, so the card FRAME carries the alert rail — with a
                  shape and a sentence, so the signal survives for anyone
                  who perceives no glow. The figures inside are untouched.
                  It is ALWAYS rendered, whatever the mode: an unresolved
                  blocking issue must never vanish because a mode slice
                  happens to be empty. */
            const dqCard = (
              <ChartCard
                heading={copy.dashboard.dq.heading}
                description={copy.dashboard.dq.description}
                flag={
                  (dqCounts?.open.by_severity?.blocking ?? 0) > 0
                    ? {
                        tone: "alert",
                        label: copy.dashboard.dq.blockingFlag(
                          formatCount(dqCounts?.open.by_severity?.blocking ?? 0),
                        ),
                      }
                    : undefined
                }
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
                ) : dqCounts === null ? (
                  <p>{copy.loading}</p>
                ) : dqBars.length === 0 ? (
                  <p>{copy.dashboard.dq.empty}</p>
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
                    {/* Stated, not implied (handoff 0030): the date filter
                        above slices the charts, but these are whole-queue
                        tallies from the server's counts — a date-sliced
                        tally could only come from counting loaded rows. */}
                    {(fromDate !== "" || toDate !== "") && (
                      <p className="chart-desc">
                        {copy.dashboard.dq.wholeQueueNote}
                      </p>
                    )}
                  </>
                )}
                {/* The DQ queue carries NO mode dimension: it counts
                    issues, not figures. Under a mode the card says it is
                    not narrowed, rather than showing agency tallies under
                    a mode heading (handoff 0041). */}
                {!agencyView && (
                  <p className="chart-desc">
                    {copy.dashboard.mode.dqNote(modeLabel)}
                  </p>
                )}
                <p>
                  <Link to="/dq">{copy.dashboard.dq.goToQueue}</Link>
                </p>
              </ChartCard>
            );

            // ---- Operations metrics (handoff 0014, design point 5):
            // route-level OTP + headway adherence. Every card carries the
            // ops badge; refusal accounting is shown, never hidden; and
            // nothing in this section can be certified — the boundary is
            // structural (category='ops'). Under the OPERATIONS lens
            // (handoff 0024) this section leads — an order change only.
            const opsSection = (
            <section aria-label={copy.ops.dashboard.heading}>
              <h2>{copy.ops.dashboard.heading}</h2>
              <p className="chart-desc">{copy.ops.dashboard.intro}</p>
              {/* Operations metrics are computed PER ROUTE. There is no
                  per-mode operations figure, so this section is not
                  narrowed by the Mode selector — and says so, rather than
                  letting agency figures sit under a mode heading. */}
              {!agencyView && (
                <p className="chart-desc">
                  {copy.dashboard.mode.opsNote(modeLabel)}
                </p>
              )}
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
            );

            /* An INVITING per-mode empty state (handoff 0041 #4): a mode
               with nothing computed in these dates gets a designed panel
               that names it and says why it is empty — never a blank grid
               of "0"s, and never a fabricated zero. The operations section
               still renders below it (with its own not-narrowed note),
               because it carries no mode dimension at all. */
            const modeEmpty = (
              <section
                className="card mode-empty"
                aria-label={copy.dashboard.mode.emptyHeading(modeLabel)}
              >
                <p className="mode-empty-eyebrow mono">
                  {copy.dashboard.mode.scopeReceipt(modeScope)}
                </p>
                <h2>{copy.dashboard.mode.emptyHeading(modeLabel)}</h2>
                <p>{copy.dashboard.mode.emptyBody(modeLabel)}</p>
                <p className="chart-desc">{copy.dashboard.mode.emptyWiden}</p>
                {canComputeFigures(session) && (
                  <p>
                    <Link to="/calc-runs">{copy.dashboard.emptyDoor}</Link>
                  </p>
                )}
              </section>
            );
            /* The data-quality card rides along either way — a mode with no
               figures must not hide an open blocking issue. */
            const figuresBlock = (
              <div className="dashboard-grid">
                {!agencyView && scopedInRange === 0 ? modeEmpty : figureCards}
                {dqCard}
              </div>
            );

            return opsFirst ? (
              <>
                {opsSection}
                {figuresBlock}
              </>
            ) : (
              <>
                {figuresBlock}
                {opsSection}
              </>
            );
            })()}
            </>
          )}
        </>
      )}
    </>
  );
}
