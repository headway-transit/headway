import { Fragment, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, listMetricValues } from "../api/client";
import type { MetricValue } from "../api/types";
import { canCertify, useSession } from "../auth/session";
import { DrScopeBadge } from "../components/DrScopeBadge";
import { OpsBadge } from "../components/OpsBadge";
import { Receipt } from "../components/Receipt";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { copy } from "../copy";
import { isOps, isPreVerification, isSimulated } from "../detail";
import { parseDrScope } from "../regulatory/drRules";

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function unitLabel(code: string): string {
  return copy.unitLabels[code] ?? code;
}

function periodLabel(value: MetricValue): string {
  return `${value.period_start} to ${value.period_end}`;
}

/**
 * Read-only metrics table. The certify flow that used to live inline here
 * moved to the certification cockpit at /certify (handoff 0007's deferred
 * pillar — one screen showing exactly what a signature covers); this view
 * keeps a plain note pointing there for the certifying official.
 */
export function MetricsView() {
  const session = useSession();
  const [values, setValues] = useState<MetricValue[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [openDetails, setOpenDetails] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setValues(await listMetricValues());
    } catch (err) {
      setValues(null);
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleDetails = (id: string) => {
    setOpenDetails((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const showCertifyLink = canCertify(session); // UX only; API enforces
  const anyPreVerification = (values ?? []).some(isPreVerification);

  return (
    <>
      <h1>{copy.metrics.heading}</h1>

      {showCertifyLink && (
        <p className="banner">
          {copy.metrics.certifyMoved}{" "}
          <Link to="/certify">{copy.metrics.certifyMovedLink}</Link>
        </p>
      )}

      {anyPreVerification && (
        <p className="banner">{copy.metrics.preVerificationBanner}</p>
      )}

      {loadError && (
        <div role="alert" className="alert">
          {loadError}
        </div>
      )}

      {values && values.length === 0 && <p>{copy.metrics.empty}</p>}
      {!values && !loadError && <p>{copy.loading}</p>}

      {values && values.length > 0 && (
        /* role/tabIndex: a horizontally scrollable region must be
           keyboard-reachable and named (axe: scrollable-region-focusable) */
        <div
          className="table-wrap"
          role="region"
          aria-label={copy.metrics.heading}
          tabIndex={0}
        >
          <table>
            <caption>{copy.metrics.tableCaption}</caption>
            <thead>
              <tr>
                <th scope="col">{copy.metrics.columns.metric}</th>
                <th scope="col">{copy.metrics.columns.unit}</th>
                <th scope="col">{copy.metrics.columns.period}</th>
                <th scope="col">{copy.metrics.columns.value}</th>
                <th scope="col">{copy.metrics.columns.calc}</th>
                <th scope="col">{copy.metrics.columns.status}</th>
                <th scope="col">{copy.metrics.columns.details}</th>
                <th scope="col">{copy.metrics.columns.provenance}</th>
              </tr>
            </thead>
            <tbody>
              {values.map((v) => {
                // Every figure opens a Receipt (handoff 0007 pillar 1:
                // "every displayed figure is interactive") — even a
                // detail-less one still has its story, its FTA rule, its
                // flags, and its walk to raw records.
                const detailsOpen = openDetails.has(v.metric_value_id);
                return (
                  <Fragment key={v.metric_value_id}>
                    <tr>
                      <th scope="row">
                        {metricLabel(v.metric)}
                        {/* The DR mode/TOS badge (handoff 0013): DR-scoped
                            rows must never look like fleet rows. */}
                        {parseDrScope(v.scope) && (
                          <>
                            {" "}
                            <DrScopeBadge scope={v.scope} />
                          </>
                        )}
                        {/* The ops badge (handoff 0014): an operations
                            metric never looks like an NTD figure. */}
                        {isOps(v) && (
                          <>
                            {" "}
                            <OpsBadge />
                          </>
                        )}
                        {isSimulated(v.detail) && (
                          <>
                            {" "}
                            <SimulatedBadge />
                          </>
                        )}
                      </th>
                      <td>{unitLabel(v.unit)}</td>
                      <td>{periodLabel(v)}</td>
                      {/* The figure, verbatim as the API served it. Never
                          parsed, rounded, or reformatted client-side. */}
                      <td className="figure">{v.value}</td>
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
                        <button
                          type="button"
                          aria-expanded={detailsOpen}
                          onClick={() => toggleDetails(v.metric_value_id)}
                        >
                          {copy.metrics.columns.details}
                          <span className="visually-hidden">
                            {` — ${metricLabel(v.metric)}, ${periodLabel(v)}`}
                          </span>
                        </button>
                      </td>
                      <td>
                        <Link to={`/metrics/${v.metric_value_id}/lineage`}>
                          {copy.metrics.explainLink}
                          <span className="visually-hidden">
                            {` — ${metricLabel(v.metric)}, ${periodLabel(v)}`}
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
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
