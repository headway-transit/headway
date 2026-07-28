/**
 * /admin/sources — data-source status, read-only v0 (handoff 0025, design
 * point 2): what raw.records has actually SEEN per (source, connector) —
 * latest data, windowed and all-time volumes, and what was REFUSED at
 * parse (quarantined loudly, never dropped) — plus the canonical
 * vehicle-position liveness the live map states.
 *
 * BINDING HONESTY RULE: there is NO add-source form here, because no
 * add-source API exists. Connecting a source happens on the server today
 * (.env feeds, the APC drop folder, machine keys); the server's
 * connecting_note renders VERBATIM and the teaching panel names the guide
 * (docs/connecting-your-data.md). In-app source configuration is the
 * recorded roadmap increment.
 *
 * Counts and timestamps render as served; ages are the server's own
 * age fields put into words (presentation, never a computed figure).
 */

import { useEffect, useState } from "react";
import { ApiError, getSourcesStatus } from "../api/client";
import type { SourcesStatusResponse } from "../api/types";
import { canViewSourceStatus, useSession } from "../auth/session";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { Skeleton } from "../components/Skeleton";
import { copy } from "../copy";

const t = copy.admin.sources;

/** Workflow tally display (thousands separators; never a figure). */
function formatCount(count: number): string {
  return count.toLocaleString("en-US");
}

/** Absolute timestamp label for a server-served ISO instant. */
function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
    hour12: false,
  });
}

/**
 * The server's age_seconds in words — presentation of a served field
 * (the same affordance the map's staleness chip uses), not arithmetic on
 * a figure.
 */
function ageInWords(ageSeconds: number): string {
  if (ageSeconds < 60) return "less than a minute ago";
  const minutes = Math.floor(ageSeconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} days ago`;
}

export function AdminSourcesView() {
  const session = useSession();
  const [status, setStatus] = useState<SourcesStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const allowed = canViewSourceStatus(session);

  useEffect(() => {
    if (!allowed) return;
    getSourcesStatus().then(setStatus, (err) =>
      setError(err instanceof ApiError ? err.message : String(err)),
    );
  }, [allowed]);

  if (!allowed) {
    return (
      <>
        <h1>{t.heading}</h1>
        <p>{copy.admin.notAllowed}</p>
      </>
    );
  }

  return (
    <>
      <Breadcrumbs
        trail={[
          { label: copy.admin.heading, to: "/admin" },
          { label: t.heading },
        ]}
      />
      <h1>{t.heading}</h1>
      <p>{t.intro}</p>

      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {!status && !error && (
        <Skeleton variant="table" count={4} label={copy.loading} />
      )}

      {status && (
        <>
          <p className="field-hint">{t.asOf(formatWhen(status.as_of))}</p>
          {/* Plain language when the table itself would mislead (nothing
              ever ingested) — the server's note, verbatim. */}
          {status.note && <p className="banner">{status.note}</p>}

          {status.sources.length > 0 && (
            <div className="table-wrap">
              <table className="admin-sources-table">
                <caption className="visually-hidden">
                  {t.table.caption}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">{t.table.source}</th>
                    <th scope="col">{t.table.connector}</th>
                    <th scope="col">{t.table.latest}</th>
                    <th scope="col">
                      {t.table.inWindow(status.window_hours)}
                    </th>
                    <th scope="col">
                      {t.table.refused(status.window_hours)}
                    </th>
                    <th scope="col">{t.table.total}</th>
                    <th scope="col">{t.table.refusedTotal}</th>
                  </tr>
                </thead>
                <tbody>
                  {status.sources.map((s) => (
                    <tr key={`${s.source}/${s.connector}`}>
                      <th scope="row">
                        {s.source} {s.simulated && <SimulatedBadge />}
                      </th>
                      <td>
                        {s.connector} {s.latest_connector_version}
                      </td>
                      <td>
                        {formatWhen(s.latest_landed_at)}{" "}
                        <span className="field-hint">
                          ({ageInWords(s.latest_age_seconds)})
                        </span>
                      </td>
                      <td>{formatCount(s.records_in_window)}</td>
                      <td>{formatCount(s.malformed_in_window)}</td>
                      <td>{formatCount(s.records_total)}</td>
                      <td>{formatCount(s.malformed_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {status.sources.length > 0 && (
            <p className="field-hint">{t.refusedHint}</p>
          )}

          <section className="card admin-section">
            <h2>{t.canonicalHeading}</h2>
            {/* The server's liveness statement, verbatim, with its own
                timestamp beside it. */}
            <p>{status.canonical.note}</p>
            {status.canonical.newest_vehicle_position_at && (
              <p>
                {formatWhen(status.canonical.newest_vehicle_position_at)}{" "}
                {status.canonical.age_seconds !== null && (
                  <span className="field-hint">
                    ({ageInWords(status.canonical.age_seconds)})
                  </span>
                )}
              </p>
            )}
          </section>

          <section className="card admin-section">
            <h2>{t.teaching.heading}</h2>
            {/* The server's connecting story, VERBATIM, then the teaching
                bullets. No add-source form — nothing here pretends. */}
            <p>{status.connecting_note}</p>
            <ul>
              {t.teaching.items.map((item) => (
                <li key={item.slice(0, 24)}>{item}</li>
              ))}
            </ul>
          </section>
        </>
      )}
    </>
  );
}
