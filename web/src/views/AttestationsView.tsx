/**
 * Statistician attestations (/attestations — handoff 0019, design A).
 *
 * The p. 146 rule (quoted verbatim on this page from quotes.json, never
 * paraphrased alone) permits factoring beyond the 2% missing-trip line only
 * when a qualified statistician has approved the factoring method. Headway
 * previously refused flat — stricter than the regulation. This room:
 *
 *  - records that such an approval EXISTS and where its document lives (an
 *    external pointer — Headway never stores the document itself), with an
 *    audited, authorized-role entry (server-enforced; the UX gate mirrors
 *    it);
 *  - lists every attestation on record, REVOKED ONES INCLUDED — the table
 *    is append-only history and this page never hides a row;
 *  - states plainly what an attestation can never do (the handoff's hard
 *    limits, pinned by calc tests server-side).
 *
 * The UI records and displays; the CALC decides. Whether a figure is
 * factored under an attestation is the deterministic calculation's call —
 * this page never applies one to a number.
 */

import { useCallback, useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  createAttestation,
  listAttestations,
  revokeAttestation,
} from "../api/client";
import type { AttestationRecord } from "../api/types";
import { canEnterAttestations, useSession } from "../auth/session";
import { QuoteFigure } from "../components/QuoteFigure";
import { copy } from "../copy";
import { quoteContaining } from "../regulatory/quotes";
import { pushToast } from "../toasts";

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

/** The metrics whose calcs have a factor-up path (handoff 0019 design 2). */
const ATTESTABLE_METRICS = ["upt", "pmt"];

/** The p. 146 statistician sentence, from the tracker's upt_v0 section. */
const STATISTICIAN_QUOTE = quoteContaining(
  "upt_v0",
  "qualified statistician approve the factoring method",
);

/** The p. 149 undersampling HARD LIMIT — no statistician cure exists. */
const UNDERSAMPLING_QUOTE = quoteContaining(
  "upt_v0",
  "must not collect a smaller sample",
);

/** The p. 150 statistician-qualifications guidance, verbatim. */
const QUALIFICATIONS_QUOTE = quoteContaining(
  "upt_v0",
  "FTA does not prescribe specific statistician qualifications",
);

