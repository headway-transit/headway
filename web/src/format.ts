/**
 * String-only display formatting for API-served values.
 *
 * The guardrail: a reported figure or ratio is NEVER parsed into a JS number
 * (binary float would silently change it). Where the UI shows a ratio as a
 * percentage, the decimal point is shifted with STRING operations only.
 */

/**
 * "0.9126" -> "91.26", "0.02" -> "2", "1.0000" -> "100".
 *
 * Shifts a decimal-string ratio two places (x100) purely by moving the
 * decimal point in the string — no Number()/parseFloat ever touches it.
 * Anything that is not a plain decimal string is returned unchanged (shown
 * raw rather than guessed at).
 */
export function ratioToPercentString(ratio: string): string {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(ratio.trim());
  if (!m) return ratio;
  const sign = m[1];
  const intPart = m[2];
  const fracPart = m[3] ?? "";
  const intOut = (intPart + (fracPart + "00").slice(0, 2)).replace(
    /^0+(?=\d)/,
    "",
  );
  const fracOut = fracPart.slice(2).replace(/0+$/, "");
  return sign + intOut + (fracOut ? `.${fracOut}` : "");
}

/**
 * Render one JSON detail value for display. Strings pass through verbatim;
 * numbers/booleans use their canonical JSON text; anything structured is
 * shown as compact JSON — raw but tidy, never hidden.
 */
export function detailValueToString(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "none";
  if (typeof value === "number" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  return JSON.stringify(value);
}
