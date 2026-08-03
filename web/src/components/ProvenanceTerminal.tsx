/**
 * THE PROVENANCE TERMINAL (handoff 0044, output 4).
 *
 * A dense monospace stream of what this installation actually did: figures
 * computed, figures refused, runs opened and closed, findings raised.
 *
 * THE HONESTY RULES, WHICH ARE THE WHOLE POINT
 * --------------------------------------------
 * 1. EVERY ROW IS A REAL RECORDED EVENT. Each one is built from a record the
 *    API served — a `calc_runs` row (and the per-figure outcomes inside its
 *    summary) or a `dq.issues` row — carrying that record's OWN timestamp.
 *    There is no synthesised tick, no demo row, and no filler.
 * 2. IF THERE IS NOTHING, IT SAYS SO. An installation that has computed
 *    nothing shows the empty state, not invented activity.
 * 3. IT NEVER GRADES A FIGURE. A row says what happened. A computed figure
 *    takes the NEUTRAL rail; the semantic ok/watch/alert set appears only
 *    where the platform itself assigned a severity (a finding), and the
 *    identity accent marks Headway's own refusals — "we declined", which is
 *    neither good news nor bad news, it is the product working.
 * 4. REDUCED MOTION. The slide-in and the LIVE blink are CSS-only and
 *    `prefers-reduced-motion` removes both; the stream still updates.
 *
 * v0 POLLS (handoff 0044's own recommendation): the two endpoints already
 * exist and are already authorized, so this adds no new server surface to
 * secure or rate-limit. The cadence is stated on the panel.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, listCalcRuns, listDqIssues } from "../api/client";
import type { CalcRunRecord, DqIssueSummary } from "../api/types";
import { copy } from "../copy";

/** Poll cadence, in ms. Stated on the panel — never a hidden number. */
export const TERMINAL_POLL_MS = 30_000;
/** Rows kept on screen. The cap is stated beneath the stream. */
export const TERMINAL_CAP = 12;
/** Runs read per poll, and how many of them contribute per-figure rows. */
const RUN_LOOKBACK = 8;
const RUN_DETAIL = 3;
/** Findings read per poll. */
const FINDING_LOOKBACK = 12;

/** The four rails. `note` is the neutral one — no valence at all. */
export type TerminalTone = "note" | "sig" | "watch" | "alert";

export interface TerminalEvent {
  key: string;
  /** The RECORD's own ISO timestamp. Never generated here. */
  at: string;
  tag: string;
  tone: TerminalTone;
  message: string;
}

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function unitLabel(code: string | null): string {
  if (!code) return "";
  return copy.unitLabels[code] ?? code;
}

/** "HH:MM:SS" of an ISO timestamp — a time label, never a figure. */
export function terminalTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(11, 19);
}

function periodLabel(run: CalcRunRecord): string {
  return `${run.period_start}→${run.period_end}`;
}

/**
 * Runs → events. The run row itself, plus (for the newest few runs) one row
 * per figure the runner reported. Every string is the server's.
 */
export function runEvents(runs: CalcRunRecord[]): TerminalEvent[] {
  const t = copy.terminal;
  const out: TerminalEvent[] = [];
  runs.forEach((run, index) => {
    const at = run.finished_at ?? run.started_at ?? run.requested_at;
    const period = periodLabel(run);
    if (run.stale) {
      out.push({
        key: `run-${run.run_id}-stale`,
        at,
        tag: t.tags.stale,
        tone: "watch",
        message: t.rows.runStale(period),
      });
    } else if (run.status === "failed") {
      out.push({
        key: `run-${run.run_id}`,
        at,
        tag: t.tags.failed,
        tone: "alert",
        message: t.rows.runFailed(period, run.summary?.error ?? run.status),
      });
    } else if (run.status === "queued" || run.status === "running") {
      out.push({
        key: `run-${run.run_id}`,
        at,
        tag: run.status === "queued" ? t.tags.queued : t.tags.running,
        tone: "note",
        message: t.rows.runOpen(period),
      });
    } else {
      const persisted = run.summary?.persisted_count;
      const blocked = run.summary?.blocked_count;
      out.push({
        key: `run-${run.run_id}`,
        at,
        tag: run.status === "refused" ? t.tags.refused : t.tags.computed,
        tone: run.status === "refused" ? "sig" : "note",
        message: t.rows.runFinished(
          period,
          persisted === null || persisted === undefined
            ? "?"
            : String(persisted),
          blocked === null || blocked === undefined ? "?" : String(blocked),
        ),
      });
    }
    // Per-figure outcomes, newest runs only — the stream is a window on the
    // record, and the calculation-runs room holds the rest.
    if (index >= RUN_DETAIL) return;
    for (const outcome of run.summary?.metrics ?? []) {
      const metric = outcome.metric ? metricLabel(outcome.metric) : "figure";
      const scope = outcome.scope ?? "—";
      if (outcome.outcome === "refused") {
        out.push({
          key: `run-${run.run_id}-${outcome.calc_name}-${outcome.metric}-${scope}`,
          at,
          tag: t.tags.refused,
          tone: "sig",
          message: t.rows.figureRefused(
            metric,
            scope,
            String(outcome.blocking_issue_ids.length),
          ),
        });
      } else if (outcome.value !== null) {
        const unit = unitLabel(outcome.unit);
        out.push({
          key: `run-${run.run_id}-${outcome.calc_name}-${outcome.metric}-${scope}`,
          at,
          tag: t.tags.computed,
          tone: "note",
          message: t.rows.figureComputed(
            metric,
            scope,
            unit ? `${outcome.value} ${unit}` : outcome.value,
          ),
        });
      }
    }
  });
  return out;
}

