/**
 * The certification cockpit (handoff 0007's deferred pillar; signing
 * ceremony reworked per handoff 0019, design 5): ONE screen showing exactly
 * what a signature covers. Attestation is informed consent, so the screen
 * is built as a chain of explicit steps, in reading and tab order:
 *
 *   (a) a period picker (same calendar-month selection as the monthly
 *       report — period SELECTION is UI logic; figures never are);
 *   (b) every figure the API serves for that period, EACH rendered as its
 *       full Receipt (story, coverage, the verbatim FTA rule, flags, the
 *       walk to raw records) with a visible, labeled checkbox — ticking a
 *       figure is per-figure consent, given against the full receipt;
 *   (c) a blockers panel: the count of open blocking data-quality issues,
 *       in plain language, with the path to /dq. While any exist the
 *       certify action is DISABLED and the reason shown mirrors the API's
 *       own 409 refusal — screen and server tell the same story. The button
 *       itself uses aria-disabled (never the native disabled attribute,
 *       which swallows clicks and hides the button from the tab order) and
 *       EVERY disabled cause is restated in an always-visible reason line
 *       directly beside the button (2026-07-11 click-through, finding 1);
 *   (d) unmissable aggregate warnings: if ANY selected figure is simulated
 *       or pre-verification, an alert restates what signing would mean and
 *       a separate acknowledge checkbox must be ticked before the button
 *       enables. Changing the selection clears the acknowledgement —
 *       consent applies to a specific set of figures, never carries over;
 *   (e) the SIGNATURE BLOCK (handoff 0019, design 5 — the final step):
 *       everything the signature covers listed first (each selected figure
 *       with its receipt hash and any statistician attestations it relies
 *       on, plus the acknowledged warnings), then the plain-language intent
 *       statement, then the signer's typed full name and title, then the
 *       sign-and-certify action. Submitting POSTs to /certifications — the
 *       server canonicalizes, signs with the installation key, and stores —
 *       and the UI then navigates to the certificate view (SPA nav).
 *
 * The client-side gating here is UX ONLY: the API enforces the role, the
 * blocking-DQ refusal, and double-certification server-side, and the API —
 * never this page — is the system of record for the certification.
 *
 * STALE-RESPONSE GUARD (the handoff-0017-era month-switch race, fixed
 * here): every load takes a sequence number, and a response only lands in
 * state if no newer load has started since. Without this, switching months
 * while a slow request was in flight could paint the OLD month's figures
 * under the NEW month's picker — a consent screen must never show figures
 * from a period the signer did not pick.
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ApiError,
  certify,
  getCertificationIntent,
  listDqIssues,
  listMetricValues,
} from "../api/client";
import type {
  CertificationIntent,
  DqIssue,
  MetricValue,
} from "../api/types";
import { canCertify, useSession } from "../auth/session";
import { Receipt } from "../components/Receipt";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { copy } from "../copy";
import {
  attestationReference,
  isPreVerification,
  isSimulated,
} from "../detail";
import { monthPeriod, previousMonth } from "../reports/period";

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function unitLabel(code: string): string {
  return copy.unitLabels[code] ?? code;
}

function periodLabel(value: MetricValue): string {
  return `${value.period_start} to ${value.period_end}`;
}

export function CertifyView() {
  const session = useSession();
  const allowed = canCertify(session); // UX only; the API enforces the role
  const navigate = useNavigate();
  const monthId = useId();
  const yearId = useId();
  const acknowledgeId = useId();
  const initial = useMemo(() => previousMonth(new Date()), []);
  const [month, setMonth] = useState(initial.month);
  const [year, setYear] = useState(initial.year);
  const reasonId = useId();
  const signerNameId = useId();
  const signerNameHintId = useId();
  const signerTitleId = useId();
  const signerTitleHintId = useId();
  const intentId = useId();
  const [values, setValues] = useState<MetricValue[] | null>(null);
  const [issues, setIssues] = useState<DqIssue[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // The SERVER's intent + scope statements (GET /certifications/intent):
  // the ceremony signs against the server's words, never this bundle's.
  // Until they load, the sign action refuses with a stated reason.
  const [intent, setIntent] = useState<CertificationIntent | null>(null);
  const [intentError, setIntentError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [acknowledged, setAcknowledged] = useState(false);
  const [signerName, setSignerName] = useState("");
  const [signerTitle, setSignerTitle] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [blockedByDq, setBlockedByDq] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // The stale-response guard: each load takes a ticket; only the response
  // holding the CURRENT ticket may write state. A month switch mid-flight
  // invalidates the older request's ticket, so its late response is
  // discarded instead of painting the wrong month's figures.
  const loadSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoadError(null);
    setValues(null);
    setIssues(null);
    setSelected(new Set());
    setAcknowledged(false);
    try {
      // The figures for the picked month AND the DQ issue list, together:
      // the blockers panel is as load-bearing as the figures themselves.
      // category=ntd (handoff 0014): the cockpit is the certifiable room —
      // operations metrics are structurally uncertifiable (the API refuses
      // them at 409 and the database CHECK makes a certified ops row
      // unrepresentable), so the server's own filter keeps them from ever
      // appearing beside a signature checkbox.
      const [nextValues, nextIssues] = await Promise.all([
        listMetricValues({ ...monthPeriod(year, month), category: "ntd" }),
        listDqIssues(),
      ]);
      if (seq !== loadSeq.current) return; // a newer load owns the screen
      setValues(nextValues);
      setIssues(nextIssues);
    } catch (err) {
      if (seq !== loadSeq.current) return;
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }, [year, month]);

  useEffect(() => {
    if (allowed) void load();
  }, [allowed, load]);

  // The intent/scope statements are fixed server text: fetched once.
  useEffect(() => {
    if (!allowed) return;
    let stale = false;
    (async () => {
      try {
        const next = await getCertificationIntent();
        if (!stale) setIntent(next);
      } catch (err) {
        if (!stale) {
          setIntentError(err instanceof ApiError ? err.message : String(err));
        }
      }
    })();
    return () => {
      stale = true;
    };
  }, [allowed]);

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    // Consent applies to a specific set of figures: any change to the
    // selection means the warnings must be read and acknowledged again.
    setAcknowledged(false);
  };

  const currentYear = new Date().getFullYear();
  const yearOptions = Array.from({ length: 4 }, (_, i) => currentYear - 3 + i);

  // The same rule the API's 409 applies: severity 'blocking' with status
  // 'open' or 'owned'. 'resolved' AND 'attested' (migration 0029 — the
  // p. 146 statistician closure) are the two CLOSED states; treating
  // 'attested' as open here made the cockpit refuse what the API allows
  // (found by the 2026-07-15 live click-through; screen and server must
  // tell the same story). Counted for DISPLAY and UX gating only — the
  // API re-checks on POST.
  const openBlocking =
    issues === null
      ? null
      : issues.filter(
          (i) =>
            i.severity === "blocking" &&
            (i.status === "open" || i.status === "owned"),
        ).length;
  const blocked = openBlocking === null || openBlocking > 0;

  const selectedValues = (values ?? []).filter((v) =>
    selected.has(v.metric_value_id),
  );
  const anySelectedSimulated = selectedValues.some((v) =>
    isSimulated(v.detail),
  );
  const anySelectedPreVerification = selectedValues.some(isPreVerification);
  const needsAcknowledge = anySelectedSimulated || anySelectedPreVerification;
  const nothingSelected = selected.size === 0;
  const nameMissing = signerName.trim().length === 0;
  const titleMissing = signerTitle.trim().length === 0;
  // No server intent statement = nothing to sign against: refuses, stated.
  const intentMissing = intent === null;
  const signDisabled =
    blocked ||
    nothingSelected ||
    (needsAcknowledge && !acknowledged) ||
    nameMissing ||
    titleMissing ||
    intentMissing ||
    submitting;

  const handleSign = async (event: FormEvent) => {
    event.preventDefault();
    // aria-disabled (unlike the native disabled attribute) keeps the button
    // focusable and clickable, so the refusal is PERCEIVABLE: the click
    // lands here and is refused while the always-visible reason line beside
    // the button says why. Nothing is silently swallowed.
    if (signDisabled || intent === null) return;
    setSubmitError(null);
    setBlockedByDq(false);
    setSubmitting(true);
    try {
      const response = await certify({
        metric_value_ids: selectedValues.map((v) => v.metric_value_id),
        // The SERVER's intent statement, sent back verbatim — the
        // permanent record carries exactly the words that were on screen.
        attestation: intent.intent_statement,
        signer_full_name: signerName.trim(),
        signer_title: signerTitle.trim(),
      });
      // SPA nav to the certificate (handoff 0019 design 5: submit →
      // certificate view). The certificate page IS the confirmation — the
      // shell moves focus to it on route change and it shows the stored
      // record read from the API (a toast would not survive the designed
      // navigation: the shell retires toasts on route change by design).
      navigate(`/certifications/${response.certification_id}`);
    } catch (err) {
      // Refusals (including 409 blocking-DQ) are shown verbatim: the API
      // explains itself in plain language, and hiding a refusal would make
      // an unresolved problem look resolved.
      setSubmitError(err instanceof ApiError ? err.message : String(err));
      setBlockedByDq(err instanceof ApiError && err.status === 409);
      setSubmitting(false);
    }
  };

  if (!allowed) {
    // Stated plainly, not hidden — and the API enforces the same rule.
    return (
      <>
        <h1>{copy.certify.heading}</h1>
        <p className="banner">{copy.certify.notAllowed}</p>
      </>
    );
  }

  return (
    <>
      <h1>{copy.certify.heading}</h1>
      <p>{copy.certify.intro}</p>

      {/* (a) the period picker: same calendar-month selection as the
          monthly report; the API does the filtering. */}
      <div className="month-picker">
        <div>
          <label htmlFor={monthId}>{copy.report.monthLabel}</label>
          <select
            id={monthId}
            value={month}
            onChange={(e) => setMonth(Number(e.target.value))}
          >
            {copy.report.monthNames.map((name, i) => (
              <option key={name} value={i + 1}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={yearId}>{copy.report.yearLabel}</label>
          <select
            id={yearId}
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
          >
            {yearOptions.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loadError && (
        <div role="alert" className="alert">
          {loadError}
        </div>
      )}

      {!values && !loadError && <p>{copy.loading}</p>}

      {/* (b) every figure of the period as a full Receipt, each with its
          own labeled consent checkbox. */}
      {values && (
        <section aria-labelledby="certify-figures-heading">
          <h2 id="certify-figures-heading">{copy.certify.figuresHeading}</h2>
          {values.length === 0 ? (
            <p>{copy.certify.empty}</p>
          ) : (
            <>
              <p>{copy.certify.figuresIntro}</p>
              <ul className="certify-list">
                {values.map((v) => {
                  const checkboxId = `certify-select-${v.metric_value_id}`;
                  return (
                    <li key={v.metric_value_id} className="certify-figure">
                      {v.certification_status === "certified" ? (
                        <p className="certify-checkbox">
                          <span className="tag certified">
                            {copy.certify.alreadyCertified}
                          </span>
                        </p>
                      ) : (
                        <p className="certify-checkbox">
                          <input
                            type="checkbox"
                            id={checkboxId}
                            checked={selected.has(v.metric_value_id)}
                            onChange={() => toggleSelected(v.metric_value_id)}
                          />
                          <label htmlFor={checkboxId}>
                            {copy.certify.selectFigure(
                              metricLabel(v.metric),
                              periodLabel(v),
                            )}
                          </label>
                        </p>
                      )}
                      <Receipt value={v} />
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </section>
      )}

      {/* (c) blockers: open blocking DQ issues stop certification, stated
          with the same reason the API's 409 would give, plus the path to
          act. Its absence is stated too — never left blank. */}
      <section aria-labelledby="certify-blockers-heading">
        <h2 id="certify-blockers-heading">{copy.certify.blockersHeading}</h2>
        {issues === null && !loadError && <p>{copy.loading}</p>}
        {issues === null && loadError && (
          <div role="alert" className="alert">
            <p>{copy.certify.blockersUnknown}</p>
          </div>
        )}
        {openBlocking !== null && openBlocking > 0 && (
          <div role="alert" className="alert">
            <p>{copy.certify.blockersReason(String(openBlocking))}</p>
            <p>
              <Link to="/dq">{copy.certify.reviewDqLink}</Link>
            </p>
          </div>
        )}
        {openBlocking === 0 && (
          <p>
            {copy.certify.blockersNone}{" "}
            <Link to="/dq">{copy.certify.reviewDqLink}</Link>
          </p>
        )}
      </section>

      {/* (d) aggregate warnings: simulated / pre-verification figures in
          the selection demand a separate, explicit acknowledgement before
          the sign action works. */}
      {needsAcknowledge && (
        <div role="alert" className="alert certify-warning">
          <h2>{copy.certify.warningsHeading}</h2>
          {anySelectedSimulated && (
            <p>
              <SimulatedBadge /> {copy.certify.simulatedWarning}
            </p>
          )}
          {anySelectedPreVerification && (
            <p>
              <span className="tag pre-verification">
                {copy.metrics.preVerificationTag}
              </span>{" "}
              {copy.certify.preVerificationWarning}
            </p>
          )}
          <p className="certify-checkbox">
            <input
              type="checkbox"
              id={acknowledgeId}
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            <label htmlFor={acknowledgeId}>
              {copy.certify.acknowledgeLabel}
            </label>
          </p>
        </div>
      )}

      {/* (e) the signature block (handoff 0019, design 5): the covered
          list first — each selected figure with its receipt hash and any
          statistician attestations it relies on, plus the acknowledged
          warnings — then the intent statement, the typed name and title,
          and the sign action with its always-visible reason line. */}
      <section aria-labelledby="certify-sign-heading" className="signature-block">
        <h2 id="certify-sign-heading">{copy.certify.sign.heading}</h2>

        <h3>{copy.certify.sign.coversHeading}</h3>
        {selectedValues.length === 0 ? (
          <p>{copy.certify.sign.coversEmpty}</p>
        ) : (
          <>
            <p>{copy.certify.sign.coversIntro}</p>
            <ul className="signature-covers">
              {selectedValues.map((v) => {
                const attested = attestationReference(v.detail);
                return (
                  <li key={v.metric_value_id}>
                    {copy.certify.sign.figureSummary(
                      metricLabel(v.metric),
                      periodLabel(v),
                      v.value,
                      unitLabel(v.unit),
                      `${v.calc_name} ${v.calc_version}`,
                    )}{" "}
                    <Link to={`/metrics/${v.metric_value_id}/lineage`}>
                      {copy.metrics.explainLink}
                    </Link>
                    <br />
                    {/* Receipt hashes exist only inside the signed document
                        (the server computes them at signing) — stated, so
                        the covered list never fakes one. */}
                    <span className="signature-hash">
                      {copy.certify.sign.receiptHashPending}
                    </span>
                    {attested && (
                      <>
                        <br />
                        <span>
                          {copy.certify.sign.attestationReliance(attested.id)}{" "}
                          <Link to="/attestations">
                            {copy.receipt.attested.detailsLink(attested.id)}
                          </Link>
                        </span>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}

        {submitError && (
          <div role="alert" className="alert">
            <p>{submitError}</p>
            {blockedByDq && (
              <p>
                <Link to="/dq">{copy.certify.reviewDqLink}</Link>
              </p>
            )}
          </div>
        )}

        <form onSubmit={handleSign}>
          {/* The intent statement is the SERVER's own text (GET
              /certifications/intent), shown verbatim — screen and signed
              record carry the same words. Until it loads there is nothing
              to sign against, and the reason line below says so. */}
          {intent ? (
            <p id={intentId} className="signature-intent">
              {intent.intent_statement}
            </p>
          ) : intentError ? (
            <div role="alert" className="alert">
              <p>{copy.certify.sign.intentUnavailable}</p>
              <p>{intentError}</p>
            </div>
          ) : (
            <p id={intentId}>{copy.loading}</p>
          )}
          <label htmlFor={signerNameId}>{copy.certify.sign.nameLabel}</label>
          <p id={signerNameHintId} className="field-hint">
            {copy.certify.sign.nameHint}
          </p>
          <input
            id={signerNameId}
            type="text"
            autoComplete="name"
            aria-describedby={`${signerNameHintId} ${intentId}`}
            value={signerName}
            onChange={(e) => setSignerName(e.target.value)}
          />
          <label htmlFor={signerTitleId}>{copy.certify.sign.titleLabel}</label>
          <p id={signerTitleHintId} className="field-hint">
            {copy.certify.sign.titleHint}
          </p>
          <input
            id={signerTitleId}
            type="text"
            autoComplete="organization-title"
            aria-describedby={signerTitleHintId}
            value={signerTitle}
            onChange={(e) => setSignerTitle(e.target.value)}
          />

          <p>{copy.certify.sign.recordedNote}</p>

          {/* The sign action + its reason line (2026-07-11 click-through,
              finding 1). The button uses aria-disabled, NOT the native
              disabled attribute: a natively disabled button swallows every
              click and falls out of the tab order, so the refusal was
              invisible right where the user was looking. Here the button
              stays perceivable and every disabled cause is stated in an
              always-visible reason line DIRECTLY beside it — the same story
              the blockers panel above and the API's own 409 tell. */}
          <div className="certify-action">
            <p>
              <button
                type="submit"
                className="primary"
                aria-disabled={signDisabled || undefined}
                aria-describedby={signDisabled ? reasonId : undefined}
              >
                {copy.certify.sign.submit}
              </button>
            </p>
            {signDisabled && (
              <div
                id={reasonId}
                role="status"
                className="certify-reason"
                aria-label={copy.certify.sign.reasonLabel}
              >
                {issues === null && !loadError && (
                  <p>{copy.certify.blockersLoading}</p>
                )}
                {issues === null && loadError && (
                  <p>{copy.certify.blockersUnknown}</p>
                )}
                {openBlocking !== null && openBlocking > 0 && (
                  <p>
                    {copy.certify.reasonBlockers(String(openBlocking))}{" "}
                    <Link to="/dq">{copy.certify.reasonBlockersLink}</Link>
                  </p>
                )}
                {values !== null && nothingSelected && (
                  <p>{copy.certify.nothingSelected}</p>
                )}
                {needsAcknowledge && !acknowledged && (
                  <p>{copy.certify.acknowledgeHint}</p>
                )}
                {nameMissing && (
                  <p>{copy.certify.sign.nameMissing}</p>
                )}
                {titleMissing && (
                  <p>{copy.certify.sign.titleMissing}</p>
                )}
                {intentMissing && !intentError && (
                  <p>{copy.certify.sign.intentLoading}</p>
                )}
                {intentMissing && intentError && (
                  <p>{copy.certify.sign.intentUnavailable}</p>
                )}
              </div>
            )}
          </div>
        </form>
      </section>
    </>
  );
}
