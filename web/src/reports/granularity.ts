/**
 * Period-granularity bucketing for the dashboard chart filters (maintainer feedback #1).
 *
 * THE RULE, stated once and enforced everywhere: bucketing is DATE MATH ON
 * PERIOD BOUNDARIES ONLY — deciding which hour/day/week/month/quarter a
 * reported period belongs to. Displayed FIGURES stay the API's strings
 * verbatim. Aggregating display values into buckets (summing daily figures
 * into a "weekly" figure client-side) is FORBIDDEN: a browser-added number
 * would be a figure nobody computed, certified, or can trace. So when the
 * selected granularity is COARSER than the rows the API served, the charts
 * show the rows they have, each verbatim, with an honest "showing N periods
 * as reported" note — never a client-side sum.
 */

export type Granularity =
  | "hourly"
  | "daily"
  | "weekly"
  | "monthly"
  | "quarterly";

/** Display order of the granularity toggle group. */
export const GRANULARITIES: Granularity[] = [
  "hourly",
  "daily",
  "weekly",
  "monthly",
  "quarterly",
];

/** Days in a month via UTC date math — period SELECTION only, never figures. */
function lastDayOfMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

function iso(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Parse an ISO date (YYYY-MM-DD) into UTC parts; null when malformed. */
function parts(isoDate: string): { y: number; m: number; d: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!m) return null;
  return { y: Number(m[1]), m: Number(m[2]), d: Number(m[3]) };
}

/**
 * Whether one reported period EXACTLY spans a bucket of the selected
 * granularity (e.g. a 2026-02-01..2026-02-28 row spans a monthly bucket).
 * When every charted row spans its bucket, the chart's periods and the
 * selected granularity agree; otherwise the honest as-reported note shows.
 *
 * Hourly can never be spanned: the API serves date-only periods, so the
 * finest period a row can state is one full day.
 */
export function spansBucket(
  periodStart: string,
  periodEnd: string,
  granularity: Granularity,
): boolean {
  const p = parts(periodStart);
  if (!p) return false;
  switch (granularity) {
    case "hourly":
      return false;
    case "daily":
      return periodStart === periodEnd;
    case "weekly": {
      // ISO week: Monday..Sunday, via UTC day-of-week math.
      const date = new Date(Date.UTC(p.y, p.m - 1, p.d));
      if ((date.getUTCDay() + 6) % 7 !== 0) return false; // starts on Monday?
      const end = new Date(date);
      end.setUTCDate(end.getUTCDate() + 6);
      return (
        periodEnd ===
        iso(end.getUTCFullYear(), end.getUTCMonth() + 1, end.getUTCDate())
      );
    }
    case "monthly":
      return (
        p.d === 1 && periodEnd === iso(p.y, p.m, lastDayOfMonth(p.y, p.m))
      );
    case "quarterly": {
      const qStart = Math.floor((p.m - 1) / 3) * 3 + 1;
      const qEndMonth = qStart + 2;
      return (
        p.d === 1 &&
        p.m === qStart &&
        periodEnd === iso(p.y, qEndMonth, lastDayOfMonth(p.y, qEndMonth))
      );
    }
  }
}

export interface PeriodRow {
  period_start: string;
  period_end: string;
}

/**
 * How many of the given rows do NOT line up with the selected granularity.
 * > 0 means the chart must carry the "showing N periods as reported" note
 * (and must NEVER sum — see the module comment).
 */
export function misalignedCount(
  rows: PeriodRow[],
  granularity: Granularity,
): number {
  return rows.filter(
    (r) => !spansBucket(r.period_start, r.period_end, granularity),
  ).length;
}

/**
 * Date-range SELECTION: does a reported period overlap [from, to]? Empty
 * bound = unbounded. ISO date strings compare lexicographically, so this is
 * pure string comparison — no reported value is ever parsed.
 */
export function overlapsRange(
  periodStart: string,
  periodEnd: string,
  from: string,
  to: string,
): boolean {
  return (from === "" || periodEnd >= from) && (to === "" || periodStart <= to);
}
