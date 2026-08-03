/**
 * The mode legend (handoff 0043, design point 4).
 *
 * The legend draws the SAME glyph the canvas draws, in the SAME colour it
 * is drawn in on the ground currently under the marks — both come from
 * `marks.ts`, so a re-tuned palette moves the legend with it and the two
 * cannot drift apart. It is also the place where the two honesty lines
 * live: what a "mode" is on this map (the route's mode, joined from the
 * agency's own schedule data — the position feed does not report one), and
 * that shape, not colour, is the primary channel.
 *
 * Data-driven: only modes this agency's own routes actually carry appear.
 * Nothing here knows the name of a single mode ahead of time.
 */

import { copy } from "../copy";
import {
  FAMILY_GLYPH,
  markColor,
  markFamily,
  type MarkGround,
} from "./marks";

export interface ModeLegendProps {
  ground: MarkGround;
  /** Modes actually present, plus 'unknown' when any vehicle has no mode. */
  modes: string[];
  /** Vehicles with no mode, by reason — counted, never quietly grey. */
  unresolved: { "no-route-id": number; "route-not-held": number };
}

export function ModeLegend({ ground, modes, unresolved }: ModeLegendProps) {
  const t = copy.map.marks;
  if (modes.length === 0) return null;
  return (
    <section aria-label={t.legendHeading} className="map-mode-legend">
      <h3>{t.legendHeading}</h3>
      <ul>
        {modes.map((mode) => {
          const label = t.modeLabels[mode] ?? mode;
          return (
            <li key={mode}>
              <span
                aria-hidden="true"
                className="map-mode-glyph"
                style={{ color: markColor(mode, ground) }}
              >
                {FAMILY_GLYPH[markFamily(mode)]}
              </span>
              {label}
            </li>
          );
        })}
      </ul>
      <p className="chart-desc">{t.legendNote}</p>
      <p className="chart-desc">{t.legendChannels}</p>
      {unresolved["no-route-id"] > 0 && (
        <p className="chart-desc">
          {t.unknownNoRoute(unresolved["no-route-id"].toLocaleString("en-US"))}
        </p>
      )}
      {unresolved["route-not-held"] > 0 && (
        <p className="chart-desc">
          {t.unknownRouteMissing(
            unresolved["route-not-held"].toLocaleString("en-US"),
          )}
        </p>
      )}
    </section>
  );
}

export default ModeLegend;
