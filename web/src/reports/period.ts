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

/** The previous calendar month — the month being reported on. */
export function previousMonth(today: Date): { year: number; month: number } {
  const year = today.getFullYear();
  const month = today.getMonth() + 1;
  return month === 1
    ? { year: year - 1, month: 12 }
    : { year, month: month - 1 };
}
