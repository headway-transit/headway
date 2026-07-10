/**
 * Monthly Ridership report (PREVIEW): the VRM, VRH, and UPT figures the API
 * serves for one calendar month, with certification status, data-coverage
 * summary, simulated-data marking, and a per-figure provenance link.
 *
 * Deriving period_start/period_end from the picked month is UI logic (period
 * SELECTION); the figures themselves are the API's strings verbatim — this
 * view never computes, rounds, or edits one, and the CSV export writes the
 * exact same strings.
 *
 * The permanent disclaimer is not decorative: the official NTD Monthly
 * Ridership submission format has not been verified against FTA's reporting
 * system documentation (a tracked NTD-role item), so nothing here presents
 * itself as a submission.
 */

import { useEffect, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, listMetricValues } from "../api/client";
import type { MetricValue } from "../api/types";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { copy } from "../copy";
import { coverageSummary, isSimulated } from "../detail";
import { buildMonthlyRidershipCsv } from "../reports/csv";
import { monthPeriod, previousMonth } from "../reports/period";

/** The metrics of the Monthly Ridership preview, in display order. */
const REPORT_METRICS = ["vrm", "vrh", "upt"] as const;

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function unitLabel(code: string): string {
  return copy.unitLabels[code] ?? code;
}

function isPreVerification(value: MetricValue): boolean {
  return value.calc_version.startsWith("0.");
}

export function MonthlyReportView() {
  const monthId = useId();
  const yearId = useId();
  const initial = useMemo(() => previousMonth(new Date()), []);
  const [month, setMonth] = useState(initial.month);
  const [year, setYear] = useState(initial.year);
  const [byMetric, setByMetric] = useState<Record<
    string,
    MetricValue[]
  > | null>(null);
  const [error, setError] = useState<string | null>(null);

  const currentYear = new Date().getFullYear();
  const yearOptions = Array.from(
    { length: 4 },
    (_, i) => currentYear - 3 + i,
  );

  useEffect(() => {
    let cancelled = false;
    setByMetric(null);
    setError(null);
    const period = monthPeriod(year, month);
    // One read per metric — three calls, all filtered to the picked month.
    Promise.all(
      REPORT_METRICS.map((metric) =>
        listMetricValues({ metric, ...period }),
      ),
    )
      .then((results) => {
        if (cancelled) return;
        const next: Record<string, MetricValue[]> = {};
        REPORT_METRICS.forEach((metric, i) => {
          next[metric] = results[i];
        });
        setByMetric(next);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [year, month]);

  const allValues = REPORT_METRICS.flatMap(
    (metric) => byMetric?.[metric] ?? [],
  );
  const anySimulated = allValues.some((v) => isSimulated(v.detail));
  const monthName = copy.report.monthNames[month - 1];

  const handleExport = () => {
    // The CSV is assembled client-side from the API strings VERBATIM
    // (see reports/csv.ts — asserted cell === API string in tests).
    const csv = buildMonthlyRidershipCsv(allValues);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = copy.report.exportFileName(
      String(year),
      String(month).padStart(2, "0"),
    );
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <h1>{copy.report.heading}</h1>
      <p>{copy.report.intro}</p>

      {/* Permanent, always-visible: this is a preview, not a submission. */}
      <p className="banner">{copy.report.disclaimer}</p>

      <div className="month-picker">
        <div>
          <label htmlFor={monthId}>{copy.report.monthLabel}</label>
          <select
            id={monthId}
            value={month}
            onChange={(e) => setMonth(Number(e.target.value))}
          >
            {copy.report.monthNames.map((name, i) => (
              <option key={name} value={i + 1}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={yearId}>{copy.report.yearLabel}</label>
          <select
            id={yearId}
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
          >
            {yearOptions.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {!byMetric && !error && <p>{copy.loading}</p>}

      {byMetric && (
        <>
          {anySimulated && (
            <div className="alert">
              <SimulatedBadge /> {copy.simulated.reportBanner}
            </div>
          )}

          {/* role/tabIndex: a horizontally scrollable region must be
              keyboard-reachable and named (axe: scrollable-region-focusable) */}
          <div
            className="table-wrap"
            role="region"
            aria-label={copy.report.heading}
            tabIndex={0}
          >
            <table>
              <caption>
                {copy.report.tableCaption(monthName, String(year))}
              </caption>
              <thead>
                <tr>
                  <th scope="col">{copy.report.columns.metric}</th>
                  <th scope="col">{copy.report.columns.value}</th>
                  <th scope="col">{copy.report.columns.unit}</th>
                  <th scope="col">{copy.report.columns.calc}</th>
                  <th scope="col">{copy.report.columns.status}</th>
                  <th scope="col">{copy.report.columns.coverage}</th>
                  <th scope="col">{copy.report.columns.provenance}</th>
                </tr>
              </thead>
              <tbody>
                {REPORT_METRICS.map((metric) => {
                  const rows = byMetric[metric];
                  if (rows.length === 0) {
                    // A missing figure is shown, never silently skipped.
                    return (
                      <tr key={metric}>
                        <th scope="row">{metricLabel(metric)}</th>
                        <td colSpan={6}>
                          {copy.report.noFigure(metricLabel(metric))}
                        </td>
                      </tr>
                    );
                  }
                  return rows.map((v) => (
                    <tr key={v.metric_value_id}>
                      <th scope="row">
                        {metricLabel(v.metric)}
                        {isSimulated(v.detail) && (
                          <>
                            {" "}
                            <SimulatedBadge />
                          </>
                        )}
                      </th>
                      {/* The figure, verbatim as the API served it. */}
                      <td className="figure">{v.value}</td>
                      <td>{unitLabel(v.unit)}</td>
                      <td>
                        {v.calc_name} {v.calc_version}
                        {isPreVerification(v) && (
                          <>
                            {" "}
                            <span className="tag pre-verification">
                              {copy.metrics.preVerificationTag}
                            </span>
                          </>
                        )}
                      </td>
                      <td>
                        <span className={`tag ${v.certification_status}`}>
                          {v.certification_status}
                        </span>
                      </td>
                      <td>
                        {coverageSummary(v.detail) ??
                          copy.report.coverageNotReported}
                      </td>
                      <td>
                        <Link to={`/metrics/${v.metric_value_id}/lineage`}>
                          {copy.metrics.explainLink}
                          <span className="visually-hidden">
                            {` — ${metricLabel(v.metric)}, ${v.period_start} to ${v.period_end}`}
                          </span>
                        </Link>
                      </td>
                    </tr>
                  ));
                })}
              </tbody>
            </table>
          </div>

          {allValues.length > 0 && (
            <p>
              <button type="button" onClick={handleExport}>
                {copy.report.exportCsv}
              </button>
            </p>
          )}
        </>
      )}
    </>
  );
}
