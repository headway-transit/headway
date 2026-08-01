/**
 * The "needs investigation" list (handoff 0043, design points 6 and 7).
 *
 * THE CANVAS IS NOT ACCESSIBLE, SO THIS LIST IS THE ENTRY POINT
 * -------------------------------------------------------------
 * A WebGL canvas has no readable structure: a flag drawn on it is invisible
 * to a screen reader and unreachable by Tab. So every flagged finding is
 * ALSO a real `<button>` here, in severity-then-age order, and opening one
 * from the keyboard does exactly what clicking its flag does — it opens the
 * relationship inspector and lights the finding's routes on the map. This
 * is the accessible equivalent the rest of /map already follows for vehicle
 * dots (the vehicle list), applied to findings.
 *
 * NOTHING IS HIDDEN BEHIND THE MAP'S LIMITS
 * -----------------------------------------
 * Findings that could not be drawn — because they name no route, name a
 * route this installation has no line for, are about a run rather than
 * about trips, or fell past the flag cap — are all still HERE, each with
 * the reason it has no flag. The map's drawing limits are never allowed to
 * quietly shrink the worklist.
 */

import { copy } from "../copy";
import { SeverityIcon } from "../components/SeverityIcon";
import { FLAG_CAP, type FindingPlacement, type PlacementGap } from "./findings";

const GAP_COPY: Record<PlacementGap, string> = {
  "no-subject": copy.map.findings.gapNoSubject,
  "no-route": copy.map.findings.gapNoRoute,
  "route-not-drawn": copy.map.findings.gapRouteNotDrawn,
  "over-cap": copy.map.findings.gapOverCap,
};

export interface NeedsInvestigationProps {
  placement: FindingPlacement;
  loading: boolean;
  error: string | null;
  selectedIssueId: string | null;
  onSelect: (issueId: string) => void;
}

export function NeedsInvestigation({
  placement,
  loading,
  error,
  selectedIssueId,
  onSelect,
}: NeedsInvestigationProps) {
  const t = copy.map.findings;
  const total = placement.placed.length + placement.skipped.length;

  return (
    <section aria-label={t.listHeading} className="map-flags">
      <h2>{t.listHeading}</h2>
      <p className="chart-desc">{t.listIntro}</p>
      {error && (
        <div role="alert" className="alert">
          {t.error(error)}
        </div>
      )}
      {loading && !error && <p className="chart-desc">{t.listLoading}</p>}
      {!loading && !error && total === 0 && (
        <p className="chart-desc">{t.listEmpty}</p>
      )}
      {total > 0 && (
        <>
          <p className="map-count">
            {t.countLine(String(total), String(placement.placed.length))}
          </p>
          <ol>
            {placement.placed.map((flag) => (
              <li key={flag.issue_id}>
                <button
                  type="button"
                  className="map-flag"
                  aria-pressed={selectedIssueId === flag.issue_id}
                  onClick={() => onSelect(flag.issue_id)}
                >
                  <span className="map-flag-title">
                    <span className={`severity ${flag.severity}`}>
                      <SeverityIcon severity={flag.severity} />
                      {flag.severity}
                    </span>{" "}
                    {flag.title}
                  </span>
                  <span className="map-flag-meta">
                    {t.onMap(flag.label)}
                    {flag.other_route_count > 0 &&
                      t.onMapAlso(String(flag.other_route_count))}
                  </span>
                </button>
              </li>
            ))}
            {placement.skipped.map(({ issue, gap }) => (
              <li key={issue.issue_id}>
                <button
                  type="button"
                  className="map-flag"
                  aria-pressed={selectedIssueId === issue.issue_id}
                  onClick={() => onSelect(issue.issue_id)}
                >
                  <span className="map-flag-title">
                    <span className={`severity ${issue.severity}`}>
                      <SeverityIcon severity={issue.severity} />
                      {issue.severity}
                    </span>{" "}
                    {issue.title}
                  </span>
                  <span className="map-flag-gap">{GAP_COPY[gap]}</span>
                </button>
              </li>
            ))}
          </ol>
          <p className="chart-desc">{t.capNote(String(FLAG_CAP))}</p>
        </>
      )}
    </section>
  );
}

export default NeedsInvestigation;
