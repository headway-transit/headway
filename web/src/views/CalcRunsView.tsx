import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  listCalcRuns,
  startCalcRun,
} from "../api/client";
import type { CalcRunMetricOutcome, CalcRunRecord } from "../api/types";
import { canComputeFigures, useSession } from "../auth/session";
import { Skeleton } from "../components/Skeleton";
import { copy } from "../copy";
import {
  halfOpenMonthPeriod,
  recentMonthOptions,
} from "../reports/period";
import { pushToast } from "../toasts";

/**
 * The calculations room (/calc-runs — handoff 0026): "Compute figures".
 *
 * This page STARTS the server's deterministic calculation runner and shows
 * what it reported — it never computes, edits, or rounds a number. Every
 * figure, count, and id below is the API's string verbatim.
 *
 * Honesty rules embodied here:
 * - Refusals are FIRST-CLASS: a run whose calculations all withheld their
 *   figures renders plainly (no red-alarm theater, no animation) with the
 *   exact blocking data-quality findings linked, and the house-voice
 *   teaching block explains that the refusal is Headway working as designed.
 * - No fake progress: a live run shows its real start time ("running since
 *   HH:MM:SS UTC") and nothing else — there is no percentage to show, so
 *   none is shown.
 * - The single-flight 409 renders VERBATIM at the control.
 * - Staleness is the server's call (stale + stale_note), rendered verbatim.
 * - The run button uses aria-disabled (never native disabled) with the
 *   reason always visible at the control; the live-run region is aria-busy.
 * - Role gating here is UX only — the API enforces data_steward+ on POST.
 */

const cr = copy.calcRuns;

/** Poll cadence while a run is live: the run takes minutes; 5 s keeps the
 *  page honest without hammering the API. */
const POLL_INTERVAL_MS = 5_000;

/** ISO timestamp -> "HH:MM:SS UTC" (display formatting, not a figure). */
function utcTime(iso: string): string {
  return `${new Date(iso).toISOString().slice(11, 19)} UTC`;
}

/** ISO timestamp -> "YYYY-MM-DD HH:MM:SS UTC". */
function utcStamp(iso: string): string {
  const d = new Date(iso).toISOString();
  return `${d.slice(0, 10)} ${d.slice(11, 19)} UTC`;
}

/** Seconds -> plain words ("4 minutes 12 seconds"). The input is the
 *  server's duration (two timestamps' difference), never a figure. */
function durationWords(seconds: number): string {
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  if (minutes === 0) return `${rest} second${rest === 1 ? "" : "s"}`;
  return `${minutes} minute${minutes === 1 ? "" : "s"} ${rest} second${
    rest === 1 ? "" : "s"
  }`;
}

function isLive(run: CalcRunRecord): boolean {
  return (run.status === "queued" || run.status === "running") && !run.stale;
}

