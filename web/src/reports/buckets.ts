/**
 * Calendar-bucket key enumeration for the audience-lens sparklines
 * (handoff 0024, design point 2).
 *
 * THE RULE: this module does DATE MATH ON BUCKET LABELS only — it mirrors
 * the server's bucket-key derivation (services/api routers/history.py,
 * bucket_key_for) so the UI can tell WHICH calendar buckets between two
 * served keys hold no figure. A bucket with no figure renders as a GAP:
 * the sparkline's line breaks there and the absence is stated in words.
 * Nothing here ever touches a figure's value — interpolating, averaging,
 * or summing across buckets is FORBIDDEN everywhere in this UI.
 */

export type HistoryBucketKind = "day" | "week" | "month" | "quarter";

/** Display order of the bucket toggle group. */
export const HISTORY_BUCKETS: HistoryBucketKind[] = [
  "day",
  "week",
  "month",
  "quarter",
];

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/**
 * The bucket key an ISO date falls in — the SAME labels the server assigns
 * (day: YYYY-MM-DD; week: ISO YYYY-Www; month: YYYY-MM; quarter: YYYY-Qn).
 * Returns null for a malformed date (never guesses).
 */
export function bucketKeyFor(
  isoDate: string,
  bucket: HistoryBucketKind,
): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  switch (bucket) {
    case "day":
      return `${m[1]}-${m[2]}-${m[3]}`;
    case "week": {
      // ISO 8601 week number via UTC date math (Thursday rule).
      const date = new Date(Date.UTC(y, mo - 1, d));
      const day = (date.getUTCDay() + 6) % 7; // Monday = 0
      date.setUTCDate(date.getUTCDate() - day + 3); // this week's Thursday
      const isoYear = date.getUTCFullYear();
      const jan4 = new Date(Date.UTC(isoYear, 0, 4));
      const jan4Day = (jan4.getUTCDay() + 6) % 7;
      const week1Monday = new Date(jan4);
      week1Monday.setUTCDate(jan4.getUTCDate() - jan4Day);
      const week =
        1 +
        Math.round(
          (date.getTime() - week1Monday.getTime()) / (7 * 86400000) - 0.5,
        );
      return `${isoYear}-W${pad(week)}`;
    }
    case "month":
      return `${m[1]}-${m[2]}`;
    case "quarter":
      return `${m[1]}-Q${Math.floor((mo - 1) / 3) + 1}`;
  }
}

/** Parse a bucket key back to the UTC date its bucket starts on. */
function bucketStart(key: string, bucket: HistoryBucketKind): Date | null {
  switch (bucket) {
    case "day": {
      const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
      return m
        ? new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])))
        : null;
    }
    case "week": {
      const m = /^(\d{4})-W(\d{2})$/.exec(key);
      if (!m) return null;
      // Monday of ISO week w: Jan 4 is always in week 1.
      const jan4 = new Date(Date.UTC(Number(m[1]), 0, 4));
      const jan4Day = (jan4.getUTCDay() + 6) % 7;
      const week1Monday = new Date(jan4);
      week1Monday.setUTCDate(jan4.getUTCDate() - jan4Day);
      week1Monday.setUTCDate(week1Monday.getUTCDate() + (Number(m[2]) - 1) * 7);
      return week1Monday;
    }
    case "month": {
      const m = /^(\d{4})-(\d{2})$/.exec(key);
      return m ? new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, 1)) : null;
    }
    case "quarter": {
      const m = /^(\d{4})-Q([1-4])$/.exec(key);
      return m
        ? new Date(Date.UTC(Number(m[1]), (Number(m[2]) - 1) * 3, 1))
        : null;
    }
  }
}

function nextKey(key: string, bucket: HistoryBucketKind): string | null {
  const start = bucketStart(key, bucket);
  if (!start) return null;
  switch (bucket) {
    case "day":
      start.setUTCDate(start.getUTCDate() + 1);
      break;
    case "week":
      start.setUTCDate(start.getUTCDate() + 7);
      break;
    case "month":
      start.setUTCMonth(start.getUTCMonth() + 1);
      break;
    case "quarter":
      start.setUTCMonth(start.getUTCMonth() + 3);
      break;
  }
  return bucketKeyFor(
    `${start.getUTCFullYear()}-${pad(start.getUTCMonth() + 1)}-${pad(start.getUTCDate())}`,
    bucket,
  );
}

/**
 * Every calendar bucket key from `first` to `last` inclusive, in order —
 * the sparkline's x axis. Keys the served data skipped are the GAPS.
 * Malformed keys (or a runaway range) return just the served endpoints,
 * honestly unenumerated. Bounded to 400 slots as a safety stop.
 */
export function enumerateBucketKeys(
  first: string,
  last: string,
  bucket: HistoryBucketKind,
): string[] {
  const firstStart = bucketStart(first, bucket);
  const lastStart = bucketStart(last, bucket);
  if (!firstStart || !lastStart || firstStart.getTime() > lastStart.getTime()) {
    return first === last ? [first] : [first, last];
  }
  const keys: string[] = [];
  let key: string | null = first;
  while (key !== null && keys.length < 400) {
    keys.push(key);
    if (key === last) return keys;
    key = nextKey(key, bucket);
  }
  return first === last ? [first] : [first, last];
}
