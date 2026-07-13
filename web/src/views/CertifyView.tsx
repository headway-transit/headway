/**
 * The certification cockpit (handoff 0007's deferred pillar): ONE screen
 * showing exactly what a signature covers. Attestation is informed consent,
 * so the screen is built as a chain of explicit steps, in reading and tab
 * order:
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
 *   (e) the attestation dialog (focus-trapped Modal): the selected figures
 *       restated verbatim (metric, value, period, calculation + version),
 *       the attestation statement, and POST /certifications. Success shows
 *       the certification id and audit event reference verbatim; a 409
 *       shows the API's refusal verbatim with the /dq link.
 *
 * The client-side gating here is UX ONLY: the API enforces the role, the
 * blocking-DQ refusal, and double-certification server-side, and the API —
 * never this page — is the system of record for the certification.
 */

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  certify,
  listDqIssues,
  listMetricValues,
} from "../api/client";
import type { DqIssue, MetricValue } from "../api/types";
import { canCertify, useSession } from "../auth/session";
import { Modal } from "../components/Modal";
import { Receipt } from "../components/Receipt";
import { SimulatedBadge } from "../components/SimulatedBadge";
import { copy } from "../copy";
import { isPreVerification, isSimulated } from "../detail";
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
  const monthId = useId();
  const yearId = useId();
  const acknowledgeId = useId();
  const initial = useMemo(() => previousMonth(new Date()), []);
  const [month, setMonth] = useState(initial.month);
  const [year, setYear] = useState(initial.year);
  const reasonId = useId();
  const [values, setValues] = useState<MetricValue[] | null>(null);
  const [issues, setIssues] = useState<DqIssue[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [acknowledged, setAcknowledged] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
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
      setValues(nextValues);
      setIssues(nextIssues);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }, [year, month]);

  useEffect(() => {
    if (allowed) void load();
  }, [allowed, load]);

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

  // The same rule the API's 409 applies (severity 'blocking', not resolved).
  // Counted for DISPLAY and UX gating only — the API re-checks on POST.
  const openBlocking =
    issues === null
      ? null
      : issues.filter(
          (i) => i.severity === "blocking" && i.status !== "resolved",
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
  const certifyDisabled =
    blocked || nothingSelected || (needsAcknowledge && !acknowledged);

  const openCertifyModal = () => {
    // aria-disabled (unlike the native disabled attribute) keeps the button
    // focusable and clickable, so the refusal is PERCEIVABLE: the click lands
    // here and is refused while the always-visible reason line beside the
    // button says why. Nothing is silently swallowed.
    if (certifyDisabled) return;
    setSuccessMessage(null);
    setModalOpen(true);
  };

  const handleCertified = async (message: string) => {
    setModalOpen(false);
    setSuccessMessage(message);
    await load(); // re-read figures AND blockers from the API — never assume
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

      {successMessage && (
        <div role="status" className="status">
          {successMessage}
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
          the certify button works. */}
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

      {/* The certify action + its reason line (2026-07-11 click-through,
          finding 1). The button uses aria-disabled, NOT the native disabled
          attribute: a natively disabled button swallows every click and
          falls out of the tab order, so the refusal was invisible right
          where the user was looking. Here the button stays perceivable and
          every disabled cause is stated in an always-visible reason line
          DIRECTLY beside it — the same story the blockers panel above and
          the API's own 409 tell. */}
      <div className="certify-action">
        <p>
          <button
            type="button"
            className="primary"
            aria-disabled={certifyDisabled || undefined}
            aria-describedby={certifyDisabled ? reasonId : undefined}
            onClick={openCertifyModal}
          >
            {copy.certify.certifySelected}
          </button>
        </p>
        {certifyDisabled && (
          <div
            id={reasonId}
            role="status"
            className="certify-reason"
            aria-label={copy.certify.reasonLabel}
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
          </div>
        )}
      </div>

      {/* (e) the attestation dialog. */}
      {modalOpen && (
        <CertifyModal
          values={selectedValues}
          onClose={() => setModalOpen(false)}
          onCertified={handleCertified}
        />
      )}
    </>
  );
}

interface CertifyModalProps {
  values: MetricValue[];
  onClose: () => void;
  onCertified: (successMessage: string) => void;
}

/**
 * The attestation dialog (relocated from the Metrics view — handoff 0007's
 * cockpit pillar). It restates EXACTLY what is being certified — every
 * selected figure's metric, value verbatim, period, and calculation +
 * version — takes the attestation statement, and delegates the recorded
 * attestation to POST /certifications. The API is the system of record; the
 * UI never records a certification locally.
 */
function CertifyModal({ values, onClose, onCertified }: CertifyModalProps) {
  const titleId = useId();
  const attestationId = useId();
  const hintId = useId();
  const [attestation, setAttestation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [blockedByDq, setBlockedByDq] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (attestation.trim().length === 0) {
      setError(copy.certifyModal.attestationRequired);
      setBlockedByDq(false);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const response = await certify({
        metric_value_ids: values.map((v) => v.metric_value_id),
        attestation,
      });
      // Success restates the API's identifiers verbatim: the certification
      // id and the audit event reference the API recorded.
      onCertified(
        copy.certify.certifySuccess(
          response.metric_value_ids.length,
          response.certification_id,
          String(response.audit_event_id),
        ),
      );
    } catch (err) {
      // Refusals (including 409 blocking-DQ) are shown verbatim: the API
      // explains itself in plain language, and hiding a refusal would make
      // an unresolved problem look resolved.
      setError(err instanceof ApiError ? err.message : String(err));
      setBlockedByDq(err instanceof ApiError && err.status === 409);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal titleId={titleId} onClose={onClose}>
      <h2 id={titleId}>{copy.certifyModal.heading}</h2>
      <p>{copy.certifyModal.intro}</p>
      <ul>
        {values.map((v) => (
          <li key={v.metric_value_id}>
            {copy.certifyModal.figureSummary(
              metricLabel(v.metric),
              periodLabel(v),
              v.value,
              unitLabel(v.unit),
              `${v.calc_name} ${v.calc_version}`,
            )}{" "}
            <Link to={`/metrics/${v.metric_value_id}/lineage`}>
              {copy.metrics.explainLink}
            </Link>
          </li>
        ))}
      </ul>
      {error && (
        <div role="alert" className="alert">
          <p>{error}</p>
          {blockedByDq && (
            <p>
              <Link to="/dq">{copy.certify.reviewDqLink}</Link>
            </p>
          )}
        </div>
      )}
      <form onSubmit={handleSubmit}>
        <label htmlFor={attestationId}>
          {copy.certifyModal.attestationLabel}
        </label>
        <p id={hintId}>{copy.certifyModal.attestationHint}</p>
        <textarea
          id={attestationId}
          aria-describedby={hintId}
          value={attestation}
          onChange={(e) => setAttestation(e.target.value)}
        />
        <div className="modal-actions">
          <button type="submit" className="primary" disabled={submitting}>
            {copy.certifyModal.confirm}
          </button>
          <button type="button" onClick={onClose}>
            {copy.certifyModal.cancel}
          </button>
        </div>
      </form>
    </Modal>
  );
}
