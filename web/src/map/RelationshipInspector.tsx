/**
 * The relationship inspector (handoff 0043, design point 7).
 *
 * A react-aria dialog panel over the canvas that renders one finding and
 * the chain the API can honestly draw from it:
 *
 *     finding → block → route → calculation → data-quality owner
 *
 * WHAT MAKES IT A REACT-ARIA PANEL AND NOT A MODAL
 * ------------------------------------------------
 * `useDialog` supplies the dialog semantics and the label wiring; a
 * `FocusScope` with `restoreFocus` sends focus back to whatever opened the
 * panel — the flag on the map or the row in the "needs investigation"
 * list. It deliberately does NOT `contain` focus: this panel sits beside a
 * live map and a worklist, and trapping a keyboard user inside a read-only
 * readout would be a keyboard trap with no purpose. Escape closes it.
 *
 * WHERE THE CONTENT COMES FROM
 * ----------------------------
 * All of it from the API. The block/route half is the finding's OWN
 * `subject_context` — the agency-vocabulary record of what the finding was
 * about, frozen when it was raised — and the calculation half is the calc
 * runs whose outcome rows name this exact issue id. The panel infers no
 * link and computes no figure; where the subject context capped its own
 * lists, it says so and shows the true count beside the sample.
 */

import { useRef, type ReactNode } from "react";
import { FocusScope, useDialog } from "react-aria";
import { Link } from "react-router-dom";
import { SeverityIcon } from "../components/SeverityIcon";
import { copy } from "../copy";
import type { FindingChain } from "./findings";

export interface RelationshipInspectorProps {
  chain: FindingChain;
  /** Source-record ids from GET /dq/issues/{id}; null while loading. */
  sourceRecordIds: string[] | null;
  sourceRecordsLoading: boolean;
  /** True when the panel was opened by clicking the map, not the list. */
  fromMap: boolean;
  onClose: () => void;
}

function modeLabel(mode: string | null): string {
  if (!mode) return copy.map.inspector.routeModeUnknown;
  return copy.map.marks.modeLabels[mode] ?? mode;
}

function routeName(short: string | null, long: string | null, id: string) {
  return short || long || id;
}

