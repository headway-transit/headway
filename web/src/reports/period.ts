/**
 * Calendar-month period SELECTION for the Monthly Ridership report. This is
 * UI logic (which month to ask the API for) — date math never touches a
 * reported figure.
 */

/** First/last calendar day of a month as ISO dates. `month` is 1–12. */
export function monthPeriod(
  year: number,
  month: number,
): { period_start: string; period_end: string } {
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const mm = String(month).padStart(2, "0");
  return {
    period_start: `${year}-${mm}-01`,
    period_end: `${year}-${mm}-${String(lastDay).padStart(2, "0")}`,
  };
}

/**
 * "2026-06" -> HALF-OPEN period [2026-06-01, 2026-07-01) — the calc
 * runner's period convention (handoff 0026: the start date is included,
 * the end date is not). Calendar arithmetic on a picker label, never on a
 * figure. Distinct from monthPeriod above, which builds the CLOSED
 * first..last-day range the Monthly Ridership report endpoint expects.
 */
export function halfOpenMonthPeriod(month: string): {
  period_start: string;
  period_end: string;
} {
  const [y, m] = month.split("-").map((part) => parseInt(part, 10));
  const nextY = m === 12 ? y + 1 : y;
  const nextM = m === 12 ? 1 : m + 1;
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    period_start: `${y}-${pad(m)}-01`,
    period_end: `${nextY}-${pad(nextM)}-01`,
  };
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** The last 12 calendar months (newest first), UTC-anchored — the
 *  calculations room's month presets. */
export function recentMonthOptions(
  now: Date = new Date(),
): { value: string; label: string }[] {
  const options = [];
  let y = now.getUTCFullYear();
  let m = now.getUTCMonth() + 1; // 1-based
  for (let i = 0; i < 12; i++) {
    options.push({
      value: `${y}-${String(m).padStart(2, "0")}`,
      label: `${MONTH_NAMES[m - 1]} ${y}`,
    });
    m -= 1;
    if (m === 0) {
      m = 12;
      y -= 1;
    }
  }
  return options;
}

/** The previous calendar month — the month being reported on. */
export function previousMonth(today: Date): { year: number; month: number } {
  const year = today.getFullYear();
  const month = today.getMonth() + 1;
  return month === 1
    ? { year: year - 1, month: 12 }
    : { year, month: month - 1 };
}
