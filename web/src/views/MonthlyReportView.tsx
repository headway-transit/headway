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

import { Fragment, useEffect, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getMr20Report, listMetricValues } from "../api/client";
import type { Mr20Fetch } from "../api/client";
import type { MetricValue, Mr20Cell, Mr20Cells } from "../api/types";
import { Receipt } from "../components/Receipt";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { copy } from "../copy";
import { coverageSummary, isPreVerification, isSimulated } from "../detail";
import { ratioToPercentString } from "../format";
import { buildMonthlyRidershipCsv } from "../reports/csv";
import { monthPeriod, previousMonth } from "../reports/period";

/** The metrics of the Monthly Ridership preview, in display order. */
const REPORT_METRICS = ["vrm", "vrh", "upt"] as const;

/** The MR-20 measures, in the package's column order. */
const MR20_MEASURES = ["upt", "vrm", "vrh", "voms"] as const;

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function unitLabel(code: string): string {
  return copy.unitLabels[code] ?? code;
}

/**
 * One flag badge on an MR-20 cell. "simulated" reuses the SimulatedBadge
 * (same rule, same rendering everywhere); known flags get their
 * plain-language label plus a visually-hidden note; unknown flags are shown
 * raw — a flag the UI does not know is displayed, never hidden.
 */
function Mr20FlagBadge({ flag }: { flag: string }) {
  const key = flag.toLowerCase().replace(/-/g, "_");
  if (key === "simulated") return <SimulatedBadge />;
  const label = copy.report.mr20.flagLabels[key] ?? flag;
  const note = copy.report.mr20.flagNotes[key];
  return (
    <span className="tag mr20-flag">
      {label}
      {note && <span className="visually-hidden"> — {note}</span>}
    </span>
  );
}

/**
 * One MR-20 value cell. The figure is the package's string VERBATIM; a null
 * value shows the package's plain-language reason instead. Flags and
 * certification status ride with the figure, and any figure that has a
 * metric_value_id keeps its provenance path.
 */
