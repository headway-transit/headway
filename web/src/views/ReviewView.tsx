/**
 * The review surface (/review — handoff 0047, design points 1, 2, 4 and 6).
 *
 * Wave F shipped the `auditor` role and no place to be one: a reader signed
 * in and landed in the operations control room, a queue of things to do,
 * built for people who act. This is the room for the other question — "what
 * was filed, and does it hold up?".
 *
 * It is a WORKLIST OF CERTIFICATIONS, because the certification is the
 * object being audited: the moment a named person put their name to a set of
 * figures. It is deliberately not a second dashboard. There is no queue, no
 * count that wants clearing, and nothing on it asks to be acted on.
 *
 * WHAT IS AND IS NOT COMPUTED HERE
 * --------------------------------
 * Nothing. Each row's period comes from the signed document the server
 * parsed, and each row's verdict is the server's own live verification
 * (GET /certifications/{id}, which re-reads the stored bytes and re-checks
 * the signature on every read). This page reads them and renders them
 * verbatim — a verdict worked out in a browser would be worth nothing to the
 * person reading it. A certificate that cannot be read says so, in the
 * server's words, and is never shown as a pass.
 *
 * Rows lead into the existing certificate view rather than restating it:
 * that page already carries the signature block, the covered figures and
 * the walk to each figure's provenance.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getCertification, listCertifications } from "../api/client";
import type {
  CertificationCertificate,
  CertificationRecord,
} from "../api/types";
import { Skeleton } from "../components/Skeleton";
import { copy } from "../copy";

const r = copy.review;

/** The certificate behind one row: still arriving, read, or unreadable. */
type RowDetail =
  | { kind: "checking" }
  | { kind: "ready"; certificate: CertificationCertificate }
  | { kind: "error"; message: string };

/** Workflow tallies for display: thousands-separated, never a figure. */
function formatCount(count: number): string {
  return count.toLocaleString("en-US");
}

/**
 * The distinct periods the signed document's figures cover, in the order the
 * document lists them. Deliberately NOT a min/max range: inventing "March 1
 * to May 31" over three separate months would state a period nobody signed.
 *
 * `null` = there is no signed document to read a period from (a record from
 * before signatures existed). An EMPTY array is a different thing — a signed
 * document that lists no figures at all — and the two are never merged: one
 * is honest history, the other is an anomaly worth seeing.
 */
function periodsOf(certificate: CertificationCertificate): string[] | null {
  if (!certificate.document) return null;
  const seen: string[] = [];
  for (const figure of certificate.document.figures) {
    const period = `${figure.period_start} to ${figure.period_end}`;
    if (!seen.includes(period)) seen.push(period);
  }
  return seen;
}

