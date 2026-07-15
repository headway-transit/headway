/**
 * A comparison delta (handoff 0017, design point 1 — binding rules):
 *
 * - The delta itself is SERVER-computed (exact decimal arithmetic) and
 *   arrives as a signed decimal STRING. This component never subtracts two
 *   figures; its only string work is reading the sign character and
 *   stripping it for the displayed magnitude (the ratioToPercentString
 *   discipline: string operations, never parseFloat).
 * - SIGN-NEUTRAL by default: a direction glyph (▲/▼) + the magnitude, in
 *   the muted text color for BOTH directions — more VRM is not "better",
 *   it is just more. Red/green appears ONLY when the metric's registry
 *   direction says the metric defines better/worse (coverage only today),
 *   and then always WITH the words "better"/"worse" — never color alone.
 */

import { copy } from "../copy";

/** "-120.50" → sign; string inspection only. */
function deltaSign(delta: string): "up" | "down" | "zero" {
  const trimmed = delta.trim();
  if (/^-?0(\.0*)?$/.test(trimmed)) return "zero";
  return trimmed.startsWith("-") ? "down" : "up";
}

/** The magnitude: the served string with a leading sign stripped. */
function deltaMagnitude(delta: string): string {
  return delta.trim().replace(/^[+-]/, "");
}

export interface DeltaFigureProps {
  /** The server's signed decimal delta string, or null (stated, not blank). */
  delta: string | null;
  /**
   * The metric registry's direction as the API serves it
   * (CompareResponse.directions[metric]): "higher_is_better" |
   * "lower_is_better" | null. null (or anything unrecognized) renders
   * sign-neutral — the safe default for an unregistered metric.
   */
  direction: string | null;
  /** What the delta is against ("the baseline", "the previous comparand"). */
  versus: string;
}

export function DeltaFigure({ delta, direction, versus }: DeltaFigureProps) {
  const d = copy.compare.delta;
  if (delta === null) {
    return <span className="delta">{d.notComparable(versus)}</span>;
  }
  const sign = deltaSign(delta);
  if (sign === "zero") {
    return (
      <span className="delta">
        <span className="delta-glyph" aria-hidden="true">
          =
        </span>{" "}
        {d.noChange(versus)}
      </span>
    );
  }
  const magnitude = deltaMagnitude(delta);
  // Registry-directed metrics (coverage only today): better/worse in words
  // AND color. Everything else: sign-neutral (muted, both directions).
  let judged: "better" | "worse" | null = null;
  if (direction === "higher_is_better") {
    judged = sign === "up" ? "better" : "worse";
  } else if (direction === "lower_is_better") {
    judged = sign === "up" ? "worse" : "better";
  }
  const words =
    sign === "up" ? d.more(magnitude, versus) : d.less(magnitude, versus);
  return (
    <span className={`delta${judged ? ` ${judged}` : ""}`}>
      <span className="delta-glyph" aria-hidden="true">
        {sign === "up" ? "▲" : "▼"}
      </span>{" "}
      {words}
      {judged && ` — ${d.judgement[judged]}`}
    </span>
  );
}
