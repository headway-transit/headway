/**
 * Compact server-export control (handoff 0017, design point 5): one CSV and
 * one XLSX button for a surface's export endpoint. The API assembles BOTH
 * formats from one row grid (XLSX cells are text holding the byte-identical
 * CSV strings), and the saved file is the response body byte for byte.
 *
 * Success is confirmed through the shell's toast region (role="log",
 * deterministic lifetime), naming the saved file; an API refusal is shown
 * verbatim in a local alert. Buttons carry a visually-hidden surface name so
 * several export controls on one page stay uniquely labeled.
 */

import { useState } from "react";
import { ApiError } from "../api/client";
import type { ExportDownload, ExportFormat } from "../api/client";
import { copy } from "../copy";
import { saveBlob } from "../download";
import { pushToast } from "../toasts";

export function ExportButtons({
  label,
  download,
  note,
}: {
  /** Names the surface: the group's accessible name and each button's
   *  visually-hidden suffix. */
  label: string;
  /** Fetches one export in the pressed format (see api/client.ts). */
  download: (format: ExportFormat) => Promise<ExportDownload>;
  /** Optional always-visible hint stating exactly what the file covers. */
  note?: string;
}) {
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleDownload = async (format: ExportFormat) => {
    setBusy(format);
    setError(null);
    try {
      const file = await download(format);
      // Saved byte for byte; the server's attachment filename wins.
      saveBlob(file.blob, file.filename);
      pushToast(copy.exports.toast(file.filename));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="export-control" role="group" aria-label={label}>
      <button
        type="button"
        disabled={busy !== null}
        onClick={() => void handleDownload("csv")}
      >
        {copy.exports.csvButton}
        <span className="visually-hidden"> — {label}</span>
      </button>
      <button
        type="button"
        disabled={busy !== null}
        onClick={() => void handleDownload("xlsx")}
      >
        {copy.exports.xlsxButton}
        <span className="visually-hidden"> — {label}</span>
      </button>
      {note && <p className="field-hint">{note}</p>}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  );
}