export function ReviewView() {
  const [records, setRecords] = useState<CertificationRecord[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, RowDetail>>({});

  useEffect(() => {
    let cancelled = false;
    listCertifications()
      .then((rows) => {
        if (cancelled) return;
        setRecords(rows);
        // Every row starts as "checking" so a reader is never shown a blank
        // where a verdict is going to appear.
        setDetails(
          Object.fromEntries(
            rows.map((row) => [
              row.certification_id,
              { kind: "checking" } as RowDetail,
            ]),
          ),
        );
        // One read per certification, because the LIST endpoint carries
        // neither the period nor the verdict — both live in the certificate
        // (GET /certifications/{id}). That is a read per row, and it is the
        // honest cost of showing a server-computed verdict rather than
        // guessing one: a certification is a rare object (one per signing
        // act), so the list is tens of rows, not thousands. If it ever grows
        // past that, the fix is a list endpoint that carries the verdict —
        // never a verdict worked out in the browser.
        for (const row of rows) {
          const id = row.certification_id;
          getCertification(id)
            .then((certificate) => {
              if (cancelled) return;
              setDetails((prev) => ({
                ...prev,
                [id]: { kind: "ready", certificate },
              }));
            })
            .catch((err) => {
              if (cancelled) return;
              setDetails((prev) => ({
                ...prev,
                [id]: {
                  kind: "error",
                  message:
                    err instanceof ApiError ? err.message : String(err),
                },
              }));
            });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <h1>{r.heading}</h1>
      <p>{r.intro}</p>

      {/* Design point 4: said once, on entry, in plain words — and framed as
          what it is (a protection that runs both ways), never as a warning. */}
      <section className="card review-panel" aria-labelledby="review-record">
        <h2 id="review-record">{r.recordHeading}</h2>
        <p>{r.recordBody}</p>
        <p>{r.recordWhy}</p>
        <p>{r.recordNoWrites}</p>
        {/* The exception to the line above, stated in the same breath as the
            rule. A reviewer who finds out later that the rule had a carve-out
            stops trusting the rule — and this one is the role's whole point
            (handoff 0047, the verify decision). */}
        <p>{r.recordVerify}</p>
      </section>

      {loadError && (
        <div role="alert" className="alert">
          <p>{r.loadErrorLead}</p>
          <p>{loadError}</p>
        </div>
      )}
      {!records && !loadError && (
        <Skeleton variant="table" count={4} label={r.loading} />
      )}
      {records && records.length === 0 && <p>{r.empty}</p>}

      {records && records.length > 0 && (
        <>
          {/* role/tabIndex: a horizontally scrollable region must be
              keyboard-reachable and named (axe: scrollable-region-focusable). */}
          <div
            className="table-wrap"
            role="region"
            aria-label={r.tableLabel}
            tabIndex={0}
          >
            <table>
              <caption>{r.tableCaption}</caption>
              <thead>
                <tr>
                  <th scope="col">{r.columns.certification}</th>
                  <th scope="col">{r.columns.period}</th>
                  <th scope="col">{r.columns.signer}</th>
                  <th scope="col">{r.columns.signedAt}</th>
                  {/* A bare count: the column stacks on the ones place. */}
                  <th scope="col" className="numeric">
                    {r.columns.figures}
                  </th>
                  <th scope="col">{r.columns.verification}</th>
                </tr>
              </thead>
              <tbody>
                {records.map((record) => (
                  <ReviewRow
                    key={record.certification_id}
                    record={record}
                    detail={
                      details[record.certification_id] ?? { kind: "checking" }
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
          <p className="field-hint">{r.verdictNote}</p>
        </>
      )}

      {/* Design point 6: what this role cannot see, stated on the surface
          rather than met as a 403 at the end of a guessed URL. */}
      <section className="card review-panel" aria-labelledby="review-scope">
        <h2 id="review-scope">{r.scopeHeading}</h2>
        <p>{r.scopeIntro}</p>
        <ul>
          {r.scopeItems.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p>{r.scopeAsk}</p>
        <h3>{r.scopeWithheldHeading}</h3>
        <p>{r.scopeWithheld}</p>
      </section>

      <section className="card review-panel" aria-labelledby="review-more">
        <h2 id="review-more">{r.moreHeading}</h2>
        <ul>
          <li>
            {/* Linked for every reader (handoff 0047): GET /calc/runs is open
                to any signed-in account, and which calculation version
                produced a figure is evidence. */}
            <Link to="/calc-runs">{r.moreCalcRunsLink}</Link> — {r.moreCalcRuns}
          </li>
          <li>
            <Link to="/metrics">{r.moreMetricsLink}</Link> — {r.moreMetrics}
          </li>
          <li>
            <Link to="/dq">{r.moreDqLink}</Link> — {r.moreDq}
          </li>
        </ul>
      </section>
    </>
  );
}

/** One certification, exactly as the record and its certificate state it. */
function ReviewRow({
  record,
  detail,
}: {
  record: CertificationRecord;
  detail: RowDetail;
}) {
  const periods = detail.kind === "ready" ? periodsOf(detail.certificate) : null;
  return (
    <tr>
      <th scope="row">
        <Link to={`/certifications/${record.certification_id}`}>
          {r.rowLink(record.certification_id)}
        </Link>
      </th>
      <td>
        {detail.kind === "checking" && (
          <span className="field-hint">{r.detailChecking}</span>
        )}
        {/* Worded apart from the verdict cell beside it on purpose: "the
            period could not be read" and "the signature could not be
            checked" are two different admissions. */}
        {detail.kind === "error" && (
          <span className="field-hint">{r.periodUnavailable}</span>
        )}
        {detail.kind === "ready" &&
          (periods === null ? (
            r.periodUnknown
          ) : periods.length === 0 ? (
            // A signed document that covers no figures is not history, it
            // is an anomaly — said in its own words, never softened into
            // the legacy line above.
            <strong>{r.periodNoFigures}</strong>
          ) : periods.length === 1 ? (
            periods[0]
          ) : (
            <ul className="review-periods">
              {periods.map((period) => (
                <li key={period}>{period}</li>
              ))}
            </ul>
          ))}
      </td>
      <td>
        {/* A record signed before typed names existed states the absence
            rather than rendering a blank cell. */}
        {record.signer_full_name && record.signer_title
          ? r.signerLine(record.signer_full_name, record.signer_title)
          : r.signerAccountOnly(record.certified_by)}
      </td>
      <td>{record.certified_at}</td>
      {/* A workflow count of covered figures — never a regulatory figure. */}
      <td className="figure numeric">
        {formatCount(record.metric_value_ids.length)}
      </td>
      <td>
        <RowVerdict detail={detail} />
      </td>
    </tr>
  );
}

/**
 * The server's verdict for one row, in the server's own words.
 *
 * A tag carries the state in TEXT (never colour alone), and the server's
 * message rides underneath it verbatim. The two failure shapes are kept
 * apart on purpose: "the signature did not verify" and "Headway could not
 * check the signature" are different findings, and collapsing them would put
 * a false one in a reviewer's notes.
 *
 * No `role="alert"` here: these arrive as the page loads rather than as the
 * result of an action, and a table that fires one alert per row announces
 * nothing usefully. The words carry the weight instead.
 */
function RowVerdict({ detail }: { detail: RowDetail }) {
  if (detail.kind === "checking") {
    return <span className="field-hint">{r.detailChecking}</span>;
  }
  if (detail.kind === "error") {
    return (
      <>
        <span className="tag verdict-inconclusive">{r.verdictUnavailable}</span>
        <p className="review-verdict-message">{detail.message}</p>
      </>
    );
  }
  const result = detail.certificate.verification;
  const label = r.verdictLabels[result.verdict] ?? r.verdictUnknown;
  // A verdict this build does not recognise is drawn LOUD, like a failure —
  // the same rule the certificate view follows.
  const tone =
    result.verdict === "verified"
      ? "verdict-verified"
      : result.verdict === "unsigned_legacy"
        ? "verdict-unsigned"
        : result.verdict === "key_mismatch"
          ? "verdict-inconclusive"
          : "verdict-failed";
  return (
    <>
      <span className={`tag ${tone}`}>{label}</span>
      <p className="review-verdict-message">{result.message}</p>
    </>
  );
}
