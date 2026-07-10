/**
 * Client-side CSV assembly for the Monthly Ridership PREVIEW export.
 *
 * Every data cell is the API-served string VERBATIM — no parsing, rounding,
 * or arithmetic ever touches a figure (asserted in tests: exported cell ===
 * API string). Only CSV quoting is applied, and only when a cell contains a
 * delimiter/quote/newline; a plain decimal string passes through untouched.
 *
 * The export is a preview: the official NTD Monthly Ridership submission
 * format has not been verified against FTA's reporting system documentation
 * (tracked NTD-role item), so the file leads with the same disclaimer the
 * page shows and never claims to be a submission.
 */

import type { MetricValue } from "../api/types";
import { copy } from "../copy";
import { isSimulated } from "../detail";

/** Column order of the preview export — API contract field names. */
export const CSV_HEADER = [
  "metric",
  "unit",
  "period_start",
  "period_end",
  "value",
  "calc_name",
  "calc_version",
  "certification_status",
  "simulated_data",
] as const;

const SIMULATED_CELL = "SIMULATED DATA - MUST NOT BE SUBMITTED";

function escapeCsvCell(cell: string): string {
  return /[",\n\r]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell;
}

export function buildMonthlyRidershipCsv(values: MetricValue[]): string {
  const rows: string[][] = [
    [copy.report.disclaimer],
    [...CSV_HEADER],
    ...values.map((v) => [
      v.metric,
      v.unit,
      v.period_start,
      v.period_end,
      v.value, // VERBATIM — the exact string the API served
      v.calc_name,
      v.calc_version,
      v.certification_status,
      isSimulated(v.detail) ? SIMULATED_CELL : "no",
    ]),
  ];
  return (
    rows.map((row) => row.map(escapeCsvCell).join(",")).join("\r\n") + "\r\n"
  );
}
