/**
 * A compact in-row progress bar (handoff 0017, design point 3): used in the
 * sampling plans list (measured vs required per plan) and reusable for any
 * future checklist-shaped entity.
 *
 * Accessibility (binding): the value + label TEXT leads and the bar is the
 * visual echo — never bar-alone. Built on the house meter pattern (React
 * Aria useMeter, role pinned to "meter", aria-valuetext = the verbatim
 * sentence). The counts are API-served workflow counts; the ONE piece of
 * arithmetic here is the bar's position (display geometry, never a figure).
 * The "ready" state (target reached) is visually distinct — success fill +
 * an explicit tag — because reaching the required size is the state a
 * steward scans the list for.
 */

import { useMeter } from "react-aria";

export interface RowProgressProps {
  /** API-served counts (workflow tallies, not figures). */
  done: number;
  required: number;
  /** The full sentence, e.g. "40 of 48 required units measured." */
  text: string;
  /** Accessible name for the meter. */
  label: string;
  /** Target reached — render the visually distinct ready state. */
  ready?: boolean;
  /** The ready tag's text (rendered only when ready). */
  readyLabel?: string;
}

export function RowProgress({
  done,
  required,
  text,
  label,
  ready = false,
  readyLabel,
}: RowProgressProps) {
  // Bar position only: capped 0–100, display geometry (the text carries the
  // real counts verbatim).
  const percent =
    required > 0 ? Math.min(100, Math.round((done / required) * 100)) : 0;
  const { meterProps } = useMeter({
    value: percent,
    minValue: 0,
    maxValue: 100,
    valueLabel: text,
    "aria-label": label,
  });
  return (
    <div className={`row-progress${ready ? " ready" : ""}`}>
      <span className="row-progress-text">{text}</span>
      <span {...meterProps} role="meter" className="meter-track">
        <span className="meter-fill" style={{ width: `${percent}%` }} />
      </span>
      {ready && readyLabel && <span className="tag ready">{readyLabel}</span>}
    </div>
  );
}
