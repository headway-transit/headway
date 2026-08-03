/**
 * The raw-record inspector (handoff 0035) — the leaf of the lineage walk,
 * opened.
 *
 * A UAT auditor walked a VRH figure back to its sources and hit a wall of
 * hashes labelled "the end of the trail": *"It doesn't really provide any
 * data to validate or verify."* A content address is genuine proof, but
 * proof you cannot inspect asks for trust at the one step where this product
 * must never ask for it. So this component renders, for one raw record:
 *
 *  1. THE LABEL — source, who collected it, when it arrived, how big it is,
 *     whether it could be read on arrival. Absent values render as absent.
 *  2. VERIFY INTEGRITY — a real action against the stored bytes, with the
 *     verdict in words. A pass is quiet and specific; a MISMATCH is an
 *     `role="alert"` panel that states both fingerprints and names the
 *     data-quality finding it raised. Failure is never a colour cue: it is
 *     a heading, a sentence, an icon and a link.
 *  3. THE WINDOW — a bounded preview of the contents, with the cap stated,
 *     and the exact bytes one button away.
 *  4. THE FINGERPRINT — still visible, deliberately demoted to a footnote
 *     under the label. It was the whole screen; it should always have been
 *     the small print.
 *
 * Nothing here is computed client-side. Every string that carries meaning —
 * the verdict, the truncation note, the withholding reason — is the server's
 * own words, rendered verbatim. The sensitivity gate is enforced by the API;
 * this component only explains the refusal it was given.
 */

import { useEffect, useId, useState } from "react";
import {
  ApiError,
  downloadRawRecord,
  getRawRecord,
  getRawRecordPayload,
  verifyRawRecord,
} from "../api/client";
import type {
  GtfsRealtimeEntity,
  RawRecordLabel,
  RawRecordPreview,
  RawRecordVerdict,
} from "../api/types";
import { saveBlob } from "../download";
import { copy } from "../copy";
import { SimulatedBadge } from "./SimulatedBadge";

const c = copy.rawRecord;

