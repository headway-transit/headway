/**
 * The attention pulse on a flagged mark (handoff 0043, design point 6).
 *
 * WHAT THE GLOW IS ALLOWED TO MEAN
 * --------------------------------
 * "Look here." Nothing else. It never means good, never means bad, never
 * means big. It is drawn on the FRAME of a flagged mark — a ring around it,
 * with no fill — so it can never sit behind a figure and inflate it, which
 * is the same rule the dashboard's attention rail follows (`.attn::before`,
 * handoff 0041). It is scarce by construction: the layer it animates holds
 * only open, blocking findings, capped (findings.ts).
 *
 * And it is an AMPLIFIER, never the signal. Every flagged item also carries
 * a reserved shape (▲) and a text label on the canvas, a row in the "needs
 * investigation" list beside the map, and its severity in words — so a
 * viewer who never perceives the pulse loses nothing but the nudge.
 *
 * REDUCED MOTION
 * --------------
 * `prefers-reduced-motion: reduce` collapses the pulse to a STATIC ring at
 * full strength — the house rule is instant, never "slower" (handoff 0041).
 * The ring itself never disappears, because it is part of the mark.
 *
 * ONE PAINT PROPERTY, A HANDFUL OF FEATURES
 * -----------------------------------------
 * The loop calls `setPaintProperty` on the findings ring layer only. That
 * layer is capped at FLAG_CAP features; the vehicle layers are never
 * touched by it, so a quiet 900-vehicle fleet costs nothing per frame.
 */

/** One full breath, in milliseconds. Slow enough to read as attention, not
 *  as an alarm. */
export const PULSE_PERIOD_MS = 2600;

/** The ring at rest, and at full breath (px). */
export const PULSE_RADIUS = { min: 11, max: 17 };
export const PULSE_STROKE = { min: 1.4, max: 2.6 };

export interface PulseFrame {
  radius: number;
  strokeWidth: number;
  strokeOpacity: number;
}

/** The ring drawn when motion is reduced (and the first frame otherwise). */
export const PULSE_STATIC: PulseFrame = {
  radius: PULSE_RADIUS.min,
  strokeWidth: PULSE_STROKE.max,
  strokeOpacity: 1,
};

/**
 * The ring at `elapsed` ms into the loop. A raised cosine, so the breath has
 * no corner at either end and the loop is seamless.
 */
export function pulseFrame(elapsed: number): PulseFrame {
  const phase = ((elapsed % PULSE_PERIOD_MS) + PULSE_PERIOD_MS) %
    PULSE_PERIOD_MS / PULSE_PERIOD_MS;
  const eased = 0.5 - 0.5 * Math.cos(phase * 2 * Math.PI);
  return {
    radius: PULSE_RADIUS.min + eased * (PULSE_RADIUS.max - PULSE_RADIUS.min),
    strokeWidth:
      PULSE_STROKE.max - eased * (PULSE_STROKE.max - PULSE_STROKE.min),
    strokeOpacity: 1 - eased * 0.6,
  };
}
