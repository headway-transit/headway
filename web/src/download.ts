/**
 * The one file-save helper: hand the browser a Blob under a filename via a
 * temporary object URL. The Blob is saved byte for byte — nothing here
 * reads, parses, or re-encodes it (the MR-20 JSON download and every
 * CSV/XLSX export lean on that).
 */

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
