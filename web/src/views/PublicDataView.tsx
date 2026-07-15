/**
 * /public — the human-readable rendering of GET /public/metrics/certified
 * (2026-07-11 click-through, finding 3). That endpoint is the ONE deliberate
 * unauthenticated exception (handoff 0006, design point 8): it serves only
 * figures a certifying official has already attested to, with no PII and no
 * certifier identity. This page requires no sign-in and renders each figure
 * as a receipt-lite card:
 *
 *   - the metric's plain name and the value VERBATIM (the API's string —
 *     never parsed, recalculated, or re-rounded client-side);
 *   - the period, and the certification date when the API serves one
 *     (it does not today — the field renders the moment it appears);
 *   - the SIMULATED DATA badge whenever the figure's detail flags it —
 *     transparency shows the flags, it never hides them;
 *   - the plain-language coverage line from the calculation detail, with
 *     its absence stated rather than left blank.
 *
 * The permanent disclaimer renders on every visit (empty state included),
 * and the machine-readable JSON stays one link away.
 */

import { useEffect, useId, useState } from "react";
import {
  ApiError,
  listPublicCertifiedValues,
  publicCertifiedValuesUrl,
} from "../api/client";
import type { PublicMetricValue } from "../api/types";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { copy } from "../copy";
import { coverageSummary, isSimulated } from "../detail";

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function unitLabel(code: string): string {
  return copy.unitLabels[code] ?? code;
}

export function PublicDataView() {
  const [values, setValues] = useState<PublicMetricValue[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPublicCertifiedValues()
      .then(setValues)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : String(err)),
      );
  }, []);

  return (
    <>
      <h1>{copy.publicData.heading}</h1>
      <p>{copy.publicData.intro}</p>
      {/* The permanent disclaimer: always rendered, never dismissible. */}
      <p className="banner">{copy.publicData.disclaimer}</p>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {!values && !error && <p>{copy.loading}</p>}
      {values && values.length === 0 && <p>{copy.publicData.empty}</p>}
      {values && values.length > 0 && (
        <ul className="public-list">
          {values.map((v) => (
            <li key={v.metric_value_id}>
              <PublicFigureCard value={v} />
            </li>
          ))}
        </ul>
      )}
      <p>
        <a href={publicCertifiedValuesUrl()}>
          {copy.publicData.machineReadable}
        </a>
      </p>
    </>
  );
}

/** One certified figure as a receipt-lite card. Numbers stay sacred. */
function PublicFigureCard({ value }: { value: PublicMetricValue }) {
  const headingId = useId();
  const period = `${value.period_start} to ${value.period_end}`;
  const metric = metricLabel(value.metric);
  const detail = value.detail ?? {};
  const simulated = isSimulated(detail);
  const coverage = coverageSummary(detail);

  return (
    <article className="public-card" aria-labelledby={headingId}>
      <h2 id={headingId}>{metric}</h2>
      {/* The figure verbatim: the API's string, exactly as certified. */}
      <p className="public-value">
        {value.value} {unitLabel(value.unit)}{" "}
        <span className="tag certified">{copy.publicData.statusCertified}</span>
      </p>
      <dl>
        <dt>{copy.publicData.periodLabel}</dt>
        <dd>{period}</dd>
        {(value.certification?.certified_at ?? value.certified_at) && (
          <>
            <dt>{copy.publicData.certifiedOnLabel}</dt>
            <dd>{value.certification?.certified_at ?? value.certified_at}</dd>
          </>
        )}
        {/* The signature fingerprint (handoff 0019, design 7): the public
            feed serves the key fingerprint — never the certifier's
            identity. A legacy (pre-signature) certification says so
            honestly instead of showing a blank. */}
        {value.certification && (
          <>
            <dt>{copy.publicData.fingerprintLabel}</dt>
            <dd>
              {value.certification.key_fingerprint ? (
                <code className="certificate-fingerprint">
                  {value.certification.key_fingerprint}
                </code>
              ) : (
                copy.publicData.fingerprintLegacy
              )}
            </dd>
          </>
        )}
      </dl>
      {simulated && (
        <p>
          <SimulatedBadge /> {copy.simulated.tooltip}
        </p>
      )}
      <p>{coverage ?? copy.receipt.coverageNotReported}</p>
      <p className="public-calc">
        {copy.publicData.calcLine(value.calc_name, value.calc_version)}
      </p>
    </article>
  );
}
