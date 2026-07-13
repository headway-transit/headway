/**
 * The Receipt (handoff 0007, pillar 1): every displayed figure opens into a
 * receipt with five parts, in this order —
 *
 *   (a) a plain-language story line for the figure;
 *   (b) an accessible coverage meter (text + visual) with the exclusions
 *       stated, plus the rest of the calculation detail in plain language
 *       (this absorbs the former MetricDetail panel);
 *   (c) the FTA rule inside the number: the VERBATIM manual quotes + page
 *       citations for the calc that produced it (src/regulatory/quotes.json,
 *       extracted from services/calc/REGULATORY_TRACKER.md — never
 *       paraphrased, never generated);
 *   (d) flags (simulated / pre-verification / anomaly), each with its
 *       meaning — text + icon + color, never color alone;
 *   (e) the door onward: walk this number to its raw records.
 *
 * NUMBERS STAY SACRED. Every figure, ratio, and count shown is the API's
 * string verbatim; percentages come from the string-only decimal shift in
 * src/format.ts. The ONE numeric conversion in this file is the meter's
 * aria-valuenow (ARIA requires a number): it is derived by taking the integer
 * part of the ALREADY-SHIFTED percent STRING (never parseFloat on the ratio),
 * is used only for the meter's position, and is never displayed — the
 * displayed and announced value is the verbatim percent string.
 */

import { Link } from "react-router-dom";
import { useMeter } from "react-aria";
import type { MetricValue } from "../api/types";
import { copy } from "../copy";
import {
  coverageSummary,
  detailLines,
  isPreVerification,
  isSimulated,
} from "../detail";
import type { Detail } from "../detail";
import { detailValueToString, ratioToPercentString } from "../format";
import { drCallouts, parseDrScope } from "../regulatory/drRules";
import { quoteContaining, quotesForCalc } from "../regulatory/quotes";
import { DrScopeBadge } from "./DrScopeBadge";
import { QuoteFigure } from "./QuoteFigure";
import { SimulatedBadge } from "./SimulatedBadge";

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function unitLabel(code: string): string {
  return copy.unitLabels[code] ?? code;
}

function periodLabel(value: MetricValue): string {
  return `${value.period_start} to ${value.period_end}`;
}

/**
 * The meter's aria-valuenow, derived from the string-shifted percent by
 * STRING operations only: take the digits before the decimal point and
 * convert that integer (0–100, exactly representable — no float can alter
 * it). Returns null for anything that is not a plain 0–100 integer string,
 * in which case no meter is rendered (the text states coverage instead —
 * shown raw, never guessed at).
 */
function meterValueFromPercentString(percent: string): number | null {
  const intPart = percent.split(".")[0];
  if (!/^\d{1,3}$/.test(intPart)) return null;
  const value = Number(intPart); // integer ≤ 999: exact, display-only, never shown
  return value <= 100 ? value : null;
}

export interface CoverageMeterProps {
  /** The string-shifted percent, displayed and announced verbatim. */
  percent: string;
  /** Integer 0–100 derived from the percent STRING — position/aria-valuenow only. */
  meterValue: number;
  label: string;
}

/**
 * The accessible coverage meter, built on React Aria's useMeter. The role is
 * pinned to the single token "meter" (the ARIA meter pattern): useMeter's
 * default fallback list ("meter progressbar") defeats the axe gate's role
 * resolution, and this suite treats axe as binding. aria-valuetext (from
 * valueLabel) announces the VERBATIM percent string; aria-valuenow is the
 * display-only integer.
 */
function CoverageMeter({ percent, meterValue, label }: CoverageMeterProps) {
  const { meterProps } = useMeter({
    value: meterValue,
    minValue: 0,
    maxValue: 100,
    valueLabel: `${percent}%`,
    "aria-label": label,
  });
  return (
    <div {...meterProps} role="meter" className="coverage-meter">
      <span className="coverage-meter-value">{percent}%</span>
      <span className="meter-track">
        <span className="meter-fill" style={{ width: `${meterValue}%` }} />
      </span>
    </div>
  );
}

export interface ReceiptProps {
  value: MetricValue;
}

