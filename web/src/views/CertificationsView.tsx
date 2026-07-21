/**
 * The certifications index (/certifications) — the "GET /certifications
 * has no UI room yet" follow-up recorded in handoff 0019's frontend
 * evidence. The room in front of every certificate: each certification on
 * record listed VERBATIM, oldest first exactly as the API serves them —
 * digitally signed records with their typed signer and signing-key
 * fingerprint, pre-signature (legacy) records with the honest absence
 * stated instead of a blank — and a door to each certificate view, where
 * the signature can be verified.
 *
 * House patterns: SummaryCards split the record by signature state as
 * filter toggles (counts are workflow tallies of records, never figures;
 * filtering hides nothing from the counts and the held-back count is
 * stated); every state — loading, error, empty — is stated in plain
 * language. Any signed-in role reads this room, like the API.
 */

import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, listCertifications } from "../api/client";
import type { CertificationRecord } from "../api/types";
import { canCertify, useSession } from "../auth/session";
import { Skeleton } from "../components/Skeleton";
import { SummaryCards } from "../components/SummaryCards";
import { copy } from "../copy";

/** Workflow tallies for display: thousands-separated, never a figure. */
function formatCount(count: number): string {
  return count.toLocaleString("en-US");
}

export function CertificationsView() {
  const session = useSession();
  const [records, setRecords] = useState<CertificationRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** null = no filter (all records shown). */
  const [filter, setFilter] = useState<"signed" | "legacy" | null>(null);

  useEffect(() => {
    listCertifications()
      .then(setRecords)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : String(err)),
      );
  }, []);

  const all = records ?? [];
  const signedCount = all.filter((r) => r.signed).length;
  const legacyCount = all.length - signedCount;
  const shown = all.filter(
    (r) => filter === null || (filter === "signed") === r.signed,
  );
  const heldBack = all.length - shown.length;

  return (
    <>
      <h1>{copy.certifications.heading}</h1>
      <p>{copy.certifications.intro}</p>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {/* Skeleton (handoff 0021 #2): the record list's shape while it
          loads; the words stay the room's own loading line. */}
      {!records && !error && (
        <Skeleton
          variant="table"
          count={4}
          label={copy.certifications.loading}
        />
      )}
      {/* Teaching empty state (handoff 0021 #4): warm + the first action
          (the Certify door renders for the certifying official). */}
      {records && records.length === 0 && (
        <>
          <p>{copy.certifications.empty}</p>
          {canCertify(session) && (
            <p>
              {copy.certifications.emptyActionOfficial}{" "}
              <Link to="/certify">{copy.certifications.emptyDoor}</Link>
            </p>
          )}
        </>
      )}
      {records && records.length > 0 && (
        <>
          {/* Signature-state cards ARE the filter toggles (handoff 0017
              #2): count + colored top border + label, aria-pressed. The
              counts always cover the whole record. */}
          <SummaryCards
            label={copy.certifications.summaryLabel}
            cards={[
              {
                key: "signed",
                label: copy.certifications.cardLabels.signed,
                count: formatCount(signedCount),
                tone: "success",
                pressed: filter === "signed",
              },
              {
                key: "legacy",
                label: copy.certifications.cardLabels.legacy,
                count: formatCount(legacyCount),
                tone: "neutral",
                pressed: filter === "legacy",
              },
            ]}
            onToggle={(key, pressed) =>
              setFilter(pressed ? (key as "signed" | "legacy") : null)
            }
          />
          {heldBack > 0 && (
            <p className="banner">
              {copy.certifications.filteredNote(formatCount(heldBack))}
            </p>
          )}
          <ul
            className="certification-list"
            aria-label={copy.certifications.listLabel}
          >
            {shown.map((record) => (
              <li key={record.certification_id}>
                <CertificationCard record={record} />
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

/**
 * One certification record, verbatim. A signed record leads with its typed
 * signer and carries the signing-key fingerprint; a legacy record states
 * the absence of a signature honestly — never a blank, never a backfill.
 */
function CertificationCard({ record }: { record: CertificationRecord }) {
  const headingId = useId();
  return (
    <article aria-labelledby={headingId} className="certification-record">
      <h2 id={headingId}>
        {copy.certifications.recordLabel(record.certification_id)}{" "}
        {record.signed ? (
          <span className="tag certified">{copy.certifications.signedTag}</span>
        ) : (
          <span className="tag uncertified">
            {copy.certifications.legacyTag}
          </span>
        )}
      </h2>
      {record.signed && record.signer_full_name && record.signer_title ? (
        <p className="certificate-signer">
          {copy.certifications.signerLine(
            record.signer_full_name,
            record.signer_title,
          )}
        </p>
      ) : (
        <p className="certificate-signer">
          {copy.certifications.certifiedByLine(record.certified_by)}
        </p>
      )}
      <dl>
        <dt>{copy.certifications.certifiedAtLabel}</dt>
        <dd>{record.certified_at}</dd>
        {/* The fingerprint verbatim on signed records; the honest legacy
            line otherwise. */}
        <dt>{copy.certifications.fingerprintLabel}</dt>
        <dd>
          {record.key_fingerprint ? (
            <code className="certificate-fingerprint">
              {record.key_fingerprint}
            </code>
          ) : (
            copy.certifications.legacyNote
          )}
        </dd>
      </dl>
      <p>
        {copy.certifications.coversLine(
          formatCount(record.metric_value_ids.length),
        )}{" "}
        <Link to={`/certifications/${record.certification_id}`}>
          {copy.certifications.viewCertificate(record.certification_id)}
        </Link>
      </p>
    </article>
  );
}