/** Findings → events. Severity comes from the platform, not from this UI. */
export function findingEvents(issues: DqIssueSummary[]): TerminalEvent[] {
  const t = copy.terminal;
  return issues.map((issue) => ({
    key: `dq-${issue.issue_id}`,
    at: issue.created_at,
    tag: t.tags.raised,
    tone:
      issue.severity === "blocking"
        ? ("alert" as const)
        : issue.severity === "warning"
          ? ("watch" as const)
          : ("note" as const),
    message: t.rows.findingRaised(
      copy.dq.severityLabels[issue.severity] ?? issue.severity,
      issue.title,
    ),
  }));
}

/** Newest first, capped. Sorting only — nothing is combined or derived. */
export function mergeEvents(...groups: TerminalEvent[][]): TerminalEvent[] {
  return groups
    .flat()
    .sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0))
    .slice(0, TERMINAL_CAP);
}

type Load =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; events: TerminalEvent[] };

export function ProvenanceTerminal() {
  const t = copy.terminal;
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const seq = useRef(0);

  const poll = useCallback(() => {
    const mine = ++seq.current;
    Promise.all([
      listCalcRuns(RUN_LOOKBACK),
      listDqIssues({ limit: FINDING_LOOKBACK }),
    ])
      .then(([runs, page]) => {
        if (mine !== seq.current) return; // a newer poll superseded us
        setLoad({
          state: "ready",
          events: mergeEvents(runEvents(runs), findingEvents(page.issues)),
        });
      })
      .catch((err: unknown) => {
        if (mine !== seq.current) return;
        setLoad({
          state: "error",
          message: err instanceof ApiError ? err.message : String(err),
        });
      });
  }, []);

  useEffect(() => {
    poll();
    const timer = window.setInterval(poll, TERMINAL_POLL_MS);
    return () => window.clearInterval(timer);
  }, [poll]);

  const events = load.state === "ready" ? load.events : [];

  return (
    <section className="prov-terminal" aria-label={t.heading}>
      <div className="rail-head">
        <h2 className="rail-head-title">{t.heading}</h2>
        {/* LIVE is a state, said in a word. The dot only echoes it, and
            prefers-reduced-motion stops the dot without stopping the poll. */}
        <span className="term-live">
          <span aria-hidden="true" className="term-live-dot" />
          {t.live}
        </span>
      </div>
      {load.state === "loading" && <p className="term-note">{t.loading}</p>}
      {load.state === "error" && (
        <p className="term-note term-error" role="alert">
          {t.error(load.message)}
        </p>
      )}
      {load.state === "ready" && events.length === 0 && (
        <p className="term-note">{t.empty}</p>
      )}
      {events.length > 0 && (
        <ol className="term-stream">
          {events.map((e) => (
            <li key={e.key} className={`term-row term-${e.tone}`}>
              <time className="term-time" dateTime={e.at}>
                {terminalTime(e.at)}
              </time>
              <span className="term-msg">{e.message}</span>
              {/* The word carries the kind; the rail is only an echo. */}
              <span className="term-tag">{e.tag}</span>
            </li>
          ))}
        </ol>
      )}
      <p className="term-note">{t.cadence(String(TERMINAL_POLL_MS / 1000))}</p>
      <p className="term-note">{t.sources}</p>
      {events.length > 0 && (
        <p className="term-note">{t.cap(String(TERMINAL_CAP))}</p>
      )}
    </section>
  );
}

export default ProvenanceTerminal;