export function Receipt({ value }: ReceiptProps) {
  const detail: Detail = value.detail ?? {};
  const metric = metricLabel(value.metric);
  const period = periodLabel(value);

  // (b) coverage: the ratio string, shifted to a percent string, string-only.
  const coverageRatio =
    "coverage" in detail ? detailValueToString(detail.coverage) : null;
  const percentString =
    coverageRatio !== null ? ratioToPercentString(coverageRatio) : null;
  const meterValue =
    percentString !== null ? meterValueFromPercentString(percentString) : null;

  // The exclusions sentence ("covers X% — N excluded and documented" for
  // vrm/vrh, the counted-trips sentence for UPT); its absence is stated,
  // never blank.
  const exclusions = coverageSummary(detail);

  // The rest of the calculation detail (absorbed MetricDetail), minus the
  // coverage sentence already shown beside the meter.
  const lines = detailLines(detail).filter((line) => line !== exclusions);

  // (c) the verified FTA quotes for this calc. null is a LOUD condition.
  const quotes = quotesForCalc(value.calc_name);

  // The DR affordance (handoff 0013, design point 5): a mode/TOS badge on
  // every `mode:DR`/`mode:DR:tos:*` figure, plus a callout quoting each
  // verified rule the TOS makes govern THIS figure's semantics. A callout
  // whose quote is not on file is a LOUD absence, never silence.
  const drScope = parseDrScope(value.scope);
  const callouts = drScope ? drCallouts(value.metric, drScope.tos) : [];

  // (d) flags. "anomaly" is forward-compatible: any detail key naming an
  // anomaly raises the flag (no current calc emits one; when one does, it is
  // shown, never hidden — and its raw detail line already renders above).
  const simulated = isSimulated(detail);
  const preVerification = isPreVerification(value);
  const anomaly = Object.keys(detail).some((key) =>
    key.toLowerCase().includes("anomaly"),
  );
  const hasFlags = simulated || preVerification || anomaly;

  return (
    <section className="receipt" aria-label={copy.receipt.label(metric, period)}>
      {/* (a) the plain-language story: the figure verbatim, in context.
          A DR-scoped figure carries its mode/TOS badge right beside it. */}
      <p className="receipt-story">
        {copy.receipt.story(value.value, unitLabel(value.unit), metric, period)}
        {drScope && (
          <>
            {" "}
            <DrScopeBadge scope={value.scope} />
          </>
        )}
      </p>

      {/* (b) coverage meter + exclusions + the rest of the detail. */}
      <div className="receipt-coverage">
        <h2>{copy.receipt.coverageHeading}</h2>
        {percentString !== null && meterValue !== null && (
          <CoverageMeter
            percent={percentString}
            meterValue={meterValue}
            label={copy.receipt.coverageMeterLabel(metric, period)}
          />
        )}
        <p className="receipt-exclusions">
          {exclusions ?? copy.receipt.coverageNotReported}
        </p>
        {lines.length > 0 ? (
          <ul
            className="detail-panel"
            aria-label={copy.metrics.detailListLabel(metric, period)}
          >
            {lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : (
          exclusions === null && (
            <p className="detail-panel">{copy.metrics.detailEmpty}</p>
          )
        )}
      </div>

      {/* (c) the FTA rule inside the number: verbatim quotes + citations.
          DR rule callouts come first — the rules the TOS makes govern this
          figure, each led in with plain language and quoted verbatim. */}
      <div className="receipt-rule">
        <h2>{copy.receipt.ruleHeading}</h2>
        {callouts.map((callout) => {
          const quote = quoteContaining(value.calc_name, callout.snippet);
          return (
            <div className="dr-callout" key={callout.key}>
              <p>{copy.dr.calloutIntro[callout.key]}</p>
              {/* FAIL LOUDLY: a callout whose rule is missing states it. */}
              <QuoteFigure
                quote={quote}
                missingMessage={copy.receipt.ruleMissing(value.calc_name)}
              />
            </div>
          );
        })}
        {quotes ? (
          <>
            <p>{copy.receipt.ruleIntro(value.calc_name)}</p>
            {quotes.map((q) => (
              <QuoteFigure
                quote={q}
                missingMessage={copy.receipt.ruleMissing(value.calc_name)}
                key={`${q.citation}:${q.quote}`}
              />
            ))}
          </>
        ) : (
          // FAIL LOUDLY: a calc with no verified quote is stated, not blank.
          <p className="alert">{copy.receipt.ruleMissing(value.calc_name)}</p>
        )}
      </div>

      {/* (d) flags, each with its meaning. No flags is stated explicitly. */}
      <div className="receipt-flags">
        <h2>{copy.receipt.flagsHeading}</h2>
        {hasFlags ? (
          <ul className="flag-list">
            {simulated && (
              <li>
                <SimulatedBadge /> {copy.simulated.tooltip}
              </li>
            )}
            {preVerification && (
              <li>
                <span className="tag pre-verification">
                  {copy.metrics.preVerificationTag}
                </span>{" "}
                {copy.receipt.preVerificationNote}
              </li>
            )}
            {anomaly && (
              <li>
                <span className="tag pre-verification">
                  {copy.receipt.anomalyFlag}
                </span>{" "}
                {copy.receipt.anomalyNote}
              </li>
            )}
          </ul>
        ) : (
          <p>{copy.receipt.noFlags}</p>
        )}
      </div>

      {/* (e) the door onward: every number walks to its raw records. */}
      <p className="receipt-walk">
        <Link to={`/metrics/${value.metric_value_id}/lineage`}>
          {copy.receipt.walkLink}
          <span className="visually-hidden">{` — ${metric}, ${period}`}</span>
        </Link>
      </p>
    </section>
  );
}