export function AttestationsView() {
  const session = useSession();
  const allowed = canEnterAttestations(session); // UX only; API enforces
  const [records, setRecords] = useState<AttestationRecord[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setRecords(await listAttestations());
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <h1>{copy.attestations.heading}</h1>
      <p>{copy.attestations.intro}</p>
      {/* The rule itself, word for word — the lead-in above never stands
          alone as a paraphrase (the DR-callout discipline). */}
      <QuoteFigure
        quote={STATISTICIAN_QUOTE}
        missingMessage={copy.receipt.attested.quoteMissing("upt_v0")}
      />
      <p>{copy.attestations.behaviorNote}</p>

      <section aria-labelledby="attestation-limits-heading">
        <h2 id="attestation-limits-heading">
          {copy.attestations.limitsHeading}
        </h2>
        <ul>
          {copy.attestations.limits.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
        {/* The undersampling hard limit in the manual's own words — no
            statistician approval cures a too-small sample (p. 149). */}
        <QuoteFigure
          quote={UNDERSAMPLING_QUOTE}
          missingMessage={copy.receipt.ruleMissing("upt_v0")}
        />
      </section>

      {allowed ? (
        <AttestationForm onRecorded={load} />
      ) : (
        <p className="banner">{copy.attestations.form.notAllowed}</p>
      )}

      <section aria-labelledby="attestation-list-heading">
        <h2 id="attestation-list-heading">{copy.attestations.listHeading}</h2>
        {loadError && (
          <div role="alert" className="alert">
            {loadError}
          </div>
        )}
        {!records && !loadError && <p>{copy.loading}</p>}
        {records && records.length === 0 && (
          <p>{copy.attestations.empty}</p>
        )}
        {records && records.length > 0 && (
          <ul className="attestation-list">
            {records.map((record) => (
              <AttestationCard
                key={record.attestation_id}
                record={record}
                canRevoke={allowed}
                onRevoked={load}
              />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function AttestationCard({
  record,
  canRevoke,
  onRevoked,
}: {
  record: AttestationRecord;
  canRevoke: boolean;
  onRevoked: () => Promise<void>;
}) {
  const id = record.attestation_id;
  const revoked = record.revoked_at !== null;
  return (
    <li
      className={revoked ? "attestation-card revoked" : "attestation-card"}
      id={`attestation-${id}`}
    >
      <h3>
        {copy.attestations.attestationLabel(id)}
        {revoked && (
          <>
            {" "}
            <span className="tag revoked">{copy.attestations.revokedTag}</span>
          </>
        )}
      </h3>
      {/* Revocation is a visible state, never a deletion or a hidden row. */}
      {revoked && (
        <>
          <p className="attestation-revoked-note">
            {copy.attestations.revokedNote(
              record.revoked_at as string,
              record.revoked_by ?? "",
            )}
          </p>
          {record.revocation_reason && (
            <p>{copy.attestations.revokedReason(record.revocation_reason)}</p>
          )}
        </>
      )}
      <p>
        {copy.attestations.statisticianLine(
          record.statistician_name,
          record.statistician_credentials,
        )}
      </p>
      <h4>{copy.attestations.methodHeading}</h4>
      <p>{record.method_description}</p>
      <h4>{copy.attestations.scopeHeading}</h4>
      <ul>
        <li>{copy.attestations.scopeMetric(metricLabel(record.metric))}</li>
        <li>{copy.attestations.scopePattern(record.scope_pattern)}</li>
        <li>
          {copy.attestations.scopePeriod(
            record.period_start,
            record.period_end,
          )}
        </li>
      </ul>
      <p>{copy.attestations.documentLine(record.document_reference)}</p>
      <p className="attestation-entered">
        {copy.attestations.enteredLine(record.entered_by, record.entered_at)}
      </p>
      {canRevoke && !revoked && (
        <RevokeForm attestationId={id} onRevoked={onRevoked} />
      )}
    </li>
  );
}

/**
 * The per-card revocation act (certifying_official; server-enforced;
 * audited). Append-only: revoking marks the row, never removes it — the
 * note says exactly what revoking does and does not change.
 */
function RevokeForm({
  attestationId,
  onRevoked,
}: {
  attestationId: string;
  onRevoked: () => Promise<void>;
}) {
  const reasonId = useId();
  const reasonHintId = useId();
  const disabledReasonId = useId();
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const disabled = reason.trim().length === 0 || submitting;

  const handleRevoke = async (event: FormEvent) => {
    event.preventDefault();
    if (disabled) return; // aria-disabled: perceivable refusal, stated below
    setError(null);
    setSubmitting(true);
    try {
      await revokeAttestation(attestationId, { reason: reason.trim() });
      pushToast(copy.attestations.revoke.toast);
      await onRevoked(); // re-read the record from the API — never assume
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleRevoke} className="attestation-revoke">
      <h4>{copy.attestations.revoke.heading}</h4>
      <p className="field-hint">{copy.attestations.revoke.note}</p>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <label htmlFor={reasonId}>
        {copy.attestations.revoke.reasonLabel(attestationId)}
      </label>
      <p id={reasonHintId} className="field-hint">
        {copy.attestations.revoke.reasonHint}
      </p>
      <input
        id={reasonId}
        type="text"
        aria-describedby={reasonHintId}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <button
        type="submit"
        aria-disabled={disabled || undefined}
        aria-describedby={disabled ? disabledReasonId : undefined}
      >
        {copy.attestations.revoke.button(attestationId)}
      </button>
      {disabled && (
        <p id={disabledReasonId} role="status" className="field-hint">
          {copy.attestations.revoke.reasonMissing}
        </p>
      )}
    </form>
  );
}

function AttestationForm({ onRecorded }: { onRecorded: () => Promise<void> }) {
  const ids = {
    name: useId(),
    credentials: useId(),
    credentialsHint: useId(),
    method: useId(),
    methodHint: useId(),
    document: useId(),
    documentHint: useId(),
    metric: useId(),
    metricHint: useId(),
    pattern: useId(),
    patternHint: useId(),
    periodStart: useId(),
    periodEnd: useId(),
    reason: useId(),
  };
  const f = copy.attestations.form;
  const [name, setName] = useState("");
  const [credentials, setCredentials] = useState("");
  const [method, setMethod] = useState("");
  const [documentRef, setDocumentRef] = useState("");
  const [metric, setMetric] = useState(ATTESTABLE_METRICS[0]);
  const [pattern, setPattern] = useState("agency");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Every incomplete field is a stated reason (the house disabled-with-
  // reason pattern): the button stays perceivable and says why it is off.
  const missing: string[] = [
    ...(name.trim() ? [] : [f.nameLabel]),
    ...(credentials.trim() ? [] : [f.credentialsLabel]),
    ...(method.trim() ? [] : [f.methodLabel]),
    ...(documentRef.trim() ? [] : [f.documentLabel]),
    ...(pattern.trim() ? [] : [f.patternLabel]),
    ...(periodStart ? [] : [f.periodStartLabel]),
    ...(periodEnd ? [] : [f.periodEndLabel]),
  ];
  const disabled = missing.length > 0 || submitting;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (disabled) return; // aria-disabled: the click lands, the reason shows
    setError(null);
    setSuccess(null);
    setSubmitting(true);
    try {
      const response = await createAttestation({
        statistician_name: name.trim(),
        statistician_credentials: credentials.trim(),
        method_description: method.trim(),
        document_reference: documentRef.trim(),
        metric,
        scope_pattern: pattern.trim(),
        period_start: periodStart,
        period_end: periodEnd,
      });
      // The durable identifiers, verbatim from the API; the toast confirms.
      setSuccess(
        f.success(response.attestation_id, String(response.audit_event_id)),
      );
      pushToast(f.toast);
      setName("");
      setCredentials("");
      setMethod("");
      setDocumentRef("");
      setPattern("agency");
      setPeriodStart("");
      setPeriodEnd("");
      await onRecorded(); // re-read the list from the API — never assume
    } catch (err) {
      // API refusals verbatim — the server writes plain-language errors.
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section aria-labelledby="attestation-form-heading">
      <h2 id="attestation-form-heading">{f.heading}</h2>
      <p>{f.intro}</p>

      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {success && (
        <div role="status" className="status">
          {success}
        </div>
      )}

      <form onSubmit={handleSubmit} className="attestation-form">
        <fieldset>
          <legend>{f.statisticianLegend}</legend>
          {/* Who counts as qualified, in the manual's own words (p. 150):
              the agency is accountable for the qualification. */}
          <QuoteFigure
            quote={QUALIFICATIONS_QUOTE}
            missingMessage={copy.receipt.ruleMissing("upt_v0")}
          />
          <label htmlFor={ids.name}>{f.nameLabel}</label>
          <input
            id={ids.name}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <label htmlFor={ids.credentials}>{f.credentialsLabel}</label>
          <p id={ids.credentialsHint} className="field-hint">
            {f.credentialsHint}
          </p>
          <input
            id={ids.credentials}
            type="text"
            aria-describedby={ids.credentialsHint}
            value={credentials}
            onChange={(e) => setCredentials(e.target.value)}
          />
        </fieldset>

        <fieldset>
          <legend>{f.methodLegend}</legend>
          <label htmlFor={ids.method}>{f.methodLabel}</label>
          <p id={ids.methodHint} className="field-hint">
            {f.methodHint}
          </p>
          <textarea
            id={ids.method}
            aria-describedby={ids.methodHint}
            value={method}
            onChange={(e) => setMethod(e.target.value)}
          />
          <label htmlFor={ids.document}>{f.documentLabel}</label>
          <p id={ids.documentHint} className="field-hint">
            {f.documentHint}
          </p>
          <input
            id={ids.document}
            type="text"
            aria-describedby={ids.documentHint}
            value={documentRef}
            onChange={(e) => setDocumentRef(e.target.value)}
          />
        </fieldset>

        <fieldset>
          <legend>{f.scopeLegend}</legend>
          <label htmlFor={ids.metric}>{f.metricLabel}</label>
          <p id={ids.metricHint} className="field-hint">
            {f.metricHint}
          </p>
          <select
            id={ids.metric}
            aria-describedby={ids.metricHint}
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
          >
            {ATTESTABLE_METRICS.map((code) => (
              <option key={code} value={code}>
                {metricLabel(code)}
              </option>
            ))}
          </select>
          <label htmlFor={ids.pattern}>{f.patternLabel}</label>
          <p id={ids.patternHint} className="field-hint">
            {f.patternHint}
          </p>
          <input
            id={ids.pattern}
            type="text"
            aria-describedby={ids.patternHint}
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
          />
          <label htmlFor={ids.periodStart}>{f.periodStartLabel}</label>
          <input
            id={ids.periodStart}
            type="date"
            value={periodStart}
            onChange={(e) => setPeriodStart(e.target.value)}
          />
          <label htmlFor={ids.periodEnd}>{f.periodEndLabel}</label>
          <input
            id={ids.periodEnd}
            type="date"
            value={periodEnd}
            onChange={(e) => setPeriodEnd(e.target.value)}
          />
        </fieldset>

        <div className="certify-action">
          <p>
            <button
              type="submit"
              className="primary"
              aria-disabled={disabled || undefined}
              aria-describedby={disabled ? ids.reason : undefined}
            >
              {f.submit}
            </button>
          </p>
          {disabled && (
            <div
              id={ids.reason}
              role="status"
              className="certify-reason"
              aria-label={f.reasonLabel}
            >
              {missing.map((field) => (
                <p key={field}>{f.missingField(field)}</p>
              ))}
            </div>
          )}
        </div>
      </form>
    </section>
  );
}
