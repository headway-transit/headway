/**
 * One certification-verification verdict, rendered with the SERVER's
 * message VERBATIM (handoff 0019, design 6). Extracted from the
 * certificate view so the public verify affordance (/public) renders the
 * exact same four honest verdicts:
 *
 *   verified        → status (success tokens)
 *   failed          → alert (danger tokens) — a failure is never softened
 *   key_mismatch    → alert (warning voice — honestly inconclusive, per
 *                     the server's own message)
 *   unsigned_legacy → plain banner (an honest gap, not a failure)
 *
 * Any verdict this UI does not know renders LOUD, like a failure.
 */

import type { VerificationResult } from "../api/types";
import { copy } from "../copy";

export function VerificationVerdict({ result }: { result: VerificationResult }) {
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
