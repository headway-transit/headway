/**
 * KPI trend sparkline (handoff 0024, design point 2).
 *
 * BINDING rules, enforced here:
 * - Every point IS a persisted figure (a /metrics/history row, verbatim):
 *   the visible dot is a real <button> whose accessible name carries the
 *   figure's exact value string, and pressing it opens the figure's full
 *   Receipt — receipts are one click away, never further.
 * - GAPS RENDER AS GAPS: a calendar bucket with no figure breaks the line
 *   (nothing is drawn across it) and the absence is stated in words below
 *   the sparkline. Interpolation is forbidden.
 * - NUMBERS STAY SACRED: `Number(point.value)` is GEOMETRY ONLY (dot
 *   position); every displayed/announced value is the API's string
 *   verbatim. A value that does not parse cannot be positioned and is not
 *   drawn — it still exists on the Metrics page (nothing hidden, stated by
 *   the cap/coverage lines).
 * - Certification status is never color-alone: certified points differ by
 *   SHAPE (filled square vs round outline) and every point's accessible
 *   name states its status.
 */

import type { HistoryPoint } from "../../api/types";
import { copy } from "../../copy";
import type { HistoryBucketKind } from "../../reports/buckets";
import { enumerateBucketKeys } from "../../reports/buckets";

export interface SparklinePoint {
  point: HistoryPoint;
  /** The server-assigned calendar bucket key this figure was grouped in. */
  bucketKey: string;
}

export interface SparklineProps {
  /** Plain-language metric label (for the group's accessible name). */
  metricLabel: string;
  unit: string;
  bucket: HistoryBucketKind;
  points: SparklinePoint[];
  /** metric_value_id of the point whose receipt is open (aria-expanded). */
  openId: string | null;
  onToggle: (point: HistoryPoint) => void;
}

/** Most recent figures drawn per sparkline — the cap is STATED when hit. */
const POINT_CAP = 60;

/** Internal drawing box; the svg stretches, strokes stay 2px. */
const W = 240;
const H = 48;
const PAD_Y = 8;

function periodLabel(p: HistoryPoint): string {
  return p.period_start === p.period_end
    ? p.period_start
    : `${p.period_start} to ${p.period_end}`;
}

export function Sparkline({
  metricLabel,
  unit,
  bucket,
  points,
  openId,
  onToggle,
}: SparklineProps) {
  if (points.length === 0) return null;

  // Chronological order (period, then computed_at, then id — the server's
  // own stable ordering), most recent POINT_CAP kept.
  const sorted = [...points].sort((a, b) => {
    const pa = a.point;
    const pb = b.point;
    if (pa.period_start !== pb.period_start)
      return pa.period_start < pb.period_start ? -1 : 1;
    if (pa.computed_at !== pb.computed_at)
      return pa.computed_at < pb.computed_at ? -1 : 1;
    return pa.metric_value_id < pb.metric_value_id ? -1 : 1;
  });
  const capped = sorted.length > POINT_CAP;
  const shown = capped ? sorted.slice(sorted.length - POINT_CAP) : sorted;

  // The calendar x axis: every bucket from the first shown key to the last,
  // so a bucket the data skipped is VISIBLE ABSENCE.
  const keys = enumerateBucketKeys(
    shown[0].bucketKey,
    shown[shown.length - 1].bucketKey,
    bucket,
  );
  const keyIndex = new Map(keys.map((k, i) => [k, i]));
  const perBucket = new Map<string, SparklinePoint[]>();
  for (const sp of shown) {
    const list = perBucket.get(sp.bucketKey) ?? [];
    list.push(sp);
    perBucket.set(sp.bucketKey, list);
  }
  const gapCount = keys.filter((k) => !perBucket.has(k)).length;

  // Geometry (positions only; never displayed).
  interface Placed {
    sp: SparklinePoint;
    xFrac: number;
    yFrac: number;
  }
  const drawable = shown.filter((sp) => Number.isFinite(Number(sp.point.value)));
  const yMax = Math.max(...drawable.map((sp) => Number(sp.point.value)), 0);
  const placed: Placed[] = [];
  for (const sp of shown) {
    const idx = keyIndex.get(sp.bucketKey);
    if (idx === undefined) continue;
    const siblings = perBucket.get(sp.bucketKey) ?? [sp];
    const within = siblings.indexOf(sp);
    const xFrac =
      (idx + (within + 1) / (siblings.length + 1)) / Math.max(keys.length, 1);
    const y = Number(sp.point.value);
    if (!Number.isFinite(y)) continue; // unpositionable — not drawn, stated
    const yFrac =
      yMax > 0 ? 1 - (Math.min(y, yMax) / yMax) * ((H - 2 * PAD_Y) / H) - PAD_Y / H : 0.5;
    placed.push({ sp, xFrac, yFrac });
  }

  // Line segments between CONSECUTIVE drawn points — broken wherever a
  // calendar bucket with no figure lies between them (the gap rule).
  const segments: string[] = [];
  let current: string[] = [];
  for (let i = 0; i < placed.length; i++) {
    const here = placed[i];
    if (i > 0) {
      const prev = placed[i - 1];
      const a = keyIndex.get(prev.sp.bucketKey) ?? 0;
      const b = keyIndex.get(here.sp.bucketKey) ?? 0;
      let gapBetween = false;
      for (let k = a + 1; k < b; k++) {
        if (!perBucket.has(keys[k])) gapBetween = true;
      }
      if (gapBetween) {
        if (current.length > 1) segments.push(current.join(" "));
        current = [];
      }
    }
    current.push(
      `${current.length === 0 ? "M" : "L"}${(here.xFrac * W).toFixed(2)},${(here.yFrac * H).toFixed(2)}`,
    );
  }
  if (current.length > 1) segments.push(current.join(" "));

  const t = copy.dashboard.sparkline;
  return (
    <div className="sparkline-block">
      <div
        className="sparkline"
        role="group"
        aria-label={t.label(metricLabel)}
      >
        <svg
          className="sparkline-svg"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          aria-hidden="true"
          focusable="false"
        >
          {segments.map((d) => (
            <path key={d} className="sparkline-line" d={d} />
          ))}
        </svg>
        {placed.map(({ sp, xFrac, yFrac }) => {
          const p = sp.point;
          const certified = p.certification_status === "certified";
          return (
            <button
              key={p.metric_value_id}
              type="button"
              className={`spark-point${certified ? " certified" : ""}`}
              style={{
                left: `${(xFrac * 100).toFixed(2)}%`,
                top: `${(yFrac * 100).toFixed(2)}%`,
              }}
              aria-expanded={openId === p.metric_value_id}
              onClick={() => onToggle(p)}
            >
              <span className="visually-hidden">
                {t.pointLabel(
                  p.value,
                  unit,
                  periodLabel(p),
                  p.certification_status,
                )}
              </span>
            </button>
          );
        })}
      </div>
      {gapCount > 0 && (
        <p className="sparkline-note">{t.gapsNote(String(gapCount))}</p>
      )}
      {capped && (
        <p className="sparkline-note">
          {t.pointCap(String(POINT_CAP), String(sorted.length))}
        </p>
      )}
    </div>
  );
}
