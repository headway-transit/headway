/**
 * The certificate view (/certifications/:id — handoff 0019, designs 5–8):
 * the permanent record of one certification with the SIGNATURE BLOCK front
 * and center — the typed name and title, timestamp, key fingerprint — a
 * verification verdict computed BY THE SERVER (once on load, and again on
 * demand via the verify button), the covered figures from the signed
 * canonical document with their receipt hashes, and the HONEST-SCOPE
 * statement exactly as it was signed (integrity and attribution within
 * this system — not PKI non-repudiation; the text is the server's, stored
 * inside the signed document, rendered VERBATIM and never paraphrased —
 * its absence on a signed record is stated loudly).
 *
 * Typed against services/api routers/certify.py exactly (reconciled
 * 2026-07-15): GET /certifications/{id} serves the record + raw signed
 * bytes + parsed document + a live VerificationResult; GET
 * /certifications/{id}/verify re-verifies on demand. Every verdict —
 * verified, FAILED, key_mismatch, unsigned legacy — renders the server's
 * own message verbatim. Certifications recorded before the signing key
 * existed have NULL signature columns: honest history, never backfilled.
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, getCertification, verifyCertification } from "../api/client";
import type {
  CertificationCertificate,
  VerificationResult,
} from "../api/types";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { copy } from "../copy";

function metricLabel(code: string): string {
  return copy.metricLabels[code] ?? code;
}

function unitLabel(code: string): string {
  return copy.unitLabels[code] ?? code;
}

/**
 * One verification verdict, rendered with the server's message VERBATIM.
 * verified = status (success tokens); failed = alert (danger tokens);
 * key_mismatch = alert (warning tokens — honestly inconclusive, per the
 * server's own message); unsigned_legacy = plain banner (an honest gap,
 * not a failure).
 */
function Verdict({ result }: { result: VerificationResult }) {
  if (result.verdict === "verified") {
    return (
      <div role="status" className="status certificate-verified">
        <p>
          <strong>{copy.certificate.verifiedLead}</strong> {result.message}
        </p>
      </div>
    );
  }
  if (result.verdict === "unsigned_legacy") {
    return <p className="banner">{result.message}</p>;
  }
  if (result.verdict === "key_mismatch") {
    return (
      <div role="alert" className="alert certificate-mismatch">
        <p>
          <strong>{copy.certificate.mismatchLead}</strong> {result.message}
        </p>
      </div>
    );
  }
  // 'failed' and any verdict this UI does not know: LOUD, verbatim.
  return (
    <div role="alert" className="alert certificate-failed">
      <p>
        <strong>{copy.certificate.failedLead}</strong> {result.message}
      </p>
    </div>
  );
}