function Mr20CellView({
  cell,
  measure,
  modeLabel,
}: {
  cell: Mr20Cell | undefined;
  measure: string;
  modeLabel: string;
}) {
  if (!cell) {
    return <td>{copy.report.mr20.cellMissing}</td>;
  }
  if (cell.value === null) {
    // A missing figure is stated in the package's own words, plus any flags
    // (e.g. the rail pending-D2 hold) — never a silent blank.
    return (
      <td>
        {cell.reason ?? copy.report.mr20.noReason}
        {cell.flags.map((flag) => (
          <Fragment key={flag}>
            {" "}
            <Mr20FlagBadge flag={flag} />
          </Fragment>
        ))}
      </td>
    );
  }
  return (
    <td>
      {/* The figure, verbatim as the API packaged it. */}
      <span className="figure">{cell.value}</span>{" "}
      <span className="mr20-unit">
        {copy.unitLabels[cell.unit] ?? cell.unit}
      </span>
      <span className="mr20-cell-meta">
        {cell.certification_status && (
          <span className={`tag ${cell.certification_status}`}>
            {cell.certification_status}
          </span>
        )}
        {cell.flags.map((flag) => (
          <Mr20FlagBadge key={flag} flag={flag} />
        ))}
        {typeof cell.coverage === "string" && (
          <span>
            {copy.report.mr20.cellCoverage(ratioToPercentString(cell.coverage))}
          </span>
        )}
        {cell.metric_value_id && (
          <Link to={`/metrics/${cell.metric_value_id}/lineage`}>
            {copy.metrics.explainLink}
            <span className="visually-hidden">
              {` — ${copy.metricLabels[measure] ?? measure}, ${modeLabel}`}
            </span>
          </Link>
        )}
      </span>
    </td>
  );
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
  const [openDetails, setOpenDetails] = useState<Set<string>>(new Set());
  /** Which report section is shown: the ridership preview or MR-20. */
  const [section, setSection] = useState<"preview" | "mr20">("preview");
  const [mr20, setMr20] = useState<Mr20Fetch | null>(null);
  const [mr20Error, setMr20Error] = useState<string | null>(null);
  const [caveatsOpen, setCaveatsOpen] = useState(false);

  const toggleDetails = (id: string) => {
    setOpenDetails((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

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

  // The MR-20 package is fetched only when its section is open (and
  // refetched when the picked month changes while it is open).
  useEffect(() => {
    if (section !== "mr20") return;
    let cancelled = false;
    setMr20(null);
    setMr20Error(null);
    setCaveatsOpen(false);
    getMr20Report(`${year}-${String(month).padStart(2, "0")}`)
      .then((result) => {
        if (!cancelled) setMr20(result);
      })
      .catch((err) => {
        if (!cancelled)
          setMr20Error(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [section, year, month]);

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

  const handleDownloadMr20 = () => {
    if (!mr20) return;
    // The saved file is the FETCHED RESPONSE TEXT, byte for byte (mr20.raw).
    // Re-serializing the parsed object (JSON.stringify) could reorder keys
    // or reformat values, so it is never used here — byte-identity is
    // asserted in tests.
    const blob = new Blob([mr20.raw], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = copy.report.mr20.downloadFileName(mr20.pkg.month);
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

      {/* Section toggle (the ChartCard / lineage pattern: aria-pressed
          buttons; the pressed one is filled AND keeps its label). */}
      <div
        className="view-toggle"
        role="group"
        aria-label={copy.report.mr20.sectionToggleLabel}
      >
        <button
          type="button"
          aria-pressed={section === "preview"}
          onClick={() => setSection("preview")}
        >
          {copy.report.mr20.previewTab}
        </button>
        <button
          type="button"
          aria-pressed={section === "mr20"}
          onClick={() => setSection("mr20")}
        >
          {copy.report.mr20.mr20Tab}
        </button>
      </div>

      {section === "mr20" && (
        <section aria-label={copy.report.mr20.heading}>
          <h2>{copy.report.mr20.heading}</h2>
          <p>{copy.report.mr20.intro}</p>
          {mr20Error && (
            <div role="alert" className="alert">
              {mr20Error}
            </div>
          )}
          {!mr20 && !mr20Error && <p>{copy.loading}</p>}
          {mr20 && (
            <>
              {/* The package's own NOT-REPORTABLE banner, verbatim and
                  unmissable (the existing alert pattern). */}
              {mr20.pkg.banner && (
                <div className="alert mr20-banner">{mr20.pkg.banner}</div>
              )}
              {/* The citation line, verbatim from the package. */}
              <p className="mr20-citation">{mr20.pkg.citation}</p>
              <div
                className="table-wrap"
                role="region"
                aria-label={copy.report.mr20.tableCaption(
                  monthName,
                  String(year),
                )}
                tabIndex={0}
              >
                <table>
                  <caption>
                    {copy.report.mr20.tableCaption(monthName, String(year))}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">{copy.report.mr20.columns.mode}</th>
                      {MR20_MEASURES.map((measure) => (
                        <th scope="col" key={measure}>
                          {copy.metricLabels[measure] ?? measure}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <th scope="row">{copy.report.mr20.fleetRow}</th>
                      {MR20_MEASURES.map((measure) => (
                        <Mr20CellView
                          key={measure}
                          cell={mr20.pkg.fleet[measure]}
                          measure={measure}
                          modeLabel={copy.report.mr20.fleetRow}
                        />
                      ))}
                    </tr>
                    {Object.entries(mr20.pkg.modes).map(
                      ([mode, cells]: [string, Mr20Cells]) => {
                        const modeLabel =
                          copy.report.mr20.modeLabels[mode] ?? mode;
                        return (
                          <tr key={mode}>
                            <th scope="row">{modeLabel}</th>
                            {MR20_MEASURES.map((measure) => (
                              <Mr20CellView
                                key={measure}
                                cell={cells[measure]}
                                measure={measure}
                                modeLabel={modeLabel}
                              />
                            ))}
                          </tr>
                        );
                      },
                    )}
                  </tbody>
                </table>
              </div>
              {mr20.pkg.caveats.length > 0 && (
                <div className="mr20-caveats">
                  {/* Disclosure: collapsed by default, state announced. */}
                  <button
                    type="button"
                    aria-expanded={caveatsOpen}
                    onClick={() => setCaveatsOpen((open) => !open)}
                  >
                    {copy.report.mr20.caveatsToggle(
                      String(mr20.pkg.caveats.length),
                    )}
                  </button>
                  {caveatsOpen && (
                    <ul>
                      {mr20.pkg.caveats.map((caveat) => (
                        <li key={caveat}>{caveat}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              <p>
                <button type="button" onClick={handleDownloadMr20}>
                  {copy.report.mr20.download}
                </button>
              </p>
            </>
          )}
        </section>
      )}

      {section === "preview" && error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {section === "preview" && !byMetric && !error && <p>{copy.loading}</p>}

      {section === "preview" && byMetric && (
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
                  <th scope="col">{copy.report.columns.details}</th>
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
                        <td colSpan={7}>
                          {copy.report.noFigure(metricLabel(metric))}
                        </td>
                      </tr>
                    );
                  }
                  return rows.map((v) => {
                    const detailsOpen = openDetails.has(v.metric_value_id);
                    return (
                      <Fragment key={v.metric_value_id}>
                        <tr>
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
                            <button
                              type="button"
                              aria-expanded={detailsOpen}
                              onClick={() => toggleDetails(v.metric_value_id)}
                            >
                              {copy.report.columns.details}
                              <span className="visually-hidden">
                                {` — ${metricLabel(v.metric)}, ${v.period_start} to ${v.period_end}`}
                              </span>
                            </button>
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
                        {detailsOpen && (
                          <tr>
                            <td colSpan={8}>
                              <Receipt value={v} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  });
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