function formatBytes(bytes: number | null | undefined): string | null {
  if (bytes === null || bytes === undefined) return null;
  if (bytes < 1024) return `${bytes.toLocaleString()} bytes`;
  if (bytes < 1024 * 1024)
    return `${(bytes / 1024).toFixed(1)} KB (${bytes.toLocaleString()} bytes)`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB (${bytes.toLocaleString()} bytes)`;
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return c.absent;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

/** A definition row; an absent value says so rather than rendering blank. */
function Field({
  label,
  value,
  children,
}: {
  label: string;
  value?: string | null;
  children?: React.ReactNode;
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children ?? (value ? value : <em>{c.absent}</em>)}</dd>
    </>
  );
}

export function RawRecordInspector({ recordId }: { recordId: string }) {
  const [label, setLabel] = useState<RawRecordLabel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<RawRecordVerdict | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [preview, setPreview] = useState<RawRecordPreview | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  /** Ties the refused control to the server's refusal (see below). */
  const withheldId = useId();

  useEffect(() => {
    let cancelled = false;
    setLabel(null);
    setError(null);
    setVerdict(null);
    setVerifyError(null);
    setPreview(null);
    setPreviewOpen(false);
    setPreviewError(null);
    getRawRecord(recordId)
      .then((body) => {
        if (!cancelled) setLabel(body);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [recordId]);

  async function onVerify() {
    setVerifying(true);
    setVerifyError(null);
    try {
      setVerdict(await verifyRawRecord(recordId));
    } catch (err) {
      setVerdict(null);
      setVerifyError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setVerifying(false);
    }
  }

  async function onTogglePreview() {
    // Withheld: the control is aria-disabled, so the click still arrives
    // here and is refused, exactly as the server would refuse it. Asking
    // anyway would trade the stated reason for a raw 403.
    if (label && !label.sensitivity.preview_allowed) return;
    if (previewOpen) {
      setPreviewOpen(false);
      return;
    }
    setPreviewOpen(true);
    if (preview) return;
    setPreviewError(null);
    try {
      setPreview(await getRawRecordPayload(recordId));
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function onDownload() {
    setDownloading(true);
    try {
      const file = await downloadRawRecord(recordId);
      saveBlob(file.blob, file.filename);
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDownloading(false);
    }
  }

  if (error) {
    return (
      <div role="alert" className="alert">
        {error}
      </div>
    );
  }
  if (!label) {
    return <p className="raw-record-loading">{c.loading}</p>;
  }

  const size =
    formatBytes(label.stored_bytes.size_bytes) ??
    (label.stored_bytes.status === "measured_on_open" ? c.sizeUnknown : null);

  return (
    <div className="raw-record">
      <dl className="raw-record-label">
        <Field label={c.source}>
          {label.source}
          {label.simulated && (
            <>
              {" "}
              <SimulatedBadge />
            </>
          )}
        </Field>
        <Field
          label={c.connector}
          value={`${label.connector} (version ${label.connector_version})`}
        />
        <Field label={c.fetchedAt} value={formatWhen(label.fetched_at)} />
        <Field label={c.contentType} value={label.content_type} />
        <Field label={c.size} value={size} />
        <Field label={c.parseStatus}>
          {label.parse_status === "ok" ? (
            c.parseOk
          ) : (
            /* A record that could not be read on arrival is a finding, not a
               footnote: it is said in words, with the parser's own reason. */
            <span className="raw-record-malformed">
              <strong>{c.parseMalformed}</strong>
              {label.parse_error ? ` — ${label.parse_error}` : null}
            </span>
          )}
        </Field>
        <Field label={c.storedAt} value={label.stored_bytes.note} />
      </dl>

      {/* The hash: still here, now the footnote it should always have been. */}
      <p className="raw-record-fingerprint">
        <span className="raw-record-fingerprint-label">
          {c.fingerprintHeading}
        </span>{" "}
        <code>{label.content_address.digest}</code>
        <span className="raw-record-fingerprint-note">
          {label.content_address.note}
        </span>
      </p>

      <div className="raw-record-actions">
        <button type="button" onClick={onVerify} disabled={verifying}>
          {verifying ? c.verifying : c.verify}
        </button>
        {/* WITHHELD IS NOT ABSENT (handoff 0047, design point 3).
            aria-disabled, never the native attribute: `disabled` takes the
            control out of the tab order, so a keyboard or screen-reader
            reviewer sweeping the actions never meets it and is never told
            why the contents are closed — they meet a silence, and a silence
            gets written down as missing data. Focusable, described by the
            server's own refusal, and the handler refuses the click. */}
        <button
          type="button"
          onClick={onTogglePreview}
          aria-expanded={previewOpen}
          aria-disabled={!label.sensitivity.preview_allowed || undefined}
          aria-describedby={
            label.sensitivity.preview_allowed ? undefined : withheldId
          }
        >
          {previewOpen ? c.hideInspect : c.inspect}
        </button>
        {label.sensitivity.preview_allowed && (
          <button type="button" onClick={onDownload} disabled={downloading}>
            {downloading ? c.downloading : c.download}
          </button>
        )}
      </div>

      {!label.sensitivity.preview_allowed && (
        /* Withheld, and the reason is the server's own words, VERBATIM. The
           record's label and its integrity check stay available: the chain
           of custody is never broken, only the window is closed.

           This block is what stands between a reviewer and a false finding.
           A blank where contents should be reads as MISSING DATA — a finding
           against an agency that did nothing wrong — so the absence is
           always drawn, named and explained. */
        <div className="banner raw-record-withheld" id={withheldId}>
          <p>
            <strong>{c.withheldHeading}</strong> — {label.sensitivity.label}
          </p>
          <p>{label.sensitivity.refusal ?? label.sensitivity.reason}</p>
        </div>
      )}

      {verifyError && (
        <div role="alert" className="alert">
          {verifyError}
        </div>
      )}
      {verdict && <Verdict verdict={verdict} />}

      {previewOpen && (
        <div className="raw-record-preview">
          {previewError && (
            <div role="alert" className="alert">
              {previewError}
            </div>
          )}
          {!preview && !previewError && <p>{c.previewLoading}</p>}
          {preview && <Preview preview={preview} />}
        </div>
      )}
    </div>
  );
}

/**
 * The verdict, in the server's own words. A pass is a `status`; anything
 * else is an `alert` — loud by role, by heading, by icon and by text, so it
 * survives a monochrome print-out and a screen reader alike.
 */
function Verdict({ verdict }: { verdict: RawRecordVerdict }) {
  const matched = verdict.result === "match";
  const heading = matched
    ? c.verdictMatch
    : verdict.result === "mismatch"
      ? c.verdictMismatch
      : verdict.result === "missing"
        ? c.verdictMissing
        : c.verdictUnavailable;

  return (
    <div
      role={matched ? "status" : "alert"}
      className={`raw-record-verdict raw-record-verdict-${matched ? "match" : "fail"}`}
    >
      <p className="raw-record-verdict-headline">
        <svg aria-hidden="true" width={16} height={16} viewBox="0 0 16 16" fill="currentColor">
          {matched ? (
            <path d="M6.2 11.4 2.8 8l1.2-1.2 2.2 2.2 5.8-5.8L13.2 4.4z" />
          ) : (
            <path d="M8 1 15 14H1zM7.2 6h1.6v4H7.2zm0 5h1.6v1.6H7.2z" />
          )}
        </svg>
        <strong>{heading}</strong> — {verdict.headline}
      </p>
      <p>{verdict.detail}</p>
      <dl className="raw-record-digests">
        <dt>{c.verdictExpected}</dt>
        <dd>
          <code>{verdict.expected_digest}</code>
        </dd>
        <dt>{c.verdictActual}</dt>
        <dd>
          {verdict.actual_digest ? (
            <code>{verdict.actual_digest}</code>
          ) : (
            <em>{c.absent}</em>
          )}
        </dd>
      </dl>
      {verdict.dq_issue_id && (
        <p className="raw-record-verdict-issue">
          {c.verdictIssue(verdict.dq_issue_id)}{" "}
          <a href={`/dq/issues/${verdict.dq_issue_id}`}>{c.verdictIssueLink}</a>
        </p>
      )}
      <p className="raw-record-verdict-when">
        {c.verifiedAt(formatWhen(verdict.verified_at))}
      </p>
    </div>
  );
}

function Preview({ preview }: { preview: RawRecordPreview }) {
  return (
    /* A labelled region rather than a heading: this component is embedded
       inside a lineage tree at a depth the page owns, so inventing a heading
       level here would break the document outline (axe heading-order). */
    <section aria-label={c.previewHeading}>
      <p className="raw-record-preview-heading">
        <strong>{c.previewHeading}</strong>
      </p>
      {/* The cap is stated before the data, never after it. */}
      {preview.truncation_note && (
        <p className="raw-record-cap">{preview.truncation_note}</p>
      )}
      {preview.gtfs_realtime && <GtfsRealtime feed={preview.gtfs_realtime} />}
      {preview.delimited && (
        <>
          {preview.delimited.note && <p>{preview.delimited.note}</p>}
          {preview.delimited.readable && (
            <div className="table-wrap">
              <table>
                <caption>{c.rowsHeading}</caption>
                <thead>
                  <tr>
                    {(preview.delimited.header ?? []).map((h, i) => (
                      <th key={`${h}:${i}`} scope="col">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.delimited.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {preview.text && (
        <>
          {preview.text.note && <p>{preview.text.note}</p>}
          {preview.text.readable && (
            <>
              <p className="raw-record-preview-heading">
                <strong>{c.linesHeading}</strong>
              </p>
              <pre className="raw-record-lines" aria-label={c.linesHeading}>
                {preview.text.lines.join("\n")}
              </pre>
            </>
          )}
        </>
      )}
      {preview.undecoded && (
        <div className="banner">
          <p>
            <strong>{c.undecodedHeading}</strong> —{" "}
            {preview.undecoded.content_type}
          </p>
          <p>{preview.undecoded.reason}</p>
        </div>
      )}
      <p className="raw-record-download-note">{preview.download_note}</p>
    </section>
  );
}

/**
 * The moment the whole wave exists for: a steward's own bus, at that minute,
 * at those coordinates, decoded from the record's own bytes.
 */
function GtfsRealtime({
  feed,
}: {
  feed: NonNullable<RawRecordPreview["gtfs_realtime"]>;
}) {
  if (!feed.decoded) {
    return (
      <div role="alert" className="alert">
        {feed.decode_error}
      </div>
    );
  }
  return (
    <>
      <dl className="raw-record-label">
        <Field label={c.feedVersion} value={feed.gtfs_realtime_version} />
        <Field label={c.feedIncrementality} value={feed.incrementality} />
        <Field
          label={c.feedTimestamp}
          value={
            feed.header_timestamp_utc
              ? formatWhen(feed.header_timestamp_utc)
              : null
          }
        />
        <Field
          label={c.feedEntities}
          value={(feed.entity_count ?? 0).toLocaleString()}
        />
      </dl>
      <div className="table-wrap">
        <table>
          <caption>{c.entitiesHeading}</caption>
          <thead>
            <tr>
              <th scope="col">{c.entityVehicle}</th>
              <th scope="col">{c.entityRoute}</th>
              <th scope="col">{c.entityTrip}</th>
              <th scope="col">{c.entityPosition}</th>
              <th scope="col">{c.entityTime}</th>
              <th scope="col">{c.entityStatus}</th>
            </tr>
          </thead>
          <tbody>
            {(feed.entities ?? []).map((entity, i) => (
              <EntityRow key={`${entity.entity_id ?? i}`} entity={entity} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function EntityRow({ entity }: { entity: GtfsRealtimeEntity }) {
  const absent = <em>{c.absent}</em>;
  const position =
    entity.latitude !== null && entity.latitude !== undefined
      ? `${entity.latitude.toFixed(5)}, ${entity.longitude?.toFixed(5)}`
      : null;
  const status =
    entity.kind === "trip_update"
      ? `${c.entityStopUpdates}: ${entity.stop_time_update_count ?? 0}`
      : entity.kind === "alert"
        ? `${c.entityAlert}: ${entity.effect ?? ""} ${entity.header_text ?? ""}`.trim()
        : entity.current_status;
  return (
    <tr>
      <td>{entity.vehicle_label ?? entity.vehicle_id ?? entity.entity_id ?? absent}</td>
      <td>{entity.route_id ?? absent}</td>
      <td>{entity.trip_id ?? absent}</td>
      <td>{position ?? absent}</td>
      <td>{entity.timestamp_utc ? formatWhen(entity.timestamp_utc) : absent}</td>
      <td>{status ?? absent}</td>
    </tr>
  );
}