export function CalcRunsView() {
  const session = useSession();
  const mayCompute = canComputeFigures(session);
  const ids = {
    month: useId(),
    customStart: useId(),
    customEnd: useId(),
    reason: useId(),
  };

  const [runs, setRuns] = useState<CalcRunRecord[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  // The month presets are computed once per mount (calendar labels).
  const monthsRef = useRef(recentMonthOptions());
  const months = monthsRef.current;
  // Default: the previous calendar month — the period most likely complete.
  const [monthChoice, setMonthChoice] = useState<string>(
    months[1]?.value ?? "",
  );
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [starting, setStarting] = useState(false);
  // The server's refusal (the single-flight 409, a validation 422, ...)
  // rendered VERBATIM at the control.
  const [startError, setStartError] = useState<string | null>(null);

  const refresh = () => {
    listCalcRuns()
      .then((rows) => {
        setRuns(rows);
        setListError(null);
      })
      .catch((err) =>
        setListError(err instanceof ApiError ? err.message : String(err)),
      );
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const liveRun = (runs ?? []).find(isLive) ?? null;

  // Poll while a run is live; the DB row (not this page's memory) is the
  // truth, so a refresh mid-run shows exactly the same state.
  useEffect(() => {
    if (!liveRun) return;
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveRun?.run_id, liveRun?.status]);

  const period =
    monthChoice === "custom"
      ? customStart && customEnd
        ? { period_start: customStart, period_end: customEnd }
        : null
      : monthChoice
        ? halfOpenMonthPeriod(monthChoice)
        : null;

  const runDisabled = period === null || liveRun !== null || starting;

  const handleRun = async () => {
    // aria-disabled house pattern: the click lands here; the always-visible
    // reason line at the control says why nothing happened.
    if (runDisabled || period === null) return;
    setStarting(true);
    setStartError(null);
    try {
      await startCalcRun(period);
      pushToast(cr.startedToast);
      refresh();
    } catch (err) {
      setStartError(err instanceof ApiError ? err.message : String(err));
      // A 409 means a run is live that this page had not seen yet — pick
      // it up so the button's reason and the history agree with the server.
      refresh();
    } finally {
      setStarting(false);
    }
  };

  const newest = runs?.[0] ?? null;

  return (
    <>
      <h1>{cr.heading}</h1>
      <p>{cr.intro}</p>
      <p>{cr.refusalTeachingIntro}</p>

      {mayCompute ? (
        <section className="card" aria-label={cr.periodHeading}>
          <h2>{cr.periodHeading}</h2>
          <p>{cr.periodHint}</p>
          <div className="chart-filters">
            <div className="date-range-field">
              <label htmlFor={ids.month}>{cr.monthLabel}</label>
              <select
                id={ids.month}
                value={monthChoice}
                onChange={(e) => setMonthChoice(e.target.value)}
              >
                {months.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
                <option value="custom">{cr.customOption}</option>
              </select>
            </div>
            {monthChoice === "custom" && (
              <>
                <div className="date-range-field">
                  <label htmlFor={ids.customStart}>{cr.customStartLabel}</label>
                  <input
                    id={ids.customStart}
                    type="date"
                    value={customStart}
                    onChange={(e) => setCustomStart(e.target.value)}
                  />
                </div>
                <div className="date-range-field">
                  <label htmlFor={ids.customEnd}>{cr.customEndLabel}</label>
                  <input
                    id={ids.customEnd}
                    type="date"
                    value={customEnd}
                    onChange={(e) => setCustomEnd(e.target.value)}
                  />
                </div>
              </>
            )}
          </div>
          <p>
            <button
              type="button"
              className="primary"
              aria-disabled={runDisabled || undefined}
              aria-busy={starting || undefined}
              aria-describedby={runDisabled ? ids.reason : undefined}
              onClick={handleRun}
            >
              {liveRun || starting ? cr.runningButton : cr.runButton}
            </button>
          </p>
          {runDisabled && (
            <div
              id={ids.reason}
              className="certify-reason"
              aria-label={cr.reasonLabel}
            >
              {period === null && <p>{cr.reasonPickPeriod}</p>}
              {period !== null && (liveRun !== null || starting) && (
                <p>{cr.reasonRunLive}</p>
              )}
            </div>
          )}
          {/* The server's refusal — the single-flight 409, a validation
              message — VERBATIM at the control. */}
          {startError && (
            <div role="alert" className="alert">
              {startError}
            </div>
          )}
          <p className="field-hint">{cr.scopeNote}</p>
        </section>
      ) : (
        <p className="banner">{cr.viewerNote}</p>
      )}

      <section aria-label={cr.historyHeading}>
        <h2>{cr.historyHeading}</h2>
        <p>{cr.historyIntro}</p>
        {listError && (
          <div role="alert" className="alert">
            {listError}
          </div>
        )}
        {runs === null && !listError && <Skeleton variant="table" count={3} />}
        {runs !== null && runs.length === 0 && <p>{cr.historyEmpty}</p>}
        {runs !== null && runs.length > 0 && (
          <ul className="issue-list" aria-label={cr.tableCaption}>
            {runs.map((run) => (
              <RunCard
                key={run.run_id}
                run={run}
                showTeaching={run === newest && run.status === "refused"}
              />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function RunCard({
  run,
  showTeaching,
}: {
  run: CalcRunRecord;
  showTeaching: boolean;
}) {
  const live = run.status === "queued" || run.status === "running";
  const summary = run.summary;
  const outcomes = summary?.metrics ?? [];
  const periodLabel = `${run.period_start} to ${run.period_end}`;
  return (
    <li
      className={`card run-card run-${run.status}`}
      // Honest liveness for assistive tech: the region is busy while the
      // server is working. No spinner, no bar — the poll updates the text.
      aria-busy={(live && !run.stale) || undefined}
    >
      <h3>
        {cr.statusLabels[run.status] ?? run.status}
        {run.stale && <> — {cr.staleTag}</>}
      </h3>
      <p>{cr.statusExplanations[run.status] ?? null}</p>
      {/* The server's staleness note, verbatim. */}
      {run.stale && run.stale_note && (
        <p className="banner">{run.stale_note}</p>
      )}
      <p>
        {cr.periodLine(run.period_start, run.period_end)}{" "}
        {cr.requestedLine(run.requested_by, utcStamp(run.requested_at))}
      </p>
      {/* Timing, honestly: a real start time while live (never a progress
          percentage), the timestamps' difference once finished. */}
      {live && !run.stale && run.status === "running" && run.started_at && (
        <p>{cr.runningSince(utcTime(run.started_at))}</p>
      )}
      {live && !run.stale && run.status === "queued" && (
        <p>{cr.queuedAt(utcTime(run.requested_at))}</p>
      )}
      {run.duration_seconds !== null && (
        <p>{cr.durationLine(durationWords(run.duration_seconds))}</p>
      )}

      {/* Failed: the dispatcher's recorded reason, verbatim; the runner
          output tail behind a plain disclosure. */}
      {run.status === "failed" && summary?.error && (
        <>
          <p>{cr.failedLead}</p>
          <div role="alert" className="alert">
            {summary.error}
          </div>
        </>
      )}

      {/* The per-calc outcome table (succeeded AND refused runs both have
          one — refusals are outcomes, not absences). */}
      {(run.status === "succeeded" || run.status === "refused") &&
        summary && (
          <>
            <p>
              {cr.summaryCounts(
                summary.persisted_count ?? 0,
                summary.blocked_count ?? 0,
              )}{" "}
              {summary.positions_loaded !== null &&
                summary.positions_loaded !== undefined &&
                cr.summaryContext(
                  String(summary.positions_loaded),
                  String(summary.passenger_events_loaded ?? 0),
                )}
            </p>
            {summary.coverage_threshold && (
              <p>
                {cr.thresholdContext(
                  summary.coverage_threshold,
                  summary.threshold_sources?.coverage_threshold ?? "settings",
                )}
              </p>
            )}
            {outcomes.length > 0 && (
              <table>
                <caption>{cr.outcomeTableCaption(periodLabel)}</caption>
                <thead>
                  <tr>
                    <th scope="col">{cr.outcomeColumns.calc}</th>
                    <th scope="col">{cr.outcomeColumns.scope}</th>
                    <th scope="col">{cr.outcomeColumns.outcome}</th>
                    <th scope="col">{cr.outcomeColumns.figure}</th>
                    <th scope="col">{cr.outcomeColumns.links}</th>
                  </tr>
                </thead>
                <tbody>
                  {outcomes.map((o, i) => (
                    <OutcomeRow key={`${o.calc_name}-${o.scope}-${i}`} o={o} />
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

      {showTeaching && (
        <aside className="banner" aria-label={cr.refusedTeachingHeading}>
          <h4>{cr.refusedTeachingHeading}</h4>
          <p>{cr.refusedTeachingBody}</p>
          <p>
            <Link to="/dq">{cr.refusedTeachingDoor}</Link>
          </p>
        </aside>
      )}

      {run.stdout_tail && (
        <details>
          <summary>{cr.outputTailToggle}</summary>
          <pre aria-label={cr.outputTailLabel}>{run.stdout_tail}</pre>
        </details>
      )}
    </li>
  );
}

function OutcomeRow({ o }: { o: CalcRunMetricOutcome }) {
  const persisted = o.outcome === "persisted";
  return (
    <tr>
      <td>
        {o.calc_name} {o.calc_version}
      </td>
      <td>{o.scope}</td>
      <td>
        {persisted ? cr.outcomePersisted : cr.outcomeRefused}
        {o.coverage && (
          <>
            {" "}
            <span className="field-hint">{cr.coverageLine(o.coverage)}</span>
          </>
        )}
      </td>
      <td>
        {/* The figure verbatim (the runner's string), or the refusal with
            its exact blocking findings linked. */}
        {persisted ? (
          <>
            {o.value} {o.unit}
            {o.already_on_record && (
              <>
                {" "}
                <span className="field-hint">{cr.outcomeAlreadyOnRecord}</span>
              </>
            )}
          </>
        ) : (
          <>
            {cr.refusedIssuesLead(o.blocking_issue_ids.length)}
            <ul>
              {o.blocking_issue_ids.map((issueId, n) => (
                <li key={issueId}>
                  <Link to={`/dq?issue=${encodeURIComponent(issueId)}`}>
                    {cr.refusedIssueLink(n + 1)}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </td>
      <td>
        {persisted && o.metric_value_id ? (
          <>
            <Link to="/metrics">{cr.persistedMetricsLink}</Link>{" "}
            <Link to={`/metrics/${encodeURIComponent(o.metric_value_id)}/lineage`}>
              {cr.persistedReceiptLink}
            </Link>
          </>
        ) : null}
      </td>
    </tr>
  );
}