export function RelationshipInspector({
  chain,
  sourceRecordIds,
  sourceRecordsLoading,
  fromMap,
  onClose,
}: RelationshipInspectorProps) {
  const t = copy.map.inspector;
  const ref = useRef<HTMLDivElement>(null);
  // `useDialog` names the panel from its own heading via titleProps —
  // no hand-written aria-labelledby, and no chance of the two drifting.
  const { dialogProps, titleProps } = useDialog({}, ref);
  const issue = chain.issue;

  return (
    <FocusScope autoFocus restoreFocus>
      <div
        {...dialogProps}
        ref={ref}
        className="map-inspector"
        data-testid="map-inspector"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            onClose();
          }
        }}
      >
        <div className="map-inspector-head">
          <h2 {...titleProps}>{t.heading(issue.title)}</h2>
          <button
            type="button"
            className="map-inspector-close"
            aria-label={t.close}
            onClick={onClose}
          >
            {t.closeShort}
          </button>
        </div>

        {fromMap && <p className="chart-desc">{t.openedFromMap}</p>}

        {/* The finding itself, verbatim from the queue's own record. */}
        <p className={`severity ${issue.severity}`}>
          <SeverityIcon severity={issue.severity} />
          {t.severityLabel}: {issue.severity}
        </p>
        <p>{issue.description}</p>
        <dl className="map-inspector-facts">
          <dt>{t.statusLabel}</dt>
          <dd>{issue.status}</dd>
          <dt>{t.raisedLabel}</dt>
          <dd>{issue.created_at}</dd>
          <dt>{t.idLabel}</dt>
          <dd>{issue.issue_id}</dd>
        </dl>

        <h3>{t.chainHeading}</h3>
        <p className="chart-desc">{t.chainIntro}</p>

        {/* The chain as a CHAIN. Every link below was already rendered; the
            list draws the spine that says they are consecutive. */}
        <ol className="chain-trail">
        {/* --- block --- */}
        {chain.blocks.length > 0 && (
          <ChainStep marker="B" heading={t.blocksHeading}>
            <ul>
              {chain.blocks.map((block, index) => (
                <li key={`${block.block_id ?? "none"}-${index}`}>
                  <span className="mono">
                    {t.blockLine(
                      block.block_label ?? block.block_id ?? t.blockUnnamed,
                      String(block.trip_count),
                    )}
                  </span>
                  {block.first_departure && block.last_departure && (
                    <>
                      {" "}
                      <span className="map-flag-meta">
                        {t.blockWindow(
                          block.first_departure,
                          block.last_departure,
                        )}
                      </span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </ChainStep>
        )}
        {chain.unmatchedTripCount > 0 && (
          <p className="chart-desc">
            {t.unmatchedTrips(String(chain.unmatchedTripCount))}
          </p>
        )}
        {chain.subjectCapped && (
          <p className="chart-desc">{t.subjectCapped}</p>
        )}

        {/* --- route --- */}
        {chain.routes.length > 0 && (
          <ChainStep marker="R" heading={t.routesHeading}>
            <ul>
              {chain.routes.map((route) => (
                <li key={route.route_id}>
                  {t.routeLine(
                    routeName(
                      route.short_name,
                      route.long_name,
                      route.route_id,
                    ),
                    modeLabel(route.mode),
                  )}
                  {!route.drawn && (
                    <>
                      {" "}
                      <span className="map-flag-meta">
                        ({t.routeNotDrawn})
                      </span>
                    </>
                  )}
                </li>
              ))}
            </ul>
            <p className="chart-desc">{t.relatedNote}</p>
          </ChainStep>
        )}

        {/* --- calculation --- */}
        <ChainStep marker="C" heading={t.calcsHeading}>
        {chain.calcs.length === 0 ? (
          <p className="chart-desc">{t.calcsEmpty}</p>
        ) : (
          <ul>
            {chain.calcs.map((calc, index) => (
              <li key={`${calc.run_id}-${calc.metric}-${index}`}>
                <span className="mono">
                  {t.calcLine(
                    calc.calc_name ?? "—",
                    calc.calc_version ?? "—",
                    calc.metric ?? "—",
                  )}
                </span>
                <br />
                <span className="map-flag-meta">
                  {calc.outcome === "refused"
                    ? t.calcOutcomeRefused
                    : t.calcOutcomePersisted}{" "}
                  {t.calcPeriod(calc.period_start, calc.period_end)}
                </span>
              </li>
            ))}
          </ul>
        )}
        </ChainStep>

        {/* --- owner --- */}
        <ChainStep marker="D" heading={t.ownerHeading}>
          <p>{chain.owner ? t.ownerNamed(chain.owner) : t.ownerNone}</p>
        </ChainStep>

        {/* --- provenance: the raw records the finding cited --- */}
        <ChainStep marker="S" heading={t.recordsHeading}>
        {sourceRecordsLoading && (
          <p className="chart-desc">{t.recordsLoading}</p>
        )}
        {!sourceRecordsLoading &&
          (sourceRecordIds && sourceRecordIds.length > 0 ? (
            <ul>
              {sourceRecordIds.map((id) => (
                <li key={id}>
                  <span className="mono">{id}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="chart-desc">{t.recordsNone}</p>
          ))}
        </ChainStep>
        </ol>

        <p>
          <Link to="/dq">{t.queueLink}</Link>
        </p>
      </div>
    </FocusScope>
  );
}

/**
 * One rung on the relationship trail.
 *
 * The chain from a flag to the number it moved was already all here — finding,
 * block, route, calculation, owner, raw records — as a run of headings and
 * lists. Reading it required knowing that consecutive headings meant
 * consecutive LINKS. Nothing on screen said so.
 *
 * The rung draws that: a lettered marker on a continuous spine, so the eye
 * follows the chain the way the data does. The heading stays a real <h3> and
 * the content is untouched — this is a frame around what was already true,
 * never a second rendering of it.
 */
function ChainStep({
  marker,
  heading,
  children,
}: {
  /** One letter. The trail is read, not decoded — it labels, never encodes. */
  marker: string;
  heading: string;
  children: ReactNode;
}) {
  return (
    <li className="chain-step">
      <span className="chain-step-marker" aria-hidden="true">
        {marker}
      </span>
      <div className="chain-step-body">
        <h3>{heading}</h3>
        {children}
      </div>
    </li>
  );
}

export default RelationshipInspector;
