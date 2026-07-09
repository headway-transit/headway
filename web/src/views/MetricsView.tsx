import { useCallback, useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, certify, listMetricValues } from "../api/client";
import type { MetricValue } from "../api/types";
import { canCertify, useSession } from "../auth/session";
import { Modal } from "../components/Modal";
import { copy } from "../copy";

/**
 * A calc version below 1.0.0 is marked PRE-VERIFICATION in
 * services/calc/REGULATORY_TRACKER.md: the calculation has not yet been
 * verified against the current FTA NTD Reporting Manual. This is a display
 * flag read off the version the API serves — the figure itself is never
 * touched client-side.
 */
function isPreVerification(value: MetricValue): boolean {
  return value.calc_version.startsWith("0.");
}

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function periodLabel(value: MetricValue): string {
  return `${value.period_start} to ${value.period_end}`;
}

export function MetricsView() {
  const session = useSession();
  const [values, setValues] = useState<MetricValue[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setValues(await listMetricValues());
    } catch (err) {
      setValues(null);
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const openCertifyModal = () => {
    setSuccessMessage(null);
    if (selected.size === 0) {
      setSelectionError(copy.metrics.nothingSelected);
      return;
    }
    setSelectionError(null);
    setModalOpen(true);
  };

  const handleCertified = async (message: string) => {
    setModalOpen(false);
    setSuccessMessage(message);
    setSelected(new Set());
    await load(); // re-read certification status from the API — never assume
  };

  const showCertifyControls = canCertify(session); // UX only; API enforces
  const selectedValues = (values ?? []).filter((v) =>
    selected.has(v.metric_value_id),
  );
  const anyPreVerification = (values ?? []).some(isPreVerification);

  return (
    <>
      <h1>{copy.metrics.heading}</h1>

      {anyPreVerification && (
        <p className="banner">{copy.metrics.preVerificationBanner}</p>
      )}

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

      {selectionError && (
        <div role="alert" className="alert">
          {selectionError}
        </div>
      )}

      {values && values.length === 0 && <p>{copy.metrics.empty}</p>}
      {!values && !loadError && <p>{copy.loading}</p>}

      {values && values.length > 0 && (
        <>
          {/* role/tabIndex: a horizontally scrollable region must be
              keyboard-reachable and named (axe: scrollable-region-focusable) */}
          <div
            className="table-wrap"
            role="region"
            aria-label={copy.metrics.heading}
            tabIndex={0}
          >
            <table>
              <caption>{copy.metrics.tableCaption}</caption>
              <thead>
                <tr>
                  {showCertifyControls && (
                    <th scope="col">{copy.metrics.columns.select}</th>
                  )}
                  <th scope="col">{copy.metrics.columns.metric}</th>
                  <th scope="col">{copy.metrics.columns.unit}</th>
                  <th scope="col">{copy.metrics.columns.period}</th>
                  <th scope="col">{copy.metrics.columns.value}</th>
                  <th scope="col">{copy.metrics.columns.calc}</th>
                  <th scope="col">{copy.metrics.columns.status}</th>
                  <th scope="col">{copy.metrics.columns.provenance}</th>
                </tr>
              </thead>
              <tbody>
                {values.map((v) => (
                  <tr key={v.metric_value_id}>
                    {showCertifyControls && (
                      <td>
                        {v.certification_status === "certified" ? (
                          <span>{copy.metrics.alreadyCertified}</span>
                        ) : (
                          <input
                            type="checkbox"
                            checked={selected.has(v.metric_value_id)}
                            onChange={() => toggleSelected(v.metric_value_id)}
                            aria-label={copy.metrics.selectRow(
                              metricLabel(v.metric),
                              periodLabel(v),
                            )}
                          />
                        )}
                      </td>
                    )}
                    <th scope="row">{metricLabel(v.metric)}</th>
                    <td>{v.unit}</td>
                    <td>{periodLabel(v)}</td>
                    {/* The figure, verbatim as the API served it. Never
                        parsed, rounded, or reformatted client-side. */}
                    <td className="figure">{v.value}</td>
                    <td>
                      {v.calc_name} {v.calc_version}
                      {isPreVerification(v) && (
                        <>
                          {" "}
                          <span className="tag pre-verification">
                            {copy.metrics.preVerificationTag}
                          </span>
                        </>
                      )}
                    </td>
                    <td>
                      <span className={`tag ${v.certification_status}`}>
                        {v.certification_status}
                      </span>
                    </td>
                    <td>
                      <Link to={`/metrics/${v.metric_value_id}/lineage`}>
                        {copy.metrics.explainLink}
                        <span className="visually-hidden">
                          {` — ${metricLabel(v.metric)}, ${periodLabel(v)}`}
                        </span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {showCertifyControls && (
            <p>
              <button
                type="button"
                className="primary"
                onClick={openCertifyModal}
              >
                {copy.metrics.certifySelected}
              </button>
            </p>
          )}
        </>
      )}

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
 * The attestation dialog. It states EXACTLY what is being certified (every
 * figure, its period, and the calculation that produced it) and delegates the
 * recorded attestation to POST /certifications — the API is the system of
 * record; the UI never records a certification locally.
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
      onCertified(
        copy.metrics.certifySuccess(
          response.metric_value_ids.length,
          response.certification_id,
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
              copy.metricLabels[v.metric] ?? v.metric,
              `${v.period_start} to ${v.period_end}`,
              v.value,
              v.unit,
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
              <Link to="/dq">{copy.metrics.reviewDqLink}</Link>
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