export function CertificateView() {
  const { id } = useParams<{ id: string }>();
  const [certificate, setCertificate] =
    useState<CertificationCertificate | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // The on-demand re-verification (the verify button); the certificate
  // itself already carries the server's on-load verification.
  const [recheck, setRecheck] = useState<
    | { kind: "idle" }
    | { kind: "running" }
    | { kind: "done"; result: VerificationResult }
    | { kind: "error"; message: string }
  >({ kind: "idle" });

  const load = useCallback(async () => {
    setLoadError(null);
    setCertificate(null);
    setRecheck({ kind: "idle" });
    try {
      setCertificate(await getCertification(id ?? ""));
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleVerify = async () => {
    setRecheck({ kind: "running" });
    try {
      setRecheck({ kind: "done", result: await verifyCertification(id ?? "") });
    } catch (err) {
      // A verification error is a FAILURE to verify — loud and verbatim,
      // never an ignorable note.
      setRecheck({
        kind: "error",
        message: err instanceof ApiError ? err.message : String(err),
      });
    }
  };

  const document = certificate?.document ?? null;

  return (
    <>
      <Breadcrumbs
        trail={[
          { label: copy.certificate.crumbCertify, to: "/certify" },
          { label: copy.certificate.crumbSelf(id ?? "") },
        ]}
      />
      <h1>{copy.certificate.heading}</h1>
      <p>{copy.certificate.intro}</p>

      {loadError && (
        <div role="alert" className="alert">
          <p>{copy.certificate.loadErrorLead}</p>
          <p>{loadError}</p>
        </div>
      )}
      {!certificate && !loadError && <p>{copy.loading}</p>}

      {certificate && (
        <>
          {/* The signature block — FRONT AND CENTER (design 5). */}
          <section
            aria-labelledby="certificate-signature-heading"
            className="certificate-signature"
          >
            <h2 id="certificate-signature-heading">
              {copy.certificate.signatureHeading}
            </h2>
            {certificate.signer_full_name && certificate.signer_title ? (
              <p className="certificate-signer">
                {copy.certificate.signedBy(
                  certificate.signer_full_name,
                  certificate.signer_title,
                )}
              </p>
            ) : (
              <p className="certificate-signer">
                {copy.certificate.certifiedByOnly(certificate.certified_by)}
              </p>
            )}
            <p>{copy.certificate.signedAt(certificate.certified_at)}</p>

            {/* The server's on-load verification verdict, verbatim. */}
            <Verdict result={certificate.verification} />

            {certificate.signed && (
              <>
                <p>
                  {copy.certificate.fingerprintLabel}:{" "}
                  <code className="certificate-fingerprint">
                    {certificate.key_fingerprint}
                  </code>
                </p>
                {certificate.signature && (
                  <details>
                    <summary>{copy.certificate.signatureLabel}</summary>
                    <code className="certificate-fingerprint">
                      {certificate.signature}
                    </code>
                  </details>
                )}
                <p>
                  <button
                    type="button"
                    className="primary"
                    aria-disabled={recheck.kind === "running" || undefined}
                    onClick={() => {
                      if (recheck.kind !== "running") void handleVerify();
                    }}
                  >
                    {copy.certificate.verifyButton}
                  </button>
                </p>
                {recheck.kind === "running" && (
                  <p role="status">{copy.certificate.verifying}</p>
                )}
                {recheck.kind === "done" && <Verdict result={recheck.result} />}
                {recheck.kind === "error" && (
                  <div role="alert" className="alert certificate-failed">
                    <p>
                      <strong>{copy.certificate.failedLead}</strong>{" "}
                      {recheck.message}
                    </p>
                  </div>
                )}
              </>
            )}
          </section>

          {/* The honest-scope statement (design 8), VERBATIM as it was
              signed (document.scope_statement). Its absence on a SIGNED
              record is a loud condition — this page never substitutes its
              own description of what a signature means. */}
          {certificate.signed && (
            <section aria-labelledby="certificate-scope-heading">
              <h2 id="certificate-scope-heading">
                {copy.certificate.scopeHeading}
              </h2>
              {document?.scope_statement ? (
                <p className="certificate-scope">{document.scope_statement}</p>
              ) : (
                <p className="alert">{copy.certificate.scopeMissing}</p>
              )}
            </section>
          )}

          {/* The statement that was signed, verbatim from the record. */}
          <section aria-labelledby="certificate-statement-heading">
            <h2 id="certificate-statement-heading">
              {copy.certificate.statementHeading}
            </h2>
            <blockquote className="certificate-statement">
              <p>{certificate.attestation}</p>
            </blockquote>
          </section>

          {/* The covered figures, from the signed document (design 5),
              each with the receipt hash the signature covers. */}
          <section aria-labelledby="certificate-covered-heading">
            <h2 id="certificate-covered-heading">
              {copy.certificate.coveredHeading}
            </h2>
            {document && document.figures.length > 0 ? (
              <ul className="signature-covers">
                {document.figures.map((figure) => (
                  <li key={figure.metric_value_id}>
                    {copy.certificate.coveredFigure(
                      metricLabel(figure.metric),
                      `${figure.period_start} to ${figure.period_end}`,
                      figure.value,
                      unitLabel(figure.unit),
                      `${figure.calc_name} ${figure.calc_version}`,
                    )}{" "}
                    <Link to={`/metrics/${figure.metric_value_id}/lineage`}>
                      {copy.certificate.provenanceLink}
                    </Link>
                    <br />
                    <span className="signature-hash">
                      {copy.certificate.receiptHash(figure.receipt_sha256)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              // Degraded-but-honest (a legacy record without a signed
              // document): ids only, stated, provenance links kept.
              <>
                <p>{copy.certificate.coveredIdsOnly}</p>
                <ul className="signature-covers">
                  {certificate.metric_value_ids.map((figureId) => (
                    <li key={figureId}>
                      <code>{figureId}</code>{" "}
                      <Link to={`/metrics/${figureId}/lineage`}>
                        {copy.certificate.provenanceLink}
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          {/* Statistician attestations recorded in the signed document. */}
          {document && document.statistician_attestations.length > 0 && (
            <section aria-labelledby="certificate-attestations-heading">
              <h2 id="certificate-attestations-heading">
                {copy.certificate.attestationsHeading}
              </h2>
              <ul className="signature-covers">
                {document.statistician_attestations.map((attestation) => (
                  <li key={attestation.attestation_id}>
                    {copy.certificate.attestationLine(
                      attestation.attestation_id,
                      attestation.statistician_name,
                    )}{" "}
                    <Link to="/attestations">
                      {copy.certificate.attestationsLink}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </>
  );
}
